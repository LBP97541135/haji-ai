"""
workflow - 工作流引擎

支持通过 Python 构造 WorkflowDefinition，描述多 Agent 协作关系，按顺序或条件执行。

核心概念：
- StepKind：步骤类型（AGENT / CONDITION / PARALLEL）
- WorkflowStep：单个步骤定义（agent_code、message_template、condition_expr 等）
- WorkflowDefinition：完整工作流（steps 列表 + entry_step_id）
- WorkflowResult：执行结果（step_results 字典 + success/error）
- WorkflowEngine：执行引擎，run() 方法驱动整个工作流
- WorkflowRegistry：全局注册表，按 workflow_id 存取
- @workflow：装饰器，自动注册 WorkflowDefinition

示例::

    from haiji.workflow import (
        StepKind, WorkflowStep, WorkflowDefinition,
        WorkflowEngine, get_workflow_registry
    )

    step1 = WorkflowStep(
        step_id="translate",
        kind=StepKind.AGENT,
        agent_code="TranslatorAgent",
        message_template="请将以下文本翻译成英文：{{input}}",
        next_step_id="summarize",
    )
    step2 = WorkflowStep(
        step_id="summarize",
        kind=StepKind.AGENT,
        agent_code="SummaryAgent",
        message_template="请总结：{{step_translate_result}}",
    )

    wf = WorkflowDefinition(
        workflow_id="translate_and_summarize",
        name="翻译+摘要工作流",
        steps=[step1, step2],
        entry_step_id="translate",
    )

    engine = WorkflowEngine()
    result = await engine.run(wf, "你好世界", llm_client=client)
    print(result.step_results)
"""

from haiji.workflow.definition import StepKind, WorkflowDefinition, WorkflowResult, WorkflowStep
from haiji.workflow.base import (
    WorkflowEngine,
    WorkflowRegistry,
    get_workflow_registry,
    reset_workflow_registry,
    workflow,
)

__all__ = [
    # 数据结构
    "StepKind",
    "WorkflowStep",
    "WorkflowDefinition",
    "WorkflowResult",
    # 执行引擎
    "WorkflowEngine",
    # 注册表
    "WorkflowRegistry",
    "get_workflow_registry",
    "reset_workflow_registry",
    # 装饰器
    "workflow",
]
