"""server/routers/groups.py - 群组管理 + 群聊接口"""
from __future__ import annotations

import asyncio
import json
import uuid
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from haiji.agent.registry import get_agent_registry
from haiji.context.definition import ExecutionContext
from haiji.sse.base import SseEventEmitter
from haiji.sse.definition import SseEventType

from server.deps import get_llm_client, get_memory, get_user_memory
from server.group_store import (
    Group, GroupMember, save_group, load_group, load_all_groups, delete_group
)
from server.group_decision import decide_speakers

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 请求/响应模型 ──────────────────────────────────────────────

class CreateGroupRequest(BaseModel):
    name: str
    description: str = ""
    members: list[dict]  # [{"agent_code": "xxx", "role": "owner/admin/member"}]


class GroupChatRequest(BaseModel):
    group_id: str
    message: str
    user_id: str = "user_001"
    session_id: str = ""  # 留空则用 group_id


class AddMemberRequest(BaseModel):
    agent_code: str
    role: str = "member"


# ── 群组管理 ───────────────────────────────────────────────────

@router.get("/groups")
def list_groups():
    """获取所有群组"""
    groups = load_all_groups()
    return [
        {
            "group_id": g.group_id,
            "name": g.name,
            "description": g.description,
            "member_count": len(g.members),
            "members": [{"agent_code": m.agent_code, "role": m.role, "muted": m.muted} for m in g.members],
        }
        for g in groups
    ]


@router.post("/groups")
def create_group(req: CreateGroupRequest):
    """创建群组"""
    group_id = uuid.uuid4().hex[:8]
    members = [GroupMember(agent_code=m["agent_code"], role=m.get("role", "member"))
               for m in req.members]
    group = Group(group_id=group_id, name=req.name, description=req.description, members=members)
    save_group(group)
    return {"ok": True, "group_id": group_id, "name": req.name}


