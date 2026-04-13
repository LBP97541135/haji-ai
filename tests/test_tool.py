"""tool 模块单元测试 + 集成测试"""

import pytest
from haiji.tool.base import tool, ToolRegistry, _build_schema_from_func
from haiji.tool.definition import XTool
from haiji.context import ExecutionContext, ToolCallContext


# ==================== 单元测试：Schema 生成 ====================

def test_schema_required_params():
    async def my_func(query: str, limit: int) -> str:
        return ""
    schema = _build_schema_from_func(my_func)
    assert "query" in schema["required"]
    assert "limit" in schema["required"]
    assert schema["properties"]["query"]["type"] == "string"
    assert schema["properties"]["limit"]["type"] == "integer"


def test_schema_optional_params():
    async def my_func(query: str, limit: int = 5) -> str:
        return ""
    schema = _build_schema_from_func(my_func)
    assert "query" in schema["required"]
    assert "limit" not in schema.get("required", [])


def test_schema_skips_ctx_param():
    async def my_func(query: str, ctx: ToolCallContext) -> str:
        return ""
    schema = _build_schema_from_func(my_func)
    assert "ctx" not in schema["properties"]


# ==================== 单元测试：@tool 装饰器 ====================

def test_tool_decorator_registers():
    registry = ToolRegistry()

    @tool(description="测试工具", code="test_register_tool")
    async def my_test_tool(query: str) -> str:
        return f"result: {query}"

    # 从全局 registry 获取
    from haiji.tool import get_tool_registry
    t = get_tool_registry().get("test_register_tool")
    assert t is not None
    assert t.description == "测试工具"


def test_tool_code_defaults_to_func_name():
    @tool(description="默认 code 测试")
    async def default_code_func(x: str) -> str:
        return x

    from haiji.tool import get_tool_registry
    t = get_tool_registry().get("default_code_func")
    assert t is not None


# ==================== 集成测试：Tool 执行 ====================

@pytest.mark.asyncio
async def test_tool_execute():
    @tool(description="加法工具", code="add_numbers")
    async def add(a: int, b: int) -> str:
        return str(a + b)

    from haiji.tool import get_tool_registry
    t = get_tool_registry().get("add_numbers")
    assert t is not None

    ctx = ToolCallContext(session_id="s1", agent_code="a", trace_id="t1")
    result = await t.execute({"a": 3, "b": 4}, ctx)
    assert result == "7"


@pytest.mark.asyncio
async def test_tool_execute_with_ctx():
    @tool(description="带 ctx 的工具", code="ctx_tool")
    async def ctx_aware(query: str, ctx: ToolCallContext) -> str:
        return f"{ctx.agent_code}:{query}"

    from haiji.tool import get_tool_registry
    t = get_tool_registry().get("ctx_tool")
    ctx = ToolCallContext(session_id="s1", agent_code="my_agent", trace_id="t1")
    result = await t.execute({"query": "hello"}, ctx)
    assert result == "my_agent:hello"


def test_tool_to_llm_tool():
    @tool(description="LLM Tool 转换测试", code="llm_tool_test")
    async def llm_func(keyword: str) -> str:
        return keyword

    from haiji.tool import get_tool_registry
    t = get_tool_registry().get("llm_tool_test")
    llm_tool = t.to_meta().to_llm_tool()
    assert llm_tool.function.name == "llm_tool_test"
    assert llm_tool.function.description == "LLM Tool 转换测试"
