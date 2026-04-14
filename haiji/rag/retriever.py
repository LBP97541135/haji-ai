"""
rag/retriever.py - RAG 检索器

提供：
- RagRetriever：调用 BaseKnowledgeBase.search 检索，格式化为可注入 prompt 的文本

设计原则：
- 接受 BaseKnowledgeBase 而非具体实现，支持任意可插拔知识库
- 不依赖 Agent 内部实现，可独立使用
- Agent 层通过 _prepare_execution() 时注入 RagRetriever（可选）
- 全异步：直接调用 kb.search（kb 内部负责 embed + 检索）
"""

from __future__ import annotations

import logging

from haiji.knowledge.base_kb import BaseKnowledgeBase, KBResult
from haiji.rag.definition import RagConfig, RagResult

logger = logging.getLogger(__name__)

_INJECT_HEADER = "以下是相关知识：\n\n"
_INJECT_SEPARATOR = "\n\n---\n\n"
_INJECT_TRUNCATION_SUFFIX = "..."


class RagRetriever:
    """
    RAG 检索器：给定查询文本，通过 BaseKnowledgeBase 检索相关内容并格式化为注入文本。

    使用方式::

        embedder = MockEmbedder()
        kb = KnowledgeBase(embedder)
        await kb.load_text("haiji 是一个 Python Multi-Agent 框架。", doc_id="readme")
        retriever = RagRetriever(kb, RagConfig(top_k=3))

        result = await retriever.retrieve("如何使用 haiji？")
        # result.injected_text 可直接拼接到 system prompt 或用户消息

    Attributes:
        kb:     知识库实例（实现 BaseKnowledgeBase 接口）
        config: RAG 配置
    """

    def __init__(
        self,
        kb: BaseKnowledgeBase,
        config: RagConfig | None = None,
    ) -> None:
        """
        初始化 RagRetriever。

        Args:
            kb:     知识库实例（任何实现 BaseKnowledgeBase 的类）
            config: RAG 配置，None 时使用默认配置
        """
        self.kb = kb
        self.config = config or RagConfig()

    async def retrieve(self, query: str) -> RagResult:
        """
        检索与查询最相关的内容，返回格式化后的注入文本。

        执行步骤：
        1. 将 query 传给 kb.search（kb 内部负责 embed + 检索 + 过滤）
        2. 格式化并截断至 max_inject_chars

        Args:
            query: 用户查询文本

        Returns:
            RagResult: 检索结果（KBResult 列表 + 格式化注入文本）
        """
        if not query.strip():
            logger.debug("RagRetriever.retrieve: query 为空，返回空结果")
            return RagResult()

        # 直接调用 kb.search，score_threshold 过滤在 kb 内部完成
        logger.debug("RagRetriever.retrieve: 调用 kb.search（query_len=%d）", len(query))
        kb_results = await self.kb.search(
            query,
            top_k=self.config.top_k,
            score_threshold=self.config.score_threshold,
        )

        if not kb_results:
            logger.debug("RagRetriever.retrieve: kb 无结果，返回空")
            return RagResult()

        # 格式化并截断
        injected_text = self._format_and_truncate(kb_results)

        logger.info(
            "RagRetriever.retrieve: 返回 %d 个结果，注入文本长度=%d",
            len(kb_results),
            len(injected_text),
        )
        return RagResult(results=kb_results, injected_text=injected_text)

    def _format_and_truncate(self, results: list[KBResult]) -> str:
        """
        将 KBResult 列表格式化为注入文本，并在超出 max_inject_chars 时截断。

        格式::

            以下是相关知识：

            <result1.content>

            ---

            <result2.content>

        若总长超出 max_inject_chars，截断最后一个结果并追加 "..."。

        Args:
            results: 已过滤的 KBResult 列表

        Returns:
            str: 格式化后的注入文本
        """
        max_chars = self.config.max_inject_chars
        header = _INJECT_HEADER
        sep = _INJECT_SEPARATOR
        suffix = _INJECT_TRUNCATION_SUFFIX

        # 先构建完整文本，再决定是否截断
        parts: list[str] = []
        for i, result in enumerate(results):
            part = result.content
            if i > 0:
                part = sep + part
            parts.append(part)

        full_text = header + "".join(parts)

        if len(full_text) <= max_chars:
            return full_text

        # 超出限制，逐步截断
        result_text = header
        remaining = max_chars - len(header) - len(suffix)

        if remaining <= 0:
            # header 本身已超出限制，罕见情况，返回空
            return ""

        for i, kb_result in enumerate(results):
            content = kb_result.content
            prefix = sep if i > 0 else ""
            piece = prefix + content

            if len(result_text) + len(piece) + len(suffix) <= max_chars:
                result_text += piece
            else:
                # 截断最后一个结果
                space_left = max_chars - len(result_text) - len(suffix)
                if space_left > len(prefix):
                    result_text += prefix + content[: space_left - len(prefix)]
                result_text += suffix
                break

        return result_text
