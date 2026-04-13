"""测试 haiji.config 模块。

覆盖场景：
- 默认值是否正确
- 显式传参覆盖
- 全局单例行为（get_config / set_config / reset_config）
- 字段校验（超出范围的值应报错）
- 环境变量读取
"""

from __future__ import annotations

import os

import pytest

from haiji.config import HaijiConfig, get_config, reset_config, set_config


# ── 辅助 ─────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """每个测试前后都重置全局单例，避免测试间互相污染。"""
    reset_config()
    yield
    reset_config()


# ── 默认值测试 ────────────────────────────────────────────────────────────────


def test_default_llm_model() -> None:
    """默认 llm_model 应为 gpt-4o。"""
    config = HaijiConfig()
    assert config.llm_model == "gpt-4o"


def test_default_llm_base_url() -> None:
    """默认 llm_base_url 应指向 OpenAI 官方接口。"""
    config = HaijiConfig()
    assert config.llm_base_url == "https://api.openai.com/v1"


def test_default_agent_max_rounds() -> None:
    """默认 REACT 最大轮次应为 10。"""
    config = HaijiConfig()
    assert config.agent_max_rounds == 10


def test_default_skill_max_candidates() -> None:
    """默认 Skill 候选池上限应为 20。"""
    config = HaijiConfig()
    assert config.skill_max_candidates == 20


def test_default_llm_timeout() -> None:
    """默认 LLM 超时应为 60 秒。"""
    config = HaijiConfig()
    assert config.llm_timeout == 60


def test_default_workspace_dir() -> None:
    """默认工作区路径应为 ./workspace_data。"""
    config = HaijiConfig()
    assert config.workspace_dir == "./workspace_data"


# ── 显式传参覆盖 ───────────────────────────────────────────────────────────────


def test_explicit_llm_model_override() -> None:
    """显式传参应覆盖默认值。"""
    config = HaijiConfig(llm_model="gpt-4o-mini", api_key="sk-test")
    assert config.llm_model == "gpt-4o-mini"
    assert config.api_key == "sk-test"


def test_explicit_base_url_override() -> None:
    """显式传参覆盖 base_url。"""
    config = HaijiConfig(llm_base_url="https://custom.api.com/v1")
    assert config.llm_base_url == "https://custom.api.com/v1"


def test_explicit_timeout_override() -> None:
    """显式传参覆盖超时时间。"""
    config = HaijiConfig(llm_timeout=120)
    assert config.llm_timeout == 120


# ── 字段校验 ───────────────────────────────────────────────────────────────────


def test_llm_timeout_too_large_raises_error() -> None:
    """llm_timeout 超过 300 应报 ValidationError。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HaijiConfig(llm_timeout=999)


def test_llm_timeout_zero_raises_error() -> None:
    """llm_timeout 为 0 应报 ValidationError（最小值为 1）。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HaijiConfig(llm_timeout=0)


def test_agent_max_rounds_zero_raises_error() -> None:
    """agent_max_rounds 为 0 应报 ValidationError。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HaijiConfig(agent_max_rounds=0)


def test_llm_temperature_out_of_range_raises_error() -> None:
    """temperature 超过 2.0 应报 ValidationError。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HaijiConfig(llm_temperature=3.0)


# ── 全局单例行为 ───────────────────────────────────────────────────────────────


def test_get_config_returns_singleton() -> None:
    """多次调用 get_config() 应返回同一实例。"""
    c1 = get_config()
    c2 = get_config()
    assert c1 is c2


def test_set_config_replaces_singleton() -> None:
    """set_config() 应替换全局单例。"""
    custom = HaijiConfig(llm_model="gpt-4o-mini")
    set_config(custom)
    assert get_config() is custom
    assert get_config().llm_model == "gpt-4o-mini"


def test_reset_config_clears_singleton() -> None:
    """reset_config() 后 get_config() 应返回新实例。"""
    c1 = get_config()
    reset_config()
    c2 = get_config()
    assert c1 is not c2


# ── 环境变量读取 ───────────────────────────────────────────────────────────────


def test_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量 HAIJI_LLM_MODEL 应覆盖默认值。"""
    monkeypatch.setenv("HAIJI_LLM_MODEL", "claude-3-5-sonnet")
    config = HaijiConfig()
    assert config.llm_model == "claude-3-5-sonnet"


def test_env_var_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量 HAIJI_API_KEY 应被正确读取。"""
    monkeypatch.setenv("HAIJI_API_KEY", "sk-env-test-key")
    config = HaijiConfig()
    assert config.api_key == "sk-env-test-key"


def test_env_var_llm_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量 HAIJI_LLM_TIMEOUT 应被正确解析为整数。"""
    monkeypatch.setenv("HAIJI_LLM_TIMEOUT", "90")
    config = HaijiConfig()
    assert config.llm_timeout == 90
