"""
sse/base.py - SSE 事件发射器

SseEventEmitter 是 Agent 执行层和输出层之间的解耦桥梁。
Agent 只管 emit 事件，不关心事件怎么传给前端。
"""

from __future__ import annotations
import asyncio
import logging
from typing import Optional, AsyncGenerator, Callable, Awaitable
from haiji.sse.definition import SseEvent, SseEventType

logger = logging.getLogger(__name__)


class SseEventEmitter:
    """
    SSE 事件发射器。

    Agent 执行过程中通过此类发出所有事件（token、tool_call、done、error）。
    调用方通过 events() 异步迭代器消费事件。

    示例：
        emitter = SseEventEmitter()

        # Agent 侧：发出事件
        await emitter.emit_token("你好")
        await emitter.emit_done()

        # 消费侧：消费事件
        async for event in emitter.events():
            print(event.type, event.message)
    """

    def __init__(self, max_buffer: int = 512) -> None:
        self._queue: asyncio.Queue[Optional[SseEvent]] = asyncio.Queue(maxsize=max_buffer)
        self._finished = False
        self._pipes: list[Callable[[SseEvent], Awaitable[Optional[SseEvent]]]] = []

    # ==================== 事件发射（Agent 侧调用）====================

    async def emit(self, event: SseEvent) -> None:
        """发出任意事件，经过 pipe 链处理后放入队列"""
        processed = await self._run_pipes(event)
        if processed is not None:
            await self._queue.put(processed)

    async def emit_token(self, content: str) -> None:
        """发出 token 事件"""
        await self.emit(SseEvent.token(content))

    async def emit_tool_call(self, tool_name: str, tool_call_id: str, arguments: str) -> None:
        """发出工具调用事件"""
        await self.emit(SseEvent.tool_call(tool_name, tool_call_id, arguments))

    async def emit_tool_result(self, tool_name: str, tool_call_id: str, result: str) -> None:
        """发出工具结果事件"""
        await self.emit(SseEvent.tool_result(tool_name, tool_call_id, result))

    async def emit_thinking(self, content: str) -> None:
        """发出思考过程事件"""
        await self.emit(SseEvent.thinking(content))

    async def emit_done(self, final_content: Optional[str] = None) -> None:
        """发出完成事件，之后不再接受新事件"""
        await self.emit(SseEvent.done(final_content))
        self._finished = True
        await self._queue.put(None)  # 哨兵值，通知消费侧结束

    async def emit_error(self, message: str) -> None:
        """发出错误事件并结束"""
        await self.emit(SseEvent.error(message))
        self._finished = True
        await self._queue.put(None)

    # ==================== 事件消费（调用方侧）====================

    async def events(self) -> AsyncGenerator[SseEvent, None]:
        """
        异步迭代器，消费所有事件直到 done 或 error。

        示例：
            async for event in emitter.events():
                if event.type == SseEventType.TOKEN:
                    print(event.message, end="")
        """
        while True:
            event = await self._queue.get()
            if event is None:  # 哨兵值，结束
                break
            yield event

    # ==================== Pipe 链（可选的事件变换）====================

    def add_pipe(self, pipe: Callable[[SseEvent], Awaitable[Optional[SseEvent]]]) -> None:
        """
        添加事件处理管道。

        pipe 接收一个事件，返回处理后的事件（返回 None 表示过滤掉该事件）。

        示例：
            async def uppercase_pipe(event: SseEvent) -> Optional[SseEvent]:
                if event.type == SseEventType.TOKEN and event.message:
                    event.message = event.message.upper()
                return event

            emitter.add_pipe(uppercase_pipe)
        """
        self._pipes.append(pipe)

    async def _run_pipes(self, event: SseEvent) -> Optional[SseEvent]:
        """依次经过所有 pipe，返回最终事件（None 表示被过滤）"""
        current: Optional[SseEvent] = event
        for pipe in self._pipes:
            if current is None:
                break
            current = await pipe(current)
        return current

    @property
    def is_finished(self) -> bool:
        return self._finished
