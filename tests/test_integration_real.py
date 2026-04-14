"""
真实 LLM 集成测试
使用小红书 MaaS 平台（minimax-m2.7）验证端到端链路

运行方式:
    pytest tests/test_integration_real.py -v -s

前提条件:
    .env 文件中配置了 HAIJI_API_KEY 和 HAIJI_LLM_BASE_URL
"""
import asyncio
import os
import uuid
import pytest
from pathlib import Path

# 加载 .env
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

API_KEY  = os.environ.get("HAIJI_API_KEY", "")
BASE_URL = os.environ.get("HAIJI_LLM_BASE_URL", "")
MODEL    = os.environ.get("HAIJI_LLM_MODEL", "minimax-m2.7")

pytestmark = pytest.mark.skipif(
    not API_KEY,
    reason="需要 HAIJI_API_KEY，跳过真实 LLM 测试"
)

# ── 全局 client fixture ──────────────────────────────────────
@pytest.fixture(scope="module")
def llm_client():
    from haiji.llm.impl.openai import OpenAILlmClient
    from haiji.config import HaijiConfig, set_config, reset_config
    cfg = HaijiConfig(
        api_key=API_KEY,
        llm_base_url=BASE_URL,
        llm_model=MODEL,
        llm_timeout=60,
    )
    set_config(cfg)
    yield OpenAILlmClient(cfg)
    reset_config()


# ── helper：收集 emitter 里的 token 拼成字符串 ────────────────
def collect_reply(emitter) -> str:
    from haiji.sse import SseEventType
    tokens = []
    while not emitter._queue.empty():
        e = emitter._queue.get_nowait()
        if e is None:  # 哨兵值，跳过
            continue
        if e.type == SseEventType.TOKEN and e.message:
            tokens.append(e.message)
    return "".join(tokens)


def collect_events(emitter) -> list:
    """收集所有非 None 事件"""
    events = []
    while not emitter._queue.empty():
        e = emitter._queue.get_nowait()
        if e is not None:
            events.append(e)
    return events


def make_ctx(agent_code: str) -> "ExecutionContext":
    from haiji.context import ExecutionContext
    return ExecutionContext(
        session_id=str(uuid.uuid4()),
        agent_code=agent_code,
        trace_id=str(uuid.uuid4()),
        user_id="test_user",
    )


# ════════════════════════════════════════════════════════════
# TEST 1: LLM 基本连通性（非流式）
# ════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_llm_basic_chat(llm_client):
    from haiji.llm import LlmRequest, LlmMessage
    req = LlmRequest(
        messages=[
            LlmMessage(role="system", content="你是一个简洁的助手，只回答数字。"),
            LlmMessage(role="user", content="1+1等于几？只回答数字"),
        ],
        temperature=0.1,
        max_tokens=20,
    )
    resp = await llm_client.chat(req)
    print(f"\n[T1 LLM Basic] reply={resp.content!r}  usage={resp.usage}")
    assert resp.content, "响应内容不应为空"
    if resp.usage:
        assert resp.usage.total_tokens > 0


# ════════════════════════════════════════════════════════════
# TEST 2: LLM 流式输出
# ════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_llm_stream_chat(llm_client):
    from haiji.llm import LlmRequest, LlmMessage
    req = LlmRequest(
        messages=[
            LlmMessage(role="user", content="用三个词形容春天，用逗号隔开"),
        ],
        temperature=0.5,
        max_tokens=30,
        stream=True,
    )
    tokens = []
    async for tok in llm_client.stream_chat(req):
        tokens.append(tok)
        print(tok, end="", flush=True)
    print()
    full = "".join(tokens)
    print(f"[T2 LLM Stream] full={full!r}")
    assert len(full) > 0


# ════════════════════════════════════════════════════════════
# TEST 3: LLM Function Calling
# ════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_llm_function_calling(llm_client):
    from haiji.llm import LlmRequest, LlmMessage, LlmTool, FunctionDef
    calc_tool = LlmTool(
        type="function",
        function=FunctionDef(
            name="calculate",
            description="执行数学计算，返回结果",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "数学表达式，如 '37 * 42'"}
                },
                "required": ["expression"],
            },
        ),
    )
    req = LlmRequest(
        messages=[
            LlmMessage(role="system", content="你是一个助手，遇到数学问题必须调用 calculate 工具。"),
            LlmMessage(role="user", content="请帮我计算 37 乘以 42"),
        ],
        tools=[calc_tool],
        temperature=0.1,
        max_tokens=200,
    )
    resp = await llm_client.chat_with_tools(req)
    print(f"\n[T3 FuncCall] content={resp.content!r}")
    print(f"[T3 FuncCall] tool_calls={resp.tool_calls}")
    assert resp.content is not None or resp.tool_calls, "应有 content 或 tool_calls"


