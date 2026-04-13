"""
sse/definition.py - SSE 事件数据结构

定义流式输出中的所有事件类型。
Agent 执行过程中产生的所有输出都以 SseEvent 的形式发出。
"""

from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel


class SseEventType(str, Enum):
    """SSE 事件类型"""
    TOKEN = "token"              # LLM 输出的 token 片段
    TOOL_CALL = "tool_call"      # Agent 决定调用工具
    TOOL_RESULT = "tool_result"  # 工具执行结果
    THINKING = "thinking"        # Agent 思考过程（REACT 循环中）
    DONE = "done"                # 执行完成
    ERROR = "error"              # 执行出错


class SseEvent(BaseModel):
    """单个 SSE 事件"""

    type: SseEventType
    data: Optional[Any] = None      # 事件携带的数据
    message: Optional[str] = None  # 给用户看的文字（token/error 时使用）
    tool_name: Optional[str] = None  # 工具名（tool_call/tool_result 时使用）
    tool_call_id: Optional[str] = None  # 工具调用 ID

    @classmethod
    def token(cls, content: str) -> "SseEvent":
        """LLM 输出 token"""
        return cls(type=SseEventType.TOKEN, message=content)

    @classmethod
    def tool_call(cls, tool_name: str, tool_call_id: str, arguments: str) -> "SseEvent":
        """Agent 调用工具"""
        return cls(
            type=SseEventType.TOOL_CALL,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            data=arguments,
        )

    @classmethod
    def tool_result(cls, tool_name: str, tool_call_id: str, result: str) -> "SseEvent":
        """工具执行完毕"""
        return cls(
            type=SseEventType.TOOL_RESULT,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            data=result,
        )

    @classmethod
    def thinking(cls, content: str) -> "SseEvent":
        """Agent 思考过程"""
        return cls(type=SseEventType.THINKING, message=content)

    @classmethod
    def done(cls, final_content: Optional[str] = None) -> "SseEvent":
        """执行完成"""
        return cls(type=SseEventType.DONE, message=final_content)

    @classmethod
    def error(cls, message: str) -> "SseEvent":
        """执行出错"""
        return cls(type=SseEventType.ERROR, message=message)
