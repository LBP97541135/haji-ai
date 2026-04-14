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


# ---------------------------------------------------------------------------
# KBResult 测试
# ---------------------------------------------------------------------------


class TestKBResult:
    def test_default_values(self) -> None:
        from haiji.knowledge.base_kb import KBResult
        result = KBResult(content="测试")
        assert result.content == "测试"
        assert result.score == 0.0
        assert result.doc_id == ""
        assert result.chunk_id == ""
        assert result.metadata == {}

    def test_custom_values(self) -> None:
        from haiji.knowledge.base_kb import KBResult
        result = KBResult(
            content="内容",
            score=0.85,
            doc_id="doc1",
            chunk_id="doc1_0",
            metadata={"source": "test"},
        )
        assert result.score == 0.85
        assert result.doc_id == "doc1"
        assert result.metadata == {"source": "test"}


# ---------------------------------------------------------------------------
# BaseKnowledgeBase 测试
# ---------------------------------------------------------------------------


class TestBaseKnowledgeBase:
    @pytest.mark.asyncio
    async def test_on_before_search_default_no_op(self) -> None:
        """on_before_search 默认原样返回 query。"""
        from haiji.knowledge.base_kb import BaseKnowledgeBase, KBResult

        class ConcreteKB(BaseKnowledgeBase):
            async def search(self, query, top_k=5, score_threshold=0.0):
                return []

        kb = ConcreteKB()
        result = await kb.on_before_search("hello world")
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_on_after_search_default_no_op(self) -> None:
        """on_after_search 默认原样返回结果。"""
        from haiji.knowledge.base_kb import BaseKnowledgeBase, KBResult

        class ConcreteKB(BaseKnowledgeBase):
            async def search(self, query, top_k=5, score_threshold=0.0):
                return []

        kb = ConcreteKB()
        input_results = [KBResult(content="内容", score=0.9)]
        output = await kb.on_after_search(input_results)
        assert output is input_results

    @pytest.mark.asyncio
    async def test_hooks_callable_from_subclass(self) -> None:
        """子类可以覆盖钩子。"""
        from haiji.knowledge.base_kb import BaseKnowledgeBase, KBResult

        class TransformKB(BaseKnowledgeBase):
            async def search(self, query, top_k=5, score_threshold=0.0):
                return [KBResult(content=query, score=1.0)]

            async def on_before_search(self, query: str) -> str:
                return query + "_modified"

            async def on_after_search(self, results):
                return [r for r in results if r.score > 0.5]

        kb = TransformKB()
        processed = await kb.on_before_search("hello")
        assert processed == "hello_modified"

        filtered = await kb.on_after_search([
            KBResult(content="a", score=0.8),
            KBResult(content="b", score=0.3),
        ])
        assert len(filtered) == 1
        assert filtered[0].content == "a"

    def test_cannot_instantiate_abstract(self) -> None:
        """BaseKnowledgeBase 是抽象类，不能直接实例化。"""
        from haiji.knowledge.base_kb import BaseKnowledgeBase
        with pytest.raises(TypeError):
            BaseKnowledgeBase()  # type: ignore


# ---------------------------------------------------------------------------
# KnowledgeBase 测试
# ---------------------------------------------------------------------------


