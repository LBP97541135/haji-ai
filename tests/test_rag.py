"""
tests/test_rag.py - RAG 模块测试

覆盖：
- RagConfig 默认值与校验
- RagResult 数据结构（results 字段，KBResult 格式）
- RagRetriever 正常检索并格式化（使用 BaseKnowledgeBase）
- RagRetriever score_threshold 过滤
- RagRetriever 超长内容截断
- RagRetriever 空结果处理
- RagRetriever 空 query 处理
- KnowledgeBase 作为 RagRetriever 后端的端到端测试
"""

from __future__ import annotations

import asyncio
import math
import random
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from haiji.knowledge.base_kb import BaseKnowledgeBase, KBResult
from haiji.knowledge.definition import ChunkConfig, DocumentChunk, KnowledgeDocument
from haiji.knowledge.embedder import BaseEmbedder, MockEmbedder
from haiji.knowledge.knowledge_base import KnowledgeBase
from haiji.knowledge.store import InMemoryKnowledgeStore, _cosine_similarity
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


def unit_vector(seed: int, dim: int = 8) -> list[float]:
    """生成确定性单位向量（用于相似度可控的测试）。"""
    rng = random.Random(seed)
    raw = [rng.gauss(0, 1) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw))
    if norm == 0.0:
        return [1.0] + [0.0] * (dim - 1)
    return [x / norm for x in raw]


