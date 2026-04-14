"""
knowledge/knowledge_base.py - 内置知识库实现

提供：
- KnowledgeBase：开箱即用的知识库，继承 BaseKnowledgeBase

内置实现：
- 文本加载：load_text / load_file（自动 chunk + embed + 入库）
- 向量检索：余弦相似度（InMemoryKnowledgeStore + 自行计算 score）
- 文档管理：delete_doc / info

扩展预留：
- search 方法内部预留混合检索（BM25 + 向量）、父子检索等扩展注释
- 钩子：on_before_search / on_after_search（继承自 BaseKnowledgeBase，可覆盖）
- store 和 chunker 均可在构造时注入，便于测试和自定义
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional, Union

from haiji.knowledge.base_kb import BaseKnowledgeBase, KBResult
from haiji.knowledge.chunker import TextChunker
from haiji.knowledge.definition import ChunkConfig, KnowledgeDocument
from haiji.knowledge.embedder import BaseEmbedder
from haiji.knowledge.store import InMemoryKnowledgeStore, _cosine_similarity

logger = logging.getLogger(__name__)

# 支持加载的文件后缀
_SUPPORTED_SUFFIXES = {".txt", ".md"}


class KnowledgeBase(BaseKnowledgeBase):
    """
    内置知识库：开箱即用，继承 BaseKnowledgeBase。

    当前实现：
    - 文档加载（load_text / load_file）：自动 chunk + embed + 入库
    - 向量检索（search）：用余弦相似度在 InMemoryKnowledgeStore 中检索

    扩展预留（外部接口不变）：
    - 替换 store：可传入自定义持久化 store（如 Milvus / Qdrant 适配器）
    - 替换 chunker：可传入自定义切片策略（如递归切片、语义切片）
    - 扩展 search：在 search 方法内部添加 BM25 并行检索并 RRF 合并
    - 扩展钩子：覆盖 on_before_search / on_after_search 实现 rerank 等

    使用示例::

        embedder = QwenEmbedder(api_key="...", base_url="...")
        kb = KnowledgeBase(embedder)
        count = await kb.load_text("haiji 是一个 Python Multi-Agent 框架", doc_id="readme")
        results = await kb.search("什么是 haiji？", top_k=3)
        for r in results:
            print(r.content, r.score)
    """

    def __init__(
        self,
        embedder: BaseEmbedder,
        store: Optional[InMemoryKnowledgeStore] = None,
        store_id: str = "default",
        chunker: Optional[TextChunker] = None,
    ) -> None:
        """
        初始化内置知识库。

        Args:
            embedder:  文本向量化器（必须）
            store:     知识库存储，None 时自动创建 InMemoryKnowledgeStore
            store_id:  store 唯一标识（仅在 store=None 时生效），默认 "default"
            chunker:   文本切片器，None 时使用默认 ChunkConfig（chunk_size=512）
        """
        self._embedder = embedder
        self._store = store if store is not None else InMemoryKnowledgeStore(store_id)
        self._chunker = chunker if chunker is not None else TextChunker(ChunkConfig())

    async def load_text(
        self,
        text: str,
        doc_id: str,
        source: str = "",
        metadata: Optional[dict] = None,
    ) -> int:
        """
        加载纯文本，自动 chunk + embed + 入库。

        Args:
            text:     待加载文本内容
            doc_id:   文档唯一 ID（调用方负责保证唯一性）
            source:   来源标识，默认为空字符串
            metadata: 附加元数据，None 时使用空字典

        Returns:
            int: 成功入库的 chunk 数量
        """
        if not text.strip():
            logger.debug("KnowledgeBase.load_text: doc_id=%s 内容为空，跳过", doc_id)
            return 0

        doc = KnowledgeDocument(
            doc_id=doc_id,
            source=source or "inline",
            content=text,
            metadata=metadata or {},
        )
        return await self._index_document(doc)

    async def load_file(
        self,
        path: Union[str, Path],
        doc_id: str = "",
        metadata: Optional[dict] = None,
    ) -> int:
        """
        加载文件（支持 .txt / .md），自动 chunk + embed + 入库。

        Args:
            path:     文件路径（str 或 Path）
            doc_id:   文档唯一 ID，为空时自动生成 UUID
            metadata: 附加元数据，None 时自动填充 {"file_path": str(path)}

        Returns:
            int: 成功入库的 chunk 数量

        Raises:
            ValueError:        文件类型不受支持（非 .txt / .md）
            FileNotFoundError: 文件不存在
            IOError:           文件读取失败
        """
        file_path = Path(path)
        suffix = file_path.suffix.lower()

        if suffix not in _SUPPORTED_SUFFIXES:
            raise ValueError(
                f"不支持的文件类型：{suffix}，仅支持 {_SUPPORTED_SUFFIXES}"
            )

        logger.info("KnowledgeBase.load_file: path=%s", file_path)

        loop = asyncio.get_event_loop()
        try:
            content = await loop.run_in_executor(None, file_path.read_text, "utf-8")
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise IOError(f"读取文件失败：{file_path}") from exc

        effective_doc_id = doc_id or str(uuid.uuid4())
        effective_metadata = metadata if metadata is not None else {"file_path": str(file_path)}

        doc = KnowledgeDocument(
            doc_id=effective_doc_id,
            source=str(file_path),
            content=content,
            metadata=effective_metadata,
        )
        return await self._index_document(doc)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[KBResult]:
        """
        向量检索：将 query 向量化后在知识库中检索最相关切片。

        执行步骤：
        1. 调用 on_before_search 处理 query（默认 no-op，可覆盖）
        2. 将 query 向量化
        3. 在 store 中检索 top_k 候选切片
        4. 重算余弦相似度并过滤 score < score_threshold 的结果
        5. 调用 on_after_search 处理结果（默认 no-op，可覆盖）

        扩展预留（外部接口不变）：
        - 混合检索（BM25 + 向量）：可在 Step 2/3 之间并行调用 BM25 检索，
          用 RRF（Reciprocal Rank Fusion）或线性融合合并 score
        - 父子检索：检索子块后，替换为父块内容（提升上下文完整性）
        - 同类检索：按 metadata 过滤后检索

        Args:
            query:           用户查询文本
            top_k:           返回结果数量上限
            score_threshold: 相似度阈值，低于此值的结果不返回

        Returns:
            list[KBResult]: 检索结果列表，按 score 降序排列
        """
        if not query.strip():
            logger.debug("KnowledgeBase.search: query 为空，返回空结果")
            return []

        # Step 1: on_before_search 钩子（如 query 改写、HyDE）
        processed_query = await self.on_before_search(query)

        # Step 2: 向量化 query
        logger.debug("KnowledgeBase.search: 向量化 query（len=%d）", len(processed_query))
        query_embedding = await self._embedder.embed(processed_query)

        # Step 3: 在 store 中检索候选切片
        # 注意：store.search 只返回 DocumentChunk，不附带 score
        candidates = self._store.search(query_embedding, top_k=top_k)

        if not candidates:
            logger.debug("KnowledgeBase.search: 知识库无候选结果")
            return []

        # Step 4: 重算余弦相似度，过滤低分结果，转换为 KBResult
        # store.search 内部已按相似度排序，但不暴露 score，需自行重算
        kb_results: list[KBResult] = []
        for chunk in candidates:
            if chunk.embedding is None:
                continue
            # 重算余弦相似度（与 store.search 内部逻辑一致）
            score = _cosine_similarity(query_embedding, chunk.embedding)
            if score < score_threshold:
                continue
            # 从 chunk_id 推断 doc_id（格式："{doc_id}_{index}"）
            doc_id = "_".join(chunk.chunk_id.split("_")[:-1]) if "_" in chunk.chunk_id else chunk.chunk_id
            kb_results.append(
                KBResult(
                    content=chunk.content,
                    score=score,
                    doc_id=doc_id,
                    chunk_id=chunk.chunk_id,
                    metadata=dict(chunk.metadata),
                )
            )

        # 保持按 score 降序排列
        kb_results.sort(key=lambda r: r.score, reverse=True)

        if not kb_results:
            logger.debug(
                "KnowledgeBase.search: 所有结果低于 score_threshold=%.2f，返回空结果",
                score_threshold,
            )
            return []

        # Step 5: on_after_search 钩子（如 rerank、去重）
        final_results = await self.on_after_search(kb_results)

        logger.info(
            "KnowledgeBase.search: 返回 %d 个结果（top_k=%d，threshold=%.2f）",
            len(final_results),
            top_k,
            score_threshold,
        )
        return final_results

    def delete_doc(self, doc_id: str) -> None:
        """
        删除指定文档及其所有切片。

        Args:
            doc_id: 文档唯一 ID，不存在时静默忽略
        """
        self._store.delete_document(doc_id)
        logger.info("KnowledgeBase.delete_doc: doc_id=%s 已删除", doc_id)

    def info(self) -> dict:
        """
        返回知识库统计信息。

        Returns:
            dict: 包含 store_id, doc_count, chunk_count 的字典
        """
        store_info = self._store.info()
        return {
            "store_id": store_info.store_id,
            "doc_count": store_info.doc_count,
            "chunk_count": store_info.chunk_count,
        }

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    async def _index_document(self, doc: KnowledgeDocument) -> int:
        """
        将文档切片、向量化并存入知识库。

        Args:
            doc: 待索引的完整文档

        Returns:
            int: 成功入库的 chunk 数量
        """
        # 1. 切片
        chunks = self._chunker.chunk(doc)
        if not chunks:
            logger.debug(
                "KnowledgeBase._index_document: doc_id=%s 切片为空，跳过", doc.doc_id
            )
            return 0

        # 2. 批量向量化
        texts = [chunk.content for chunk in chunks]
        embeddings = await self._embedder.embed_batch(texts)

        # 3. 将 embedding 写入 chunk
        for chunk, embedding in zip(chunks, embeddings):
            chunk.embedding = embedding

        # 4. 存入 store
        self._store.add_document(doc, chunks)
        logger.info(
            "KnowledgeBase._index_document: doc_id=%s 入库 %d 个 chunk",
            doc.doc_id,
            len(chunks),
        )
        return len(chunks)
