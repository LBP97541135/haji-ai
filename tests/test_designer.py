"""
tests/test_designer.py - Designer 模块单元测试

覆盖：
1. test_design_draft_fields        - DesignDraft 字段验证
2. test_validator_valid_draft      - 合法草稿通过校验
3. test_validator_empty_name       - name 为空报错
4. test_validator_invalid_mode     - mode 非法报错
5. test_validator_unknown_tool     - tool_codes 含未注册 tool 报错
6. test_validator_bio_too_long     - bio 超长报错
7. test_registrar_registers_agent  - 注册后 AgentRegistry 能找到
8. test_registrar_agent_code_unique - 同名 Agent 注册两次 code 不冲突
9. test_registrar_soul_injected    - soul 正确注入到 system_prompt
10. test_designer_full_flow_mock_llm - 用 mock LLM 跑完整三步流程
11. test_designer_validation_fail  - 校验失败时返回 DesignResult(ok=False)
12. test_designer_get_agent        - design 成功后 get_agent 能返回实例
"""

from __future__ import annotations

import json
from typing import AsyncGenerator, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from haiji.agent.registry import get_agent_registry
from haiji.designer import (
    Designer,
    DesignDraft,
    DesignRequest,
    DesignResult,
    ValidationError,
)
from haiji.designer.generator import DesignerGenerator
from haiji.designer.registrar import DesignerRegistrar, _make_code, _to_snake_case
from haiji.designer.validator import DesignerValidator
from haiji.llm.base import LlmClient
from haiji.llm.definition import LlmRequest, LlmResponse
from haiji.skill.base import get_skill_registry, skill
from haiji.tool.base import get_tool_registry, tool


# ---------------------------------------------------------------------------
# 测试辅助：Mock LLM Client
# ---------------------------------------------------------------------------

def make_mock_llm(json_content: str) -> LlmClient:
    """
    创建一个返回指定 JSON 内容的 Mock LLM 客户端。

    Args:
        json_content: LLM 应该返回的 JSON 字符串（DesignDraft 格式）

    Returns:
        实现 LlmClient 接口的 Mock 对象
    """
    mock = MagicMock(spec=LlmClient)
    response = LlmResponse(content=json_content)
    mock.chat = AsyncMock(return_value=response)

    async def _stream(*args, **kwargs) -> AsyncGenerator[str, None]:
        yield json_content

    mock.stream_chat = _stream
    mock.chat_with_tools = AsyncMock(return_value=response)
    return mock


# 合法的 DesignDraft JSON（无需注册任何 tool/skill 因为列表为空）
_VALID_DRAFT_JSON = json.dumps({
    "name": "投资顾问",
    "avatar": "💰",
    "bio": "你的专属投资分析师",
    "soul": "# 性格\n直接、犀利、数据驱动。\n# 说话风格\n简洁有力，不废话。\n# 禁止\n不瞎吹，不荐股。",
    "mode": "direct",
    "tool_codes": [],
    "skill_codes": [],
    "tags": ["金融", "投资", "分析"],
    "rag_enabled": False,
    "reasoning": "用户需要一个直接的投资顾问，无需工具调用，使用 direct 模式。",
})


# ---------------------------------------------------------------------------
# Fixture：注册一个测试 tool 和 skill，供测试用
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def register_test_tool():
    """注册一个测试用 tool，用于校验 tool_codes 存在性测试。"""
    registry = get_tool_registry()
    # 手动构造并注册一个假 tool
    from haiji.tool.definition import XTool, ToolMeta

    class FakeTool(XTool):
        @property
        def tool_code(self) -> str:
            return "test_tool_for_designer"

        @property
        def description(self) -> str:
            return "测试专用 tool"

        @property
        def parameters_schema(self) -> dict:
            return {"type": "object", "properties": {}}

        async def execute(self, args, ctx):
            return "ok"

    ft = FakeTool()
    registry.register(ft)
    yield ft
    # 清理（ToolRegistry 无 unregister，这里手动删除）
    registry._tools.pop("test_tool_for_designer", None)


