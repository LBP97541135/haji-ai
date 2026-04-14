"""
workflow/base.py - 工作流引擎 + 注册表 + @workflow 装饰器

提供：
- WorkflowEngine：工作流执行引擎（支持 AGENT / CONDITION / PARALLEL 步骤）
- WorkflowRegistry：全局工作流注册表
- get_workflow_registry()：全局单例工厂
- @workflow：装饰器，自动注册 WorkflowDefinition
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Optional

from haiji.workflow.definition import (
    StepKind,
    WorkflowDefinition,
    WorkflowResult,
    WorkflowStep,
)

logger = logging.getLogger(__name__)

# 条件表达式中允许引用的变量名格式（step_xxx_result）
_SAFE_VAR_PATTERN = re.compile(r"^step_[a-zA-Z0-9_]+_result$")
# 危险字符串黑名单（防注入）
_FORBIDDEN_EXPR_TOKENS = ("import", "__", "exec", "eval", "open", "os", "sys", "subprocess")


class WorkflowError(Exception):
    """工作流执行错误基类。"""


class WorkflowStepNotFoundError(WorkflowError):
    """步骤不存在。"""


class WorkflowMaxStepsError(WorkflowError):
    """超过最大执行步骤数。"""


class WorkflowConditionError(WorkflowError):
    """条件表达式执行错误。"""


class WorkflowEngine:
    """
    工作流执行引擎。

    支持三种步骤类型：
    - AGENT：调用指定 Agent，将结果作为步骤输出
    - CONDITION：eval 布尔表达式，根据结果跳转
    - PARALLEL：asyncio.gather 并发执行子步骤

    示例::

        engine = WorkflowEngine()
        result = await engine.run(definition, "开始任务", llm_client)
        if result.success:
            print(result.step_results)
    """

    async def run(
        self,
        definition: WorkflowDefinition,
        initial_message: str,
        llm_client: Any = None,
        session_id: Optional[str] = None,
    ) -> WorkflowResult:
        """
        运行工作流。

        Args:
            definition:      工作流定义
            initial_message: 初始消息（传给入口步骤的 Agent）
            llm_client:      LLM 客户端（传递给 Agent 执行）
            session_id:      会话 ID，不传则自动生成

        Returns:
            WorkflowResult：工作流执行结果
        """
        import uuid

        session_id = session_id or f"wf_sess_{uuid.uuid4().hex[:8]}"
        started_at = datetime.utcnow()
        step_results: dict[str, str] = {}
        step_count = 0

        logger.info(
            "[WorkflowEngine] 开始执行工作流 '%s'（session_id=%s）",
            definition.workflow_id,
            session_id,
        )

        current_step_id: Optional[str] = definition.entry_step_id

        try:
            while current_step_id is not None:
                # 防死循环
                step_count += 1
                if step_count > definition.max_total_steps:
                    raise WorkflowMaxStepsError(
                        f"工作流 '{definition.workflow_id}' 执行步骤数超过上限 {definition.max_total_steps}"
                    )

                step = definition.get_step(current_step_id)
                if step is None:
                    raise WorkflowStepNotFoundError(
                        f"步骤 '{current_step_id}' 在工作流定义中不存在"
                    )

                logger.info(
                    "[WorkflowEngine] 执行步骤 %s（kind=%s，共 %d 步）",
                    step.step_id,
                    step.kind,
                    step_count,
                )

                # 渲染消息模板（将 {{step_xxx_result}} 替换为实际值）
                message = self._render_message(
                    step.message_template or initial_message,
                    step_results,
                    initial_message,
                )

                if step.kind == StepKind.AGENT:
                    result_text = await self._run_agent_step(step, message, llm_client, session_id)
                    step_results[f"step_{step.step_id}_result"] = result_text
                    current_step_id = step.next_step_id

                elif step.kind == StepKind.CONDITION:
                    condition_met = self._eval_condition(step, step_results)
                    # CONDITION 步骤本身不产生输出，只做路由
                    if condition_met:
                        current_step_id = step.next_step_id
                    else:
                        current_step_id = step.else_step_id

                elif step.kind == StepKind.PARALLEL:
                    parallel_results = await self._run_parallel_step(
                        step, message, llm_client, session_id
                    )
                    step_results.update(parallel_results)
                    current_step_id = step.next_step_id

                else:
                    raise WorkflowError(f"未知步骤类型：{step.kind}")

        except (WorkflowMaxStepsError, WorkflowStepNotFoundError, WorkflowConditionError) as exc:
            logger.error("[WorkflowEngine] 工作流执行失败：%s", exc)
            return WorkflowResult(
                workflow_id=definition.workflow_id,
                session_id=session_id,
                success=False,
                step_results=step_results,
                error=str(exc),
                started_at=started_at,
                finished_at=datetime.utcnow(),
            )
        except Exception as exc:
            logger.error("[WorkflowEngine] 工作流意外错误：%s", exc, exc_info=True)
            return WorkflowResult(
                workflow_id=definition.workflow_id,
                session_id=session_id,
                success=False,
                step_results=step_results,
                error=f"工作流执行意外失败：{exc}",
                started_at=started_at,
                finished_at=datetime.utcnow(),
            )

        logger.info(
            "[WorkflowEngine] 工作流 '%s' 执行完成，共 %d 步",
            definition.workflow_id,
            step_count,
        )
        return WorkflowResult(
            workflow_id=definition.workflow_id,
            session_id=session_id,
            success=True,
            step_results=step_results,
            started_at=started_at,
            finished_at=datetime.utcnow(),
        )

    # ------------------------------------------------------------------
    # 步骤执行方法
    # ------------------------------------------------------------------

    async def _run_agent_step(
        self,
        step: WorkflowStep,
        message: str,
        llm_client: Any,
        session_id: str,
    ) -> str:
        """
        执行 AGENT 步骤：调用 Agent，收集流式输出，返回完整文本。
        """
        from haiji.agent.base import BaseAgent
        from haiji.agent.registry import get_agent_registry
        from haiji.context.definition import ExecutionContext
        from haiji.memory.base import SessionMemoryManager
        from haiji.sse.base import SseEvent, SseEventEmitter, SseEventType

        if not step.agent_code:
            raise WorkflowError(f"步骤 '{step.step_id}' 是 AGENT 类型但缺少 agent_code")

        agent_registry = get_agent_registry()
        agent_cls = agent_registry.get(step.agent_code)
        if agent_cls is None:
            raise WorkflowError(f"Agent '{step.agent_code}' 未注册")

        agent_instance: BaseAgent = agent_cls()
        ctx = ExecutionContext.create(
            session_id=f"{session_id}_{step.step_id}",
            agent_code=step.agent_code,
        )
        memory = SessionMemoryManager()
        emitter = SseEventEmitter()

        # 并发：Agent 运行 + 收集输出
        tokens: list[str] = []

        async def collect_output() -> None:
            async for event in emitter.events():
                if event.type == SseEventType.TOKEN:
                    tokens.append(event.message or "")

        agent_task = asyncio.create_task(
            agent_instance.stream_chat(message, ctx, emitter, memory, llm_client)
        )
        collect_task = asyncio.create_task(collect_output())

        await asyncio.gather(agent_task, collect_task)

        result_text = "".join(tokens)
        logger.debug(
            "[WorkflowEngine] 步骤 %s Agent '%s' 输出：%s",
            step.step_id,
            step.agent_code,
            result_text[:200],
        )
        return result_text

    async def _run_parallel_step(
        self,
        step: WorkflowStep,
        message: str,
        llm_client: Any,
        session_id: str,
    ) -> dict[str, str]:
        """
        执行 PARALLEL 步骤：asyncio.gather 并发执行子步骤，返回所有子步骤结果。
        """
        if not step.parallel_steps:
            logger.warning("[WorkflowEngine] PARALLEL 步骤 '%s' 没有子步骤，跳过", step.step_id)
            return {}

        async def run_sub_step(sub_step: WorkflowStep) -> tuple[str, str]:
            """运行单个子步骤，返回 (result_key, result_text)。"""
            if sub_step.kind != StepKind.AGENT:
                raise WorkflowError(
                    f"PARALLEL 子步骤 '{sub_step.step_id}' 目前只支持 AGENT 类型"
                )
            sub_message = sub_step.message_template or message
            result = await self._run_agent_step(sub_step, sub_message, llm_client, session_id)
            return f"step_{sub_step.step_id}_result", result

        tasks = [run_sub_step(sub) for sub in step.parallel_steps]
        results_list = await asyncio.gather(*tasks)
        return dict(results_list)

    def _eval_condition(
        self,
        step: WorkflowStep,
        step_results: dict[str, str],
    ) -> bool:
        """
        安全 eval 条件表达式。

        安全约束：
        - 只允许引用 step_xxx_result 变量
        - 禁止 import / __ / exec / eval / open 等危险关键字
        - 使用受限的 locals/globals 沙箱

        Args:
            step:         CONDITION 步骤定义
            step_results: 当前已有的步骤结果字典

        Returns:
            bool：条件是否成立
        """
        expr = step.condition_expr
        if not expr:
            raise WorkflowConditionError(f"步骤 '{step.step_id}' 缺少 condition_expr")

        # 安全检查：黑名单关键字
        expr_lower = expr.lower()
        for forbidden in _FORBIDDEN_EXPR_TOKENS:
            if forbidden in expr_lower:
                raise WorkflowConditionError(
                    f"条件表达式包含禁止关键字 '{forbidden}'：{expr}"
                )

        # 构建安全的本地变量环境（只暴露 step_results 字典内的变量）
        safe_locals: dict[str, Any] = dict(step_results)

        try:
            result = eval(expr, {"__builtins__": {}}, safe_locals)  # noqa: S307
            return bool(result)
        except Exception as exc:
            raise WorkflowConditionError(
                f"步骤 '{step.step_id}' 条件表达式执行失败：{exc}（expr={expr!r}）"
            ) from exc

    @staticmethod
    def _render_message(
        template: str,
        step_results: dict[str, str],
        initial_message: str,
    ) -> str:
        """
        渲染消息模板。

        将 {{step_xxx_result}} 替换为 step_results 中对应的值。
        若未找到对应变量，保留原始占位符不变（不抛异常）。

        Args:
            template:        消息模板字符串
            step_results:    已有步骤结果（step_xxx_result 格式的键值对）
            initial_message: 如果模板为空，使用初始消息

        Returns:
            渲染后的消息字符串
        """
        if not template:
            return initial_message

        def replace_var(match: re.Match) -> str:
            var_name = match.group(1)
            return step_results.get(var_name, match.group(0))

        # 匹配 {{step_xxx_result}} 形式的占位符
        rendered = re.sub(r"\{\{(step_[a-zA-Z0-9_]+_result)\}\}", replace_var, template)
        return rendered


# ------------------------------------------------------------------
# 全局注册表
# ------------------------------------------------------------------


class WorkflowRegistry:
    """
    全局工作流注册表。

    按 workflow_id 注册和查找 WorkflowDefinition。

    示例::

        registry = get_workflow_registry()
        registry.register(my_workflow_def)
        wf = registry.get("my_workflow")
    """

    def __init__(self) -> None:
        self._definitions: dict[str, WorkflowDefinition] = {}

    def register(self, definition: WorkflowDefinition) -> None:
        """
        注册工作流定义。

        Args:
            definition: 要注册的工作流定义，workflow_id 必须唯一
        """
        if definition.workflow_id in self._definitions:
            logger.warning(
                "[WorkflowRegistry] workflow_id '%s' 已存在，覆盖注册",
                definition.workflow_id,
            )
        self._definitions[definition.workflow_id] = definition
        logger.debug("[WorkflowRegistry] 注册工作流 '%s'", definition.workflow_id)

    def get(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """
        按 workflow_id 查找工作流定义。

        Args:
            workflow_id: 工作流唯一 ID

        Returns:
            WorkflowDefinition 或 None（未找到时）
        """
        return self._definitions.get(workflow_id)

    def all_workflow_ids(self) -> list[str]:
        """返回所有已注册的 workflow_id 列表。"""
        return list(self._definitions.keys())

    def clear(self) -> None:
        """清空注册表（主要用于测试）。"""
        self._definitions.clear()

    def __len__(self) -> int:
        """返回已注册的工作流数量。"""
        return len(self._definitions)


# 全局单例
_workflow_registry: Optional[WorkflowRegistry] = None


def get_workflow_registry() -> WorkflowRegistry:
    """
    获取全局 WorkflowRegistry 单例。

    Returns:
        WorkflowRegistry 实例
    """
    global _workflow_registry
    if _workflow_registry is None:
        _workflow_registry = WorkflowRegistry()
    return _workflow_registry


def reset_workflow_registry() -> None:
    """重置全局单例（主要用于测试隔离）。"""
    global _workflow_registry
    _workflow_registry = None


# ------------------------------------------------------------------
# @workflow 装饰器
# ------------------------------------------------------------------


def workflow(definition: WorkflowDefinition) -> WorkflowDefinition:
    """
    @workflow 装饰器：自动将 WorkflowDefinition 注册到全局 WorkflowRegistry。

    可以装饰函数（返回 WorkflowDefinition）或直接传入 WorkflowDefinition 实例。

    示例（装饰实例）::

        @workflow
        wf = WorkflowDefinition(
            workflow_id="my_wf",
            ...
        )

    示例（装饰函数）::

        @workflow
        def build_my_workflow() -> WorkflowDefinition:
            return WorkflowDefinition(...)

        # 之后通过 get_workflow_registry().get("my_wf") 访问

    Args:
        definition: WorkflowDefinition 实例，或返回 WorkflowDefinition 的无参函数

    Returns:
        原始 WorkflowDefinition 实例（或执行函数后的实例）
    """
    import inspect

    if inspect.isfunction(definition) or inspect.ismethod(definition):
        # 装饰函数
        result = definition()
        if not isinstance(result, WorkflowDefinition):
            raise TypeError(
                f"@workflow 装饰的函数必须返回 WorkflowDefinition，实际返回 {type(result)}"
            )
        get_workflow_registry().register(result)
        return result
    elif isinstance(definition, WorkflowDefinition):
        get_workflow_registry().register(definition)
        return definition
    else:
        raise TypeError(
            f"@workflow 只接受 WorkflowDefinition 实例或返回它的函数，实际传入 {type(definition)}"
        )
