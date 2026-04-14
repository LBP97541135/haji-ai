"""
tests/test_startup.py - Startup 模块单元测试

覆盖：
- TriggerConfig / StartupConfig / TriggerEvent / StartupResult 数据结构
- CronRunner：cron 表达式解析与匹配
- StartupScheduler：register / unregister / all_configs
- StartupScheduler：fire_event 并发触发
- StartupScheduler：fire_webhook 触发
- StartupScheduler：_execute Agent 执行（含失败场景）
- StartupScheduler：CONDITION 触发检查
- StartupScheduler：get_results / clear_results
- StartupScheduler：start / stop（Cron 循环，不等待完整循环）
- get_startup_scheduler / reset_startup_scheduler 单例
- StartupConfig.render_message 模板渲染
- StartupConfig.make_session_id 策略
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
import pytest_asyncio

from haiji.agent.base import BaseAgent, agent
from haiji.agent.registry import get_agent_registry
from haiji.llm.definition import LlmResponse, ToolCall
from haiji.memory.base import SessionMemoryManager
from haiji.sse.base import SseEventEmitter
from haiji.sse.definition import SseEventType
from haiji.startup import (
    CronRunner,
    StartupConfig,
    StartupResult,
    StartupScheduler,
    TriggerConfig,
    TriggerEvent,
    TriggerKind,
    get_startup_scheduler,
    reset_startup_scheduler,
)
from haiji.startup.definition import StartupConfig


# ---------------------------------------------------------------------------
# 测试 fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_registries():
    """每个测试前重置全局注册表"""
    from haiji.agent.registry import get_agent_registry
    from haiji.tool.base import get_tool_registry
    from haiji.skill.base import get_skill_registry

    # 清空注册表内部字典
    get_agent_registry()._agents.clear()
    get_tool_registry()._tools.clear()
    get_skill_registry()._skills.clear()
    reset_startup_scheduler()
    yield
    get_agent_registry()._agents.clear()
    get_tool_registry()._tools.clear()
    get_skill_registry()._skills.clear()
    reset_startup_scheduler()


def make_mock_llm(stream_tokens: Optional[list[str]] = None) -> MagicMock:
    """创建 Mock LLM 客户端"""
    mock_llm = MagicMock()

    tokens = stream_tokens or ["Hello", " World"]

    async def _stream_gen(request):
        for token in tokens:
            yield token

    mock_llm.stream_chat = _stream_gen

    mock_response = LlmResponse(content="Hello World", tool_calls=None, usage=None)
    mock_llm.chat_with_tools = AsyncMock(return_value=mock_response)

    return mock_llm


def make_test_agent() -> type:
    """创建一个最简单的测试 Agent（DIRECT 模式）"""
    @agent(mode="direct", code="test_startup_agent")
    class TestStartupAgent(BaseAgent):
        system_prompt = "你是测试助手"

    return TestStartupAgent


# ===========================================================================
# 1. 数据结构测试
# ===========================================================================


class TestTriggerConfig:
    """TriggerConfig 数据结构测试"""

    def test_cron_trigger_config(self):
        config = TriggerConfig(kind=TriggerKind.CRON, cron_expr="0 9 * * *")
        assert config.kind == TriggerKind.CRON
        assert config.cron_expr == "0 9 * * *"
        assert config.event_name is None
        assert config.webhook_path is None

    def test_event_trigger_config(self):
        config = TriggerConfig(kind=TriggerKind.EVENT, event_name="user_registered")
        assert config.kind == TriggerKind.EVENT
        assert config.event_name == "user_registered"

    def test_webhook_trigger_config(self):
        config = TriggerConfig(kind=TriggerKind.WEBHOOK, webhook_path="/hooks/my_agent")
        assert config.kind == TriggerKind.WEBHOOK
        assert config.webhook_path == "/hooks/my_agent"

    def test_condition_trigger_config(self):
        fn = lambda: True  # noqa: E731
        config = TriggerConfig(kind=TriggerKind.CONDITION, condition_fn=fn)
        assert config.kind == TriggerKind.CONDITION
        assert config.condition_fn is fn


class TestStartupConfig:
    """StartupConfig 数据结构测试"""

    def test_basic_config(self):
        config = StartupConfig(
            agent_code="my_agent",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="test"),
        )
        assert config.agent_code == "my_agent"
        assert config.enabled is True
        assert config.startup_id  # 自动生成

    def test_make_session_id_default(self):
        config = StartupConfig(
            agent_code="my_agent",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="test"),
        )
        sid1 = config.make_session_id()
        sid2 = config.make_session_id()
        # 默认每次生成唯一 id
        assert sid1 != sid2
        assert sid1.startswith("my_agent_")

    def test_make_session_id_fixed(self):
        config = StartupConfig(
            agent_code="my_agent",
            session_id_factory="fixed",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="test"),
        )
        sid1 = config.make_session_id()
        sid2 = config.make_session_id()
        assert sid1 == sid2 == "my_agent"

    def test_render_message_event_data(self):
        config = StartupConfig(
            agent_code="my_agent",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="test"),
            initial_message_template="收到事件：{{event_name}}，数据：{{event_data}}",
        )
        event = TriggerEvent(
            trigger_kind=TriggerKind.EVENT,
            event_name="user_registered",
            payload={"user_id": "u_1"},
        )
        message = config.render_message(event)
        assert "user_registered" in message
        assert "u_1" in message

    def test_render_message_triggered_at(self):
        config = StartupConfig(
            agent_code="my_agent",
            trigger=TriggerConfig(kind=TriggerKind.CRON, cron_expr="0 9 * * *"),
            initial_message_template="触发时间：{{triggered_at}}",
        )
        now = datetime(2026, 4, 14, 9, 0, 0)
        event = TriggerEvent(
            trigger_kind=TriggerKind.CRON,
            payload={},
            triggered_at=now,
        )
        message = config.render_message(event)
        assert "2026-04-14" in message


class TestTriggerEvent:
    """TriggerEvent 数据结构测试"""

    def test_event_id_auto_generated(self):
        e1 = TriggerEvent(trigger_kind=TriggerKind.EVENT)
        e2 = TriggerEvent(trigger_kind=TriggerKind.EVENT)
        assert e1.event_id != e2.event_id

    def test_triggered_at_default_now(self):
        before = datetime.now()
        event = TriggerEvent(trigger_kind=TriggerKind.CRON)
        after = datetime.now()
        assert before <= event.triggered_at <= after

    def test_payload_default_empty(self):
        event = TriggerEvent(trigger_kind=TriggerKind.WEBHOOK)
        assert event.payload == {}


class TestStartupResult:
    """StartupResult 数据结构测试"""

    def test_duration_ms(self):
        from datetime import timedelta
        now = datetime.now()
        finished = now + timedelta(seconds=2)
        result = StartupResult(
            event_id="e1",
            startup_id="s1",
            agent_code="agent",
            session_id="sess",
            success=True,
            started_at=now,
            finished_at=finished,
        )
        assert result.duration_ms is not None
        assert result.duration_ms >= 1000  # 至少 1 秒（2000ms）

    def test_duration_ms_none_when_not_finished(self):
        result = StartupResult(
            event_id="e1",
            startup_id="s1",
            agent_code="agent",
            session_id="sess",
            success=True,
            started_at=datetime.now(),
            finished_at=None,
        )
        assert result.duration_ms is None


# ===========================================================================
# 2. CronRunner 测试
# ===========================================================================


class TestCronRunner:
    """CronRunner cron 表达式解析测试"""

    def test_wildcard_matches_any(self):
        runner = CronRunner("* * * * *")  # 任意时间都匹配
        assert runner.matches(datetime(2026, 4, 14, 9, 0))
        assert runner.matches(datetime(2026, 12, 31, 23, 59))

    def test_fixed_minute(self):
        runner = CronRunner("30 * * * *")  # 每小时 :30 触发
        assert runner.matches(datetime(2026, 4, 14, 9, 30))
        assert not runner.matches(datetime(2026, 4, 14, 9, 0))
        assert not runner.matches(datetime(2026, 4, 14, 9, 31))

    def test_fixed_hour(self):
        runner = CronRunner("0 9 * * *")  # 每天 09:00
        assert runner.matches(datetime(2026, 4, 14, 9, 0))
        assert not runner.matches(datetime(2026, 4, 14, 10, 0))
        assert not runner.matches(datetime(2026, 4, 14, 9, 1))

    def test_step_expression(self):
        runner = CronRunner("*/5 * * * *")  # 每 5 分钟
        assert runner.matches(datetime(2026, 4, 14, 9, 0))
        assert runner.matches(datetime(2026, 4, 14, 9, 5))
        assert runner.matches(datetime(2026, 4, 14, 9, 30))
        assert not runner.matches(datetime(2026, 4, 14, 9, 1))
        assert not runner.matches(datetime(2026, 4, 14, 9, 7))

    def test_step_hour(self):
        runner = CronRunner("0 */6 * * *")  # 每 6 小时（0, 6, 12, 18）
        assert runner.matches(datetime(2026, 4, 14, 0, 0))
        assert runner.matches(datetime(2026, 4, 14, 6, 0))
        assert runner.matches(datetime(2026, 4, 14, 12, 0))
        assert runner.matches(datetime(2026, 4, 14, 18, 0))
        assert not runner.matches(datetime(2026, 4, 14, 3, 0))

    def test_fixed_weekday(self):
        # 2026-04-13 是周一（Python weekday=0, Cron weekday=1）
        runner = CronRunner("0 9 * * 1")  # 每周一 09:00
        assert runner.matches(datetime(2026, 4, 13, 9, 0))  # 周一
        assert not runner.matches(datetime(2026, 4, 14, 9, 0))  # 周二

    def test_sunday(self):
        # 2026-04-12 是周日（Python weekday=6, Cron weekday=0）
        runner = CronRunner("0 9 * * 0")  # 每周日 09:00
        assert runner.matches(datetime(2026, 4, 12, 9, 0))
        assert not runner.matches(datetime(2026, 4, 13, 9, 0))  # 周一

    def test_fixed_day_and_month(self):
        runner = CronRunner("0 0 1 1 *")  # 每年 1 月 1 日 00:00
        assert runner.matches(datetime(2026, 1, 1, 0, 0))
        assert not runner.matches(datetime(2026, 1, 2, 0, 0))
        assert not runner.matches(datetime(2026, 2, 1, 0, 0))

    def test_enum_expression(self):
        runner = CronRunner("0 9,18 * * *")  # 每天 09:00 和 18:00
        assert runner.matches(datetime(2026, 4, 14, 9, 0))
        assert runner.matches(datetime(2026, 4, 14, 18, 0))
        assert not runner.matches(datetime(2026, 4, 14, 12, 0))

    def test_invalid_field_count(self):
        with pytest.raises(ValueError, match="5 字段"):
            CronRunner("* * * *")  # 只有 4 字段

    def test_invalid_step_zero(self):
        with pytest.raises(ValueError):
            CronRunner("*/0 * * * *")

    def test_invalid_value_out_of_range(self):
        with pytest.raises(ValueError):
            CronRunner("60 * * * *")  # 分钟最大 59

    def test_invalid_hour_out_of_range(self):
        with pytest.raises(ValueError):
            CronRunner("0 24 * * *")  # 小时最大 23

    def test_expr_property(self):
        runner = CronRunner("0 9 * * *")
        assert runner.expr == "0 9 * * *"


# ===========================================================================
# 3. StartupScheduler：注册 / 注销 / 查询
# ===========================================================================


class TestStartupSchedulerRegister:
    """StartupScheduler 注册相关测试"""

    def test_register_returns_startup_id(self):
        scheduler = StartupScheduler()
        config = StartupConfig(
            agent_code="agent1",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="test"),
        )
        startup_id = scheduler.register(config)
        assert startup_id == config.startup_id

    def test_register_multiple_configs(self):
        scheduler = StartupScheduler()
        for i in range(3):
            scheduler.register(StartupConfig(
                agent_code=f"agent_{i}",
                trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name=f"event_{i}"),
            ))
        assert len(scheduler.all_configs()) == 3

    def test_unregister_existing(self):
        scheduler = StartupScheduler()
        config = StartupConfig(
            agent_code="agent1",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="test"),
        )
        startup_id = scheduler.register(config)
        assert scheduler.unregister(startup_id) is True
        assert len(scheduler.all_configs()) == 0

    def test_unregister_nonexistent(self):
        scheduler = StartupScheduler()
        assert scheduler.unregister("nonexistent_id") is False

    def test_event_index_built_on_register(self):
        scheduler = StartupScheduler()
        config = StartupConfig(
            agent_code="agent1",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="my_event"),
        )
        scheduler.register(config)
        assert "my_event" in scheduler._event_index
        assert config.startup_id in scheduler._event_index["my_event"]

    def test_event_index_cleaned_on_unregister(self):
        scheduler = StartupScheduler()
        config = StartupConfig(
            agent_code="agent1",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="my_event"),
        )
        startup_id = scheduler.register(config)
        scheduler.unregister(startup_id)
        assert "my_event" not in scheduler._event_index

    def test_webhook_index_built_on_register(self):
        scheduler = StartupScheduler()
        config = StartupConfig(
            agent_code="agent1",
            trigger=TriggerConfig(kind=TriggerKind.WEBHOOK, webhook_path="/hooks/test"),
        )
        scheduler.register(config)
        assert "/hooks/test" in scheduler._webhook_index

    def test_webhook_index_cleaned_on_unregister(self):
        scheduler = StartupScheduler()
        config = StartupConfig(
            agent_code="agent1",
            trigger=TriggerConfig(kind=TriggerKind.WEBHOOK, webhook_path="/hooks/test"),
        )
        startup_id = scheduler.register(config)
        scheduler.unregister(startup_id)
        assert "/hooks/test" not in scheduler._webhook_index


# ===========================================================================
# 4. StartupScheduler：fire_event
# ===========================================================================


@pytest.mark.asyncio
class TestStartupSchedulerFireEvent:
    """fire_event 并发触发测试"""

    async def test_fire_event_triggers_matching_agent(self):
        make_test_agent()  # 注册 test_startup_agent
        mock_llm = make_mock_llm()

        scheduler = StartupScheduler()
        scheduler._llm_client = mock_llm

        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="my_event"),
        )
        scheduler.register(config)

        results = await scheduler.fire_event("my_event", {"key": "value"})
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].agent_code == "test_startup_agent"

    async def test_fire_event_no_matching_config_returns_empty(self):
        scheduler = StartupScheduler()
        results = await scheduler.fire_event("nonexistent_event")
        assert results == []

    async def test_fire_event_concurrent_multiple_configs(self):
        """多个 Startup 配置监听同一事件，并发触发"""
        make_test_agent()
        mock_llm = make_mock_llm()
        scheduler = StartupScheduler()
        scheduler._llm_client = mock_llm

        for i in range(3):
            scheduler.register(StartupConfig(
                agent_code="test_startup_agent",
                trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="shared_event"),
            ))

        results = await scheduler.fire_event("shared_event", {})
        assert len(results) == 3
        assert all(r.success for r in results)

    async def test_fire_event_skips_disabled_config(self):
        make_test_agent()
        mock_llm = make_mock_llm()
        scheduler = StartupScheduler()
        scheduler._llm_client = mock_llm

        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="my_event"),
            enabled=False,
        )
        scheduler.register(config)

        results = await scheduler.fire_event("my_event", {})
        assert results == []  # 禁用的配置不触发

    async def test_fire_event_agent_not_found_returns_failure(self):
        scheduler = StartupScheduler()
        config = StartupConfig(
            agent_code="nonexistent_agent",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="my_event"),
        )
        scheduler.register(config)

        results = await scheduler.fire_event("my_event", {})
        assert len(results) == 1
        assert results[0].success is False
        assert "未注册" in (results[0].error or "")


# ===========================================================================
# 5. StartupScheduler：fire_webhook
# ===========================================================================


@pytest.mark.asyncio
class TestStartupSchedulerFireWebhook:
    """fire_webhook 触发测试"""

    async def test_fire_webhook_triggers_agent(self):
        make_test_agent()
        mock_llm = make_mock_llm()
        scheduler = StartupScheduler()
        scheduler._llm_client = mock_llm

        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.WEBHOOK, webhook_path="/hooks/test"),
        )
        scheduler.register(config)

        result = await scheduler.fire_webhook("/hooks/test", {"data": "hello"})
        assert result is not None
        assert result.success is True

    async def test_fire_webhook_no_match_returns_none(self):
        scheduler = StartupScheduler()
        result = await scheduler.fire_webhook("/hooks/nonexistent")
        assert result is None

    async def test_fire_webhook_disabled_config_returns_none(self):
        make_test_agent()
        scheduler = StartupScheduler()

        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.WEBHOOK, webhook_path="/hooks/test"),
            enabled=False,
        )
        scheduler.register(config)

        result = await scheduler.fire_webhook("/hooks/test", {})
        assert result is None


# ===========================================================================
# 6. StartupScheduler：_execute
# ===========================================================================


@pytest.mark.asyncio
class TestStartupSchedulerExecute:
    """_execute 执行逻辑测试"""

    async def test_execute_success_records_result(self):
        make_test_agent()
        mock_llm = make_mock_llm()
        scheduler = StartupScheduler()
        scheduler._llm_client = mock_llm

        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.CRON, cron_expr="0 9 * * *"),
        )
        event = TriggerEvent(trigger_kind=TriggerKind.CRON, payload={})
        result = await scheduler._execute(config, event)

        assert result.success is True
        assert result.finished_at is not None
        assert result.duration_ms is not None
        assert result.duration_ms >= 0

    async def test_execute_failure_records_result(self):
        """Agent 不存在时执行失败"""
        scheduler = StartupScheduler()

        config = StartupConfig(
            agent_code="nonexistent_agent",
            trigger=TriggerConfig(kind=TriggerKind.CRON, cron_expr="0 9 * * *"),
        )
        event = TriggerEvent(trigger_kind=TriggerKind.CRON, payload={})
        result = await scheduler._execute(config, event)

        assert result.success is False
        assert result.error is not None

    async def test_execute_appends_to_results_history(self):
        make_test_agent()
        mock_llm = make_mock_llm()
        scheduler = StartupScheduler()
        scheduler._llm_client = mock_llm

        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="test"),
        )
        event = TriggerEvent(trigger_kind=TriggerKind.EVENT, payload={})
        await scheduler._execute(config, event)
        await scheduler._execute(config, event)

        results = scheduler.get_results()
        assert len(results) == 2

    async def test_execute_uses_session_id_from_config(self):
        make_test_agent()
        mock_llm = make_mock_llm()
        scheduler = StartupScheduler()
        scheduler._llm_client = mock_llm

        config = StartupConfig(
            agent_code="test_startup_agent",
            session_id_factory="fixed",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="test"),
        )
        event = TriggerEvent(trigger_kind=TriggerKind.EVENT, payload={})
        result = await scheduler._execute(config, event)

        assert result.session_id == "test_startup_agent"


# ===========================================================================
# 7. StartupScheduler：CONDITION 触发
# ===========================================================================


@pytest.mark.asyncio
class TestStartupSchedulerCondition:
    """CONDITION 触发器测试"""

    async def test_condition_true_triggers_agent(self):
        make_test_agent()
        mock_llm = make_mock_llm()
        scheduler = StartupScheduler()
        scheduler._llm_client = mock_llm

        trigger_count = [0]

        def always_true():
            trigger_count[0] += 1
            return True

        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.CONDITION, condition_fn=always_true),
        )
        scheduler.register(config)

        await scheduler._check_condition_triggers()

        assert trigger_count[0] == 1
        assert len(scheduler.get_results()) == 1

    async def test_condition_false_does_not_trigger(self):
        make_test_agent()
        scheduler = StartupScheduler()

        def always_false():
            return False

        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.CONDITION, condition_fn=always_false),
        )
        scheduler.register(config)

        await scheduler._check_condition_triggers()
        assert len(scheduler.get_results()) == 0

    async def test_condition_exception_is_handled(self):
        make_test_agent()
        scheduler = StartupScheduler()

        def broken_fn():
            raise RuntimeError("条件检查崩了")

        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.CONDITION, condition_fn=broken_fn),
        )
        scheduler.register(config)

        # 不应该抛出异常，只打日志
        await scheduler._check_condition_triggers()
        assert len(scheduler.get_results()) == 0


# ===========================================================================
# 8. StartupScheduler：get_results / clear_results
# ===========================================================================


@pytest.mark.asyncio
class TestStartupSchedulerResults:
    """执行历史测试"""

    async def test_get_results_all(self):
        make_test_agent()
        mock_llm = make_mock_llm()
        scheduler = StartupScheduler()
        scheduler._llm_client = mock_llm

        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="test"),
        )
        event = TriggerEvent(trigger_kind=TriggerKind.EVENT, payload={})
        await scheduler._execute(config, event)
        await scheduler._execute(config, event)

        results = scheduler.get_results()
        assert len(results) == 2

    async def test_get_results_filter_by_agent_code(self):
        # 注册两个 Agent
        @agent(mode="direct", code="agent_a")
        class AgentA(BaseAgent):
            system_prompt = "Agent A"

        @agent(mode="direct", code="agent_b")
        class AgentB(BaseAgent):
            system_prompt = "Agent B"

        mock_llm = make_mock_llm()
        scheduler = StartupScheduler()
        scheduler._llm_client = mock_llm

        for code in ["agent_a", "agent_b"]:
            config = StartupConfig(
                agent_code=code,
                trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="test"),
            )
            event = TriggerEvent(trigger_kind=TriggerKind.EVENT, payload={})
            await scheduler._execute(config, event)

        assert len(scheduler.get_results("agent_a")) == 1
        assert len(scheduler.get_results("agent_b")) == 1
        assert len(scheduler.get_results()) == 2

    async def test_get_results_sorted_by_time_desc(self):
        make_test_agent()
        mock_llm = make_mock_llm()
        scheduler = StartupScheduler()
        scheduler._llm_client = mock_llm

        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="test"),
        )
        event = TriggerEvent(trigger_kind=TriggerKind.EVENT, payload={})
        for _ in range(3):
            await scheduler._execute(config, event)
            await asyncio.sleep(0.01)  # 确保时间有序

        results = scheduler.get_results()
        for i in range(len(results) - 1):
            assert results[i].started_at >= results[i + 1].started_at

    async def test_clear_results(self):
        make_test_agent()
        mock_llm = make_mock_llm()
        scheduler = StartupScheduler()
        scheduler._llm_client = mock_llm

        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="test"),
        )
        event = TriggerEvent(trigger_kind=TriggerKind.EVENT, payload={})
        await scheduler._execute(config, event)

        assert len(scheduler.get_results()) == 1
        scheduler.clear_results()
        assert len(scheduler.get_results()) == 0


# ===========================================================================
# 9. StartupScheduler：start / stop
# ===========================================================================


@pytest.mark.asyncio
class TestStartupSchedulerStartStop:
    """start / stop 测试（不等完整 Cron 循环）"""

    async def test_start_sets_running_true(self):
        scheduler = StartupScheduler()
        assert not scheduler.is_running
        await scheduler.start()
        assert scheduler.is_running
        await scheduler.stop()

    async def test_stop_sets_running_false(self):
        scheduler = StartupScheduler()
        await scheduler.start()
        await scheduler.stop()
        assert not scheduler.is_running

    async def test_double_start_is_safe(self):
        """重复 start() 不应报错"""
        scheduler = StartupScheduler()
        await scheduler.start()
        await scheduler.start()  # 第二次 start 应该被忽略
        assert scheduler.is_running
        await scheduler.stop()

    async def test_stop_without_start_is_safe(self):
        """未 start 的情况下 stop() 不应报错"""
        scheduler = StartupScheduler()
        await scheduler.stop()  # 应该安全

    async def test_start_stores_llm_client(self):
        mock_llm = MagicMock()
        scheduler = StartupScheduler()
        await scheduler.start(llm_client=mock_llm)
        assert scheduler._llm_client is mock_llm
        await scheduler.stop()


# ===========================================================================
# 10. 全局单例
# ===========================================================================


class TestGlobalSingleton:
    """get_startup_scheduler / reset_startup_scheduler 测试"""

    def test_get_returns_same_instance(self):
        s1 = get_startup_scheduler()
        s2 = get_startup_scheduler()
        assert s1 is s2

    def test_reset_creates_new_instance(self):
        s1 = get_startup_scheduler()
        reset_startup_scheduler()
        s2 = get_startup_scheduler()
        assert s1 is not s2

    def test_reset_clears_registered_configs(self):
        scheduler = get_startup_scheduler()
        scheduler.register(StartupConfig(
            agent_code="agent1",
            trigger=TriggerConfig(kind=TriggerKind.EVENT, event_name="test"),
        ))
        assert len(scheduler.all_configs()) == 1

        reset_startup_scheduler()
        new_scheduler = get_startup_scheduler()
        assert len(new_scheduler.all_configs()) == 0


# ===========================================================================
# 11. Cron 检查触发测试（不等真实时间）
# ===========================================================================


@pytest.mark.asyncio
class TestCronCheckTriggers:
    """_check_cron_triggers 直接调用测试（绕过等待）"""

    async def test_cron_triggers_when_expression_matches(self):
        make_test_agent()
        mock_llm = make_mock_llm()
        scheduler = StartupScheduler()
        scheduler._llm_client = mock_llm

        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.CRON, cron_expr="* * * * *"),  # 任意时间都匹配
        )
        scheduler.register(config)

        await scheduler._check_cron_triggers(datetime.now())
        assert len(scheduler.get_results()) == 1

    async def test_cron_no_trigger_when_expression_not_match(self):
        make_test_agent()
        mock_llm = make_mock_llm()
        scheduler = StartupScheduler()
        scheduler._llm_client = mock_llm

        # 明确不匹配的时间（9:00）但 cron 是 18:00
        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.CRON, cron_expr="0 18 * * *"),
        )
        scheduler.register(config)

        # 使用 09:00 检查，不应该触发
        await scheduler._check_cron_triggers(datetime(2026, 4, 14, 9, 0, 0))
        assert len(scheduler.get_results()) == 0

    async def test_cron_skips_disabled_config(self):
        make_test_agent()
        scheduler = StartupScheduler()

        config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.CRON, cron_expr="* * * * *"),
            enabled=False,
        )
        scheduler.register(config)

        await scheduler._check_cron_triggers(datetime.now())
        assert len(scheduler.get_results()) == 0

    async def test_cron_handles_invalid_expr_gracefully(self):
        """无效 cron 表达式不应让调度循环崩溃"""
        scheduler = StartupScheduler()
        # 直接注入一个手动构造的无效配置（跳过 Pydantic 校验）
        bad_config = StartupConfig(
            agent_code="test_startup_agent",
            trigger=TriggerConfig(kind=TriggerKind.CRON, cron_expr="invalid_expr"),
        )
        scheduler.register(bad_config)

        # 不应抛出异常
        await scheduler._check_cron_triggers(datetime.now())
