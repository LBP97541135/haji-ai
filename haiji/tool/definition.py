"""
tool/definition.py - Tool 数据结构

定义 Tool 的元数据和执行接口。
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Optional
from pydantic import BaseModel
from haiji.context.definition import ToolCallContext
from haiji.llm.definition import FunctionDef, LlmTool


class ToolMeta(BaseModel):
    """Tool 元数据（注册表用）"""
    code: str
    description: str
    parameters_schema: dict[str, Any]  # JSON Schema

    def to_function_def(self) -> FunctionDef:
        return FunctionDef(
            name=self.code,
            description=self.description,
            parameters=self.parameters_schema,
        )

    def to_llm_tool(self) -> LlmTool:
        return LlmTool(function=self.to_function_def())


class XTool(ABC):
    """
    Tool 抽象基类。

    所有 Tool 都必须实现 execute() 方法。
    推荐使用 @tool 装饰器而不是直接继承此类。
    """

    @property
    @abstractmethod
    def tool_code(self) -> str:
        """Tool 的唯一标识"""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool 的描述，会注入给 LLM"""
        ...

    @property
    @abstractmethod
    def parameters_schema(self) -> dict[str, Any]:
        """Tool 的参数 JSON Schema"""
        ...

    @abstractmethod
    async def execute(self, args: dict[str, Any], ctx: ToolCallContext) -> str:
        """
        执行 Tool。

        Args:
            args: 参数字典（已经过校验）
            ctx:  执行上下文

        Returns:
            str: 执行结果（会作为 tool_result 返回给 LLM）
        """
        ...

    def to_meta(self) -> ToolMeta:
        return ToolMeta(
            code=self.tool_code,
            description=self.description,
            parameters_schema=self.parameters_schema,
        )
