"""
sse - 流式事件发射器

解耦 Agent 执行层和输出层。Agent 发出事件，调用方消费事件。

示例：
    from haiji.sse import SseEventEmitter, SseEvent, SseEventType

    emitter = SseEventEmitter()

    # Agent 侧
    await emitter.emit_token("你好")
    await emitter.emit_done()

    # 消费侧
    async for event in emitter.events():
        if event.type == SseEventType.TOKEN:
            print(event.message, end="")
"""

from haiji.sse.base import SseEventEmitter
from haiji.sse.definition import SseEvent, SseEventType

__all__ = ["SseEventEmitter", "SseEvent", "SseEventType"]
