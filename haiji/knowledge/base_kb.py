"""
knowledge/base_kb.py - 可插拔知识库抽象接口

提供：
- KBResult：内外知识库统一返回格式，含相似度分数
- BaseKnowledgeBase：可插拔抽象基类，外部知识库只需实现 search 方法

设计原则：
- 扩展点全部用抽象接口隔离，不写死
- 钩子方法（on_before_search / on_after_search）默认 no-op，便于后期扩展：
  * on_before_search：query 改写、扩展、多路检索拆分等
  * on_after_search：rerank、去重、置信度过滤等
- 后期支持关键词/向量混合检索、父子检索、同类检索，均在子类 search 内部扩展，
  外部调用方接口保持不变
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class KBResult(BaseModel):
    """
    知识库检索结果统一格式。

    内置知识库（KnowledgeBase）和外部知识库均必须返回此格式，
    确保 RagRetriever 和 Agent 层的兼容性。

    Attributes:
        content:   切片文本内容
        score:     相似度分数 [0.0, 1.0]，内外库都必须带（外部库不支持时填 0.0）
        doc_id:    所属文档 ID，外部库不支持时可为空字符串
        chunk_id:  切片唯一 ID，外部库不支持时可为空字符串
        metadata:  附加元数据，任意键值对
    """

    content: str
    score: float = 0.0
    doc_id: str = ""
    chunk_id: str = ""
    metadata: dict = Field(default_factory=dict)


class BaseKnowledgeBase(ABC):
    """
    可插拔知识库抽象基类。

    外部知识库（如 Elasticsearch、Milvus、第三方 RAG 服务）只需继承此类并实现
    search 方法，即可无缝接入 haiji Agent 的 RAG 流程。

    扩展点说明：
    - search()：核心检索接口，子类必须实现
        当前内置实现为向量检索（余弦相似度）；
        后期可在此处扩展为 BM25 + 向量混合检索、父子检索、同类检索等，
        外部调用方接口保持不变。
    - on_before_search()：检索前 query 处理钩子（可选覆盖）
        可用于 query 改写、HyDE、多路拆分等；
        默认直接返回原始 query（no-op）。
    - on_after_search()：检索后结果处理钩子（可选覆盖）
        可用于 rerank（如 cross-encoder 重排）、去重、置信度过滤等；
        默认直接返回原始结果（no-op）。

    使用示例::

        class MyExternalKB(BaseKnowledgeBase):
            async def search(self, query: str, top_k: int = 5,
                             score_threshold: float = 0.0) -> list[KBResult]:
                # 调用外部检索服务
                raw = await my_api.search(query, top_k)
                return [KBResult(content=r.text, score=r.score) for r in raw]

        kb = MyExternalKB()
        results = await kb.search("什么是 haiji？", top_k=3)
    """

    @abstractmethod
    async def search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[KBResult]:
        """
        核心检索接口，子类必须实现。

        实现要求：
        - 返回按相似度降序排列的结果列表
        - 过滤 score < score_threshold 的结果
        - score 字段必须填写（不支持时填 0.0）

        扩展点（在子类中实现）：
        - 向量检索：当前内置实现
        - BM25 关键词检索：可并行调用后 RRF 合并分数
        - 混合检索：BM25 + 向量双路，RRF/线性融合
        - 父子检索：检索子块，返回父块内容（提升上下文完整性）
        - 同类检索：按分类/标签过滤后检索

        Args:
            query:           用户查询文本（已经过 on_before_search 处理）
            top_k:           返回结果数量上限
            score_threshold: 相似度阈值，低于此值的结果不返回

        Returns:
            list[KBResult]: 检索结果列表，按 score 降序排列
        """
        ...

    async def on_before_search(self, query: str) -> str:
        """
        检索前处理 query 的钩子（可选覆盖）。

        扩展点：
        - Query 改写：用 LLM 将口语化 query 规范化
        - HyDE（假设性文档扩展）：生成假设文档后检索
        - Query 分解：将复合问题拆分为多个子 query
        默认直接返回原始 query（no-op）。

        Args:
            query: 原始用户查询文本

        Returns:
            str: 处理后的查询文本
        """
        return query

    async def on_after_search(self, results: list[KBResult]) -> list[KBResult]:
        """
        检索后处理结果的钩子（可选覆盖）。

        扩展点：
        - Rerank：用 cross-encoder 对结果重新打分排序
        - 去重：移除内容高度重叠的结果
        - 置信度过滤：基于业务规则二次过滤
        默认直接返回原始结果（no-op）。

        Args:
            results: 检索返回的原始结果列表

        Returns:
            list[KBResult]: 处理后的结果列表
        """
        return results
