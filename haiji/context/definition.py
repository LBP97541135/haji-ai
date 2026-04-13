"""
context/definition.py - 执行上下文数据结构

单次 Agent 执行的元信息，贯穿整个执行链路。
"""

import uuid
from typing import Optional
from pydantic import BaseModel, Field


def _gen_trace_id() -> str:
    return uuid.uuid4().hex[:8]


class ExecutionContext(BaseModel):
    """
    Agent 单次执行上下文。

    由 Agent 入口创建，传递给执行器、Tool、子 Agent。
    """
    session_id: str = Field(description="会话 ID，同一用户的多轮对话共用")
    agent_code: str = Field(description="当前执行的 Agent 标识")
    trace_id: str = Field(default_factory=_gen_trace_id, description="本次执行的追踪 ID，自动生成")
    user_id: Optional[str] = Field(default=None, description="用户 ID")

    @classmethod
    def create(
        cls,
        session_id: str,
        agent_code: str,
        user_id: Optional[str] = None,
    ) -> "ExecutionContext":
        """
        创建执行上下文（推荐用此工厂方法）。

        示例：
            ctx = ExecutionContext.create(
                session_id="sess_123",
                agent_code="research_agent",
                user_id="user_456",
            )
        """
        return cls(session_id=session_id, agent_code=agent_code, user_id=user_id)


class ToolCallContext(BaseModel):
    """
    Tool 执行时的上下文，是 ExecutionContext 的子集。
    Tool 不需要知道完整的 Agent 执行上下文，只需要这些信息。
    """
    session_id: str
    agent_code: str
    trace_id: str
    user_id: Optional[str] = None

    @classmethod
    def from_execution(cls, ctx: ExecutionContext) -> "ToolCallContext":
        """从 ExecutionContext 创建 ToolCallContext"""
        return cls(
            session_id=ctx.session_id,
            agent_code=ctx.agent_code,
            trace_id=ctx.trace_id,
            user_id=ctx.user_id,
        )
