"""
memory/persistent.py - 持久化会话记忆管理器

继承 SessionMemoryManager，在每次写操作后自动保存到磁盘 JSON。
启动时自动从磁盘恢复所有历史会话。

文件结构：
  persist_dir/
    <session_id>.json   ← 每个会话一个文件

JSON 格式：
  {
    "session_id": "private_haji_assistant_user_001",
    "messages": [
      {"role": "user", "content": "你好"},
      {"role": "assistant", "content": "你好！"}
    ]
  }
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from haiji.memory.base import SessionMemoryManager
from haiji.memory.definition import SessionHistory
from haiji.llm.definition import LlmMessage, MessageRole

logger = logging.getLogger(__name__)

# session_id 合法字符：允许字母、数字、下划线、连字符、点
_SAFE_FILENAME_RE = re.compile(r"[^\w\-.]")


def _safe_filename(session_id: str) -> str:
    """将 session_id 转换为安全文件名（替换非法字符为 _）"""
    return _SAFE_FILENAME_RE.sub("_", session_id)


class PersistentSessionMemoryManager(SessionMemoryManager):
    """
    持久化会话记忆管理器。

    每次写操作后自动保存到磁盘，启动时自动恢复。
    继承 SessionMemoryManager，所有接口完全兼容。

    示例::

        memory = PersistentSessionMemoryManager(Path("workspace/sessions"))
        memory.add_user_message("sess_1", "你好")
        # workspace/sessions/sess_1.json 已自动写入

        # 重启后恢复
        memory2 = PersistentSessionMemoryManager(Path("workspace/sessions"))
        print(memory2.get_history("sess_1"))  # 恢复成功
    """

    def __init__(self, persist_dir: Path, max_history: int = 50) -> None:
        super().__init__(max_history=max_history)
        self._persist_dir = persist_dir
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._load_all()

    # ------------------------------------------------------------------
    # 写操作重写（每次写后自动保存）
    # ------------------------------------------------------------------

    def add_user_message(self, session_id: str, content: str) -> None:
        super().add_user_message(session_id, content)
        self._save(session_id)

    def add_assistant_message(self, session_id: str, content: str) -> None:
        super().add_assistant_message(session_id, content)
        self._save(session_id)

    def add_message(self, session_id: str, message: LlmMessage) -> None:
        super().add_message(session_id, message)
        self._save(session_id)

    def clear(self, session_id: str) -> None:
        super().clear(session_id)
        # 清空后删除对应文件
        path = self._path(session_id)
        if path.exists():
            path.unlink()
            logger.info("[PersistentMemory] 删除会话文件: %s", path)

    def clear_all(self) -> None:
        super().clear_all()
        # 清空后删除所有 session 文件
        for f in self._persist_dir.glob("*.json"):
            f.unlink()
        logger.info("[PersistentMemory] 已清空所有会话文件")

    # ------------------------------------------------------------------
    # 持久化内部方法
    # ------------------------------------------------------------------

    def _path(self, session_id: str) -> Path:
        return self._persist_dir / f"{_safe_filename(session_id)}.json"

    def _save(self, session_id: str) -> None:
        """保存单个会话到磁盘"""
        session = self._sessions.get(session_id)
        if not session:
            return
        path = self._path(session_id)
        try:
            data = {
                "session_id": session_id,
                "messages": [
                    self._msg_to_dict(m)
                    for m in session.messages
                ],
            }
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("[PersistentMemory] 保存失败 session=%s: %s", session_id, e)

    def _load_all(self) -> None:
        """启动时从磁盘加载所有会话"""
        loaded = 0
        for path in self._persist_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                session_id = data["session_id"]
                messages = [self._dict_to_msg(m) for m in data.get("messages", [])]
                session = SessionHistory(session_id=session_id)
                session.messages = messages
                self._sessions[session_id] = session
                loaded += 1
            except Exception as e:
                logger.warning("[PersistentMemory] 加载失败 %s: %s", path, e)
        if loaded:
            logger.info("[PersistentMemory] 恢复 %d 个会话", loaded)

    @staticmethod
    def _msg_to_dict(msg: LlmMessage) -> dict:
        """LlmMessage → JSON dict"""
        d: dict = {"role": msg.role.value if hasattr(msg.role, "value") else str(msg.role)}
        if msg.content is not None:
            d["content"] = msg.content
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in msg.tool_calls
            ]
        if hasattr(msg, "tool_call_id") and msg.tool_call_id:
            d["tool_call_id"] = msg.tool_call_id
        if hasattr(msg, "name") and msg.name:
            d["name"] = msg.name
        return d

    @staticmethod
    def _dict_to_msg(d: dict) -> LlmMessage:
        """JSON dict → LlmMessage"""
        role_str = d.get("role", "user")
        try:
            role = MessageRole(role_str)
        except ValueError:
            role = MessageRole.USER

        content = d.get("content")
        tool_calls_data = d.get("tool_calls")
        tool_call_id = d.get("tool_call_id")
        name = d.get("name")

        if role == MessageRole.USER:
            return LlmMessage.user(content or "")
        elif role == MessageRole.ASSISTANT:
            if tool_calls_data:
                from haiji.llm.definition import ToolCall
                tool_calls = [
                    ToolCall(
                        id=tc["id"],
                        name=tc["function"]["name"],
                        arguments=tc["function"]["arguments"],
                    )
                    for tc in tool_calls_data
                ]
                return LlmMessage.assistant(content, tool_calls=tool_calls)
            return LlmMessage.assistant(content or "")
        elif role == MessageRole.SYSTEM:
            return LlmMessage.system(content or "")
        elif role == MessageRole.TOOL:
            return LlmMessage(
                role=MessageRole.TOOL,
                content=content or "",
                tool_call_id=tool_call_id,
                name=name,
            )
        else:
            return LlmMessage(role=role, content=content or "")
