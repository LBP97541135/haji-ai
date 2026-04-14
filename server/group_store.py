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


@dataclass
class Group:
    group_id: str
    name: str
    description: str = ""
    members: list[GroupMember] = field(default_factory=list)   # Agent 成员列表
    # 注意：消息历史存在 SessionMemoryManager 里，key = group_id

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
        "members": [{"agent_code": m.agent_code, "role": m.role} for m in group.members],
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
