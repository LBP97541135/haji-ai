"""
designer/definition.py - Designer 模块数据结构

定义 Designer 流程中涉及的所有数据结构：
- DesignRequest:   用户输入的设计请求
- DesignDraft:     LLM 生成的 Agent 草稿（中间产物）
- ValidationError: 单条校验错误
- DesignResult:    最终输出结果
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from haiji.agent.definition import AgentDefinition


class DesignRequest(BaseModel):
    """
    用户的 Agent 设计请求。

    包含用户的自然语言描述及可选配置项，作为 Generator 的输入。

    示例::

        request = DesignRequest(
            description="我想要一个懂投资的朋友，说话直接",
            preferred_mode="react",
            allow_rag=True,
        )
    """

    description: str
    """用户自然语言描述，如"我想要一个懂投资的朋友，说话直接"。"""

    preferred_mode: Optional[str] = None
    """用户偏好的执行模式（"direct" / "react" / "plan_and_execute"）。
    None 时让 LLM 自动判断。"""

    allow_rag: bool = True
    """是否允许绑定知识库。"""

    rag: Optional[Any] = None
    """可选的知识库实例（BaseKnowledgeBase）。"""

    rag_config: Optional[Any] = None
    """可选的 RagConfig 实例。"""

    model_config = {"arbitrary_types_allowed": True}


class DesignDraft(BaseModel):
    """
    LLM 生成的 Agent 草稿（中间产物）。

    字段宽松，允许为空，方便从 LLM JSON 输出中解析。
    Validator 负责对字段做结构性校验。

    示例::

        draft = DesignDraft(
            name="投资顾问",
            avatar="💰",
            bio="你的专属投资顾问",
            soul="# 性格\\n直接、犀利...",
            mode="react",
            tool_codes=["search_web"],
            tags=["金融", "投资"],
        )
    """

    name: str = ""
    """Agent 名称，简洁有辨识度。"""

    avatar: str = ""
    """头像，通常是一个 emoji，也可以是 URL。"""

    bio: str = ""
    """个性签名，展示在联系人卡片上，不超过 50 字符。"""

    soul: str = ""
    """soul 文档（Markdown 格式），描述 Agent 的性格、说话风格、禁止项。"""

    mode: str = "react"
    """执行模式："direct" / "react" / "plan_and_execute"。"""

    tool_codes: list[str] = []
    """从已注册 Tool 里选用的 tool code 列表。"""

    skill_codes: list[str] = []
    """从已注册 Skill 里选用的 skill code 列表。"""

    tags: list[str] = []
    """分类标签，2-4 个，用于联系人搜索和推荐。"""

    rag_enabled: bool = False
    """是否启用 RAG 知识库。"""

    reasoning: str = ""
    """LLM 的设计推理说明，调试用，不写入 AgentDefinition。"""


class ValidationError(BaseModel):
    """
    单条校验错误。

    由 DesignerValidator 返回，描述具体哪个字段出错以及原因。

    示例::

        error = ValidationError(field="name", message="name 不能为空")
    """

    field: str
    """出错的字段名。"""

    message: str
    """错误描述信息。"""


class DesignResult(BaseModel):
    """
    Designer.design() 的最终输出结果。

    ok=True 时包含 agent_code、definition 和 draft；
    ok=False 时包含 draft 和 errors。

    示例::

        result = await designer.design("我想要一个懂投资的朋友")
        if result.ok:
            print(f"Agent 注册成功：{result.agent_code}")
        else:
            for err in result.errors:
                print(f"  [{err.field}] {err.message}")
    """

    ok: bool
    """是否成功。True 表示生成、校验、注册全部成功。"""

    agent_code: str = ""
    """注册成功后的 Agent code（全局唯一）。"""

    definition: Optional[AgentDefinition] = None
    """注册后的 AgentDefinition，包含完整元数据。"""

    draft: Optional[DesignDraft] = None
    """LLM 生成的草稿，无论成功失败都会附带（方便调试）。"""

    errors: list[ValidationError] = []
    """校验错误列表，ok=False 时非空。"""

    model_config = {"arbitrary_types_allowed": True}
