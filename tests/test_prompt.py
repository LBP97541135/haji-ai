"""
tests/test_prompt.py — haiji.prompt 模块单元测试。

覆盖：
- PromptTemplate / PromptRenderResult 数据结构
- PromptRenderer 渲染成功、变量缺失、模板语法错误
- PromptLoader 加载文件、文件不存在、目录不存在
- TemplateRegistry 注册、查找、批量注册、覆盖 warning、all_names、clear
- get_template_registry / reset_template_registry 单例行为
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from haiji.prompt import (
    PromptLoadError,
    PromptLoader,
    PromptRenderError,
    PromptRenderResult,
    PromptRenderer,
    PromptTemplate,
    TemplateRegistry,
    get_template_registry,
    reset_template_registry,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_registry():
    """每个测试前后重置全局注册表，避免状态污染。"""
    reset_template_registry()
    yield
    reset_template_registry()


@pytest.fixture()
def renderer() -> PromptRenderer:
    return PromptRenderer()


@pytest.fixture()
def simple_template() -> PromptTemplate:
    return PromptTemplate(
        name="greeting",
        template="Hello, {{ name }}! 你好 {{ name }}。",
        variables=["name"],
    )


@pytest.fixture()
def tmpdir_with_templates(tmp_path: Path) -> Path:
    """在临时目录中创建几个模板文件。"""
    (tmp_path / "hello.jinja2").write_text("Hi {{ who }}!", encoding="utf-8")
    (tmp_path / "plain.txt").write_text("plain text, no vars", encoding="utf-8")
    (tmp_path / "multi.jinja2").write_text("{{ a }} + {{ b }}", encoding="utf-8")
    return tmp_path


# ──────────────────────────────────────────────
# PromptTemplate & PromptRenderResult 数据结构
# ──────────────────────────────────────────────


class TestPromptTemplateModel:
    def test_create_with_required_fields(self):
        tmpl = PromptTemplate(name="t", template="hello")
        assert tmpl.name == "t"
        assert tmpl.template == "hello"
        assert tmpl.variables == []
        assert tmpl.description == ""

    def test_create_with_all_fields(self):
        tmpl = PromptTemplate(
            name="sys",
            template="你是 {{ agent }}",
            variables=["agent"],
            description="系统 prompt",
        )
        assert tmpl.variables == ["agent"]
        assert tmpl.description == "系统 prompt"

    def test_render_result_model(self):
        result = PromptRenderResult(
            content="Hello, 祎晗!",
            template_name="greeting",
            variables_used={"name": "祎晗"},
        )
        assert result.content == "Hello, 祎晗!"
        assert result.template_name == "greeting"
        assert result.variables_used == {"name": "祎晗"}

    def test_render_result_default_variables_used(self):
        result = PromptRenderResult(content="text", template_name="t")
        assert result.variables_used == {}


# ──────────────────────────────────────────────
# PromptRenderer
# ──────────────────────────────────────────────


class TestPromptRenderer:
    def test_render_simple_variable(self, renderer: PromptRenderer, simple_template: PromptTemplate):
        result = renderer.render(simple_template, {"name": "祎晗"})
        assert result.content == "Hello, 祎晗! 你好 祎晗。"
        assert result.template_name == "greeting"
        assert result.variables_used == {"name": "祎晗"}

    def test_render_no_variables(self, renderer: PromptRenderer):
        tmpl = PromptTemplate(name="static", template="固定文本，无变量")
        result = renderer.render(tmpl, {})
        assert result.content == "固定文本，无变量"

    def test_render_multiple_variables(self, renderer: PromptRenderer):
        tmpl = PromptTemplate(
            name="calc",
            template="{{ a }} + {{ b }} = {{ result }}",
            variables=["a", "b", "result"],
        )
        result = renderer.render(tmpl, {"a": 1, "b": 2, "result": 3})
        assert result.content == "1 + 2 = 3"

    def test_render_missing_variable_raises_error(
        self, renderer: PromptRenderer, simple_template: PromptTemplate
    ):
        """变量缺失应抛出 PromptRenderError（StrictUndefined）。"""
        with pytest.raises(PromptRenderError) as exc_info:
            renderer.render(simple_template, {})
        assert "greeting" in str(exc_info.value)

    def test_render_partial_variable_raises_error(self, renderer: PromptRenderer):
        tmpl = PromptTemplate(
            name="partial",
            template="{{ a }} and {{ b }}",
            variables=["a", "b"],
        )
        with pytest.raises(PromptRenderError):
            renderer.render(tmpl, {"a": "only_a"})

    def test_render_syntax_error_raises_render_error(self, renderer: PromptRenderer):
        """Jinja2 语法错误应抛出 PromptRenderError。"""
        tmpl = PromptTemplate(name="bad", template="{{ unclosed")
        with pytest.raises(PromptRenderError) as exc_info:
            renderer.render(tmpl, {})
        assert "bad" in str(exc_info.value)

    def test_render_returns_correct_template_name(
        self, renderer: PromptRenderer, simple_template: PromptTemplate
    ):
        result = renderer.render(simple_template, {"name": "test"})
        assert result.template_name == simple_template.name

    def test_render_extra_variables_are_ignored(self, renderer: PromptRenderer):
        """Jinja2 默认忽略多余变量（非 strict 对 extra vars）。"""
        tmpl = PromptTemplate(name="simple", template="Hello {{ name }}")
        result = renderer.render(tmpl, {"name": "world", "extra": "ignored"})
        assert result.content == "Hello world"

    def test_render_preserves_whitespace(self, renderer: PromptRenderer):
        tmpl = PromptTemplate(name="ws", template="line1\n{{ x }}\nline3")
        result = renderer.render(tmpl, {"x": "line2"})
        assert result.content == "line1\nline2\nline3"

    def test_render_jinja2_filters_work(self, renderer: PromptRenderer):
        tmpl = PromptTemplate(name="upper", template="{{ name | upper }}")
        result = renderer.render(tmpl, {"name": "hello"})
        assert result.content == "HELLO"

    def test_render_jinja2_conditionals_work(self, renderer: PromptRenderer):
        tmpl = PromptTemplate(
            name="cond",
            template="{% if flag %}yes{% else %}no{% endif %}",
        )
        assert renderer.render(tmpl, {"flag": True}).content == "yes"
        assert renderer.render(tmpl, {"flag": False}).content == "no"


# ──────────────────────────────────────────────
# PromptLoader
# ──────────────────────────────────────────────


class TestPromptLoader:
    @pytest.mark.asyncio
    async def test_load_jinja2_file(self, tmpdir_with_templates: Path):
        loader = PromptLoader(tmpdir_with_templates)
        tmpl = await loader.load("hello")
        assert tmpl.name == "hello"
        assert tmpl.template == "Hi {{ who }}!"

    @pytest.mark.asyncio
    async def test_load_txt_file(self, tmpdir_with_templates: Path):
        loader = PromptLoader(tmpdir_with_templates)
        tmpl = await loader.load("plain")
        assert tmpl.name == "plain"
        assert tmpl.template == "plain text, no vars"

    @pytest.mark.asyncio
    async def test_load_nonexistent_file_raises_error(self, tmpdir_with_templates: Path):
        loader = PromptLoader(tmpdir_with_templates)
        with pytest.raises(PromptLoadError) as exc_info:
            await loader.load("nonexistent")
        assert "nonexistent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_load_all_returns_all_templates(self, tmpdir_with_templates: Path):
        loader = PromptLoader(tmpdir_with_templates)
        templates = await loader.load_all()
        names = {t.name for t in templates}
        assert "hello" in names
        assert "plain" in names
        assert "multi" in names
        assert len(templates) == 3

    @pytest.mark.asyncio
    async def test_load_all_nonexistent_dir_raises_error(self, tmp_path: Path):
        loader = PromptLoader(tmp_path / "does_not_exist")
        with pytest.raises(PromptLoadError) as exc_info:
            await loader.load_all()
        assert "不存在" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_load_jinja2_preferred_over_txt(self, tmp_path: Path):
        """同名 .jinja2 和 .txt 都存在时，load 应找到其中一个（不报错）。"""
        (tmp_path / "tmpl.jinja2").write_text("jinja2 content", encoding="utf-8")
        (tmp_path / "tmpl.txt").write_text("txt content", encoding="utf-8")
        loader = PromptLoader(tmp_path)
        tmpl = await loader.load("tmpl")
        # 优先级：.jinja2 排在前，应加载 jinja2 版本
        assert tmpl.template == "jinja2 content"

    @pytest.mark.asyncio
    async def test_loaded_template_can_be_rendered(self, tmpdir_with_templates: Path):
        loader = PromptLoader(tmpdir_with_templates)
        tmpl = await loader.load("hello")
        renderer = PromptRenderer()
        result = renderer.render(tmpl, {"who": "祎晗"})
        assert result.content == "Hi 祎晗!"


# ──────────────────────────────────────────────
# TemplateRegistry
# ──────────────────────────────────────────────


class TestTemplateRegistry:
    def test_register_and_get(self, simple_template: PromptTemplate):
        registry = TemplateRegistry()
        registry.register(simple_template)
        found = registry.get("greeting")
        assert found is simple_template

    def test_get_nonexistent_raises_key_error(self):
        registry = TemplateRegistry()
        with pytest.raises(KeyError) as exc_info:
            registry.get("nope")
        assert "nope" in str(exc_info.value)

    def test_register_all(self):
        registry = TemplateRegistry()
        templates = [
            PromptTemplate(name="a", template="A"),
            PromptTemplate(name="b", template="B"),
        ]
        registry.register_all(templates)
        assert registry.get("a").template == "A"
        assert registry.get("b").template == "B"
        assert len(registry) == 2

    def test_register_duplicate_overwrites(self, simple_template: PromptTemplate):
        """覆盖已存在的模板应成功（并记录 warning）。"""
        registry = TemplateRegistry()
        registry.register(simple_template)
        new_tmpl = PromptTemplate(name="greeting", template="New content")
        registry.register(new_tmpl)
        assert registry.get("greeting").template == "New content"

    def test_all_names_returns_registered_names(self):
        registry = TemplateRegistry()
        registry.register(PromptTemplate(name="x", template="X"))
        registry.register(PromptTemplate(name="y", template="Y"))
        names = registry.all_names()
        assert set(names) == {"x", "y"}

    def test_all_names_empty_when_no_templates(self):
        registry = TemplateRegistry()
        assert registry.all_names() == []

    def test_clear_removes_all_templates(self, simple_template: PromptTemplate):
        registry = TemplateRegistry()
        registry.register(simple_template)
        registry.clear()
        assert len(registry) == 0
        with pytest.raises(KeyError):
            registry.get("greeting")

    def test_len_reflects_count(self):
        registry = TemplateRegistry()
        assert len(registry) == 0
        registry.register(PromptTemplate(name="t1", template="T1"))
        assert len(registry) == 1
        registry.register(PromptTemplate(name="t2", template="T2"))
        assert len(registry) == 2


# ──────────────────────────────────────────────
# get_template_registry / reset_template_registry 单例
# ──────────────────────────────────────────────


class TestGlobalRegistry:
    def test_get_registry_returns_same_instance(self):
        reg1 = get_template_registry()
        reg2 = get_template_registry()
        assert reg1 is reg2

    def test_reset_creates_new_instance(self):
        reg1 = get_template_registry()
        reset_template_registry()
        reg2 = get_template_registry()
        assert reg1 is not reg2

    def test_register_via_global_registry(self, simple_template: PromptTemplate):
        registry = get_template_registry()
        registry.register(simple_template)
        # 再次获取应看到同一注册表
        same_registry = get_template_registry()
        assert same_registry.get("greeting") is simple_template

    def test_reset_clears_registered_templates(self, simple_template: PromptTemplate):
        registry = get_template_registry()
        registry.register(simple_template)
        reset_template_registry()
        fresh = get_template_registry()
        with pytest.raises(KeyError):
            fresh.get("greeting")
