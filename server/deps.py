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
from haiji.memory.base import SessionMemoryManager
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


# 全局 memory（内存版，重启丢失）
_memory = SessionMemoryManager()


def get_memory() -> SessionMemoryManager:
    """获取全局 SessionMemoryManager"""
    return _memory


_user_memory_persist_dir = Path(__file__).parent.parent / "workspace" / "memory"


@lru_cache
def get_user_memory() -> UserMemoryManager:
    """获取用户画像 Memory 管理器单例（持久化到 workspace/memory/）"""
    return init_user_memory_manager(_user_memory_persist_dir)
