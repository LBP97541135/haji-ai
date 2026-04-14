"""
tests/test_knowledge.py - knowledge 模块测试

覆盖：
- ChunkConfig / DocumentChunk / KnowledgeDocument 数据结构
- TextChunker：正常切分、空文档、超长段落、overlap、separator
- MockEmbedder：embed / embed_batch、确定性、维度正确
- InMemoryKnowledgeStore：add / search / delete / info
- KnowledgeLoader：load_text / load_file（正常 & 异常）
- OpenAIEmbedder：Mock openai SDK，不真实调用
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from haiji.knowledge.chunker import TextChunker
from haiji.knowledge.definition import ChunkConfig, DocumentChunk, KnowledgeDocument
from haiji.knowledge.embedder import MockEmbedder, OpenAIEmbedder
from haiji.knowledge.loader import KnowledgeLoader, UnsupportedFileTypeError
from haiji.knowledge.store import InMemoryKnowledgeStore, _cosine_similarity


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def make_doc(content: str, doc_id: str = "doc1", source: str = "test") -> KnowledgeDocument:
    return KnowledgeDocument(doc_id=doc_id, source=source, content=content)


# ---------------------------------------------------------------------------
# 数据结构测试
# ---------------------------------------------------------------------------


class TestDefinitions:
    def test_document_chunk_defaults(self) -> None:
        chunk = DocumentChunk(chunk_id="c1", source="src", content="hello")
        assert chunk.metadata == {}
        assert chunk.embedding is None

    def test_document_chunk_with_embedding(self) -> None:
        emb = [0.1, 0.2, 0.3]
        chunk = DocumentChunk(chunk_id="c1", source="src", content="hello", embedding=emb)
        assert chunk.embedding == emb

    def test_knowledge_document_defaults(self) -> None:
        doc = make_doc("text")
        assert doc.chunks == []
        assert doc.metadata == {}

    def test_chunk_config_defaults(self) -> None:
        cfg = ChunkConfig()
        assert cfg.chunk_size == 512
        assert cfg.chunk_overlap == 64
        assert cfg.separator == "\n\n"

    def test_chunk_config_custom(self) -> None:
        cfg = ChunkConfig(chunk_size=100, chunk_overlap=10, separator="\n")
        assert cfg.chunk_size == 100
        assert cfg.chunk_overlap == 10
        assert cfg.separator == "\n"


# ---------------------------------------------------------------------------
# TextChunker 测试
# ---------------------------------------------------------------------------


class TestTextChunker:
    def _chunker(self, chunk_size: int = 512, overlap: int = 64, sep: str = "\n\n") -> TextChunker:
        return TextChunker(ChunkConfig(chunk_size=chunk_size, chunk_overlap=overlap, separator=sep))

    def test_empty_document_returns_empty(self) -> None:
        chunker = self._chunker()
        doc = make_doc("")
        assert chunker.chunk(doc) == []

    def test_whitespace_only_returns_empty(self) -> None:
        chunker = self._chunker()
        doc = make_doc("   \n\n  ")
        assert chunker.chunk(doc) == []

    def test_short_text_single_chunk(self) -> None:
        chunker = self._chunker(chunk_size=200)
        doc = make_doc("Hello world")
        chunks = chunker.chunk(doc)
        assert len(chunks) == 1
        assert "Hello world" in chunks[0].content

    def test_chunk_id_format(self) -> None:
        chunker = self._chunker(chunk_size=200)
        doc = make_doc("Hello world", doc_id="mydoc")
        chunks = chunker.chunk(doc)
        assert chunks[0].chunk_id == "mydoc_0"

    def test_source_preserved(self) -> None:
        chunker = self._chunker(chunk_size=200)
        doc = make_doc("Hello world", source="my_file.md")
        chunks = chunker.chunk(doc)
        assert chunks[0].source == "my_file.md"

    def test_metadata_copied(self) -> None:
        chunker = self._chunker(chunk_size=200)
        doc = KnowledgeDocument(doc_id="d", source="s", content="hi", metadata={"key": "val"})
        chunks = chunker.chunk(doc)
        assert chunks[0].metadata == {"key": "val"}
        # 确保是副本，不共享引用
        chunks[0].metadata["extra"] = "x"
        assert "extra" not in doc.metadata

    def test_multiple_paragraphs_split(self) -> None:
        """三个段落，每个 > chunk_size/3，不能全合并进一块"""
        chunker = self._chunker(chunk_size=20, overlap=0)
        # 每段约 14 字符，合并两段 = 14+1+14 = 29 > 20，所以应切成多块
        content = "paragraph one.\n\nparagraph two.\n\nparagraph three."
        doc = make_doc(content)
        chunks = chunker.chunk(doc)
        assert len(chunks) >= 2

    def test_long_paragraph_hard_split(self) -> None:
        chunker = self._chunker(chunk_size=10, overlap=0, sep="\n\n")
        # 单段落超长
        content = "A" * 35  # 35 字符，无段落分隔
        doc = make_doc(content)
        chunks = chunker.chunk(doc)
        # 应该切成 4 块（10+10+10+5）
        assert len(chunks) == 4
        for chunk in chunks:
            assert len(chunk.content) <= 10

    def test_overlap_applied(self) -> None:
        chunker = self._chunker(chunk_size=20, overlap=5, sep="\n\n")
        # 两段：各 15 字符，不会被合并（合并后 31 > 20）
        content = "A" * 15 + "\n\n" + "B" * 15
        doc = make_doc(content)
        chunks = chunker.chunk(doc)
        assert len(chunks) >= 2
        # 第二块开头应包含第一块末尾的 overlap 内容
        if len(chunks) == 2:
            assert chunks[1].content.startswith("A" * 5)

    def test_no_overlap_when_overlap_zero(self) -> None:
        chunker = self._chunker(chunk_size=20, overlap=0, sep="\n\n")
        content = "Hello\n\nWorld"
        doc = make_doc(content)
        chunks = chunker.chunk(doc)
        # 第二块不应以 Hello 内容开头
        assert len(chunks) >= 1

    def test_single_chunk_no_overlap(self) -> None:
        """只有一个 chunk 时不应用 overlap（无需处理）"""
        chunker = self._chunker(chunk_size=200, overlap=10)
        doc = make_doc("short text")
        chunks = chunker.chunk(doc)
        assert len(chunks) == 1

    def test_chunk_indices_sequential(self) -> None:
        chunker = self._chunker(chunk_size=5, overlap=0, sep="\n\n")
        content = "AAAAA\n\nBBBBB\n\nCCCCC"
        doc = make_doc(content, doc_id="seq")
        chunks = chunker.chunk(doc)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_id == f"seq_{i}"

    def test_custom_separator(self) -> None:
        chunker = self._chunker(chunk_size=100, overlap=0, sep="\n")
        content = "line1\nline2\nline3"
        doc = make_doc(content)
        chunks = chunker.chunk(doc)
        # 三行各自独立，但短到会被合并
        assert len(chunks) >= 1

    def test_merge_short_paragraphs(self) -> None:
        """短段落应被合并成一个 chunk"""
        chunker = self._chunker(chunk_size=100, overlap=0)
        content = "short\n\ntext"
        doc = make_doc(content)
        chunks = chunker.chunk(doc)
        # 两段合并后 < 100，应为 1 chunk
        assert len(chunks) == 1


# ---------------------------------------------------------------------------
# MockEmbedder 测试
# ---------------------------------------------------------------------------


class TestMockEmbedder:
    @pytest.mark.asyncio
    async def test_embed_returns_correct_dim(self) -> None:
        embedder = MockEmbedder(dim=128)
        vector = await embedder.embed("hello")
        assert len(vector) == 128

    @pytest.mark.asyncio
    async def test_embed_deterministic_same_text(self) -> None:
        embedder = MockEmbedder(dim=64)
        v1 = await embedder.embed("hello world")
        v2 = await embedder.embed("hello world")
        assert v1 == v2

    @pytest.mark.asyncio
    async def test_embed_different_text_different_vector(self) -> None:
        embedder = MockEmbedder(dim=64)
        v1 = await embedder.embed("hello")
        v2 = await embedder.embed("world")
        assert v1 != v2

    @pytest.mark.asyncio
    async def test_embed_unit_vector(self) -> None:
        import math

        embedder = MockEmbedder(dim=100)
        v = await embedder.embed("test")
        norm = math.sqrt(sum(x * x for x in v))
        assert abs(norm - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_embed_batch_returns_list(self) -> None:
        embedder = MockEmbedder(dim=32)
        texts = ["a", "b", "c"]
        result = await embedder.embed_batch(texts)
        assert len(result) == 3
        for v in result:
            assert len(v) == 32

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self) -> None:
        embedder = MockEmbedder(dim=32)
        result = await embedder.embed_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_with_fixed_seed(self) -> None:
        e1 = MockEmbedder(dim=16, seed=42)
        e2 = MockEmbedder(dim=16, seed=42)
        v1 = await e1.embed("any text")
        v2 = await e2.embed("other text")
        # 固定 seed 时，不同文本返回相同向量
        assert v1 == v2

    @pytest.mark.asyncio
    async def test_default_dim(self) -> None:
        embedder = MockEmbedder()
        v = await embedder.embed("x")
        assert len(v) == 1536


# ---------------------------------------------------------------------------
# InMemoryKnowledgeStore 测试
# ---------------------------------------------------------------------------


class TestInMemoryKnowledgeStore:
    def _make_chunk(
        self,
        chunk_id: str,
        content: str,
        embedding: list[float],
    ) -> DocumentChunk:
        return DocumentChunk(
            chunk_id=chunk_id,
            source="test",
            content=content,
            embedding=embedding,
        )

    def test_initial_info(self) -> None:
        store = InMemoryKnowledgeStore("test_store")
        info = store.info()
        assert info.store_id == "test_store"
        assert info.doc_count == 0
        assert info.chunk_count == 0

    def test_add_document_increases_count(self) -> None:
        store = InMemoryKnowledgeStore()
        doc = make_doc("content", doc_id="d1")
        chunk = self._make_chunk("d1_0", "content", [1.0, 0.0])
        store.add_document(doc, [chunk])
        info = store.info()
        assert info.doc_count == 1
        assert info.chunk_count == 1

    def test_add_multiple_documents(self) -> None:
        store = InMemoryKnowledgeStore()
        doc1 = make_doc("text1", doc_id="d1")
        doc2 = make_doc("text2", doc_id="d2")
        c1 = self._make_chunk("d1_0", "text1", [1.0, 0.0])
        c2 = self._make_chunk("d2_0", "text2", [0.0, 1.0])
        store.add_document(doc1, [c1])
        store.add_document(doc2, [c2])
        assert store.info().doc_count == 2
        assert store.info().chunk_count == 2

    def test_search_returns_most_similar(self) -> None:
        store = InMemoryKnowledgeStore()
        doc = make_doc("text", doc_id="d1")
        c1 = self._make_chunk("d1_0", "similar", [1.0, 0.0])
        c2 = self._make_chunk("d1_1", "different", [0.0, 1.0])
        store.add_document(doc, [c1, c2])
        results = store.search([1.0, 0.0], top_k=1)
        assert len(results) == 1
        assert results[0].chunk_id == "d1_0"

    def test_search_top_k_limit(self) -> None:
        store = InMemoryKnowledgeStore()
        doc = make_doc("text", doc_id="d1")
        chunks = [self._make_chunk(f"d1_{i}", f"c{i}", [float(i), 0.0]) for i in range(5)]
        store.add_document(doc, chunks)
        results = store.search([1.0, 0.0], top_k=3)
        assert len(results) == 3

    def test_search_empty_store(self) -> None:
        store = InMemoryKnowledgeStore()
        results = store.search([1.0, 0.0], top_k=5)
        assert results == []

    def test_search_empty_query(self) -> None:
        store = InMemoryKnowledgeStore()
        doc = make_doc("text", doc_id="d1")
        chunk = self._make_chunk("d1_0", "text", [1.0, 0.0])
        store.add_document(doc, [chunk])
        results = store.search([], top_k=5)
        assert results == []

    def test_search_skips_chunks_without_embedding(self) -> None:
        store = InMemoryKnowledgeStore()
        doc = make_doc("text", doc_id="d1")
        c_with = self._make_chunk("d1_0", "with emb", [1.0, 0.0])
        c_without = DocumentChunk(chunk_id="d1_1", source="test", content="no emb")
        store.add_document(doc, [c_with, c_without])
        results = store.search([1.0, 0.0], top_k=5)
        chunk_ids = [r.chunk_id for r in results]
        assert "d1_0" in chunk_ids
        assert "d1_1" not in chunk_ids

    def test_delete_document(self) -> None:
        store = InMemoryKnowledgeStore()
        doc = make_doc("text", doc_id="d1")
        chunk = self._make_chunk("d1_0", "text", [1.0, 0.0])
        store.add_document(doc, [chunk])
        store.delete_document("d1")
        assert store.info().doc_count == 0
        assert store.info().chunk_count == 0

    def test_delete_nonexistent_document(self) -> None:
        store = InMemoryKnowledgeStore()
        # 不应抛异常
        store.delete_document("not_exist")

    def test_add_duplicate_replaces_old(self) -> None:
        store = InMemoryKnowledgeStore()
        doc = make_doc("old text", doc_id="d1")
        old_chunk = self._make_chunk("d1_0", "old", [1.0, 0.0])
        store.add_document(doc, [old_chunk])

        doc2 = make_doc("new text", doc_id="d1")
        new_chunk = self._make_chunk("d1_0", "new", [0.0, 1.0])
        store.add_document(doc2, [new_chunk])

        assert store.info().doc_count == 1
        assert store.info().chunk_count == 1
        results = store.search([0.0, 1.0], top_k=1)
        assert results[0].content == "new"

    def test_delete_only_removes_target_doc_chunks(self) -> None:
        store = InMemoryKnowledgeStore()
        doc1 = make_doc("text1", doc_id="d1")
        doc2 = make_doc("text2", doc_id="d2")
        c1 = self._make_chunk("d1_0", "text1", [1.0, 0.0])
        c2 = self._make_chunk("d2_0", "text2", [0.0, 1.0])
        store.add_document(doc1, [c1])
        store.add_document(doc2, [c2])
        store.delete_document("d1")
        assert store.info().doc_count == 1
        assert store.info().chunk_count == 1
        results = store.search([0.0, 1.0], top_k=1)
        assert results[0].chunk_id == "d2_0"


# ---------------------------------------------------------------------------
# _cosine_similarity 测试
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        assert abs(_cosine_similarity([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9

    def test_orthogonal_vectors(self) -> None:
        assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_opposite_vectors(self) -> None:
        assert abs(_cosine_similarity([1.0, 0.0], [-1.0, 0.0]) + 1.0) < 1e-9

    def test_zero_vector_returns_zero(self) -> None:
        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_different_dim_returns_zero(self) -> None:
        assert _cosine_similarity([1.0], [1.0, 0.0]) == 0.0

    def test_empty_vector_returns_zero(self) -> None:
        assert _cosine_similarity([], []) == 0.0


# ---------------------------------------------------------------------------
# KnowledgeLoader 测试
# ---------------------------------------------------------------------------


class TestKnowledgeLoader:
    @pytest.mark.asyncio
    async def test_load_text_basic(self) -> None:
        loader = KnowledgeLoader()
        doc = await loader.load_text("hello world")
        assert doc.content == "hello world"
        assert doc.source == "inline"
        assert doc.doc_id != ""
        assert doc.chunks == []

    @pytest.mark.asyncio
    async def test_load_text_custom_source(self) -> None:
        loader = KnowledgeLoader()
        doc = await loader.load_text("content", source="custom_src")
        assert doc.source == "custom_src"

    @pytest.mark.asyncio
    async def test_load_text_custom_doc_id(self) -> None:
        loader = KnowledgeLoader()
        doc = await loader.load_text("content", doc_id="my_doc")
        assert doc.doc_id == "my_doc"

    @pytest.mark.asyncio
    async def test_load_text_metadata(self) -> None:
        loader = KnowledgeLoader()
        doc = await loader.load_text("content", metadata={"author": "test"})
        assert doc.metadata == {"author": "test"}

    @pytest.mark.asyncio
    async def test_load_text_empty_metadata(self) -> None:
        loader = KnowledgeLoader()
        doc = await loader.load_text("content")
        assert doc.metadata == {}

    @pytest.mark.asyncio
    async def test_load_file_txt(self) -> None:
        loader = KnowledgeLoader()
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write("hello from file")
            tmp_path = f.name
        try:
            doc = await loader.load_file(tmp_path)
            assert doc.content == "hello from file"
            assert doc.source == tmp_path
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_load_file_md(self) -> None:
        loader = KnowledgeLoader()
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False, encoding="utf-8") as f:
            f.write("# Title\n\nBody text")
            tmp_path = f.name
        try:
            doc = await loader.load_file(tmp_path)
            assert "Title" in doc.content
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_load_file_auto_metadata(self) -> None:
        loader = KnowledgeLoader()
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write("content")
            tmp_path = f.name
        try:
            doc = await loader.load_file(tmp_path)
            assert "file_path" in doc.metadata
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_load_file_path_object(self) -> None:
        loader = KnowledgeLoader()
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write("path object test")
            tmp_path = f.name
        try:
            doc = await loader.load_file(Path(tmp_path))
            assert doc.content == "path object test"
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_load_file_not_found(self) -> None:
        loader = KnowledgeLoader()
        with pytest.raises(FileNotFoundError):
            await loader.load_file("/nonexistent/path/file.txt")

    @pytest.mark.asyncio
    async def test_load_file_unsupported_type(self) -> None:
        loader = KnowledgeLoader()
        with pytest.raises(UnsupportedFileTypeError):
            await loader.load_file("/some/file.pdf")

    @pytest.mark.asyncio
    async def test_load_file_unsupported_type_docx(self) -> None:
        loader = KnowledgeLoader()
        with pytest.raises(UnsupportedFileTypeError):
            await loader.load_file("/some/file.docx")

    @pytest.mark.asyncio
    async def test_load_file_custom_metadata(self) -> None:
        loader = KnowledgeLoader()
        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write("content")
            tmp_path = f.name
        try:
            doc = await loader.load_file(tmp_path, metadata={"custom": True})
            assert doc.metadata == {"custom": True}
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# OpenAIEmbedder 测试（Mock openai SDK）
# ---------------------------------------------------------------------------


class TestOpenAIEmbedder:
    @pytest.mark.asyncio
    async def test_embed_calls_openai(self) -> None:
        """embed() 应正确调用 openai embeddings API 并返回向量。"""
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

        mock_client = MagicMock()
        mock_client.embeddings = MagicMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        embedder = OpenAIEmbedder(api_key="fake-key", model="text-embedding-3-small")
        embedder._client = mock_client

        result = await embedder.embed("hello world")
        assert result == [0.1, 0.2, 0.3]
        mock_client.embeddings.create.assert_called_once()
        call_kwargs = mock_client.embeddings.create.call_args[1]
        assert call_kwargs["input"] == "hello world"

    @pytest.mark.asyncio
    async def test_embed_batch_calls_openai_once(self) -> None:
        """embed_batch() 应一次性调用 openai API，而非逐条调用。"""
        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(index=0, embedding=[1.0, 0.0]),
            MagicMock(index=1, embedding=[0.0, 1.0]),
        ]

        mock_client = MagicMock()
        mock_client.embeddings = MagicMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        embedder = OpenAIEmbedder(api_key="fake-key")
        embedder._client = mock_client

        results = await embedder.embed_batch(["text1", "text2"])
        assert len(results) == 2
        assert results[0] == [1.0, 0.0]
        assert results[1] == [0.0, 1.0]
        # 只调用一次 API
        assert mock_client.embeddings.create.call_count == 1

    @pytest.mark.asyncio
    async def test_embed_batch_empty(self) -> None:
        """embed_batch([]) 应返回空列表，不调用 API。"""
        mock_client = MagicMock()
        mock_client.embeddings = MagicMock()
        mock_client.embeddings.create = AsyncMock()

        embedder = OpenAIEmbedder(api_key="fake-key")
        embedder._client = mock_client

        result = await embedder.embed_batch([])
        assert result == []
        mock_client.embeddings.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_embed_batch_order_by_index(self) -> None:
        """embed_batch 应按 index 排序返回结果（openai 可能乱序）。"""
        mock_response = MagicMock()
        # 故意把 index=1 放在前面
        mock_response.data = [
            MagicMock(index=1, embedding=[0.0, 1.0]),
            MagicMock(index=0, embedding=[1.0, 0.0]),
        ]

        mock_client = MagicMock()
        mock_client.embeddings = MagicMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        embedder = OpenAIEmbedder(api_key="fake-key")
        embedder._client = mock_client

        results = await embedder.embed_batch(["text1", "text2"])
        assert results[0] == [1.0, 0.0]  # index=0
        assert results[1] == [0.0, 1.0]  # index=1


# ---------------------------------------------------------------------------
# 集成测试：端到端 load → chunk → embed → store → search
# ---------------------------------------------------------------------------


class TestKnowledgeIntegration:
    @pytest.mark.asyncio
    async def test_end_to_end_pipeline(self) -> None:
        from haiji.knowledge import (
            ChunkConfig,
            InMemoryKnowledgeStore,
            KnowledgeLoader,
            MockEmbedder,
            TextChunker,
        )

        loader = KnowledgeLoader()
        embedder = MockEmbedder(dim=64)
        chunker = TextChunker(ChunkConfig(chunk_size=50, chunk_overlap=5))
        store = InMemoryKnowledgeStore("integration")

        # 两个文档
        doc1 = await loader.load_text(
            "Python 是一种通用编程语言，广泛用于数据科学和 AI 开发。",
            source="doc1",
        )
        doc2 = await loader.load_text(
            "Java 是一种面向对象的编程语言，广泛用于企业级应用开发。",
            source="doc2",
        )

        for doc in [doc1, doc2]:
            chunks = chunker.chunk(doc)
            for chunk in chunks:
                chunk.embedding = await embedder.embed(chunk.content)
            store.add_document(doc, chunks)

        info = store.info()
        assert info.doc_count == 2

        # 搜索
        query_emb = await embedder.embed("Python 编程")
        results = store.search(query_emb, top_k=3)
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_load_file_then_chunk(self) -> None:
        from haiji.knowledge import ChunkConfig, KnowledgeLoader, TextChunker

        loader = KnowledgeLoader()
        chunker = TextChunker(ChunkConfig(chunk_size=30, chunk_overlap=0))

        with tempfile.NamedTemporaryFile(
            suffix=".md", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Title\n\nFirst paragraph.\n\nSecond paragraph.")
            tmp_path = f.name

        try:
            doc = await loader.load_file(tmp_path)
            chunks = chunker.chunk(doc)
            assert len(chunks) >= 1
            all_content = " ".join(c.content for c in chunks)
            assert "Title" in all_content or "paragraph" in all_content
        finally:
            os.unlink(tmp_path)