@pytest.fixture(autouse=False)
def register_test_skill():
    """注册一个测试用 skill。"""
    from haiji.skill.definition import SkillEntry, XSkillDef

    registry = get_skill_registry()
    skill_def = XSkillDef(
        code="test_skill_for_designer",
        name="测试技能",
        description="Designer 测试专用 skill",
        tool_codes=[],
        prompt_fragment="",
    )
    entry = SkillEntry(definition=skill_def, skill_class=None)
    registry.register(entry)
    yield entry
    registry._skills.pop("test_skill_for_designer", None)


# ---------------------------------------------------------------------------
# 1. test_design_draft_fields - DesignDraft 字段验证
# ---------------------------------------------------------------------------

def test_design_draft_fields():
    """验证 DesignDraft 所有字段的默认值和赋值行为。"""
    # 默认值测试
    draft = DesignDraft()
    assert draft.name == ""
    assert draft.avatar == ""
    assert draft.bio == ""
    assert draft.soul == ""
    assert draft.mode == "react"
    assert draft.tool_codes == []
    assert draft.skill_codes == []
    assert draft.tags == []
    assert draft.rag_enabled is False
    assert draft.reasoning == ""

    # 赋值测试
    draft2 = DesignDraft(
        name="投资顾问",
        avatar="💰",
        bio="说话直接的投资朋友",
        soul="# 性格\n直接。",
        mode="direct",
        tool_codes=["search_web"],
        skill_codes=["web_research"],
        tags=["金融", "投资"],
        rag_enabled=True,
        reasoning="测试用",
    )
    assert draft2.name == "投资顾问"
    assert draft2.avatar == "💰"
    assert draft2.mode == "direct"
    assert "search_web" in draft2.tool_codes
    assert draft2.rag_enabled is True


# ---------------------------------------------------------------------------
# 2. test_validator_valid_draft - 合法草稿通过校验
# ---------------------------------------------------------------------------

def test_validator_valid_draft():
    """合法草稿应该通过校验，返回空错误列表。"""
    validator = DesignerValidator()
    draft = DesignDraft(
        name="投资顾问",
        avatar="💰",
        bio="你的专属投资分析师",
        soul="# 性格\n直接。\n# 说话风格\n简洁。\n# 禁止\n不荐股。",
        mode="direct",
        tool_codes=[],
        skill_codes=[],
        tags=["金融"],
    )
    errors = validator.validate(draft)
    assert errors == [], f"期望无错误，实际错误：{errors}"


# ---------------------------------------------------------------------------
# 3. test_validator_empty_name - name 为空报错
# ---------------------------------------------------------------------------

def test_validator_empty_name():
    """name 为空字符串时，校验应返回包含 name 字段的错误。"""
    validator = DesignerValidator()
    draft = DesignDraft(name="", mode="direct")
    errors = validator.validate(draft)
    assert any(e.field == "name" for e in errors), f"期望 name 字段报错，实际：{errors}"


def test_validator_empty_name_whitespace():
    """name 为纯空白字符时，也应返回 name 字段错误。"""
    validator = DesignerValidator()
    draft = DesignDraft(name="   ", mode="direct")
    errors = validator.validate(draft)
    assert any(e.field == "name" for e in errors)


# ---------------------------------------------------------------------------
# 4. test_validator_invalid_mode - mode 非法报错
# ---------------------------------------------------------------------------

def test_validator_invalid_mode():
    """mode 不在合法枚举值内时，应返回 mode 字段错误。"""
    validator = DesignerValidator()
    draft = DesignDraft(name="测试Agent", mode="turbo_mode_xxx")
    errors = validator.validate(draft)
    assert any(e.field == "mode" for e in errors), f"期望 mode 字段报错，实际：{errors}"


def test_validator_valid_modes():
    """所有合法 mode 值应通过校验。"""
    validator = DesignerValidator()
    for mode_val in ["direct", "react", "plan_and_execute"]:
        draft = DesignDraft(name="测试", mode=mode_val)
        errors = validator.validate(draft)
        mode_errors = [e for e in errors if e.field == "mode"]
        assert mode_errors == [], f"mode={mode_val!r} 不应报错，实际：{mode_errors}"


# ---------------------------------------------------------------------------
# 5. test_validator_unknown_tool - tool_codes 含未注册 tool 报错
# ---------------------------------------------------------------------------

