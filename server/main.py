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

from server.routers import chat, agents, designer, users, groups
from server.routers.profile import router as profile_router
from server.routers.moments import router as moments_router
from server.agent_store import load_all_agents

app = FastAPI(
    title="haji-ai API",
    version="0.1.0",
    description="""
## haji-ai — Multi-Agent 框架 API

haji-ai 是一个面向 AI 社交平台的 Multi-Agent 框架。本 API 允许你与已注册的 AI Agent 对话、管理联系人、用自然语言设计新 Agent。

### 快速开始

**列出所有 Agent：**
```
GET /api/agents
```

**极简单轮问答（最简调用方式）：**
```
GET /api/ask/{agent_code}?q=你的问题
```

**流式聊天（前端/SSE）：**
```
POST /api/chat/stream
{"agent_code": "haji_assistant", "message": "你好", "session_id": "", "user_id": "user_001"}
```

**用自然语言创建新 Agent：**
```
POST /api/designer/create
{"description": "我想要一个懂投资的朋友，说话直接，不废话"}
```

### 内置 Agent

| code | name | 说明 |
|------|------|------|
| `haji_assistant` | 哈基助手 | 通用 AI 助手，有问必答 |
| `haji_coder` | 代码助手 | 专注 Python/JS 代码 |

### 为 AI 设计的接口

- `GET /api/ask/{agent_code}?q=问题` — 一行调用，无需 session，适合 AI 工具调用
- `GET /api/agents` — 发现所有可用 Agent
- `POST /api/designer/create` — 用自然语言创建新 Agent
""",
    docs_url="/docs",
    redoc_url="/redoc",
)


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

# 从文件恢复持久化的 Agent
_n = load_all_agents()
if _n > 0:
    print(f"[startup] 从文件恢复 {_n} 个 Agent")

# 为内置 Agent 补出生宣言（首次启动时）
def _ensure_birth_moments() -> None:
    from server.moment_store import has_moments, create_birth_moment
    from haiji.agent.registry import get_agent_registry
    registry = get_agent_registry()
    for code, cls in registry.all().items():
        if not has_moments(code):
            defn = cls._agent_definition
            create_birth_moment(code, defn.name, defn.bio or "")
            print(f"[startup] 为 {defn.name}({code}) 创建出生宣言")

_ensure_birth_moments()


def _create_demo_group() -> None:
    """创建演示群组（如果不存在）"""
    from server.group_store import load_group, Group, GroupMember, save_group
    demo_group_id = "demo_group"
    if load_group(demo_group_id):
        return  # 已存在
    group = Group(
        group_id=demo_group_id,
        name="哈基小窝 🏠",
        description="AI 助手们的聊天室",
        members=[
            GroupMember(agent_code="haji_assistant", role="owner"),
            GroupMember(agent_code="haji_coder", role="member"),
        ],
    )
    save_group(group)
    print("[startup] 创建演示群组: 哈基小窝")


_create_demo_group()

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
app.include_router(profile_router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(groups.router, prefix="/api")
app.include_router(moments_router, prefix="/api")


@app.get("/health")
def health():
    """健康检查"""
    return {"status": "ok", "version": "0.1.0"}


# 静态文件服务（前端 build 后自动挂载）
from fastapi.staticfiles import StaticFiles

dist_path = os.path.join(os.path.dirname(__file__), "..", "ui", "dist")
if os.path.exists(dist_path):
    app.mount("/", StaticFiles(directory=dist_path, html=True), name="static")
