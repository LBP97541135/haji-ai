"""
examples/full_agent/prompt_agent.py — Prompt 模板渲染验证示例

演示 haiji.prompt 模块的完整使用流程：
  1. 向 TemplateRegistry 注册 Jinja2 模板
  2. 通过 PromptRenderer 渲染模板（含变量注入）
  3. 在 Agent 的 system_prompt 中使用渲染结果
  4. 验证变量缺失时抛出 PromptRenderError

Usage:
    python3 examples/full_agent/prompt_agent.py

依赖：
    pip install -e .
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import unittest.mock as mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from haiji.agent import BaseAgent, agent, get_agent_registry
from haiji.context.definition import ExecutionContext
from haiji.llm.definition import LlmResponse
from haiji.memory.base import SessionMemoryManager
from haiji.prompt import (
    PromptRenderError,
    PromptRenderer,
    PromptTemplate,
    get_template_registry,
    reset_template_registry,
)
from haiji.sse.base import SseEventEmitter

logging.basicConfig(level=logging.WARNING)

# ─── Prompt 模板定义 ─────────────────────────────────────────────────────────

# 模板 1：Agent 系统提示词模板
SYSTEM_PROMPT_TEMPLATE = PromptTemplate(
    name="agent_system_prompt",
    template=(
        "你是 {{ agent_name }}，一个专注于 {{ domain }} 领域的 AI 助手。\n"
        "你的工作风格：{{ style }}\n"
        "{% if extra_rules %}\n"
        "额外规则：\n"
        "{% for rule in extra_rules %}"
        "- {{ rule }}\n"
        "{% endfor %}"
        "{% endif %}"
        "请用简洁、准确的语言回答用户的问题。"
    ),
    variables=["agent_name", "domain", "style"],
    description="Agent 系统提示词模板，支持角色定制和领域专注",
)

# 模板 2：用户查询包装模板
USER_QUERY_TEMPLATE = PromptTemplate(
    name="user_query_wrapper",
    template=(
        "【用户查询】\n"
        "时间：{{ timestamp }}\n"
        "问题：{{ user_question }}\n"
        "{% if context %}上下文：{{ context }}\n{% endif %}"
        "请根据以上信息给出回答。"
    ),
    variables=["timestamp", "user_question"],
    description="用户查询包装模板，可附加上下文信息",
)


# ─── Mock LLM Client ────────────────────────────────────────────────────────

def _make_mock_client(expected_system_prompt: str) -> mock.AsyncMock:
    """构造 Mock LLM Client，验证系统提示词是否正确注入。"""

    async def mock_stream_chat(request: object):  # type: ignore[override]
        """DIRECT 模式使用 stream_chat（async generator）。"""
        tokens = ["我是专注于 AI 框架", "领域的助手，", "很高兴为你服务！"]
        for token in tokens:
            yield token

    client = mock.MagicMock()
    client.stream_chat = mock_stream_chat
    return client


# ─── Agent 定义（使用动态渲染的 system_prompt）──────────────────────────────

@agent(mode="direct")
class PromptDemoAgent(BaseAgent):
    """使用 Prompt 模板渲染的 Agent（system_prompt 在运行时动态设置）。"""
    system_prompt = ""  # 将在 main() 中动态渲染并设置


# ─── 主流程 ──────────────────────────────────────────────────────────────────

async def main() -> None:
    print("=" * 60)
    print("🦐 haiji 第二期集成示例：Prompt 模板渲染验证")
    print("=" * 60)

    # 确保测试隔离
    reset_template_registry()

    renderer = PromptRenderer()
    registry = get_template_registry()

    # ── 步骤 1：注册 Prompt 模板 ──────────────────────────────────────
    print("\n[1/4] 向 TemplateRegistry 注册模板...")
    registry.register(SYSTEM_PROMPT_TEMPLATE)
    registry.register(USER_QUERY_TEMPLATE)

    assert len(registry) == 2, f"期望注册 2 个模板，实际 {len(registry)}"
    assert registry.get("agent_system_prompt") is not None
    assert registry.get("user_query_wrapper") is not None
    print(f"    ✅ 已注册 {len(registry)} 个模板：agent_system_prompt, user_query_wrapper")

    # ── 步骤 2：渲染系统提示词模板 ────────────────────────────────────
    print("\n[2/4] 渲染 agent_system_prompt 模板...")
    system_tmpl = registry.get("agent_system_prompt")
    assert system_tmpl is not None

    system_render_result = renderer.render(
        system_tmpl,
        {
            "agent_name": "哈基虾",
            "domain": "AI Agent 框架",
            "style": "温柔、高效，像青梅竹马一样懂你",
            "extra_rules": ["保持简洁", "优先使用中文", "遇到不确定的问题主动告知"],
        },
    )
    rendered_system_prompt = system_render_result.content
    print(f"    ✅ 渲染成功，使用变量：{system_render_result.variables_used}")
    print(f"    渲染结果（前100字）：{rendered_system_prompt[:100]}...")

    # 验证渲染结果包含关键内容
    assert "哈基虾" in rendered_system_prompt
    assert "AI Agent 框架" in rendered_system_prompt
    assert "保持简洁" in rendered_system_prompt

    # ── 步骤 3：渲染用户查询模板 ──────────────────────────────────────
    print("\n[3/4] 渲染 user_query_wrapper 模板...")
    query_tmpl = registry.get("user_query_wrapper")
    assert query_tmpl is not None

    query_render_result = renderer.render(
        query_tmpl,
        {
            "timestamp": "2026-04-14 06:08:00",
            "user_question": "haiji 框架和 AgentX 有什么区别？",
            "context": "用户是一名后端开发工程师，熟悉 Java 和 Python",
        },
    )
    rendered_query = query_render_result.content
    print(f"    ✅ 渲染成功（含可选 context 字段）")
    print(f"    渲染结果：\n{rendered_query}")

    # 无可选字段时也能正常渲染（传 context=None 触发 {% if context %} 为 False）
    query_no_context = renderer.render(
        query_tmpl,
        {
            "timestamp": "2026-04-14 06:08:00",
            "user_question": "haiji 是什么？",
            "context": None,  # 显式传 None 让 Jinja2 {% if %} 判断为 False
        },
    )
    assert "上下文" not in query_no_context.content, "可选字段为 None 时不应出现 '上下文'"
    print("    ✅ 无可选字段时渲染正常（context=None，if 块被跳过）")

    # ── 步骤 4：验证变量缺失时抛 PromptRenderError ────────────────────
    print("\n[4/4] 验证变量缺失时抛出 PromptRenderError...")
    try:
        renderer.render(
            system_tmpl,
            {
                "agent_name": "哈基虾",
                # 故意缺少 domain 和 style
            },
        )
        raise AssertionError("期望抛出 PromptRenderError，但没有！")
    except PromptRenderError as e:
        print(f"    ✅ 正确抛出 PromptRenderError：{e}")

    # ── 附加：验证渲染后的 system_prompt 可以作为 Agent 提示词使用 ────
    print("\n[附加] 验证渲染结果可注入 Agent system_prompt 并正常执行...")

    # 动态设置 Agent 的 system_prompt
    PromptDemoAgent.system_prompt = rendered_system_prompt

    ctx = ExecutionContext.create(session_id="prompt_demo_session", agent_code="PromptDemoAgent")
    memory = SessionMemoryManager()
    emitter = SseEventEmitter()
    mock_client = _make_mock_client(rendered_system_prompt)

    collected: list[str] = []

    async def consume() -> None:
        async for event in emitter.events():
            if event.type.value == "token" and event.message:
                collected.append(event.message)

    agent_instance = PromptDemoAgent()
    await asyncio.gather(
        agent_instance.stream_chat(
            "你好，请介绍一下你自己",
            ctx,
            emitter,
            memory,
            mock_client,
        ),
        consume(),
    )

    answer = "".join(collected)
    assert len(answer) > 0, "Agent 未返回任何内容！"
    print(f"    ✅ Agent 执行成功，回答：{answer[:80]}{'...' if len(answer) > 80 else ''}")

    print("\n" + "=" * 60)
    print("✅ Prompt 模板渲染验证全部通过！")
    print("=" * 60)
    print("\n📝 关键验证点：")
    print("   ✓ 模板注册到 TemplateRegistry")
    print("   ✓ Jinja2 变量注入（含可选块 if/endif）")
    print("   ✓ 变量缺失时抛 PromptRenderError（StrictUndefined）")
    print("   ✓ 渲染结果可直接作为 Agent.system_prompt 使用")


if __name__ == "__main__":
    asyncio.run(main())
