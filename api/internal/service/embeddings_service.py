import os
from dataclasses import dataclass
from typing import Optional

import tiktoken
from injector import inject
from langchain_classic.embeddings import CacheBackedEmbeddings
from langchain_community.embeddings import DashScopeEmbeddings, ZhipuAIEmbeddings
from langchain_community.storage import RedisStore
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from redis import Redis

from .language_model_service import LanguageModelService

DEFAULT_EMBEDDING_PROVIDER = "openai"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSION = 1536

_EMBEDDING_MODEL_DIMENSIONS: dict[str, dict[str, int]] = {
    "openai": {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    },
    "tongyi": {
        "text-embedding-v1": 1536,
        "text-embedding-v2": 1536,
        "text-embedding-v3": 1024,
        "text-embedding-v4": 1024,
    },
    "zhipu": {
        "embedding-2": 1024,
        "embedding-3": 2048,
    },
}


@inject
@dataclass
class EmbeddingsService:
    """文本嵌入模型服务"""
    _store: RedisStore
    _embeddings: Embeddings
    _cache_backed_embeddings: CacheBackedEmbeddings

    def __init__(self, redis: Redis, language_model_service: LanguageModelService = None):
        """构造函数，初始化文本嵌入模型客户端、存储器、缓存客户端"""
        self._store = RedisStore(client=redis)
        self._language_model_service = language_model_service
        self._embeddings: Optional[Embeddings] = None
        self._cache_backed_embeddings: Optional[CacheBackedEmbeddings] = None
        self._dimension: Optional[int] = None
        self._provider: Optional[str] = None
        self._model: Optional[str] = None

    @classmethod
    def calculate_token_count(cls, query: str) -> int:
        """计算传入文本的token数"""
        encoding = tiktoken.encoding_for_model("gpt-3.5")
        return len(encoding.encode(query))

    def _resolve_provider_and_model(self) -> tuple[str, str]:
        """从环境变量读取嵌入 provider 与 model，缺省时回退默认值"""
        provider = (os.getenv("EMBEDDING_PROVIDER") or DEFAULT_EMBEDDING_PROVIDER).strip() or DEFAULT_EMBEDDING_PROVIDER
        model = (os.getenv("EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL).strip() or DEFAULT_EMBEDDING_MODEL
        return provider, model

    def _build_embeddings_for_provider(self, provider: str, model: str) -> Optional[Embeddings]:
        """根据 provider 构建对应的 Embeddings 实例，不支持的 provider 返回 None"""
        normalized = (provider or "").strip().lower()
        if normalized == "openai":
            return OpenAIEmbeddings(model=model)
        if normalized in ("tongyi", "dashscope"):
            return DashScopeEmbeddings(model=model)
        if normalized in ("zhipu", "zhipuai"):
            return ZhipuAIEmbeddings(model=model)
        return None

    def _build_embeddings(self) -> Embeddings:
        """根据配置构建嵌入模型，构建失败时降级为 OpenAI 默认模型"""
        provider, model = self._resolve_provider_and_model()
        try:
            embeddings = self._build_embeddings_for_provider(provider, model)
            if embeddings is not None:
                self._provider = provider
                self._model = model
                return embeddings
        except Exception:
            pass
        self._provider = DEFAULT_EMBEDDING_PROVIDER
        self._model = DEFAULT_EMBEDDING_MODEL
        return OpenAIEmbeddings(model=DEFAULT_EMBEDDING_MODEL)

    def _dimension_from_provider_config(self, provider: str, model: str) -> Optional[int]:
        """从 providers.yaml 配置的 embedding_models 读取维度，未配置时返回 None"""
        if self._language_model_service is None:
            return None
        try:
            manager = getattr(self._language_model_service, "language_model_manager", None)
            if manager is None:
                return None
            provider_entity = manager.get_provider(provider).provider_entity
            embedding_models = getattr(provider_entity, "embedding_models", []) or []
            for entry in embedding_models:
                if entry.get("name") == model:
                    dimension = entry.get("dimension")
                    if isinstance(dimension, int) and dimension > 0:
                        return dimension
        except Exception:
            return None
        return None

    def _resolve_dimension(self) -> int:
        """解析嵌入维度：优先 providers.yaml，其次内置映射，最后默认值"""
        provider, model = self._resolve_provider_and_model()
        dimension = self._dimension_from_provider_config(provider, model)
        if dimension:
            return dimension
        dimension = _EMBEDDING_MODEL_DIMENSIONS.get(provider, {}).get(model)
        if dimension:
            return dimension
        return DEFAULT_EMBEDDING_DIMENSION

    @property
    def embeddings(self) -> Embeddings:
        if self._embeddings is None:
            self._embeddings = self._build_embeddings()
        return self._embeddings

    @property
    def cache_backed_embeddings(self) -> CacheBackedEmbeddings:
        if self._cache_backed_embeddings is None:
            self._cache_backed_embeddings = CacheBackedEmbeddings.from_bytes_store(
                self.embeddings,
                self._store,
                namespace="embeddings",
                key_encoder="sha256",
            )
        return self._cache_backed_embeddings

    @property
    def embedding_dimension(self) -> int:
        if self._dimension is None:
            self._dimension = self._resolve_dimension()
        return self._dimension

    @property
    def embedding_provider(self) -> str:
        if self._provider is None:
            provider, _ = self._resolve_provider_and_model()
            return provider
        return self._provider

    @property
    def embedding_model(self) -> str:
        if self._model is None:
            _, model = self._resolve_provider_and_model()
            return model
        return self._model
