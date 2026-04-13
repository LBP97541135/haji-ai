"""
context - 执行上下文

封装单次 Agent 执行的元信息（session_id、trace_id、user_id 等）。

示例：
    from haiji.context import ExecutionContext, ToolCallContext

    ctx = ExecutionContext.create(
        session_id="sess_123",
        agent_code="my_agent",
        user_id="user_456",
    )
    tool_ctx = ToolCallContext.from_execution(ctx)
"""

from haiji.context.definition import ExecutionContext, ToolCallContext

__all__ = ["ExecutionContext", "ToolCallContext"]
