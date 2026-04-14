"""
rag/retriever.py - RAG 检索器

提供：
- RagRetriever：将查询向量化后在知识库中检索，格式化为可注入 prompt 的文本

设计原则：
- 不依赖 Agent 内部实现，可独立使用
- Agent 层通过 prepare_execution() 时注入 RagRetriever（可选）
- 全异步：embed 和 search 均为 async
"""

from __future__ import annotations

import logging

from haiji.knowledge.embedder import BaseEmbedder
from haiji.knowledge.store import InMemoryKnowledgeStore
from haiji.rag.definition import RagConfig, RagResult

logger = logging.getLogger(__name__)

_INJECT_HEADER = "以下是相关知识：\n\n"
_INJECT_SEPARATOR = "\n\n---\n\n"
_INJECT_TRUNCATION_SUFFIX = "..."


class RagRetriever:
    """
    RAG 检索器：给定查询文本，在知识库中检索相关切片并格式化为注入文本。

    使用方式::

        embedder = MockEmbedder()
        store = InMemoryKnowledgeStore("kb")
        retriever = RagRetriever(store, embedder, RagConfig(top_k=3))

        result = await retriever.retrieve("如何使用 haiji？")
        # result.injected_text 可直接拼接到 system prompt 或用户消息

    Attributes:
        store: 知识库存储
        embedder: 向量化器
        config: RAG 配置
    """

    def __init__(
        self,
        store: InMemoryKnowledgeStore,
        embedder: BaseEmbedder,
        config: RagConfig | None = None,
    ) -> None:
        """
        初始化 RagRetriever。

        Args:
            store: 知识库存储实例
            embedder: 文本向量化器
            config: RAG 配置，None 时使用默认配置
        """
        self.store = store
        self.embedder = embedder
        self.config = config or RagConfig()

    async def retrieve(self, query: str) -> RagResult:
        """
        检索与查询最相关的切片，返回格式化后的注入文本。

        执行步骤：
        1. 将 query 向量化
        2. 在 store 中检索 top_k 个切片
        3. 过滤低于 score_threshold 的结果
        4. 格式化并截断至 max_inject_chars

        Args:
            query: 用户查询文本

        Returns:
            RagResult: 检索结果（切片列表 + 格式化注入文本）
        """
        if not query.strip():
            logger.debug("RagRetriever.retrieve: query 为空，返回空结果")
            return RagResult()

        # 1. 向量化查询
        logger.debug("RagRetriever.retrieve: 向量化 query（len=%d）", len(query))
        query_embedding = await self.embedder.embed(query)

        # 2. 从知识库检索（先取更多候选，再按 score_threshold 过滤）
        candidates = self.store.search(query_embedding, top_k=self.config.top_k)

        if not candidates:
            logger.debug("RagRetriever.retrieve: 知识库无结果")
            return RagResult()

        # 3. 过滤低分切片
        # store.search 返回 DocumentChunk，但不附带分数
        # 需要重新计算分数（用 store 内部余弦逻辑）
        from haiji.knowledge.store import _cosine_similarity

        filtered_chunks = []
        for chunk in candidates:
            if chunk.embedding is None:
                continue
            score = _cosine_similarity(query_embedding, chunk.embedding)
            if score >= self.config.score_threshold:
                filtered_chunks.append(chunk)

        if not filtered_chunks:
            logger.debug(
                "RagRetriever.retrieve: 所有结果低于 score_threshold=%.2f，返回空结果",
                self.config.score_threshold,
            )
            return RagResult()

        # 4. 格式化并截断
        injected_text = self._format_and_truncate(filtered_chunks)

        logger.info(
            "RagRetriever.retrieve: 返回 %d 个切片，注入文本长度=%d",
            len(filtered_chunks),
            len(injected_text),
        )
        return RagResult(chunks=filtered_chunks, injected_text=injected_text)

    def _format_and_truncate(self, chunks: list) -> str:
        """
        将切片列表格式化为注入文本，并在超出 max_inject_chars 时截断。

        格式::

            以下是相关知识：

            <chunk1.content>

            ---

            <chunk2.content>

        若总长超出 max_inject_chars，截断最后一个 chunk 并追加 "..."。

        Args:
            chunks: 已过滤的切片列表

        Returns:
            str: 格式化后的注入文本
        """
        max_chars = self.config.max_inject_chars
        header = _INJECT_HEADER
        sep = _INJECT_SEPARATOR
        suffix = _INJECT_TRUNCATION_SUFFIX

        # 先构建完整文本，再决定是否截断
        parts: list[str] = []
        total_chars = len(header)

        for i, chunk in enumerate(chunks):
            part = chunk.content
            if i > 0:
                part = sep + part
            parts.append(part)
            total_chars += len(part)

        full_text = header + "".join(parts)

        if len(full_text) <= max_chars:
            return full_text

        # 超出限制，逐步截断
        result = header
        remaining = max_chars - len(header) - len(suffix)

        if remaining <= 0:
            # header 本身已超出限制，罕见情况，返回空
            return ""

        for i, chunk in enumerate(chunks):
            content = chunk.content
            prefix = sep if i > 0 else ""
            piece = prefix + content

            if len(result) + len(piece) + len(suffix) <= max_chars:
                result += piece
            else:
                # 截断最后一个 chunk
                space_left = max_chars - len(result) - len(suffix)
                if space_left > len(prefix):
                    result += prefix + content[: space_left - len(prefix)]
                result += suffix
                break

        return result
