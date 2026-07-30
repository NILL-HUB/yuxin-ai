import logging
import threading
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import tiktoken
from injector import inject
from langchain_classic.embeddings import CacheBackedEmbeddings
from langchain_community.storage import RedisStore
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from redis import Redis

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_DIMENSION = 1536

_EMBEDDING_MODEL_DIMENSIONS: dict[str, dict[str, int]] = {
    "openai": {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    },
    "SiliconFlow": {
        "Qwen/Qwen3-Embedding-8B": 4096,
        "BAAI/bge-large-zh-v1.5": 1024,
        "BAAI/bge-m3": 1024,
        "netease-youdao/bce-embedding-base_v1": 768,
        "Pro/BAAI/bge-m3": 1024,
    },
}


@inject
@dataclass
class EmbeddingsService:
    """文本嵌入模型服务"""
    _store: RedisStore
    _embeddings: Embeddings
    _cache_backed_embeddings: CacheBackedEmbeddings

    def __init__(self, redis: Redis):
        """构造函数，初始化文本嵌入模型客户端、存储器、缓存客户端"""
        self._store = RedisStore(client=redis)
        self._embeddings: Optional[Embeddings] = None
        self._cache_backed_embeddings: Optional[CacheBackedEmbeddings] = None
        self._dimension: Optional[int] = None
        self._provider: Optional[str] = None
        self._model: Optional[str] = None
        # 按 model_id 缓存的 embeddings 客户端 {model_id_str: (Embeddings, dimension)}
        self._model_embeddings_cache: dict[str, tuple[Embeddings, int]] = {}
        self._model_cache_lock = threading.Lock()

    @classmethod
    def calculate_token_count(cls, query: str) -> int:
        """计算传入文本的token数"""
        encoding = tiktoken.encoding_for_model("gpt-3.5")
        return len(encoding.encode(query))

    def _resolve_embeddings_config(self) -> dict[str, str]:
        """从数据库查询 embedding 模型配置（provider/model/api_key/base_url）。

        替代原来从环境变量 EMBEDDING_PROVIDER/EMBEDDING_MODEL 读取的方式，
        统一走 admin 数据库管理。

        返回字典额外包含 ``embedding_dimension``（DB 配置的维度，0 表示未配置）和
        ``model_id``（DB 模型记录 ID）。
        """
        from .language_model_service import LanguageModelService

        creds = LanguageModelService.get_provider_credentials(model_type="embedding")
        if not creds or not creds.get("api_key") or not creds.get("model"):
            raise RuntimeError(
                "数据库无可用 embedding 模型或缺少 api_key，请在 admin 中配置 "
                "model_type=embedding 的模型及对应 key"
            )
        # 补充查询 embedding_dimension 和 model_id
        creds = dict(creds)
        creds.setdefault("embedding_dimension", 0)
        creds.setdefault("model_id", None)
        try:
            from internal.model.model_pool_entity import ModelPoolConfig
            from internal.extension.database_extension import db
            model_record = (
                db.session.query(ModelPoolConfig)
                .filter_by(
                    provider=creds["provider"],
                    model_name=creds["model"],
                    status="active",
                    model_type="embedding",
                )
                .order_by(ModelPoolConfig.priority.desc())
                .first()
            )
            if model_record is not None:
                creds["model_id"] = str(model_record.id)
                if model_record.embedding_dimension and model_record.embedding_dimension > 0:
                    creds["embedding_dimension"] = int(model_record.embedding_dimension)
        except Exception:
            logger.warning("_resolve_embeddings_config: 查询 embedding_dimension 失败", exc_info=True)
        return creds

    def _build_embeddings(self) -> Embeddings:
        """从数据库配置构建嵌入模型。

        数据库中的 embedding 模型均为 compatible_api=openai，统一用 OpenAIEmbeddings 构造，
        传入数据库查询的 api_key 和 base_url。

        当配置维度小于模型原生维度时，传 dimensions 参数触发 MRL 降维，
        使高维模型（如 Qwen3-Embedding-8B 4096维）可降维到 ≤2000 使用 HNSW 索引。
        """
        config = self._resolve_embeddings_config()
        self._provider = config["provider"]
        self._model = config["model"]
        db_dim = config.get("embedding_dimension", 0)
        if db_dim and db_dim > 0:
            self._dimension = db_dim

        # MRL 降维：配置维度 < 模型原生维度时传 dimensions 参数
        native_dim = _EMBEDDING_MODEL_DIMENSIONS.get(self._provider, {}).get(self._model)
        effective_dim = self._dimension if self._dimension and self._dimension > 0 else native_dim
        kwargs: dict = {
            "model": config["model"],
            "api_key": config["api_key"],
            "base_url": config.get("base_url") or None,
        }
        # 仅当配置维度有效且小于原生维度时传 dimensions（避免不支持的模型报错）
        if (
            effective_dim
            and effective_dim > 0
            and native_dim
            and native_dim > 0
            and effective_dim < native_dim
        ):
            kwargs["dimensions"] = effective_dim
            logger.info(
                "_build_embeddings: MRL 降维 %s/%s 原生 %d -> 实际 %d",
                self._provider, self._model, native_dim, effective_dim,
            )
        embeddings = OpenAIEmbeddings(**kwargs)
        return embeddings

    def _resolve_dimension(self) -> int:
        """解析嵌入维度。

        优先级：
            1. _build_embeddings() 时从 DB 读取的 embedding_dimension（已存入 self._dimension）
            2. 内置映射字典 _EMBEDDING_MODEL_DIMENSIONS
            3. DEFAULT_EMBEDDING_DIMENSION (1536)
        """
        # DB 配置优先（_build_embeddings 时已填充）
        if self._dimension is not None and self._dimension > 0:
            return self._dimension
        # 内置映射兜底
        provider = self._provider or ""
        model = self._model or ""
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
            # 触发 _build_embeddings 从数据库加载并填充 _provider
            _ = self.embeddings
        return self._provider or ""

    @property
    def embedding_model(self) -> str:
        if self._model is None:
            # 触发 _build_embeddings 从数据库加载并填充 _model
            _ = self.embeddings
        return self._model or ""

    # =========================================================
    # 按 model_id 获取 embeddings 客户端（支持每个 App/KB 绑定不同 embedding 模型）
    # =========================================================

    @classmethod
    def get_dimension_for_model_id(cls, model_id: UUID | str | None) -> int:
        """查询指定 embedding 模型的向量维度。

        优先级：
            1. ModelPoolConfig.embedding_dimension（DB 配置）
            2. _EMBEDDING_MODEL_DIMENSIONS 内置字典
            3. DEFAULT_EMBEDDING_DIMENSION (1536)

        Args:
            model_id: 模型 ID，None 时返回系统默认维度
        """
        if model_id is None:
            return DEFAULT_EMBEDDING_DIMENSION
        try:
            from internal.model.model_pool_entity import ModelPoolConfig
            from internal.extension.database_extension import db

            model = db.session.query(ModelPoolConfig).filter_by(id=model_id).first()
            if model is None:
                return DEFAULT_EMBEDDING_DIMENSION
            if model.embedding_dimension and model.embedding_dimension > 0:
                return int(model.embedding_dimension)
            # 内置字典兜底
            dim = _EMBEDDING_MODEL_DIMENSIONS.get(model.provider, {}).get(model.model_name)
            return dim or DEFAULT_EMBEDDING_DIMENSION
        except Exception:
            logger.warning("get_dimension_for_model_id: 查询失败 model_id=%s", model_id, exc_info=True)
            return DEFAULT_EMBEDDING_DIMENSION

    def get_embeddings_for_model_id(
        self, model_id: UUID | str | None
    ) -> tuple[Embeddings, int]:
        """返回指定 model_id 的 (embeddings 客户端, 维度)。

        model_id 为 None 时返回系统默认 embeddings 客户端和维度。
        客户端按 model_id 缓存，避免重复构建。

        Args:
            model_id: embedding 模型 ID

        Returns:
            (Embeddings 实例, dimension)
        """
        if model_id is None:
            # 系统默认
            return self.embeddings, self.embedding_dimension

        model_id_str = str(model_id)
        with self._model_cache_lock:
            cached = self._model_embeddings_cache.get(model_id_str)
            if cached is not None:
                return cached

        # 查 DB 获取模型配置
        try:
            from internal.model.model_pool_entity import ModelPoolConfig, ModelKeyConfig
            from internal.model.model_provider_entity import ModelProviderConfig
            from internal.extension.database_extension import db
            from internal.service.admin_model_pool_service import _decrypt_key_value

            model = db.session.query(ModelPoolConfig).filter_by(
                id=model_id_str, status="active", model_type="embedding"
            ).first()
            if model is None:
                logger.warning(
                    "get_embeddings_for_model_id: 模型不存在或非 active embedding 类型 "
                    "model_id=%s，回退系统默认",
                    model_id_str,
                )
                return self.embeddings, self.embedding_dimension

            key = db.session.query(ModelKeyConfig).filter(
                ModelKeyConfig.provider == model.provider,
                ModelKeyConfig.status == "active",
            ).order_by(
                ModelKeyConfig.used_credits.asc(),
                ModelKeyConfig.created_at.asc(),
            ).first()
            if key is None:
                logger.warning(
                    "get_embeddings_for_model_id: 无可用 API key provider=%s，回退系统默认",
                    model.provider,
                )
                return self.embeddings, self.embedding_dimension

            provider_config = db.session.query(ModelProviderConfig).filter_by(
                name=model.provider
            ).first()

            api_key = _decrypt_key_value(key.key_value_encrypted)
            base_url = (provider_config.default_base_url if provider_config else "") or None

            # 解析维度
            if model.embedding_dimension and model.embedding_dimension > 0:
                dimension = int(model.embedding_dimension)
            else:
                dimension = _EMBEDDING_MODEL_DIMENSIONS.get(model.provider, {}).get(
                    model.model_name
                ) or DEFAULT_EMBEDDING_DIMENSION

            # MRL 降维：配置维度 < 模型原生维度时传 dimensions 参数
            native_dim = _EMBEDDING_MODEL_DIMENSIONS.get(model.provider, {}).get(model.model_name)
            kwargs: dict = {
                "model": model.model_name,
                "api_key": api_key,
                "base_url": base_url or None,
            }
            if (
                dimension
                and dimension > 0
                and native_dim
                and native_dim > 0
                and dimension < native_dim
            ):
                kwargs["dimensions"] = dimension
                logger.info(
                    "get_embeddings_for_model_id: MRL 降维 %s/%s 原生 %d -> 实际 %d",
                    model.provider, model.model_name, native_dim, dimension,
                )
            embeddings = OpenAIEmbeddings(**kwargs)

            result = (embeddings, dimension)
            with self._model_cache_lock:
                self._model_embeddings_cache[model_id_str] = result
            return result
        except Exception:
            logger.warning(
                "get_embeddings_for_model_id: 构建失败 model_id=%s，回退系统默认",
                model_id_str,
                exc_info=True,
            )
            return self.embeddings, self.embedding_dimension

    def embed_query_with_model(
        self, query: str, model_id: UUID | str | None
    ) -> tuple[list[float], int]:
        """使用指定 model_id 对查询文本进行向量化。

        Args:
            query: 查询文本
            model_id: embedding 模型 ID，None 时使用系统默认

        Returns:
            (向量, 维度)
        """
        embeddings, dimension = self.get_embeddings_for_model_id(model_id)
        vector = embeddings.embed_query(query)
        return vector, dimension

    def invalidate_model_cache(self, model_id: UUID | str | None = None) -> None:
        """失效按 model_id 缓存的 embeddings 客户端。

        在 admin 更新/删除 embedding 模型配置时调用。
        """
        with self._model_cache_lock:
            if model_id is not None:
                self._model_embeddings_cache.pop(str(model_id), None)
            else:
                self._model_embeddings_cache.clear()
