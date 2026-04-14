"""
designer/registrar.py - Agent 动态注册器

职责：将校验通过的 DesignDraft 动态构造 Agent 类并注册到 AgentRegistry。

关键特性：
1. 根据草稿 name 生成全局唯一的 agent_code（snake_case + 4位随机后缀）
2. 将 soul 文档注入 system_prompt
3. 使用 type() 动态创建 Agent 类
4. 支持 RAG 知识库注入
5. 注册到全局 AgentRegistry
"""

from __future__ import annotations

import logging
import random
import re
import string

from haiji.agent.base import BaseAgent
from haiji.agent.definition import AgentDefinition, AgentMode
from haiji.agent.registry import get_agent_registry
from haiji.designer.definition import DesignDraft

logger = logging.getLogger(__name__)


def _to_snake_case(name: str) -> str:
    """
    将任意字符串转换为合法的 snake_case 标识符。

    1. 去除非字母数字和空格的字符（含 emoji、标点等）
    2. 将空格替换为下划线
    3. 将 CamelCase 转为 snake_case
    4. 转为小写，去除首尾下划线

    Args:
        name: 任意字符串，如"投资顾问 Pro"

    Returns:
        str: snake_case 字符串，如"tou_zi_gu_wen_pro"；
             若最终为空则返回 "agent"
    """
    # 去除 emoji 和特殊符号，保留字母、数字、空格、下划线
    cleaned = re.sub(r"[^\w\s]", "", name, flags=re.UNICODE)
    # 将 CamelCase 转 snake_case（在大写字母前插入下划线）
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", cleaned)
    s2 = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s1)
    # 替换空白为下划线，转小写
    result = re.sub(r"[\s]+", "_", s2).lower().strip("_")
    # 去除连续下划线
    result = re.sub(r"_+", "_", result)
    return result or "agent"


def _make_code(name: str) -> str:
    """
    生成带随机后缀的唯一 agent_code。

    格式：{snake_case_name}_{4位随机字母数字}
    例如：investment_advisor_a3k9

    Args:
        name: Agent 名称（用户提供或 LLM 生成）

    Returns:
        str: 全局唯一的 agent_code
    """
    base = _to_snake_case(name)
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{base}_{suffix}"


class DesignerRegistrar:
    """
    Agent 动态注册器。

    将校验通过的 DesignDraft 动态构造为 BaseAgent 子类并注册到 AgentRegistry。
    支持 RAG 知识库注入。

    示例::

        registrar = DesignerRegistrar()
        agent_code, definition = registrar.register(draft, rag=my_kb)
        # 之后可通过 get_agent_registry().get(agent_code) 获取类
    """

    def register(
        self,
        draft: DesignDraft,
        rag: object = None,
        rag_config: object = None,
    ) -> tuple[str, AgentDefinition]:
        """
        将 DesignDraft 动态注册为 Agent。

        步骤：
        1. 生成全局唯一 agent_code（snake_case + 4位随机后缀）
        2. 构造注入 soul 后的 system_prompt
        3. 构造 AgentDefinition
        4. 用 type() 动态创建 BaseAgent 子类
        5. 注入 _rag_kb / _rag_config
        6. 注册到 AgentRegistry
        7. 返回 (agent_code, definition)

        Args:
            draft:      校验通过的 Agent 草稿
            rag:        可选知识库实例（BaseKnowledgeBase）
            rag_config: 可选 RAG 配置（RagConfig）

        Returns:
            tuple[str, AgentDefinition]: (agent_code, definition)
        """
        # Step 1: 生成唯一 agent_code
        agent_code = _make_code(draft.name)

        # Step 2: 构造注入 soul 后的 system_prompt
        identity_line = f"你叫{draft.name}，{draft.bio}" if draft.bio else f"你叫{draft.name}"
        if draft.soul:
            final_prompt = f"{draft.soul}\n\n---\n\n{identity_line}"
        else:
            final_prompt = identity_line

        # Step 3: 构造 AgentDefinition
        try:
            mode = AgentMode(draft.mode)
        except ValueError:
            logger.warning(
                "[DesignerRegistrar] 未知 mode=%r，降级为 REACT", draft.mode
            )
            mode = AgentMode.REACT

        definition = AgentDefinition(
            code=agent_code,
            name=draft.name,
            avatar=draft.avatar,
            bio=draft.bio,
            soul=draft.soul,
            mode=mode,
            system_prompt=final_prompt,
            required_tool_codes=draft.tool_codes,
            required_skill_codes=draft.skill_codes,
            tags=draft.tags,
        )

        # Step 4: 动态创建 Agent 类
        DynamicAgent = type(
            f"Agent_{agent_code}",
            (BaseAgent,),
            {
                "system_prompt": final_prompt,
                "_agent_definition": definition,
                "_rag_kb": rag,
                "_rag_config": rag_config,
            },
        )

        # Step 5 & 6: 注册到 AgentRegistry
        registry = get_agent_registry()
        registry.register_class(DynamicAgent)

        logger.info(
            "[DesignerRegistrar] 注册动态 Agent：code=%s name=%r mode=%s tools=%s",
            agent_code,
            draft.name,
            mode.value,
            draft.tool_codes,
        )

        # Step 7: 返回
        return agent_code, definition