def test_validator_unknown_tool():
    """tool_codes 包含未注册的 tool code 时，应返回 tool_codes 字段错误。"""
    validator = DesignerValidator()
    draft = DesignDraft(
        name="测试Agent",
        mode="react",
        tool_codes=["nonexistent_tool_xyz_9999"],
    )
    errors = validator.validate(draft)
    assert any(e.field == "tool_codes" for e in errors), \
        f"期望 tool_codes 字段报错，实际：{errors}"


def test_validator_known_tool_passes(register_test_tool):
    """tool_codes 包含已注册的 tool code 时，不应报 tool_codes 错误。"""
    validator = DesignerValidator()
    draft = DesignDraft(
        name="测试Agent",
        mode="react",
        tool_codes=["test_tool_for_designer"],
    )
    errors = validator.validate(draft)
    tool_errors = [e for e in errors if e.field == "tool_codes"]
    assert tool_errors == [], f"已注册 tool 不应报错，实际：{tool_errors}"


# ---------------------------------------------------------------------------
# 6. test_validator_bio_too_long - bio 超长报错
# ---------------------------------------------------------------------------

def test_validator_bio_too_long():
    """bio 超过 50 字符时，应返回 bio 字段错误。"""
    validator = DesignerValidator()
    long_bio = "a" * 51  # 51 字符，超限
    draft = DesignDraft(name="测试Agent", mode="direct", bio=long_bio)
    errors = validator.validate(draft)
    assert any(e.field == "bio" for e in errors), \
        f"期望 bio 字段报错，实际：{errors}"


def test_validator_bio_exactly_50():
    """bio 正好 50 字符时，应通过校验。"""
    validator = DesignerValidator()
    ok_bio = "a" * 50
    draft = DesignDraft(name="测试Agent", mode="direct", bio=ok_bio)
    errors = validator.validate(draft)
    bio_errors = [e for e in errors if e.field == "bio"]
    assert bio_errors == [], f"50字符 bio 不应报错，实际：{bio_errors}"


def test_validator_soul_too_long():
    """soul 超过 4000 字符时，应返回 soul 字段错误。"""
    validator = DesignerValidator()
    long_soul = "x" * 4001
    draft = DesignDraft(name="测试Agent", mode="direct", soul=long_soul)
    errors = validator.validate(draft)
    assert any(e.field == "soul" for e in errors), \
        f"期望 soul 字段报错，实际：{errors}"


# ---------------------------------------------------------------------------
# 7. test_registrar_registers_agent - 注册后 AgentRegistry 能找到
# ---------------------------------------------------------------------------

def test_registrar_registers_agent():
    """成功注册后，AgentRegistry 应能通过 agent_code 找到对应类。"""
    registrar = DesignerRegistrar()
    draft = DesignDraft(
        name="财经助手",
        avatar="📈",
        bio="实时资讯，精准分析",
        soul="# 性格\n冷静客观。",
        mode="direct",
        tags=["金融"],
    )
    agent_code, definition = registrar.register(draft)

    registry = get_agent_registry()
    cls = registry.get(agent_code)

    assert cls is not None, f"AgentRegistry 中未找到 agent_code={agent_code!r}"
    assert definition.code == agent_code
    assert definition.name == "财经助手"
    assert definition.avatar == "📈"
    assert definition.bio == "实时资讯，精准分析"
    assert "金融" in definition.tags


# ---------------------------------------------------------------------------
# 8. test_registrar_agent_code_unique - 同名 Agent 注册两次 code 不冲突
# ---------------------------------------------------------------------------

def test_registrar_agent_code_unique():
    """同名 Agent 注册两次时，由于随机后缀，agent_code 应不同（极大概率）。"""
    registrar = DesignerRegistrar()
    draft = DesignDraft(name="重复名称Agent", mode="direct")

    code1, _ = registrar.register(draft)
    code2, _ = registrar.register(draft)

    # 两次注册的 code 应不同（随机后缀保证）
    assert code1 != code2, f"两次注册的 code 不应相同，实际 code1={code1!r} code2={code2!r}"

    # 两者都能在 registry 中找到
    registry = get_agent_registry()
    assert registry.get(code1) is not None
    assert registry.get(code2) is not None


# ---------------------------------------------------------------------------
# 9. test_registrar_soul_injected - soul 正确注入到 system_prompt
# ---------------------------------------------------------------------------

