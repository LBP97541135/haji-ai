"""哈基AI（haiji）— 基于 Python 的 Multi-Agent 框架。

快速上手::

    from haiji import HaijiConfig, get_config

    # 从 .env 或环境变量自动读取配置
    config = get_config()

    # 或者显式传参
    config = HaijiConfig(llm_model="gpt-4o", api_key="sk-xxx")
"""

from haiji.config import HaijiConfig, get_config, reset_config, set_config

__all__ = [
    "HaijiConfig",
    "get_config",
    "set_config",
    "reset_config",
]

__version__ = "0.1.0"
