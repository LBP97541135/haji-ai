"""
server/main.py - haji-ai FastAPI 桥接层入口

启动命令：
    cd /home/node/.openclaw/workspace/haji-ai
    python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8765 --reload
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

# 加载 .env（在 haiji 框架初始化前）
load_dotenv(
    dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"),
    override=False,
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.routers import chat, agents, designer

app = FastAPI(title="haji-ai server", version="0.1.0")


def _register_demo_agents() -> None:
    """启动时注册演示 Agent，让前端有内容可用"""
    from haiji.agent import agent
    from haiji.agent.base import BaseAgent

    @agent(
        mode="direct",
        code="haji_assistant",
        name="哈基助手",
        avatar="🤖",
        bio="通用 AI 助手，有问必答",
        soul="# 性格\n温柔、高效、有帮助。\n# 说话风格\n简洁中文，偶尔用 emoji，回答不超过200字。\n# 禁止\n不涉及政治话题。",
        tags=["通用", "助手"],
    )
    class HajiAssistantAgent(BaseAgent):
        system_prompt = "你是哈基AI框架的通用助手，基于 haji-ai 框架构建。回答简洁友好，不超过200字。"

    @agent(
        mode="react",
        code="haji_coder",
        name="代码助手",
        avatar="💻",
        bio="专注代码，Python/JS 全能",
        soul="# 性格\n严谨、务实、专业。\n# 说话风格\n直接给代码，少废话，必要时加注释。\n# 擅长\nPython、JavaScript、架构设计。",
        tags=["代码", "技术", "开发"],
    )
    class HajiCoderAgent(BaseAgent):
        system_prompt = "你是一个专业的代码助手，擅长 Python 和 JavaScript。直接给出可运行的代码，加必要注释，回答简洁。"


_register_demo_agents()

# CORS 全开（开发阶段）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(chat.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(designer.router, prefix="/api")


@app.get("/health")
def health():
    """健康检查"""
    return {"status": "ok", "version": "0.1.0"}


# 静态文件服务（前端 build 后自动挂载）
from fastapi.staticfiles import StaticFiles

dist_path = os.path.join(os.path.dirname(__file__), "..", "ui", "dist")
if os.path.exists(dist_path):
    app.mount("/", StaticFiles(directory=dist_path, html=True), name="static")
