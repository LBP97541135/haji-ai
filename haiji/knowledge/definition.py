"""
knowledge/definition.py - 知识库数据结构定义

提供：
- DocumentChunk：文档切片，含 embedding
- KnowledgeDocument：完整文档，含切片列表
- ChunkConfig：切片配置
- KnowledgeStoreInfo：知识库统计信息
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    """
    文档切片，知识库的最小存储单元。

    Attributes:
        chunk_id: 切片唯一 ID，格式 "{doc_id}_{index}"
        source: 来源（文件路径或 "inline"）
        content: 切片文本内容
        metadata: 附加元数据（任意键值对）
        embedding: 向量表示，来自 Embedder，None 表示尚未向量化
    """

    chunk_id: str
    source: str
    content: str
    metadata: dict = Field(default_factory=dict)
    embedding: Optional[list[float]] = None


class KnowledgeDocument(BaseModel):
    """
    完整知识文档，由多个 DocumentChunk 组成。

    Attributes:
        doc_id: 文档唯一 ID
        source: 来源（文件路径或 "inline"）
        content: 原始完整文本
        metadata: 附加元数据
        chunks: 切片列表（由 TextChunker 填充）
    """

    doc_id: str
    source: str
    content: str
    metadata: dict = Field(default_factory=dict)
    chunks: list[DocumentChunk] = Field(default_factory=list)


class ChunkConfig(BaseModel):
    """
    文档切片配置。

    Attributes:
        chunk_size: 每片最大字符数，默认 512
        chunk_overlap: 相邻切片重叠字符数，默认 64
        separator: 优先按此分隔符切分，默认双换行（段落）
    """

    chunk_size: int = 512
    chunk_overlap: int = 64
    separator: str = "\n\n"


class KnowledgeStoreInfo(BaseModel):
    """
    知识库统计信息。

    Attributes:
        store_id: 知识库唯一标识
        doc_count: 已存储文档数
        chunk_count: 已存储切片数（含向量化切片）
    """

    store_id: str
    doc_count: int
    chunk_count: int
