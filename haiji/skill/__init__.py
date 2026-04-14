"""
skill - Skill 层

Skill 是 Tool 的组合 + 使用规则，是 Agent 能力的最小语义单元。
每个 Skill 关联一组 Tool，并携带面向 LLM 的 prompt 片段，
告诉 Agent 在什么场景下使用这些 Tool。

核心概念：
- XSkillDef：Skill 元数据定义（code、name、description、tool_codes、prompt_fragment）
- SkillEntry：注册表存储单元（definition + skill_class）
- SkillRegistry：全局注册表，@skill 装饰的 Skill 自动注册
- SkillSearcher：向量相似度检索器（相比关键词匹配，语义更准确）
- build_prompt_fragment：将激活的 Skill 列表拼成 system prompt 注入片段

示例::

    from haiji.skill import skill, get_skill_registry, SkillSearcher, build_prompt_fragment
    from haiji.tool import tool

    @tool(description="搜索网络信息")
    async def search_web(query: str) -> str:
        return f"搜索结果：{query}"

    @skill(
        description="搜索网络获取最新信息",
        tools=[search_web],
        prompt_fragment="当用户需要查找信息时，使用 search_web 工具。",
    )
    class WebResearchSkill:
        pass

    registry = get_skill_registry()
    entry = registry.get("WebResearchSkill")
    prompt = build_prompt_fragment([entry])
"""

from haiji.skill.definition import XSkillDef, SkillEntry
from haiji.skill.base import (
    SkillRegistry,
    SkillSearcher,
    get_skill_registry,
    skill,
    build_prompt_fragment,
)

__all__ = [
    "XSkillDef",
    "SkillEntry",
    "SkillRegistry",
    "SkillSearcher",
    "get_skill_registry",
    "skill",
    "build_prompt_fragment",
]
