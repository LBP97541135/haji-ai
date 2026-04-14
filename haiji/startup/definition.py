"""
startup/definition.py - 触发器引擎数据结构

定义触发器配置、事件、执行结果等核心数据结构。
触发器类型：CRON（定时）/ EVENT（事件）/ WEBHOOK（HTTP 回调）/ CONDITION（条件）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, Any, Callable

from pydantic import BaseModel, Field


def _gen_event_id() -> str:
    return uuid.uuid4().hex


class TriggerKind(str, Enum):
    """触发器类型"""

    CRON = "cron"          # 定时触发（cron 表达式）
    EVENT = "event"        # 事件触发（内部事件总线）
    WEBHOOK = "webhook"    # Webhook 触发（HTTP 请求）
    CONDITION = "condition"  # 条件触发（运行时条件判断）


class TriggerConfig(BaseModel):
    """
    触发器配置。

    根据 kind 不同，需要填写对应字段。

    示例（CRON）::

        TriggerConfig(kind="cron", cron_expr="0 9 * * *")  # 每天 09:00 触发

    示例（EVENT）::

        TriggerConfig(kind="event", event_name="user_registered")

    示例（WEBHOOK）::

        TriggerConfig(kind="webhook", webhook_path="/hooks/my_agent")
    """

    kind: TriggerKind = Field(description="触发器类型")
    cron_expr: Optional[str] = Field(
        default=None,
        description="Cron 表达式（kind=CRON 时必填）。支持 5 字段格式：分 时 日 月 周",
    )
    event_name: Optional[str] = Field(
        default=None,
        description="事件名称（kind=EVENT 时必填）",
    )
    webhook_path: Optional[str] = Field(
        default=None,
        description="Webhook 路径（kind=WEBHOOK 时必填，如 '/hooks/my_agent'）",
    )
    condition_fn: Optional[Callable[[], bool]] = Field(
        default=None,
        description="条件函数（kind=CONDITION 时必填），返回 True 时触发",
    )

    model_config = {"arbitrary_types_allowed": True}


class StartupConfig(BaseModel):
    """
    Startup 完整配置：一个 Agent + 一个触发器 = 一条 Startup 配置。

    示例::

        StartupConfig(
            agent_code="daily_report_agent",
            trigger=TriggerConfig(kind="cron", cron_expr="0 9 * * *"),
            initial_message_template="请生成今日日报，当前时间：{{triggered_at}}",
        )
    """

    startup_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex[:8],
        description="Startup 唯一 ID，自动生成",
    )
    agent_code: str = Field(description="要触发的 Agent code")
    trigger: TriggerConfig = Field(description="触发器配置")
    session_id_factory: str = Field(
        default="default",
        description=(
            "session_id 生成策略：'default' 每次生成唯一 session_id；"
            "'fixed' 使用 agent_code 作为固定 session_id"
        ),
    )
    user_id: Optional[str] = Field(
        default=None,
        description="触发执行时使用的 user_id（可为空）",
    )
    initial_message_template: str = Field(
        default="{{event_data}}",
        description=(
            "初始消息模板，支持 {{event_data}} / {{event_name}} / {{triggered_at}} 占位符"
        ),
    )
    enabled: bool = Field(default=True, description="是否启用此 Startup 配置")

    def make_session_id(self) -> str:
        """生成 session_id"""
        if self.session_id_factory == "fixed":
            return self.agent_code
        return f"{self.agent_code}_{uuid.uuid4().hex[:8]}"

    def render_message(self, event: "TriggerEvent") -> str:
        """
        渲染初始消息。

        将模板中的占位符替换为事件信息。

        Args:
            event: 触发事件

        Returns:
            渲染后的消息字符串
        """
        import json
        event_data_str = json.dumps(event.payload, ensure_ascii=False) if event.payload else ""
        return (
            self.initial_message_template
            .replace("{{event_data}}", event_data_str)
            .replace("{{event_name}}", event.event_name or "")
            .replace("{{triggered_at}}", event.triggered_at.isoformat())
        )


class TriggerEvent(BaseModel):
    """
    触发事件。

    当 Startup 被触发时创建，携带触发类型和附加数据。

    示例::

        event = TriggerEvent(
            trigger_kind=TriggerKind.EVENT,
            event_name="user_registered",
            payload={"user_id": "u_123", "email": "test@example.com"},
        )
    """

    event_id: str = Field(default_factory=_gen_event_id, description="事件唯一 ID")
    trigger_kind: TriggerKind = Field(description="触发类型")
    event_name: Optional[str] = Field(default=None, description="事件名称（EVENT 触发时有值）")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="附加数据（事件数据 / Webhook 请求体等）",
    )
    triggered_at: datetime = Field(
        default_factory=datetime.now,
        description="触发时间",
    )


class StartupResult(BaseModel):
    """
    Startup 执行结果。

    每次触发执行后产生一条记录。

    示例::

        result = StartupResult(
            event_id="abc123",
            agent_code="daily_report_agent",
            session_id="sess_xyz",
            success=True,
            started_at=datetime.now(),
            finished_at=datetime.now(),
        )
    """

    result_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8], description="结果唯一 ID")
    event_id: str = Field(description="对应的事件 ID")
    startup_id: str = Field(description="对应的 Startup 配置 ID")
    agent_code: str = Field(description="执行的 Agent code")
    session_id: str = Field(description="本次执行使用的 session_id")
    success: bool = Field(description="执行是否成功")
    error: Optional[str] = Field(default=None, description="失败时的错误信息")
    started_at: datetime = Field(description="开始执行时间")
    finished_at: Optional[datetime] = Field(default=None, description="执行完成时间")

    @property
    def duration_ms(self) -> Optional[float]:
        """执行耗时（毫秒）"""
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds() * 1000
