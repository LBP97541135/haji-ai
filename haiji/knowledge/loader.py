"""
knowledge/loader.py - 文档加载器

提供：
- KnowledgeLoader：从纯文本或文件系统加载 KnowledgeDocument
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional, Union

from haiji.knowledge.definition import KnowledgeDocument

logger = logging.getLogger(__name__)

# 支持的文件后缀
_SUPPORTED_SUFFIXES = {".txt", ".md"}


class KnowledgeLoaderError(Exception):
    """KnowledgeLoader 异常基类。"""


class UnsupportedFileTypeError(KnowledgeLoaderError):
    """不支持的文件类型。"""


class KnowledgeLoader:
    """
    知识文档加载器，支持从纯文本和文件系统加载。

    Example:
        >>> loader = KnowledgeLoader()
        >>> doc = await loader.load_text("hello world", source="readme")
        >>> doc2 = await loader.load_file("/path/to/file.md")
    """

    async def load_text(
        self,
        content: str,
        source: str = "inline",
        metadata: Optional[dict] = None,
        doc_id: Optional[str] = None,
    ) -> KnowledgeDocument:
        """
        从纯文本创建 KnowledgeDocument。

        Args:
            content: 文档文本内容
            source: 来源标识，默认 "inline"
            metadata: 附加元数据，None 时使用空字典
            doc_id: 文档 ID，None 时自动生成 UUID

        Returns:
            KnowledgeDocument: 创建的文档（chunks 为空，需经 TextChunker 填充）
        """
        return KnowledgeDocument(
            doc_id=doc_id or str(uuid.uuid4()),
            source=source,
            content=content,
            metadata=metadata or {},
        )

    async def load_file(
        self,
        path: Union[str, Path],
        metadata: Optional[dict] = None,
        doc_id: Optional[str] = None,
    ) -> KnowledgeDocument:
        """
        从文件系统加载文档（支持 .txt / .md）。

        文件读取通过 asyncio.run_in_executor 异步化，不阻塞事件循环。

        Args:
            path: 文件路径
            metadata: 附加元数据，None 时自动填充 {"file_path": str(path)}
            doc_id: 文档 ID，None 时自动生成 UUID

        Returns:
            KnowledgeDocument: 加载的文档

        Raises:
            UnsupportedFileTypeError: 文件类型不受支持（非 .txt / .md）
            FileNotFoundError: 文件不存在
            KnowledgeLoaderError: 文件读取失败
        """
        file_path = Path(path)
        suffix = file_path.suffix.lower()

        if suffix not in _SUPPORTED_SUFFIXES:
            raise UnsupportedFileTypeError(
                f"不支持的文件类型：{suffix}，仅支持 {_SUPPORTED_SUFFIXES}"
            )

        logger.info("KnowledgeLoader.load_file: path=%s", file_path)

        loop = asyncio.get_event_loop()
        try:
            content = await loop.run_in_executor(None, file_path.read_text, "utf-8")
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise KnowledgeLoaderError(f"读取文件失败：{file_path}") from exc

        meta = metadata if metadata is not None else {"file_path": str(file_path)}

        return KnowledgeDocument(
            doc_id=doc_id or str(uuid.uuid4()),
            source=str(file_path),
            content=content,
            metadata=meta,
        )
