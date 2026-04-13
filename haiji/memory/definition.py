"""
memory/definition.py - 会话记忆数据结构
"""

from pydantic import BaseModel
from haiji.llm.definition import LlmMessage


class SessionHistory(BaseModel):
    """单个会话的消息历史"""
    session_id: str
    messages: list[LlmMessage] = []

    def add(self, message: LlmMessage) -> None:
        self.messages.append(message)

    def get_recent(self, n: int) -> list[LlmMessage]:
        """获取最近 n 条消息"""
        return self.messages[-n:] if n < len(self.messages) else self.messages[:]

    def clear(self) -> None:
        self.messages.clear()
