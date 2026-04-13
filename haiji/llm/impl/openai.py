"""
llm/impl/openai.py - OpenAI LLM 客户端实现

基于 openai 官方 SDK 实现 LlmClient 接口。
同时兼容所有 OpenAI 协议兼容的接口（如通义千问、DeepSeek 等）。
"""

from __future__ import annotations
import json
import logging
from typing import AsyncGenerator, Any

from haiji.llm.base import LlmClient
from haiji.llm.definition import (
    LlmRequest, LlmResponse, LlmMessage, ToolCall, LlmConfig, MessageRole
)
from haiji.config import HaijiConfig

logger = logging.getLogger(__name__)


class OpenAILlmClient(LlmClient):
    """
    OpenAI LLM 客户端。

    兼容所有 OpenAI 协议的接口（通义、DeepSeek、本地模型等）。

    示例：
        client = OpenAILlmClient(config)
        response = await client.chat(request)

        async for token in client.stream_chat(request):
            print(token, end="", flush=True)
    """

    def __init__(self, config: HaijiConfig, llm_config: LlmConfig | None = None) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("请先安装 openai：pip install openai")

        self._config = config
        self._llm_config = llm_config

        api_key = (llm_config.api_key if llm_config and llm_config.api_key else None) or config.api_key
        base_url = (llm_config.base_url if llm_config and llm_config.base_url else None) or config.llm_base_url
        timeout = (llm_config.timeout if llm_config and llm_config.timeout else None) or config.llm_timeout

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._default_model = (llm_config.model if llm_config and llm_config.model else None) or config.llm_model
        self._default_temperature = (
            llm_config.temperature if llm_config and llm_config.temperature else None
        ) or config.llm_temperature
        self._default_max_tokens = (
            llm_config.max_tokens if llm_config and llm_config.max_tokens else None
        ) or config.llm_max_tokens

    def _build_messages(self, messages: list[LlmMessage]) -> list[dict[str, Any]]:
        """将 LlmMessage 列表转换为 OpenAI API 格式"""
        result = []
        for msg in messages:
            d: dict[str, Any] = {"role": msg.role.value}
            if msg.content is not None:
                d["content"] = msg.content
            if msg.tool_call_id:
                d["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                d["tool_calls"] = msg.tool_calls
            if msg.name:
                d["name"] = msg.name
            result.append(d)
        return result

    def _build_tools(self, request: LlmRequest) -> list[dict[str, Any]] | None:
        """将 LlmTool 列表转换为 OpenAI API 格式"""
        if not request.tools:
            return None
        return [t.model_dump() for t in request.tools]

    def _resolve_model(self, request: LlmRequest) -> str:
        return request.model or self._default_model

    def _resolve_temperature(self, request: LlmRequest) -> float:
        return request.temperature if request.temperature is not None else self._default_temperature

    def _resolve_max_tokens(self, request: LlmRequest) -> int:
        return request.max_tokens if request.max_tokens is not None else self._default_max_tokens

    async def chat(self, request: LlmRequest) -> LlmResponse:
        """非流式对话"""
        logger.info("[LLM] chat: model=%s, messages=%d", self._resolve_model(request), len(request.messages))
        response = await self._client.chat.completions.create(
            model=self._resolve_model(request),
            messages=self._build_messages(request.messages),  # type: ignore
            temperature=self._resolve_temperature(request),
            max_tokens=self._resolve_max_tokens(request),
            stream=False,
        )
        choice = response.choices[0]
        return LlmResponse(
            content=choice.message.content,
            finish_reason=choice.finish_reason,
        )

    async def stream_chat(self, request: LlmRequest) -> AsyncGenerator[str, None]:
        """流式对话，逐 token yield"""
        logger.info("[LLM] stream_chat: model=%s", self._resolve_model(request))
        stream = await self._client.chat.completions.create(
            model=self._resolve_model(request),
            messages=self._build_messages(request.messages),  # type: ignore
            temperature=self._resolve_temperature(request),
            max_tokens=self._resolve_max_tokens(request),
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    async def chat_with_tools(self, request: LlmRequest) -> LlmResponse:
        """支持 Function Calling 的对话"""
        tools = self._build_tools(request)
        logger.info(
            "[LLM] chat_with_tools: model=%s, tools=%d",
            self._resolve_model(request),
            len(tools) if tools else 0,
        )
        response = await self._client.chat.completions.create(
            model=self._resolve_model(request),
            messages=self._build_messages(request.messages),  # type: ignore
            tools=tools,  # type: ignore
            temperature=self._resolve_temperature(request),
            max_tokens=self._resolve_max_tokens(request),
            stream=False,
        )
        choice = response.choices[0]
        message = choice.message

        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                )
                for tc in message.tool_calls
            ]

        return LlmResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
        )
