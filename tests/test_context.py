"""context 模块单元测试"""

import pytest
from haiji.context import ExecutionContext, ToolCallContext


def test_execution_context_create():
    ctx = ExecutionContext.create(
        session_id="sess_123",
        agent_code="test_agent",
        user_id="user_456",
    )
    assert ctx.session_id == "sess_123"
    assert ctx.agent_code == "test_agent"
    assert ctx.user_id == "user_456"
    assert len(ctx.trace_id) == 8  # 自动生成 8 位


def test_trace_id_auto_generated():
    ctx1 = ExecutionContext.create(session_id="s1", agent_code="a")
    ctx2 = ExecutionContext.create(session_id="s2", agent_code="a")
    assert ctx1.trace_id != ctx2.trace_id  # 每次不同


def test_tool_call_context_from_execution():
    ctx = ExecutionContext.create(
        session_id="sess_123",
        agent_code="test_agent",
        user_id="user_456",
    )
    tool_ctx = ToolCallContext.from_execution(ctx)
    assert tool_ctx.session_id == ctx.session_id
    assert tool_ctx.agent_code == ctx.agent_code
    assert tool_ctx.trace_id == ctx.trace_id
    assert tool_ctx.user_id == ctx.user_id


def test_user_id_optional():
    ctx = ExecutionContext.create(session_id="s1", agent_code="a")
    assert ctx.user_id is None
