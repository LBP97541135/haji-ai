"""
config/definition.py - 配置数据结构

定义 HaijiConfig，作为框架唯一的配置入口。
支持从环境变量和 .env 文件读取，字段名以 HAIJI_ 为前缀。
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class HaijiConfig(BaseSettings):
    """
    哈基AI 全局配置。

    优先级：代码传参 > 环境变量 > .env 文件 > 默认值

    示例：
        config = HaijiConfig(llm_model="gpt-4o", api_key="sk-xxx")
        # 或者直接读环境变量：
        config = HaijiConfig()
    """

    # LLM 配置
    llm_model: str = Field(default="gpt-4o", description="默认使用的大模型")
    llm_base_url: str = Field(
        default="https://api.openai.com/v1", description="LLM API 地址"
    )
    api_key: str = Field(default="", description="LLM API Key")

    # LLM 行为配置
    llm_temperature: float = Field(default=0.7, description="模型温度")
    llm_max_tokens: int = Field(default=4096, description="最大 token 数")
    llm_timeout: int = Field(default=60, description="LLM 调用超时秒数，最大 300")

    # Agent 配置
    agent_max_rounds: int = Field(default=10, description="REACT 循环最大轮次")

    # 工作区配置
    workspace_dir: str = Field(default="./workspace_data", description="Agent 工作区路径")

    model_config = {"env_prefix": "HAIJI_", "env_file": ".env", "extra": "ignore"}