# ════════════════════════════════════════════════════════════
# TEST 4: DIRECT Agent 端到端
# ════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_direct_agent_e2e(llm_client):
    from haiji.agent.base import BaseAgent
    from haiji.agent import agent, AgentMode
    from haiji.memory import SessionMemoryManager
    from haiji.sse import SseEventEmitter

    @agent(mode="direct", code="t4_direct", max_rounds=1)
    class DirectTestAgent(BaseAgent):
        system_prompt = "你是一个简洁的助手，回答不超过30字。"

    a = DirectTestAgent()
    ctx = make_ctx("t4_direct")
    mem = SessionMemoryManager()
    emitter = SseEventEmitter()

    await a.stream_chat("你好，用一句话介绍自己", ctx, emitter, mem, llm_client=llm_client)
    reply = collect_reply(emitter)
    print(f"\n[T4 DIRECT] reply={reply!r}")
    assert len(reply) > 0, "DIRECT Agent 应有输出"


# ════════════════════════════════════════════════════════════
# TEST 5: REACT Agent + Tool 调用
# ════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_react_agent_with_tool(llm_client):
    from haiji.tool import tool, get_tool_registry
    from haiji.agent.base import BaseAgent
    from haiji.agent import agent, AgentMode
    from haiji.memory import SessionMemoryManager
    from haiji.sse import SseEventEmitter, SseEventType

    registry = get_tool_registry()

    @tool(description="执行 Python 数学表达式，返回计算结果", code="t5_calculate")
    async def calculate(expression: str) -> str:
        try:
            allowed = set("0123456789+-*/().% ")
            if not all(c in allowed for c in expression):
                return "表达式包含非法字符"
            result = eval(expression, {"__builtins__": {}}, {})
            return str(result)
        except Exception as e:
            return f"计算错误: {e}"

    @agent(mode="react", code="t5_react", tools=["t5_calculate"], max_rounds=5)
    class ReactTestAgent(BaseAgent):
        system_prompt = "你是一个数学助手。遇到计算问题，必须调用 t5_calculate 工具计算，不要自己心算。"

    a = ReactTestAgent()
    ctx = make_ctx("t5_react")
    mem = SessionMemoryManager()
    emitter = SseEventEmitter()

    await a.stream_chat("请帮我计算 123 * 456 + 789", ctx, emitter, mem, llm_client=llm_client)

    events = collect_events(emitter)
    tool_calls = [e for e in events if e.type == SseEventType.TOOL_CALL]
    tokens = [e.message for e in events if e.type == SseEventType.TOKEN and e.message]
    reply = "".join(tokens)

    print(f"\n[T5 REACT] tool_calls={len(tool_calls)}  reply={reply!r}")
    assert len(reply) > 0, "REACT Agent 应有最终输出"
    # 正确答案是 56877，回复里应该包含
    assert "56877" in reply or "56,877" in reply, f"期望包含 56877，实际: {reply}"


# ════════════════════════════════════════════════════════════
# TEST 6: Memory 多轮对话
# ════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_multi_turn_memory(llm_client):
    from haiji.agent.base import BaseAgent
    from haiji.agent import agent
    from haiji.memory import SessionMemoryManager
    from haiji.sse import SseEventEmitter

    @agent(mode="direct", code="t6_memory", max_rounds=1)
    class MemoryTestAgent(BaseAgent):
        system_prompt = "你是一个助手，请认真记住用户告诉你的信息，回答不超过40字。"

    a = MemoryTestAgent()
    session_id = str(uuid.uuid4())
    mem = SessionMemoryManager()

    async def chat(msg: str) -> str:
        from haiji.context import ExecutionContext
        ctx = ExecutionContext(
            session_id=session_id,
            agent_code="t6_memory",
            trace_id=str(uuid.uuid4()),
            user_id="test_user",
        )
        emitter = SseEventEmitter()
        await a.stream_chat(msg, ctx, emitter, mem, llm_client=llm_client)
        return collect_reply(emitter)

    reply1 = await chat("我叫祎晗，我是一个后端工程师，正在做 haji-ai 项目")
    print(f"\n[T6 Memory R1] {reply1!r}")

    reply2 = await chat("你还记得我叫什么名字吗？")
    print(f"[T6 Memory R2] {reply2!r}")

    history = mem.get_history(session_id)
    print(f"[T6 Memory] history_len={len(history)}")

    assert len(history) >= 4, f"应有至少4条历史，实际 {len(history)}"
    assert "祎晗" in reply2, f"Agent 应记住用户名字，实际回复: {reply2}"


