"""
tests/test_rag.py - RAG 模块测试

覆盖：
- RagConfig 默认值与校验
- RagResult 数据结构
- RagRetriever 正常检索并格式化
- RagRetriever score_threshold 过滤
- RagRetriever 超长内容截断
- RagRetriever 空结果处理
- RagRetriever 空 query 处理
- embedder AsyncMock
"""

from __future__ import annotations

import asyncio
import math
import random
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from haiji.knowledge.definition import ChunkConfig, DocumentChunk, KnowledgeDocument
from haiji.knowledge.embedder import BaseEmbedder, MockEmbedder
from haiji.knowledge.store import InMemoryKnowledgeStore
from haiji.rag.definition import RagConfig, RagResult
from haiji.rag.retriever import RagRetriever, _INJECT_HEADER, _INJECT_SEPARATOR


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


def make_chunk(chunk_id: str, content: str, embedding: Optional[list[float]] = None) -> DocumentChunk:
    """创建测试用切片。"""
    return DocumentChunk(
        chunk_id=chunk_id,
        source="test",
        content=content,
        embedding=embedding,
    )


def make_store_with_chunks(chunks: list[DocumentChunk], store_id: str = "test") -> InMemoryKnowledgeStore:
    """创建并填充好的知识库。"""
    store = InMemoryKnowledgeStore(store_id)
    doc = KnowledgeDocument(
        doc_id="doc-1",
        source="test",
        content="combined",
    )
    store.add_document(doc, chunks)
    return store


def unit_vector(seed: int, dim: int = 8) -> list[float]:
    """生成确定性单位向量（用于相似度可控的测试）。"""
    rng = random.Random(seed)
    raw = [rng.gauss(0, 1) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw))
    if norm == 0.0:
        return [1.0] + [0.0] * (dim - 1)
    return [x / norm for x in raw]


# ---------------------------------------------------------------------------
# RagConfig 测试
# ---------------------------------------------------------------------------


class TestRagConfig:
    def test_default_values(self):
        """RagConfig 默认值正确。"""
        cfg = RagConfig()
        assert cfg.top_k == 5
        assert cfg.score_threshold == 0.0
        assert cfg.inject_mode == "system_suffix"
        assert cfg.max_inject_chars == 2000

    def test_custom_values(self):
        """RagConfig 可以自定义所有字段。"""
        cfg = RagConfig(
            top_k=10,
            score_threshold=0.7,
            inject_mode="user_prefix",
            max_inject_chars=500,
        )
        assert cfg.top_k == 10
        assert cfg.score_threshold == 0.7
        assert cfg.inject_mode == "user_prefix"
        assert cfg.max_inject_chars == 500

    def test_top_k_lower_bound(self):
        """top_k 最小值为 1。"""
        with pytest.raises(Exception):
            RagConfig(top_k=0)

    def test_score_threshold_bounds(self):
        """score_threshold 范围 [0.0, 1.0]。"""
        with pytest.raises(Exception):
            RagConfig(score_threshold=-0.1)
        with pytest.raises(Exception):
            RagConfig(score_threshold=1.1)

    def test_max_inject_chars_lower_bound(self):
        """max_inject_chars 最小值为 100。"""
        with pytest.raises(Exception):
            RagConfig(max_inject_chars=50)

    def test_inject_mode_validation(self):
        """inject_mode 只允许两个值。"""
        with pytest.raises(Exception):
            RagConfig(inject_mode="invalid_mode")  # type: ignore


# ---------------------------------------------------------------------------
# RagResult 测试
# ---------------------------------------------------------------------------


class TestRagResult:
    def test_default_empty(self):
        """RagResult 默认为空。"""
        result = RagResult()
        assert result.chunks == []
        assert result.injected_text == ""

    def test_with_data(self):
        """RagResult 可以存储切片和注入文本。"""
        chunk = make_chunk("c1", "hello world")
        result = RagResult(chunks=[chunk], injected_text="以下是相关知识：\n\nhello world")
        assert len(result.chunks) == 1
        assert "hello" in result.injected_text


# ---------------------------------------------------------------------------
# RagRetriever 正常检索
# ---------------------------------------------------------------------------


