"""
agent/registry.py - Agent 注册表

全局单例注册表，@agent 装饰器自动注册 Agent 类。
Agent 间互调时从这里查找目标 Agent。
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from haiji.agent.base import BaseAgent

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    全局 Agent 注册表。

    所有通过 @agent 装饰的类自动注册到这里。
    支持按 code 查找 Agent 类，用于 Multi-Agent 互调。

    示例::

        registry = get_agent_registry()
        cls = registry.get("research_agent")
        if cls:
            instance = cls()
    """

    def __init__(self) -> None:
        self._agents: dict[str, type["BaseAgent"]] = {}

    def register_class(self, cls: type["BaseAgent"]) -> None:
        """
        注册一个 Agent 类。

        Args:
            cls: BaseAgent 子类，必须有 _agent_definition 属性（由 @agent 装饰器注入）
        """
        from haiji.agent.definition import AgentDefinition  # 避免循环 import

        definition = getattr(cls, "_agent_definition", None)
        if not isinstance(definition, AgentDefinition):
            logger.warning(
                "[AgentRegistry] 类 %s 没有有效的 _agent_definition，跳过注册",
                cls.__name__,
            )
            return

        code = definition.code
        if code in self._agents:
            logger.warning("[AgentRegistry] agent_code=%s 已存在，将被覆盖", code)
        self._agents[code] = cls
        logger.info("[AgentRegistry] 注册 agent: %s (mode=%s)", code, definition.mode)

    def get(self, code: str) -> Optional[type["BaseAgent"]]:
        """
        按 code 查找 Agent 类。

        Args:
            code: Agent 唯一标识

        Returns:
            BaseAgent 子类，不存在则返回 None
        """
        return self._agents.get(code)

    def all_codes(self) -> list[str]:
        """返回所有已注册 Agent 的 code 列表。"""
        return list(self._agents.keys())

    def all(self) -> dict[str, type["BaseAgent"]]:
        """返回所有已注册 Agent 的 code → class 字典。"""
        return dict(self._agents)

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, code: str) -> bool:
        return code in self._agents


# 全局注册表单例
_registry = AgentRegistry()


def get_agent_registry() -> AgentRegistry:
    """获取全局 AgentRegistry 单例。"""
    return _registry
