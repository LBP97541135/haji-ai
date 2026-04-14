"""
knowledge/embedder.py - 文本向量化接口

提供：
- BaseEmbedder：抽象基类，定义 embed / embed_batch 接口
- OpenAIEmbedder：基于 openai SDK 的向量化实现
- QwenEmbedder：基于 MaaS 平台（qwen3-embedding-8b）的向量化实现，支持批量
- MockEmbedder：固定维度随机向量，仅用于测试
"""

from __future__ import annotations

import logging
import math
import random
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class BaseEmbedder(ABC):
    """
    文本向量化抽象基类。

    所有 Embedder 实现必须继承此类并实现 embed / embed_batch。
    """

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """
        将单段文本向量化。

        Args:
            text: 待向量化文本

        Returns:
            list[float]: 向量表示
        """
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        批量向量化文本。

        默认实现为逐条调用 embed()；子类可重写以使用批量 API 提升效率。

        Args:
            texts: 待向量化文本列表

        Returns:
            list[list[float]]: 各文本对应向量列表，顺序与输入一致
        """
        results: list[list[float]] = []
        for text in texts:
            results.append(await self.embed(text))
        return results


class OpenAIEmbedder(BaseEmbedder):
    """
    基于 OpenAI Embeddings API 的向量化实现。

    从全局 HaijiConfig 读取 api_key / base_url / embedding_model，
    使用 openai.AsyncOpenAI 异步客户端。

    Example:
        >>> from haiji.config import get_config
        >>> embedder = OpenAIEmbedder()
        >>> vector = await embedder.embed("hello world")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        """
        初始化 OpenAIEmbedder。

        Args:
            api_key: OpenAI API Key，None 时从 HaijiConfig 读取
            base_url: API 地址，None 时从 HaijiConfig 读取
            model: Embedding 模型名，None 时从 HaijiConfig 读取
        """
        from haiji.config import get_config

        config = get_config()
        self._api_key = api_key or config.api_key
        self._base_url = base_url or getattr(config, "embedding_base_url", config.llm_base_url)
        self._model = model or getattr(config, "embedding_model", "text-embedding-3-small")
        self._client: object = None  # lazy init

    def _get_client(self) -> object:
        """懒加载 AsyncOpenAI 客户端。"""
        if self._client is None:
            from openai import AsyncOpenAI  # type: ignore[import-untyped]

            kwargs: dict = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    async def embed(self, text: str) -> list[float]:
        """
        调用 OpenAI Embeddings API 向量化单段文本。

        Args:
            text: 待向量化文本

        Returns:
            list[float]: 向量表示
        """
        client = self._get_client()
        logger.debug("OpenAIEmbedder.embed: model=%s, text_len=%d", self._model, len(text))
        from openai import AsyncOpenAI  # type: ignore[import-untyped]

        response = await client.embeddings.create(  # type: ignore[union-attr]
            input=text,
            model=self._model,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        批量调用 OpenAI Embeddings API（一次请求）。

        Args:
            texts: 待向量化文本列表

        Returns:
            list[list[float]]: 各文本对应向量列表
        """
        if not texts:
            return []
        client = self._get_client()
        logger.debug(
            "OpenAIEmbedder.embed_batch: model=%s, count=%d", self._model, len(texts)
        )
        response = await client.embeddings.create(  # type: ignore[union-attr]
            input=texts,
            model=self._model,
        )
        # OpenAI 返回的 data 按 index 排序
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in sorted_data]


class QwenEmbedder(BaseEmbedder):
    """
    基于 MaaS 平台（qwen3-embedding-8b）的向量化实现。

    通过 httpx 异步调用小红书内部 MaaS 服务，支持按 batch_size 分批处理，
    避免单次请求过大。

    向量维度：4096（qwen3-embedding-8b 固定输出维度）

    API 规格：
    - URL: {base_url}/embeddings
    - Headers: Authorization: Bearer {api_key}, Content-Type: application/json
    - Body: {"model": "qwen3-embedding-8b", "input": [...], "encoding_format": "float"}
    - 返回：response["data"][i]["embedding"]

    Example:
        >>> embedder = QwenEmbedder(api_key="sk-xxx", base_url="https://maas.devops.xiaohongshu.com/v1")
        >>> vector = await embedder.embed("hello world")
        >>> len(vector)
        4096
        >>> vectors = await embedder.embed_batch(["text1", "text2", "text3"])
        >>> len(vectors)
        3
    """

    _DEFAULT_MODEL = "qwen3-embedding-8b"
    _DEFAULT_BATCH_SIZE = 32
    _EMBEDDING_DIM = 4096  # qwen3-embedding-8b 固定维度

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = _DEFAULT_MODEL,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        """
        初始化 QwenEmbedder。

        Args:
            api_key:    MaaS 平台 API Key
            base_url:   MaaS API 地址（如 "https://maas.devops.xiaohongshu.com/v1"）
            model:      Embedding 模型名，默认 "qwen3-embedding-8b"
            batch_size: 单次 API 调用的最大文本数量，默认 32
        """
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._batch_size = batch_size

    async def embed(self, text: str) -> list[float]:
        """
        将单段文本向量化（调用 MaaS embedding API）。

        Args:
            text: 待向量化文本

        Returns:
            list[float]: 长度为 4096 的向量

        Raises:
            httpx.HTTPStatusError: API 返回非 2xx 状态码
            httpx.RequestError:    网络请求失败
        """
        results = await self._call_api([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        批量向量化文本，自动按 batch_size 分批调用 MaaS API。

        Args:
            texts: 待向量化文本列表

        Returns:
            list[list[float]]: 各文本对应向量列表，顺序与输入一致

        Raises:
            httpx.HTTPStatusError: API 返回非 2xx 状态码
            httpx.RequestError:    网络请求失败
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            logger.debug(
                "QwenEmbedder.embed_batch: batch %d/%d, size=%d",
                i // self._batch_size + 1,
                (len(texts) + self._batch_size - 1) // self._batch_size,
                len(batch),
            )
            batch_embeddings = await self._call_api(batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    async def _call_api(self, texts: list[str]) -> list[list[float]]:
        """
        调用 MaaS Embeddings API。

        Args:
            texts: 待向量化文本列表（不超过 batch_size 条）

        Returns:
            list[list[float]]: 向量列表，顺序与输入一致
        """
        import httpx

        url = f"{self._base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "input": texts,
            "encoding_format": "float",
        }

        logger.debug("QwenEmbedder._call_api: url=%s, input_count=%d", url, len(texts))

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        # data["data"] 是按 index 排序的结果列表
        # 按 index 排序，确保顺序与输入一致
        items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]


class MockEmbedder(BaseEmbedder):
    """
    固定维度随机向量 Embedder，仅用于测试。

    为保证测试可复现，支持传入随机种子；每次 embed() 调用基于
    文本内容的哈希生成确定性向量（相同文本返回相同向量）。

    Example:
        >>> embedder = MockEmbedder(dim=128)
        >>> vector = await embedder.embed("hello")
        >>> len(vector)
        128
    """

    def __init__(self, dim: int = 1536, seed: Optional[int] = None) -> None:
        """
        初始化 MockEmbedder。

        Args:
            dim: 向量维度，默认 1536（与 text-embedding-3-small 一致）
            seed: 随机种子，None 时使用文本哈希作为种子
        """
        self.dim = dim
        self.seed = seed

    async def embed(self, text: str) -> list[float]:
        """
        生成固定维度的随机向量（确定性：相同文本 → 相同向量）。

        Args:
            text: 输入文本（用于计算种子）

        Returns:
            list[float]: 单位化随机向量
        """
        seed = self.seed if self.seed is not None else hash(text) % (2**31)
        rng = random.Random(seed)
        raw = [rng.gauss(0, 1) for _ in range(self.dim)]
        norm = math.sqrt(sum(x * x for x in raw))
        if norm == 0.0:
            return [0.0] * self.dim
        return [x / norm for x in raw]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        批量生成随机向量。

        Args:
            texts: 文本列表

        Returns:
            list[list[float]]: 各文本对应向量列表
        """
        return [await self.embed(t) for t in texts]
