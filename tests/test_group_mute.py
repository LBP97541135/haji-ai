"""tests/test_group_mute.py - 禁言功能测试"""
from server.group_store import Group, GroupMember, save_group, load_group
import server.group_store as gs


def test_mute_and_unmute(tmp_path):
    gs.STORE_DIR = tmp_path
    group = Group(
        group_id="mute_test",
        name="禁言测试",
        members=[
            GroupMember(agent_code="a", role="owner"),
            GroupMember(agent_code="b", role="member"),
        ]
    )
    save_group(group)
    loaded = load_group("mute_test")
    assert loaded is not None

    loaded.set_muted("b", True)
    save_group(loaded)

    reloaded = load_group("mute_test")
    assert reloaded is not None
    assert reloaded.is_muted("b") is True
    assert reloaded.is_muted("a") is False

    reloaded.set_muted("b", False)
    save_group(reloaded)
    final = load_group("mute_test")
    assert final is not None
    assert final.is_muted("b") is False


def test_set_role(tmp_path):
    gs.STORE_DIR = tmp_path
    group = Group(
        group_id="role_test",
        name="角色测试",
        members=[
            GroupMember(agent_code="a", role="owner"),
            GroupMember(agent_code="b", role="member"),
        ]
    )
    save_group(group)
    loaded = load_group("role_test")
    assert loaded is not None
    loaded.set_role("b", "admin")
    save_group(loaded)
    reloaded = load_group("role_test")
    assert reloaded is not None
    assert reloaded.get_role("b") == "admin"
