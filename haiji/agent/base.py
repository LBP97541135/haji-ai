"""
agent/base.py - Agent 基类 + 执行引擎 + @agent 装饰器

提供：
- BaseAgent：Agent 抽象基类，封装 prepare / execute / tool_call 逻辑
- DirectExecutor：DIRECT 模式（LLM 单次调用，无 Tool 循环）
- ReactLoopExecutor：REACT 模式（思考→工具→结果→再思考 循环）
- PlanExecuteExecutor：PLAN_AND_EXECUTE 模式（先规划再执行，第一期做骨架）
- @agent 装饰器：注册 Agent 类到 AgentRegistry
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional, TYPE_CHECKING

from haiji.agent.definition import AgentDefinition, AgentMode, AgentCallFrame
from haiji.agent.exceptions import (
    AgentCircularCallError,
    AgentMaxRoundsError,
    AgentToolNotFoundError,
    AgentConfigError,
)
from haiji.agent.registry import get_agent_registry
from haiji.context.definition import ExecutionContext, ToolCallContext
from haiji.llm.definition import LlmMessage, LlmRequest, LlmTool, ToolCall
from haiji.memory.base import SessionMemoryManager
from haiji.skill.base import build_prompt_fragment, get_skill_registry
from haiji.sse.base import SseEventEmitter
from haiji.tool.base import get_tool_registry

logger = logging.getLogger(__name__)

# 流式 token buffer 上限（性能规范）
_MAX_TOKEN_BUFFER = 4096


class BaseAgent:
    """
    Agent 抽象基类。

    子类通过 @agent 装饰器注册，并可以覆盖 system_prompt 属性。
    框架使用者不需要手动调用内部方法，只需调用 stream_chat()。

    示例::

        @agent(mode="react", skills=["web_research"])
        class ResearchAgent(BaseAgent):
            system_prompt = "你是一个擅长网络调研的助手。"

        agent_instance = ResearchAgent()
        emitter = SseEventEmitter()
        ctx = ExecutionContext.create(session_id="sess_1", agent_code="ResearchAgent")
        memory = SessionMemoryManager()

        async for event in emitter.events():
            print(event)

        # 在另一个协程里运行：
        await agent_instance.stream_chat("帮我搜索最新 AI 新闻", ctx, emitter, memory)
    """

    # 子类可以直接覆盖
    system_prompt: str = ""

    def __init__(self) -> None:
        definition = getattr(self, "_agent_definition", None)
        if not isinstance(definition, AgentDefinition):
            raise AgentConfigError(
                f"{self.__class__.__name__} 未通过 @agent 装饰器注册，缺少 _agent_definition"
            )
        self._definition: AgentDefinition = definition

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        user_message: str,
        ctx: ExecutionContext,
        emitter: SseEventEmitter,
        memory: SessionMemoryManager,
        llm_client: Any = None,  # LlmClient 实例，测试时传 mock
        call_stack: Optional[list[AgentCallFrame]] = None,
    ) -> None:
        """
        Agent 执行主入口（流式）。

        1. 将用户消息追加到 memory
        2. 根据 mode 分发到对应 Executor
        3. 执行完毕后 emit done 事件

        Args:
            user_message: 用户输入的消息
            ctx:          执行上下文
            emitter:      SSE 事件发射器
            memory:       会话记忆管理器
            llm_client:   LLM 客户端（可在运行时传入，优先于全局配置）
            call_stack:   Multi-Agent 调用栈，顶层调用传 None 即可
        """
        call_stack = call_stack or []

        # 防循环：将自身加入调用栈
        current_frame = AgentCallFrame(
            agent_code=self._definition.code,
            session_id=ctx.session_id,
        )
        call_stack = call_stack + [current_frame]

        # 追加用户消息
        memory.add_user_message(ctx.session_id, user_message)

        # 准备 LLM 工具列表 + system prompt
        llm_tools, system_prompt_text = self._prepare_execution()

        try:
            mode = self._definition.mode
            if mode == AgentMode.DIRECT:
                executor = DirectExecutor(self, llm_client, memory, emitter, call_stack)
                await executor.run(ctx, llm_tools, system_prompt_text)
            elif mode == AgentMode.REACT:
                executor = ReactLoopExecutor(self, llm_client, memory, emitter, call_stack)
                await executor.run(ctx, llm_tools, system_prompt_text)
            elif mode == AgentMode.PLAN_AND_EXECUTE:
                executor = PlanExecuteExecutor(self, llm_client, memory, emitter, call_stack)
                await executor.run(ctx, llm_tools, system_prompt_text)
            else:
                raise AgentConfigError(f"未知的 AgentMode: {mode}")
        except AgentMaxRoundsError as exc:
            logger.warning("[Agent:%s] %s", self._definition.code, exc)
            await emitter.emit_error(str(exc))
        except AgentCircularCallError as exc:
            logger.warning("[Agent:%s] 循环调用检测: %s", self._definition.code, exc)
            await emitter.emit_error(str(exc))
        except Exception as exc:
            logger.error("[Agent:%s] 执行异常: %s", self._definition.code, exc, exc_info=True)
            await emitter.emit_error(f"Agent 执行失败：{exc}")

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _prepare_execution(self) -> tuple[list[LlmTool], str]:
        """
        准备执行：
        1. 从 SkillRegistry 加载所需 Skill，收集关联 Tool 的 FunctionDef
        2. 从 ToolRegistry 加载直接声明的 Tool
        3. 渲染 system_prompt（拼接 Skill prompt 片段）

        Returns:
            (llm_tools, system_prompt_text)
        """
        skill_registry = get_skill_registry()
        tool_registry = get_tool_registry()

        # 加载 Skill，收集 tool_codes
        activated_skills = []
        skill_tool_codes: list[str] = []
        for skill_code in self._definition.required_skill_codes:
            entry = skill_registry.get(skill_code)
            if entry is None:
                logger.warning(
                    "[Agent:%s] Skill '%s' 未注册，跳过",
                    self._definition.code,
                    skill_code,
                )
                continue
            activated_skills.append(entry)
            skill_tool_codes.extend(entry.tool_codes)

        # 合并 tool_codes（Skill 带来的 + 直接声明的）
        all_tool_codes = list(dict.fromkeys(skill_tool_codes + self._definition.required_tool_codes))

        # 收集 LlmTool 列表
        llm_tools: list[LlmTool] = []
        for tool_code in all_tool_codes:
            tool = tool_registry.get(tool_code)
            if tool is None:
                logger.warning(
                    "[Agent:%s] Tool '%s' 未注册，跳过",
                    self._definition.code,
                    tool_code,
                )
                continue
            llm_tools.append(tool.to_meta().to_llm_tool())

        # 渲染 system_prompt
        skill_fragment = build_prompt_fragment(activated_skills)
        base_prompt = self._definition.system_prompt or self.system_prompt
        if skill_fragment:
            system_prompt_text = f"{base_prompt}\n\n{skill_fragment}" if base_prompt else skill_fragment
        else:
            system_prompt_text = base_prompt

        logger.debug(
            "[Agent:%s] 准备完成：skills=%s tools=%d",
            self._definition.code,
            self._definition.required_skill_codes,
            len(llm_tools),
        )
        return llm_tools, system_prompt_text

    async def execute_tool(
        self,
        tool_call: ToolCall,
        ctx: ExecutionContext,
        call_stack: list[AgentCallFrame],
        llm_client: Any = None,
    ) -> str:
        """
        执行 Tool。

        若 tool_call.name 对应的是另一个 Agent，则走 Multi-Agent 互调路径，
        先检测循环再执行。

        Args:
            tool_call:  LLM 返回的工具调用信息
            ctx:        当前执行上下文
            call_stack: 当前调用栈（用于防循环）
            llm_client: LLM 客户端（子 Agent 执行时传递）

        Returns:
            str: 工具执行结果（将作为 tool_result 返回给 LLM）
        """
        tool_code = tool_call.name
        agent_registry = get_agent_registry()
        tool_registry = get_tool_registry()

        # 优先匹配 Agent（Multi-Agent 互调路径）
        agent_cls = agent_registry.get(tool_code)
        if agent_cls is not None:
            return await self._invoke_sub_agent(
                agent_cls=agent_cls,
                tool_call=tool_call,
                ctx=ctx,
                call_stack=call_stack,
                llm_client=llm_client,
            )

        # 普通 Tool 执行路径
        tool_impl = tool_registry.get(tool_code)
        if tool_impl is None:
            raise AgentToolNotFoundError(f"Tool '{tool_code}' 未注册")

        tool_ctx = ToolCallContext.from_execution(ctx)
        try:
            args = json.loads(tool_call.arguments) if tool_call.arguments else {}
        except json.JSONDecodeError as exc:
            raise AgentToolNotFoundError(f"Tool '{tool_code}' 参数解析失败: {exc}") from exc

        logger.info(
            "[Agent:%s] 调用 Tool: %s args=%s",
            self._definition.code,
            tool_code,
            str(args)[:200],
        )
        result = await tool_impl.execute(args, tool_ctx)
        logger.debug("[Agent:%s] Tool %s 结果: %s", self._definition.code, tool_code, str(result)[:200])
        return result

    async def _invoke_sub_agent(
        self,
        agent_cls: type[BaseAgent],
        tool_call: ToolCall,
        ctx: ExecutionContext,
        call_stack: list[AgentCallFrame],
        llm_client: Any,
    ) -> str:
        """
        Multi-Agent 互调：将另一个 Agent 作为 Tool 调用。

        防循环检测：若目标 Agent 已在 call_stack 中，拒绝调用。
        """
        target_code = tool_call.name

        # 防循环检测
        for frame in call_stack:
            if frame.agent_code == target_code and frame.session_id == ctx.session_id:
                raise AgentCircularCallError(
                    f"检测到循环调用：agent_code='{target_code}' 已在调用栈中 "
                    f"(session_id={ctx.session_id})，拒绝执行"
                )

        logger.info(
            "[Agent:%s] 调用子 Agent: %s",
            self._definition.code,
            target_code,
        )

        sub_agent = agent_cls()
        sub_definition: AgentDefinition = sub_agent._definition

        # 解析用户消息（从 tool_call.arguments 取 message 字段）
        try:
            args = json.loads(tool_call.arguments) if tool_call.arguments else {}
        except json.JSONDecodeError:
            args = {}
        user_msg = args.get("message", args.get("query", str(args)))

        # 子 Agent 上下文策略
        strategy = sub_definition.sub_agent_context_strategy
        from haiji.agent.definition import SubAgentContextStrategy

        if strategy == SubAgentContextStrategy.FRESH:
            sub_memory = SessionMemoryManager()
        elif strategy == SubAgentContextStrategy.FORK:
            # 复制父 Agent 的完整历史到子 Agent
            from haiji.memory.base import SessionMemoryManager as SMM
            sub_memory = SMM()
            from haiji.llm.definition import LlmMessage as LMsg
            for msg in _get_parent_memory_snapshot(ctx):
                sub_memory.add_message(ctx.session_id, msg)
        elif strategy == SubAgentContextStrategy.FORK_LAST:
            sub_memory = SessionMemoryManager()
        else:
            sub_memory = SessionMemoryManager()

        # 子 Agent 用独立 emitter，收集结果
        sub_emitter = SseEventEmitter()
        sub_ctx = ExecutionContext.create(
            session_id=ctx.session_id,
            agent_code=target_code,
            user_id=ctx.user_id,
        )

        # 收集子 Agent 输出
        result_parts: list[str] = []

        import asyncio

        async def _collect() -> None:
            async for event in sub_emitter.events():
                from haiji.sse.definition import SseEventType
                if event.type == SseEventType.TOKEN and event.message:
                    result_parts.append(event.message)

        collect_task = asyncio.create_task(_collect())
        await sub_agent.stream_chat(
            user_message=user_msg,
            ctx=sub_ctx,
            emitter=sub_emitter,
            memory=sub_memory,
            llm_client=llm_client,
            call_stack=call_stack,
        )
        await collect_task

        result = "".join(result_parts) or f"子 Agent '{target_code}' 执行完毕（无文本输出）"
        logger.info("[Agent:%s] 子 Agent %s 完成，输出 %d 字符", self._definition.code, target_code, len(result))
        return result


def _get_parent_memory_snapshot(ctx: ExecutionContext) -> list:
    """辅助函数：获取父 Agent 内存快照（FORK 策略用）"""
    # 实际项目中可以通过依赖注入拿到，这里返回空列表作为骨架
    return []


# ---------------------------------------------------------------------------
# DirectExecutor - DIRECT 模式
# ---------------------------------------------------------------------------


class DirectExecutor:
    """
    DIRECT 执行器：调用 LLM 一次，直接输出结果，不支持 Tool 调用循环。

    适合简单的问答场景。
    """

    def __init__(
        self,
        agent: BaseAgent,
        llm_client: Any,
        memory: SessionMemoryManager,
        emitter: SseEventEmitter,
        call_stack: list[AgentCallFrame],
    ) -> None:
        self._agent = agent
        self._llm_client = llm_client
        self._memory = memory
        self._emitter = emitter
        self._call_stack = call_stack

    async def run(
        self,
        ctx: ExecutionContext,
        llm_tools: list[LlmTool],
        system_prompt: str,
    ) -> None:
        """执行 DIRECT 模式"""
        messages = self._build_messages(ctx, system_prompt)

        request = LlmRequest(
            messages=messages,
            tools=llm_tools if llm_tools else None,
            stream=True,
        )

        logger.info("[DirectExecutor] agent=%s 开始流式输出", self._agent._definition.code)

        token_count = 0
        full_content: list[str] = []

        async for token in self._llm_client.stream_chat(request):
            if token_count >= _MAX_TOKEN_BUFFER:
                logger.warning("[DirectExecutor] token buffer 达到上限 %d，截断输出", _MAX_TOKEN_BUFFER)
                break
            await self._emitter.emit_token(token)
            full_content.append(token)
            token_count += 1

        final = "".join(full_content)
        self._memory.add_assistant_message(ctx.session_id, final)
        await self._emitter.emit_done(final)

    def _build_messages(self, ctx: ExecutionContext, system_prompt: str) -> list[LlmMessage]:
        """构建 LLM 消息列表（system + history）"""
        messages: list[LlmMessage] = []
        if system_prompt:
            messages.append(LlmMessage.system(system_prompt))
        messages.extend(self._memory.get_history(ctx.session_id))
        return messages


# ---------------------------------------------------------------------------
# ReactLoopExecutor - REACT 模式
# ---------------------------------------------------------------------------


class ReactLoopExecutor:
    """
    REACT 执行器：思考 → 选工具 → 执行 → 追加结果 → 再思考，循环至无工具调用或超轮次。

    每轮循环中，LLM 流式输出 token（emit token 事件），
    若 LLM 返回 tool_calls，则执行 Tool 并将结果追加到 memory，再开始下一轮。
    """

    def __init__(
        self,
        agent: BaseAgent,
        llm_client: Any,
        memory: SessionMemoryManager,
        emitter: SseEventEmitter,
        call_stack: list[AgentCallFrame],
    ) -> None:
        self._agent = agent
        self._llm_client = llm_client
        self._memory = memory
        self._emitter = emitter
        self._call_stack = call_stack

    async def run(
        self,
        ctx: ExecutionContext,
        llm_tools: list[LlmTool],
        system_prompt: str,
    ) -> None:
        """执行 REACT 循环"""
        max_rounds = self._agent._definition.max_rounds
        agent_code = self._agent._definition.code

        for round_num in range(1, max_rounds + 1):
            logger.info("[ReactLoop:%s] 第 %d 轮 / 共 %d 轮", agent_code, round_num, max_rounds)

            messages = self._build_messages(ctx, system_prompt)

            request = LlmRequest(
                messages=messages,
                tools=llm_tools if llm_tools else None,
                stream=False,  # REACT 模式用非流式以获取完整 tool_calls
            )

            # 调用 LLM（含 tool_calls 检测）
            response = await self._llm_client.chat_with_tools(request)

            # 若有 tool_calls，执行工具后继续循环
            if response.tool_calls:
                # 将 assistant 消息（含 tool_calls）加入 memory
                assistant_msg = LlmMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=[
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": tc.arguments},
                        }
                        for tc in response.tool_calls
                    ],
                )
                self._memory.add_message(ctx.session_id, assistant_msg)

                # 执行所有 tool_calls
                for tool_call in response.tool_calls:
                    await self._emitter.emit_tool_call(
                        tool_name=tool_call.name,
                        tool_call_id=tool_call.id,
                        arguments=tool_call.arguments,
                    )

                    try:
                        result = await self._agent.execute_tool(
                            tool_call=tool_call,
                            ctx=ctx,
                            call_stack=self._call_stack,
                            llm_client=self._llm_client,
                        )
                    except (AgentToolNotFoundError, AgentCircularCallError) as exc:
                        result = f"[ERROR] {exc}"
                        logger.error("[ReactLoop:%s] tool=%s 执行失败: %s", agent_code, tool_call.name, exc)

                    # 追加 tool_result 到 memory
                    tool_result_msg = LlmMessage.tool_result(
                        tool_call_id=tool_call.id,
                        content=result,
                    )
                    self._memory.add_message(ctx.session_id, tool_result_msg)

                    await self._emitter.emit_tool_result(
                        tool_name=tool_call.name,
                        tool_call_id=tool_call.id,
                        result=result,
                    )

                # 继续下一轮
                continue

            # 无 tool_calls：最终输出，流式 emit
            final_content = response.content or ""
            logger.info("[ReactLoop:%s] 第 %d 轮完成，开始输出结果", agent_code, round_num)

            # 流式输出最终内容（分块 emit）
            chunk_size = 10
            token_count = 0
            for i in range(0, len(final_content), chunk_size):
                if token_count >= _MAX_TOKEN_BUFFER:
                    logger.warning("[ReactLoop] token buffer 达到上限 %d，截断输出", _MAX_TOKEN_BUFFER)
                    break
                chunk = final_content[i: i + chunk_size]
                await self._emitter.emit_token(chunk)
                token_count += 1

            self._memory.add_assistant_message(ctx.session_id, final_content)
            await self._emitter.emit_done(final_content)
            return

        # 超出最大轮次
        raise AgentMaxRoundsError(
            f"REACT 循环超出最大轮次限制 max_rounds={max_rounds}，强制终止"
        )

    def _build_messages(self, ctx: ExecutionContext, system_prompt: str) -> list[LlmMessage]:
        """构建 LLM 消息列表"""
        messages: list[LlmMessage] = []
        if system_prompt:
            messages.append(LlmMessage.system(system_prompt))
        messages.extend(self._memory.get_history(ctx.session_id))
        return messages


# ---------------------------------------------------------------------------
# PlanExecuteExecutor - PLAN_AND_EXECUTE 模式（第一期骨架）
# ---------------------------------------------------------------------------


class PlanExecuteExecutor:
    """
    PLAN_AND_EXECUTE 执行器（第一期骨架）。

    先让 LLM 生成执行计划（list of steps），再顺序执行每步。
    第一期只实现骨架，后续补充完整逻辑。
    """

    def __init__(
        self,
        agent: BaseAgent,
        llm_client: Any,
        memory: SessionMemoryManager,
        emitter: SseEventEmitter,
        call_stack: list[AgentCallFrame],
    ) -> None:
        self._agent = agent
        self._llm_client = llm_client
        self._memory = memory
        self._emitter = emitter
        self._call_stack = call_stack

    async def run(
        self,
        ctx: ExecutionContext,
        llm_tools: list[LlmTool],
        system_prompt: str,
    ) -> None:
        """执行 PLAN_AND_EXECUTE 模式（第一期：降级为 REACT 模式）"""
        logger.info(
            "[PlanExecute:%s] PLAN_AND_EXECUTE 第一期骨架，降级为 REACT 执行",
            self._agent._definition.code,
        )
        react_executor = ReactLoopExecutor(
            agent=self._agent,
            llm_client=self._llm_client,
            memory=self._memory,
            emitter=self._emitter,
            call_stack=self._call_stack,
        )
        await react_executor.run(ctx, llm_tools, system_prompt)


# ---------------------------------------------------------------------------
# @agent 装饰器
# ---------------------------------------------------------------------------


def agent(
    *,
    mode: str = "react",
    skills: Optional[list[Any]] = None,
    tools: Optional[list[Any]] = None,
    code: Optional[str] = None,
    name: Optional[str] = None,
    max_rounds: int = 10,
    llm_config_override: Optional[dict[str, Any]] = None,
) -> Callable:
    """
    @agent 装饰器，将 BaseAgent 子类注册到 AgentRegistry。

    只做注册和元数据标记，不执行任何业务逻辑。

    Args:
        mode:                执行模式（"direct" / "react" / "plan_and_execute"）
        skills:              所需的 Skill 列表（class 或 code 字符串）
        tools:               直接依赖的 Tool 列表（函数或 code 字符串）
        code:                Agent 唯一标识，默认用类名
        name:                Agent 名称，默认和 code 相同
        max_rounds:          REACT 循环最大轮次（默认 10）
        llm_config_override: Agent 级别的 LLM 配置覆盖

    示例::

        @agent(mode="react", skills=["web_research"], max_rounds=5)
        class ResearchAgent(BaseAgent):
            system_prompt = "你是一个助手..."
    """

    def decorator(cls: type) -> type:
        agent_code = code or cls.__name__

        # 收集 skill_codes
        skill_codes: list[str] = []
        for s in skills or []:
            if isinstance(s, str):
                skill_codes.append(s)
            elif hasattr(s, "__name__"):
                skill_codes.append(s.__name__)
            else:
                logger.warning("[agent] 无法识别 skill=%r，跳过", s)

        # 收集 tool_codes
        tool_codes: list[str] = []
        for t in tools or []:
            if isinstance(t, str):
                tool_codes.append(t)
            elif hasattr(t, "_tool"):
                tool_codes.append(t._tool.tool_code)
            elif hasattr(t, "tool_code"):
                tool_codes.append(t.tool_code)
            else:
                logger.warning("[agent] 无法识别 tool=%r，跳过", t)

        # 读取类上定义的 system_prompt（若有）
        cls_system_prompt = getattr(cls, "system_prompt", "")

        definition = AgentDefinition(
            code=agent_code,
            name=name or agent_code,
            mode=AgentMode(mode),
            system_prompt=cls_system_prompt,
            required_skill_codes=skill_codes,
            required_tool_codes=tool_codes,
            max_rounds=max_rounds,
            llm_config_override=llm_config_override,
        )

        # 注入 _agent_definition 到类
        cls._agent_definition = definition  # type: ignore

        # 注册到全局 AgentRegistry
        registry = get_agent_registry()
        registry.register_class(cls)  # type: ignore

        return cls

    return decorator
