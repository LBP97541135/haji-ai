"""tests/test_user_memory.py - 用户 Memory 测试"""
import pytest
from haiji.memory.user_memory import UserMemoryManager


def test_get_profile_creates_new():
    mgr = UserMemoryManager()
    p = mgr.get_profile("user_001")
    assert p.user_id == "user_001"
    assert p.message_count == 0


def test_add_fact_dedup():
    mgr = UserMemoryManager()
    mgr.add_fact("u1", "喜欢Python")
    mgr.add_fact("u1", "喜欢Python")
    p = mgr.get_profile("u1")
    assert p.facts.count("喜欢Python") == 1


def test_increment_message_count():
    mgr = UserMemoryManager()
    mgr.increment_message_count("u2", "haji_assistant")
    mgr.increment_message_count("u2", "haji_coder")
    p = mgr.get_profile("u2")
    assert p.message_count == 2
    assert p.last_seen_agent == "haji_coder"


def test_build_user_context_prompt():
    mgr = UserMemoryManager()
    mgr.add_fact("u3", "大三学生")
    mgr.add_fact("u3", "正在实习")
    prompt = mgr.build_user_context_prompt("u3", "haji_assistant")
    assert "大三学生" in prompt
    assert "正在实习" in prompt


def test_agent_memory_notes():
    mgr = UserMemoryManager()
    mgr.add_agent_note("haji_assistant", "u4", "用户喜欢简洁回答")
    mem = mgr.get_agent_memory("haji_assistant", "u4")
    assert "用户喜欢简洁回答" in mem.notes


def test_persist_and_load(tmp_path):
    mgr1 = UserMemoryManager(persist_dir=tmp_path)
    mgr1.add_fact("u5", "测试事实")
    mgr1.increment_message_count("u5", "agent_x")
    mgr2 = UserMemoryManager(persist_dir=tmp_path)
    p = mgr2.get_profile("u5")
    assert "测试事实" in p.facts
    assert p.message_count == 1
