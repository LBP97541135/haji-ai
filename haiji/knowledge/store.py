"""
knowledge/store.py - 知识库内存存储

提供：
- InMemoryKnowledgeStore：基于内存的知识库，支持余弦相似度检索
"""

from __future__ import annotations

import logging
import math

from haiji.knowledge.definition import DocumentChunk, KnowledgeDocument, KnowledgeStoreInfo

logger = logging.getLogger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    计算两个向量的余弦相似度（纯 Python 实现，无需 numpy）。

    Args:
        a: 向量 A
        b: 向量 B

    Returns:
        float: 余弦相似度 [-1, 1]；维度不同或零向量时返回 0.0
    """
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryKnowledgeStore:
    """
    基于内存的知识库存储，第一期实现（无持久化）。

    支持：
    - 按 doc_id 存储文档及其切片
    - 余弦相似度检索 top-k 切片
    - 按 doc_id 删除文档

    Example:
        >>> store = InMemoryKnowledgeStore("my_store")
        >>> store.add_document(doc, chunks_with_embeddings)
        >>> results = store.search(query_embedding, top_k=5)
    """

    def __init__(self, store_id: str = "default") -> None:
        """
        初始化知识库。

        Args:
            store_id: 知识库唯一标识
        """
        self.store_id = store_id
        # doc_id → KnowledgeDocument（不含 chunks，仅用于文档元数据记录）
        self._docs: dict[str, KnowledgeDocument] = {}
        # 所有 chunk（含 embedding）的扁平列表，用于检索
        self._chunks: list[DocumentChunk] = []
        # doc_id → chunk_id 集合，用于删除
        self._doc_to_chunks: dict[str, list[str]] = {}

    def add_document(
        self,
        doc: KnowledgeDocument,
        chunks_with_embeddings: list[DocumentChunk],
    ) -> None:
        """
        将文档及其带 embedding 的切片存入知识库。

        若 doc_id 已存在，会先删除旧数据再重新导入。

        Args:
            doc: 文档元数据（不需要含 chunks）
            chunks_with_embeddings: 已向量化的切片列表
        """
        if doc.doc_id in self._docs:
            logger.info("document %s 已存在，先删除再重新导入", doc.doc_id)
            self.delete_document(doc.doc_id)

        self._docs[doc.doc_id] = doc
        chunk_ids: list[str] = []
        for chunk in chunks_with_embeddings:
            self._chunks.append(chunk)
            chunk_ids.append(chunk.chunk_id)
        self._doc_to_chunks[doc.doc_id] = chunk_ids

        logger.info(
            "document %s 已导入 %d 个 chunk 到 store=%s",
            doc.doc_id,
            len(chunks_with_embeddings),
            self.store_id,
        )

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[DocumentChunk]:
        """
        按余弦相似度检索最相关的 top-k 切片。

        只有包含 embedding 的切片才参与检索。

        Args:
            query_embedding: 查询向量
            top_k: 返回结果数量上限

        Returns:
            list[DocumentChunk]: 按相似度降序排列的切片列表
        """
        if not self._chunks or not query_embedding:
            return []

        scored: list[tuple[float, DocumentChunk]] = []
        for chunk in self._chunks:
            if chunk.embedding is None:
                continue
            score = _cosine_similarity(query_embedding, chunk.embedding)
            scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [chunk for _, chunk in scored[:top_k]]
        logger.debug("search 返回 %d 个结果（top_k=%d）", len(results), top_k)
        return results

    def delete_document(self, doc_id: str) -> None:
        """
        删除指定文档及其所有切片。

        若 doc_id 不存在，静默忽略。

        Args:
            doc_id: 文档唯一 ID
        """
        if doc_id not in self._docs:
            logger.debug("delete_document: doc_id=%s 不存在，跳过", doc_id)
            return

        chunk_ids_to_remove = set(self._doc_to_chunks.get(doc_id, []))
        self._chunks = [c for c in self._chunks if c.chunk_id not in chunk_ids_to_remove]
        del self._docs[doc_id]
        del self._doc_to_chunks[doc_id]
        logger.info("document %s 已从 store=%s 删除", doc_id, self.store_id)

    def info(self) -> KnowledgeStoreInfo:
        """
        返回知识库统计信息。

        Returns:
            KnowledgeStoreInfo: 统计数据
        """
        return KnowledgeStoreInfo(
            store_id=self.store_id,
            doc_count=len(self._docs),
            chunk_count=len(self._chunks),
        )
