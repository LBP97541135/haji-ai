"""server/routers/users.py - 用户画像接口"""
from fastapi import APIRouter
from server.deps import get_user_memory

router = APIRouter()


@router.get("/users/{user_id}/profile")
def get_user_profile(user_id: str):
    """获取 AI 对该用户的画像记忆"""
    mgr = get_user_memory()
    p = mgr.get_profile(user_id)
    return {
        "user_id": p.user_id,
        "display_name": p.display_name,
        "facts": p.facts,
        "preferences": p.preferences,
        "last_seen_agent": p.last_seen_agent,
        "message_count": p.message_count,
    }


@router.post("/users/{user_id}/profile/facts")
def add_user_fact(user_id: str, body: dict):
    """手动添加用户事实"""
    fact = body.get("fact", "").strip()
    if not fact:
        return {"ok": False, "error": "fact is required"}
    mgr = get_user_memory()
    mgr.add_fact(user_id, fact)
    return {"ok": True}


@router.put("/users/{user_id}/profile/name")
def set_display_name(user_id: str, body: dict):
    """设置用户昵称"""
    name = body.get("name", "").strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    mgr = get_user_memory()
    mgr.update_profile(user_id, display_name=name)
    return {"ok": True}