class TestRagRetrieverNormalSearch:
    @pytest.mark.asyncio
    async def test_retrieve_returns_matching_chunks(self):
        """正常检索：返回相关切片，injected_text 包含内容。"""
        dim = 8
        # query 向量 = chunk1 向量（高相似度）
        v1 = unit_vector(42, dim)
        v2 = unit_vector(99, dim)

        chunk1 = make_chunk("c1", "Python Multi-Agent 框架", embedding=v1)
        chunk2 = make_chunk("c2", "前端 React 组件", embedding=v2)
        store = make_store_with_chunks([chunk1, chunk2])

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v1)  # query 向量与 chunk1 完全一致

        retriever = RagRetriever(store, embedder, RagConfig(top_k=2))
        result = await retriever.retrieve("什么是 haiji？")

        assert len(result.chunks) >= 1
        assert result.injected_text.startswith("以下是相关知识：")
        assert "Python Multi-Agent 框架" in result.injected_text

    @pytest.mark.asyncio
    async def test_inject_header_present(self):
        """注入文本以固定 header 开头。"""
        dim = 4
        v = unit_vector(7, dim)
        chunk = make_chunk("c1", "测试内容", embedding=v)
        store = make_store_with_chunks([chunk])

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v)

        retriever = RagRetriever(store, embedder)
        result = await retriever.retrieve("测试")

        assert result.injected_text.startswith(_INJECT_HEADER)

    @pytest.mark.asyncio
    async def test_multiple_chunks_joined_with_separator(self):
        """多切片之间用分隔符连接。"""
        dim = 4
        v = unit_vector(1, dim)  # 所有切片用同一向量 → 均被检索到
        chunks = [
            make_chunk("c1", "内容A", embedding=v),
            make_chunk("c2", "内容B", embedding=v),
        ]

        # 用两个独立 doc 放入 store
        store = InMemoryKnowledgeStore("s")
        doc1 = KnowledgeDocument(doc_id="d1", source="t", content="内容A")
        doc2 = KnowledgeDocument(doc_id="d2", source="t", content="内容B")
        store.add_document(doc1, [chunks[0]])
        store.add_document(doc2, [chunks[1]])

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v)

        retriever = RagRetriever(store, embedder, RagConfig(top_k=5))
        result = await retriever.retrieve("内容")

        assert _INJECT_SEPARATOR in result.injected_text

    @pytest.mark.asyncio
    async def test_embedder_called_with_query(self):
        """检索时 embedder.embed 被以 query 调用。"""
        dim = 4
        v = unit_vector(3, dim)
        chunk = make_chunk("c1", "content", embedding=v)
        store = make_store_with_chunks([chunk])

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v)

        retriever = RagRetriever(store, embedder)
        await retriever.retrieve("my query")

        embedder.embed.assert_called_once_with("my query")


# ---------------------------------------------------------------------------
# score_threshold 过滤
# ---------------------------------------------------------------------------


class TestRagRetrieverScoreFilter:
    @pytest.mark.asyncio
    async def test_score_threshold_filters_low_score_chunks(self):
        """低于 score_threshold 的切片被过滤，返回空结果。"""
        dim = 8
        v_query = unit_vector(1, dim)
        # 使用与 query 完全不同的向量（低相似度）
        v_opposite = [-x for x in v_query]

        chunk = make_chunk("c1", "不相关内容", embedding=v_opposite)
        store = make_store_with_chunks([chunk])

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v_query)

        # 设置很高的阈值，相反向量的相似度为 -1，必然被过滤
        retriever = RagRetriever(store, embedder, RagConfig(score_threshold=0.5))
        result = await retriever.retrieve("查询")

        assert result.chunks == []
        assert result.injected_text == ""

    @pytest.mark.asyncio
    async def test_score_threshold_zero_passes_all(self):
        """score_threshold=0.0 时不过滤任何结果。"""
        dim = 8
        v = unit_vector(42, dim)
        chunk = make_chunk("c1", "任意内容", embedding=v)
        store = make_store_with_chunks([chunk])

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v)

        retriever = RagRetriever(store, embedder, RagConfig(score_threshold=0.0))
        result = await retriever.retrieve("查询")

        assert len(result.chunks) == 1

    @pytest.mark.asyncio
    async def test_score_threshold_partial_filter(self):
        """score_threshold 只过滤低分切片，高分切片正常返回。"""
        dim = 8
        v_query = unit_vector(10, dim)
        v_same = v_query  # 高相似度
        v_opposite = [-x for x in v_query]  # 低相似度

        store = InMemoryKnowledgeStore("s")
        doc1 = KnowledgeDocument(doc_id="d1", source="t", content="高相关")
        doc2 = KnowledgeDocument(doc_id="d2", source="t", content="低相关")
        store.add_document(doc1, [make_chunk("c1", "高相关内容", embedding=v_same)])
        store.add_document(doc2, [make_chunk("c2", "低相关内容", embedding=v_opposite)])

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v_query)

        retriever = RagRetriever(store, embedder, RagConfig(top_k=5, score_threshold=0.5))
        result = await retriever.retrieve("查询")

        assert len(result.chunks) == 1
        assert result.chunks[0].content == "高相关内容"


# ---------------------------------------------------------------------------
# 超长截断
# ---------------------------------------------------------------------------


