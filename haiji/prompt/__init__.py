"""
haiji.prompt — Prompt 模板管理模块。

提供 Jinja2 模板的定义、渲染、文件系统加载和全局注册表能力。

Quick start::

    from haiji.prompt import PromptTemplate, PromptRenderer, get_template_registry

    # 定义模板
    tmpl = PromptTemplate(
        name="system",
        template="你是 {{ agent_name }}，请回答用户的问题。",
        variables=["agent_name"],
    )

    # 渲染
    renderer = PromptRenderer()
    result = renderer.render(tmpl, {"agent_name": "哈基虾"})
    print(result.content)  # 你是 哈基虾，请回答用户的问题。

    # 注册表
    registry = get_template_registry()
    registry.register(tmpl)
    found = registry.get("system")
"""

from haiji.prompt.base import (
    PromptLoadError,
    PromptLoader,
    PromptRenderError,
    PromptRenderer,
    TemplateRegistry,
    get_template_registry,
    reset_template_registry,
)
from haiji.prompt.definition import PromptRenderResult, PromptTemplate

__all__ = [
    "PromptTemplate",
    "PromptRenderResult",
    "PromptRenderer",
    "PromptLoader",
    "PromptRenderError",
    "PromptLoadError",
    "TemplateRegistry",
    "get_template_registry",
    "reset_template_registry",
]