class MockKnowledgeBase(BaseKnowledgeBase):
    """
    测试用知识库：包装 InMemoryKnowledgeStore + BaseEmbedder，
    实现 BaseKnowledgeBase 接口，用于测试 RagRetriever 行为。
    """

    def __init__(
        self,
        store: InMemoryKnowledgeStore,
        embedder: BaseEmbedder,
        score_threshold_override: Optional[float] = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._score_threshold_override = score_threshold_override

    async def search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[KBResult]:
        """向量检索实现（测试用）。"""
        if not query.strip():
            return []
        query_embedding = await self._embedder.embed(query)
        candidates = self._store.search(query_embedding, top_k=top_k)
        if not candidates:
            return []
        threshold = self._score_threshold_override if self._score_threshold_override is not None else score_threshold
        results: list[KBResult] = []
        for chunk in candidates:
            if chunk.embedding is None:
                continue
            score = _cosine_similarity(query_embedding, chunk.embedding)
            if score >= threshold:
                doc_id = "_".join(chunk.chunk_id.split("_")[:-1]) if "_" in chunk.chunk_id else chunk.chunk_id
                results.append(KBResult(
                    content=chunk.content,
                    score=score,
                    doc_id=doc_id,
                    chunk_id=chunk.chunk_id,
                    metadata=dict(chunk.metadata),
                ))
        results.sort(key=lambda r: r.score, reverse=True)
        return results


def make_kb_with_chunks(
    chunks: list[DocumentChunk],
    embedder: BaseEmbedder,
    store_id: str = "test",
) -> MockKnowledgeBase:
    """创建并填充好的 MockKnowledgeBase。"""
    store = InMemoryKnowledgeStore(store_id)
    doc = KnowledgeDocument(
        doc_id="doc-1",
        source="test",
        content="combined",
    )
    store.add_document(doc, chunks)
    return MockKnowledgeBase(store, embedder)


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
        assert result.results == []
        assert result.injected_text == ""

    def test_with_data(self):
        """RagResult 可以存储 KBResult 列表和注入文本。"""
        kb_result = KBResult(content="hello world", score=0.9)
        result = RagResult(results=[kb_result], injected_text="以下是相关知识：\n\nhello world")
        assert len(result.results) == 1
        assert "hello" in result.injected_text

    def test_results_field_is_kb_result_list(self):
        """RagResult.results 是 KBResult 列表。"""
        kb_result = KBResult(content="内容", score=0.8, doc_id="doc1", chunk_id="doc1_0")
        result = RagResult(results=[kb_result])
        assert result.results[0].content == "内容"
        assert result.results[0].score == 0.8
        assert result.results[0].doc_id == "doc1"


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

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v1)  # query 向量与 chunk1 完全一致

        kb = make_kb_with_chunks([chunk1, chunk2], embedder)
        retriever = RagRetriever(kb, RagConfig(top_k=2))
        result = await retriever.retrieve("什么是 haiji？")

        assert len(result.results) >= 1
        assert result.injected_text.startswith("以下是相关知识：")
        assert "Python Multi-Agent 框架" in result.injected_text

    @pytest.mark.asyncio
    async def test_inject_header_present(self):
        """注入文本以固定 header 开头。"""
        dim = 4
        v = unit_vector(7, dim)
        chunk = make_chunk("c1", "测试内容", embedding=v)

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v)

        kb = make_kb_with_chunks([chunk], embedder)
        retriever = RagRetriever(kb)
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

        kb = MockKnowledgeBase(store, embedder)
        retriever = RagRetriever(kb, RagConfig(top_k=5))
        result = await retriever.retrieve("内容")

        assert _INJECT_SEPARATOR in result.injected_text

    @pytest.mark.asyncio
    async def test_kb_search_called_with_query(self):
        """检索时 kb.search 被以正确参数调用。"""
        kb = AsyncMock(spec=BaseKnowledgeBase)
        kb.search = AsyncMock(return_value=[
            KBResult(content="测试内容", score=0.9)
        ])

        retriever = RagRetriever(kb, RagConfig(top_k=3))
        await retriever.retrieve("my query")

        kb.search.assert_called_once_with("my query", top_k=3, score_threshold=0.0)


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

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v_query)

        # MockKnowledgeBase 使用显式的 score_threshold_override=0.5 过滤
        store = InMemoryKnowledgeStore("s")
        doc = KnowledgeDocument(doc_id="d1", source="t", content="test")
        store.add_document(doc, [chunk])
        kb = MockKnowledgeBase(store, embedder, score_threshold_override=0.5)

        retriever = RagRetriever(kb, RagConfig(score_threshold=0.5))
        result = await retriever.retrieve("查询")

        assert result.results == []
        assert result.injected_text == ""

    @pytest.mark.asyncio
    async def test_score_threshold_zero_passes_all(self):
        """score_threshold=0.0 时不过滤任何结果。"""
        dim = 8
        v = unit_vector(42, dim)
        chunk = make_chunk("c1", "任意内容", embedding=v)

        embedder = AsyncMock(spec=BaseEmbedder)
        embedder.embed = AsyncMock(return_value=v)

        kb = make_kb_with_chunks([chunk], embedder)
        retriever = RagRetriever(kb, RagConfig(score_threshold=0.0))
        result = await retriever.retrieve("查询")

        assert len(result.results) == 1

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

        kb = MockKnowledgeBase(store, embedder, score_threshold_override=0.5)
        retriever = RagRetriever(kb, RagConfig(top_k=5, score_threshold=0.5))
        result = await retriever.retrieve("查询")

        assert len(result.results) == 1
        assert result.results[0].content == "高相关内容"


# ---------------------------------------------------------------------------
# 超长截断
# ---------------------------------------------------------------------------


