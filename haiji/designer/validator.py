"""
designer/validator.py - Agent 草稿校验器

职责：对 DesignDraft 进行结构性校验，返回错误列表。
只做结构性校验（字段非空、值域合法、引用存在），不校验语义内容。

校验规则：
1. name 不为空
2. mode 是合法的 AgentMode 值
3. tool_codes 中每个 code 在 ToolRegistry 里存在
4. skill_codes 中每个 code 在 SkillRegistry 里存在
5. soul 长度不超过 4000 字符（防止 prompt 爆炸）
6. bio 不超过 50 字符
"""

from __future__ import annotations

import logging

from haiji.agent.definition import AgentMode
from haiji.designer.definition import DesignDraft, ValidationError
from haiji.skill.base import get_skill_registry
from haiji.tool.base import get_tool_registry

logger = logging.getLogger(__name__)

# 常量
_MAX_SOUL_LENGTH = 4000
_MAX_BIO_LENGTH = 50


class DesignerValidator:
    """
    Agent 草稿校验器。

    对 DesignDraft 进行结构性校验，返回所有校验错误。
    调用方根据返回列表是否为空来判断草稿是否合法。

    注意：此类不校验 soul 的语义内容，那是 LLM 的职责。

    示例::

        validator = DesignerValidator()
        errors = validator.validate(draft)
        if errors:
            for err in errors:
                print(f"[{err.field}] {err.message}")
    """

    def validate(self, draft: DesignDraft) -> list[ValidationError]:
        """
        校验 DesignDraft，返回所有错误。

        Args:
            draft: 待校验的 Agent 草稿

        Returns:
            list[ValidationError]: 错误列表，为空表示校验通过。
        """
        errors: list[ValidationError] = []

        # 规则 1：name 不为空
        if not draft.name or not draft.name.strip():
            errors.append(ValidationError(field="name", message="name 不能为空"))
            logger.debug("[DesignerValidator] 校验失败：name 为空")

        # 规则 2：mode 是合法的 AgentMode 值
        valid_modes = {m.value for m in AgentMode}
        if draft.mode not in valid_modes:
            errors.append(
                ValidationError(
                    field="mode",
                    message=f"mode '{draft.mode}' 不合法，合法值为：{sorted(valid_modes)}",
                )
            )
            logger.debug("[DesignerValidator] 校验失败：mode=%r 不合法", draft.mode)

        # 规则 3：tool_codes 中每个 code 必须在 ToolRegistry 里存在
        tool_registry = get_tool_registry()
        for code in draft.tool_codes:
            if tool_registry.get(code) is None:
                errors.append(
                    ValidationError(
                        field="tool_codes",
                        message=f"tool_code '{code}' 未在 ToolRegistry 中注册",
                    )
                )
                logger.debug("[DesignerValidator] 校验失败：tool_code=%r 未注册", code)

        # 规则 4：skill_codes 中每个 code 必须在 SkillRegistry 里存在
        skill_registry = get_skill_registry()
        for code in draft.skill_codes:
            if skill_registry.get(code) is None:
                errors.append(
                    ValidationError(
                        field="skill_codes",
                        message=f"skill_code '{code}' 未在 SkillRegistry 中注册",
                    )
                )
                logger.debug("[DesignerValidator] 校验失败：skill_code=%r 未注册", code)

        # 规则 5：soul 长度不超过 4000 字符
        if len(draft.soul) > _MAX_SOUL_LENGTH:
            errors.append(
                ValidationError(
                    field="soul",
                    message=(
                        f"soul 长度 {len(draft.soul)} 超过上限 {_MAX_SOUL_LENGTH} 字符，"
                        f"请精简内容"
                    ),
                )
            )
            logger.debug(
                "[DesignerValidator] 校验失败：soul 长度 %d 超限", len(draft.soul)
            )

        # 规则 6：bio 不超过 50 字符
        if len(draft.bio) > _MAX_BIO_LENGTH:
            errors.append(
                ValidationError(
                    field="bio",
                    message=(
                        f"bio 长度 {len(draft.bio)} 超过上限 {_MAX_BIO_LENGTH} 字符，"
                        f"请精简到 50 字以内"
                    ),
                )
            )
            logger.debug(
                "[DesignerValidator] 校验失败：bio 长度 %d 超限", len(draft.bio)
            )

        if not errors:
            logger.debug("[DesignerValidator] 草稿 '%s' 校验通过", draft.name)

        return errors
