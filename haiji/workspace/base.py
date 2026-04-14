"""
workspace/base.py - Agent 工作区核心实现

AgentWorkspace 为每个 (agent_code, session_id) 提供隔离的文件系统键值存储。
所有文件操作均异步（asyncio.run_in_executor），目录自动创建。
路径穿越防护：禁止包含 .. 的 key 访问工作区边界之外的文件。
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path

from haiji.workspace.definition import WorkspaceEntry, WorkspaceInfo

logger = logging.getLogger(__name__)

# key 合法字符正则：仅允许字母、数字、下划线、短横线
_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class WorkspaceError(Exception):
    """workspace 模块根异常（继承自 HaijiBaseException 的简化版，避免循环 import）"""
    pass


class WorkspaceKeyNotFoundError(WorkspaceError):
    """
    指定的 key 在工作区中不存在。

    示例::

        raise WorkspaceKeyNotFoundError("key='session_state' 不存在")
    """
    pass


class WorkspacePathTraversalError(WorkspaceError):
    """
    检测到路径穿越攻击（key 包含 .. 或解析后超出工作区边界）。

    示例::

        raise WorkspacePathTraversalError("key='../secret' 包含非法路径")
    """
    pass


class AgentWorkspace:
    """
    Agent 工作区：为单个 (agent_code, session_id) 提供键值持久化存储。

    文件布局::

        {base_dir}/{agent_code}/{session_id}/{key}

    特性：
    - 所有 I/O 异步（asyncio.run_in_executor）
    - 路径穿越防护
    - key 格式校验（仅字母/数字/下划线/短横线）
    - 目录不存在时自动创建

    示例::

        ws = AgentWorkspace("/tmp/workspace", "math_agent", "sess_001")
        await ws.write("state", '{"step": 3}')
        value = await ws.read("state")
    """

    def __init__(self, base_dir: str | Path, agent_code: str, session_id: str) -> None:
        """
        初始化工作区。

        Args:
            base_dir: 所有 Agent 工作区的根目录
            agent_code: Agent 的唯一标识码
            session_id: Session 的唯一 ID
        """
        self._base_path = Path(base_dir).resolve() / agent_code / session_id
        self._agent_code = agent_code
        self._session_id = session_id
        logger.info(
            "AgentWorkspace 初始化 | agent=%s session=%s path=%s",
            agent_code,
            session_id,
            self._base_path,
        )

    # ------------------------------------------------------------------
    # 内部工具方法
    # ------------------------------------------------------------------

    def _validate_key(self, key: str) -> None:
        """校验 key 格式，不合法时抛 ValueError。"""
        if not _KEY_PATTERN.match(key):
            raise ValueError(
                f"key='{key}' 格式非法，只允许字母、数字、下划线和短横线"
            )

    def _safe_path(self, key: str) -> Path:
        """
        返回 key 对应的安全文件路径，同时做路径穿越防护。

        Args:
            key: 已通过 _validate_key 校验的键名

        Returns:
            key 对应的绝对文件路径

        Raises:
            WorkspacePathTraversalError: key 解析后超出工作区边界
        """
        candidate = (self._base_path / key).resolve()
        # 检查解析后的路径必须在 base_path 下
        try:
            candidate.relative_to(self._base_path)
        except ValueError:
            raise WorkspacePathTraversalError(
                f"key='{key}' 的解析路径 '{candidate}' 超出工作区边界 '{self._base_path}'"
            )
        return candidate

    def _resolve_key(self, key: str) -> Path:
        """校验 key 并返回安全路径（组合 _validate_key + _safe_path）。"""
        self._validate_key(key)
        return self._safe_path(key)

    # ------------------------------------------------------------------
    # 目录初始化（lazy）
    # ------------------------------------------------------------------

    def _ensure_dir_sync(self) -> None:
        """同步创建工作区目录（供 run_in_executor 调用）。"""
        self._base_path.mkdir(parents=True, exist_ok=True)

    async def _ensure_dir(self) -> None:
        """异步确保工作区目录存在。"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._ensure_dir_sync)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def write(self, key: str, value: str) -> None:
        """
        写入键值（不存在则创建，存在则覆盖）。

        Args:
            key: 键名（仅允许字母、数字、下划线、短横线）
            value: 要写入的文本内容

        Raises:
            ValueError: key 格式不合法
            WorkspacePathTraversalError: 路径穿越检测失败
        """
        file_path = self._resolve_key(key)
        await self._ensure_dir()

        def _write() -> None:
            file_path.write_text(value, encoding="utf-8")
            logger.debug("workspace.write | key=%s len=%d", key, len(value))

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write)

    async def read(self, key: str) -> str:
        """
        读取键对应的值。

        Args:
            key: 键名

        Returns:
            键对应的文本内容

        Raises:
            ValueError: key 格式不合法
            WorkspaceKeyNotFoundError: key 不存在
            WorkspacePathTraversalError: 路径穿越检测失败
        """
        file_path = self._resolve_key(key)

        def _read() -> str:
            if not file_path.exists():
                raise WorkspaceKeyNotFoundError(
                    f"key='{key}' 在工作区中不存在"
                )
            content = file_path.read_text(encoding="utf-8")
            logger.debug("workspace.read | key=%s len=%d", key, len(content))
            return content

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _read)

    async def delete(self, key: str) -> None:
        """
        删除指定键及其对应文件。

        Args:
            key: 键名

        Raises:
            ValueError: key 格式不合法
            WorkspaceKeyNotFoundError: key 不存在
            WorkspacePathTraversalError: 路径穿越检测失败
        """
        file_path = self._resolve_key(key)

        def _delete() -> None:
            if not file_path.exists():
                raise WorkspaceKeyNotFoundError(
                    f"key='{key}' 在工作区中不存在，无法删除"
                )
            file_path.unlink()
            logger.debug("workspace.delete | key=%s", key)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _delete)

    async def list_keys(self) -> list[str]:
        """
        列出工作区中所有 key（即文件名列表）。

        Returns:
            key 列表，按字典序排序；工作区目录不存在时返回空列表
        """
        def _list() -> list[str]:
            if not self._base_path.exists():
                return []
            keys = sorted(
                f.name
                for f in self._base_path.iterdir()
                if f.is_file()
            )
            logger.debug("workspace.list_keys | count=%d", len(keys))
            return keys

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _list)

    async def exists(self, key: str) -> bool:
        """
        检查 key 是否存在。

        Args:
            key: 键名

        Returns:
            True 表示存在，False 表示不存在

        Raises:
            ValueError: key 格式不合法
            WorkspacePathTraversalError: 路径穿越检测失败
        """
        file_path = self._resolve_key(key)

        def _exists() -> bool:
            return file_path.exists() and file_path.is_file()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _exists)

    async def info(self) -> WorkspaceInfo:
        """
        返回工作区整体信息。

        Returns:
            WorkspaceInfo，包含 agent_code、session_id、base_path、entry_count
        """
        keys = await self.list_keys()
        return WorkspaceInfo(
            agent_code=self._agent_code,
            session_id=self._session_id,
            base_path=str(self._base_path),
            entry_count=len(keys),
        )

    async def get_entry(self, key: str) -> WorkspaceEntry:
        """
        读取 key 并返回完整 WorkspaceEntry（含时间戳）。

        Args:
            key: 键名

        Returns:
            WorkspaceEntry

        Raises:
            WorkspaceKeyNotFoundError: key 不存在
        """
        file_path = self._resolve_key(key)

        def _get() -> WorkspaceEntry:
            if not file_path.exists():
                raise WorkspaceKeyNotFoundError(
                    f"key='{key}' 在工作区中不存在"
                )
            stat = file_path.stat()
            content = file_path.read_text(encoding="utf-8")
            return WorkspaceEntry(
                key=key,
                value=content,
                created_at=datetime.utcfromtimestamp(stat.st_ctime),
                updated_at=datetime.utcfromtimestamp(stat.st_mtime),
            )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _get)