def test_registrar_soul_injected():
    """soul 应正确注入到 Agent 的 system_prompt，格式为 soul + '---' + identity。"""
    registrar = DesignerRegistrar()
    soul_text = "# 性格\n温柔、直接、偶尔毒舌。\n# 说话风格\n用中文，短句。\n# 禁止\n不扮演其他角色。"
    draft = DesignDraft(
        name="小助手",
        bio="你的贴心小助手",
        soul=soul_text,
        mode="direct",
    )
    agent_code, definition = registrar.register(draft)

    # 检查 system_prompt 包含 soul
    assert soul_text in definition.system_prompt, \
        f"system_prompt 应包含 soul，实际：{definition.system_prompt!r}"

    # 检查 system_prompt 包含 identity（名称和 bio）
    assert "小助手" in definition.system_prompt, \
        f"system_prompt 应包含 Agent 名称"
    assert "你的贴心小助手" in definition.system_prompt, \
        f"system_prompt 应包含 bio"

    # 检查分隔符
    assert "---" in definition.system_prompt, \
        f"system_prompt 应包含 soul 和 identity 的分隔符"

    # 检查 soul 在 system_prompt 中的存储
    assert definition.soul == soul_text


def test_registrar_soul_empty():
    """soul 为空时，system_prompt 仅包含 identity 行。"""
    registrar = DesignerRegistrar()
    draft = DesignDraft(name="无人设助手", bio="简单助手", soul="", mode="direct")
    agent_code, definition = registrar.register(draft)

    assert "无人设助手" in definition.system_prompt
    assert "---" not in definition.system_prompt, "soul 为空时不应有分隔符"


# ---------------------------------------------------------------------------
# 10. test_designer_full_flow_mock_llm - 用 mock LLM 跑完整三步流程
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_designer_full_flow_mock_llm():
    """使用 Mock LLM 跑完整 design() 三步流程，验证返回结果正确。"""
    mock_llm = make_mock_llm(_VALID_DRAFT_JSON)
    designer = Designer(llm_client=mock_llm)

    result = await designer.design("我想要一个懂投资的朋友，说话直接")

    assert result.ok is True, f"期望 ok=True，实际 errors：{result.errors}"
    assert result.agent_code != "", "agent_code 不应为空"
    assert result.definition is not None, "definition 不应为 None"
    assert result.draft is not None, "draft 不应为 None"
    assert result.draft.name == "投资顾问"
    assert result.draft.mode == "direct"
    assert result.errors == []

    # 验证注册到 registry
    registry = get_agent_registry()
    cls = registry.get(result.agent_code)
    assert cls is not None, f"AgentRegistry 中未找到 {result.agent_code!r}"


@pytest.mark.asyncio
async def test_designer_full_flow_with_preferred_mode():
    """preferred_mode 参数应正确传入请求。"""
    mock_llm = make_mock_llm(_VALID_DRAFT_JSON)
    designer = Designer(llm_client=mock_llm)

    result = await designer.design("一个助手", preferred_mode="react")
    assert result.ok is True


# ---------------------------------------------------------------------------
# 11. test_designer_validation_fail - 校验失败时返回 DesignResult(ok=False)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_designer_validation_fail():
    """当 LLM 返回的草稿校验失败时，design() 应返回 DesignResult(ok=False, errors=...)。"""
    # 构造一个 name 为空的非法草稿 JSON
    invalid_draft_json = json.dumps({
        "name": "",          # 非法：name 为空
        "avatar": "🤖",
        "bio": "测试",
        "soul": "",
        "mode": "direct",
        "tool_codes": [],
        "skill_codes": [],
        "tags": [],
        "rag_enabled": False,
        "reasoning": "故意让 name 为空",
    })
    mock_llm = make_mock_llm(invalid_draft_json)
    designer = Designer(llm_client=mock_llm)

    result = await designer.design("描述不重要，反正 name 为空")

    assert result.ok is False, "校验失败时 ok 应为 False"
    assert len(result.errors) > 0, "errors 不应为空"
    assert any(e.field == "name" for e in result.errors), \
        f"期望 name 字段报错，实际：{result.errors}"
    assert result.draft is not None, "即使失败也应返回 draft"
    assert result.agent_code == "", "失败时 agent_code 应为空"
    assert result.definition is None, "失败时 definition 应为 None"


