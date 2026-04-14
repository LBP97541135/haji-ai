"""
startup/base.py - 触发器引擎核心调度器

提供：
- StartupScheduler：核心调度器，支持 CRON / EVENT / WEBHOOK / CONDITION 四种触发方式
- CronRunner：内部 Cron 解析器（纯 asyncio 实现，不依赖第三方库）
- get_startup_scheduler() / reset_startup_scheduler()：全局单例

依赖层：startup → agent（单向，agent 不依赖 startup）
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from haiji.agent.base import BaseAgent
from haiji.agent.registry import get_agent_registry
from haiji.context.definition import ExecutionContext
from haiji.memory.base import SessionMemoryManager
from haiji.sse.base import SseEventEmitter
from haiji.startup.definition import (
    StartupConfig,
    StartupResult,
    TriggerEvent,
    TriggerKind,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CronRunner - 纯 Python Cron 解析与调度
# ---------------------------------------------------------------------------


class _CronField:
    """
    Cron 字段解析器。

    支持：
    - `*`：任意值
    - `5`：固定值
    - `*/5`：步进（每 5 个单位）
    - `1,3,5`：枚举（不在本期实现范围，但预留）

    不支持范围（`1-5`）和 L/W 等特殊字符（超出第一期范围）。
    """

    def __init__(self, expr: str, min_val: int, max_val: int) -> None:
        self._min = min_val
        self._max = max_val
        self._expr = expr.strip()
        self._values: Optional[set[int]] = self._parse()

    def _parse(self) -> Optional[set[int]]:
        """
        解析字段表达式，返回该字段允许的值集合。
        返回 None 表示 `*`（任意值）。
        """
        expr = self._expr

        if expr == "*":
            return None  # 任意值

        if expr.startswith("*/"):
            # 步进：*/n
            try:
                step = int(expr[2:])
                if step <= 0:
                    raise ValueError(f"步进值必须 > 0，got {step!r}")
                return {v for v in range(self._min, self._max + 1) if (v - self._min) % step == 0}
            except ValueError as exc:
                raise ValueError(f"无效的 cron 步进表达式 {expr!r}: {exc}") from exc

        # 枚举：1,3,5
        if "," in expr:
            values = set()
            for part in expr.split(","):
                try:
                    v = int(part.strip())
                    if not (self._min <= v <= self._max):
                        raise ValueError(f"值 {v} 超出范围 [{self._min}, {self._max}]")
                    values.add(v)
                except ValueError as exc:
                    raise ValueError(f"无效的 cron 枚举值 {expr!r}: {exc}") from exc
            return values

        # 单值
        try:
            v = int(expr)
            if not (self._min <= v <= self._max):
                raise ValueError(f"值 {v} 超出范围 [{self._min}, {self._max}]")
            return {v}
        except ValueError as exc:
            raise ValueError(f"无效的 cron 字段值 {expr!r}: {exc}") from exc

    def matches(self, value: int) -> bool:
        """判断给定值是否匹配此字段"""
        if self._values is None:
            return True
        return value in self._values


class CronRunner:
    """
    纯 Python Cron 解析器。

    支持标准 5 字段 Cron 表达式：`分 时 日 月 周`

    示例::

        runner = CronRunner("0 9 * * *")  # 每天 09:00
        runner = CronRunner("*/5 * * * *")  # 每 5 分钟
        runner = CronRunner("0 9 * * 1")  # 每周一 09:00

    字段范围：
        - 分（0-59）
        - 时（0-23）
        - 日（1-31）
        - 月（1-12）
        - 周（0-6，0=周日）
    """

    def __init__(self, cron_expr: str) -> None:
        self._expr = cron_expr
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(
                f"Cron 表达式必须是 5 字段（分 时 日 月 周），got {len(parts)} 字段: {cron_expr!r}"
            )
        self._minute = _CronField(parts[0], 0, 59)
        self._hour = _CronField(parts[1], 0, 23)
        self._day = _CronField(parts[2], 1, 31)
        self._month = _CronField(parts[3], 1, 12)
        self._weekday = _CronField(parts[4], 0, 6)

    def matches(self, dt: datetime) -> bool:
        """
        判断给定时间是否符合 cron 表达式。

        Args:
            dt: 要检查的时间（精确到分钟）

        Returns:
            bool: 是否匹配
        """
        # Python weekday(): 0=周一, 6=周日；Cron 惯例: 0=周日, 6=周六
        cron_weekday = (dt.weekday() + 1) % 7  # Python weekday → Cron weekday
        return (
            self._minute.matches(dt.minute)
            and self._hour.matches(dt.hour)
            and self._day.matches(dt.day)
            and self._month.matches(dt.month)
            and self._weekday.matches(cron_weekday)
        )

    @property
    def expr(self) -> str:
        return self._expr


# ---------------------------------------------------------------------------
# StartupScheduler
# ---------------------------------------------------------------------------


class StartupScheduler:
    """
    触发器引擎核心调度器。

    支持四种触发方式：
    - CRON：定时触发，内置纯 Python Cron 调度循环
    - EVENT：事件触发，调用 fire_event() 手动触发
    - WEBHOOK：HTTP 触发，调用 fire_webhook() 触发
    - CONDITION：条件触发，定期检查条件函数

    示例::

        scheduler = get_startup_scheduler()
        config = StartupConfig(
            agent_code="my_agent",
            trigger=TriggerConfig(kind="cron", cron_expr="0 9 * * *"),
        )
        scheduler.register(config)
        await scheduler.start(llm_client=my_llm_client)
        # ... 等待触发 ...
        await scheduler.stop()
    """

    def __init__(self) -> None:
        self._configs: dict[str, StartupConfig] = {}         # startup_id → config
        self._event_index: dict[str, list[str]] = {}          # event_name → [startup_ids]
        self._webhook_index: dict[str, str] = {}              # webhook_path → startup_id
        self._results: list[StartupResult] = []               # 执行历史（内存）
        self._running: bool = False
        self._cron_task: Optional[asyncio.Task] = None        # type: ignore[type-arg]
        self._llm_client: Any = None                          # 全局 LLM 客户端

    # ------------------------------------------------------------------
    # 注册 / 注销
    # ------------------------------------------------------------------

    def register(self, config: StartupConfig) -> str:
        """
        注册一条 Startup 配置。

        Args:
            config: Startup 配置

        Returns:
            str: startup_id（用于后续 unregister / 查询）
        """
        startup_id = config.startup_id
        self._configs[startup_id] = config

        # 建立事件索引
        if config.trigger.kind == TriggerKind.EVENT and config.trigger.event_name:
            event_name = config.trigger.event_name
            self._event_index.setdefault(event_name, [])
            if startup_id not in self._event_index[event_name]:
                self._event_index[event_name].append(startup_id)

        # 建立 Webhook 索引
        if config.trigger.kind == TriggerKind.WEBHOOK and config.trigger.webhook_path:
            self._webhook_index[config.trigger.webhook_path] = startup_id

        logger.info(
            "[Startup] 注册 startup_id=%s agent=%s trigger=%s",
            startup_id,
            config.agent_code,
            config.trigger.kind.value,
        )
        return startup_id

    def unregister(self, startup_id: str) -> bool:
        """
        注销一条 Startup 配置。

        Args:
            startup_id: 要注销的 startup_id

        Returns:
            bool: 是否成功注销（配置不存在时返回 False）
        """
        config = self._configs.pop(startup_id, None)
        if config is None:
            logger.warning("[Startup] 注销失败，startup_id=%s 不存在", startup_id)
            return False

        # 清理事件索引
        if config.trigger.kind == TriggerKind.EVENT and config.trigger.event_name:
            ids = self._event_index.get(config.trigger.event_name, [])
            if startup_id in ids:
                ids.remove(startup_id)
            if not ids:
                self._event_index.pop(config.trigger.event_name, None)

        # 清理 Webhook 索引
        if config.trigger.kind == TriggerKind.WEBHOOK and config.trigger.webhook_path:
            self._webhook_index.pop(config.trigger.webhook_path, None)

        logger.info("[Startup] 注销 startup_id=%s", startup_id)
        return True

    def all_configs(self) -> list[StartupConfig]:
        """返回所有已注册的 Startup 配置（按注册顺序）"""
        return list(self._configs.values())

    # ------------------------------------------------------------------
    # 触发接口
    # ------------------------------------------------------------------

    async def fire_event(
        self,
        event_name: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> list[StartupResult]:
        """
        手动触发指定事件名的所有 Startup 配置（并发执行）。

        Args:
            event_name: 事件名称
            payload:    附加数据

        Returns:
            list[StartupResult]: 所有执行结果
        """
        startup_ids = self._event_index.get(event_name, [])
        if not startup_ids:
            logger.debug("[Startup] 事件 '%s' 没有匹配的 Startup 配置", event_name)
            return []

        event = TriggerEvent(
            trigger_kind=TriggerKind.EVENT,
            event_name=event_name,
            payload=payload or {},
        )

        # 并发执行所有匹配的配置
        enabled_ids = [sid for sid in startup_ids if self._configs.get(sid, StartupConfig(
            agent_code="", trigger={"kind": "event"}, enabled=False  # type: ignore
        )).enabled]
        enabled_configs = [self._configs[sid] for sid in enabled_ids if sid in self._configs]

        tasks = [self._execute(config, event) for config in enabled_configs]
        results: list[StartupResult] = await asyncio.gather(*tasks, return_exceptions=True)  # type: ignore

        # 过滤异常（转为失败 result）
        final_results: list[StartupResult] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error("[Startup] fire_event=%s 执行异常: %s", event_name, r)
                # 构造失败 result
                config = enabled_configs[i]
                final_results.append(StartupResult(
                    event_id=event.event_id,
                    startup_id=config.startup_id,
                    agent_code=config.agent_code,
                    session_id=config.make_session_id(),
                    success=False,
                    error=str(r),
                    started_at=event.triggered_at,
                    finished_at=datetime.now(),
                ))
            else:
                final_results.append(r)

        return final_results

    async def fire_webhook(
        self,
        webhook_path: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> Optional[StartupResult]:
        """
        触发指定 Webhook 路径对应的 Startup 配置。

        Args:
            webhook_path: Webhook 路径（如 '/hooks/my_agent'）
            payload:      HTTP 请求体数据

        Returns:
            StartupResult | None: 执行结果，未匹配则返回 None
        """
        startup_id = self._webhook_index.get(webhook_path)
        if startup_id is None:
            logger.debug("[Startup] Webhook 路径 '%s' 没有匹配的 Startup 配置", webhook_path)
            return None

        config = self._configs.get(startup_id)
        if config is None or not config.enabled:
            return None

        event = TriggerEvent(
            trigger_kind=TriggerKind.WEBHOOK,
            event_name=webhook_path,
            payload=payload or {},
        )
        return await self._execute(config, event)

    # ------------------------------------------------------------------
    # 启动 / 停止（Cron 调度循环）
    # ------------------------------------------------------------------

    async def start(self, llm_client: Any = None) -> None:
        """
        启动调度器（开启 Cron 调度循环）。

        Args:
            llm_client: 全局 LLM 客户端，Agent 执行时使用
        """
        if self._running:
            logger.warning("[Startup] 调度器已在运行中，忽略重复 start()")
            return
        self._running = True
        self._llm_client = llm_client
        self._cron_task = asyncio.create_task(self._cron_loop())
        logger.info("[Startup] 调度器已启动")

    async def stop(self) -> None:
        """停止调度器，取消 Cron 调度循环"""
        self._running = False
        if self._cron_task is not None:
            self._cron_task.cancel()
            try:
                await self._cron_task
            except asyncio.CancelledError:
                pass
            self._cron_task = None
        logger.info("[Startup] 调度器已停止")

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # 执行历史
    # ------------------------------------------------------------------

    def get_results(self, agent_code: Optional[str] = None) -> list[StartupResult]:
        """
        获取执行历史。

        Args:
            agent_code: 若指定，只返回该 Agent 的结果；否则返回全部

        Returns:
            list[StartupResult]: 按时间倒序排列
        """
        results = self._results if agent_code is None else [
            r for r in self._results if r.agent_code == agent_code
        ]
        return sorted(results, key=lambda r: r.started_at, reverse=True)

    def clear_results(self) -> None:
        """清空执行历史（主要用于测试）"""
        self._results.clear()

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    async def _cron_loop(self) -> None:
        """
        Cron 调度循环：每分钟检查一次是否有 CRON 触发器需要触发。

        为了对齐到分钟，先等待到当前分钟结束再开始循环。
        """
        logger.debug("[Startup] Cron 循环启动")

        # 对齐到下一分钟（减少首次延迟）
        now = datetime.now()
        seconds_to_next_minute = 60 - now.second
        try:
            await asyncio.sleep(seconds_to_next_minute)
        except asyncio.CancelledError:
            return

        while self._running:
            now = datetime.now()
            await self._check_cron_triggers(now)

            # 等待到下一分钟（精确对齐）
            elapsed = datetime.now().second
            sleep_secs = max(0.1, 60 - elapsed)
            try:
                await asyncio.sleep(sleep_secs)
            except asyncio.CancelledError:
                break

        logger.debug("[Startup] Cron 循环退出")

    async def _check_cron_triggers(self, now: datetime) -> None:
        """检查所有 CRON 触发器，触发匹配的配置"""
        cron_configs = [
            c for c in self._configs.values()
            if c.enabled and c.trigger.kind == TriggerKind.CRON and c.trigger.cron_expr
        ]

        if not cron_configs:
            return

        tasks = []
        for config in cron_configs:
            try:
                runner = CronRunner(config.trigger.cron_expr)  # type: ignore[arg-type]
            except ValueError as exc:
                logger.error(
                    "[Startup] Cron 表达式解析失败，startup_id=%s expr=%r: %s",
                    config.startup_id,
                    config.trigger.cron_expr,
                    exc,
                )
                continue

            if runner.matches(now):
                event = TriggerEvent(
                    trigger_kind=TriggerKind.CRON,
                    event_name=config.trigger.cron_expr,
                    payload={"triggered_at": now.isoformat()},
                    triggered_at=now,
                )
                logger.info(
                    "[Startup] Cron 触发：startup_id=%s agent=%s expr=%r",
                    config.startup_id,
                    config.agent_code,
                    config.trigger.cron_expr,
                )
                tasks.append(self._execute(config, event))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.error("[Startup] Cron 执行异常: %s", r)

    async def _check_condition_triggers(self) -> None:
        """检查所有 CONDITION 触发器（可在外部定期调用）"""
        condition_configs = [
            c for c in self._configs.values()
            if c.enabled and c.trigger.kind == TriggerKind.CONDITION and c.trigger.condition_fn
        ]
        for config in condition_configs:
            try:
                should_trigger = config.trigger.condition_fn()  # type: ignore[misc]
            except Exception as exc:
                logger.error(
                    "[Startup] CONDITION 检查异常，startup_id=%s: %s",
                    config.startup_id,
                    exc,
                )
                continue

            if should_trigger:
                event = TriggerEvent(
                    trigger_kind=TriggerKind.CONDITION,
                    payload={"condition_met": True},
                )
                logger.info(
                    "[Startup] CONDITION 触发：startup_id=%s agent=%s",
                    config.startup_id,
                    config.agent_code,
                )
                await self._execute(config, event)

    async def _execute(self, config: StartupConfig, event: TriggerEvent) -> StartupResult:
        """
        执行一次 Startup：创建 ExecutionContext + Memory + Emitter，调用 Agent.stream_chat。

        Args:
            config: Startup 配置
            event:  触发事件

        Returns:
            StartupResult: 执行结果
        """
        started_at = datetime.now()
        session_id = config.make_session_id()
        agent_code = config.agent_code

        # 渲染初始消息
        user_message = config.render_message(event)

        # 查找 Agent 类
        agent_registry = get_agent_registry()
        agent_cls = agent_registry.get(agent_code)
        if agent_cls is None:
            error = f"Agent '{agent_code}' 未注册"
            logger.error("[Startup] %s", error)
            result = StartupResult(
                event_id=event.event_id,
                startup_id=config.startup_id,
                agent_code=agent_code,
                session_id=session_id,
                success=False,
                error=error,
                started_at=started_at,
                finished_at=datetime.now(),
            )
            self._results.append(result)
            return result

        # 创建执行组件
        ctx = ExecutionContext.create(
            session_id=session_id,
            agent_code=agent_code,
            user_id=config.user_id,
        )
        memory = SessionMemoryManager()
        emitter = SseEventEmitter()

        logger.info(
            "[Startup] 开始执行：startup_id=%s agent=%s session=%s",
            config.startup_id,
            agent_code,
            session_id,
        )

        success = True
        error_msg: Optional[str] = None

        try:
            agent_instance: BaseAgent = agent_cls()

            # 消费 emitter 事件（防止 Queue 阻塞）
            async def _drain_emitter() -> None:
                async for _ in emitter.events():
                    pass  # 仅消费，不处理（Startup 执行不需要实时流式输出）

            drain_task = asyncio.create_task(_drain_emitter())
            await agent_instance.stream_chat(
                user_message=user_message,
                ctx=ctx,
                emitter=emitter,
                memory=memory,
                llm_client=self._llm_client,
            )
            await drain_task

        except Exception as exc:
            success = False
            error_msg = str(exc)
            logger.error(
                "[Startup] 执行失败：startup_id=%s agent=%s error=%s",
                config.startup_id,
                agent_code,
                exc,
                exc_info=True,
            )

        finished_at = datetime.now()
        result = StartupResult(
            event_id=event.event_id,
            startup_id=config.startup_id,
            agent_code=agent_code,
            session_id=session_id,
            success=success,
            error=error_msg,
            started_at=started_at,
            finished_at=finished_at,
        )
        self._results.append(result)
        logger.info(
            "[Startup] 执行完成：startup_id=%s success=%s duration=%.1fms",
            config.startup_id,
            success,
            result.duration_ms or 0,
        )
        return result


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_scheduler_instance: Optional[StartupScheduler] = None


def get_startup_scheduler() -> StartupScheduler:
    """
    获取全局 StartupScheduler 单例。

    Returns:
        StartupScheduler: 全局调度器实例
    """
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = StartupScheduler()
    return _scheduler_instance


def reset_startup_scheduler() -> None:
    """
    重置全局 StartupScheduler 单例（用于测试）。

    注意：若调度器正在运行，需先调用 stop() 再 reset。
    """
    global _scheduler_instance
    _scheduler_instance = None