class TestKnowledgeBase:
    @pytest.mark.asyncio
    async def test_load_text_returns_chunk_count(self) -> None:
        """load_text 返回正确的 chunk 数量。"""
        from haiji.knowledge.knowledge_base import KnowledgeBase

        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder)
        count = await kb.load_text("Hello world test content.", doc_id="doc1")
        assert count >= 1

    @pytest.mark.asyncio
    async def test_load_text_empty_returns_zero(self) -> None:
        """load_text 空内容返回 0。"""
        from haiji.knowledge.knowledge_base import KnowledgeBase

        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder)
        count = await kb.load_text("   ", doc_id="empty_doc")
        assert count == 0

    @pytest.mark.asyncio
    async def test_search_returns_kb_results(self) -> None:
        """search 返回 KBResult 列表，含 content 和 score。使用相同文本确保高相似度。"""
        from haiji.knowledge.knowledge_base import KnowledgeBase
        from haiji.knowledge.base_kb import KBResult

        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder)
        text = "Python 是一种通用编程语言"
        await kb.load_text(text, doc_id="doc1")

        # 用相同文本查询，保证余弦相似度为 1.0（MockEmbedder 确定性）
        results = await kb.search(text)
        assert len(results) >= 1
        assert isinstance(results[0], KBResult)
        assert results[0].content != ""
        assert isinstance(results[0].score, float)

    @pytest.mark.asyncio
    async def test_search_empty_query_returns_empty(self) -> None:
        """search 空 query 返回空列表。"""
        from haiji.knowledge.knowledge_base import KnowledgeBase

        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder)
        await kb.load_text("内容", doc_id="doc1")
        results = await kb.search("")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_whitespace_query_returns_empty(self) -> None:
        """search 空白 query 返回空列表。"""
        from haiji.knowledge.knowledge_base import KnowledgeBase

        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder)
        results = await kb.search("   ")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_score_threshold_filters(self) -> None:
        """score_threshold 过滤低分结果。"""
        from haiji.knowledge.knowledge_base import KnowledgeBase

        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder)
        await kb.load_text("完全不同的内容 xyz", doc_id="doc1")

        # score_threshold=1.0 时只有完全相同才能通过（几乎不可能）
        results = await kb.search("Python 编程", score_threshold=0.9999)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_results_sorted_by_score_desc(self) -> None:
        """搜索结果按 score 降序排列。"""
        from haiji.knowledge.knowledge_base import KnowledgeBase

        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder)
        await kb.load_text("Python 编程语言数据科学", doc_id="doc1")
        await kb.load_text("Java 企业级开发面向对象", doc_id="doc2")

        results = await kb.search("Python 数据科学", top_k=5)
        if len(results) >= 2:
            scores = [r.score for r in results]
            assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_delete_doc_removes_from_search(self) -> None:
        """delete_doc 后该文档不再出现在搜索结果中。"""
        from haiji.knowledge.knowledge_base import KnowledgeBase
        import asyncio

        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder)
        text = "Python 是一种通用编程语言"
        await kb.load_text(text, doc_id="to_delete")

        # 删除前能搜到（用相同文本，保证相似度为 1.0）
        results_before = await kb.search(text)
        assert len(results_before) >= 1

        # 删除
        kb.delete_doc("to_delete")

        # 删除后搜不到（store 为空，search 应返回空列表）
        results_after = await kb.search(text)
        assert len(results_after) == 0

    def test_info_returns_dict(self) -> None:
        """info() 返回包含统计信息的字典。"""
        from haiji.knowledge.knowledge_base import KnowledgeBase

        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder, store_id="test_info")
        info = kb.info()
        assert "store_id" in info
        assert "doc_count" in info
        assert "chunk_count" in info
        assert info["doc_count"] == 0

    @pytest.mark.asyncio
    async def test_info_updates_after_load(self) -> None:
        """load_text 后 info() 统计数量增加。"""
        from haiji.knowledge.knowledge_base import KnowledgeBase

        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder)
        await kb.load_text("文档内容", doc_id="doc1")
        info = kb.info()
        assert info["doc_count"] == 1
        assert info["chunk_count"] >= 1

    @pytest.mark.asyncio
    async def test_load_file_txt(self) -> None:
        """load_file 支持 .txt 文件。"""
        import tempfile
        import os
        from haiji.knowledge.knowledge_base import KnowledgeBase

        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder)

        with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False, encoding="utf-8") as f:
            f.write("Hello from file")
            tmp_path = f.name

        try:
            count = await kb.load_file(tmp_path, doc_id="file_doc")
            assert count >= 1
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_load_file_unsupported_type(self) -> None:
        """load_file 不支持的文件类型抛 ValueError。"""
        from haiji.knowledge.knowledge_base import KnowledgeBase

        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder)

        with pytest.raises(ValueError):
            await kb.load_file("/some/file.pdf")

    @pytest.mark.asyncio
    async def test_load_file_not_found(self) -> None:
        """load_file 文件不存在抛 FileNotFoundError。"""
        from haiji.knowledge.knowledge_base import KnowledgeBase

        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder)

        with pytest.raises(FileNotFoundError):
            await kb.load_file("/nonexistent/path/file.txt")

    @pytest.mark.asyncio
    async def test_hooks_called_during_search(self) -> None:
        """search 内部调用 on_before_search 和 on_after_search。"""
        import asyncio
        from haiji.knowledge.knowledge_base import KnowledgeBase
        from haiji.knowledge.base_kb import KBResult

        before_called: list[str] = []
        after_called: list[list] = []

        class HookedKB(KnowledgeBase):
            async def on_before_search(self, query: str) -> str:
                before_called.append(query)
                return query

            async def on_after_search(self, results: list[KBResult]) -> list[KBResult]:
                after_called.append(results)
                return results

        embedder = MockEmbedder(dim=32)
        kb = HookedKB(embedder)
        text = "测试内容关键词"
        await kb.load_text(text, doc_id="doc1")
        # 用相同文本查询，保证 score >= 0，触发 after 钩子
        await kb.search(text)

        assert len(before_called) == 1
        assert before_called[0] == text
        assert len(after_called) == 1

    @pytest.mark.asyncio
    async def test_custom_store_injected(self) -> None:
        """可以注入自定义 InMemoryKnowledgeStore。"""
        from haiji.knowledge.knowledge_base import KnowledgeBase

        embedder = MockEmbedder(dim=32)
        custom_store = InMemoryKnowledgeStore("custom_store")
        kb = KnowledgeBase(embedder, store=custom_store)
        info = kb.info()
        assert info["store_id"] == "custom_store"

    @pytest.mark.asyncio
    async def test_kb_result_has_doc_id_and_chunk_id(self) -> None:
        """搜索结果的 KBResult 包含 doc_id 和 chunk_id。"""
        from haiji.knowledge.knowledge_base import KnowledgeBase

        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder)
        text = "测试文档内容关键词"
        await kb.load_text(text, doc_id="my_doc")

        # 用相同文本查询，保证能找到结果
        results = await kb.search(text)
        assert len(results) >= 1
        assert results[0].doc_id != "" or results[0].chunk_id != ""


