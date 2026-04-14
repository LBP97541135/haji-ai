"""tests/test_group_store.py - 群组存储测试"""
import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from server.group_store import Group, GroupMember, save_group, load_group, delete_group


def test_save_and_load(tmp_path):
    import server.group_store as gs
    gs.STORE_DIR = tmp_path

    group = Group(
        group_id="test_g1",
        name="测试群",
        members=[
            GroupMember(agent_code="haji_assistant", role="owner"),
            GroupMember(agent_code="haji_coder", role="member"),
        ]
    )
    save_group(group)
    loaded = load_group("test_g1")
    assert loaded is not None
    assert loaded.name == "测试群"
    assert len(loaded.members) == 2
    assert loaded.get_owner() == "haji_assistant"


def test_ordered_codes(tmp_path):
    import server.group_store as gs
    gs.STORE_DIR = tmp_path

    group = Group(
        group_id="test_g2",
        name="顺序测试",
        members=[
            GroupMember(agent_code="member_a", role="member"),
            GroupMember(agent_code="admin_b", role="admin"),
            GroupMember(agent_code="owner_c", role="owner"),
        ]
    )
    save_group(group)
    loaded = load_group("test_g2")
    codes = loaded.ordered_codes()
    assert codes[0] == "owner_c"
    assert codes[1] == "admin_b"
    assert codes[2] == "member_a"


def test_get_admins():
    group = Group(
        group_id="test_g3",
        name="管理员测试",
        members=[
            GroupMember(agent_code="a", role="owner"),
            GroupMember(agent_code="b", role="admin"),
            GroupMember(agent_code="c", role="member"),
        ]
    )
    admins = group.get_admins()
    assert "a" in admins
    assert "b" in admins
    assert "c" not in admins
