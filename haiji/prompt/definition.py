"""
Prompt 模板数据结构定义。

包含 PromptTemplate（Jinja2 模板 + 变量声明）和 PromptRenderResult（渲染结果）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PromptTemplate(BaseModel):
    """Jinja2 Prompt 模板。

    Attributes:
        name: 模板的唯一标识名称，用于注册表查找。
        template: Jinja2 模板内容字符串。
        variables: 模板声明的变量列表（用于文档/校验提示，渲染时由 renderer 校验）。
        description: 可选的模板用途描述。

    Example::

        tmpl = PromptTemplate(
            name="system_prompt",
            template="你是 {{ agent_name }}，请回答以下问题。",
            variables=["agent_name"],
        )
    """

    name: str = Field(..., description="模板唯一标识名称")
    template: str = Field(..., description="Jinja2 模板内容")
    variables: list[str] = Field(default_factory=list, description="声明的变量列表")
    description: str = Field(default="", description="模板用途描述（可选）")


class PromptRenderResult(BaseModel):
    """Prompt 渲染结果。

    Attributes:
        content: 渲染后的最终文本内容。
        template_name: 来源模板的名称。
        variables_used: 渲染时实际使用的变量字典。

    Example::

        result = PromptRenderResult(
            content="你是小明，请回答以下问题。",
            template_name="system_prompt",
            variables_used={"agent_name": "小明"},
        )
    """

    content: str = Field(..., description="渲染后的最终文本内容")
    template_name: str = Field(..., description="来源模板名称")
    variables_used: dict[str, Any] = Field(default_factory=dict, description="渲染时使用的变量")
