"""
memory/base.py - 会话记忆管理器

管理多轮对话历史，按 session_id 隔离。
默认使用内存存储，后续可扩展 Redis 等持久化实现。
"""

from __future__ import annotations
import logging
from typing import Optional
from haiji.llm.definition import LlmMessage, MessageRole
from haiji.memory.definition import SessionHistory

logger = logging.getLogger(__name__)


class SessionMemoryManager:
    """
    会话记忆管理器（内存实现）。

    按 session_id 存储多轮对话历史，支持最大长度限制。

    示例：
        memory = SessionMemoryManager(max_history=20)
        memory.add_user_message("sess_1", "你好")
        memory.add_assistant_message("sess_1", "你好！有什么可以帮你的？")
        history = memory.get_history("sess_1")
    """

    def __init__(self, max_history: int = 50) -> None:
        """
        Args:
            max_history: 每个会话最多保留的消息条数，超出后自动裁剪最旧的消息
        """
        self._sessions: dict[str, SessionHistory] = {}
        self._max_history = max_history

    def _get_or_create(self, session_id: str) -> SessionHistory:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionHistory(session_id=session_id)
        return self._sessions[session_id]

    def _trim(self, session: SessionHistory) -> None:
        """超出最大长度时裁剪最旧的消息（保留 system 消息）"""
        messages = session.messages
        if len(messages) <= self._max_history:
            return
        # 保留所有 system 消息 + 最新的 (max_history - system_count) 条
        system_msgs = [m for m in messages if m.role == MessageRole.SYSTEM]
        non_system = [m for m in messages if m.role != MessageRole.SYSTEM]
        keep_count = max(0, self._max_history - len(system_msgs))
        session.messages = system_msgs + non_system[-keep_count:]
        logger.debug("[Memory] session=%s 裁剪历史至 %d 条", session.session_id, len(session.messages))

    def add_user_message(self, session_id: str, content: str) -> None:
        """添加用户消息"""
        session = self._get_or_create(session_id)
        session.add(LlmMessage.user(content))
        self._trim(session)

    def add_assistant_message(self, session_id: str, content: str) -> None:
        """添加 Assistant 消息"""
        session = self._get_or_create(session_id)
        session.add(LlmMessage.assistant(content))
        self._trim(session)

    def add_message(self, session_id: str, message: LlmMessage) -> None:
        """添加任意消息（tool_result 等）"""
        session = self._get_or_create(session_id)
        session.add(message)
        self._trim(session)

    def get_history(self, session_id: str) -> list[LlmMessage]:
        """获取完整历史"""
        session = self._sessions.get(session_id)
        return session.messages[:] if session else []

    def get_recent(self, session_id: str, n: int) -> list[LlmMessage]:
        """获取最近 n 条历史"""
        session = self._sessions.get(session_id)
        return session.get_recent(n) if session else []

    def clear(self, session_id: str) -> None:
        """清空某个会话的历史"""
        if session_id in self._sessions:
            self._sessions[session_id].clear()
            logger.info("[Memory] 已清空 session=%s 的历史", session_id)

    def clear_all(self) -> None:
        """清空所有会话历史（主要用于测试）"""
        self._sessions.clear()

    def session_count(self) -> int:
        """当前活跃会话数"""
        return len(self._sessions)