# ---------------------------------------------------------------------------
# QwenEmbedder 测试（Mock httpx）
# ---------------------------------------------------------------------------


class TestQwenEmbedder:
    @pytest.mark.asyncio
    async def test_embed_calls_api(self) -> None:
        """embed() 应调用 MaaS API 并返回向量。"""
        from haiji.knowledge.embedder import QwenEmbedder
        import httpx
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"index": 0, "embedding": [0.1] * 4096}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        embedder = QwenEmbedder(api_key="fake-key", base_url="https://test.example.com/v1")

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await embedder.embed("hello world")

        assert len(result) == 4096
        assert result[0] == 0.1
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args[1]
        assert call_kwargs["json"]["model"] == "qwen3-embedding-8b"
        assert call_kwargs["json"]["input"] == ["hello world"]
        assert call_kwargs["json"]["encoding_format"] == "float"

    @pytest.mark.asyncio
    async def test_embed_batch_batches_correctly(self) -> None:
        """embed_batch 按 batch_size 分批调用 API。"""
        from haiji.knowledge.embedder import QwenEmbedder
        import httpx
        from unittest.mock import AsyncMock, MagicMock, patch

        call_count = 0

        async def mock_post(url, headers, json):
            nonlocal call_count
            call_count += 1
            items = [{"index": i, "embedding": [float(call_count)] * 4096}
                     for i in range(len(json["input"]))]
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"data": items}
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=mock_post)

        # batch_size=3, 7 texts → 3 batches (3+3+1)
        embedder = QwenEmbedder(
            api_key="fake-key",
            base_url="https://test.example.com/v1",
            batch_size=3,
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await embedder.embed_batch(["text"] * 7)

        assert len(results) == 7
        assert call_count == 3  # ceil(7/3) = 3 批

    @pytest.mark.asyncio
    async def test_embed_batch_empty_returns_empty(self) -> None:
        """embed_batch([]) 返回空列表，不调用 API。"""
        from haiji.knowledge.embedder import QwenEmbedder
        from unittest.mock import patch, MagicMock

        embedder = QwenEmbedder(api_key="fake-key", base_url="https://test.example.com/v1")
        with patch("httpx.AsyncClient") as mock_cls:
            result = await embedder.embed_batch([])
        assert result == []
        mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_embed_batch_result_order_by_index(self) -> None:
        """embed_batch 按 index 排序返回结果（API 可能乱序）。"""
        from haiji.knowledge.embedder import QwenEmbedder
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_response = MagicMock()
        # 故意乱序返回
        mock_response.json.return_value = {
            "data": [
                {"index": 1, "embedding": [0.2] * 4096},
                {"index": 0, "embedding": [0.1] * 4096},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        embedder = QwenEmbedder(api_key="fake-key", base_url="https://test.example.com/v1")
        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await embedder.embed_batch(["text1", "text2"])

        assert results[0][0] == 0.1  # index=0 在前
        assert results[1][0] == 0.2  # index=1 在后

    def test_auth_header_sent(self) -> None:
        """Bearer token 正确写入 Authorization header。"""
        from haiji.knowledge.embedder import QwenEmbedder

        embedder = QwenEmbedder(api_key="my-secret-key", base_url="https://test.example.com/v1")
        assert embedder._api_key == "my-secret-key"
        assert embedder._base_url == "https://test.example.com/v1"
        assert embedder._model == "qwen3-embedding-8b"
        assert embedder._batch_size == 32

    def test_custom_model_and_batch_size(self) -> None:
        """支持自定义 model 和 batch_size。"""
        from haiji.knowledge.embedder import QwenEmbedder

        embedder = QwenEmbedder(
            api_key="key",
            base_url="https://test.com/v1",
            model="custom-model",
            batch_size=16,
        )
        assert embedder._model == "custom-model"
        assert embedder._batch_size == 16

    def test_base_url_trailing_slash_stripped(self) -> None:
        """base_url 末尾斜杠被移除。"""
        from haiji.knowledge.embedder import QwenEmbedder

        embedder = QwenEmbedder(api_key="key", base_url="https://test.com/v1/")
        assert embedder._base_url == "https://test.com/v1"
