"""
tests/test_observer.py - observer 模块测试

覆盖：
- TokenUsage.add 累加
- TraceRecord.total_tokens 计算属性
- Observer CRUD：start_trace / record_llm_call / record_tool_call / finish_trace / get_trace / all_traces / clear
- llm_span_ctx 正常退出 + 异常退出
- tool_span_ctx 正常退出 + 异常退出
- 多 trace 并发（两个 trace_id 互不干扰）
- 全局单例 get_observer / reset_observer
"""

from __future__ import annotations

import asyncio
import pytest

from haiji.observer import (
    Observer,
    LlmCallSpan,
    TokenUsage,
    ToolCallSpan,
    TraceRecord,
    get_observer,
    llm_span_ctx,
    reset_observer,
    tool_span_ctx,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_obs():
    """每个测试前后都重置全局单例，防止测试间污染。"""
    reset_observer()
    yield
    reset_observer()


@pytest.fixture()
def obs() -> Observer:
    return Observer()


# ---------------------------------------------------------------------------
# TokenUsage
# ---------------------------------------------------------------------------


class TestTokenUsage:
    def test_default_zero(self):
        """默认值全为 0"""
        u = TokenUsage()
        assert u.prompt_tokens == 0
        assert u.completion_tokens == 0
        assert u.total_tokens == 0

    def test_add_returns_new_object(self):
        """add 返回新对象，不修改原对象"""
        a = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        b = TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30)
        c = a.add(b)
        assert c.prompt_tokens == 30
        assert c.completion_tokens == 15
        assert c.total_tokens == 45
        # 原对象不变
        assert a.prompt_tokens == 10
        assert b.prompt_tokens == 20

    def test_add_with_zero(self):
        """与 0 相加结果不变"""
        a = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        result = a.add(TokenUsage())
        assert result.prompt_tokens == 100
        assert result.total_tokens == 150

    def test_chain_add(self):
        """链式累加"""
        usages = [
            TokenUsage(prompt_tokens=i, completion_tokens=i, total_tokens=i * 2)
            for i in range(1, 5)
        ]
        total = TokenUsage()
        for u in usages:
            total = total.add(u)
        # 1+2+3+4=10
        assert total.prompt_tokens == 10
        assert total.total_tokens == 20


# ---------------------------------------------------------------------------
# TraceRecord.total_tokens（计算属性）
# ---------------------------------------------------------------------------


class TestTraceRecordTotalTokens:
    def test_no_spans_returns_zero(self):
        """无 LLM span 时，total_tokens 全为 0"""
        record = TraceRecord(trace_id="t1", agent_code="agent", session_id="s1")
        assert record.total_tokens.total_tokens == 0

    def test_single_span(self):
        """单个 span 的 tokens 正确汇总"""
        record = TraceRecord(trace_id="t1", agent_code="agent", session_id="s1")
        span = LlmCallSpan(
            trace_id="t1",
            agent_code="agent",
            model="gpt-4o",
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        )
        record.llm_spans.append(span)
        assert record.total_tokens.prompt_tokens == 100
        assert record.total_tokens.completion_tokens == 50
        assert record.total_tokens.total_tokens == 150

    def test_multiple_spans_accumulate(self):
        """多个 span 的 tokens 正确累加"""
        record = TraceRecord(trace_id="t1", agent_code="agent", session_id="s1")
        for i in range(3):
            span = LlmCallSpan(
                trace_id="t1",
                agent_code="agent",
                model="gpt-4o",
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )
            record.llm_spans.append(span)
        assert record.total_tokens.prompt_tokens == 30
        assert record.total_tokens.total_tokens == 45

    def test_tool_spans_not_counted(self):
        """Tool span 不计入 total_tokens"""
        record = TraceRecord(trace_id="t1", agent_code="agent", session_id="s1")
        tool_span = ToolCallSpan(
            trace_id="t1", agent_code="agent", tool_code="search"
        )
        record.tool_spans.append(tool_span)
        assert record.total_tokens.total_tokens == 0


# ---------------------------------------------------------------------------
# Observer CRUD
# ---------------------------------------------------------------------------


