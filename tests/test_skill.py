"""
tests/test_skill.py - Skill 模块测试

覆盖：XSkillDef / SkillEntry 数据结构、@skill 装饰器、SkillRegistry、
SkillSearcher（向量路径 + 关键词降级路径）、build_prompt_fragment。
"""

from __future__ import annotations

import math
import pytest
from unittest.mock import AsyncMock, patch

from haiji.skill.definition import XSkillDef, SkillEntry
from haiji.skill.base import (
    SkillRegistry,
    SkillSearcher,
    build_prompt_fragment,
    _cosine_similarity,
    get_skill_registry,
    skill,
)
from haiji.tool.base import ToolRegistry, FunctionTool, ToolRegistry
from haiji.tool.definition import XTool


# ---------------------------------------------------------------------------
# 辅助 fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch: pytest.MonkeyPatch) -> SkillRegistry:
    """每个测试使用独立注册表，避免全局状态污染。"""
    reg = SkillRegistry()
    import haiji.skill.base as skill_base
    monkeypatch.setattr(skill_base, "_registry", reg)
    return reg


def _make_entry(
    code: str = "test_skill",
    name: str = "测试Skill",
    description: str = "这是一个测试用 Skill",
    tool_codes: list[str] | None = None,
    prompt_fragment: str = "测试用 prompt",
) -> SkillEntry:
    """创建一个测试用 SkillEntry。"""
    return SkillEntry(
        definition=XSkillDef(
            code=code,
            name=name,
            description=description,
            tool_codes=tool_codes or [],
            prompt_fragment=prompt_fragment,
        )
    )


# ---------------------------------------------------------------------------
# XSkillDef 数据结构
# ---------------------------------------------------------------------------


class TestXSkillDef:
    def test_create_with_required_fields(self) -> None:
        d = XSkillDef(code="my_skill", name="我的Skill", description="一个描述")
        assert d.code == "my_skill"
        assert d.name == "我的Skill"
        assert d.description == "一个描述"
        assert d.tool_codes == []
        assert d.prompt_fragment == ""
        assert d.embedding is None

    def test_create_with_all_fields(self) -> None:
        d = XSkillDef(
            code="full_skill",
            name="完整Skill",
            description="完整描述",
            tool_codes=["tool_a", "tool_b"],
            prompt_fragment="当需要时使用...",
        )
        assert d.tool_codes == ["tool_a", "tool_b"]
        assert d.prompt_fragment == "当需要时使用..."

    def test_embedding_field_optional(self) -> None:
        d = XSkillDef(code="s", name="n", description="d", embedding=[0.1, 0.2, 0.3])
        assert d.embedding == [0.1, 0.2, 0.3]


# ---------------------------------------------------------------------------
# SkillEntry
# ---------------------------------------------------------------------------


class TestSkillEntry:
    def test_properties_delegate_to_definition(self) -> None:
        entry = _make_entry(code="abc", tool_codes=["t1"], prompt_fragment="pf")
        assert entry.code == "abc"
        assert entry.tool_codes == ["t1"]
        assert entry.prompt_fragment == "pf"

    def test_skill_class_optional(self) -> None:
        entry = _make_entry()
        assert entry.skill_class is None

        class MySkill:
            pass

        entry2 = SkillEntry(definition=_make_entry().definition, skill_class=MySkill)
        assert entry2.skill_class is MySkill


# ---------------------------------------------------------------------------
# SkillRegistry
# ---------------------------------------------------------------------------


class TestSkillRegistry:
    def test_register_and_get(self) -> None:
        reg = SkillRegistry()
        entry = _make_entry("s1")
        reg.register(entry)
        assert reg.get("s1") is entry

    def test_get_missing_returns_none(self) -> None:
        reg = SkillRegistry()
        assert reg.get("not_exist") is None

    def test_len(self) -> None:
        reg = SkillRegistry()
        assert len(reg) == 0
        reg.register(_make_entry("a"))
        reg.register(_make_entry("b"))
        assert len(reg) == 2

    def test_all(self) -> None:
        reg = SkillRegistry()
        e1 = _make_entry("x")
        e2 = _make_entry("y")
        reg.register(e1)
        reg.register(e2)
        assert set(e.code for e in reg.all()) == {"x", "y"}

    def test_all_codes(self) -> None:
        reg = SkillRegistry()
        reg.register(_make_entry("p"))
        reg.register(_make_entry("q"))
        assert set(reg.all_codes()) == {"p", "q"}

    def test_overwrite_existing_skill(self) -> None:
        reg = SkillRegistry()
        e1 = _make_entry("dup", name="原始")
        e2 = _make_entry("dup", name="覆盖")
        reg.register(e1)
        reg.register(e2)
        assert reg.get("dup").definition.name == "覆盖"
        assert len(reg) == 1


