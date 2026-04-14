"""
llm/definition.py - LLM 相关数据结构

定义 LLM 调用所需的所有数据结构，与具体厂商无关。
"""

from __future__ import annotations
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """消息角色"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class LlmMessage(BaseModel):
    """单条对话消息"""

    role: MessageRole
    content: Optional[str] = None
    tool_call_id: Optional[str] = None   # role=tool 时使用
    tool_calls: Optional[list[dict[str, Any]]] = None  # role=assistant 且有工具调用时使用
    name: Optional[str] = None

    @classmethod
    def system(cls, content: str) -> "LlmMessage":
        return cls(role=MessageRole.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> "LlmMessage":
        return cls(role=MessageRole.USER, content=content)

    @classmethod
    def assistant(cls, content: str) -> "LlmMessage":
        return cls(role=MessageRole.ASSISTANT, content=content)

    @classmethod
    def tool_result(cls, tool_call_id: str, content: str) -> "LlmMessage":
        return cls(role=MessageRole.TOOL, tool_call_id=tool_call_id, content=content)


class ToolCall(BaseModel):
    """LLM 返回的工具调用"""
    id: str
    name: str
    arguments: str  # JSON 字符串


class FunctionParam(BaseModel):
    """工具参数定义"""
    type: str
    description: str
    enum: Optional[list[str]] = None


class FunctionDef(BaseModel):
    """工具函数定义（OpenAI function calling 格式）"""
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class LlmTool(BaseModel):
    """传给 LLM 的工具定义"""
    type: str = "function"
    function: FunctionDef


class LlmConfig(BaseModel):
    """LLM 配置（支持三层合并：runtime > agent > global）"""
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout: Optional[int] = None

    @classmethod
    def merge(cls, *configs: Optional["LlmConfig"]) -> "LlmConfig":
        """
        合并多个 LlmConfig，优先级从左到右降低（左边的覆盖右边的）。

        示例：
            merged = LlmConfig.merge(runtime_config, agent_config, global_config)
        """
        result: dict[str, Any] = {}
        for config in reversed(configs):
            if config is None:
                continue
            for key, val in config.model_dump(exclude_none=True).items():
                result[key] = val
        return cls(**result)


class LlmRequest(BaseModel):
    """LLM 请求"""
    messages: list[LlmMessage]
    tools: Optional[list[LlmTool]] = None
    stream: bool = True
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class LlmUsage(BaseModel):
    """LLM token 用量统计"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LlmResponse(BaseModel):
    """LLM 非流式响应"""
    content: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None
    finish_reason: Optional[str] = None
    usage: Optional[LlmUsage] = None
