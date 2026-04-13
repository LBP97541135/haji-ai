"""config 模块单元测试"""

import pytest
from haiji.config import HaijiConfig, get_config, set_config, reset_config


def setup_function():
    reset_config()


def test_default_config_loads():
    config = HaijiConfig(api_key="sk-test")
    assert config.llm_model == "gpt-4o"
    assert config.agent_max_rounds == 10
    assert config.llm_timeout == 60


def test_get_config_returns_singleton():
    c1 = get_config()
    c2 = get_config()
    assert c1 is c2


def test_set_config_overrides():
    set_config(HaijiConfig(llm_model="gpt-4o-mini", api_key="sk-test"))
    config = get_config()
    assert config.llm_model == "gpt-4o-mini"


def test_reset_config():
    set_config(HaijiConfig(llm_model="gpt-4o-mini", api_key="sk-test"))
    reset_config()
    config = get_config()
    assert config.llm_model == "gpt-4o"