class TestRagRetrieverTruncation:
    @pytest.mark.asyncio
    async def test_long_content_truncated_to_max_inject_chars(self):
        """注入文本超出 max_inject_chars 时，结果不超过限制。"""
        dim = 4
        v = unit_vector(5, dim)
        long_content = "X" * 3000  # 很长的内容
        chunk = make_chunk("c1", long_content, embedding=v)
        store = make_store_with_chunks([chunk])

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v)

        retriever = RagRetriever(store, embedder, RagConfig(max_inject_chars=500))
        result = await retriever.retrieve("查询")

        assert len(result.injected_text) <= 500

    @pytest.mark.asyncio
    async def test_truncated_text_ends_with_ellipsis(self):
        """截断后的文本以 '...' 结尾。"""
        dim = 4
        v = unit_vector(5, dim)
        long_content = "A" * 3000
        chunk = make_chunk("c1", long_content, embedding=v)
        store = make_store_with_chunks([chunk])

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v)

        retriever = RagRetriever(store, embedder, RagConfig(max_inject_chars=200))
        result = await retriever.retrieve("查询")

        assert result.injected_text.endswith("...")

    @pytest.mark.asyncio
    async def test_short_content_not_truncated(self):
        """短内容不被截断，不含多余 '...'。"""
        dim = 4
        v = unit_vector(5, dim)
        short_content = "短内容"
        chunk = make_chunk("c1", short_content, embedding=v)
        store = make_store_with_chunks([chunk])

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v)

        retriever = RagRetriever(store, embedder, RagConfig(max_inject_chars=2000))
        result = await retriever.retrieve("查询")

        assert not result.injected_text.endswith("...")
        assert short_content in result.injected_text

    @pytest.mark.asyncio
    async def test_multiple_chunks_truncation_stops_early(self):
        """多切片时超长立即停止添加后续切片。"""
        dim = 4
        v = unit_vector(1, dim)

        store = InMemoryKnowledgeStore("s")
        chunks = []
        for i in range(10):
            c = make_chunk(f"c{i}", f"内容{i}" + "Y" * 200, embedding=v)
            chunks.append(c)
            doc = KnowledgeDocument(doc_id=f"d{i}", source="t", content=f"内容{i}")
            store.add_document(doc, [c])

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v)

        retriever = RagRetriever(store, embedder, RagConfig(top_k=10, max_inject_chars=300))
        result = await retriever.retrieve("查询")

        assert len(result.injected_text) <= 300


# ---------------------------------------------------------------------------
# 空结果 & 空 query
# ---------------------------------------------------------------------------


class TestRagRetrieverEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_store_returns_empty_result(self):
        """空知识库返回空结果。"""
        store = InMemoryKnowledgeStore("empty")
        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

        retriever = RagRetriever(store, embedder)
        result = await retriever.retrieve("查询")

        assert result.chunks == []
        assert result.injected_text == ""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_result(self):
        """空 query 不调用 embedder，返回空结果。"""
        dim = 4
        v = unit_vector(1, dim)
        chunk = make_chunk("c1", "内容", embedding=v)
        store = make_store_with_chunks([chunk])

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v)

        retriever = RagRetriever(store, embedder)
        result = await retriever.retrieve("")

        assert result.chunks == []
        assert result.injected_text == ""
        embedder.embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_whitespace_only_query_returns_empty_result(self):
        """纯空白 query 同样返回空结果。"""
        store = InMemoryKnowledgeStore("s")
        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=[0.1])

        retriever = RagRetriever(store, embedder)
        result = await retriever.retrieve("   \n\t  ")

        assert result.injected_text == ""
        embedder.embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_chunks_without_embedding_skipped(self):
        """没有 embedding 的切片被跳过，不参与检索。"""
        store = InMemoryKnowledgeStore("s")
        chunk_no_emb = make_chunk("c1", "没有向量", embedding=None)
        doc = KnowledgeDocument(doc_id="d1", source="t", content="测试")
        store.add_document(doc, [chunk_no_emb])

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=[0.1, 0.2])

        retriever = RagRetriever(store, embedder)
        result = await retriever.retrieve("查询")

        assert result.chunks == []


# ---------------------------------------------------------------------------
# 使用 MockEmbedder 的端到端测试
# ---------------------------------------------------------------------------


class TestRagRetrieverWithMockEmbedder:
    @pytest.mark.asyncio
    async def test_end_to_end_with_mock_embedder(self):
        """使用 MockEmbedder 的端到端测试（相同文本检索自身）。"""
        embedder = MockEmbedder(dim=64)
        store = InMemoryKnowledgeStore("e2e")

        text = "haiji 是一个 Python Multi-Agent 框架"
        chunk = make_chunk("c1", text, embedding=await embedder.embed(text))
        doc = KnowledgeDocument(doc_id="d1", source="test", content=text)
        store.add_document(doc, [chunk])

        retriever = RagRetriever(store, embedder, RagConfig(top_k=1))
        result = await retriever.retrieve(text)  # 相同文本，相似度为 1

        assert len(result.chunks) == 1
        assert text in result.injected_text

    @pytest.mark.asyncio
    async def test_rag_config_inject_mode_stored(self):
        """inject_mode 字段被正确存储（供 Agent 层使用）。"""
        store = InMemoryKnowledgeStore("s")
        embedder = MockEmbedder(dim=16)
        config = RagConfig(inject_mode="user_prefix")
        retriever = RagRetriever(store, embedder, config)

        assert retriever.config.inject_mode == "user_prefix"