# ════════════════════════════════════════════════════════════
# TEST 7: RAG 知识注入 + Agent
# ════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_rag_inject_to_agent(llm_client):
    from haiji.knowledge import (
        TextChunker, ChunkConfig, KnowledgeDocument,
        InMemoryKnowledgeStore, MockEmbedder,
    )
    from haiji.rag import RagRetriever, RagConfig
    from haiji.agent.base import BaseAgent
    from haiji.agent import agent
    from haiji.memory import SessionMemoryManager
    from haiji.sse import SseEventEmitter

    # 1. 构建知识库
    knowledge_text = (
        "哈基AI（haji-ai）是一个基于 Python 的 Multi-Agent 框架。"
        "支持三种 Agent 执行模式：DIRECT（直接问答）、REACT（循环推理+工具调用）、"
        "PLAN_AND_EXECUTE（先规划后执行）。"
        "哈基AI的核心特点：全异步执行（asyncio）、Pydantic 参数校验、"
        "Skill 动态加载、内置可观测性（链路追踪、token 统计）。"
        "哈基AI由吕祎晗开发，是他的个人开源项目，目标是易于调用并支持 AI 驱动的 Agent 设计。"
    )
    doc = KnowledgeDocument(doc_id="haji-doc", source="readme", content=knowledge_text)
    chunker = TextChunker(ChunkConfig(chunk_size=150, overlap=20))
    chunks = chunker.chunk(doc)

    embedder = MockEmbedder(dim=16, seed=42)
    chunks_with_emb = []
    for c in chunks:
        c.embedding = await embedder.embed(c.content)
        chunks_with_emb.append(c)

    store = InMemoryKnowledgeStore()
    store.add_document(doc, chunks_with_emb)

    # 2. RAG 检索
    rag = RagRetriever(
        store=store,
        embedder=embedder,
        config=RagConfig(top_k=3, score_threshold=0.0),
    )
    rag_result = await rag.retrieve("哈基AI支持哪些Agent模式")
    print(f"\n[T7 RAG] chunks={len(rag_result.chunks)}")
    print(f"[T7 RAG] injected preview: {rag_result.injected_text[:80]}...")
    assert len(rag_result.chunks) > 0

    # 3. 注入 system prompt
    enhanced_prompt = (
        "你是哈基AI的专属助手。\n\n"
        "以下是相关知识：\n"
        f"{rag_result.injected_text}\n\n"
        "请基于以上知识回答用户问题，回答不超过60字。"
    )

    @agent(mode="direct", code="t7_rag", max_rounds=1)
    class RagTestAgent(BaseAgent):
        pass  # system_prompt 动态传入，通过 definition 覆盖

    # 直接修改 definition 的 system_prompt
    from haiji.agent.definition import AgentDefinition, AgentMode
    RagTestAgent._agent_definition = AgentDefinition(
        code="t7_rag",
        name="知识助手",
        mode=AgentMode.DIRECT,
        system_prompt=enhanced_prompt,
        max_rounds=1,
    )

    a = RagTestAgent()
    ctx = make_ctx("t7_rag")
    mem = SessionMemoryManager()
    emitter = SseEventEmitter()

    await a.stream_chat("哈基AI支持哪些Agent执行模式？", ctx, emitter, mem, llm_client=llm_client)
    reply = collect_reply(emitter)
    print(f"[T7 RAG Agent] reply={reply!r}")

    assert len(reply) > 0
    assert any(kw in reply for kw in ["DIRECT", "REACT", "PLAN", "直接", "推理", "规划", "模式", "三种"]), \
        f"回复应包含 Agent 模式相关内容，实际: {reply}"


# ════════════════════════════════════════════════════════════
# TEST 8: Observer 追踪真实 LLM 用量
# ════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_observer_traces_real_llm(llm_client):
    from haiji.llm import LlmRequest, LlmMessage
    from haiji.observer import get_observer, reset_observer, llm_span_ctx, TokenUsage

    reset_observer()
    obs = get_observer()
    trace_id = str(uuid.uuid4())
    obs.start_trace(trace_id, "test_agent", "test_session")

    req = LlmRequest(
        messages=[LlmMessage(role="user", content="你好")],
        max_tokens=20,
        temperature=0.1,
    )

    async with llm_span_ctx(obs, trace_id, "test_agent", MODEL) as span_ctx:
        resp = await llm_client.chat(req)
        if resp.usage:
            span_ctx.set_usage(TokenUsage(
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                total_tokens=resp.usage.total_tokens,
            ))
        else:
            # 部分平台不返回 usage，手动估算
            span_ctx.set_usage(TokenUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20))

    record = obs.finish_trace(trace_id)
    print(f"\n[T8 Observer] total_tokens={record.total_tokens.total_tokens}")
    print(f"[T8 Observer] latency_ms={record.llm_spans[0].latency_ms:.1f}ms")

    assert record.total_tokens.total_tokens > 0
    assert len(record.llm_spans) == 1
    assert record.llm_spans[0].latency_ms > 0
