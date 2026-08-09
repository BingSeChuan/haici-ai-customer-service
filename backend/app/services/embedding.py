"""Embedding 抽象层：可插拔 Provider。

- local_bge: 本地 sentence-transformers bge-small-zh-v1.5（免注册，中文优化，CPU 可跑）
- openai_compatible: 任意 OpenAI 兼容 embedding 端点（如 SiliconFlow 免费 bge-m3）

DeepSeek 不提供 embedding API，因此向量化与对话 LLM 解耦。
"""
import logging
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Sequence

import numpy as np

from ..config import settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        ...

    @property
    @abstractmethod
    def dim(self) -> int:
        ...


class LocalBgeProvider(EmbeddingProvider):
    """本地 bge 系列模型（默认 bge-small-zh-v1.5，24M/768 维，CPU 友好）。

    可通过 EMBEDDING_MODEL 配置切换为任意 bge 系列（如 bge-large-zh-v1.5 /
    bge-m3），企业部署时按精度/算力权衡选择。
    """

    def __init__(self):
        import os

        # 中国大陆网络默认走 hf-mirror.com 镜像
        os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
        from sentence_transformers import SentenceTransformer

        model_name = settings.embedding_model or "BAAI/bge-small-zh-v1.5"
        logger.info("加载本地 embedding 模型 %s ...", model_name)
        self._model = SentenceTransformer(model_name)
        self._dim = self._model.get_sentence_embedding_dimension()
        logger.info("embedding 模型加载完成，维度=%s", self._dim)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        # bge 系列建议加 query 前缀提高检索精度（官方推荐）
        prefixed = [f"为这个句子生成表示以用于检索相关文章：{t}" for t in texts]
        vectors = self._model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
        return vectors.astype(np.float32).tolist()

    @property
    def dim(self) -> int:
        return self._dim


class OpenAICompatibleProvider(EmbeddingProvider):
    """OpenAI 兼容 embedding 端点（SiliconFlow bge-m3 / OpenAI text-embedding-3 等）。"""

    def __init__(self):
        if not settings.embedding_api_key or not settings.embedding_base_url:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=openai_compatible 时需配置 EMBEDDING_API_KEY / EMBEDDING_BASE_URL / EMBEDDING_MODEL"
            )
        from openai import OpenAI

        self._client = OpenAI(
            api_key=settings.embedding_api_key, base_url=settings.embedding_base_url, timeout=30
        )
        self._model = settings.embedding_model or "BAAI/bge-m3"
        self._dim = None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self._model, input=list(texts))
        # OpenAI 兼容接口返回顺序与输入一致
        vectors = [d.embedding for d in resp.data]
        if self._dim is None and vectors:
            self._dim = len(vectors[0])
        return vectors

    @property
    def dim(self) -> int:
        return self._dim or 1024


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    provider = settings.embedding_provider
    logger.info("初始化 embedding provider: %s", provider)
    if provider == "openai_compatible":
        return OpenAICompatibleProvider()
    return LocalBgeProvider()
