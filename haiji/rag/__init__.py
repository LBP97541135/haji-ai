"""
haiji.rag - 检索增强生成（RAG）模块

在 Agent 执行流程中集成知识库检索，将相关知识片段注入 system prompt 或用户消息。

Quick start::

    from haiji.knowledge import InMemoryKnowledgeStore, MockEmbedder, KnowledgeLoader, TextChunker, ChunkConfig
    from haiji.rag import RagConfig, RagResult, RagRetriever

    # 构建知识库
    embedder = MockEmbedder(dim=64)
    store = InMemoryKnowledgeStore("kb")
    loader = KnowledgeLoader()
    doc = await loader.load_text("haiji 是一个 Python Multi-Agent 框架。", source="readme")
    chunks = TextChunker(ChunkConfig()).chunk(doc)
    for chunk in chunks:
        chunk.embedding = await embedder.embed(chunk.content)
    store.add_document(doc, chunks)

    # 检索
    retriever = RagRetriever(store, embedder, RagConfig(top_k=3))
    result = await retriever.retrieve("什么是 haiji？")
    print(result.injected_text)
    # 以下是相关知识：
    #
    # haiji 是一个 Python Multi-Agent 框架。
"""

from haiji.rag.definition import RagConfig, RagResult
from haiji.rag.retriever import RagRetriever

__all__ = [
    "RagConfig",
    "RagResult",
    "RagRetriever",
]
