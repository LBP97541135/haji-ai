"""
server/deps.py - 依赖注入

提供 llm_client、designer、memory 等全局单例。
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path

from haiji.config import get_config
from haiji.llm.impl.openai import OpenAILlmClient
from haiji.agent.registry import get_agent_registry
from haiji.memory.persistent import PersistentSessionMemoryManager
from haiji.memory.user_memory import UserMemoryManager, init_user_memory_manager
from haiji.designer import Designer


@lru_cache
def get_llm_client() -> OpenAILlmClient:
    """获取 LLM 客户端单例"""
    return OpenAILlmClient(get_config())


@lru_cache
def get_designer() -> Designer:
    """获取 Designer 单例"""
    return Designer(get_llm_client())


_sessions_persist_dir = Path(__file__).parent.parent / "workspace" / "sessions"

# 全局 memory（持久化版，重启自动恢复）
_memory: PersistentSessionMemoryManager | None = None


def get_memory() -> PersistentSessionMemoryManager:
    """获取全局 SessionMemoryManager（持久化版）"""
    global _memory
    if _memory is None:
        _memory = PersistentSessionMemoryManager(_sessions_persist_dir)
    return _memory


_user_memory_persist_dir = Path(__file__).parent.parent / "workspace" / "memory"


@lru_cache
def get_user_memory() -> UserMemoryManager:
    """获取用户画像 Memory 管理器单例（持久化到 workspace/memory/）"""
    return init_user_memory_manager(_user_memory_persist_dir)