class TestObserverStartTrace:
    def test_start_trace_returns_record(self, obs: Observer):
        """start_trace 返回 TraceRecord"""
        record = obs.start_trace("t1", "agent_a", "session-1")
        assert isinstance(record, TraceRecord)
        assert record.trace_id == "t1"
        assert record.agent_code == "agent_a"
        assert record.session_id == "session-1"
        assert record.finished_at is None

    def test_start_trace_stored_in_observer(self, obs: Observer):
        """start_trace 后可以 get_trace 查到"""
        obs.start_trace("t1", "agent_a", "session-1")
        retrieved = obs.get_trace("t1")
        assert retrieved is not None
        assert retrieved.trace_id == "t1"


class TestObserverRecordLlmCall:
    def test_record_llm_call_appends_span(self, obs: Observer):
        """record_llm_call 将 span 追加到 trace"""
        obs.start_trace("t1", "agent_a", "session-1")
        span = LlmCallSpan(trace_id="t1", agent_code="agent_a", model="gpt-4o")
        obs.record_llm_call("t1", span)
        record = obs.get_trace("t1")
        assert len(record.llm_spans) == 1
        assert record.llm_spans[0].model == "gpt-4o"

    def test_record_llm_call_unknown_trace_skipped(self, obs: Observer):
        """未知 trace_id 时静默跳过，不报错"""
        span = LlmCallSpan(trace_id="unknown", agent_code="agent_a", model="gpt-4o")
        obs.record_llm_call("unknown", span)  # 不应 raise

    def test_record_multiple_llm_spans(self, obs: Observer):
        """多个 LLM span 都被记录"""
        obs.start_trace("t1", "agent_a", "session-1")
        for i in range(3):
            span = LlmCallSpan(trace_id="t1", agent_code="agent_a", model="gpt-4o")
            obs.record_llm_call("t1", span)
        record = obs.get_trace("t1")
        assert len(record.llm_spans) == 3


class TestObserverRecordToolCall:
    def test_record_tool_call_appends_span(self, obs: Observer):
        """record_tool_call 将 span 追加到 trace"""
        obs.start_trace("t1", "agent_a", "session-1")
        span = ToolCallSpan(trace_id="t1", agent_code="agent_a", tool_code="search")
        obs.record_tool_call("t1", span)
        record = obs.get_trace("t1")
        assert len(record.tool_spans) == 1
        assert record.tool_spans[0].tool_code == "search"

    def test_record_tool_call_unknown_trace_skipped(self, obs: Observer):
        """未知 trace_id 时静默跳过"""
        span = ToolCallSpan(trace_id="unknown", agent_code="agent_a", tool_code="search")
        obs.record_tool_call("unknown", span)

    def test_record_multiple_tool_spans(self, obs: Observer):
        """多个 Tool span 都被记录"""
        obs.start_trace("t1", "agent_a", "session-1")
        for i in range(2):
            span = ToolCallSpan(trace_id="t1", agent_code="agent_a", tool_code=f"tool_{i}")
            obs.record_tool_call("t1", span)
        record = obs.get_trace("t1")
        assert len(record.tool_spans) == 2


class TestObserverFinishTrace:
    def test_finish_trace_sets_finished_at(self, obs: Observer):
        """finish_trace 设置 finished_at"""
        obs.start_trace("t1", "agent_a", "session-1")
        record = obs.finish_trace("t1")
        assert record.finished_at is not None

    def test_finish_trace_returns_full_record(self, obs: Observer):
        """finish_trace 返回包含所有 span 的完整记录"""
        obs.start_trace("t1", "agent_a", "session-1")
        llm_span = LlmCallSpan(
            trace_id="t1",
            agent_code="agent_a",
            model="gpt-4o",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )
        obs.record_llm_call("t1", llm_span)
        record = obs.finish_trace("t1")
        assert len(record.llm_spans) == 1
        assert record.total_tokens.total_tokens == 15

    def test_finish_trace_unknown_raises_key_error(self, obs: Observer):
        """finish_trace 未知 trace_id 时抛 KeyError"""
        with pytest.raises(KeyError):
            obs.finish_trace("non-existent")


