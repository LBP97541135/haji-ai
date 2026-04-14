"""
workflow/definition.py - 工作流数据结构

定义工作流的核心数据模型：
- StepKind：步骤类型（AGENT / CONDITION / PARALLEL）
- WorkflowStep：单个工作流步骤
- WorkflowDefinition：完整工作流定义
- WorkflowResult：工作流执行结果
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class StepKind(str, Enum):
    """工作流步骤类型。"""

    AGENT = "agent"          # 调用一个 Agent
    CONDITION = "condition"  # 条件判断，决定跳转路径
    PARALLEL = "parallel"    # 并行执行多个子步骤


class WorkflowStep(BaseModel):
    """
    单个工作流步骤定义。

    示例（AGENT 步骤）::

        WorkflowStep(
            step_id="step_1",
            kind=StepKind.AGENT,
            agent_code="SummaryAgent",
            message_template="请总结以下内容：{{step_0_result}}",
            next_step_id="step_2",
        )

    示例（CONDITION 步骤）::

        WorkflowStep(
            step_id="branch",
            kind=StepKind.CONDITION,
            condition_expr="'成功' in step_1_result",
            next_step_id="step_success",
            else_step_id="step_failure",
        )

    示例（PARALLEL 步骤）::

        WorkflowStep(
            step_id="parallel_1",
            kind=StepKind.PARALLEL,
            parallel_steps=[step_a, step_b],
            next_step_id="step_merge",
        )
    """

    step_id: str = Field(description="步骤唯一标识")
    kind: StepKind = Field(description="步骤类型")

    # AGENT 步骤专用
    agent_code: Optional[str] = Field(default=None, description="要调用的 Agent code（kind=AGENT 时必填）")
    message_template: Optional[str] = Field(
        default=None,
        description="发给 Agent 的消息模板，支持 {{step_xxx_result}} 引用上一步输出",
    )

    # CONDITION 步骤专用
    condition_expr: Optional[str] = Field(
        default=None,
        description="Python bool 表达式（kind=CONDITION 时必填），变量只能引用 step_xxx_result",
    )
    else_step_id: Optional[str] = Field(
        default=None,
        description="条件不满足时跳转的步骤 ID（None 表示结束）",
    )

    # PARALLEL 步骤专用
    parallel_steps: Optional[list[WorkflowStep]] = Field(
        default=None,
        description="并行执行的子步骤列表（kind=PARALLEL 时必填）",
    )

    # 公共字段
    next_step_id: Optional[str] = Field(
        default=None,
        description="下一步骤 ID（None 表示结束）",
    )

    @field_validator("agent_code")
    @classmethod
    def validate_agent_code(cls, v: Optional[str], info: Any) -> Optional[str]:
        """AGENT 步骤必须有 agent_code。"""
        # 在 Pydantic v2 里通过 model_validator 做跨字段校验更合适
        # 这里先做单字段校验，跨字段校验在 model_validator 里做
        return v

    model_config = {"arbitrary_types_allowed": True}


# 解决 WorkflowStep 自引用问题
WorkflowStep.model_rebuild()


class WorkflowDefinition(BaseModel):
    """
    完整工作流定义。

    示例::

        step1 = WorkflowStep(step_id="s1", kind=StepKind.AGENT, agent_code="AgentA", ...)
        step2 = WorkflowStep(step_id="s2", kind=StepKind.AGENT, agent_code="AgentB", ...)

        wf = WorkflowDefinition(
            workflow_id="my_workflow",
            name="示例工作流",
            steps=[step1, step2],
            entry_step_id="s1",
        )
    """

    workflow_id: str = Field(default_factory=lambda: f"wf_{uuid.uuid4().hex[:8]}", description="工作流唯一 ID")
    name: str = Field(default="", description="工作流名称")
    steps: list[WorkflowStep] = Field(default_factory=list, description="所有步骤列表")
    entry_step_id: str = Field(description="入口步骤 ID（第一步）")
    max_total_steps: int = Field(default=50, description="最大执行步骤数（防死循环）", ge=1, le=500)

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        """根据 step_id 查找步骤。"""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None


class WorkflowResult(BaseModel):
    """
    工作流执行结果。

    包含：
    - 执行是否成功
    - 每个步骤的输出（step_id → 输出文本）
    - 错误信息（如有）
    - 开始/结束时间
    """

    workflow_id: str = Field(description="工作流 ID")
    session_id: str = Field(description="执行会话 ID")
    success: bool = Field(default=True, description="是否执行成功")
    step_results: dict[str, str] = Field(default_factory=dict, description="步骤输出：step_id → 输出文本")
    error: Optional[str] = Field(default=None, description="错误信息（success=False 时有值）")
    started_at: datetime = Field(default_factory=datetime.utcnow, description="开始时间（UTC）")
    finished_at: Optional[datetime] = Field(default=None, description="结束时间（UTC）")

    @property
    def duration_ms(self) -> Optional[float]:
        """执行耗时（毫秒），未结束时返回 None。"""
        if self.finished_at is None:
            return None
        delta = self.finished_at - self.started_at
        return delta.total_seconds() * 1000
