"""
rag/definition.py - RAG（检索增强生成）数据结构定义

提供：
- RagConfig：RAG 检索配置（top_k、score_threshold、inject_mode、max_inject_chars）
- RagResult：检索结果（匹配切片 + 格式化后的注入文本）
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from haiji.knowledge.definition import DocumentChunk


class RagConfig(BaseModel):
    """
    RAG 检索配置。

    Attributes:
        top_k: 检索返回的最大切片数量，默认 5
        score_threshold: 相似度阈值，低于此值的结果过滤掉，默认 0.0（不过滤）
        inject_mode: 检索结果注入位置，"system_suffix" 追加到 system prompt，
            "user_prefix" 前置到用户消息，默认 "system_suffix"
        max_inject_chars: 注入内容最大字符数，防止 context 撑爆，默认 2000
    """

    top_k: int = Field(default=5, ge=1, le=50)
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    inject_mode: Literal["system_suffix", "user_prefix"] = "system_suffix"
    max_inject_chars: int = Field(default=2000, ge=100)


class RagResult(BaseModel):
    """
    RAG 检索结果。

    Attributes:
        chunks: 满足 score_threshold 的检索结果切片列表（按相似度降序）
        injected_text: 已格式化的注入文本（可直接插入 prompt），
            若无结果则为空字符串
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    chunks: list[DocumentChunk] = Field(default_factory=list)
    injected_text: str = ""
