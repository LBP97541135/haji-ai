"""
server/routers/profile.py - Profile 路由

GET /api/profile → 返回 LLM 配置和框架信息
"""
from fastapi import APIRouter
import os

router = APIRouter()


@router.get("/profile")
def get_profile():
    """返回当前 LLM 配置和框架信息"""
    return {
        "model": os.getenv("HAIJI_LLM_MODEL", "minimax-m2.7"),
        "base_url": os.getenv("HAIJI_LLM_BASE_URL", "https://maas.devops.xiaohongshu.com/v1"),
        "version": "0.1.0",
        "framework": "haji-ai",
    }
