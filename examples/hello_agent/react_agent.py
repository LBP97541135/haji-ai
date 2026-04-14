"""
examples/hello_agent/react_agent.py - REACT 模式示例

演示 REACT 循环：LLM 调用工具 → 拿结果 → 最终回答的完整流程。

工具：calculate（简单算术）
Agent：MathAgent（REACT 模式）

Usage:
    python3 examples/hello_agent/react_agent.py

    # 指定模型：
    HAIJI_API_KEY=sk-xxx HAIJI_LLM_MODEL=gpt-4o python3 examples/hello_agent/react_agent.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from haiji.agent.base import BaseAgent, agent
from haiji.config import get_config
from haiji.context.definition import ExecutionContext
from haiji.llm.impl.openai import OpenAILlmClient
from haiji.memory.base import SessionMemoryManager
from haiji.sse.base import SseEventEmitter
from haiji.sse.definition import SseEventType
from haiji.tool.base import tool


# ---------------------------------------------------------------------------
# 定义工具
# ---------------------------------------------------------------------------


@tool(description="执行简单算术计算，支持加减乘除。expression 是合法的数学表达式，如 '3 + 5 * 2'")
async def calculate(expression: str) -> str:
    """
    计算数学表达式。

    :param expression: 数学表达式字符串，例如 '3 + 5 * 2'
    """
    try:
        # 安全地计算简单数学表达式（只允许数字和运算符）
        allowed_chars = set("0123456789+-*/()., ")
        if not all(c in allowed_chars for c in expression):
            return f"不支持的表达式：{expression}（只允许数字和 + - * / () 运算符）"
        result = eval(expression)  # noqa: S307 示例用途，仅允许简单算术
        return f"{expression} = {result}"
    except Exception as exc:
        return f"计算失败：{exc}"


# ---------------------------------------------------------------------------
# 定义 Agent
# ---------------------------------------------------------------------------


@agent(
    mode="react",
    tools=[calculate],
    code="MathAgent",
    name="数学助手",
    max_rounds=5,
)
class MathAgent(BaseAgent):
    """
    REACT 模式的数学助手 Agent。

    能够通过调用 calculate 工具完成复杂计算，并给出解释。
    """

    system_prompt = (
        "你是一个数学助手。当用户提出计算问题时，使用 calculate 工具完成计算，"
        "然后用通俗语言解释计算过程和结果。"
    )


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------


async def main() -> None:
    """运行 MathAgent 示例（REACT 模式）。"""
    config = get_config()

    if not config.api_key:
        print(
            "❌ 未检测到 API Key，请先设置环境变量：\n"
            "   export HAIJI_API_KEY=sk-xxx\n",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"🤖 MathAgent 启动（model={config.llm_model}，mode=REACT）\n")
    print("=" * 50)

    llm_client = OpenAILlmClient(config)
    memory = SessionMemoryManager()
    ctx = ExecutionContext.create(session_id="math-session", agent_code="MathAgent")
    agent_instance = MathAgent()

    user_message = "帮我算一下：(3 + 7) * 15 - 42 / 6 的结果是多少？请解释一下计算步骤。"
    print(f"👤 用户：{user_message}\n")
    print("🦐 MathAgent：", end="", flush=True)

    emitter = SseEventEmitter()

    async def run_agent() -> None:
        await agent_instance.stream_chat(
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
                tool_info = f"{event.tool_name}({event.data})"
                print(f"\n\n🔧 [工具调用: {tool_info}]\n", flush=True)
                print("🦐 MathAgent：", end="", flush=True)
            elif event.type == SseEventType.TOOL_RESULT:
                print(f"\n📊 工具结果: {event.data}\n", flush=True)
                print("🦐 MathAgent：", end="", flush=True)
            elif event.type == SseEventType.DONE:
                print("\n")
                print("✅ 完成！")
            elif event.type == SseEventType.ERROR:
                print(f"\n❌ 错误：{event.message}")

    await asyncio.gather(run_agent(), consume_events())


if __name__ == "__main__":
    asyncio.run(main())
