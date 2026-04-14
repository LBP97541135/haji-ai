"""
examples/full_agent/api_server.py — FastAPI HTTP 服务验证示例

演示 HaijiServer 的 REST 接口和 SSE 流式接口：
  - GET  /health        健康检查
  - POST /chat          非流式对话
  - POST /chat/stream   SSE 流式对话

使用 httpx.AsyncClient(app=app) 在同进程内测试，无需真实启动服务器。
LLM 调用使用 AsyncMock，不花费真实 API 费用。

Usage:
    python3 examples/full_agent/api_server.py

依赖：
    pip install -e .
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from httpx import ASGITransport, AsyncClient

from haiji.agent import BaseAgent, agent, get_agent_registry
from haiji.agent.registry import AgentRegistry
from haiji.api import HaijiServer
from haiji.llm.definition import LlmResponse

logging.basicConfig(level=logging.WARNING)

# ─── Agent 定义 ──────────────────────────────────────────────────────────────

@agent(mode="direct")
class HelloApiAgent(BaseAgent):
    """用于 API 测试的简单 Agent。"""
    system_prompt = "你是一个友好的助手，请简洁地回答用户的问题。"


# ─── Mock LLM Client ────────────────────────────────────────────────────────

def _make_mock_client() -> mock.AsyncMock:
    """构造 Mock LLM Client，返回固定回答。"""

    async def mock_chat(request: object) -> LlmResponse:
        return LlmResponse(
            content="你好！我是 haiji AI 助手，很高兴为你服务。",
            tool_calls=None,
            finish_reason="stop",
        )

    async def mock_stream_chat(request: object):  # type: ignore[override]
        tokens = ["你好！", "我是 ", "haiji ", "AI 助手，", "很高兴为你服务。"]
        for token in tokens:
            yield token

    client = mock.AsyncMock()
    client.chat = mock_chat
    client.stream_chat = mock_stream_chat
    return client


# ─── 主流程 ──────────────────────────────────────────────────────────────────

async def main() -> None:
    print("=" * 60)
    print("🦐 haiji 第二期集成示例：FastAPI HTTP 服务验证")
    print("=" * 60)

    # 构建 Server
    registry: AgentRegistry = get_agent_registry()
    mock_client = _make_mock_client()
    server = HaijiServer(agent_registry=registry, llm_client=mock_client)
    app = server.create_app()

    # 用 httpx 的 ASGI transport 在进程内测试（无需启动真实 HTTP 服务）
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:

        # ── 测试 1：GET /health ────────────────────────────────────────
        print("\n[1/3] 测试 GET /health...")
        resp = await client.get("/health")
        assert resp.status_code == 200, f"期望 200，实际 {resp.status_code}"
        body = resp.json()
        assert body.get("status") == "ok", f"健康检查响应异常：{body}"
        print(f"    ✅ /health 响应：{body}")

        # ── 测试 2：POST /chat（非流式）────────────────────────────────
        print("\n[2/3] 测试 POST /chat（非流式）...")
        chat_payload = {
            "session_id": "test_session_001",
            "user_id": "test_user",
            "agent_code": "HelloApiAgent",
            "message": "你好，介绍一下自己",
            "stream": False,
        }
        resp = await client.post("/chat", json=chat_payload)
        assert resp.status_code == 200, f"期望 200，实际 {resp.status_code}，body={resp.text}"
        body = resp.json()
        assert "content" in body, f"响应中缺少 content 字段：{body}"
        assert "session_id" in body, f"响应中缺少 session_id 字段：{body}"
        assert body["session_id"] == "test_session_001"
        print(f"    ✅ /chat 响应：session_id={body['session_id']}")
        print(f"       content: {body['content'][:80]}{'...' if len(body['content']) > 80 else ''}")

        # ── 测试 3：POST /chat/stream（SSE 流式）──────────────────────
        print("\n[3/3] 测试 POST /chat/stream（SSE 流式）...")
        stream_payload = {
            "session_id": "test_session_002",
            "user_id": "test_user",
            "agent_code": "HelloApiAgent",
            "message": "你好",
            "stream": True,
        }
        received_events: list[dict] = []
        async with client.stream("POST", "/chat/stream", json=stream_payload) as resp:
            assert resp.status_code == 200, f"SSE 响应码异常：{resp.status_code}"
            # 读取 SSE 数据行
            async for line in resp.aiter_lines():
                line = line.strip()
                if line.startswith("data:"):
                    data_str = line[len("data:"):].strip()
                    if data_str:
                        try:
                            event_data = json.loads(data_str)
                            received_events.append(event_data)
                        except json.JSONDecodeError:
                            pass  # 忽略非 JSON 行（如心跳）

        assert len(received_events) > 0, "SSE 流式接口未收到任何事件"
        event_types = {e.get("type") for e in received_events}
        print(f"    ✅ SSE 收到 {len(received_events)} 个事件，类型：{event_types}")

        # 验证包含 done 或 token 类型事件
        has_meaningful_event = bool(event_types & {"token", "done", "error"})
        assert has_meaningful_event, f"SSE 事件类型异常，未收到 token/done/error：{event_types}"

        # ── 测试 4：agent_not_found 错误处理 ──────────────────────────
        print("\n[附加] 测试 agent_not_found 错误处理...")
        bad_payload = {
            "session_id": "test_session_003",
            "user_id": "test_user",
            "agent_code": "NonExistentAgent",
            "message": "你好",
        }
        resp = await client.post("/chat", json=bad_payload)
        assert resp.status_code == 404, f"期望 404，实际 {resp.status_code}"
        body = resp.json()
        assert "code" in body or "detail" in body, f"错误响应格式异常：{body}"
        print(f"    ✅ agent_not_found 正确返回 404：{body}")

    print("\n" + "=" * 60)
    print("✅ FastAPI HTTP 服务验证通过！")
    print("=" * 60)
    print("\n💡 生产部署方式：")
    print("   uvicorn your_app:app --host 0.0.0.0 --port 8000")


if __name__ == "__main__":
    asyncio.run(main())
