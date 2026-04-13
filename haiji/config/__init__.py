"""
config - 配置中心

框架唯一的配置入口，所有模块都从这里读取配置。

示例：
    from haiji.config import get_config, set_config, HaijiConfig

    # 读取配置（自动从环境变量 / .env 加载）
    config = get_config()

    # 自定义配置
    set_config(HaijiConfig(llm_model="gpt-4o-mini", api_key="sk-xxx"))
"""

from haiji.config.definition import HaijiConfig
from haiji.config.base import get_config, set_config, reset_config

__all__ = ["HaijiConfig", "get_config", "set_config", "reset_config"]
