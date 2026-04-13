"""memory 模块单元测试 + 集成测试"""

import pytest
from haiji.memory import SessionMemoryManager
from haiji.llm.definition import LlmMessage, MessageRole


@pytest.fixture
def memory():
    return SessionMemoryManager(max_history=10)


# ==================== 单元测试 ====================

def test_add_and_get_history(memory):
    memory.add_user_message("sess_1", "你好")
    memory.add_assistant_message("sess_1", "你好！")
    history = memory.get_history("sess_1")
    assert len(history) == 2
    assert history[0].role == MessageRole.USER
    assert history[1].role == MessageRole.ASSISTANT


def test_empty_session_returns_empty_list(memory):
    history = memory.get_history("nonexistent")
    assert history == []


def test_sessions_are_isolated(memory):
    memory.add_user_message("sess_1", "session 1 消息")
    memory.add_user_message("sess_2", "session 2 消息")
    assert len(memory.get_history("sess_1")) == 1
    assert len(memory.get_history("sess_2")) == 1


def test_clear_session(memory):
    memory.add_user_message("sess_1", "你好")
    memory.clear("sess_1")
    assert memory.get_history("sess_1") == []


def test_get_recent(memory):
    for i in range(5):
        memory.add_user_message("sess_1", f"消息{i}")
    recent = memory.get_recent("sess_1", 3)
    assert len(recent) == 3
    assert recent[-1].content == "消息4"


# ==================== 集成测试：最大历史裁剪 ====================

def test_max_history_trims_old_messages():
    memory = SessionMemoryManager(max_history=5)
    for i in range(8):
        memory.add_user_message("sess_1", f"消息{i}")
    history = memory.get_history("sess_1")
    assert len(history) <= 5
    # 最新的消息应该保留
    assert history[-1].content == "消息7"


def test_system_messages_preserved_during_trim():
    memory = SessionMemoryManager(max_history=5)
    memory.add_message("sess_1", LlmMessage.system("系统提示"))
    for i in range(6):
        memory.add_user_message("sess_1", f"消息{i}")
    history = memory.get_history("sess_1")
    # system 消息应该被保留
    assert history[0].role == MessageRole.SYSTEM
    assert history[0].content == "系统提示"


def test_session_count(memory):
    memory.add_user_message("sess_1", "hello")
    memory.add_user_message("sess_2", "world")
    assert memory.session_count() == 2
