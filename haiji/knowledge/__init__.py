"""
haiji.knowledge - 知识库模块

支持将文档（纯文本 / Markdown）导入知识库，自动切片并向量化存储，
最终通过余弦相似度检索最相关内容。

Quick start::

    from haiji.knowledge import (
        KnowledgeDocument,
        DocumentChunk,
        ChunkConfig,
        TextChunker,
        MockEmbedder,
        InMemoryKnowledgeStore,
        KnowledgeLoader,
    )

    loader = KnowledgeLoader()
    doc = await loader.load_text("Hello, world!", source="readme")

    chunker = TextChunker(ChunkConfig(chunk_size=200))
    chunks = chunker.chunk(doc)

    embedder = MockEmbedder(dim=128)
    for chunk in chunks:
        chunk.embedding = await embedder.embed(chunk.content)

    store = InMemoryKnowledgeStore("my_store")
    store.add_document(doc, chunks)

    query_emb = await embedder.embed("world")
    results = store.search(query_emb, top_k=3)
"""

from haiji.knowledge.chunker import TextChunker
from haiji.knowledge.definition import (
    ChunkConfig,
    DocumentChunk,
    KnowledgeDocument,
    KnowledgeStoreInfo,
)
from haiji.knowledge.embedder import BaseEmbedder, MockEmbedder, OpenAIEmbedder
from haiji.knowledge.loader import KnowledgeLoader, KnowledgeLoaderError, UnsupportedFileTypeError
from haiji.knowledge.store import InMemoryKnowledgeStore

__all__ = [
    # 数据结构
    "DocumentChunk",
    "KnowledgeDocument",
    "ChunkConfig",
    "KnowledgeStoreInfo",
    # 切片器
    "TextChunker",
    # 向量化
    "BaseEmbedder",
    "OpenAIEmbedder",
    "MockEmbedder",
    # 存储
    "InMemoryKnowledgeStore",
    # 加载器
    "KnowledgeLoader",
    "KnowledgeLoaderError",
    "UnsupportedFileTypeError",
]
