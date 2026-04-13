"""
config/base.py - 配置中心

提供全局单例访问 get_config()，整个框架所有模块都从这里读取配置。
"""

from typing import Optional
from haiji.config.definition import HaijiConfig

_config: Optional[HaijiConfig] = None


def get_config() -> HaijiConfig:
    """
    获取全局配置单例。

    首次调用时自动从环境变量 / .env 文件加载。
    如需覆盖，请先调用 set_config()。

    示例：
        config = get_config()
        print(config.llm_model)
    """
    global _config
    if _config is None:
        _config = HaijiConfig()
    return _config


def set_config(config: HaijiConfig) -> None:
    """
    覆盖全局配置（用于测试或自定义初始化）。

    示例：
        set_config(HaijiConfig(llm_model="gpt-4o-mini", api_key="sk-xxx"))
    """
    global _config
    _config = config


def reset_config() -> None:
    """重置配置单例，下次 get_config() 时重新从环境变量加载（主要用于测试）。"""
    global _config
    _config = None
