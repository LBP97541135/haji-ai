"""
server/routers/designer.py - Designer 路由

POST /api/designer/create → 用自然语言创建 Agent
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from server.deps import get_designer
from server.models import DesignerCreateRequest, DesignerCreateResponse
from server.agent_store import save_agent
from server.moment_store import create_birth_moment

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/designer/create", response_model=DesignerCreateResponse)
async def create_agent(req: DesignerCreateRequest):
    """用自然语言描述创建一个新 Agent"""
    designer = get_designer()
    try:
        result = await designer.design(req.description)
    except Exception as e:
        logger.error("[designer/create] 设计失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    if not result.ok:
        errors = [{"field": e.field, "message": e.message} for e in (result.errors or [])]
        return DesignerCreateResponse(ok=False, errors=errors)

    definition_dict = None
    if result.definition:
        definition_dict = result.definition.model_dump()
        # 持久化保存 Agent
        try:
            save_agent(result.definition)
        except Exception as e:
            logger.warning("[designer/create] 保存 Agent 失败: %s", e)
        # 自动发出生宣言（固定模板，零 token）
        try:
            create_birth_moment(
                agent_code=result.definition.code,
                agent_name=result.definition.name,
                bio=result.definition.bio or "",
            )
        except Exception as e:
            logger.warning("[designer/create] 创建出生宣言失败: %s", e)

    return DesignerCreateResponse(
        ok=True,
        agent_code=result.agent_code,
        definition=definition_dict,
    )
