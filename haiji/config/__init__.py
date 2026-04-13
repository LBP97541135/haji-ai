"""haiji.config — 框架配置中心。

统一管理 haiji 框架所有模块的配置，支持：
- 环境变量读取（前缀 HAIJI_）
- .env 文件加载
- 显式传参覆盖
- 全局单例访问

公共接口::

    from haiji.config import HaijiConfig, get_config, set_config, reset_config

    # 获取全局配置（自动从环境变量 / .env 读取）
    config = get_config()

    # 显式创建配置（测试常用）
    config = HaijiConfig(llm_model="gpt-4o-mini", api_key="sk-xxx")
"""

from haiji.config.base import get_config, reset_config, set_config
from haiji.config.definition import HaijiConfig

__all__ = [
    "HaijiConfig",
    "get_config",
    "set_config",
    "reset_config",
]
