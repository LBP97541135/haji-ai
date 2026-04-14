"""
observer - 可观测性模块

提供 Agent 执行链路的 Token 统计和链路追踪能力。
trace_id 贯穿整个 Agent 执行生命周期（LLM 调用 + Tool 调用）。

设计原则：
- 本模块处于依赖层的最底层，不 import 任何上层模块（agent / llm / tool 等）
- 纯内存存储，第一期不做持久化
- 所有记录方法均为同步，性能开销极低

快速示例::

    from haiji.observer import get_observer, llm_span_ctx, tool_span_ctx, TokenUsage

    observer = get_observer()
    record = observer.start_trace("trace-001", "my_agent", "session-001")

    async with llm_span_ctx(observer, "trace-001", "my_agent", "gpt-4o") as ctx:
        # 调用 LLM...
        ctx.set_usage(TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150))

    finished = observer.finish_trace("trace-001")
    print(finished.total_tokens.total_tokens)  # 150
"""

from haiji.observer.base import (
    Observer,
    get_observer,
    llm_span_ctx,
    reset_observer,
    tool_span_ctx,
)
from haiji.observer.definition import (
    LlmCallSpan,
    TokenUsage,
    ToolCallSpan,
    TraceRecord,
)

__all__ = [
    # 核心类
    "Observer",
    # 全局单例
    "get_observer",
    "reset_observer",
    # 上下文管理器
    "llm_span_ctx",
    "tool_span_ctx",
    # 数据结构
    "TokenUsage",
    "LlmCallSpan",
    "ToolCallSpan",
    "TraceRecord",
]
