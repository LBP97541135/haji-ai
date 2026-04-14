"""
api - haiji 框架的 HTTP 接口层

将 Agent 能力以 REST / SSE 形式暴露给外部客户端。

提供：
- HaijiServer：FastAPI 应用封装，对外暴露 /health、/chat、/chat/stream 接口
- ChatRequest：对话请求数据结构
- ChatResponse：非流式对话响应数据结构
- ApiError：统一的错误响应格式

快速开始::

    from haiji.api import HaijiServer, ChatRequest
    from haiji.agent import get_agent_registry
    from haiji.llm.impl.openai_client import OpenAILlmClient
    from haiji.config import get_config

    config = get_config()
    llm_client = OpenAILlmClient(config)
    server = HaijiServer(
        agent_registry=get_agent_registry(),
        llm_client=llm_client,
    )
    app = server.create_app()
    # uvicorn main:app --host 0.0.0.0 --port 8000
"""

from haiji.api.definition import ApiError, ChatRequest, ChatResponse
from haiji.api.server import HaijiServer

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "ApiError",
    "HaijiServer",
]
