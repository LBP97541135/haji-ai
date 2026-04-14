"""
designer/__init__.py - Designer 模块公共入口

Designer 模块让用户用自然语言描述一个 AI 联系人，
自动完成生成（Generator）→ 验证（Validator）→ 注册（Registrar）三步流程，
无需手动编写代码即可创建新的 Agent。

使用示例::

    from haiji.designer import Designer, DesignRequest, DesignDraft, DesignResult

    designer = Designer(llm_client=my_llm_client)
    result = await designer.design("一个懂投资的朋友，说话直接")
    if result.ok:
        print(result.agent_code)
"""

from haiji.designer.designer import Designer
from haiji.designer.definition import (
    DesignDraft,
    DesignRequest,
    DesignResult,
    ValidationError,
)

__all__ = [
    "Designer",
    "DesignRequest",
    "DesignDraft",
    "DesignResult",
    "ValidationError",
]
