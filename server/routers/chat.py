"""
server/routers/chat.py - 聊天路由

POST /api/chat/stream  → SSE 流式聊天
POST /api/chat         → 非流式聊天
GET  /api/sessions/{session_id}/history → 会话历史
"""
from __future__ import annotations

import asyncio
import json
import uuid
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from haiji.agent.registry import get_agent_registry
from haiji.context.definition import ExecutionContext
from haiji.sse.base import SseEventEmitter
from haiji.sse.definition import SseEventType

from server.deps import get_llm_client, get_memory
from server.models import ChatRequest, ChatResponse, SessionHistoryResponse, HistoryMessage

logger = logging.getLogger(__name__)
router = APIRouter()


def _resolve_session_id(session_id: str) -> str:
    """如果 session_id 为空，生成一个新的"""
    return session_id if session_id else uuid.uuid4().hex


async def _stream_agent(req: ChatRequest) -> AsyncGenerator[str, None]:
    """SSE 流式生成器：消费 emitter 事件转为 SSE 格式"""
    registry = get_agent_registry()
    cls = registry.get(req.agent_code)
    if cls is None:
        error_data = json.dumps({"type": "error", "content": f"Agent '{req.agent_code}' not found"})
        yield f"data: {error_data}\n\n"
        return

    session_id = _resolve_session_id(req.session_id)
    ctx = ExecutionContext.create(
        session_id=session_id,
        agent_code=req.agent_code,
        user_id=req.user_id,
    )
    memory = get_memory()
    llm = get_llm_client()
    agent = cls()
    emitter = SseEventEmitter()

    # 启动 agent.stream_chat 为后台任务
    agent_task = asyncio.create_task(
        agent.stream_chat(req.message, ctx, emitter, memory, llm_client=llm)
    )

    # 消费 emitter events，转为 SSE 格式
    async for event in emitter.events():
        if event.type == SseEventType.TOKEN:
            data = json.dumps({"type": "token", "content": event.message or ""})
        elif event.type == SseEventType.TOOL_CALL:
            data = json.dumps({
                "type": "tool_call",
                "tool_name": event.tool_name or "",
                "tool_call_id": event.tool_call_id or "",
            })
        elif event.type == SseEventType.TOOL_RESULT:
            data = json.dumps({
                "type": "tool_result",
                "tool_name": event.tool_name or "",
                "tool_call_id": event.tool_call_id or "",
            })
        elif event.type == SseEventType.THINKING:
            data = json.dumps({"type": "thinking", "content": event.message or ""})
        elif event.type == SseEventType.DONE:
            data = json.dumps({"type": "done", "content": event.message or "", "session_id": session_id})
        elif event.type == SseEventType.ERROR:
            data = json.dumps({"type": "error", "content": event.message or ""})
        else:
            continue
        yield f"data: {data}\n\n"

    # 确保 agent_task 完成（通常 done 事件之后已经结束）
    try:
        await agent_task
    except Exception as e:
        logger.error("[chat_stream] agent_task 异常: %s", e)
        error_data = json.dumps({"type": "error", "content": str(e)})
        yield f"data: {error_data}\n\n"


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 流式聊天接口"""
    return StreamingResponse(
        _stream_agent(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """非流式聊天接口：收集所有 token 后返回"""
    registry = get_agent_registry()
    cls = registry.get(req.agent_code)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_code}' not found")

    session_id = _resolve_session_id(req.session_id)
    ctx = ExecutionContext.create(
        session_id=session_id,
        agent_code=req.agent_code,
        user_id=req.user_id,
    )
    memory = get_memory()
    llm = get_llm_client()
    agent = cls()
    emitter = SseEventEmitter()

    agent_task = asyncio.create_task(
        agent.stream_chat(req.message, ctx, emitter, memory, llm_client=llm)
    )

    tokens: list[str] = []
    final_content = ""

    async for event in emitter.events():
        if event.type == SseEventType.TOKEN:
            tokens.append(event.message or "")
        elif event.type == SseEventType.DONE:
            final_content = event.message or "".join(tokens)

    await agent_task

    if not final_content:
        final_content = "".join(tokens)

    return ChatResponse(
        session_id=session_id,
        content=final_content,
        agent_code=req.agent_code,
    )


@router.get("/sessions/{session_id}/history", response_model=SessionHistoryResponse)
def get_session_history(session_id: str):
    """返回会话历史"""
    memory = get_memory()
    messages = memory.get_history(session_id)
    result = []
    for msg in messages:
        # LlmMessage.role 是 MessageRole 枚举
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        result.append(HistoryMessage(role=role, content=content))
    return SessionHistoryResponse(messages=result)