class TestRagRetrieverTruncation:
    @pytest.mark.asyncio
    async def test_long_content_truncated_to_max_inject_chars(self):
        """注入文本超出 max_inject_chars 时，结果不超过限制。"""
        long_content = "X" * 3000

        kb = AsyncMock(spec=BaseKnowledgeBase)
        kb.search = AsyncMock(return_value=[
            KBResult(content=long_content, score=0.9)
        ])

        retriever = RagRetriever(kb, RagConfig(max_inject_chars=500))
        result = await retriever.retrieve("查询")

        assert len(result.injected_text) <= 500

    @pytest.mark.asyncio
    async def test_truncated_text_ends_with_ellipsis(self):
        """截断后的文本以 '...' 结尾。"""
        long_content = "A" * 3000

        kb = AsyncMock(spec=BaseKnowledgeBase)
        kb.search = AsyncMock(return_value=[
            KBResult(content=long_content, score=0.9)
        ])

        retriever = RagRetriever(kb, RagConfig(max_inject_chars=200))
        result = await retriever.retrieve("查询")

        assert result.injected_text.endswith("...")

    @pytest.mark.asyncio
    async def test_short_content_not_truncated(self):
        """短内容不被截断，不含多余 '...'。"""
        short_content = "短内容"

        kb = AsyncMock(spec=BaseKnowledgeBase)
        kb.search = AsyncMock(return_value=[
            KBResult(content=short_content, score=0.9)
        ])

        retriever = RagRetriever(kb, RagConfig(max_inject_chars=2000))
        result = await retriever.retrieve("查询")

        assert not result.injected_text.endswith("...")
        assert short_content in result.injected_text

    @pytest.mark.asyncio
    async def test_multiple_chunks_truncation_stops_early(self):
        """多切片时超长立即停止添加后续切片。"""
        kb_results = [
            KBResult(content=f"内容{i}" + "Y" * 200, score=0.9 - i * 0.01)
            for i in range(10)
        ]

        kb = AsyncMock(spec=BaseKnowledgeBase)
        kb.search = AsyncMock(return_value=kb_results)

        retriever = RagRetriever(kb, RagConfig(top_k=10, max_inject_chars=300))
        result = await retriever.retrieve("查询")

        assert len(result.injected_text) <= 300


# ---------------------------------------------------------------------------
# 空结果 & 空 query
# ---------------------------------------------------------------------------


class TestRagRetrieverEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_kb_returns_empty_result(self):
        """知识库无结果时返回空结果。"""
        kb = AsyncMock(spec=BaseKnowledgeBase)
        kb.search = AsyncMock(return_value=[])

        retriever = RagRetriever(kb)
        result = await retriever.retrieve("查询")

        assert result.results == []
        assert result.injected_text == ""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_result(self):
        """空 query 不调用 kb.search，返回空结果。"""
        kb = AsyncMock(spec=BaseKnowledgeBase)
        kb.search = AsyncMock(return_value=[KBResult(content="内容", score=0.9)])

        retriever = RagRetriever(kb)
        result = await retriever.retrieve("")

        assert result.results == []
        assert result.injected_text == ""
        kb.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_whitespace_only_query_returns_empty_result(self):
        """纯空白 query 同样返回空结果。"""
        kb = AsyncMock(spec=BaseKnowledgeBase)
        kb.search = AsyncMock(return_value=[])

        retriever = RagRetriever(kb)
        result = await retriever.retrieve("   \n\t  ")

        assert result.injected_text == ""
        kb.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_kb_search_called_with_correct_args(self):
        """retrieve 将 config 参数正确传给 kb.search。"""
        kb = AsyncMock(spec=BaseKnowledgeBase)
        kb.search = AsyncMock(return_value=[])

        config = RagConfig(top_k=7, score_threshold=0.3)
        retriever = RagRetriever(kb, config)
        await retriever.retrieve("查询文本")

        kb.search.assert_called_once_with("查询文本", top_k=7, score_threshold=0.3)


# ---------------------------------------------------------------------------
# KBResult 测试
# ---------------------------------------------------------------------------


class TestKBResult:
    def test_default_values(self):
        """KBResult 默认值正确。"""
        result = KBResult(content="测试内容")
        assert result.content == "测试内容"
        assert result.score == 0.0
        assert result.doc_id == ""
        assert result.chunk_id == ""
        assert result.metadata == {}

    def test_custom_values(self):
        """KBResult 可以自定义所有字段。"""
        result = KBResult(
            content="内容",
            score=0.85,
            doc_id="doc1",
            chunk_id="doc1_0",
            metadata={"source": "test"},
        )
        assert result.score == 0.85
        assert result.doc_id == "doc1"
        assert result.chunk_id == "doc1_0"
        assert result.metadata == {"source": "test"}


