"""sse 模块单元测试 + 集成测试"""

import pytest
import asyncio
from haiji.sse import SseEventEmitter, SseEvent, SseEventType


# ==================== 单元测试：事件构造 ====================

def test_token_event():
    event = SseEvent.token("你好")
    assert event.type == SseEventType.TOKEN
    assert event.message == "你好"


def test_tool_call_event():
    event = SseEvent.tool_call("search_web", "call_1", '{"query": "天气"}')
    assert event.type == SseEventType.TOOL_CALL
    assert event.tool_name == "search_web"
    assert event.tool_call_id == "call_1"


def test_done_event():
    event = SseEvent.done("最终答案")
    assert event.type == SseEventType.DONE
    assert event.message == "最终答案"


def test_error_event():
    event = SseEvent.error("出错了")
    assert event.type == SseEventType.ERROR
    assert event.message == "出错了"


# ==================== 单元测试：发射器 ====================

@pytest.mark.asyncio
async def test_emitter_collects_tokens():
    emitter = SseEventEmitter()

    async def produce():
        await emitter.emit_token("你")
        await emitter.emit_token("好")
        await emitter.emit_done()

    asyncio.create_task(produce())

    collected = []
    async for event in emitter.events():
        collected.append(event)

    tokens = [e for e in collected if e.type == SseEventType.TOKEN]
    assert len(tokens) == 2
    assert tokens[0].message == "你"
    assert tokens[1].message == "好"


@pytest.mark.asyncio
async def test_emitter_done_stops_iteration():
    emitter = SseEventEmitter()

    async def produce():
        await emitter.emit_token("hello")
        await emitter.emit_done("完成")

    asyncio.create_task(produce())

    events = []
    async for event in emitter.events():
        events.append(event)

    assert events[-1].type == SseEventType.DONE
    assert emitter.is_finished


@pytest.mark.asyncio
async def test_emitter_error_stops_iteration():
    emitter = SseEventEmitter()

    async def produce():
        await emitter.emit_error("出错了")

    asyncio.create_task(produce())

    events = []
    async for event in emitter.events():
        events.append(event)

    assert events[-1].type == SseEventType.ERROR
    assert emitter.is_finished


# ==================== 集成测试：pipe 链 ====================

@pytest.mark.asyncio
async def test_pipe_transforms_event():
    emitter = SseEventEmitter()

    async def upper_pipe(event: SseEvent):
        if event.type == SseEventType.TOKEN and event.message:
            return SseEvent.token(event.message.upper())
        return event

    emitter.add_pipe(upper_pipe)

    async def produce():
        await emitter.emit_token("hello")
        await emitter.emit_done()

    asyncio.create_task(produce())

    tokens = []
    async for event in emitter.events():
        if event.type == SseEventType.TOKEN:
            tokens.append(event.message)

    assert tokens == ["HELLO"]


@pytest.mark.asyncio
async def test_pipe_can_filter_event():
    emitter = SseEventEmitter()

    async def filter_thinking(event: SseEvent):
        if event.type == SseEventType.THINKING:
            return None  # 过滤掉思考事件
        return event

    emitter.add_pipe(filter_thinking)

    async def produce():
        await emitter.emit_thinking("我在思考...")
        await emitter.emit_token("结果")
        await emitter.emit_done()

    asyncio.create_task(produce())

    events = []
    async for event in emitter.events():
        events.append(event)

    types = [e.type for e in events]
    assert SseEventType.THINKING not in types
    assert SseEventType.TOKEN in types
