"""
api/server.py - HaijiServer：框架自身的 HTTP 服务

将 haiji Agent 通过 FastAPI 暴露为 HTTP 接口，支持：
- POST /chat        非流式对话（等待完整结果后返回）
- POST /chat/stream SSE 流式对话（边生成边推送）
- GET  /health      健康检查

使用方式::

    from haiji.api import HaijiServer
    from haiji.llm.impl.openai_client import OpenAILlmClient
    from haiji.agent import get_agent_registry

    server = HaijiServer(
        agent_registry=get_agent_registry(),
        llm_client=OpenAILlmClient(config),
    )
    app = server.create_app()

    # 用 uvicorn 运行：
    # uvicorn main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from haiji.agent.registry import AgentRegistry
from haiji.api.definition import ApiError, ChatRequest, ChatResponse
from haiji.context.definition import ExecutionContext
from haiji.memory.base import SessionMemoryManager
from haiji.sse.base import SseEventEmitter
from haiji.sse.definition import SseEventType

logger = logging.getLogger(__name__)


class HaijiServer:
    """
    haiji 框架的 HTTP 服务封装。

    接受外部注入的 AgentRegistry 和 LlmClient，不自行初始化任何依赖。
    通过 create_app() 生成 FastAPI 应用实例。

    Args:
        agent_registry: Agent 注册表，用于根据 agent_code 查找 Agent 类
        llm_client:     LLM 客户端实例（可以是 OpenAILlmClient 或 mock）
    """

    def __init__(self, agent_registry: AgentRegistry, llm_client: Any) -> None:
        self._registry = agent_registry
        self._llm_client = llm_client
        # 共享的 SessionMemoryManager（跨请求保留会话历史）
        self._memory = SessionMemoryManager()

    # ------------------------------------------------------------------
    # FastAPI 应用创建
    # ------------------------------------------------------------------

    def create_app(self) -> FastAPI:
        """
        创建并返回 FastAPI 应用实例。

        注册所有路由，设置全局异常处理器。

        Returns:
            配置好的 FastAPI 应用
        """
        app = FastAPI(
            title="haji-ai API",
            description="Multi-Agent 框架 HTTP 接口",
            version="0.1.0",
        )

        # 注册路由
        app.add_api_route("/health", self._health, methods=["GET"])
        app.add_api_route("/chat", self._chat, methods=["POST"])
        app.add_api_route("/chat/stream", self._chat_stream, methods=["POST"])

        # 全局 ValidationError 处理（Pydantic 校验失败时）
        @app.exception_handler(ValidationError)
        async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
            error = ApiError.invalid_request(str(exc))
            return JSONResponse(status_code=422, content=error.model_dump())

        return app

    # ------------------------------------------------------------------
    # 路由处理器
    # ------------------------------------------------------------------

    async def _health(self) -> dict[str, str]:
        """
        健康检查。

        Returns:
            {"status": "ok"}
        """
        return {"status": "ok"}

    async def _chat(self, request: ChatRequest) -> JSONResponse:
        """
        非流式对话接口。

        调用 Agent 执行，等待完整结果后一次性返回 ChatResponse。

        Args:
            request: 对话请求（Pydantic 校验）

        Returns:
            ChatResponse JSON，或 ApiError JSON（含对应 HTTP 状态码）
        """
        agent_cls = self._registry.get(request.agent_code)
        if agent_cls is None:
            error = ApiError.agent_not_found(request.agent_code)
            return JSONResponse(status_code=404, content=error.model_dump())

        try:
            agent_instance = agent_cls()
            ctx = ExecutionContext.create(
                session_id=request.session_id,
                agent_code=request.agent_code,
            )
            emitter = SseEventEmitter()

            # 并发：一个协程跑 Agent，一个协程收集结果
            collected_tokens: list[str] = []
            collected_usage: dict[str, Any] = {}
            error_message: Optional[str] = None

            async def run_agent() -> None:
                await agent_instance.stream_chat(
                    user_message=request.message,
                    ctx=ctx,
                    emitter=emitter,
                    memory=self._memory,
                    llm_client=self._llm_client,
                )

            async def collect_events() -> None:
                nonlocal error_message
                async for event in emitter.events():
                    if event.type == SseEventType.TOKEN and event.message:
                        collected_tokens.append(event.message)
                    elif event.type == SseEventType.DONE:
                        break
                    elif event.type == SseEventType.ERROR and event.message:
                        error_message = event.message
                        break

            await asyncio.gather(run_agent(), collect_events())

            if error_message:
                error = ApiError.execution_failed(error_message)
                return JSONResponse(status_code=500, content=error.model_dump())

            content = "".join(collected_tokens)
            response = ChatResponse(
                session_id=request.session_id,
                content=content,
                usage=collected_usage,
            )
            return JSONResponse(content=response.model_dump())

        except Exception as exc:
            logger.error("[HaijiServer] /chat 执行异常: %s", exc, exc_info=True)
            error = ApiError.internal_error(str(exc))
            return JSONResponse(status_code=500, content=error.model_dump())

    async def _chat_stream(self, request: ChatRequest) -> StreamingResponse:
        """
        SSE 流式对话接口。

        持续推送 Agent 输出的事件，直到 done 或 error。
        每行格式：``data: {json}\\n\\n``

        Args:
            request: 对话请求（Pydantic 校验）

        Returns:
            StreamingResponse（Content-Type: text/event-stream）
        """
        agent_cls = self._registry.get(request.agent_code)
        if agent_cls is None:
            # StreamingResponse 无法直接返回 404，先发一个 error 事件再结束
            error = ApiError.agent_not_found(request.agent_code)

            async def _not_found_gen() -> AsyncGenerator[str, None]:
                yield f"data: {json.dumps({'type': 'error', 'message': error.message})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"

            return StreamingResponse(
                _not_found_gen(),
                status_code=404,
                media_type="text/event-stream",
            )

        async def _event_generator() -> AsyncGenerator[str, None]:
            try:
                agent_instance = agent_cls()
                ctx = ExecutionContext.create(
                    session_id=request.session_id,
                    agent_code=request.agent_code,
                )
                emitter = SseEventEmitter()

                async def run_agent() -> None:
                    await agent_instance.stream_chat(
                        user_message=request.message,
                        ctx=ctx,
                        emitter=emitter,
                        memory=self._memory,
                        llm_client=self._llm_client,
                    )

                # 启动 Agent（在后台运行）
                agent_task = asyncio.create_task(run_agent())

                # 消费事件流，逐个转成 SSE 格式推送
                async for event in emitter.events():
                    payload: dict[str, Any] = {"type": event.type.value}
                    if event.message is not None:
                        payload["content"] = event.message
                    if event.tool_name is not None:
                        payload["tool_name"] = event.tool_name
                    if event.tool_call_id is not None:
                        payload["tool_call_id"] = event.tool_call_id
                    if event.data is not None:
                        payload["data"] = event.data

                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

                    if event.type in (SseEventType.DONE, SseEventType.ERROR):
                        break

                # 确保 agent_task 正常结束
                if not agent_task.done():
                    await agent_task

            except Exception as exc:
                logger.error("[HaijiServer] /chat/stream 执行异常: %s", exc, exc_info=True)
                error_payload = {
                    "type": "error",
                    "content": f"服务器内部错误：{exc}",
                }
                yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(
            _event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
