"""
observer/definition.py - 可观测性数据结构

定义链路追踪、Token 统计所需的所有数据结构。
保持最底层，不依赖任何上层模块（agent / llm / tool 等）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class TokenUsage(BaseModel):
    """单次 LLM 调用的 Token 用量"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: "TokenUsage") -> "TokenUsage":
        """累加两个 TokenUsage，返回新对象。

        Args:
            other: 另一个 TokenUsage 对象。

        Returns:
            累加后的新 TokenUsage。

        示例::

            total = TokenUsage().add(usage1).add(usage2)
        """
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


class LlmCallSpan(BaseModel):
    """单次 LLM 调用的追踪记录（Span）"""

    span_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str
    agent_code: str
    model: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: float = 0.0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    error: Optional[str] = None


class ToolCallSpan(BaseModel):
    """单次 Tool 调用的追踪记录（Span）"""

    span_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str
    agent_code: str
    tool_code: str
    latency_ms: float = 0.0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    success: bool = True
    error: Optional[str] = None


class TraceRecord(BaseModel):
    """一次完整 Agent 执行的汇总记录"""

    trace_id: str
    agent_code: str
    session_id: str
    llm_spans: list[LlmCallSpan] = Field(default_factory=list)
    tool_spans: list[ToolCallSpan] = Field(default_factory=list)
    total_latency_ms: float = 0.0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None

    @property
    def total_tokens(self) -> TokenUsage:
        """计算属性：对所有 LlmCallSpan.usage 求和，不冗余存储。"""
        result = TokenUsage()
        for span in self.llm_spans:
            result = result.add(span.usage)
        return result
