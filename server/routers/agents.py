"""
server/routers/agents.py - Agent 管理路由

GET /api/agents          → 返回所有已注册 Agent 列表
GET /api/agents/{code}   → 返回单个 Agent 详情
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
