"""
user_memory.py - 用户跨会话画像记忆

同一个 user_id 的画像在所有 Agent、所有会话间共享。
第一期：内存存储（进程内），后续可替换为 SQLite/Redis。
"""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class UserProfile:
    """用户画像：跨 Agent、跨会话的全局记忆"""
    user_id: str
    display_name: str = ""          # 用户昵称（AI 记住的称呼）
    facts: list[str] = field(default_factory=list)   # 关键事实 ["喜欢Python", "正在实习"]
    preferences: dict[str, str] = field(default_factory=dict)  # 偏好 {"语言": "中文", "风格": "简洁"}
    last_seen_agent: str = ""       # 最后对话的 Agent code
    message_count: int = 0          # 总消息数（所有 Agent 累计）


@dataclass
class AgentUserMemory:
    """Agent 对特定用户的专属记忆"""
    agent_code: str
    user_id: str
    notes: list[str] = field(default_factory=list)   # 该 Agent 记住的用户相关笔记
    last_topics: list[str] = field(default_factory=list)  # 最近聊过的话题（最多5条）


class UserMemoryManager:
    """用户 Memory 管理器（单例，整个 server 共享）"""

    def __init__(self, persist_dir: Optional[Path] = None):
        self._profiles: dict[str, UserProfile] = {}
        self._agent_memories: dict[str, dict[str, AgentUserMemory]] = {}
        self._persist_dir = persist_dir
        if persist_dir:
            persist_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

    def get_profile(self, user_id: str) -> UserProfile:
        """获取用户画像，不存在则创建"""
        if user_id not in self._profiles:
            self._profiles[user_id] = UserProfile(user_id=user_id)
        return self._profiles[user_id]

    def update_profile(self, user_id: str, **kwargs) -> None:
        """更新用户画像字段"""
        profile = self.get_profile(user_id)
        for k, v in kwargs.items():
            if hasattr(profile, k):
                setattr(profile, k, v)
        self._save_to_disk()

    def add_fact(self, user_id: str, fact: str) -> None:
        """添加用户事实（去重）"""
        profile = self.get_profile(user_id)
        if fact not in profile.facts:
            profile.facts.append(fact)
            if len(profile.facts) > 20:  # 最多保留20条
                profile.facts = profile.facts[-20:]
        self._save_to_disk()

    def get_agent_memory(self, agent_code: str, user_id: str) -> AgentUserMemory:
        """获取 Agent 对该用户的专属记忆"""
        if agent_code not in self._agent_memories:
            self._agent_memories[agent_code] = {}
        if user_id not in self._agent_memories[agent_code]:
            self._agent_memories[agent_code][user_id] = AgentUserMemory(
                agent_code=agent_code, user_id=user_id
            )
        return self._agent_memories[agent_code][user_id]

    def add_agent_note(self, agent_code: str, user_id: str, note: str) -> None:
        """Agent 记录关于该用户的笔记"""
        mem = self.get_agent_memory(agent_code, user_id)
        if note not in mem.notes:
            mem.notes.append(note)
            if len(mem.notes) > 10:
                mem.notes = mem.notes[-10:]
        self._save_to_disk()

    def increment_message_count(self, user_id: str, agent_code: str) -> None:
        """记录用户发了一条消息"""
        profile = self.get_profile(user_id)
        profile.message_count += 1
        profile.last_seen_agent = agent_code
        self._save_to_disk()

    def build_user_context_prompt(self, user_id: str, agent_code: str) -> str:
        """
        构建注入给 Agent system_prompt 的用户上下文片段。
        """
        profile = self.get_profile(user_id)
        agent_mem = self.get_agent_memory(agent_code, user_id)

        lines = ["[用户上下文]"]
        if profile.display_name:
            lines.append(f"用户称呼: {profile.display_name}")
        else:
            lines.append(f"用户ID: {user_id}")

        if profile.message_count > 0:
            lines.append(f"历史对话总量: {profile.message_count} 条")

        if profile.facts:
            lines.append(f"已知信息: {', '.join(profile.facts)}")

        if profile.preferences:
            prefs = ', '.join(f"{k}={v}" for k, v in profile.preferences.items())
            lines.append(f"用户偏好: {prefs}")

        if agent_mem.notes:
            lines.append(f"我对TA的印象: {', '.join(agent_mem.notes)}")

        if agent_mem.last_topics:
            lines.append(f"最近聊过: {', '.join(agent_mem.last_topics[-3:])}")

        return "\n".join(lines)

    def _save_to_disk(self) -> None:
        if not self._persist_dir:
            return
        try:
            profiles_data = {
                uid: {
                    "user_id": p.user_id,
                    "display_name": p.display_name,
                    "facts": p.facts,
                    "preferences": p.preferences,
                    "last_seen_agent": p.last_seen_agent,
                    "message_count": p.message_count,
                }
                for uid, p in self._profiles.items()
            }
            (self._persist_dir / "profiles.json").write_text(
                json.dumps(profiles_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            agent_mem_data = {
                ac: {
                    uid: {"agent_code": m.agent_code, "user_id": m.user_id,
                          "notes": m.notes, "last_topics": m.last_topics}
                    for uid, m in users.items()
                }
                for ac, users in self._agent_memories.items()
            }
            (self._persist_dir / "agent_memories.json").write_text(
                json.dumps(agent_mem_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            print(f"[UserMemoryManager] 保存失败: {e}")

    def _load_from_disk(self) -> None:
        if not self._persist_dir:
            return
        try:
            profiles_file = self._persist_dir / "profiles.json"
            if profiles_file.exists():
                data = json.loads(profiles_file.read_text(encoding="utf-8"))
                for uid, p in data.items():
                    self._profiles[uid] = UserProfile(**p)

            agent_mem_file = self._persist_dir / "agent_memories.json"
            if agent_mem_file.exists():
                data = json.loads(agent_mem_file.read_text(encoding="utf-8"))
                for ac, users in data.items():
                    self._agent_memories[ac] = {
                        uid: AgentUserMemory(**m) for uid, m in users.items()
                    }
        except Exception as e:
            print(f"[UserMemoryManager] 加载失败: {e}")


_user_memory_manager: UserMemoryManager | None = None


def get_user_memory_manager() -> UserMemoryManager:
    global _user_memory_manager
    if _user_memory_manager is None:
        _user_memory_manager = UserMemoryManager()
    return _user_memory_manager


def init_user_memory_manager(persist_dir: Path) -> UserMemoryManager:
    global _user_memory_manager
    _user_memory_manager = UserMemoryManager(persist_dir=persist_dir)
    return _user_memory_manager
