"""
group_store.py - 群组数据管理

Group 对象存储群成员、角色、消息历史。
持久化到 workspace/groups/<group_id>.json。
"""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Literal

STORE_DIR = Path(__file__).parent.parent / "workspace" / "groups"

GroupRole = Literal["owner", "admin", "member"]


@dataclass
class GroupMember:
    agent_code: str
    role: GroupRole = "member"
    muted: bool = False


@dataclass
class Group:
    group_id: str
    name: str
    description: str = ""
    members: list[GroupMember] = field(default_factory=list)   # Agent 成员列表
    # 注意：消息历史存在 SessionMemoryManager 里，key = group_id

    def is_muted(self, agent_code: str) -> bool:
        for m in self.members:
            if m.agent_code == agent_code:
                return m.muted
        return False

    def set_muted(self, agent_code: str, muted: bool) -> None:
        for m in self.members:
            if m.agent_code == agent_code:
                m.muted = muted
                return

    def set_role(self, agent_code: str, role: GroupRole) -> None:
        for m in self.members:
            if m.agent_code == agent_code:
                m.role = role
                return

    def get_role(self, agent_code: str) -> GroupRole | None:
        for m in self.members:
            if m.agent_code == agent_code:
                return m.role
        return None

    def get_owner(self) -> str | None:
        for m in self.members:
            if m.role == "owner":
                return m.agent_code
        return None

    def get_admins(self) -> list[str]:
        return [m.agent_code for m in self.members if m.role in ("owner", "admin")]

    def get_all_codes(self) -> list[str]:
        return [m.agent_code for m in self.members]

    def ordered_codes(self) -> list[str]:
        """按角色排序：owner → admin → member"""
        order = {"owner": 0, "admin": 1, "member": 2}
        sorted_members = sorted(self.members, key=lambda m: order.get(m.role, 2))
        return [m.agent_code for m in sorted_members]


def save_group(group: Group) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    path = STORE_DIR / f"{group.group_id}.json"
    data = {
        "group_id": group.group_id,
        "name": group.name,
        "description": group.description,
        "members": [{"agent_code": m.agent_code, "role": m.role, "muted": m.muted} for m in group.members],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_group(group_id: str) -> Group | None:
    path = STORE_DIR / f"{group_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    members = [GroupMember(**m) for m in data.get("members", [])]
    return Group(
        group_id=data["group_id"],
        name=data["name"],
        description=data.get("description", ""),
        members=members,
    )


def load_all_groups() -> list[Group]:
    if not STORE_DIR.exists():
        return []
    groups = []
    for path in STORE_DIR.glob("*.json"):
        g = load_group(path.stem)
        if g:
            groups.append(g)
    return groups


def delete_group(group_id: str) -> bool:
    path = STORE_DIR / f"{group_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def update_group_info(group_id: str, name: str | None = None, description: str | None = None) -> Group | None:
    g = load_group(group_id)
    if not g:
        return None
    if name is not None:
        g.name = name
    if description is not None:
        g.description = description
    save_group(g)
    return g


# ── 群聊消息持久化 ────────────────────────────────────────────

import json as _json
from dataclasses import asdict as _asdict


@dataclass
class GroupMessage:
    """群聊消息记录"""
    group_id: str
    type: str          # "user" | "agent" | "system"
    agent_code: str = ""
    agent_name: str = ""
    content: str = ""
    user_id: str = ""
    timestamp: str = ""  # ISO 格式


def _messages_path(group_id: str) -> Path:
    return STORE_DIR / f"{group_id}_messages.jsonl"


def append_group_message(msg: GroupMessage) -> None:
    """追加一条群聊消息到 JSONL 文件"""
    path = _messages_path(msg.group_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(_asdict(msg), ensure_ascii=False) + "\n")


def load_group_messages(group_id: str, limit: int = 100) -> list[GroupMessage]:
    """加载最近 limit 条群聊消息"""
    path = _messages_path(group_id)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    recent = lines[-limit:]
    msgs = []
    for line in recent:
        try:
            d = _json.loads(line)
            msgs.append(GroupMessage(**d))
        except Exception:
            pass
    return msgs
