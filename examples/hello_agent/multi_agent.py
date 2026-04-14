"""
examples/hello_agent/multi_agent.py - Multi-Agent 互调示例

演示：
1. MainAgent（REACT 模式）将 SubAgent 作为 tool 调用
2. 防循环检测：在 call_stack 里预置帧，调用时应 emit error

Usage:
    python3 examples/hello_agent/multi_agent.py

    # 指定模型：
    HAIJI_API_KEY=sk-xxx HAIJI_LLM_MODEL=gpt-4o python3 examples/hello_agent/multi_agent.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from haiji.agent.base import BaseAgent, agent
from haiji.agent.definition import AgentCallFrame
from haiji.config import get_config
from haiji.context.definition import ExecutionContext
from haiji.llm.impl.openai import OpenAILlmClient
from haiji.memory.base import SessionMemoryManager
from haiji.sse.base import SseEventEmitter
from haiji.sse.definition import SseEventType


# ---------------------------------------------------------------------------
# 定义子 Agent
# ---------------------------------------------------------------------------


@agent(
    mode="direct",
    code="SubAgent",
    name="翻译助手",
    max_rounds=3,
)
class SubAgent(BaseAgent):
    """
    子 Agent：DIRECT 模式，接收消息并将其翻译为英文。
    被 MainAgent 作为 tool 调用。
    """

    system_prompt = "你是一个翻译助手。将用户发送的中文内容翻译为英文，只输出翻译结果，不要解释。"


# ---------------------------------------------------------------------------
# 定义主 Agent
# ---------------------------------------------------------------------------


@agent(
    mode="react",
    tools=["SubAgent"],  # 将 SubAgent 的 code 注册为 tool
    code="MainAgent",
    name="主控助手",
    max_rounds=5,
)
class MainAgent(BaseAgent):
    """
    主 Agent：REACT 模式，识别用户需求后调用 SubAgent 翻译内容。
    """

    system_prompt = (
        "你是一个智能助手，有一个翻译子助手可以调用（tool name: SubAgent）。"
        "当用户需要翻译时，调用 SubAgent 完成翻译并返回结果。"
        "SubAgent 接收参数 message（待翻译的文本）。"
    )


# ---------------------------------------------------------------------------
# 示例 1：正常 Multi-Agent 互调
# ---------------------------------------------------------------------------


async def demo_normal_multi_agent(llm_client: object) -> None:
    """演示正常的 Multi-Agent 互调流程。"""
    print("\n" + "=" * 50)
    print("🔗 示例 1：MainAgent → SubAgent 正常互调")
    print("=" * 50)

    config = get_config()
    memory = SessionMemoryManager()
    ctx = ExecutionContext.create(session_id="multi-session-1", agent_code="MainAgent")
    main_agent = MainAgent()

    user_message = "帮我把这句话翻译成英文：'春天来了，万物复苏。'"
    print(f"👤 用户：{user_message}\n")
    print("🦐 MainAgent：", end="", flush=True)

    emitter = SseEventEmitter()

    async def run_agent() -> None:
        await main_agent.stream_chat(
            user_message=user_message,
            ctx=ctx,
            emitter=emitter,
            memory=memory,
            llm_client=llm_client,
        )

    async def consume_events() -> None:
        async for event in emitter.events():
            if event.type == SseEventType.TOKEN and event.message:
                print(event.message, end="", flush=True)
            elif event.type == SseEventType.TOOL_CALL:
                print(f"\n\n🔧 [调用子 Agent: {event.tool_name}]\n", flush=True)
                print("🦐 MainAgent（等待子 Agent 结果）：", flush=True)
            elif event.type == SseEventType.TOOL_RESULT:
                print(f"📊 子 Agent 返回: {event.data}\n", flush=True)
                print("🦐 MainAgent：", end="", flush=True)
            elif event.type == SseEventType.DONE:
                print("\n")
                print("✅ 正常互调完成！")
            elif event.type == SseEventType.ERROR:
                print(f"\n❌ 错误：{event.message}")

    await asyncio.gather(run_agent(), consume_events())


# ---------------------------------------------------------------------------
# 示例 2：防循环检测
# ---------------------------------------------------------------------------


async def demo_circular_detection(llm_client: object) -> None:
    """演示防循环检测：预置 call_stack，让 MainAgent 调用自己时被拦截。"""
    print("\n" + "=" * 50)
    print("🔒 示例 2：防循环检测验证")
    print("=" * 50)
    print("预置 call_stack 中已包含 MainAgent，模拟循环调用场景\n")

    from unittest.mock import AsyncMock, MagicMock
    from haiji.llm.definition import LlmResponse, ToolCall

    # 构造一个让 MainAgent 调用"自己"的 LLM 响应，触发防循环
    circular_tool_call = ToolCall(
        id="call-circular-001",
        name="MainAgent",  # 尝试调用 MainAgent 自己
        arguments=json.dumps({"message": "帮我翻译这句话"}),
    )
    mock_llm = MagicMock()
    # 第一次返回 tool_call（循环调用），之后返回正常响应
    mock_llm.chat_with_tools = AsyncMock(
        return_value=LlmResponse(
            content=None,
            tool_calls=[circular_tool_call],
        )
    )

    async def _stream_gen(*args, **kwargs):
        for token in ["检测到循环，已中止。"]:
            yield token

    mock_llm.stream_chat = _stream_gen

    memory = SessionMemoryManager()
    ctx = ExecutionContext.create(session_id="circular-test", agent_code="MainAgent")
    main_agent = MainAgent()

    # 预置调用栈：模拟 MainAgent 已在栈中（即将调用自己）
    prefilled_call_stack = [
        AgentCallFrame(agent_code="MainAgent", session_id="circular-test"),
    ]

    emitter = SseEventEmitter()

    async def run_agent() -> None:
        await main_agent.stream_chat(
            user_message="请调用自己（触发循环检测）",
            ctx=ctx,
            emitter=emitter,
            memory=memory,
            llm_client=mock_llm,
            call_stack=prefilled_call_stack,
        )

    events_collected = []

    async def consume_events() -> None:
        async for event in emitter.events():
            events_collected.append(event)
            if event.type == SseEventType.ERROR:
                print(f"🔒 循环检测触发，错误已捕获：{event.message[:80]}...")
            elif event.type == SseEventType.DONE:
                print(f"✅ 执行完成（工具调用被防循环拦截后，继续执行）")

    await asyncio.gather(run_agent(), consume_events())

    # 验证结果
    error_events = [e for e in events_collected if e.type == SseEventType.ERROR]
    if error_events:
        print(f"\n✅ 防循环检测成功！共捕获 {len(error_events)} 个 error 事件")
    else:
        print("\n⚠️  注意：未检测到错误事件（可能 LLM 在工具调用失败后改为直接回答）")


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------


async def main() -> None:
    """运行 Multi-Agent 示例。"""
    config = get_config()

    print(f"🤖 Multi-Agent 示例启动（model={config.llm_model}）\n")

    if not config.api_key:
        print(
            "❌ 未检测到 API Key，请先设置环境变量：\n"
            "   export HAIJI_API_KEY=sk-xxx\n"
            "\n"
            "示例 2（防循环检测）不依赖真实 LLM，将自动运行。\n",
            file=sys.stderr,
        )
        # 示例 1 需要真实 LLM，跳过；示例 2 使用 mock，可以运行
        await demo_circular_detection(llm_client=None)
        return

    llm_client = OpenAILlmClient(config)

    # 示例 1：正常互调
    await demo_normal_multi_agent(llm_client)

    # 示例 2：防循环检测（使用 mock，不依赖真实 LLM）
    await demo_circular_detection(llm_client)

    print("\n🎉 Multi-Agent 示例全部运行完成！")


if __name__ == "__main__":
    asyncio.run(main())
