"""
llm - 大模型客户端

封装 LLM 调用，屏蔽厂商差异，支持流式和非流式，支持 Function Calling。

示例：
    from haiji.llm import LlmClient, LlmMessage, LlmRequest
    from haiji.llm.impl.openai import OpenAILlmClient
    from haiji.config import get_config

    client = OpenAILlmClient(get_config())

    # 非流式
    request = LlmRequest(messages=[LlmMessage.user("你好")])
    response = await client.chat(request)

    # 流式
    async for token in client.stream_chat(request):
        print(token, end="")
"""

from haiji.llm.base import LlmClient
from haiji.llm.definition import (
    LlmMessage, LlmRequest, LlmResponse, LlmConfig,
    LlmTool, FunctionDef, ToolCall, MessageRole, LlmUsage,
)

__all__ = [
    "LlmClient",
    "LlmMessage", "LlmRequest", "LlmResponse", "LlmConfig",
    "LlmTool", "FunctionDef", "ToolCall", "MessageRole", "LlmUsage",
]
