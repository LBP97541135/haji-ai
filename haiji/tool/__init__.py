"""
tool - Tool 层

Tool 是 Agent 可以调用的最小执行单元。
通过 @tool 装饰器注册，框架自动生成 JSON Schema 并注入给 LLM。

示例：
    from haiji.tool import tool, get_tool_registry

    @tool(description="搜索网络信息")
    async def search_web(query: str, max_results: int = 5) -> str:
        '''
        :param query: 搜索关键词
        :param max_results: 最多返回条数
        '''
        return f"搜索到关于 {query} 的结果"

    registry = get_tool_registry()
    t = registry.get("search_web")
"""

from haiji.tool.base import tool, ToolRegistry, get_tool_registry
from haiji.tool.definition import XTool, ToolMeta

__all__ = ["tool", "ToolRegistry", "get_tool_registry", "XTool", "ToolMeta"]
