"""
agent - Agent 执行引擎

核心概念：
- AgentDefinition：Agent 元数据（code、mode、prompt、required_skills 等）
- AgentMode：执行模式（DIRECT / REACT / PLAN_AND_EXECUTE）
- BaseAgent：Agent 抽象基类，所有自定义 Agent 都继承此类
- @agent：装饰器，注册 Agent 到 AgentRegistry 并标记元数据
- AgentRegistry：全局注册表，支持 Agent 互调

示例::

    from haiji.agent import agent, BaseAgent, AgentMode
    from haiji.context.definition import ExecutionContext
    from haiji.memory.base import SessionMemoryManager
    from haiji.sse.base import SseEventEmitter

    @agent(mode="react", skills=["web_research"], max_rounds=5)
    class ResearchAgent(BaseAgent):
        system_prompt = "你是一个擅长网络调研的助手。"

    # 实例化并运行
    instance = ResearchAgent()
    ctx = ExecutionContext.create(session_id="sess_1", agent_code="ResearchAgent")
    memory = SessionMemoryManager()
    emitter = SseEventEmitter()

    await instance.stream_chat("帮我搜索最新 AI 新闻", ctx, emitter, memory, llm_client)

    async for event in emitter.events():
        print(event)
"""

from haiji.agent.definition import AgentDefinition, AgentMode, SubAgentContextStrategy, AgentCallFrame
from haiji.agent.registry import AgentRegistry, get_agent_registry
from haiji.agent.base import BaseAgent, agent
from haiji.agent.exceptions import (
    AgentError,
    AgentCircularCallError,
    AgentMaxRoundsError,
    AgentToolNotFoundError,
    AgentConfigError,
    HaijiBaseException,
)

__all__ = [
    # 数据结构
    "AgentDefinition",
    "AgentMode",
    "SubAgentContextStrategy",
    "AgentCallFrame",
    # 注册表
    "AgentRegistry",
    "get_agent_registry",
    # 基类 + 装饰器
    "BaseAgent",
    "agent",
    # 异常
    "HaijiBaseException",
    "AgentError",
    "AgentCircularCallError",
    "AgentMaxRoundsError",
    "AgentToolNotFoundError",
    "AgentConfigError",
]
