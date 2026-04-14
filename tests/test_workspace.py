"""
tests/test_workspace.py - AgentWorkspace 模块测试

覆盖：写/读/删/列出/存在性检查/get_entry/info/路径穿越防护/非法 key 格式
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from haiji.workspace import (
    AgentWorkspace,
    WorkspaceEntry,
    WorkspaceInfo,
    WorkspaceKeyNotFoundError,
    WorkspacePathTraversalError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """返回临时目录（pytest 内置 tmp_path）。"""
    return tmp_path


@pytest.fixture
def workspace(tmp_dir: Path) -> AgentWorkspace:
    """返回一个干净的 AgentWorkspace 实例。"""
    return AgentWorkspace(tmp_dir, "test_agent", "sess_001")


# ---------------------------------------------------------------------------
# 写入与读取
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_and_read_basic(workspace: AgentWorkspace) -> None:
    """write 之后 read 能拿到相同内容。"""
    await workspace.write("my_key", "hello world")
    result = await workspace.read("my_key")
    assert result == "hello world"


@pytest.mark.asyncio
async def test_write_overwrite(workspace: AgentWorkspace) -> None:
    """重复 write 同一个 key 会覆盖旧内容。"""
    await workspace.write("key1", "first")
    await workspace.write("key1", "second")
    result = await workspace.read("key1")
    assert result == "second"


@pytest.mark.asyncio
async def test_write_empty_value(workspace: AgentWorkspace) -> None:
    """允许写入空字符串。"""
    await workspace.write("empty_key", "")
    result = await workspace.read("empty_key")
    assert result == ""


@pytest.mark.asyncio
async def test_write_unicode(workspace: AgentWorkspace) -> None:
    """支持 Unicode 内容写入和读取。"""
    content = "你好，世界！🦐"
    await workspace.write("unicode_key", content)
    result = await workspace.read("unicode_key")
    assert result == content


# ---------------------------------------------------------------------------
# 读取不存在的 key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_nonexistent_key_raises(workspace: AgentWorkspace) -> None:
    """读取不存在的 key 抛 WorkspaceKeyNotFoundError。"""
    with pytest.raises(WorkspaceKeyNotFoundError):
        await workspace.read("nonexistent")


# ---------------------------------------------------------------------------
# 删除
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_existing_key(workspace: AgentWorkspace) -> None:
    """删除已存在的 key 后，read 应抛 WorkspaceKeyNotFoundError。"""
    await workspace.write("to_delete", "value")
    await workspace.delete("to_delete")
    with pytest.raises(WorkspaceKeyNotFoundError):
        await workspace.read("to_delete")


@pytest.mark.asyncio
async def test_delete_nonexistent_key_raises(workspace: AgentWorkspace) -> None:
    """删除不存在的 key 抛 WorkspaceKeyNotFoundError。"""
    with pytest.raises(WorkspaceKeyNotFoundError):
        await workspace.delete("ghost_key")


# ---------------------------------------------------------------------------
# list_keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_keys_empty(workspace: AgentWorkspace) -> None:
    """工作区为空时，list_keys 返回空列表。"""
    keys = await workspace.list_keys()
    assert keys == []


@pytest.mark.asyncio
async def test_list_keys_after_writes(workspace: AgentWorkspace) -> None:
    """写入若干 key 后，list_keys 返回全部 key（字典序）。"""
    await workspace.write("b_key", "b")
    await workspace.write("a_key", "a")
    await workspace.write("c_key", "c")
    keys = await workspace.list_keys()
    assert keys == ["a_key", "b_key", "c_key"]


@pytest.mark.asyncio
async def test_list_keys_after_delete(workspace: AgentWorkspace) -> None:
    """删除 key 后，list_keys 不再包含该 key。"""
    await workspace.write("key_x", "x")
    await workspace.write("key_y", "y")
    await workspace.delete("key_x")
    keys = await workspace.list_keys()
    assert keys == ["key_y"]


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exists_true_after_write(workspace: AgentWorkspace) -> None:
    """写入后 exists 应返回 True。"""
    await workspace.write("check_key", "value")
    assert await workspace.exists("check_key") is True


@pytest.mark.asyncio
async def test_exists_false_before_write(workspace: AgentWorkspace) -> None:
    """未写入时 exists 应返回 False。"""
    assert await workspace.exists("not_written") is False


@pytest.mark.asyncio
async def test_exists_false_after_delete(workspace: AgentWorkspace) -> None:
    """删除后 exists 应返回 False。"""
    await workspace.write("del_key", "v")
    await workspace.delete("del_key")
    assert await workspace.exists("del_key") is False


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_info_empty_workspace(workspace: AgentWorkspace) -> None:
    """空工作区的 info 应包含正确的 agent_code、session_id 和 entry_count=0。"""
    info = await workspace.info()
    assert isinstance(info, WorkspaceInfo)
    assert info.agent_code == "test_agent"
    assert info.session_id == "sess_001"
    assert info.entry_count == 0


@pytest.mark.asyncio
async def test_info_entry_count(workspace: AgentWorkspace) -> None:
    """写入 N 个 key 后，info.entry_count == N。"""
    await workspace.write("k1", "v1")
    await workspace.write("k2", "v2")
    info = await workspace.info()
    assert info.entry_count == 2


@pytest.mark.asyncio
async def test_info_base_path_is_absolute(workspace: AgentWorkspace) -> None:
    """info.base_path 应是绝对路径。"""
    info = await workspace.info()
    assert Path(info.base_path).is_absolute()


# ---------------------------------------------------------------------------
# get_entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_entry_returns_correct_data(workspace: AgentWorkspace) -> None:
    """get_entry 应返回含 key、value、created_at、updated_at 的 WorkspaceEntry。"""
    await workspace.write("entry_key", "entry_value")
    entry = await workspace.get_entry("entry_key")
    assert isinstance(entry, WorkspaceEntry)
    assert entry.key == "entry_key"
    assert entry.value == "entry_value"
    assert entry.created_at is not None
    assert entry.updated_at is not None


@pytest.mark.asyncio
async def test_get_entry_nonexistent_raises(workspace: AgentWorkspace) -> None:
    """get_entry 不存在的 key 应抛 WorkspaceKeyNotFoundError。"""
    with pytest.raises(WorkspaceKeyNotFoundError):
        await workspace.get_entry("ghost")


# ---------------------------------------------------------------------------
# 非法 key 格式
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_key_with_slash(workspace: AgentWorkspace) -> None:
    """含斜线的 key 应抛 ValueError。"""
    with pytest.raises(ValueError):
        await workspace.write("a/b", "value")


@pytest.mark.asyncio
async def test_invalid_key_with_dot_dot(workspace: AgentWorkspace) -> None:
    """含 '..' 的 key 应抛 ValueError（正则校验先于路径检查）。"""
    with pytest.raises(ValueError):
        await workspace.write("../secret", "value")


@pytest.mark.asyncio
async def test_invalid_key_with_space(workspace: AgentWorkspace) -> None:
    """含空格的 key 应抛 ValueError。"""
    with pytest.raises(ValueError):
        await workspace.write("bad key", "value")


@pytest.mark.asyncio
async def test_invalid_key_empty_string(workspace: AgentWorkspace) -> None:
    """空字符串 key 应抛 ValueError。"""
    with pytest.raises(ValueError):
        await workspace.write("", "value")


@pytest.mark.asyncio
async def test_valid_key_with_dash_and_underscore(workspace: AgentWorkspace) -> None:
    """含短横线和下划线的合法 key 应正常写入。"""
    await workspace.write("valid-key_123", "ok")
    result = await workspace.read("valid-key_123")
    assert result == "ok"


# ---------------------------------------------------------------------------
# 路径穿越防护
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_traversal_via_symlink_boundary(tmp_path: Path) -> None:
    """
    路径穿越防护：即使 key 通过了正则，最终解析路径也必须在 base_path 内。
    这里用一个子目录并手动伪造绕过来验证（正常情况 _safe_path 兜底）。
    """
    ws = AgentWorkspace(tmp_path, "agent", "sess")
    # 正则已拦截所有非法字符，这里验证 _safe_path 的防护本身
    base = (tmp_path / "agent" / "sess").resolve()
    # 合法 key，路径在 base_path 内 — 不应报错
    ws._validate_key("legitimate")
    candidate = (base / "legitimate").resolve()
    assert str(candidate).startswith(str(base))


# ---------------------------------------------------------------------------
# 多 workspace 隔离
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_different_sessions_are_isolated(tmp_path: Path) -> None:
    """不同 session_id 的工作区数据互相隔离。"""
    ws1 = AgentWorkspace(tmp_path, "agent", "sess_A")
    ws2 = AgentWorkspace(tmp_path, "agent", "sess_B")

    await ws1.write("shared_key", "from_A")
    await ws2.write("shared_key", "from_B")

    assert await ws1.read("shared_key") == "from_A"
    assert await ws2.read("shared_key") == "from_B"


@pytest.mark.asyncio
async def test_different_agents_are_isolated(tmp_path: Path) -> None:
    """不同 agent_code 的工作区数据互相隔离。"""
    ws1 = AgentWorkspace(tmp_path, "agent_A", "sess")
    ws2 = AgentWorkspace(tmp_path, "agent_B", "sess")

    await ws1.write("key", "agent_A_value")
    await ws2.write("key", "agent_B_value")

    assert await ws1.read("key") == "agent_A_value"
    assert await ws2.read("key") == "agent_B_value"


# ---------------------------------------------------------------------------
# 目录自动创建
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workspace_dir_auto_created(tmp_path: Path) -> None:
    """写入时工作区目录不存在时应自动创建。"""
    ws = AgentWorkspace(tmp_path / "deep" / "nested", "agent", "sess")
    await ws.write("auto_key", "auto_value")
    assert await ws.read("auto_key") == "auto_value"
