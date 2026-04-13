"""
llm/base.py - LLM 客户端抽象接口

所有 LLM 实现都必须继承 LlmClient，框架内部只依赖这个接口。
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator
from haiji.llm.definition import LlmRequest, LlmResponse, LlmMessage, ToolCall


class LlmClient(ABC):
    """
    LLM 客户端抽象基类。

    所有厂商实现（OpenAI、通义等）都继承此类。
    框架内部只依赖 LlmClient，不依赖具体实现。
    """

    @abstractmethod
    async def chat(self, request: LlmRequest) -> LlmResponse:
        """
        非流式对话，返回完整响应。

        Args:
            request: LLM 请求

        Returns:
            LlmResponse: 完整的响应内容
        """
        ...

    @abstractmethod
    async def stream_chat(self, request: LlmRequest) -> AsyncGenerator[str, None]:
        """
        流式对话，逐 token 返回内容。

        Args:
            request: LLM 请求

        Yields:
            str: 每次返回一个 token 片段
        """
        ...

    @abstractmethod
    async def chat_with_tools(self, request: LlmRequest) -> LlmResponse:
        """
        支持 Function Calling 的对话，返回完整响应（含 tool_calls）。

        Args:
            request: LLM 请求（request.tools 不能为空）

        Returns:
            LlmResponse: 包含 content 或 tool_calls 的响应
        """
        ...