@pytest.mark.asyncio
async def test_designer_validation_fail_invalid_mode():
    """非法 mode 导致校验失败时，应正确返回 ok=False。"""
    invalid_draft_json = json.dumps({
        "name": "测试Agent",
        "avatar": "🤖",
        "bio": "测试",
        "soul": "",
        "mode": "super_turbo_mode",   # 非法 mode
        "tool_codes": [],
        "skill_codes": [],
        "tags": [],
        "rag_enabled": False,
        "reasoning": "",
    })
    mock_llm = make_mock_llm(invalid_draft_json)
    designer = Designer(llm_client=mock_llm)

    result = await designer.design("无所谓")

    assert result.ok is False
    assert any(e.field == "mode" for e in result.errors)


# ---------------------------------------------------------------------------
# 12. test_designer_get_agent - design 成功后 get_agent 能返回实例并可调用 stream_chat
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_designer_get_agent():
    """design 成功后，get_agent 应返回可实例化的 Agent，可访问 _definition。"""
    mock_llm = make_mock_llm(_VALID_DRAFT_JSON)
    designer = Designer(llm_client=mock_llm)

    result = await designer.design("懂投资的顾问")
    assert result.ok is True

    agent_instance = designer.get_agent(result.agent_code)
    assert agent_instance is not None, "get_agent 不应返回 None"

    # 验证 Agent 实例有正确的 definition
    assert agent_instance._definition.code == result.agent_code
    assert agent_instance._definition.name == "投资顾问"
    # stream_chat 方法存在（可调用）
    assert callable(getattr(agent_instance, "stream_chat", None)), \
        "Agent 实例应有 stream_chat 方法"


@pytest.mark.asyncio
async def test_designer_get_agent_not_found():
    """get_agent 传入不存在的 code 时，应返回 None。"""
    mock_llm = make_mock_llm(_VALID_DRAFT_JSON)
    designer = Designer(llm_client=mock_llm)

    result = designer.get_agent("nonexistent_agent_code_xyz_9999")
    assert result is None


# ---------------------------------------------------------------------------
# 辅助函数单元测试
# ---------------------------------------------------------------------------

def test_to_snake_case_basic():
    """_to_snake_case 应正确转换普通英文名称。"""
    from haiji.designer.registrar import _to_snake_case
    assert _to_snake_case("InvestmentAdvisor") == "investment_advisor"
    assert _to_snake_case("my agent") == "my_agent"
    assert _to_snake_case("") == "agent"


def test_to_snake_case_chinese():
    """_to_snake_case 处理中文时不报错，返回非空字符串。"""
    from haiji.designer.registrar import _to_snake_case
    result = _to_snake_case("投资顾问")
    # 中文 unicode 字母在 \w 中，结果可能是拼音字符；关键是不崩溃
    assert isinstance(result, str)
    assert len(result) > 0


def test_make_code_uniqueness():
    """_make_code 多次调用应生成不同的 code（随机后缀）。"""
    from haiji.designer.registrar import _make_code
    codes = {_make_code("TestAgent") for _ in range(20)}
    # 20 次中应有多个不同值（随机后缀 36^4=1679616 种可能）
    assert len(codes) > 1, "多次调用 _make_code 应产生不同 code"


def test_design_request_fields():
    """DesignRequest 字段默认值和赋值测试。"""
    req = DesignRequest(description="我想要一个助手")
    assert req.description == "我想要一个助手"
    assert req.preferred_mode is None
    assert req.allow_rag is True
    assert req.rag is None
    assert req.rag_config is None


def test_design_result_ok_false():
    """DesignResult(ok=False) 的基本结构测试。"""
    err = ValidationError(field="name", message="不能为空")
    result = DesignResult(ok=False, errors=[err])
    assert result.ok is False
    assert len(result.errors) == 1
    assert result.agent_code == ""
    assert result.definition is None


def test_validation_error_fields():
    """ValidationError 字段验证。"""
    err = ValidationError(field="bio", message="超过 50 字")
    assert err.field == "bio"
    assert err.message == "超过 50 字"