# ---------------------------------------------------------------------------
# BaseKnowledgeBase 钩子测试
# ---------------------------------------------------------------------------


class TestBaseKnowledgeBaseHooks:
    @pytest.mark.asyncio
    async def test_on_before_search_default_returns_query(self):
        """on_before_search 默认返回原始 query。"""
        kb = AsyncMock(spec=BaseKnowledgeBase)
        # 调用实际基类方法
        from haiji.knowledge.base_kb import BaseKnowledgeBase as RealBase

        class ConcreteKB(RealBase):
            async def search(self, query, top_k=5, score_threshold=0.0):
                return []

        concrete = ConcreteKB()
        result = await concrete.on_before_search("hello world")
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_on_after_search_default_returns_results(self):
        """on_after_search 默认返回原始结果。"""
        from haiji.knowledge.base_kb import BaseKnowledgeBase as RealBase

        class ConcreteKB(RealBase):
            async def search(self, query, top_k=5, score_threshold=0.0):
                return []

        concrete = ConcreteKB()
        input_results = [KBResult(content="内容", score=0.9)]
        output = await concrete.on_after_search(input_results)
        assert output == input_results

    @pytest.mark.asyncio
    async def test_hooks_can_be_overridden(self):
        """子类可以覆盖钩子实现自定义逻辑。"""
        from haiji.knowledge.base_kb import BaseKnowledgeBase as RealBase

        class RewriteKB(RealBase):
            async def search(self, query, top_k=5, score_threshold=0.0):
                return [KBResult(content=query, score=1.0)]

            async def on_before_search(self, query: str) -> str:
                return query.upper()  # 转大写

            async def on_after_search(self, results):
                return []  # 过滤所有结果

        kb = RewriteKB()
        results = await kb.search("test")
        assert results == [KBResult(content="test", score=1.0)]
        assert await kb.on_before_search("hello") == "HELLO"
        assert await kb.on_after_search([KBResult(content="x", score=0.5)]) == []


# ---------------------------------------------------------------------------
# KnowledgeBase 端到端测试（使用 MockEmbedder）
# ---------------------------------------------------------------------------


class TestKnowledgeBaseWithRagRetriever:
    @pytest.mark.asyncio
    async def test_end_to_end_with_mock_embedder(self):
        """KnowledgeBase + RagRetriever 端到端测试（相同文本检索自身）。"""
        embedder = MockEmbedder(dim=64)
        kb = KnowledgeBase(embedder)

        text = "haiji 是一个 Python Multi-Agent 框架"
        await kb.load_text(text, doc_id="d1")

        retriever = RagRetriever(kb, RagConfig(top_k=1))
        result = await retriever.retrieve(text)  # 相同文本，相似度为 1

        assert len(result.results) == 1
        assert text in result.injected_text

    @pytest.mark.asyncio
    async def test_rag_config_inject_mode_stored(self):
        """inject_mode 字段被正确存储（供 Agent 层使用）。"""
        kb = AsyncMock(spec=BaseKnowledgeBase)
        kb.search = AsyncMock(return_value=[])
        config = RagConfig(inject_mode="user_prefix")
        retriever = RagRetriever(kb, config)

        assert retriever.config.inject_mode == "user_prefix"

    @pytest.mark.asyncio
    async def test_results_have_score_field(self):
        """检索结果的每个 KBResult 都有 score 字段。"""
        embedder = MockEmbedder(dim=32)
        kb = KnowledgeBase(embedder)
        await kb.load_text("测试文本内容", doc_id="doc1")

        retriever = RagRetriever(kb, RagConfig(top_k=3))
        result = await retriever.retrieve("测试")

        for r in result.results:
            assert isinstance(r.score, float)
            assert 0.0 <= r.score <= 1.0 + 1e-9  # 余弦相似度范围
