"""llm 模块单元测试（LLM 调用全部 Mock，不真实调用）"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from haiji.llm import LlmMessage, LlmRequest, LlmResponse, LlmConfig, FunctionDef, LlmTool
from haiji.llm.impl.openai import OpenAILlmClient
from haiji.config import HaijiConfig


@pytest.fixture
def config():
    return HaijiConfig(api_key="sk-test", llm_model="gpt-4o")


@pytest.fixture
def client(config):
    with patch("openai.AsyncOpenAI"):
        return OpenAILlmClient(config)


def test_llm_message_constructors():
    assert LlmMessage.system("你好").role.value == "system"
    assert LlmMessage.user("问题").role.value == "user"
    assert LlmMessage.assistant("回答").role.value == "assistant"
    assert LlmMessage.tool_result("call_1", "结果").role.value == "tool"


def test_llm_config_merge():
    runtime = LlmConfig(model="gpt-4o-mini")
    agent = LlmConfig(model="gpt-4o", temperature=0.5)
    global_cfg = LlmConfig(model="gpt-3.5-turbo", temperature=0.7, max_tokens=2048)

    merged = LlmConfig.merge(runtime, agent, global_cfg)
    assert merged.model == "gpt-4o-mini"       # runtime 优先
    assert merged.temperature == 0.5            # agent 覆盖 global
    assert merged.max_tokens == 2048            # global 兜底


@pytest.mark.asyncio
async def test_chat_returns_response(client):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "你好！"
    mock_response.choices[0].finish_reason = "stop"
    client._client.chat.completions.create = AsyncMock(return_value=mock_response)

    request = LlmRequest(messages=[LlmMessage.user("你好")], stream=False)
    response = await client.chat(request)
    assert response.content == "你好！"
    assert response.finish_reason == "stop"


@pytest.mark.asyncio
async def test_chat_with_tools_returns_tool_calls(client):
    mock_tc = MagicMock()
    mock_tc.id = "call_1"
    mock_tc.function.name = "search_web"
    mock_tc.function.arguments = '{"query": "天气"}'

    mock_response = MagicMock()
    mock_response.choices[0].message.content = None
    mock_response.choices[0].message.tool_calls = [mock_tc]
    mock_response.choices[0].finish_reason = "tool_calls"
    client._client.chat.completions.create = AsyncMock(return_value=mock_response)

    tool = LlmTool(function=FunctionDef(name="search_web", description="搜索"))
    request = LlmRequest(messages=[LlmMessage.user("今天天气")], tools=[tool], stream=False)
    response = await client.chat_with_tools(request)

    assert response.tool_calls is not None
    assert response.tool_calls[0].name == "search_web"
    assert response.tool_calls[0].id == "call_1"
