"""
examples/full_agent/rag_agent.py — RAG + workspace + observer 联动示例

演示第二期新增能力的端到端联动：
  1. 用 MockEmbedder 建立内存知识库（不真实调用 OpenAI Embedding）
  2. 用 RagRetriever 检索相关知识片段
  3. REACT Agent 调用 query_kb 工具查询知识库
  4. Observer 追踪 LLM 调用与 Tool 调用
  5. AgentWorkspace 将查询结果写入文件持久化，再读出验证

Usage:
    python3 examples/full_agent/rag_agent.py

依赖：
    pip install -e .

LLM 调用默认使用 AsyncMock，无需真实 API Key；
若需要真实调用，请先设置 HAIJI_API_KEY 和 HAIJI_LLM_MODEL。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import unittest.mock as mock

# 将项目根目录加入 sys.path（直接运行时）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from haiji.agent import BaseAgent, agent, get_agent_registry
from haiji.agent.definition import AgentMode
from haiji.context.definition import ExecutionContext
from haiji.knowledge import (
    ChunkConfig,
    InMemoryKnowledgeStore,
    KnowledgeLoader,
    MockEmbedder,
    TextChunker,
)
from haiji.llm.definition import LlmMessage, LlmResponse, ToolCall
from haiji.memory.base import SessionMemoryManager
from haiji.observer import TokenUsage, get_observer, llm_span_ctx, reset_observer, tool_span_ctx
from haiji.rag import RagConfig, RagRetriever
from haiji.sse.base import SseEventEmitter
from haiji.tool.base import tool
from haiji.workspace import AgentWorkspace

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ─── 全局资源（延迟初始化）───────────────────────────────────────────────────
_EMBEDDER: MockEmbedder | None = None
_STORE: InMemoryKnowledgeStore | None = None
_RETRIEVER: RagRetriever | None = None


async def _build_knowledge_base() -> RagRetriever:
    """构建示例知识库（MockEmbedder，不真实调用 OpenAI）。"""
    global _EMBEDDER, _STORE, _RETRIEVER
    if _RETRIEVER is not None:
        return _RETRIEVER

    embedder = MockEmbedder(dim=64)
    store = InMemoryKnowledgeStore("demo_kb")
    loader = KnowledgeLoader()
    chunker = TextChunker(ChunkConfig(chunk_size=200, overlap=20))

    # 写入几条知识文档
    docs_texts = [
        ("haiji 是一个基于 Python 的 Multi-Agent 框架，支持全异步执行。", "readme"),
        ("REACT 模式下，Agent 会循环思考并调用 Tool，直到得到最终答案。", "agent_docs"),
        (
            "RAG 检索增强生成：将用户查询转为向量，与知识库做余弦相似度匹配，"
            "并将最相关的片段注入 Prompt。",
            "rag_docs",
        ),
        ("Observer 模块记录每次 LLM 调用的 token 消耗和工具调用的耗时。", "observer_docs"),
        ("AgentWorkspace 为每个 (agent_code, session_id) 提供隔离的键值持久化存储。", "workspace_docs"),
    ]

    for text, source in docs_texts:
        doc = await loader.load_text(text, source=source)
        chunks = chunker.chunk(doc)
        for chunk in chunks:
            chunk.embedding = await embedder.embed(chunk.content)
        store.add_document(doc, chunks)

    _EMBEDDER = embedder
    _STORE = store
    _RETRIEVER = RagRetriever(store, embedder, RagConfig(top_k=2, score_threshold=0.0))
    return _RETRIEVER


# ─── Tool：查询知识库 ────────────────────────────────────────────────────────

@tool(description="查询内部知识库，返回与问题最相关的知识片段")
async def query_kb(query: str) -> str:
    """
    查询知识库。

    Args:
        query: 用户的查询问题

    Returns:
        相关知识片段文本
    """
    retriever = await _build_knowledge_base()
    result = await retriever.retrieve(query)
    if not result.chunks:
        return "知识库中未找到相关内容。"
    return result.injected_text


# ─── Agent 定义 ──────────────────────────────────────────────────────────────

@agent(mode="react", tools=["query_kb"], max_rounds=3)
class RagDemoAgent(BaseAgent):
    """演示 RAG 联动的 Agent。"""
    system_prompt = (
        "你是一个知识助手。当用户提问时，先使用 query_kb 工具查询知识库，"
        "再基于检索结果回答用户的问题。"
    )


# ─── Mock LLM Client ────────────────────────────────────────────────────────

def _make_mock_llm_client(retriever: RagRetriever) -> mock.AsyncMock:
    """
    构造一个 Mock LLM Client。

    第一轮（chat_with_tools）：LLM 决定调用 query_kb 工具。
    第二轮（chat_with_tools）：LLM 基于工具结果给出最终回答。
    """
    call_count = 0

    async def mock_chat_with_tools(request: object) -> LlmResponse:
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            # 第一轮：决定调用工具
            return LlmResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_001",
                        name="query_kb",
                        arguments='{"query": "haiji 框架是什么？"}',
                    )
                ],
                finish_reason="tool_calls",
            )
        else:
            # 第二轮：给出最终回答
            return LlmResponse(
                content=(
                    "根据知识库的信息：haiji 是一个基于 Python 的 Multi-Agent 框架，"
                    "支持全异步执行，REACT 模式支持循环思考并调用 Tool。"
                ),
                tool_calls=None,
                finish_reason="stop",
            )

    async def mock_stream_chat(request: object):  # type: ignore[override]
        resp = await mock_chat_with_tools(request)
        if resp.content:
            yield resp.content

    client = mock.AsyncMock()
    client.chat_with_tools = mock_chat_with_tools
    client.stream_chat = mock_stream_chat
    return client


# ─── 主流程 ──────────────────────────────────────────────────────────────────

async def main() -> None:
    print("=" * 60)
    print("🦐 haiji 第二期集成示例：RAG + workspace + observer")
    print("=" * 60)

    # Step 1：构建知识库
    print("\n[1/5] 构建内存知识库（MockEmbedder）...")
    retriever = await _build_knowledge_base()
    assert _STORE is not None
    info = _STORE.info()
    print(f"    知识库 '{info.store_id}' 已就绪：{info.doc_count} 篇文档，{info.chunk_count} 个片段")

    # Step 2：初始化 Observer
    print("\n[2/5] 初始化 Observer...")
    reset_observer()
    observer = get_observer()

    ctx = ExecutionContext.create(session_id="demo_session", agent_code="RagDemoAgent")
    trace = observer.start_trace(ctx.trace_id, ctx.agent_code, ctx.session_id)
    print(f"    Trace 已开启：trace_id={trace.trace_id}")

    # Step 3：运行 Agent（Mock LLM，不花钱）
    print("\n[3/5] 运行 RagDemoAgent（REACT 模式）...")
    mock_client = _make_mock_llm_client(retriever)

    # 手动追踪 LLM 调用（示意 observer 联动方式）
    async with llm_span_ctx(observer, ctx.trace_id, ctx.agent_code, "mock-model") as llm_ctx:
        memory = SessionMemoryManager()
        emitter = SseEventEmitter()

        agent_instance = RagDemoAgent()

        # 并发：运行 Agent + 消费事件
        collected_tokens: list[str] = []

        async def consume_events() -> None:
            async for event in emitter.events():
                if event.type.value == "token" and event.message:
                    collected_tokens.append(event.message)
                elif event.type.value == "tool_call":
                    # 追踪 Tool 调用
                    async with tool_span_ctx(
                        observer, ctx.trace_id, ctx.agent_code, event.tool_name or "unknown"
                    ):
                        pass  # 实际执行由 Agent 内部完成
                    print(f"    📞 Tool 调用：{event.tool_name}({event.message or ''})")
                elif event.type.value == "tool_result":
                    print(f"    ✅ Tool 结果已收到")
                elif event.type.value == "error":
                    print(f"    ❌ 错误：{event.message}")

        await asyncio.gather(
            agent_instance.stream_chat(
                "haiji 框架是什么？有什么特点？",
                ctx,
                emitter,
                memory,
                mock_client,
            ),
            consume_events(),
        )

        llm_ctx.set_usage(TokenUsage(prompt_tokens=120, completion_tokens=80, total_tokens=200))

    final_answer = "".join(collected_tokens)
    print(f"\n    Agent 回答：{final_answer[:200]}{'...' if len(final_answer) > 200 else ''}")

    # Step 4：写入 AgentWorkspace，验证持久化
    print("\n[4/5] 验证 AgentWorkspace 持久化...")
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = AgentWorkspace(tmpdir, "RagDemoAgent", "demo_session")

        # 写入查询结果
        result_data = json.dumps(
            {
                "query": "haiji 框架是什么？",
                "answer": final_answer,
                "session_id": ctx.session_id,
            },
            ensure_ascii=False,
        )
        await ws.write("last_query_result", result_data)

        # 读回验证
        read_back = await ws.read("last_query_result")
        parsed = json.loads(read_back)
        assert parsed["query"] == "haiji 框架是什么？", "workspace 读写不一致！"

        keys = await ws.list_keys()
        ws_info = await ws.info()
        print(f"    ✅ Workspace 写入/读取正常")
        print(f"    存储键：{keys}，条目数：{ws_info.entry_count}")

    # Step 5：Observer 报告
    print("\n[5/5] Observer 链路追踪报告...")
    finished_trace = observer.finish_trace(ctx.trace_id)
    print(f"    trace_id：{finished_trace.trace_id}")
    print(f"    LLM 调用次数：{len(finished_trace.llm_spans)}")
    print(f"    Tool 调用次数：{len(finished_trace.tool_spans)}")
    print(
        f"    总 token 消耗："
        f"prompt={finished_trace.total_tokens.prompt_tokens}, "
        f"completion={finished_trace.total_tokens.completion_tokens}, "
        f"total={finished_trace.total_tokens.total_tokens}"
    )

    print("\n" + "=" * 60)
    print("✅ 第二期集成示例（RAG + workspace + observer）运行成功！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
