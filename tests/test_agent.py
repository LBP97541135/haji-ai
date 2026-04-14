"""
tests/test_agent.py - Agent 模块单元测试

覆盖：
- AgentDefinition 数据结构
- AgentRegistry 注册与查找
- @agent 装饰器
- DIRECT 模式正常执行
- REACT 模式正常执行（含 Tool 调用）
- REACT 循环超轮次终止
- Multi-Agent 互调防循环检测
- Tool 执行（包括 Tool 不存在的情况）
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from haiji.agent.base import BaseAgent, agent, DirectExecutor, ReactLoopExecutor
from haiji.agent.definition import AgentCallFrame, AgentDefinition, AgentMode
from haiji.agent.exceptions import (
    AgentCircularCallError,
    AgentConfigError,
    AgentMaxRoundsError,
    AgentToolNotFoundError,
)
from haiji.agent.registry import AgentRegistry, get_agent_registry
from haiji.context.definition import ExecutionContext, ToolCallContext
from haiji.llm.definition import LlmMessage, LlmRequest, LlmResponse, ToolCall
from haiji.memory.base import SessionMemoryManager
from haiji.sse.base import SseEventEmitter
from haiji.sse.definition import SseEventType
from haiji.tool.base import get_tool_registry, tool


# ---------------------------------------------------------------------------
# 测试辅助：Mock LLM Client
# ---------------------------------------------------------------------------


def make_mock_llm(
    chat_response: Optional[LlmResponse] = None,
    stream_tokens: Optional[list[str]] = None,
) -> MagicMock:
    """创建一个 Mock LLM 客户端"""
    mock_llm = MagicMock()

    # chat_with_tools：返回 LlmResponse
    if chat_response is None:
        chat_response = LlmResponse(content="这是 LLM 的回答", tool_calls=None)
    mock_llm.chat_with_tools = AsyncMock(return_value=chat_response)
    mock_llm.chat = AsyncMock(return_value=chat_response)

    # stream_chat：返回 async generator
    if stream_tokens is None:
        stream_tokens = ["你好", "，我", "是助手"]

    async def _stream_gen(*args, **kwargs) -> AsyncGenerator[str, None]:
        for token in stream_tokens:
            yield token

    mock_llm.stream_chat = _stream_gen

    return mock_llm


async def collect_events(emitter: SseEventEmitter) -> list:
    """收集 emitter 的所有事件"""
    events = []
    async for event in emitter.events():
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# 测试夹具：隔离 ToolRegistry 和 AgentRegistry
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_registries():
    """每个测试使用独立的注册表，避免全局状态污染"""
    with (
        patch("haiji.agent.base.get_tool_registry") as mock_tool_reg,
        patch("haiji.agent.base.get_agent_registry") as mock_agent_reg,
        patch("haiji.agent.base.get_skill_registry") as mock_skill_reg,
        patch("haiji.agent.registry.get_agent_registry"),
    ):
        # tool registry：默认无 tool
        tool_reg = MagicMock()
        tool_reg.get = MagicMock(return_value=None)
        mock_tool_reg.return_value = tool_reg

        # agent registry：默认无 agent
        agent_reg = AgentRegistry()
        mock_agent_reg.return_value = agent_reg

        # skill registry：默认无 skill
        skill_reg = MagicMock()
        skill_reg.get = MagicMock(return_value=None)
        skill_reg.all = MagicMock(return_value=[])
        mock_skill_reg.return_value = skill_reg

        yield {
            "tool_reg": tool_reg,
            "agent_reg": agent_reg,
            "skill_reg": skill_reg,
        }


# ---------------------------------------------------------------------------
# TASK-009-T001 AgentDefinition 数据结构
# ---------------------------------------------------------------------------


def test_agent_definition_defaults():
    """AgentDefinition 默认值正确"""
    defn = AgentDefinition(code="my_agent")
    assert defn.code == "my_agent"
    assert defn.name == "my_agent"  # model_post_init 填充
    assert defn.mode == AgentMode.REACT
    assert defn.max_rounds == 10
    assert defn.required_skill_codes == []
    assert defn.required_tool_codes == []


def test_agent_definition_custom_values():
    """AgentDefinition 自定义字段正确"""
    defn = AgentDefinition(
        code="test",
        name="测试 Agent",
        mode=AgentMode.DIRECT,
        system_prompt="你是助手",
        required_skill_codes=["s1", "s2"],
        max_rounds=5,
    )
    assert defn.mode == AgentMode.DIRECT
    assert defn.max_rounds == 5
    assert defn.required_skill_codes == ["s1", "s2"]


# ---------------------------------------------------------------------------
# TASK-009-T002 AgentRegistry
# ---------------------------------------------------------------------------


def test_agent_registry_register_and_get():
    """AgentRegistry 注册和查找正常"""
    registry = AgentRegistry()

    # 创建一个带 _agent_definition 的类
    class FakeAgent(BaseAgent):
        pass

    FakeAgent._agent_definition = AgentDefinition(code="fake_agent")

    registry.register_class(FakeAgent)
    assert registry.get("fake_agent") is FakeAgent
    assert "fake_agent" in registry.all_codes()
    assert len(registry) == 1


def test_agent_registry_get_missing_returns_none():
    """查找不存在的 Agent 返回 None"""
    registry = AgentRegistry()
    assert registry.get("not_exist") is None


def test_agent_registry_overwrite_warns(caplog):
    """重复注册同一个 code 会发出警告"""
    import logging
    registry = AgentRegistry()

    class AgentA(BaseAgent):
        pass

    AgentA._agent_definition = AgentDefinition(code="dup")
    registry.register_class(AgentA)

    class AgentB(BaseAgent):
        pass

    AgentB._agent_definition = AgentDefinition(code="dup")
    with caplog.at_level(logging.WARNING, logger="haiji.agent.registry"):
        registry.register_class(AgentB)

    assert "已存在，将被覆盖" in caplog.text
    assert registry.get("dup") is AgentB


# ---------------------------------------------------------------------------
# TASK-009-T003 @agent 装饰器
# ---------------------------------------------------------------------------


def test_agent_decorator_registers_class(isolated_registries):
    """@agent 装饰器成功注册 Agent 并注入 _agent_definition"""
    agent_reg: AgentRegistry = isolated_registries["agent_reg"]

    @agent(mode="direct")
    class SimpleAgent(BaseAgent):
        system_prompt = "测试"

    assert hasattr(SimpleAgent, "_agent_definition")
    defn: AgentDefinition = SimpleAgent._agent_definition
    assert defn.code == "SimpleAgent"
    assert defn.mode == AgentMode.DIRECT
    assert defn.system_prompt == "测试"

    # 应已注册到 registry
    assert agent_reg.get("SimpleAgent") is SimpleAgent


def test_agent_decorator_custom_code(isolated_registries):
    """@agent 支持自定义 code"""
    agent_reg: AgentRegistry = isolated_registries["agent_reg"]

    @agent(mode="react", code="custom_code", max_rounds=3)
    class SomeAgent(BaseAgent):
        pass

    defn: AgentDefinition = SomeAgent._agent_definition
    assert defn.code == "custom_code"
    assert defn.max_rounds == 3
    assert agent_reg.get("custom_code") is SomeAgent


def test_agent_decorator_with_skills(isolated_registries):
    """@agent 中 skills 参数转换为 skill_codes"""

    @agent(mode="react", skills=["s1", "s2"])
    class AgentWithSkills(BaseAgent):
        pass

    defn: AgentDefinition = AgentWithSkills._agent_definition
    assert defn.required_skill_codes == ["s1", "s2"]


# ---------------------------------------------------------------------------
# TASK-009-T004 BaseAgent 未注册时抛出异常
# ---------------------------------------------------------------------------


def test_base_agent_without_decorator_raises():
    """未通过 @agent 注册的 BaseAgent 实例化时抛出 AgentConfigError"""

    class RawAgent(BaseAgent):
        pass

    with pytest.raises(AgentConfigError, match="未通过 @agent 装饰器注册"):
        RawAgent()


# ---------------------------------------------------------------------------
# TASK-009-T005 DIRECT 模式正常执行
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_mode_stream_chat(isolated_registries):
    """DIRECT 模式：LLM 流式输出，emit token 事件，最终 emit done"""

    @agent(mode="direct", code="direct_test")
    class DirectTestAgent(BaseAgent):
        system_prompt = "你是助手"

    mock_llm = make_mock_llm(stream_tokens=["Hello", " World"])
    instance = DirectTestAgent()
    ctx = ExecutionContext.create(session_id="sess_1", agent_code="direct_test")
    memory = SessionMemoryManager()
    emitter = SseEventEmitter()

    events_task = asyncio.create_task(collect_events(emitter))
    await instance.stream_chat("你好", ctx, emitter, memory, llm_client=mock_llm)
    events = await events_task

    token_events = [e for e in events if e.type == SseEventType.TOKEN]
    done_events = [e for e in events if e.type == SseEventType.DONE]

    assert len(token_events) == 2
    assert token_events[0].message == "Hello"
    assert token_events[1].message == " World"
    assert len(done_events) == 1
    assert done_events[0].message == "Hello World"


@pytest.mark.asyncio
async def test_direct_mode_saves_to_memory(isolated_registries):
    """DIRECT 模式：执行后将 assistant 消息保存到 memory"""

    @agent(mode="direct", code="direct_memory_test")
    class DirectMemAgent(BaseAgent):
        pass

    mock_llm = make_mock_llm(stream_tokens=["回答内容"])
    instance = DirectMemAgent()
    ctx = ExecutionContext.create(session_id="sess_2", agent_code="direct_memory_test")
    memory = SessionMemoryManager()
    emitter = SseEventEmitter()

    events_task = asyncio.create_task(collect_events(emitter))
    await instance.stream_chat("问题", ctx, emitter, memory, llm_client=mock_llm)
    await events_task

    history = memory.get_history("sess_2")
    # 包含 user 消息 + assistant 消息
    assert len(history) >= 2
    roles = [m.role for m in history]
    assert "user" in roles
    assert "assistant" in roles


# ---------------------------------------------------------------------------
# TASK-009-T006 REACT 模式正常执行
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_react_mode_no_tool_call(isolated_registries):
    """REACT 模式：LLM 直接回答（无 tool_calls），emit token + done"""

    @agent(mode="react", code="react_no_tool")
    class ReactNoToolAgent(BaseAgent):
        system_prompt = "你是助手"

    # LLM 第一次就返回最终答案，无 tool_calls
    response = LlmResponse(content="直接回答", tool_calls=None)
    mock_llm = make_mock_llm(chat_response=response)

    instance = ReactNoToolAgent()
    ctx = ExecutionContext.create(session_id="sess_react_1", agent_code="react_no_tool")
    memory = SessionMemoryManager()
    emitter = SseEventEmitter()

    events_task = asyncio.create_task(collect_events(emitter))
    await instance.stream_chat("问题", ctx, emitter, memory, llm_client=mock_llm)
    events = await events_task

    done_events = [e for e in events if e.type == SseEventType.DONE]
    assert len(done_events) == 1
    assert done_events[0].message == "直接回答"


@pytest.mark.asyncio
async def test_react_mode_with_tool_call(isolated_registries):
    """REACT 模式：LLM 调用 Tool，执行结果追加后 LLM 再次回答"""

    @agent(mode="react", code="react_with_tool")
    class ReactToolAgent(BaseAgent):
        pass

    # 第一轮：LLM 返回 tool_call
    # 第二轮：LLM 返回最终答案
    tool_call_response = LlmResponse(
        content=None,
        tool_calls=[ToolCall(id="call_1", name="my_tool", arguments='{"query": "test"}')],
    )
    final_response = LlmResponse(content="工具执行后的回答", tool_calls=None)

    mock_llm = MagicMock()
    mock_llm.chat_with_tools = AsyncMock(side_effect=[tool_call_response, final_response])
    mock_llm.chat = AsyncMock(return_value=final_response)

    async def _stream(*args, **kwargs):
        yield "工具执行后的回答"

    mock_llm.stream_chat = _stream

    # 注册一个 mock Tool
    mock_tool = MagicMock()
    mock_tool.execute = AsyncMock(return_value="工具执行结果")
    isolated_registries["tool_reg"].get = MagicMock(side_effect=lambda code: mock_tool if code == "my_tool" else None)

    instance = ReactToolAgent()
    ctx = ExecutionContext.create(session_id="sess_react_2", agent_code="react_with_tool")
    memory = SessionMemoryManager()
    emitter = SseEventEmitter()

    events_task = asyncio.create_task(collect_events(emitter))
    await instance.stream_chat("查工具", ctx, emitter, memory, llm_client=mock_llm)
    events = await events_task

    tool_call_events = [e for e in events if e.type == SseEventType.TOOL_CALL]
    tool_result_events = [e for e in events if e.type == SseEventType.TOOL_RESULT]
    done_events = [e for e in events if e.type == SseEventType.DONE]

    assert len(tool_call_events) == 1
    assert tool_call_events[0].tool_name == "my_tool"
    assert len(tool_result_events) == 1
    assert "工具执行结果" in tool_result_events[0].data
    assert len(done_events) == 1


# ---------------------------------------------------------------------------
# TASK-009-T007 REACT 超轮次终止
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_react_agent_stops_after_max_rounds(isolated_registries):
    """REACT 循环超出 max_rounds 时终止并 emit error 事件"""

    @agent(mode="react", code="react_max_rounds", max_rounds=2)
    class ReactMaxAgent(BaseAgent):
        pass

    # 每次都返回 tool_call，永远不返回最终答案 → 触发超轮次
    tool_call_response = LlmResponse(
        content=None,
        tool_calls=[ToolCall(id="call_x", name="loop_tool", arguments="{}")],
    )
    mock_llm = MagicMock()
    mock_llm.chat_with_tools = AsyncMock(return_value=tool_call_response)

    # 注册 loop_tool
    mock_tool = MagicMock()
    mock_tool.execute = AsyncMock(return_value="循环结果")
    isolated_registries["tool_reg"].get = MagicMock(return_value=mock_tool)

    instance = ReactMaxAgent()
    ctx = ExecutionContext.create(session_id="sess_max", agent_code="react_max_rounds")
    memory = SessionMemoryManager()
    emitter = SseEventEmitter()

    events_task = asyncio.create_task(collect_events(emitter))
    await instance.stream_chat("触发循环", ctx, emitter, memory, llm_client=mock_llm)
    events = await events_task

    error_events = [e for e in events if e.type == SseEventType.ERROR]
    assert len(error_events) == 1
    assert "max_rounds" in error_events[0].message or "最大轮次" in error_events[0].message

    # LLM 调用次数应等于 max_rounds
    assert mock_llm.chat_with_tools.call_count == 2


# ---------------------------------------------------------------------------
# TASK-009-T008 Multi-Agent 防循环检测
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_registry_prevents_circular_calls(isolated_registries):
    """
    Multi-Agent 互调防循环：
    当 Agent A 调用自身（或已在调用栈中的 Agent）时抛出 AgentCircularCallError
    """
    agent_reg: AgentRegistry = isolated_registries["agent_reg"]

    @agent(mode="react", code="agent_a_circular")
    class AgentA(BaseAgent):
        pass

    # 将 AgentA 注册到 mock agent_reg
    agent_reg.register_class(AgentA)
    isolated_registries["agent_reg"].get = MagicMock(
        side_effect=lambda code: AgentA if code == "agent_a_circular" else None
    )

    # 构建已包含 agent_a_circular 的调用栈（模拟已在执行中）
    existing_call_stack = [
        AgentCallFrame(agent_code="agent_a_circular", session_id="sess_circular")
    ]

    instance = AgentA()
    ctx = ExecutionContext.create(session_id="sess_circular", agent_code="agent_a_circular")

    # 模拟 Tool 调用：tool_code = "agent_a_circular"（即自身）
    tool_call = ToolCall(id="tc_1", name="agent_a_circular", arguments='{"message": "hello"}')

    # execute_tool 应检测到循环并抛出异常
    with pytest.raises(AgentCircularCallError, match="循环调用"):
        await instance.execute_tool(
            tool_call=tool_call,
            ctx=ctx,
            call_stack=existing_call_stack,
        )


# ---------------------------------------------------------------------------
# TASK-009-T009 Tool 不存在时抛出异常
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_tool_not_found_raises(isolated_registries):
    """调用未注册 Tool 时抛出 AgentToolNotFoundError"""
    isolated_registries["tool_reg"].get = MagicMock(return_value=None)
    # agent_reg 也找不到
    isolated_registries["agent_reg"].get = MagicMock(return_value=None)

    @agent(mode="react", code="tool_not_found_agent")
    class ToolNotFoundAgent(BaseAgent):
        pass

    instance = ToolNotFoundAgent()
    ctx = ExecutionContext.create(session_id="sess_tnf", agent_code="tool_not_found_agent")

    tool_call = ToolCall(id="tc_miss", name="missing_tool", arguments="{}")

    with pytest.raises(AgentToolNotFoundError, match="未注册"):
        await instance.execute_tool(tool_call=tool_call, ctx=ctx, call_stack=[])


# ---------------------------------------------------------------------------
# TASK-009-T010 AgentCallFrame
# ---------------------------------------------------------------------------


def test_agent_call_frame():
    """AgentCallFrame 正确存储调用信息"""
    frame = AgentCallFrame(agent_code="my_agent", session_id="sess_xyz")
    assert frame.agent_code == "my_agent"
    assert frame.session_id == "sess_xyz"


# ---------------------------------------------------------------------------
# TASK-009-T011 stream_chat 异常时 emit error 事件
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_chat_unexpected_error_emits_error_event(isolated_registries):
    """stream_chat 遇到未预期异常时，emit error 事件而非直接抛出"""

    @agent(mode="react", code="error_agent")
    class ErrorAgent(BaseAgent):
        pass

    mock_llm = MagicMock()
    mock_llm.chat_with_tools = AsyncMock(side_effect=RuntimeError("突发错误"))

    instance = ErrorAgent()
    ctx = ExecutionContext.create(session_id="sess_err", agent_code="error_agent")
    memory = SessionMemoryManager()
    emitter = SseEventEmitter()

    events_task = asyncio.create_task(collect_events(emitter))
    await instance.stream_chat("触发异常", ctx, emitter, memory, llm_client=mock_llm)
    events = await events_task

    error_events = [e for e in events if e.type == SseEventType.ERROR]
    assert len(error_events) == 1
    assert "突发错误" in error_events[0].message or "失败" in error_events[0].message


# ---------------------------------------------------------------------------
# TASK-009-T012 prepare_execution 加载 Skills 和 Tools
# ---------------------------------------------------------------------------


def test_prepare_execution_collects_tools(isolated_registries):
    """_prepare_execution 从 Skill 和直接声明的 Tool 中收集 LlmTool 列表"""
    from haiji.skill.definition import SkillEntry, XSkillDef
    from haiji.tool.definition import ToolMeta

    # 构造一个 mock Skill，带一个 tool_code
    skill_entry = MagicMock(spec=SkillEntry)
    skill_entry.definition = XSkillDef(
        code="test_skill",
        name="测试 Skill",
        description="测试",
        tool_codes=["skill_tool"],
        prompt_fragment="使用 skill_tool 工具",
    )
    skill_entry.tool_codes = ["skill_tool"]
    skill_entry.prompt_fragment = "使用 skill_tool 工具"

    isolated_registries["skill_reg"].get = MagicMock(return_value=skill_entry)
    isolated_registries["skill_reg"].all = MagicMock(return_value=[skill_entry])

    # 构造一个 mock Tool
    mock_tool = MagicMock()
    meta = ToolMeta(
        code="skill_tool",
        description="技能工具",
        parameters_schema={"type": "object", "properties": {}},
    )
    mock_tool.to_meta = MagicMock(return_value=meta)
    isolated_registries["tool_reg"].get = MagicMock(return_value=mock_tool)

    @agent(mode="react", code="prep_agent", skills=["test_skill"])
    class PrepAgent(BaseAgent):
        system_prompt = "基础提示"

    instance = PrepAgent()
    llm_tools, system_prompt = asyncio.get_event_loop().run_until_complete(
        instance._prepare_execution()
    )

    assert len(llm_tools) == 1
    assert llm_tools[0].function.name == "skill_tool"
    # system_prompt 应包含基础提示
    assert "基础提示" in system_prompt


# ---------------------------------------------------------------------------
# TASK-009-T013 PLAN_AND_EXECUTE 模式（骨架：降级为 REACT）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_execute_mode_runs_via_react(isolated_registries):
    """PLAN_AND_EXECUTE 模式第一期降级为 REACT 执行，能正常完成"""

    @agent(mode="plan_and_execute", code="plan_agent")
    class PlanAgent(BaseAgent):
        pass

    response = LlmResponse(content="计划执行完毕", tool_calls=None)
    mock_llm = make_mock_llm(chat_response=response)

    instance = PlanAgent()
    ctx = ExecutionContext.create(session_id="sess_plan", agent_code="plan_agent")
    memory = SessionMemoryManager()
    emitter = SseEventEmitter()

    events_task = asyncio.create_task(collect_events(emitter))
    await instance.stream_chat("执行计划", ctx, emitter, memory, llm_client=mock_llm)
    events = await events_task

    done_events = [e for e in events if e.type == SseEventType.DONE]
    assert len(done_events) == 1
    assert done_events[0].message == "计划执行完毕"


# ---------------------------------------------------------------------------
# TASK-009-T014 Sub-Agent 正常调用（无循环）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_sub_agent_success(isolated_registries):
    """Multi-Agent 互调：sub-agent 正常执行并返回结果"""
    agent_reg: AgentRegistry = isolated_registries["agent_reg"]

    # 创建 SubAgent（DIRECT 模式，一次返回结果）
    @agent(mode="direct", code="sub_agent_ok")
    class SubAgent(BaseAgent):
        system_prompt = "子 Agent"

    agent_reg.register_class(SubAgent)
    isolated_registries["agent_reg"].get = MagicMock(
        side_effect=lambda code: SubAgent if code == "sub_agent_ok" else None
    )

    # 主 Agent
    @agent(mode="react", code="main_agent_ok")
    class MainAgent(BaseAgent):
        pass

    # Mock LLM：第一轮返回调用子 Agent，第二轮返回最终答案
    sub_agent_tool_call_response = LlmResponse(
        content=None,
        tool_calls=[ToolCall(id="sub_call_1", name="sub_agent_ok", arguments='{"message": "你好子 Agent"}')],
    )
    final_response = LlmResponse(content="主 Agent 最终回答", tool_calls=None)

    mock_llm_for_main = MagicMock()
    mock_llm_for_main.chat_with_tools = AsyncMock(
        side_effect=[sub_agent_tool_call_response, final_response]
    )

    # 子 Agent 用的 LLM
    mock_llm_for_sub = make_mock_llm(stream_tokens=["子 Agent 回答"])

    # 注入到全局 mock（两个 agent 共用同一 llm_client 参数）
    # 这里 main agent 传 mock_llm_for_main，sub agent 内部也会用同一个 client
    mock_llm_for_main.stream_chat = mock_llm_for_sub.stream_chat

    instance = MainAgent()
    ctx = ExecutionContext.create(session_id="sess_sub", agent_code="main_agent_ok")
    memory = SessionMemoryManager()
    emitter = SseEventEmitter()

    events_task = asyncio.create_task(collect_events(emitter))
    await instance.stream_chat("调用子 Agent", ctx, emitter, memory, llm_client=mock_llm_for_main)
    events = await events_task

    tool_result_events = [e for e in events if e.type == SseEventType.TOOL_RESULT]
    done_events = [e for e in events if e.type == SseEventType.DONE]

    # 应有子 Agent 的执行结果
    assert len(tool_result_events) == 1
    assert "子 Agent 回答" in tool_result_events[0].data
    assert len(done_events) == 1


# ---------------------------------------------------------------------------
# TASK-009-T015 executor 包导出
# ---------------------------------------------------------------------------


def test_executor_package_exports():
    """executor/__init__.py 正确导出三个 Executor 类"""
    from haiji.agent.executor import DirectExecutor, ReactLoopExecutor, PlanExecuteExecutor
    assert DirectExecutor is not None
    assert ReactLoopExecutor is not None
    assert PlanExecuteExecutor is not None


# ---------------------------------------------------------------------------
# TASK-009-T016 Tool 参数解析失败时的处理
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_tool_invalid_json_raises(isolated_registries):
    """Tool 参数 JSON 解析失败时抛出 AgentToolNotFoundError"""
    isolated_registries["agent_reg"].get = MagicMock(return_value=None)

    mock_tool = MagicMock()
    mock_tool.execute = AsyncMock(return_value="ok")
    isolated_registries["tool_reg"].get = MagicMock(return_value=mock_tool)

    @agent(mode="react", code="invalid_json_agent")
    class InvalidJsonAgent(BaseAgent):
        pass

    instance = InvalidJsonAgent()
    ctx = ExecutionContext.create(session_id="sess_json", agent_code="invalid_json_agent")

    # 故意传入无效 JSON
    tool_call = ToolCall(id="tc_json", name="some_tool", arguments="not-valid-json{")

    with pytest.raises(AgentToolNotFoundError, match="参数解析失败"):
        await instance.execute_tool(tool_call=tool_call, ctx=ctx, call_stack=[])


# ---------------------------------------------------------------------------
# TASK-009-T017 AgentRegistry 包含检测
# ---------------------------------------------------------------------------


def test_agent_registry_contains():
    """AgentRegistry 支持 in 操作符检测"""
    registry = AgentRegistry()

    class ContainsAgent(BaseAgent):
        pass

    ContainsAgent._agent_definition = AgentDefinition(code="contains_code")
    registry.register_class(ContainsAgent)

    assert "contains_code" in registry
    assert "not_exists" not in registry
    assert registry.all() == {"contains_code": ContainsAgent}


# ---------------------------------------------------------------------------
# TASK-014b RAG 集成测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_rag_none_takes_original_path(isolated_registries):
    """_rag_retriever 为 None 时，stream_chat 完全走原路径。"""
    @agent(mode="direct", code="no_rag_agent")
    class NoRagAgent(BaseAgent):
        system_prompt = "基础提示词"

    instance = NoRagAgent()
    assert instance._rag_retriever is None

    llm_tools, prompt = await instance._prepare_execution(user_message="hello")
    # 没有 RAG，prompt 应与 system_prompt 一致
    assert "基础提示词" in prompt
    assert "以下是相关知识" not in prompt


@pytest.mark.asyncio
async def test_agent_rag_injected_into_system_prompt(isolated_registries):
    """配置 RAG 后，system_prompt 里注入了知识内容（inject_mode=system_suffix）。"""
    from unittest.mock import AsyncMock, MagicMock
    from haiji.knowledge.base_kb import BaseKnowledgeBase, KBResult
    from haiji.rag.definition import RagConfig

    mock_kb = AsyncMock(spec=BaseKnowledgeBase)
    mock_kb.search = AsyncMock(return_value=[
        KBResult(content="Python 是一种编程语言", score=0.9)
    ])

    @agent(mode="direct", code="rag_agent_inject", rag=mock_kb, rag_config=RagConfig(top_k=3))
    class RagInjectAgent(BaseAgent):
        system_prompt = "你是助手"

    instance = RagInjectAgent()
    assert instance._rag_retriever is not None

    llm_tools, prompt = await instance._prepare_execution(user_message="Python 是什么")
    assert "你是助手" in prompt
    assert "以下是相关知识" in prompt
    assert "Python 是一种编程语言" in prompt


@pytest.mark.asyncio
async def test_agent_rag_inject_mode_user_prefix(isolated_registries):
    """inject_mode=user_prefix 时，知识内容也注入到 system_prompt。"""
    from unittest.mock import AsyncMock
    from haiji.knowledge.base_kb import BaseKnowledgeBase, KBResult
    from haiji.rag.definition import RagConfig

    mock_kb = AsyncMock(spec=BaseKnowledgeBase)
    mock_kb.search = AsyncMock(return_value=[
        KBResult(content="相关知识内容", score=0.85)
    ])

    @agent(
        mode="direct",
        code="rag_user_prefix",
        rag=mock_kb,
        rag_config=RagConfig(top_k=2, inject_mode="user_prefix"),
    )
    class RagUserPrefixAgent(BaseAgent):
        system_prompt = "基础提示"

    instance = RagUserPrefixAgent()
    llm_tools, prompt = await instance._prepare_execution(user_message="查询")
    assert "相关知识内容" in prompt


@pytest.mark.asyncio
async def test_agent_rag_empty_result_no_injection(isolated_registries):
    """RAG 检索无结果时，system_prompt 不注入额外内容。"""
    from unittest.mock import AsyncMock
    from haiji.knowledge.base_kb import BaseKnowledgeBase, KBResult
    from haiji.rag.definition import RagConfig

    mock_kb = AsyncMock(spec=BaseKnowledgeBase)
    mock_kb.search = AsyncMock(return_value=[])  # 无结果

    @agent(mode="direct", code="rag_empty", rag=mock_kb)
    class RagEmptyAgent(BaseAgent):
        system_prompt = "原始提示词"

    instance = RagEmptyAgent()
    llm_tools, prompt = await instance._prepare_execution(user_message="查询")
    assert prompt == "原始提示词"


@pytest.mark.asyncio
async def test_agent_rag_failure_gracefully_degraded(isolated_registries):
    """RAG 检索失败时不阻断主流程，降级为无 RAG 路径。"""
    from unittest.mock import AsyncMock
    from haiji.knowledge.base_kb import BaseKnowledgeBase

    mock_kb = AsyncMock(spec=BaseKnowledgeBase)
    mock_kb.search = AsyncMock(side_effect=RuntimeError("网络异常"))

    @agent(mode="direct", code="rag_fail", rag=mock_kb)
    class RagFailAgent(BaseAgent):
        system_prompt = "降级提示词"

    instance = RagFailAgent()
    # 不应抛异常
    llm_tools, prompt = await instance._prepare_execution(user_message="查询")
    assert "降级提示词" in prompt


def test_agent_decorator_accepts_rag_params(isolated_registries):
    """@agent 装饰器支持 rag 和 rag_config 参数。"""
    from haiji.knowledge.base_kb import BaseKnowledgeBase, KBResult
    from haiji.rag.definition import RagConfig
    from unittest.mock import AsyncMock

    mock_kb = AsyncMock(spec=BaseKnowledgeBase)
    rag_config = RagConfig(top_k=5, inject_mode="system_suffix")

    @agent(mode="direct", code="rag_param_test", rag=mock_kb, rag_config=rag_config)
    class RagParamAgent(BaseAgent):
        system_prompt = "测试"

    instance = RagParamAgent()
    assert instance._rag_retriever is not None
    assert instance._rag_retriever.config.top_k == 5
    assert instance._rag_retriever.config.inject_mode == "system_suffix"


@pytest.mark.asyncio
async def test_agent_rag_empty_message_skips_search(isolated_registries):
    """user_message 为空时，不调用 kb.search。"""
    from unittest.mock import AsyncMock
    from haiji.knowledge.base_kb import BaseKnowledgeBase

    mock_kb = AsyncMock(spec=BaseKnowledgeBase)
    mock_kb.search = AsyncMock(return_value=[])

    @agent(mode="direct", code="rag_empty_msg", rag=mock_kb)
    class RagEmptyMsgAgent(BaseAgent):
        system_prompt = "提示词"

    instance = RagEmptyMsgAgent()
    await instance._prepare_execution(user_message="")
    mock_kb.search.assert_not_called()
