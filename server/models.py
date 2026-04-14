"""
server/models.py - Pydantic 请求/响应模型
"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """聊天请求"""
    agent_code: str = Field(..., description="Agent 标识")
    session_id: str = Field(default="", description="会话 ID，留空则由服务端生成")
    user_id: str = Field(default="user_001", description="用户 ID")
    message: str = Field(..., description="用户消息")


class ChatResponse(BaseModel):
    """非流式聊天响应"""
    session_id: str
    content: str
    agent_code: str


class AgentSummary(BaseModel):
    """Agent 列表中单个 Agent 的摘要信息"""
    code: str
    name: str
    avatar: str
    bio: str
    tags: list[str]
    mode: str


class AgentDetail(BaseModel):
    """Agent 详情（包含 AgentDefinition 所有字段）"""
    code: str
    name: str
    avatar: str
    bio: str
    soul: str
    mode: str
    system_prompt: str
    required_skill_codes: list[str]
    required_tool_codes: list[str]
    max_rounds: int
    tags: list[str]


class DesignerCreateRequest(BaseModel):
    """创建 Agent 请求"""
    description: str = Field(..., description="用自然语言描述想要的 Agent")


class DesignerCreateResponse(BaseModel):
    """创建 Agent 响应"""
    ok: bool
    agent_code: Optional[str] = None
    definition: Optional[dict[str, Any]] = None
    errors: Optional[list[dict[str, str]]] = None


class HistoryMessage(BaseModel):
    """单条历史消息"""
    role: str
    content: str


class SessionHistoryResponse(BaseModel):
    """会话历史响应"""
    messages: list[HistoryMessage]
