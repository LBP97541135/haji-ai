"""
api/definition.py - API 层数据结构

定义外部 HTTP 接口的请求/响应数据结构。
所有字段均使用 Pydantic 校验，确保类型安全。
"""

from typing import Any, Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """对话请求。

    客户端发送给 /chat 或 /chat/stream 接口的请求体。

    示例::

        {
            "session_id": "sess_abc123",
            "user_id": "user_001",
            "agent_code": "HelloAgent",
            "message": "今天天气怎么样？",
            "stream": true
        }
    """

    session_id: str = Field(..., description="会话 ID，用于区分不同的对话上下文")
    user_id: str = Field(..., description="用户 ID")
    agent_code: str = Field(..., description="要调用的 Agent 的 code")
    message: str = Field(..., description="用户输入的消息", min_length=1)
    stream: bool = Field(default=True, description="是否使用流式输出")


class ChatResponse(BaseModel):
    """非流式对话响应。

    /chat 接口（非流式）的响应体，等待 Agent 执行完毕后一次性返回。

    示例::

        {
            "session_id": "sess_abc123",
            "content": "今天杭州天气晴，气温 22°C，适合出行。",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        }
    """

    session_id: str = Field(..., description="会话 ID，与请求一致")
    content: str = Field(..., description="Agent 的最终回答内容")
    usage: dict[str, Any] = Field(default_factory=dict, description="Token 使用量统计")


class ApiError(BaseModel):
    """API 错误响应。

    所有接口的错误统一用此格式返回。

    示例::

        {
            "code": "AGENT_NOT_FOUND",
            "message": "Agent 'UnknownAgent' 未找到，请检查 agent_code 是否正确"
        }
    """

    code: str = Field(..., description="错误码，全大写下划线分隔")
    message: str = Field(..., description="对用户友好的错误描述")

    # 常用错误码常量
    AGENT_NOT_FOUND: str = "AGENT_NOT_FOUND"
    INVALID_REQUEST: str = "INVALID_REQUEST"
    AGENT_EXECUTION_FAILED: str = "AGENT_EXECUTION_FAILED"
    INTERNAL_ERROR: str = "INTERNAL_ERROR"

    @classmethod
    def agent_not_found(cls, agent_code: str) -> "ApiError":
        """构造 agent 未找到的错误。"""
        return cls(
            code="AGENT_NOT_FOUND",
            message=f"Agent '{agent_code}' 未找到，请检查 agent_code 是否正确",
        )

    @classmethod
    def invalid_request(cls, detail: str) -> "ApiError":
        """构造请求参数错误。"""
        return cls(code="INVALID_REQUEST", message=detail)

    @classmethod
    def execution_failed(cls, detail: str) -> "ApiError":
        """构造执行失败错误。"""
        return cls(code="AGENT_EXECUTION_FAILED", message=detail)

    @classmethod
    def internal_error(cls, detail: Optional[str] = None) -> "ApiError":
        """构造内部错误。"""
        return cls(
            code="INTERNAL_ERROR",
            message=detail or "服务器内部错误，请稍后重试",
        )
