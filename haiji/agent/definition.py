"""
agent/definition.py - Agent 数据结构

定义 Agent 的元数据、执行模式、调用帧等核心数据结构。
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field


class AgentMode(str, Enum):
    """Agent 执行模式"""
    DIRECT = "direct"                   # 直接调用：LLM 一次返回结果，无 Tool 调用循环
    REACT = "react"                     # ReAct 循环：思考 → 选工具 → 执行 → 再思考
    PLAN_AND_EXECUTE = "plan_and_execute"  # 先规划 → 再执行每个步骤


class SubAgentContextStrategy(str, Enum):
    """子 Agent 上下文策略（Multi-Agent 互调时使用）"""
    FRESH = "fresh"        # 全新上下文，不继承任何历史
    FORK = "fork"          # 继承父 Agent 的完整历史
    FORK_LAST = "fork_last"  # 只继承父 Agent 的最近一条消息


class AgentDefinition(BaseModel):
    """
    Agent 元数据定义。

    由 @agent 装饰器读取并注册到 AgentRegistry。

    示例::

        @agent(mode="react", skills=["web_research"], max_rounds=5)
        class MyAgent(BaseAgent):
            system_prompt = "你是一个助手..."
    """

    code: str = Field(..., description="Agent 唯一标识")
    name: str = Field(default="", description="Agent 名称，默认和 code 相同")
    mode: AgentMode = Field(default=AgentMode.REACT, description="执行模式")
    system_prompt: str = Field(default="", description="系统提示词")
    required_skill_codes: list[str] = Field(
        default_factory=list, description="Agent 需要的 Skill codes"
    )
    required_tool_codes: list[str] = Field(
        default_factory=list, description="Agent 直接依赖的 Tool codes（不经过 Skill）"
    )
    max_rounds: int = Field(
        default=10,
        ge=1,
        le=100,
        description="REACT 循环最大轮次，防止死循环",
    )
    llm_config_override: Optional[dict[str, Any]] = Field(
        default=None,
        description="Agent 级别的 LLM 配置覆盖（优先级低于 runtime，高于 global）",
    )
    sub_agent_context_strategy: SubAgentContextStrategy = Field(
        default=SubAgentContextStrategy.FRESH,
        description="作为子 Agent 被调用时的上下文策略",
    )

    model_config = {"arbitrary_types_allowed": True}

    def model_post_init(self, __context: Any) -> None:
        if not self.name:
            self.name = self.code


class AgentCallFrame(BaseModel):
    """
    Multi-Agent 互调时的调用帧。

    随着调用链传递，用于检测循环调用。

    示例：
        call_stack = [
            AgentCallFrame(agent_code="main_agent", session_id="sess_1"),
            AgentCallFrame(agent_code="sub_agent", session_id="sess_1"),
        ]
        # 若要调用 main_agent，发现 call_stack 中已有，则拒绝
    """

    agent_code: str = Field(description="正在执行的 Agent code")
    session_id: str = Field(description="执行所在的 session_id")
