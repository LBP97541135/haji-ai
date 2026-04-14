"""
knowledge/chunker.py - 文档切片器

将 KnowledgeDocument 切分为若干 DocumentChunk。
切分策略：先按 separator 分段，再按 chunk_size 合并/拆分，支持 overlap。
"""

from __future__ import annotations

import logging

from haiji.knowledge.definition import ChunkConfig, DocumentChunk, KnowledgeDocument

logger = logging.getLogger(__name__)


class TextChunker:
    """
    文本切片器。

    按段落优先、字符上限约束将文档切分为若干切片，相邻切片之间有
    chunk_overlap 个字符的重叠，以提升检索召回率。

    Example:
        >>> config = ChunkConfig(chunk_size=200, chunk_overlap=20, separator="\\n\\n")
        >>> chunker = TextChunker(config)
        >>> chunks = chunker.chunk(document)
    """

    def __init__(self, config: ChunkConfig) -> None:
        """
        初始化切片器。

        Args:
            config: 切片配置
        """
        self.config = config

    def chunk(self, document: KnowledgeDocument) -> list[DocumentChunk]:
        """
        将文档切分为若干 DocumentChunk。

        chunk_id 格式："{doc_id}_{index}"（index 从 0 开始）。

        Args:
            document: 待切分文档

        Returns:
            list[DocumentChunk]: 切片列表（不含 embedding）
        """
        content = document.content
        if not content.strip():
            logger.debug("document %s 内容为空，返回空切片列表", document.doc_id)
            return []

        raw_chunks = self._split_to_chunks(content)

        result: list[DocumentChunk] = []
        for index, chunk_text in enumerate(raw_chunks):
            chunk = DocumentChunk(
                chunk_id=f"{document.doc_id}_{index}",
                source=document.source,
                content=chunk_text,
                metadata=dict(document.metadata),
            )
            result.append(chunk)

        logger.debug("document %s 切分为 %d 个 chunk", document.doc_id, len(result))
        return result

    def _split_to_chunks(self, text: str) -> list[str]:
        """
        将文本切分为若干字符串片段。

        策略：
        1. 按 separator 分段
        2. 将段落合并成不超过 chunk_size 的块
        3. 超长段落（单段 > chunk_size）强制按字符拆分
        4. 相邻块之间保留 chunk_overlap 个字符的重叠

        Args:
            text: 原始文本

        Returns:
            list[str]: 切片字符串列表
        """
        chunk_size = self.config.chunk_size
        overlap = self.config.chunk_overlap
        separator = self.config.separator

        # Step 1: 按分隔符分段
        paragraphs = text.split(separator)
        # 过滤空段落
        paragraphs = [p for p in paragraphs if p.strip()]

        if not paragraphs:
            return []

        # Step 2: 将段落合并 / 拆分成不超过 chunk_size 的块
        base_chunks: list[str] = []
        for para in paragraphs:
            if len(para) <= chunk_size:
                base_chunks.append(para)
            else:
                # 超长段落强制按字符拆分（无 overlap，overlap 在 Step 3 统一处理）
                sub_chunks = self._hard_split(para, chunk_size)
                base_chunks.extend(sub_chunks)

        # Step 3: 合并相邻短块，使每块尽量接近 chunk_size
        merged = self._merge_chunks(base_chunks, chunk_size)

        # Step 4: 添加 overlap
        if overlap <= 0 or len(merged) <= 1:
            return merged

        return self._apply_overlap(merged, overlap)

    def _hard_split(self, text: str, chunk_size: int) -> list[str]:
        """
        将超长文本按字符硬切分。

        Args:
            text: 待切分文本
            chunk_size: 每块最大字符数

        Returns:
            list[str]: 切片列表
        """
        parts: list[str] = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            parts.append(text[start:end])
            start = end
        return parts

    def _merge_chunks(self, chunks: list[str], chunk_size: int) -> list[str]:
        """
        将短块贪心合并，使每块尽量接近 chunk_size。

        Args:
            chunks: 已有块列表
            chunk_size: 最大字符数上限

        Returns:
            list[str]: 合并后的块列表
        """
        if not chunks:
            return []

        merged: list[str] = []
        current = chunks[0]

        for chunk in chunks[1:]:
            # 预估合并后的长度（加一个换行符作为分隔）
            candidate = current + "\n" + chunk
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                merged.append(current)
                current = chunk

        merged.append(current)
        return merged

    def _apply_overlap(self, chunks: list[str], overlap: int) -> list[str]:
        """
        为相邻块添加重叠内容。

        每个块的开头追加前一块结尾的 overlap 个字符。

        Args:
            chunks: 原始块列表
            overlap: 重叠字符数

        Returns:
            list[str]: 添加 overlap 后的块列表
        """
        result: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-overlap:]
            result.append(prev_tail + chunks[i])
        return result