# ---------------------------------------------------------------------------
# @skill 装饰器
# ---------------------------------------------------------------------------


class TestSkillDecorator:
    def test_decorate_function(self, isolated_registry: SkillRegistry) -> None:
        @skill(description="测试装饰函数")
        def my_func_skill() -> None:
            pass

        entry = isolated_registry.get("my_func_skill")
        assert entry is not None
        assert entry.definition.description == "测试装饰函数"
        assert entry.definition.code == "my_func_skill"

    def test_decorate_class(self, isolated_registry: SkillRegistry) -> None:
        @skill(description="测试装饰类", code="cls_skill", name="类技能")
        class MyClassSkill:
            prompt = "类 prompt"

        entry = isolated_registry.get("cls_skill")
        assert entry is not None
        assert entry.definition.name == "类技能"
        # prompt_fragment 未传时，应读 class.prompt
        assert entry.definition.prompt_fragment == "类 prompt"
        assert entry.skill_class is MyClassSkill

    def test_explicit_prompt_fragment_wins_over_class_prompt(
        self, isolated_registry: SkillRegistry
    ) -> None:
        @skill(description="d", prompt_fragment="显式 pf")
        class SomeSkill:
            prompt = "类 pf"

        entry = isolated_registry.get("SomeSkill")
        assert entry.definition.prompt_fragment == "显式 pf"

    def test_tool_codes_from_decorated_functions(
        self, isolated_registry: SkillRegistry
    ) -> None:
        """@tool 装饰的函数有 _tool 属性，@skill 应正确提取 tool_code。"""
        from haiji.tool.definition import ToolMeta

        # 伪造一个带 _tool 属性的函数
        def fake_tool_fn():
            pass

        fake_tool_fn._tool = FunctionTool(
            func=fake_tool_fn,
            code="fake_tool",
            description="fake",
            schema={"type": "object", "properties": {}},
        )

        @skill(description="带 tool 的 skill", tools=[fake_tool_fn])
        def tool_skill() -> None:
            pass

        entry = isolated_registry.get("tool_skill")
        assert "fake_tool" in entry.definition.tool_codes

    def test_tool_codes_from_string(self, isolated_registry: SkillRegistry) -> None:
        @skill(description="字符串 tool", tools=["str_tool_a", "str_tool_b"])
        def str_skill() -> None:
            pass

        entry = isolated_registry.get("str_skill")
        assert entry.definition.tool_codes == ["str_tool_a", "str_tool_b"]

    def test_decorated_class_still_usable(self, isolated_registry: SkillRegistry) -> None:
        """装饰器不应破坏原始类的使用。"""

        @skill(description="不破坏类")
        class UsableSkill:
            value = 42

        assert UsableSkill.value == 42

    def test_decorated_function_still_callable(
        self, isolated_registry: SkillRegistry
    ) -> None:
        @skill(description="不破坏函数")
        def usable_fn() -> int:
            return 99

        assert usable_fn() == 99

    def test_custom_code_and_name(self, isolated_registry: SkillRegistry) -> None:
        @skill(description="d", code="my_code", name="我的名字")
        def any_fn() -> None:
            pass

        entry = isolated_registry.get("my_code")
        assert entry is not None
        assert entry.definition.name == "我的名字"


# ---------------------------------------------------------------------------
# _cosine_similarity
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = [1.0, 0.0, 0.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self) -> None:
        assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-6

    def test_opposite_vectors(self) -> None:
        assert abs(_cosine_similarity([1.0, 0.0], [-1.0, 0.0]) - (-1.0)) < 1e-6

    def test_zero_vector_returns_zero(self) -> None:
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_different_lengths_returns_zero(self) -> None:
        assert _cosine_similarity([1.0], [1.0, 2.0]) == 0.0


# ---------------------------------------------------------------------------
# SkillSearcher
# ---------------------------------------------------------------------------