@router.get("/groups/{group_id}")
def get_group(group_id: str):
    """获取群组详情"""
    g = load_group(group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    return {
        "group_id": g.group_id,
        "name": g.name,
        "description": g.description,
        "members": [{"agent_code": m.agent_code, "role": m.role, "muted": m.muted} for m in g.members],
    }


@router.delete("/groups/{group_id}")
def delete_group_api(group_id: str):
    delete_group(group_id)
    return {"ok": True}


@router.post("/groups/{group_id}/members")
def add_member(group_id: str, req: AddMemberRequest):
    g = load_group(group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    # 去重
    g.members = [m for m in g.members if m.agent_code != req.agent_code]
    g.members.append(GroupMember(agent_code=req.agent_code, role=req.role))
    save_group(g)
    return {"ok": True}


@router.delete("/groups/{group_id}/members/{agent_code}")
def remove_member(group_id: str, agent_code: str):
    g = load_group(group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    g.members = [m for m in g.members if m.agent_code != agent_code]
    save_group(g)
    return {"ok": True}


class UpdateRoleRequest(BaseModel):
    role: str  # "owner" | "admin" | "member"


class UpdateGroupInfoRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@router.put("/groups/{group_id}/info")
def update_group_info(group_id: str, req: UpdateGroupInfoRequest):
    """更新群基本信息（群名/描述）"""
    from server.group_store import update_group_info as _update
    g = _update(group_id, name=req.name, description=req.description)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    return {"ok": True, "name": g.name, "description": g.description}


@router.put("/groups/{group_id}/members/{agent_code}/role")
def set_member_role(group_id: str, agent_code: str, req: UpdateRoleRequest):
    """修改成员角色（群主权限）"""
    g = load_group(group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    valid_roles = {"owner", "admin", "member"}
    if req.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role: {req.role}")
    g.set_role(agent_code, req.role)  # type: ignore
    save_group(g)
    return {"ok": True, "agent_code": agent_code, "role": req.role}


@router.post("/groups/{group_id}/members/{agent_code}/mute")
def mute_member(group_id: str, agent_code: str):
    """禁言成员（管理员权限）"""
    g = load_group(group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    g.set_muted(agent_code, True)
    save_group(g)
    return {"ok": True, "muted": True}


@router.delete("/groups/{group_id}/members/{agent_code}/mute")
def unmute_member(group_id: str, agent_code: str):
    """解除禁言（管理员权限）"""
    g = load_group(group_id)
    if not g:
        raise HTTPException(status_code=404, detail="Group not found")
    g.set_muted(agent_code, False)
    save_group(g)
    return {"ok": True, "muted": False}


# ── 群聊（核心）────────────────────────────────────────────────

async def _group_stream(req: GroupChatRequest) -> AsyncGenerator[str, None]:
    """
    群聊 SSE 流：
    1. 决策哪些 Agent 发言
    2. 按顺序让每个 Agent 流式生成消息
    每个 SSE event 带有 agent_code 标识
    """
    g = load_group(req.group_id)
    if not g:
        yield f"data: {json.dumps({'type': 'error', 'content': 'Group not found'})}\n\n"
        return

    session_id = req.session_id or req.group_id
    llm = get_llm_client()
    memory = get_memory()
    user_mem = get_user_memory()
    registry = get_agent_registry()

    # 判断发送者是否是管理员（群聊里 user 没有 agent 身份，所以只检查 @all 时用）
    sender_is_admin = True  # 暂时默认用户有 @all 权限，后续做用户角色时再收紧

    # 决策发言者
    speakers = await decide_speakers(
        group=g,
        message=req.message,
        sender_user_id=req.user_id,
        sender_is_admin=sender_is_admin,
        llm_client=llm,
    )

    if not speakers:
        yield f"data: {json.dumps({'type': 'system', 'content': '群里没有 Agent 想回复这条消息'})}\n\n"
        return

    # 通知前端：哪些 Agent 要发言
    yield f"data: {json.dumps({'type': 'speakers', 'agent_codes': speakers})}\n\n"

    # 逐个 Agent 生成消息
    for agent_code in speakers:
        cls = registry.get(agent_code)
        if not cls:
            continue

        d = cls._agent_definition

        # 先发 "开始发言" 事件
        yield f"data: {json.dumps({'type': 'agent_start', 'agent_code': agent_code, 'agent_name': d.name})}\n\n"

        agent = cls()

        # 注入用户上下文
        user_ctx = user_mem.build_user_context_prompt(req.user_id, agent_code)
        if user_ctx:
            agent.system_prompt = (agent.system_prompt or "") + (
                f"\n\n---\n{user_ctx}\n"
                f"[这是群聊，群名：{g.name}，"
                f"其他成员：{', '.join(c for c in g.get_all_codes() if c != agent_code)}]"
            )

        ctx = ExecutionContext.create(
            session_id=session_id,
            agent_code=agent_code,
            user_id=req.user_id,
        )

        emitter = SseEventEmitter()
        agent_task = asyncio.create_task(
            agent.stream_chat(req.message, ctx, emitter, memory, llm_client=llm)
        )

        async for event in emitter.events():
            if event.type == SseEventType.TOKEN:
                data = json.dumps({
                    "type": "token",
                    "agent_code": agent_code,
                    "content": event.message or "",
                })
            elif event.type == SseEventType.DONE:
                data = json.dumps({
                    "type": "agent_done",
                    "agent_code": agent_code,
                    "content": event.message or "",
                })
            elif event.type == SseEventType.ERROR:
                data = json.dumps({
                    "type": "error",
                    "agent_code": agent_code,
                    "content": event.message or "",
                })
            else:
                continue
            yield f"data: {data}\n\n"

        try:
            await agent_task
        except Exception as e:
            logger.error("[group_stream] %s agent_task 异常: %s", agent_code, e)

        user_mem.increment_message_count(req.user_id, agent_code)

    yield f"data: {json.dumps({'type': 'group_done'})}\n\n"


@router.post("/groups/{group_id}/chat/stream")
async def group_chat_stream(group_id: str, req: GroupChatRequest):
    """群聊 SSE 流式接口"""
    req.group_id = group_id
    return StreamingResponse(
        _group_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/groups/{group_id}/chat")
async def group_chat(group_id: str, req: GroupChatRequest):
    """群聊非流式接口：收集所有回复后返回"""
    req.group_id = group_id
    results = []
    async for chunk in _group_stream(req):
        if chunk.startswith("data: "):
            try:
                event = json.loads(chunk[6:])
                if event.get("type") == "agent_done":
                    import re as _re
                    content = _re.sub(r"<think>[\s\S]*?</think>", "", event.get("content", "")).strip()
                    results.append({
                        "agent_code": event["agent_code"],
                        "content": content,
                    })
            except Exception:
                pass
    return {"group_id": group_id, "replies": results}
