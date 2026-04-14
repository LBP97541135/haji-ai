"""
haiji.workspace - Agent 工作区模块

为每个 (agent_code, session_id) 提供隔离的键值持久化存储，
底层使用文件系统，所有 I/O 操作异步化，内置路径穿越防护。

快速上手::

    from haiji.workspace import AgentWorkspace

    ws = AgentWorkspace("/tmp/workspace", "math_agent", "sess_001")

    await ws.write("state", '{"step": 3}')
    value = await ws.read("state")
    keys = await ws.list_keys()
    info = await ws.info()
"""

from haiji.workspace.base import (
    AgentWorkspace,
    WorkspaceError,
    WorkspaceKeyNotFoundError,
    WorkspacePathTraversalError,
)
from haiji.workspace.definition import WorkspaceEntry, WorkspaceInfo

__all__ = [
    "AgentWorkspace",
    "WorkspaceError",
    "WorkspaceKeyNotFoundError",
    "WorkspacePathTraversalError",
    "WorkspaceEntry",
    "WorkspaceInfo",
]
