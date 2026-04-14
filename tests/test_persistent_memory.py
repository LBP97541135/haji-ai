"""tests/test_persistent_memory.py - 持久化 Memory 测试"""
import pytest
from pathlib import Path
from haiji.memory.persistent import PersistentSessionMemoryManager


def test_save_and_load(tmp_path):
    """写入后重新加载，历史应该恢复"""
    m1 = PersistentSessionMemoryManager(tmp_path)
    m1.add_user_message("sess_1", "你好")
    m1.add_assistant_message("sess_1", "你好！有什么可以帮你的？")

    m2 = PersistentSessionMemoryManager(tmp_path)
    history = m2.get_history("sess_1")
    assert len(history) == 2
    assert history[0].content == "你好"
    assert history[1].content == "你好！有什么可以帮你的？"


def test_multiple_sessions(tmp_path):
    """多个会话各自持久化"""
    m = PersistentSessionMemoryManager(tmp_path)
    m.add_user_message("sess_a", "消息A")
    m.add_user_message("sess_b", "消息B")

    m2 = PersistentSessionMemoryManager(tmp_path)
    assert len(m2.get_history("sess_a")) == 1
    assert len(m2.get_history("sess_b")) == 1
    assert m2.get_history("sess_a")[0].content == "消息A"


def test_clear_deletes_file(tmp_path):
    """clear() 后对应文件应该消失"""
    m = PersistentSessionMemoryManager(tmp_path)
    m.add_user_message("sess_c", "测试")
    assert (tmp_path / "sess_c.json").exists()

    m.clear("sess_c")
    assert not (tmp_path / "sess_c.json").exists()

    # 重新加载后该 session 为空
    m2 = PersistentSessionMemoryManager(tmp_path)
    assert m2.get_history("sess_c") == []


def test_special_session_id(tmp_path):
    """带斜杠等特殊字符的 session_id 应该能安全持久化"""
    m = PersistentSessionMemoryManager(tmp_path)
    m.add_user_message("private_haji_assistant_user_001", "hello")

    m2 = PersistentSessionMemoryManager(tmp_path)
    history = m2.get_history("private_haji_assistant_user_001")
    assert len(history) == 1
    assert history[0].content == "hello"


def test_max_history_respected(tmp_path):
    """max_history 裁剪仍然生效"""
    m = PersistentSessionMemoryManager(tmp_path, max_history=3)
    for i in range(5):
        m.add_user_message("sess_d", f"消息{i}")

    history = m.get_history("sess_d")
    assert len(history) <= 3


def test_append_after_load(tmp_path):
    """加载后继续追加消息，文件应该更新"""
    m1 = PersistentSessionMemoryManager(tmp_path)
    m1.add_user_message("sess_e", "第一条")

    m2 = PersistentSessionMemoryManager(tmp_path)
    m2.add_user_message("sess_e", "第二条")

    m3 = PersistentSessionMemoryManager(tmp_path)
    history = m3.get_history("sess_e")
    assert len(history) == 2
    assert history[1].content == "第二条"
