"""哈基AI 配置数据结构定义。

包含框架所有模块的配置字段，全部通过 HaijiConfig 统一管理。
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HaijiConfig(BaseSettings):
    """哈基AI 框架全局配置。

    优先级（高到低）：
      1. 显式传参（实例化时直接赋值）
      2. 环境变量（前缀 HAIJI_）
      3. .env 文件（默认从当前工作目录读取 .env）
      4. 字段默认值

    Example::

        # 方式一：从环境变量 / .env 自动读取
        from haiji import get_config
        config = get_config()

        # 方式二：显式传参（测试常用）
        from haiji import HaijiConfig
        config = HaijiConfig(llm_model="gpt-4o-mini", api_key="sk-xxx")
    """

    model_config = SettingsConfigDict(
        env_prefix="HAIJI_",
        env_file=".env",
        env_file_encoding="utf-8",
        # 允许 .env 文件不存在，不报错
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM 配置 ───────────────────────────────────────────────────
    llm_model: str = Field(
        default="gpt-4o",
        description="使用的大模型名称，例如 gpt-4o、gpt-4o-mini",
    )
    llm_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI 兼容接口的 base_url",
    )
    api_key: str = Field(
        default="",
        description="LLM API Key，必填（生产环境从环境变量注入）",
    )

    # ── LLM 性能参数 ────────────────────────────────────────────────
    llm_timeout: int = Field(
        default=60,
        ge=1,
        le=300,
        description="LLM 调用超时（秒），范围 1-300",
    )
    llm_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="采样温度",
    )
    llm_max_tokens: int = Field(
        default=4096,
        ge=1,
        description="单次响应最大 token 数",
    )

    # ── Agent 运行参数 ───────────────────────────────────────────────
    agent_max_rounds: int = Field(
        default=10,
        ge=1,
        le=100,
        description="REACT 循环最大轮次，防死循环",
    )
    skill_max_candidates: int = Field(
        default=20,
        ge=1,
        description="Skill 动态加载候选池上限，防止 context 撑爆",
    )

    # ── 工作区 ───────────────────────────────────────────────────────
    workspace_dir: str = Field(
        default="./workspace_data",
        description="Agent 工作区根目录，存放持久化中间状态",
    )

    # ── 日志 ─────────────────────────────────────────────────────────
    log_level: str = Field(
        default="INFO",
        description="日志级别：DEBUG / INFO / WARNING / ERROR",
    )
    log_truncate_length: int = Field(
        default=200,
        ge=50,
        description="长文本打日志时截断到的最大字符数",
    )
