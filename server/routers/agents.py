"""
server/routers/agents.py - Agent 管理路由

GET /api/agents                  → 返回所有已注册 Agent 列表
GET /api/agents/{code}           → 返回单个 Agent 详情
GET /api/agents/{code}/greeting  → 返回 Agent 首次欢迎语
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from haiji.agent.registry import get_agent_registry
from server.models import AgentSummary, AgentDetail

router = APIRouter()


@router.get("/agents", response_model=list[AgentSummary])
def list_agents():
    """返回所有已注册 Agent 的摘要列表"""
    registry = get_agent_registry()
    result = []
    for code, cls in registry.all().items():
        definition = cls._agent_definition
        result.append(AgentSummary(
            code=definition.code,
            name=definition.name,
            avatar=definition.avatar,
            bio=definition.bio,
            tags=definition.tags,
            mode=definition.mode.value,
        ))
    return result


@router.delete("/agents/{code}")
def delete_agent_api(code: str):
    """删除指定 Agent（从 registry 和持久化文件中移除）"""
    from server.agent_store import delete_agent
    delete_agent(code)
    return {"ok": True, "code": code}


@router.get("/agents/{code}/greeting")
async def get_agent_greeting(code: str, user_id: str = "user_001"):
    """
    返回 Agent 的首次欢迎语（不走 memory，每次生成）。
    前端在聊天历史为空时调用此接口显示欢迎气泡。
    """
    import re
    import asyncio
    from haiji.agent.registry import get_agent_registry
    from server.deps import get_llm_client
    from haiji.context.definition import ExecutionContext
    from haiji.sse.base import SseEventEmitter
    from haiji.sse.definition import SseEventType
    from haiji.memory.base import SessionMemoryManager

    registry = get_agent_registry()
    cls = registry.get(code)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"Agent '{code}' not found")

    # 取 agent 定义
    defn = cls._agent_definition
    name = defn.name
    bio = defn.bio or ""

    llm = get_llm_client()
    agent = cls()

    # 用一个临时空 memory，不污染真实会话
    tmp_memory = SessionMemoryManager()
    ctx = ExecutionContext.create(
        session_id=f"greeting_{code}_{user_id}",
        agent_code=code,
        user_id=user_id,
    )

    emitter = SseEventEmitter()

    greeting_prompt = "请用一两句话做个简短的自我介绍，告诉用户你是谁、你能做什么。不超过50字，语气要符合你的性格。"

    agent_task = asyncio.create_task(
        agent.stream_chat(greeting_prompt, ctx, emitter, tmp_memory, llm_client=llm)
    )

    tokens = []
    async for event in emitter.events():
        if event.type == SseEventType.TOKEN:
            tokens.append(event.message or "")
        elif event.type == SseEventType.DONE:
            break

    await agent_task
    content = "".join(tokens)
    content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()

    return {"greeting": content, "agent_code": code, "agent_name": name}


@router.get("/agents/{code}", response_model=AgentDetail)
def get_agent(code: str):
    """返回单个 Agent 详情"""
    registry = get_agent_registry()
    cls = registry.get(code)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"Agent '{code}' not found")
    d = cls._agent_definition
    return AgentDetail(
        code=d.code,
        name=d.name,
        avatar=d.avatar,
        bio=d.bio,
        soul=d.soul,
        mode=d.mode.value,
        system_prompt=d.system_prompt,
        required_skill_codes=d.required_skill_codes,
        required_tool_codes=d.required_tool_codes,
        max_rounds=d.max_rounds,
        tags=d.tags,
    )
