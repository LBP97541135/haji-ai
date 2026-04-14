"""
observer/base.py - Observer 核心 + 上下文管理器

提供全局 Observer 单例，用于记录链路追踪（Trace）和 Token 统计。
纯内存存储，不做 I/O，第一期不需要持久化。

设计原则：
- 本模块是最底层，不 import agent / llm / tool 任何上层模块
- 所有方法均为同步（只写内存字典，无 I/O）
- 上下文管理器使用 time.monotonic() 计时，不阻塞热路径
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator, Optional

from haiji.observer.definition import (
    LlmCallSpan,
    TokenUsage,
    ToolCallSpan,
    TraceRecord,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Observer 核心
# ---------------------------------------------------------------------------


class Observer:
    """链路追踪与 Token 统计的全局观测器。

    纯内存存储，线程安全程度取决于调用方（asyncio 单线程安全）。

    示例::

        observer = get_observer()
        record = observer.start_trace("trace-001", "my_agent", "session-001")
        span = LlmCallSpan(trace_id="trace-001", agent_code="my_agent", model="gpt-4o")
        observer.record_llm_call("trace-001", span)
        finished = observer.finish_trace("trace-001")
        print(finished.total_tokens)
    """

    def __init__(self) -> None:
        self._traces: dict[str, TraceRecord] = {}

    def start_trace(self, trace_id: str, agent_code: str, session_id: str) -> TraceRecord:
        """开启一条新的 Trace 记录。

        Args:
            trace_id: 全局唯一的 Trace ID。
            agent_code: Agent 标识。
            session_id: 会话 ID。

        Returns:
            新创建的 TraceRecord。
        """
        record = TraceRecord(
            trace_id=trace_id,
            agent_code=agent_code,
            session_id=session_id,
        )
        self._traces[trace_id] = record
        logger.info("Trace started: trace_id=%s, agent_code=%s", trace_id, agent_code)
        return record

    def record_llm_call(self, trace_id: str, span: LlmCallSpan) -> None:
        """追加一条 LLM 调用 Span 到对应 Trace。

        Args:
            trace_id: 对应的 Trace ID。
            span: LLM 调用记录。
        """
        record = self._traces.get(trace_id)
        if record is None:
            logger.warning("record_llm_call: trace_id=%s not found, skip.", trace_id)
            return
        record.llm_spans.append(span)
        logger.debug(
            "LLM span recorded: trace_id=%s, model=%s, tokens=%d",
            trace_id,
            span.model,
            span.usage.total_tokens,
        )

    def record_tool_call(self, trace_id: str, span: ToolCallSpan) -> None:
        """追加一条 Tool 调用 Span 到对应 Trace。

        Args:
            trace_id: 对应的 Trace ID。
            span: Tool 调用记录。
        """
        record = self._traces.get(trace_id)
        if record is None:
            logger.warning("record_tool_call: trace_id=%s not found, skip.", trace_id)
            return
        record.tool_spans.append(span)
        logger.debug(
            "Tool span recorded: trace_id=%s, tool_code=%s, success=%s",
            trace_id,
            span.tool_code,
            span.success,
        )

    def finish_trace(self, trace_id: str) -> TraceRecord:
        """标记 Trace 结束，返回完整的 TraceRecord。

        Args:
            trace_id: 对应的 Trace ID。

        Returns:
            完整的 TraceRecord（含所有 span）。

        Raises:
            KeyError: 如果 trace_id 不存在。
        """
        record = self._traces.get(trace_id)
        if record is None:
            raise KeyError(f"trace_id={trace_id!r} not found in observer")
        record.finished_at = datetime.utcnow()
        logger.info(
            "Trace finished: trace_id=%s, total_tokens=%d",
            trace_id,
            record.total_tokens.total_tokens,
        )
        return record

    def get_trace(self, trace_id: str) -> Optional[TraceRecord]:
        """查询 Trace 记录。

        Args:
            trace_id: 对应的 Trace ID。

        Returns:
            TraceRecord 或 None（不存在时）。
        """
        return self._traces.get(trace_id)

    def all_traces(self) -> list[TraceRecord]:
        """返回所有 Trace，按 started_at 倒序排列。

        Returns:
            TraceRecord 列表（新 → 旧）。
        """
        return sorted(self._traces.values(), key=lambda r: r.started_at, reverse=True)

    def clear(self) -> None:
        """清空所有 Trace 记录（仅用于测试重置）。"""
        self._traces.clear()


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_observer: Optional[Observer] = None


def get_observer() -> Observer:
    """获取全局 Observer 单例。

    Returns:
        全局唯一的 Observer 实例。
    """
    global _observer
    if _observer is None:
        _observer = Observer()
    return _observer


def reset_observer() -> None:
    """重置全局 Observer 单例（仅用于测试）。"""
    global _observer
    _observer = None


# ---------------------------------------------------------------------------
# 上下文管理器辅助类
# ---------------------------------------------------------------------------


class _LlmSpanContext:
    """LLM 调用计时上下文管理器。

    进入时开始计时，退出时自动记录 LlmCallSpan。
    usage 需在退出前通过 set_usage() 设置，否则默认为空。

    用法::

        async with llm_span_ctx(observer, trace_id, "agent", "gpt-4o") as ctx:
            response = await llm_client.chat(request)
            ctx.set_usage(response.usage)
    """

    def __init__(
        self,
        observer: Observer,
        trace_id: str,
        agent_code: str,
        model: str,
    ) -> None:
        self._observer = observer
        self._trace_id = trace_id
        self._agent_code = agent_code
        self._model = model
        self._start: float = 0.0
        self._usage: TokenUsage = TokenUsage()
        self._error: Optional[str] = None

    def set_usage(self, usage: TokenUsage) -> None:
        """设置本次 LLM 调用的 Token 用量。

        Args:
            usage: Token 统计数据。
        """
        self._usage = usage

    async def __aenter__(self) -> "_LlmSpanContext":
        self._start = time.monotonic()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: object,
    ) -> bool:
        latency_ms = (time.monotonic() - self._start) * 1000
        if exc_type is not None:
            self._error = str(exc_val)[:200]

        span = LlmCallSpan(
            trace_id=self._trace_id,
            agent_code=self._agent_code,
            model=self._model,
            usage=self._usage,
            latency_ms=latency_ms,
            error=self._error,
        )
        self._observer.record_llm_call(self._trace_id, span)
        return False  # 不吞异常


class _ToolSpanContext:
    """Tool 调用计时上下文管理器。

    进入时开始计时，退出时自动记录 ToolCallSpan。

    用法::

        async with tool_span_ctx(observer, trace_id, "agent", "search_web"):
            result = await tool.execute(params)
    """

    def __init__(
        self,
        observer: Observer,
        trace_id: str,
        agent_code: str,
        tool_code: str,
    ) -> None:
        self._observer = observer
        self._trace_id = trace_id
        self._agent_code = agent_code
        self._tool_code = tool_code
        self._start: float = 0.0

    async def __aenter__(self) -> "_ToolSpanContext":
        self._start = time.monotonic()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: object,
    ) -> bool:
        latency_ms = (time.monotonic() - self._start) * 1000
        success = exc_type is None
        error = str(exc_val)[:200] if exc_val is not None else None

        span = ToolCallSpan(
            trace_id=self._trace_id,
            agent_code=self._agent_code,
            tool_code=self._tool_code,
            latency_ms=latency_ms,
            success=success,
            error=error,
        )
        self._observer.record_tool_call(self._trace_id, span)
        return False  # 不吞异常


def llm_span_ctx(
    observer: Observer,
    trace_id: str,
    agent_code: str,
    model: str,
) -> _LlmSpanContext:
    """创建 LLM 调用的计时上下文管理器。

    Args:
        observer: Observer 实例。
        trace_id: 对应的 Trace ID。
        agent_code: Agent 标识。
        model: 调用的模型名称。

    Returns:
        _LlmSpanContext 实例，可用 async with 使用。

    示例::

        async with llm_span_ctx(observer, trace_id, "my_agent", "gpt-4o") as ctx:
            response = await client.chat(request)
            ctx.set_usage(response.usage)
    """
    return _LlmSpanContext(observer, trace_id, agent_code, model)


def tool_span_ctx(
    observer: Observer,
    trace_id: str,
    agent_code: str,
    tool_code: str,
) -> _ToolSpanContext:
    """创建 Tool 调用的计时上下文管理器。

    Args:
        observer: Observer 实例。
        trace_id: 对应的 Trace ID。
        agent_code: Agent 标识。
        tool_code: Tool 标识。

    Returns:
        _ToolSpanContext 实例，可用 async with 使用。

    示例::

        async with tool_span_ctx(observer, trace_id, "my_agent", "search_web"):
            result = await tool.execute(params)
    """
    return _ToolSpanContext(observer, trace_id, agent_code, tool_code)
