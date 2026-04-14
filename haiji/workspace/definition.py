"""
workspace/definition.py - Agent 工作区数据结构

定义 WorkspaceEntry 和 WorkspaceInfo，用于描述工作区中的键值条目与整体状态。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class WorkspaceEntry(BaseModel):
    """
    工作区中的单个键值条目。

    每个 key 对应一个持久化文件，value 是文件内容（文本）。

    示例::

        entry = WorkspaceEntry(
            key="session_state",
            value='{"step": 3}',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    """

    key: str
    """键名（仅允许字母、数字、下划线、短横线）"""

    value: str
    """键值（文件文本内容）"""

    created_at: datetime
    """首次写入时间"""

    updated_at: datetime
    """最近更新时间"""


class WorkspaceInfo(BaseModel):
    """
    工作区整体信息。

    示例::

        info = WorkspaceInfo(
            agent_code="math_agent",
            session_id="sess_001",
            base_path="/tmp/workspace/math_agent/sess_001",
            entry_count=3,
        )
    """

    agent_code: str
    """所属 Agent 的 code"""

    session_id: str
    """所属 Session 的 ID"""

    base_path: str
    """工作区根目录绝对路径"""

    entry_count: int
    """当前 key 的数量"""
