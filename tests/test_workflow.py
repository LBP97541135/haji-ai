"""
tests/test_workflow.py - 工作流模块单元测试

覆盖：
- WorkflowStep / WorkflowDefinition / WorkflowResult 数据结构
- WorkflowResult.duration_ms 计算属性
- WorkflowDefinition.get_step()
- WorkflowEngine._render_message() 模板渲染
- WorkflowEngine._eval_condition() 条件表达式（正常 + 异常 + 安全检查）
- WorkflowEngine 线性 AGENT 步骤执行（正常流程）
- WorkflowEngine CONDITION 步骤（条件满足 / 不满足分支）
- WorkflowEngine PARALLEL 步骤（并发执行）
- WorkflowEngine 防死循环（超过 max_total_steps）
- WorkflowEngine 步骤不存在
- WorkflowEngine Agent 未注册
- WorkflowRegistry 注册、查找、clear、len
- @workflow 装饰器（装饰实例 + 装饰函数）
- get_workflow_registry 单例 + reset_workflow_registry
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from haiji.workflow.definition import (
    StepKind,
    WorkflowDefinition,
    WorkflowResult,
    WorkflowStep,
)
from haiji.workflow.base import (
    WorkflowEngine,
    WorkflowRegistry,
    WorkflowError,
    WorkflowStepNotFoundError,
    WorkflowMaxStepsError,
    WorkflowConditionError,
    get_workflow_registry,
    reset_workflow_registry,
    workflow,
)


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


def make_agent_step(
    step_id: str,
    agent_code: str = "TestAgent",
    message_template: Optional[str] = None,
    next_step_id: Optional[str] = None,
) -> WorkflowStep:
    """构造 AGENT 步骤。"""
    return WorkflowStep(
        step_id=step_id,
        kind=StepKind.AGENT,
        agent_code=agent_code,
        message_template=message_template,
        next_step_id=next_step_id,
    )


def make_condition_step(
    step_id: str,
    condition_expr: str,
    next_step_id: Optional[str] = None,
    else_step_id: Optional[str] = None,
) -> WorkflowStep:
    """构造 CONDITION 步骤。"""
    return WorkflowStep(
        step_id=step_id,
        kind=StepKind.CONDITION,
        condition_expr=condition_expr,
        next_step_id=next_step_id,
        else_step_id=else_step_id,
    )


def make_mock_llm() -> MagicMock:
    """创建 Mock LLM 客户端。"""
    from haiji.llm.definition import LlmResponse

    mock_llm = MagicMock()
    mock_llm.chat_with_tools = AsyncMock(return_value=LlmResponse(content="Mock 回答"))
    mock_llm.chat = AsyncMock(return_value=LlmResponse(content="Mock 回答"))

    async def _stream(*args, **kwargs) -> AsyncGenerator[str, None]:
        yield "Mock"
        yield " 回答"

    mock_llm.stream_chat = _stream
    return mock_llm


def register_mock_agent(agent_code: str = "TestAgent", response_text: str = "Agent 输出") -> type:
    """
    注册一个 Mock Agent（直接发 token 然后 done），返回 agent 类。
    用于测试 WorkflowEngine 的 AGENT 步骤执行。
    """
    from haiji.agent.base import BaseAgent
    from haiji.agent.registry import get_agent_registry
    from haiji.context.definition import ExecutionContext
    from haiji.memory.base import SessionMemoryManager
    from haiji.sse.base import SseEventEmitter
    from haiji.agent.definition import AgentDefinition, AgentMode

    class _MockAgent(BaseAgent):
        system_prompt = "Mock Agent"

        async def stream_chat(  # type: ignore[override]
            self,
            user_message: str,
            ctx: ExecutionContext,
            emitter: SseEventEmitter,
            memory: SessionMemoryManager,
            llm_client=None,
            call_stack=None,
        ) -> None:
            await emitter.emit_token(response_text)
            await emitter.emit_done()

    # 手动注册（绕开 @agent 装饰器，避免 AgentDefinition 校验）
    definition = AgentDefinition(
        code=agent_code,
        name=agent_code,
        mode=AgentMode.DIRECT,
        system_prompt="Mock Agent",
    )
    _MockAgent._agent_definition = definition  # type: ignore[attr-defined]
    # register_class 只接受 cls 参数（已有 _agent_definition）
    get_agent_registry().register_class(_MockAgent)
    return _MockAgent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_registries():
    """每个测试前后重置全局注册表。"""
    import haiji.agent.registry as _agent_reg_mod
    import haiji.tool.base as _tool_reg_mod

    # AgentRegistry / ToolRegistry 是模块级单例，直接操作内部字典
    original_agents = dict(_agent_reg_mod._registry._agents)
    original_tools = dict(_tool_reg_mod._registry._tools)
    _agent_reg_mod._registry._agents.clear()
    _tool_reg_mod._registry._tools.clear()
    reset_workflow_registry()
    yield
    _agent_reg_mod._registry._agents.clear()
    _agent_reg_mod._registry._agents.update(original_agents)
    _tool_reg_mod._registry._tools.clear()
    _tool_reg_mod._registry._tools.update(original_tools)
    reset_workflow_registry()


# ---------------------------------------------------------------------------
# 数据结构测试
# ---------------------------------------------------------------------------


class TestWorkflowStep:
    """WorkflowStep 数据结构测试。"""

    def test_agent_step_creation(self):
        """AGENT 步骤可以正常创建。"""
        step = make_agent_step("s1", agent_code="MyAgent", next_step_id="s2")
        assert step.step_id == "s1"
        assert step.kind == StepKind.AGENT
        assert step.agent_code == "MyAgent"
        assert step.next_step_id == "s2"

    def test_condition_step_creation(self):
        """CONDITION 步骤可以正常创建。"""
        step = make_condition_step(
            "branch",
            condition_expr="'ok' in step_s1_result",
            next_step_id="success",
            else_step_id="failure",
        )
        assert step.kind == StepKind.CONDITION
        assert step.condition_expr == "'ok' in step_s1_result"
        assert step.else_step_id == "failure"

    def test_parallel_step_creation(self):
        """PARALLEL 步骤可以正常创建。"""
        sub1 = make_agent_step("sub_a", agent_code="AgentA")
        sub2 = make_agent_step("sub_b", agent_code="AgentB")
        step = WorkflowStep(
            step_id="parallel",
            kind=StepKind.PARALLEL,
            parallel_steps=[sub1, sub2],
            next_step_id="merge",
        )
        assert len(step.parallel_steps) == 2
        assert step.parallel_steps[0].step_id == "sub_a"

    def test_step_kind_values(self):
        """StepKind 枚举值正确。"""
        assert StepKind.AGENT == "agent"
        assert StepKind.CONDITION == "condition"
        assert StepKind.PARALLEL == "parallel"


class TestWorkflowDefinition:
    """WorkflowDefinition 数据结构测试。"""

    def test_create_basic_workflow(self):
        """基本工作流定义创建。"""
        step = make_agent_step("s1")
        wf = WorkflowDefinition(
            workflow_id="test_wf",
            name="测试工作流",
            steps=[step],
            entry_step_id="s1",
        )
        assert wf.workflow_id == "test_wf"
        assert wf.name == "测试工作流"
        assert wf.entry_step_id == "s1"
        assert wf.max_total_steps == 50

    def test_default_workflow_id_generated(self):
        """不传 workflow_id 时自动生成。"""
        wf = WorkflowDefinition(steps=[], entry_step_id="s1")
        assert wf.workflow_id.startswith("wf_")

    def test_get_step_found(self):
        """get_step 找到存在的步骤。"""
        step1 = make_agent_step("s1")
        step2 = make_agent_step("s2")
        wf = WorkflowDefinition(
            workflow_id="wf1",
            steps=[step1, step2],
            entry_step_id="s1",
        )
        found = wf.get_step("s2")
        assert found is not None
        assert found.step_id == "s2"

    def test_get_step_not_found(self):
        """get_step 找不到时返回 None。"""
        step1 = make_agent_step("s1")
        wf = WorkflowDefinition(workflow_id="wf1", steps=[step1], entry_step_id="s1")
        assert wf.get_step("nonexistent") is None

    def test_max_total_steps_validation(self):
        """max_total_steps 边界值（>= 1, <= 500）。"""
        wf = WorkflowDefinition(
            workflow_id="wf_limit",
            steps=[],
            entry_step_id="s1",
            max_total_steps=1,
        )
        assert wf.max_total_steps == 1

        wf2 = WorkflowDefinition(
            workflow_id="wf_limit2",
            steps=[],
            entry_step_id="s1",
            max_total_steps=500,
        )
        assert wf2.max_total_steps == 500


class TestWorkflowResult:
    """WorkflowResult 数据结构测试。"""

    def test_success_result(self):
        """成功结果。"""
        result = WorkflowResult(
            workflow_id="wf1",
            session_id="sess1",
            success=True,
            step_results={"step_s1_result": "输出A"},
        )
        assert result.success is True
        assert result.step_results["step_s1_result"] == "输出A"
        assert result.error is None

    def test_failure_result(self):
        """失败结果包含 error 信息。"""
        result = WorkflowResult(
            workflow_id="wf1",
            session_id="sess1",
            success=False,
            error="步骤执行失败",
        )
        assert result.success is False
        assert result.error == "步骤执行失败"

    def test_duration_ms_computed(self):
        """duration_ms 计算属性正确。"""
        start = datetime(2026, 1, 1, 0, 0, 0)
        end = datetime(2026, 1, 1, 0, 0, 2)  # 2 秒后
        result = WorkflowResult(
            workflow_id="wf1",
            session_id="sess1",
            started_at=start,
            finished_at=end,
        )
        assert result.duration_ms == pytest.approx(2000.0)

    def test_duration_ms_none_when_not_finished(self):
        """未结束时 duration_ms 返回 None。"""
        result = WorkflowResult(
            workflow_id="wf1",
            session_id="sess1",
            finished_at=None,
        )
        assert result.duration_ms is None


# ---------------------------------------------------------------------------
# WorkflowEngine 辅助方法测试
# ---------------------------------------------------------------------------


class TestWorkflowEngineHelpers:
    """WorkflowEngine 辅助方法单元测试。"""

    def setup_method(self):
        self.engine = WorkflowEngine()

    def test_render_message_no_template(self):
        """无模板时返回 initial_message。"""
        result = WorkflowEngine._render_message("", {}, "初始消息")
        assert result == "初始消息"

    def test_render_message_with_template(self):
        """模板中的占位符被替换为 step_results 中的值。"""
        result = WorkflowEngine._render_message(
            "请总结：{{step_s1_result}}",
            {"step_s1_result": "Agent A 的输出"},
            "初始",
        )
        assert result == "请总结：Agent A 的输出"

    def test_render_message_missing_variable_kept(self):
        """找不到的变量保留原始占位符，不抛异常。"""
        result = WorkflowEngine._render_message(
            "来自 {{step_missing_result}} 的数据",
            {},
            "初始",
        )
        assert result == "来自 {{step_missing_result}} 的数据"

    def test_render_message_multiple_vars(self):
        """多个占位符全部替换。"""
        result = WorkflowEngine._render_message(
            "A={{step_a_result}} B={{step_b_result}}",
            {"step_a_result": "val_a", "step_b_result": "val_b"},
            "初始",
        )
        assert result == "A=val_a B=val_b"

    def test_eval_condition_true(self):
        """条件为 True 时返回 True。"""
        step = make_condition_step("c1", condition_expr="'hello' in step_s1_result")
        result = self.engine._eval_condition(step, {"step_s1_result": "hello world"})
        assert result is True

    def test_eval_condition_false(self):
        """条件为 False 时返回 False。"""
        step = make_condition_step("c1", condition_expr="'error' in step_s1_result")
        result = self.engine._eval_condition(step, {"step_s1_result": "hello world"})
        assert result is False

    def test_eval_condition_comparison(self):
        """支持字符串包含比较（in 操作）。"""
        step = make_condition_step("c1", condition_expr="step_s1_result == 'hello'")
        result = self.engine._eval_condition(step, {"step_s1_result": "hello"})
        assert result is True

    def test_eval_condition_missing_expr(self):
        """缺少 condition_expr 时抛 WorkflowConditionError。"""
        step = WorkflowStep(
            step_id="c1",
            kind=StepKind.CONDITION,
            condition_expr=None,
        )
        with pytest.raises(WorkflowConditionError, match="缺少 condition_expr"):
            self.engine._eval_condition(step, {})

    def test_eval_condition_invalid_expr(self):
        """非法表达式（语法错误）抛 WorkflowConditionError。"""
        step = make_condition_step("c1", condition_expr="this is not valid python !!!")
        with pytest.raises(WorkflowConditionError, match="条件表达式执行失败"):
            self.engine._eval_condition(step, {})

    def test_eval_condition_blocks_import(self):
        """条件表达式不允许 import 关键字。"""
        step = make_condition_step("c1", condition_expr="import os")
        with pytest.raises(WorkflowConditionError, match="禁止关键字"):
            self.engine._eval_condition(step, {})

    def test_eval_condition_blocks_dunder(self):
        """条件表达式不允许 __ 关键字（防注入）。"""
        step = make_condition_step("c1", condition_expr="__import__('os')")
        with pytest.raises(WorkflowConditionError, match="禁止关键字"):
            self.engine._eval_condition(step, {})

    def test_eval_condition_blocks_exec(self):
        """条件表达式不允许 exec 关键字。"""
        step = make_condition_step("c1", condition_expr="exec('print(1)')")
        with pytest.raises(WorkflowConditionError, match="禁止关键字"):
            self.engine._eval_condition(step, {})


# ---------------------------------------------------------------------------
# WorkflowEngine 执行测试
# ---------------------------------------------------------------------------


class TestWorkflowEngineRun:
    """WorkflowEngine.run() 端到端执行测试（Mock Agent）。"""

    @pytest.mark.asyncio
    async def test_single_agent_step(self):
        """单步 AGENT 工作流正常执行。"""
        register_mock_agent("AgentA", response_text="AgentA 的输出")
        step = make_agent_step("s1", agent_code="AgentA")
        wf = WorkflowDefinition(
            workflow_id="wf_single",
            steps=[step],
            entry_step_id="s1",
        )
        engine = WorkflowEngine()
        result = await engine.run(wf, "测试消息")
        assert result.success is True
        assert "step_s1_result" in result.step_results
        assert result.step_results["step_s1_result"] == "AgentA 的输出"
        assert result.finished_at is not None

    @pytest.mark.asyncio
    async def test_linear_two_steps(self):
        """两步线性流：A → B，B 可以引用 A 的输出。"""
        register_mock_agent("AgentA", response_text="来自A")
        register_mock_agent("AgentB", response_text="来自B")
        step1 = make_agent_step("s1", agent_code="AgentA", next_step_id="s2")
        step2 = make_agent_step(
            "s2",
            agent_code="AgentB",
            message_template="处理：{{step_s1_result}}",
        )
        wf = WorkflowDefinition(
            workflow_id="wf_linear",
            steps=[step1, step2],
            entry_step_id="s1",
        )
        engine = WorkflowEngine()
        result = await engine.run(wf, "开始")
        assert result.success is True
        assert result.step_results["step_s1_result"] == "来自A"
        assert result.step_results["step_s2_result"] == "来自B"

    @pytest.mark.asyncio
    async def test_condition_step_true_branch(self):
        """CONDITION 步骤：条件满足时走 next_step_id 分支。"""
        register_mock_agent("AgentA", response_text="成功")
        register_mock_agent("SuccessAgent", response_text="走成功分支")
        register_mock_agent("FailureAgent", response_text="走失败分支")

        step1 = make_agent_step("s1", agent_code="AgentA", next_step_id="check")
        step_check = make_condition_step(
            "check",
            condition_expr="'成功' in step_s1_result",
            next_step_id="success",
            else_step_id="failure",
        )
        step_success = make_agent_step("success", agent_code="SuccessAgent")
        step_failure = make_agent_step("failure", agent_code="FailureAgent")

        wf = WorkflowDefinition(
            workflow_id="wf_condition",
            steps=[step1, step_check, step_success, step_failure],
            entry_step_id="s1",
        )
        engine = WorkflowEngine()
        result = await engine.run(wf, "测试")
        assert result.success is True
        assert "step_success_result" in result.step_results
        assert "step_failure_result" not in result.step_results

    @pytest.mark.asyncio
    async def test_condition_step_false_branch(self):
        """CONDITION 步骤：条件不满足时走 else_step_id 分支。"""
        register_mock_agent("AgentA", response_text="错误发生")
        register_mock_agent("SuccessAgent", response_text="走成功分支")
        register_mock_agent("FailureAgent", response_text="走失败分支")

        step1 = make_agent_step("s1", agent_code="AgentA", next_step_id="check")
        step_check = make_condition_step(
            "check",
            condition_expr="'成功' in step_s1_result",
            next_step_id="success",
            else_step_id="failure",
        )
        step_success = make_agent_step("success", agent_code="SuccessAgent")
        step_failure = make_agent_step("failure", agent_code="FailureAgent")

        wf = WorkflowDefinition(
            workflow_id="wf_condition_false",
            steps=[step1, step_check, step_success, step_failure],
            entry_step_id="s1",
        )
        engine = WorkflowEngine()
        result = await engine.run(wf, "测试")
        assert result.success is True
        assert "step_failure_result" in result.step_results
        assert "step_success_result" not in result.step_results

    @pytest.mark.asyncio
    async def test_condition_step_no_else(self):
        """CONDITION 步骤：else_step_id 为 None 时条件不满足直接结束。"""
        register_mock_agent("AgentA", response_text="ordinary output")
        register_mock_agent("SuccessAgent", response_text="走成功分支")

        step1 = make_agent_step("s1", agent_code="AgentA", next_step_id="check")
        step_check = make_condition_step(
            "check",
            # "SPECIAL_TOKEN" 不在 "ordinary output" 里，条件为 False
            condition_expr="'SPECIAL_TOKEN' in step_s1_result",
            next_step_id="success",
            else_step_id=None,
        )
        step_success = make_agent_step("success", agent_code="SuccessAgent")

        wf = WorkflowDefinition(
            workflow_id="wf_cond_no_else",
            steps=[step1, step_check, step_success],
            entry_step_id="s1",
        )
        engine = WorkflowEngine()
        result = await engine.run(wf, "测试")
        assert result.success is True
        assert "step_success_result" not in result.step_results

    @pytest.mark.asyncio
    async def test_parallel_steps(self):
        """PARALLEL 步骤：并发执行多个子步骤，全部结果收集。"""
        register_mock_agent("AgentA", response_text="A 输出")
        register_mock_agent("AgentB", response_text="B 输出")
        register_mock_agent("MergeAgent", response_text="合并结果")

        sub_a = make_agent_step("sub_a", agent_code="AgentA")
        sub_b = make_agent_step("sub_b", agent_code="AgentB")

        step_parallel = WorkflowStep(
            step_id="parallel",
            kind=StepKind.PARALLEL,
            parallel_steps=[sub_a, sub_b],
            next_step_id="merge",
        )
        step_merge = make_agent_step("merge", agent_code="MergeAgent")

        wf = WorkflowDefinition(
            workflow_id="wf_parallel",
            steps=[step_parallel, step_merge],
            entry_step_id="parallel",
        )
        engine = WorkflowEngine()
        result = await engine.run(wf, "开始")
        assert result.success is True
        assert result.step_results.get("step_sub_a_result") == "A 输出"
        assert result.step_results.get("step_sub_b_result") == "B 输出"
        assert "step_merge_result" in result.step_results

    @pytest.mark.asyncio
    async def test_parallel_no_sub_steps(self):
        """PARALLEL 步骤：无子步骤时跳过，不报错。"""
        step_parallel = WorkflowStep(
            step_id="parallel",
            kind=StepKind.PARALLEL,
            parallel_steps=None,  # 没有子步骤
        )
        wf = WorkflowDefinition(
            workflow_id="wf_parallel_empty",
            steps=[step_parallel],
            entry_step_id="parallel",
        )
        engine = WorkflowEngine()
        result = await engine.run(wf, "开始")
        assert result.success is True
        assert result.step_results == {}

    @pytest.mark.asyncio
    async def test_max_steps_exceeded(self):
        """超过 max_total_steps 时返回失败结果（防死循环）。"""
        register_mock_agent("AgentA", response_text="循环输出")

        # 步骤 A 指向步骤 B，步骤 B 指向步骤 A → 形成循环
        # 但实际上我们只需要 max_total_steps=1，让第二步触发超限
        step1 = make_agent_step("s1", agent_code="AgentA", next_step_id="s2")
        step2 = make_agent_step("s2", agent_code="AgentA", next_step_id="s3")
        step3 = make_agent_step("s3", agent_code="AgentA")

        wf = WorkflowDefinition(
            workflow_id="wf_maxsteps",
            steps=[step1, step2, step3],
            entry_step_id="s1",
            max_total_steps=2,  # 最多执行 2 步，第 3 步会超限
        )
        engine = WorkflowEngine()
        result = await engine.run(wf, "测试")
        assert result.success is False
        assert "超过上限" in result.error

    @pytest.mark.asyncio
    async def test_step_not_found(self):
        """步骤 ID 不存在时返回失败结果。"""
        step = make_agent_step("s1", agent_code="AgentA", next_step_id="nonexistent")
        register_mock_agent("AgentA", response_text="输出")

        wf = WorkflowDefinition(
            workflow_id="wf_missing_step",
            steps=[step],  # 只有 s1，没有 nonexistent
            entry_step_id="s1",
        )
        engine = WorkflowEngine()
        result = await engine.run(wf, "测试")
        assert result.success is False
        assert "nonexistent" in result.error

    @pytest.mark.asyncio
    async def test_agent_not_registered(self):
        """Agent 未注册时返回失败结果。"""
        step = make_agent_step("s1", agent_code="NotExistAgent")
        wf = WorkflowDefinition(
            workflow_id="wf_no_agent",
            steps=[step],
            entry_step_id="s1",
        )
        engine = WorkflowEngine()
        result = await engine.run(wf, "测试")
        assert result.success is False
        assert "NotExistAgent" in result.error

    @pytest.mark.asyncio
    async def test_workflow_result_has_timing(self):
        """工作流结果包含 started_at 和 finished_at，duration_ms > 0。"""
        register_mock_agent("AgentA", response_text="输出")
        step = make_agent_step("s1", agent_code="AgentA")
        wf = WorkflowDefinition(workflow_id="wf_timing", steps=[step], entry_step_id="s1")
        engine = WorkflowEngine()
        result = await engine.run(wf, "测试")
        assert result.started_at is not None
        assert result.finished_at is not None
        assert result.duration_ms is not None
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_session_id_auto_generated(self):
        """不传 session_id 时自动生成。"""
        register_mock_agent("AgentA", response_text="输出")
        step = make_agent_step("s1", agent_code="AgentA")
        wf = WorkflowDefinition(workflow_id="wf_sess", steps=[step], entry_step_id="s1")
        engine = WorkflowEngine()
        result = await engine.run(wf, "测试")
        assert result.session_id.startswith("wf_sess_")

    @pytest.mark.asyncio
    async def test_custom_session_id(self):
        """传入自定义 session_id 时正确保存到结果。"""
        register_mock_agent("AgentA", response_text="输出")
        step = make_agent_step("s1", agent_code="AgentA")
        wf = WorkflowDefinition(workflow_id="wf_custom", steps=[step], entry_step_id="s1")
        engine = WorkflowEngine()
        result = await engine.run(wf, "测试", session_id="my_custom_session")
        assert result.session_id == "my_custom_session"

    @pytest.mark.asyncio
    async def test_condition_expr_error_returns_failure(self):
        """条件表达式错误时工作流返回失败（而非抛出未捕获异常）。"""
        register_mock_agent("AgentA", response_text="输出")
        step1 = make_agent_step("s1", agent_code="AgentA", next_step_id="check")
        step_check = make_condition_step(
            "check",
            condition_expr="undefined_var > 100",  # 引用了不存在的变量
        )
        wf = WorkflowDefinition(
            workflow_id="wf_bad_cond",
            steps=[step1, step_check],
            entry_step_id="s1",
        )
        engine = WorkflowEngine()
        result = await engine.run(wf, "测试")
        assert result.success is False
        assert result.error is not None


# ---------------------------------------------------------------------------
# WorkflowRegistry 测试
# ---------------------------------------------------------------------------


class TestWorkflowRegistry:
    """WorkflowRegistry 单元测试。"""

    def setup_method(self):
        self.registry = WorkflowRegistry()

    def test_register_and_get(self):
        """注册后可以按 workflow_id 查找。"""
        wf = WorkflowDefinition(workflow_id="wf_reg_1", steps=[], entry_step_id="s1")
        self.registry.register(wf)
        found = self.registry.get("wf_reg_1")
        assert found is not None
        assert found.workflow_id == "wf_reg_1"

    def test_get_not_found(self):
        """未注册的 workflow_id 返回 None。"""
        assert self.registry.get("nonexistent") is None

    def test_register_overwrite(self):
        """重复注册同 workflow_id 会覆盖（不报错）。"""
        wf1 = WorkflowDefinition(workflow_id="wf1", name="版本1", steps=[], entry_step_id="s1")
        wf2 = WorkflowDefinition(workflow_id="wf1", name="版本2", steps=[], entry_step_id="s1")
        self.registry.register(wf1)
        self.registry.register(wf2)
        found = self.registry.get("wf1")
        assert found.name == "版本2"

    def test_all_workflow_ids(self):
        """all_workflow_ids 返回所有已注册 ID。"""
        wf1 = WorkflowDefinition(workflow_id="wf_a", steps=[], entry_step_id="s1")
        wf2 = WorkflowDefinition(workflow_id="wf_b", steps=[], entry_step_id="s1")
        self.registry.register(wf1)
        self.registry.register(wf2)
        ids = self.registry.all_workflow_ids()
        assert "wf_a" in ids
        assert "wf_b" in ids

    def test_clear(self):
        """clear 后注册表为空。"""
        wf = WorkflowDefinition(workflow_id="wf_clear", steps=[], entry_step_id="s1")
        self.registry.register(wf)
        self.registry.clear()
        assert self.registry.get("wf_clear") is None

    def test_len(self):
        """__len__ 返回已注册数量。"""
        assert len(self.registry) == 0
        wf1 = WorkflowDefinition(workflow_id="wf_len_1", steps=[], entry_step_id="s1")
        self.registry.register(wf1)
        assert len(self.registry) == 1


# ---------------------------------------------------------------------------
# 全局单例测试
# ---------------------------------------------------------------------------


class TestGetWorkflowRegistry:
    """全局单例 get_workflow_registry / reset_workflow_registry 测试。"""

    def test_singleton_returns_same_instance(self):
        """多次调用返回同一实例。"""
        r1 = get_workflow_registry()
        r2 = get_workflow_registry()
        assert r1 is r2

    def test_reset_creates_new_instance(self):
        """reset 后返回新实例。"""
        r1 = get_workflow_registry()
        reset_workflow_registry()
        r2 = get_workflow_registry()
        assert r1 is not r2

    def test_reset_clears_registrations(self):
        """reset 后旧注册内容不可访问。"""
        registry = get_workflow_registry()
        wf = WorkflowDefinition(workflow_id="wf_singleton", steps=[], entry_step_id="s1")
        registry.register(wf)
        reset_workflow_registry()
        new_registry = get_workflow_registry()
        assert new_registry.get("wf_singleton") is None


# ---------------------------------------------------------------------------
# @workflow 装饰器测试
# ---------------------------------------------------------------------------


class TestWorkflowDecorator:
    """@workflow 装饰器测试。"""

    def test_workflow_decorator_on_instance(self):
        """装饰 WorkflowDefinition 实例时自动注册。"""
        wf = WorkflowDefinition(workflow_id="wf_deco_1", steps=[], entry_step_id="s1")
        result = workflow(wf)
        assert result is wf
        assert get_workflow_registry().get("wf_deco_1") is not None

    def test_workflow_decorator_on_function(self):
        """装饰返回 WorkflowDefinition 的函数时自动注册并返回实例。"""

        def build_wf() -> WorkflowDefinition:
            return WorkflowDefinition(workflow_id="wf_deco_func", steps=[], entry_step_id="s1")

        result = workflow(build_wf)
        assert isinstance(result, WorkflowDefinition)
        assert result.workflow_id == "wf_deco_func"
        assert get_workflow_registry().get("wf_deco_func") is not None

    def test_workflow_decorator_invalid_type_raises(self):
        """传入非 WorkflowDefinition 且非函数时抛 TypeError。"""
        with pytest.raises(TypeError, match="只接受"):
            workflow("invalid_string")  # type: ignore[arg-type]

    def test_workflow_decorator_function_returns_wrong_type(self):
        """装饰函数返回非 WorkflowDefinition 时抛 TypeError。"""

        def bad_func():
            return "not a workflow"

        with pytest.raises(TypeError, match="必须返回 WorkflowDefinition"):
            workflow(bad_func)
