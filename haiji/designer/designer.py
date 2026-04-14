"""
designer/designer.py - Designer 门面类

将 Generator → Validator → Registrar 三步串联为统一入口。
用户只需调用 design() 即可完成 Agent 的生成、校验和注册。

使用示例::

    from haiji.designer import Designer

    designer = Designer(llm_client=my_llm_client)
    result = await designer.design("我想要一个懂投资的朋友，说话直接")

    if result.ok:
        print(f"Agent 注册成功：{result.agent_code}")
        agent = designer.get_agent(result.agent_code)
    else:
        for err in result.errors:
            print(f"[{err.field}] {err.message}")
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from haiji.agent.base import BaseAgent
from haiji.agent.registry import get_agent_registry
from haiji.designer.definition import DesignRequest, DesignResult
from haiji.designer.generator import DesignerGenerator
from haiji.designer.registrar import DesignerRegistrar
from haiji.designer.validator import DesignerValidator
from haiji.llm.base import LlmClient

logger = logging.getLogger(__name__)


class Designer:
    """
    Designer 门面类。

    封装 Agent 设计的完整三步流程：
    1. Generator：LLM 生成 Agent 草稿（DesignDraft）
    2. Validator：结构性校验草稿
    3. Registrar：动态构造并注册 Agent 类

    用户只需提供 LLM 客户端并调用 design()，框架自动完成后续所有操作。

    示例::

        designer = Designer(llm_client=my_client)

        # 完整流程
        result = await designer.design(
            description="一个懂投资的朋友，说话直接",
            preferred_mode="react",
        )

        if result.ok:
            agent = designer.get_agent(result.agent_code)
            await agent.stream_chat(...)
    """

    def __init__(self, llm_client: LlmClient) -> None:
        """
        初始化 Designer。

        Args:
            llm_client: LLM 客户端，需实现 LlmClient 抽象接口。
        """
        self._generator = DesignerGenerator(llm_client)
        self._validator = DesignerValidator()
        self._registrar = DesignerRegistrar()

    async def design(
        self,
        description: str,
        rag: Optional[Any] = None,
        rag_config: Optional[Any] = None,
        preferred_mode: Optional[str] = None,
    ) -> DesignResult:
        """
        执行完整的 Agent 设计流程。

        步骤：
        1. 构造 DesignRequest
        2. 调用 Generator 生成草稿
        3. 调用 Validator 校验草稿
        4. 若校验失败，返回 DesignResult(ok=False, errors=...)
        5. 若校验通过，调用 Registrar 注册 Agent
        6. 返回 DesignResult(ok=True, agent_code=..., definition=...)

        Args:
            description:    用户自然语言描述，如"我想要一个懂投资的朋友，说话直接"
            rag:            可选知识库实例（BaseKnowledgeBase）
            rag_config:     可选 RAG 配置（RagConfig）
            preferred_mode: 偏好执行模式（None 时让 LLM 自动判断）

        Returns:
            DesignResult: 包含成功状态、agent_code、definition 或错误列表
        """
        request = DesignRequest(
            description=description,
            rag=rag,
            rag_config=rag_config,
            preferred_mode=preferred_mode,
        )

        # Step 1: 生成草稿
        logger.info("[Designer] 开始设计 Agent：description=%r", description[:50])
        try:
            draft = await self._generator.generate(request)
        except Exception as exc:
            logger.error("[Designer] Generator 失败: %s", exc)
            raise

        logger.info("[Designer] 草稿生成完成：name=%r mode=%r", draft.name, draft.mode)

        # Step 2: 校验草稿
        errors = self._validator.validate(draft)
        if errors:
            logger.warning(
                "[Designer] 草稿校验失败，共 %d 个错误：%s",
                len(errors),
                [(e.field, e.message) for e in errors],
            )
            return DesignResult(ok=False, draft=draft, errors=errors)

        # Step 3: 注册 Agent
        agent_code, definition = self._registrar.register(draft, rag=rag, rag_config=rag_config)

        logger.info(
            "[Designer] Agent 注册成功：code=%s name=%r",
            agent_code,
            draft.name,
        )

        return DesignResult(
            ok=True,
            agent_code=agent_code,
            definition=definition,
            draft=draft,
        )

    def get_agent(self, agent_code: str) -> Optional[BaseAgent]:
        """
        根据 agent_code 获取已注册的 Agent 实例。

        Args:
            agent_code: design() 成功后返回的 agent_code

        Returns:
            BaseAgent 实例，未找到时返回 None
        """
        registry = get_agent_registry()
        cls = registry.get(agent_code)
        if cls is None:
            logger.warning("[Designer] get_agent：agent_code=%r 未找到", agent_code)
            return None
        return cls()
