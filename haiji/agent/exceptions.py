"""
agent/exceptions.py - Agent 模块自定义异常

所有 Agent 层的异常都继承自 HaijiBaseException。
"""

from __future__ import annotations


class HaijiBaseException(Exception):
    """框架根异常类"""
    pass


class AgentError(HaijiBaseException):
    """Agent 执行相关错误"""
    pass


class AgentCircularCallError(AgentError):
    """
    Multi-Agent 循环调用检测错误。

    当 Agent A 调用 Agent B，Agent B 又尝试调用 Agent A 时抛出。

    示例：
        raise AgentCircularCallError(
            "agent_code=main_agent 已在调用栈中，防循环检测拒绝重复调用"
        )
    """
    pass


class AgentMaxRoundsError(AgentError):
    """
    REACT 循环超出最大轮次限制。

    Agent 执行超过 max_rounds 次后抛出。

    示例：
        raise AgentMaxRoundsError(f"REACT 循环超出最大轮次 {max_rounds}")
    """
    pass


class AgentToolNotFoundError(AgentError):
    """调用了未注册的 Tool"""
    pass


class AgentConfigError(AgentError):
    """Agent 配置错误（缺少必要字段等）"""
    pass
