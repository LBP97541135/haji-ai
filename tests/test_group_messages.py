"""tests/test_group_messages.py - 群聊消息持久化测试"""
import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_append_and_load_messages(tmp_path):
    """测试追加消息后能正确加载"""
    import server.group_store as gs
    gs.STORE_DIR = tmp_path

    from server.group_store import GroupMessage, append_group_message, load_group_messages

    msg1 = GroupMessage(
        group_id="grp_001",
        type="user",
        user_id="user_001",
        content="你好，大家！",
        timestamp="2024-01-01T10:00:00+00:00",
    )
    msg2 = GroupMessage(
        group_id="grp_001",
        type="agent",
        agent_code="haji_assistant",
        agent_name="哈基",
        content="大家好！很高兴在这里！",
        timestamp="2024-01-01T10:00:01+00:00",
    )
    append_group_message(msg1)
    append_group_message(msg2)

    loaded = load_group_messages("grp_001")
    assert len(loaded) == 2
    assert loaded[0].type == "user"
    assert loaded[0].content == "你好，大家！"
    assert loaded[1].type == "agent"
    assert loaded[1].agent_code == "haji_assistant"
    assert loaded[1].content == "大家好！很高兴在这里！"


def test_load_messages_limit(tmp_path):
    """测试 limit 参数只返回最近 N 条消息"""
    import server.group_store as gs
    gs.STORE_DIR = tmp_path

    from server.group_store import GroupMessage, append_group_message, load_group_messages

    # 写入 10 条消息
    for i in range(10):
        append_group_message(GroupMessage(
            group_id="grp_002",
            type="user",
            user_id="user_001",
            content=f"消息 {i}",
            timestamp=f"2024-01-01T10:00:{i:02d}+00:00",
        ))

    # 只取最近 3 条
    loaded = load_group_messages("grp_002", limit=3)
    assert len(loaded) == 3
    # 最后3条应该是消息 7, 8, 9
    assert loaded[0].content == "消息 7"
    assert loaded[1].content == "消息 8"
    assert loaded[2].content == "消息 9"


def test_load_messages_nonexistent_group(tmp_path):
    """测试加载不存在的群组消息时返回空列表"""
    import server.group_store as gs
    gs.STORE_DIR = tmp_path

    from server.group_store import load_group_messages

    result = load_group_messages("nonexistent_group")
    assert result == []


def test_append_multiple_groups(tmp_path):
    """测试多个群组的消息互不影响"""
    import server.group_store as gs
    gs.STORE_DIR = tmp_path

    from server.group_store import GroupMessage, append_group_message, load_group_messages

    append_group_message(GroupMessage(
        group_id="grp_a",
        type="user",
        content="群A的消息",
        user_id="user_001",
        timestamp="2024-01-01T10:00:00+00:00",
    ))
    append_group_message(GroupMessage(
        group_id="grp_b",
        type="agent",
        agent_code="haji",
        content="群B的消息",
        timestamp="2024-01-01T10:00:01+00:00",
    ))

    msgs_a = load_group_messages("grp_a")
    msgs_b = load_group_messages("grp_b")

    assert len(msgs_a) == 1
    assert msgs_a[0].content == "群A的消息"
    assert len(msgs_b) == 1
    assert msgs_b[0].content == "群B的消息"
