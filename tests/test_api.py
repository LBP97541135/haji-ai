"""
tests/test_api.py - API 模块单元测试

覆盖：
- GET /health 健康检查
- POST /chat 非流式对话正常返回
- POST /chat/stream SSE 流式输出
- agent_code 不存在时返回 404
- 请求参数校验（缺必填字段返回 422）
- Agent 执行出错时的错误处理
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from haiji.agent.base import BaseAgent, agent
from haiji.agent.registry import AgentRegistry, get_agent_registry
from haiji.api import HaijiServer, ChatRequest, ChatResponse, ApiError
from haiji.api.definition import ChatRequest, ChatResponse, ApiError
from haiji.context.definition import ExecutionContext
from haiji.llm.definition import LlmResponse, ToolCall
from haiji.memory.base import SessionMemoryManager
from haiji.sse.base import SseEventEmitter
from haiji.sse.definition import SseEvent, SseEventType


# ---------------------------------------------------------------------------
# 测试辅助：构建 Mock LLM 和测试 Agent
# ---------------------------------------------------------------------------

def make_mock_llm(
    content: str = "这是测试回答",
    tool_calls: Optional[list[ToolCall]] = None,
) -> MagicMock:
    """创建返回固定内容的 Mock LLM 客户端。"""
    mock_llm = MagicMock()
    mock_llm.chat_with_tools = AsyncMock(
        return_value=LlmResponse(content=content, tool_calls=tool_calls)
    )
    mock_llm.chat = AsyncMock(
        return_value=LlmResponse(content=content, tool_calls=tool_calls)
    )

    async def _stream(*args: Any, **kwargs: Any) -> AsyncGenerator[str, None]:
        for char in content:
            yield char

    mock_llm.stream_chat = MagicMock(side_effect=_stream)
    return mock_llm


def make_test_registry() -> AgentRegistry:
    """
    创建一个隔离的测试 AgentRegistry，注册简单的测试 Agent。

    由于 @agent 装饰器写入全局 registry，这里直接用全局 registry，
    并确保 _TestDirectAgent 已经注册进去。
    """
    # 注册一个简单的测试 Agent 到全局 registry
    @agent(mode="direct")
    class _TestDirectAgent(BaseAgent):
        system_prompt = "测试用 Direct Agent"

    return get_agent_registry()


def make_test_server(
    mock_llm: Optional[MagicMock] = None,
    registry: Optional[AgentRegistry] = None,
) -> HaijiServer:
    """创建测试用 HaijiServer。"""
    if registry is None:
        registry = make_test_registry()
    if mock_llm is None:
        mock_llm = make_mock_llm()
    return HaijiServer(agent_registry=registry, llm_client=mock_llm)


# ---------------------------------------------------------------------------
# 测试：GET /health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_ok() -> None:
    """健康检查接口应返回 {"status": "ok"}"""
    server = make_test_server()
    app = server.create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# 测试：POST /chat 非流式
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_returns_content_for_valid_request() -> None:
    """正常请求 /chat 应返回 ChatResponse，content 拼自 Agent 输出的 token。"""
    mock_llm = make_mock_llm(content="你好！")
    server = make_test_server(mock_llm=mock_llm)
    app = server.create_app()

    payload = {
        "session_id": "sess_001",
        "user_id": "user_001",
        "agent_code": "_TestDirectAgent",
        "message": "你好",
        "stream": False,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/chat", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "sess_001"
    assert isinstance(data["content"], str)
    assert "usage" in data


@pytest.mark.asyncio
async def test_chat_returns_404_for_unknown_agent() -> None:
    """agent_code 不存在时 /chat 应返回 404，body 为 ApiError 格式。"""
    server = make_test_server()
    app = server.create_app()

    payload = {
        "session_id": "sess_002",
        "user_id": "user_001",
        "agent_code": "NonExistentAgent",
        "message": "你好",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/chat", json=payload)

    assert resp.status_code == 404
    data = resp.json()
    assert data["code"] == "AGENT_NOT_FOUND"
    assert "NonExistentAgent" in data["message"]


@pytest.mark.asyncio
async def test_chat_returns_422_for_missing_required_field() -> None:
    """缺少必填字段（message）时 /chat 应返回 422。"""
    server = make_test_server()
    app = server.create_app()

    payload = {
        "session_id": "sess_003",
        "user_id": "user_001",
        "agent_code": "_TestDirectAgent",
        # message 缺失
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/chat", json=payload)

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_chat_returns_422_for_empty_message() -> None:
    """message 为空字符串时 /chat 应返回 422（Pydantic min_length 校验）。"""
    server = make_test_server()
    app = server.create_app()

    payload = {
        "session_id": "sess_004",
        "user_id": "user_001",
        "agent_code": "_TestDirectAgent",
        "message": "",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/chat", json=payload)

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_chat_handles_agent_error_gracefully() -> None:
    """/chat 当 Agent 执行抛出异常时应返回 500，body 为 ApiError 格式。"""
    # 构造一个执行时会抛异常的 LLM
    mock_llm = MagicMock()
    mock_llm.chat_with_tools = AsyncMock(side_effect=RuntimeError("LLM 挂了"))
    mock_llm.chat = AsyncMock(side_effect=RuntimeError("LLM 挂了"))

    async def _stream_err(*args: Any, **kwargs: Any) -> AsyncGenerator[str, None]:
        raise RuntimeError("LLM 挂了")
        yield  # type: ignore[misc]

    mock_llm.stream_chat = MagicMock(side_effect=_stream_err)

    server = make_test_server(mock_llm=mock_llm)
    app = server.create_app()

    payload = {
        "session_id": "sess_005",
        "user_id": "user_001",
        "agent_code": "_TestDirectAgent",
        "message": "触发错误",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/chat", json=payload)

    assert resp.status_code in (500,)
    data = resp.json()
    assert "code" in data


# ---------------------------------------------------------------------------
# 测试：POST /chat/stream SSE 流式
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_stream_emits_token_events() -> None:
    """POST /chat/stream 应以 SSE 格式推送 token 事件，最后推送 done。"""
    mock_llm = make_mock_llm(content="流式回答内容")
    server = make_test_server(mock_llm=mock_llm)
    app = server.create_app()

    payload = {
        "session_id": "sess_stream_001",
        "user_id": "user_001",
        "agent_code": "_TestDirectAgent",
        "message": "你好",
        "stream": True,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream("POST", "/chat/stream", json=payload) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")

            lines = []
            async for line in resp.aiter_lines():
                lines.append(line)

    # 解析 SSE 行
    data_lines = [line[len("data: "):] for line in lines if line.startswith("data: ")]
    assert len(data_lines) > 0

    events = [json.loads(d) for d in data_lines]
    event_types = [e["type"] for e in events]

    # 必须有 token 事件
    assert "token" in event_types
    # 最后一个事件必须是 done 或 error
    assert events[-1]["type"] in ("done", "error")


@pytest.mark.asyncio
async def test_chat_stream_returns_404_for_unknown_agent() -> None:
    """agent_code 不存在时 /chat/stream 应返回 404，并推送 error + done 事件。"""
    server = make_test_server()
    app = server.create_app()

    payload = {
        "session_id": "sess_stream_002",
        "user_id": "user_001",
        "agent_code": "GhostAgent",
        "message": "你好",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream("POST", "/chat/stream", json=payload) as resp:
            assert resp.status_code == 404

            lines = []
            async for line in resp.aiter_lines():
                lines.append(line)

    data_lines = [line[len("data: "):] for line in lines if line.startswith("data: ")]
    events = [json.loads(d) for d in data_lines]
    assert any(e["type"] == "error" for e in events)


# ---------------------------------------------------------------------------
# 测试：ApiError / ChatRequest / ChatResponse 数据结构
# ---------------------------------------------------------------------------


def test_api_error_agent_not_found() -> None:
    """ApiError.agent_not_found 应生成正确的 code 和包含 agent_code 的 message。"""
    error = ApiError.agent_not_found("MyAgent")
    assert error.code == "AGENT_NOT_FOUND"
    assert "MyAgent" in error.message


def test_api_error_invalid_request() -> None:
    """ApiError.invalid_request 应生成 INVALID_REQUEST code。"""
    error = ApiError.invalid_request("缺少 message 字段")
    assert error.code == "INVALID_REQUEST"
    assert "缺少" in error.message


def test_api_error_execution_failed() -> None:
    """ApiError.execution_failed 应生成 AGENT_EXECUTION_FAILED code。"""
    error = ApiError.execution_failed("超出最大轮次")
    assert error.code == "AGENT_EXECUTION_FAILED"


def test_api_error_internal_error_default_message() -> None:
    """ApiError.internal_error 不传 detail 时应有默认消息。"""
    error = ApiError.internal_error()
    assert error.code == "INTERNAL_ERROR"
    assert error.message  # 非空


def test_chat_request_validates_message_min_length() -> None:
    """ChatRequest 的 message 字段最小长度为 1，空字符串应抛出 ValidationError。"""
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises(PydanticValidationError):
        ChatRequest(session_id="s", user_id="u", agent_code="a", message="")


def test_chat_response_model() -> None:
    """ChatResponse 应正确保存 session_id / content / usage。"""
    resp = ChatResponse(
        session_id="sess_abc",
        content="你好世界",
        usage={"total_tokens": 42},
    )
    assert resp.session_id == "sess_abc"
    assert resp.content == "你好世界"
    assert resp.usage["total_tokens"] == 42


def test_chat_response_default_usage() -> None:
    """ChatResponse 的 usage 字段默认为空 dict。"""
    resp = ChatResponse(session_id="s", content="hi")
    assert resp.usage == {}


# ---------------------------------------------------------------------------
# 测试：HaijiServer 创建 + 路由注册
# ---------------------------------------------------------------------------


def test_create_app_returns_fastapi_instance() -> None:
    """create_app() 应返回一个 FastAPI 实例。"""
    from fastapi import FastAPI

    server = make_test_server()
    app = server.create_app()
    assert isinstance(app, FastAPI)


def test_create_app_registers_required_routes() -> None:
    """create_app() 应注册 /health、/chat、/chat/stream 三个路由。"""
    server = make_test_server()
    app = server.create_app()

    routes = {route.path for route in app.routes}  # type: ignore[attr-defined]
    assert "/health" in routes
    assert "/chat" in routes
    assert "/chat/stream" in routes
