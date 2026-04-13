"""config 模块的全局单例管理。

提供线程安全（Python GIL 保证）的全局单例 get_config() 和
用于测试的 set_config() / reset_config()。
"""

from __future__ import annotations

from typing import Optional

from haiji.config.definition import HaijiConfig

_global_config: Optional[HaijiConfig] = None


def get_config() -> HaijiConfig:
    """获取全局配置单例。

    首次调用时自动从环境变量和 .env 文件初始化配置；
    后续调用返回同一实例。

    Returns:
        HaijiConfig: 框架全局配置实例。

    Example::

        from haiji.config import get_config
        config = get_config()
        print(config.llm_model)
    """
    global _global_config
    if _global_config is None:
        _global_config = HaijiConfig()
    return _global_config


def set_config(config: HaijiConfig) -> None:
    """替换全局配置单例。

    主要用于测试场景，或在应用启动时显式覆盖配置。

    Args:
        config: 新的 HaijiConfig 实例。

    Example::

        from haiji.config import set_config, HaijiConfig
        set_config(HaijiConfig(llm_model="gpt-4o-mini", api_key="sk-test"))
    """
    global _global_config
    _global_config = config


def reset_config() -> None:
    """重置全局配置单例（清空缓存）。

    下次调用 get_config() 时将重新从环境变量读取。
    主要用于测试的 teardown。

    Example::

        from haiji.config import reset_config
        reset_config()
    """
    global _global_config
    _global_config = None
