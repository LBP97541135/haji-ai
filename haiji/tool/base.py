"""
tool/base.py - Tool 注册表 + @tool 装饰器

提供 @tool 装饰器，自动从函数签名和类型标注生成 JSON Schema，
并注册到全局 ToolRegistry。
"""

from __future__ import annotations
import inspect
import logging
from typing import Any, Callable, Optional, get_type_hints
from functools import wraps

from haiji.tool.definition import XTool, ToolMeta
from haiji.context.definition import ToolCallContext

logger = logging.getLogger(__name__)

# Python 类型 → JSON Schema type 映射
_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _build_schema_from_func(func: Callable) -> dict[str, Any]:
    """从函数签名自动生成 JSON Schema"""
    sig = inspect.signature(func)
    hints = get_type_hints(func)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "ctx", "args"):
            continue

        annotation = hints.get(name, str)
        json_type = _TYPE_MAP.get(annotation, "string")

        prop: dict[str, Any] = {"type": json_type}

        # 从默认值判断是否必填
        if param.default is inspect.Parameter.empty:
            required.append(name)

        # 从 docstring 里提取参数描述（格式：:param name: description）
        doc = inspect.getdoc(func) or ""
        for line in doc.splitlines():
            line = line.strip()
            if line.startswith(f":param {name}:"):
                prop["description"] = line[len(f":param {name}:"):].strip()
                break

        properties[name] = prop

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    return schema


class FunctionTool(XTool):
    """将普通 async 函数包装成 XTool"""

    def __init__(
        self,
        func: Callable,
        code: str,
        description: str,
        schema: dict[str, Any],
    ) -> None:
        self._func = func
        self._code = code
        self._description = description
        self._schema = schema

    @property
    def tool_code(self) -> str:
        return self._code

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return self._schema

    async def execute(self, args: dict[str, Any], ctx: ToolCallContext) -> str:
        sig = inspect.signature(self._func)
        if "ctx" in sig.parameters:
            result = await self._func(ctx=ctx, **args)
        else:
            result = await self._func(**args)
        return str(result)


class ToolRegistry:
    """
    全局 Tool 注册表。

    所有通过 @tool 装饰的函数自动注册到这里。
    Agent 执行时从这里查找 Tool。
    """

    def __init__(self) -> None:
        self._tools: dict[str, XTool] = {}

    def register(self, tool: XTool) -> None:
        code = tool.tool_code
        if code in self._tools:
            logger.warning("[ToolRegistry] tool_code=%s 已存在，将被覆盖", code)
        self._tools[code] = tool
        logger.debug("[ToolRegistry] 注册 tool: %s", code)

    def get(self, code: str) -> Optional[XTool]:
        return self._tools.get(code)

    def all(self) -> list[XTool]:
        return list(self._tools.values())

    def all_codes(self) -> list[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)


# 全局注册表单例
_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """获取全局 ToolRegistry 单例"""
    return _registry


def tool(
    description: str,
    code: Optional[str] = None,
) -> Callable:
    """
    @tool 装饰器，将 async 函数注册为可被 Agent 调用的 Tool。

    自动从函数签名生成 JSON Schema，参数描述从 docstring 的 :param: 中提取。

    Args:
        description: Tool 描述，会注入给 LLM
        code:        Tool 唯一标识，默认使用函数名

    示例：
        @tool(description="搜索网络信息")
        async def search_web(query: str, max_results: int = 5) -> str:
            '''搜索网络
            :param query: 搜索关键词
            :param max_results: 最多返回条数
            '''
            return f"搜索结果: {query}"
    """
    def decorator(func: Callable) -> Callable:
        tool_code = code or func.__name__
        schema = _build_schema_from_func(func)
        ft = FunctionTool(func, tool_code, description, schema)
        _registry.register(ft)

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        wrapper._tool = ft  # type: ignore
        return wrapper

    return decorator