class TestObserverGetTrace:
    def test_get_trace_returns_none_for_unknown(self, obs: Observer):
        """get_trace 未知 trace_id 返回 None"""
        assert obs.get_trace("unknown") is None

    def test_get_trace_returns_record(self, obs: Observer):
        """get_trace 已知 trace_id 返回 record"""
        obs.start_trace("t1", "agent_a", "session-1")
        record = obs.get_trace("t1")
        assert record is not None


class TestObserverAllTraces:
    def test_all_traces_empty(self, obs: Observer):
        """无 trace 时返回空列表"""
        assert obs.all_traces() == []

    def test_all_traces_returns_all(self, obs: Observer):
        """all_traces 返回所有 trace"""
        obs.start_trace("t1", "agent_a", "session-1")
        obs.start_trace("t2", "agent_b", "session-2")
        all_t = obs.all_traces()
        assert len(all_t) == 2

    def test_all_traces_sorted_by_started_at_desc(self, obs: Observer):
        """all_traces 按 started_at 倒序（新的在前）"""
        import time as _time

        obs.start_trace("t1", "agent_a", "session-1")
        _time.sleep(0.01)
        obs.start_trace("t2", "agent_b", "session-2")
        all_t = obs.all_traces()
        # t2 更新，应排在前面
        assert all_t[0].trace_id == "t2"
        assert all_t[1].trace_id == "t1"


class TestObserverClear:
    def test_clear_removes_all_traces(self, obs: Observer):
        """clear 后 all_traces 为空"""
        obs.start_trace("t1", "agent_a", "session-1")
        obs.clear()
        assert obs.all_traces() == []
        assert obs.get_trace("t1") is None


# ---------------------------------------------------------------------------
# 多 Trace 并发隔离
# ---------------------------------------------------------------------------


class TestMultiTraceIsolation:
    def test_two_traces_independent(self, obs: Observer):
        """两个 trace_id 的数据互不干扰"""
        obs.start_trace("t1", "agent_a", "session-1")
        obs.start_trace("t2", "agent_b", "session-2")

        span1 = LlmCallSpan(
            trace_id="t1",
            agent_code="agent_a",
            model="gpt-4o",
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        )
        span2 = LlmCallSpan(
            trace_id="t2",
            agent_code="agent_b",
            model="gpt-3.5-turbo",
            usage=TokenUsage(prompt_tokens=200, completion_tokens=100, total_tokens=300),
        )
        obs.record_llm_call("t1", span1)
        obs.record_llm_call("t2", span2)

        r1 = obs.get_trace("t1")
        r2 = obs.get_trace("t2")

        assert r1.total_tokens.total_tokens == 150
        assert r2.total_tokens.total_tokens == 300
        assert len(r1.llm_spans) == 1
        assert len(r2.llm_spans) == 1

    def test_tool_spans_isolated(self, obs: Observer):
        """Tool span 只归属于对应 trace"""
        obs.start_trace("t1", "agent_a", "session-1")
        obs.start_trace("t2", "agent_b", "session-2")

        obs.record_tool_call("t1", ToolCallSpan(trace_id="t1", agent_code="agent_a", tool_code="search"))
        obs.record_tool_call("t2", ToolCallSpan(trace_id="t2", agent_code="agent_b", tool_code="calc"))

        assert obs.get_trace("t1").tool_spans[0].tool_code == "search"
        assert obs.get_trace("t2").tool_spans[0].tool_code == "calc"


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------


class TestGlobalSingleton:
    def test_get_observer_returns_same_instance(self):
        """get_observer 返回同一个实例"""
        obs1 = get_observer()
        obs2 = get_observer()
        assert obs1 is obs2

    def test_reset_observer_creates_new_instance(self):
        """reset_observer 后 get_observer 返回新实例"""
        obs1 = get_observer()
        obs1.start_trace("t1", "agent_a", "session-1")
        reset_observer()
        obs2 = get_observer()
        assert obs2.get_trace("t1") is None


# ---------------------------------------------------------------------------
# llm_span_ctx 上下文管理器
# ---------------------------------------------------------------------------


