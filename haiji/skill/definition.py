"""
skill/definition.py - Skill 数据结构

Skill 是 Tool 的组合 + 使用规则，是 Agent 能力的最小语义单元。
每个 Skill 关联一组 Tool，并携带面向 LLM 的 prompt 片段，
告诉 Agent 在什么场景下使用这些 Tool。
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class XSkillDef(BaseModel):
    """
    Skill 定义数据结构。

    包含 Skill 的元数据信息：唯一标识、名称、描述、关联 Tool codes、
    以及注入给 LLM 的 prompt 片段。

    示例：
        skill_def = XSkillDef(
            code="web_research",
            name="网络调研",
            description="搜索网络获取最新信息",
            tool_codes=["search_web", "fetch_page"],
            prompt_fragment="当用户需要查找信息时，使用 search_web 工具...",
        )
    """

    code: str = Field(..., description="Skill 唯一标识，用于注册表查找")
    name: str = Field(..., description="Skill 人类可读名称")
    description: str = Field(..., description="Skill 的功能描述，用于语义检索")
    tool_codes: list[str] = Field(default_factory=list, description="该 Skill 激活的 Tool codes")
    prompt_fragment: str = Field(
        default="",
        description="注入给 LLM system prompt 的片段，描述何时/如何使用这些 Tool",
    )
    # embedding 向量（可选，用于 SkillSearcher 的向量检索）
    embedding: Optional[list[float]] = Field(
        default=None,
        description="description 的向量表示，由 SkillSearcher 填充",
        exclude=True,  # 不序列化到 JSON，避免冗余
    )

    model_config = {"arbitrary_types_allowed": True}


class SkillEntry(BaseModel):
    """
    完整 Skill 信息（注册表存储单元）。

    definition 存储 Skill 元数据，tool_codes 可直接用于从 ToolRegistry 取 Tool。
    """

    definition: XSkillDef
    # 如果有类级别的 Skill（通过 @skill 装饰器装饰 class），存储类引用
    skill_class: Optional[Any] = Field(default=None, exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    @property
    def code(self) -> str:
        return self.definition.code

    @property
    def tool_codes(self) -> list[str]:
        return self.definition.tool_codes

    @property
    def prompt_fragment(self) -> str:
        return self.definition.prompt_fragment