class TestSkillSearcher:
    def _make_entries(self) -> list[SkillEntry]:
        return [
            _make_entry("web", description="搜索网络获取最新信息"),
            _make_entry("math", description="进行数学计算"),
            _make_entry("code", description="编写和执行代码"),
        ]

    @pytest.mark.asyncio
    async def test_search_with_vector_embed(self) -> None:
        """向量路径：embed_fn 正确工作时，应按余弦相似度排序。"""
        entries = self._make_entries()

        # 为每个 entry 提供正交基向量
        vectors = {
            "搜索网络获取最新信息": [1.0, 0.0, 0.0],
            "进行数学计算": [0.0, 1.0, 0.0],
            "编写和执行代码": [0.0, 0.0, 1.0],
        }

        async def embed_fn(texts: list[str]) -> list[list[float]]:
            return [vectors.get(t, [0.0, 0.0, 0.0]) for t in texts]

        searcher = SkillSearcher(embed_fn=embed_fn)
        await searcher.index(entries)

        # 查询向量与 web 最相似
        results = await searcher.search("搜索网络获取最新信息", top_k=2)
        assert results[0][0].code == "web"
        assert results[0][1] == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.asyncio
    async def test_search_keyword_fallback(self) -> None:
        """无 embed_fn 时退化为关键词匹配。"""
        entries = self._make_entries()
        searcher = SkillSearcher(embed_fn=None)
        await searcher.index(entries)

        results = await searcher.search("搜索网络")
        # "搜索" "网络" 都在 web 的 description 里
        assert len(results) > 0
        assert results[0][0].code == "web"

    @pytest.mark.asyncio
    async def test_search_empty_index_returns_empty(self) -> None:
        searcher = SkillSearcher()
        await searcher.index([])
        results = await searcher.search("任意查询")
        assert results == []

    @pytest.mark.asyncio
    async def test_top_k_limit(self) -> None:
        entries = [_make_entry(str(i), description=f"skill {i}") for i in range(10)]
        searcher = SkillSearcher(embed_fn=None)
        await searcher.index(entries)
        results = await searcher.search("skill", top_k=3)
        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_top_k_capped_at_20(self) -> None:
        """top_k 超过 20 时应被截断到 20（性能规范）。"""
        entries = [_make_entry(str(i), description="skill") for i in range(30)]
        searcher = SkillSearcher(embed_fn=None)
        await searcher.index(entries)
        results = await searcher.search("skill", top_k=50)
        assert len(results) <= 20

    @pytest.mark.asyncio
    async def test_score_threshold_filters_low_scores(self) -> None:
        entries = self._make_entries()
        searcher = SkillSearcher(embed_fn=None)
        await searcher.index(entries)
        results = await searcher.search("完全无关的查询xyz", score_threshold=0.5)
        # 关键词匹配应全部低于 0.5
        assert all(score >= 0.5 for _, score in results)

    @pytest.mark.asyncio
    async def test_embed_fn_failure_falls_back_to_keyword(self) -> None:
        """embed_fn 抛异常时，应降级为关键词匹配而不是崩溃。"""
        entries = self._make_entries()

        async def bad_embed(texts: list[str]) -> list[list[float]]:
            raise RuntimeError("embed API down")

        searcher = SkillSearcher(embed_fn=bad_embed)
        # index 阶段出错：embedding 未填充
        await searcher.index(entries)
        # search 阶段也应降级
        results = await searcher.search("搜索网络")
        assert isinstance(results, list)  # 不应抛异常


# ---------------------------------------------------------------------------
# build_prompt_fragment
# ---------------------------------------------------------------------------


class TestBuildPromptFragment:
    def test_empty_list_returns_empty_string(self) -> None:
        assert build_prompt_fragment([]) == ""

    def test_single_skill_with_fragment(self) -> None:
        entry = _make_entry(
            code="web_research",
            name="网络调研",
            tool_codes=["search_web"],
            prompt_fragment="使用 search_web 搜索信息。",
        )
        result = build_prompt_fragment([entry])
        assert "## 可用能力（Skills）" in result
        assert "### 网络调研（web_research）" in result
        assert "使用 search_web 搜索信息。" in result
        assert "search_web" in result

    def test_skill_without_fragment(self) -> None:
        entry = _make_entry(code="bare", name="裸Skill", prompt_fragment="")
        result = build_prompt_fragment([entry])
        assert "### 裸Skill（bare）" in result

    def test_multiple_skills_all_present(self) -> None:
        entries = [
            _make_entry("s1", name="技能1"),
            _make_entry("s2", name="技能2"),
        ]
        result = build_prompt_fragment(entries)
        assert "技能1" in result
        assert "技能2" in result

    def test_tool_codes_listed(self) -> None:
        entry = _make_entry(tool_codes=["tool_a", "tool_b", "tool_c"])
        result = build_prompt_fragment([entry])
        assert "tool_a" in result
        assert "tool_b" in result
        assert "tool_c" in result

    def test_no_tool_codes_still_renders(self) -> None:
        entry = _make_entry(tool_codes=[])
        result = build_prompt_fragment([entry])
        assert "可用工具" not in result
