"""
examples/hello_agent/hello_agent.py - DIRECT 模式示例

演示最简单的 Agent：接收用户问题，流式输出 LLM 回答，可选调用 get_time 工具。

Usage:
    # 真实调用（需要设置 HAIJI_API_KEY）：
    python3 examples/hello_agent/hello_agent.py

    # 环境变量示例：
    HAIJI_API_KEY=sk-xxx HAIJI_LLM_MODEL=gpt-4o python3 examples/hello_agent/hello_agent.py

    # 使用兼容 OpenAI 协议的国内模型：
    HAIJI_API_KEY=xxx HAIJI_LLM_BASE_URL=https://api.deepseek.com/v1 \\
        HAIJI_LLM_MODEL=deepseek-chat python3 examples/hello_agent/hello_agent.py
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import sys

logging.basicConfig(level=logging.WARNING)  # 示例中只看 WARNING+，不刷满屏 DEBUG

# ── 运行时动态加 sys.path，方便直接 python3 运行（无需 pip install -e .）──
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from haiji.agent.base import BaseAgent, agent
from haiji.config import HaijiConfig, get_config
from haiji.context.definition import ExecutionContext
from haiji.llm.impl.openai import OpenAILlmClient
from haiji.memory.base import SessionMemoryManager
from haiji.sse.base import SseEventEmitter
from haiji.sse.definition import SseEventType
from haiji.tool.base import tool


# ---------------------------------------------------------------------------
# 定义工具
# ---------------------------------------------------------------------------


@tool(description="获取当前日期和时间（北京时间）")
async def get_time() -> str:
    """获取当前时间，返回格式：2026-04-13 20:30:00。"""
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# 定义 Agent
# ---------------------------------------------------------------------------


@agent(
    mode="direct",
    tools=[get_time],
    code="HelloAgent",
    name="你好助手",
    max_rounds=5,
)
class HelloAgent(BaseAgent):
    """最简单的 DIRECT 模式 Agent，回答问题并可查询当前时间。"""

    system_prompt = (
        "你是哈基AI的演示助手，简洁友好。"
        "如果用户问时间相关的问题，使用 get_time 工具查询。"
    )


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------


async def main() -> None:
    """运行 HelloAgent 示例。"""
    config = get_config()

    if not config.api_key:
        print(
            "❌ 未检测到 API Key，请先设置环境变量：\n"
            "   export HAIJI_API_KEY=sk-xxx\n"
            "   export HAIJI_LLM_MODEL=gpt-4o          # 可选，默认 gpt-4o\n"
            "   export HAIJI_LLM_BASE_URL=https://...   # 可选，兼容其他 OpenAI 协议接口\n",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"🤖 HelloAgent 启动（model={config.llm_model}，mode=DIRECT）\n")
    print("=" * 50)

    llm_client = OpenAILlmClient(config)
    memory = SessionMemoryManager()
    ctx = ExecutionContext.create(session_id="demo-session", agent_code="HelloAgent")
    agent_instance = HelloAgent()

    user_message = "现在几点了？顺便介绍一下你自己。"
    print(f"👤 用户：{user_message}\n")
    print("🦐 哈基AI：", end="", flush=True)

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
            elif event.type == SseEventType.DONE:
                print("\n")
                print("✅ 完成！")
            elif event.type == SseEventType.ERROR:
                print(f"\n❌ 错误：{event.message}")

    await asyncio.gather(run_agent(), consume_events())


if __name__ == "__main__":
    asyncio.run(main())
