"""
memory - 会话记忆管理

按 session_id 存储和管理多轮对话历史。

示例：
    from haiji.memory import SessionMemoryManager

    memory = SessionMemoryManager(max_history=20)
    memory.add_user_message("sess_1", "你好")
    memory.add_assistant_message("sess_1", "你好！")
    history = memory.get_history("sess_1")
"""

from haiji.memory.base import SessionMemoryManager
from haiji.memory.definition import SessionHistory
from haiji.memory.persistent import PersistentSessionMemoryManager
from haiji.memory.user_memory import (
    UserProfile,
    AgentUserMemory,
    UserMemoryManager,
    get_user_memory_manager,
    init_user_memory_manager,
)

__all__ = [
    "SessionMemoryManager",
    "SessionHistory",
    "PersistentSessionMemoryManager",
    "UserProfile",
    "AgentUserMemory",
    "UserMemoryManager",
    "get_user_memory_manager",
    "init_user_memory_manager",
]
