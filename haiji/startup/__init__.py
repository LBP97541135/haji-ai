"""
haiji.startup - 触发器引擎模块

让 Agent 可以被定时任务、外部事件、Webhook 或条件自动触发，无需人工发消息。

支持四种触发方式：
- CRON：定时触发（cron 表达式，纯 asyncio 实现）
- EVENT：事件触发（内部事件总线，fire_event()）
- WEBHOOK：HTTP 触发（fire_webhook()）
- CONDITION：条件触发（自定义函数返回 True 时触发）

快速上手::

    from haiji.startup import (
        StartupScheduler, StartupConfig, TriggerConfig, TriggerKind,
        get_startup_scheduler, reset_startup_scheduler,
    )

    scheduler = get_startup_scheduler()

    # 注册 CRON 触发器（每天 09:00）
    config = StartupConfig(
        agent_code="daily_report_agent",
        trigger=TriggerConfig(kind=TriggerKind.CRON, cron_expr="0 9 * * *"),
        initial_message_template="请生成今日日报，触发时间：{{triggered_at}}",
    )
    scheduler.register(config)

    # 启动调度器
    await scheduler.start(llm_client=my_llm_client)

    # 手动触发事件
    results = await scheduler.fire_event("user_registered", {"user_id": "u_123"})

    # 停止调度器
    await scheduler.stop()
"""

from haiji.startup.definition import (
    TriggerKind,
    TriggerConfig,
    StartupConfig,
    TriggerEvent,
    StartupResult,
)
from haiji.startup.base import (
    CronRunner,
    StartupScheduler,
    get_startup_scheduler,
    reset_startup_scheduler,
)

__all__ = [
    # 数据结构
    "TriggerKind",
    "TriggerConfig",
    "StartupConfig",
    "TriggerEvent",
    "StartupResult",
    # 核心类
    "CronRunner",
    "StartupScheduler",
    # 单例访问
    "get_startup_scheduler",
    "reset_startup_scheduler",
]