class TestLlmSpanCtx:
    @pytest.mark.asyncio
    async def test_normal_exit_records_span(self, obs: Observer):
        """正常退出后 LLM span 被记录"""
        obs.start_trace("t1", "agent_a", "session-1")

        async with llm_span_ctx(obs, "t1", "agent_a", "gpt-4o") as ctx:
            ctx.set_usage(TokenUsage(prompt_tokens=50, completion_tokens=25, total_tokens=75))

        record = obs.get_trace("t1")
        assert len(record.llm_spans) == 1
        span = record.llm_spans[0]
        assert span.model == "gpt-4o"
        assert span.usage.total_tokens == 75
        assert span.error is None
        assert span.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_exception_exit_records_error(self, obs: Observer):
        """异常退出后 error 字段被设置，span 仍然被记录"""
        obs.start_trace("t1", "agent_a", "session-1")

        with pytest.raises(ValueError):
            async with llm_span_ctx(obs, "t1", "agent_a", "gpt-4o"):
                raise ValueError("LLM timeout")

        record = obs.get_trace("t1")
        assert len(record.llm_spans) == 1
        span = record.llm_spans[0]
        assert span.error is not None
        assert "LLM timeout" in span.error

    @pytest.mark.asyncio
    async def test_latency_measured(self, obs: Observer):
        """latency_ms 大于等于 0"""
        obs.start_trace("t1", "agent_a", "session-1")

        async with llm_span_ctx(obs, "t1", "agent_a", "gpt-4o") as ctx:
            await asyncio.sleep(0.01)
            ctx.set_usage(TokenUsage())

        record = obs.get_trace("t1")
        assert record.llm_spans[0].latency_ms >= 0

    @pytest.mark.asyncio
    async def test_default_usage_is_zero(self, obs: Observer):
        """不调用 set_usage 时，usage 默认为全零"""
        obs.start_trace("t1", "agent_a", "session-1")

        async with llm_span_ctx(obs, "t1", "agent_a", "gpt-4o"):
            pass  # 不 set_usage

        record = obs.get_trace("t1")
        assert record.llm_spans[0].usage.total_tokens == 0


# ---------------------------------------------------------------------------
# tool_span_ctx 上下文管理器
# ---------------------------------------------------------------------------


class TestToolSpanCtx:
    @pytest.mark.asyncio
    async def test_normal_exit_records_success_span(self, obs: Observer):
        """正常退出后 Tool span 被记录，success=True"""
        obs.start_trace("t1", "agent_a", "session-1")

        async with tool_span_ctx(obs, "t1", "agent_a", "search_web"):
            pass

        record = obs.get_trace("t1")
        assert len(record.tool_spans) == 1
        span = record.tool_spans[0]
        assert span.tool_code == "search_web"
        assert span.success is True
        assert span.error is None

    @pytest.mark.asyncio
    async def test_exception_exit_records_failure_span(self, obs: Observer):
        """异常退出后 success=False 且 error 字段被设置"""
        obs.start_trace("t1", "agent_a", "session-1")

        with pytest.raises(RuntimeError):
            async with tool_span_ctx(obs, "t1", "agent_a", "search_web"):
                raise RuntimeError("Tool execution failed")

        record = obs.get_trace("t1")
        assert len(record.tool_spans) == 1
        span = record.tool_spans[0]
        assert span.success is False
        assert span.error is not None
        assert "Tool execution failed" in span.error

    @pytest.mark.asyncio
    async def test_latency_measured(self, obs: Observer):
        """latency_ms 大于等于 0"""
        obs.start_trace("t1", "agent_a", "session-1")

        async with tool_span_ctx(obs, "t1", "agent_a", "calc"):
            await asyncio.sleep(0.01)

        record = obs.get_trace("t1")
        assert record.tool_spans[0].latency_ms >= 0

    @pytest.mark.asyncio
    async def test_multiple_tool_spans_in_sequence(self, obs: Observer):
        """多次 tool_span_ctx 都被记录"""
        obs.start_trace("t1", "agent_a", "session-1")

        for tool_name in ["search", "calc", "format"]:
            async with tool_span_ctx(obs, "t1", "agent_a", tool_name):
                pass

        record = obs.get_trace("t1")
        assert len(record.tool_spans) == 3
        tool_codes = [s.tool_code for s in record.tool_spans]
        assert "search" in tool_codes
        assert "calc" in tool_codes
        assert "format" in tool_codes
