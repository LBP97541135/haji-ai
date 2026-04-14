"""
Prompt 模板渲染器、加载器和注册表。

- PromptRenderer: 基于 Jinja2 渲染模板，变量缺失时抛异常
- PromptLoader: 从文件系统异步加载 .jinja2 / .txt 模板
- TemplateRegistry: 全局单例注册表，按 name 注册和查找模板
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import jinja2

from haiji.prompt.definition import PromptRenderResult, PromptTemplate

logger = logging.getLogger(__name__)


class PromptRenderError(Exception):
    """Prompt 渲染失败时抛出（通常是模板变量缺失）。"""


class PromptLoadError(Exception):
    """模板文件加载失败时抛出。"""


class PromptRenderer:
    """Jinja2 Prompt 渲染器。

    使用 StrictUndefined：模板中引用的变量若未在 ``variables`` 中提供，
    则立即抛出 :class:`PromptRenderError`，避免静默产生空字符串。

    Example::

        renderer = PromptRenderer()
        tmpl = PromptTemplate(
            name="greeting",
            template="Hello, {{ name }}!",
            variables=["name"],
        )
        result = renderer.render(tmpl, {"name": "祎晗"})
        assert result.content == "Hello, 祎晗!"
    """

    def __init__(self) -> None:
        self._env = jinja2.Environment(
            undefined=jinja2.StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
        )

    def render(self, template: PromptTemplate, variables: dict[str, Any]) -> PromptRenderResult:
        """渲染模板，返回 :class:`PromptRenderResult`。

        Args:
            template: 要渲染的 :class:`PromptTemplate`。
            variables: 渲染变量字典。

        Returns:
            包含渲染结果的 :class:`PromptRenderResult`。

        Raises:
            PromptRenderError: 模板语法错误或变量缺失时抛出。
        """
        try:
            jinja_tmpl = self._env.from_string(template.template)
            content = jinja_tmpl.render(**variables)
        except jinja2.UndefinedError as e:
            raise PromptRenderError(
                f"模板 '{template.name}' 渲染失败：变量未定义 — {e}"
            ) from e
        except jinja2.TemplateSyntaxError as e:
            raise PromptRenderError(
                f"模板 '{template.name}' 语法错误：{e}"
            ) from e

        logger.debug(
            "模板渲染完成: name=%s, content_len=%d",
            template.name,
            len(content),
        )
        return PromptRenderResult(
            content=content,
            template_name=template.name,
            variables_used=dict(variables),
        )


class PromptLoader:
    """从文件系统异步加载 Prompt 模板。

    支持的文件后缀：``.jinja2`` 和 ``.txt``。
    文件名（不含后缀）作为模板的 ``name``。

    Example::

        loader = PromptLoader("/path/to/templates")
        template = await loader.load("system_prompt")
    """

    _SUPPORTED_SUFFIXES = (".jinja2", ".txt")

    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)

    async def load(self, name: str) -> PromptTemplate:
        """按名称异步加载模板文件。

        Args:
            name: 模板名称（不含后缀），对应文件 ``{name}.jinja2`` 或 ``{name}.txt``。

        Returns:
            加载好的 :class:`PromptTemplate`。

        Raises:
            PromptLoadError: 文件不存在或读取失败时抛出。
        """
        file_path = await asyncio.get_event_loop().run_in_executor(
            None, self._find_file, name
        )
        content = await asyncio.get_event_loop().run_in_executor(
            None, self._read_file, file_path
        )
        logger.info("加载模板文件: %s", file_path)
        return PromptTemplate(name=name, template=content)

    async def load_all(self) -> list[PromptTemplate]:
        """异步加载 base_dir 下所有支持后缀的模板文件。

        Returns:
            模板列表。

        Raises:
            PromptLoadError: 目录不存在时抛出。
        """
        if not self._base_dir.is_dir():
            raise PromptLoadError(f"模板目录不存在: {self._base_dir}")

        templates: list[PromptTemplate] = []
        for suffix in self._SUPPORTED_SUFFIXES:
            for file_path in sorted(self._base_dir.glob(f"*{suffix}")):
                name = file_path.stem
                content = await asyncio.get_event_loop().run_in_executor(
                    None, self._read_file, file_path
                )
                templates.append(PromptTemplate(name=name, template=content))
                logger.info("加载模板文件: %s", file_path)

        return templates

    def _find_file(self, name: str) -> Path:
        """在 base_dir 中查找对应文件（同步，在 executor 中运行）。"""
        for suffix in self._SUPPORTED_SUFFIXES:
            candidate = self._base_dir / f"{name}{suffix}"
            if candidate.exists():
                return candidate
        raise PromptLoadError(
            f"模板文件未找到: '{name}' (搜索目录: {self._base_dir}，"
            f"支持后缀: {self._SUPPORTED_SUFFIXES})"
        )

    @staticmethod
    def _read_file(file_path: Path) -> str:
        """读取文件内容（同步，在 executor 中运行）。"""
        try:
            return file_path.read_text(encoding="utf-8")
        except OSError as e:
            raise PromptLoadError(f"读取模板文件失败: {file_path} — {e}") from e


class TemplateRegistry:
    """模板注册表，按 name 存储和查找 :class:`PromptTemplate`。

    通过 :func:`get_template_registry` 获取全局单例。

    Example::

        registry = get_template_registry()
        registry.register(tmpl)
        tmpl = registry.get("system_prompt")
    """

    def __init__(self) -> None:
        self._templates: dict[str, PromptTemplate] = {}

    def register(self, template: PromptTemplate) -> None:
        """注册模板。若同名已存在则覆盖并打 warning。

        Args:
            template: 要注册的 :class:`PromptTemplate`。
        """
        if template.name in self._templates:
            logger.warning("模板已存在，将覆盖: name=%s", template.name)
        self._templates[template.name] = template
        logger.debug("注册模板: name=%s", template.name)

    def register_all(self, templates: list[PromptTemplate]) -> None:
        """批量注册模板。

        Args:
            templates: 模板列表。
        """
        for tmpl in templates:
            self.register(tmpl)

    def get(self, name: str) -> PromptTemplate:
        """按名称查找模板。

        Args:
            name: 模板名称。

        Returns:
            找到的 :class:`PromptTemplate`。

        Raises:
            KeyError: 模板不存在时抛出。
        """
        if name not in self._templates:
            raise KeyError(f"模板未注册: '{name}'（已注册: {list(self._templates.keys())}）")
        return self._templates[name]

    def all_names(self) -> list[str]:
        """返回所有已注册的模板名称列表。"""
        return list(self._templates.keys())

    def clear(self) -> None:
        """清空注册表（主要用于测试）。"""
        self._templates.clear()

    def __len__(self) -> int:
        return len(self._templates)


# ---- 全局单例 ----

_registry: TemplateRegistry | None = None


def get_template_registry() -> TemplateRegistry:
    """获取全局 :class:`TemplateRegistry` 单例。

    Returns:
        全局注册表实例。
    """
    global _registry
    if _registry is None:
        _registry = TemplateRegistry()
    return _registry


def reset_template_registry() -> None:
    """重置全局注册表（仅用于测试）。"""
    global _registry
    _registry = None
