"""EmbeddingTableRouter: 按向量维度路由到对应的存储表。

核心功能：
- 根据维度返回对应表名（user_memory_embedding_{dim} / knowledge_segment_embedding_{dim}）
- 自动建表（含 HNSW 余弦索引）
- 解析 App / 知识库绑定的 embedding 模型维度

表结构设计（轻量引用表）：
    user_memory_embedding_{dim}:
        id              UUID PK
        memory_id       UUID FK → user_memory.id (ON DELETE CASCADE)
        owner_account_id UUID FK → account.id (NOT NULL)
        embedding       Vector({dim}) NOT NULL
        embedding_node_id String(255)
        created_at      TIMESTAMP
        updated_at      TIMESTAMP

    knowledge_segment_embedding_{dim}:
        id               UUID PK
        segment_id       UUID FK → knowledge_segment.id (ON DELETE CASCADE)
        knowledge_base_id UUID FK → knowledge_base.id (NOT NULL)
        embedding        Vector({dim}) NOT NULL
        created_at       TIMESTAMP
        updated_at       TIMESTAMP

元数据（content/memory_type/scope 等）仍存储在原表 user_memory / knowledge_segment，
向量检索时通过 JOIN 原表获取元数据，避免数据冗余。

线程安全：_ensured_dimensions 与 _dimension_cache 使用锁保护。
"""

from __future__ import annotations

import logging
import threading
from typing import Optional
from uuid import UUID

from flask import current_app
from sqlalchemy import text

logger = logging.getLogger(__name__)

# 支持的维度范围（pgvector vector 类型最大 2000 维，HNSW/IVFFLAT 索引同此限制）
# 高维模型需通过 MRL 降维到 ≤2000 维使用（如 Qwen3-Embedding-8B 4096→1024）
MAX_SUPPORTED_DIMENSION = 2000
MIN_SUPPORTED_DIMENSION = 1

# 常用预设维度（前端下拉框选项，用户也可自定义 1-2000 任意值）
COMMON_DIMENSIONS: frozenset[int] = frozenset({
    512, 768, 1024, 1280, 1536, 2048,
})

# 表名前缀
_USER_MEMORY_PREFIX = "user_memory_embedding_"
_KNOWLEDGE_SEGMENT_PREFIX = "knowledge_segment_embedding_"

# 默认维度（系统默认 embedding 模型未配置维度时的兜底）
DEFAULT_FALLBACK_DIMENSION = 1536


class EmbeddingTableRouter:
    """按维度路由到对应向量表的服务。

    使用方式：
        router = EmbeddingTableRouter()
        dim = router.resolve_dimension_for_app(app_id)
        router.ensure_tables_for_dimension(dim)
        table_name = router.get_user_memory_table_name(dim)
        # 使用 raw SQL 操作 table_name
    """

    _instance: Optional["EmbeddingTableRouter"] = None
    _instance_lock = threading.Lock()

    def __init__(self, db=None):
        self._db = db
        self._ensured_dimensions: set[int] = set()
        self._dimension_cache: dict[str, int] = {}
        self._cache_lock = threading.Lock()

    # =========================================================
    # 单例获取
    # =========================================================

    @classmethod
    def get_instance(cls, db=None) -> "EmbeddingTableRouter":
        """获取单例实例（线程安全）。"""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(db=db)
            return cls._instance

    # =========================================================
    # 表名生成（纯函数，无副作用）
    # =========================================================

    @staticmethod
    def get_user_memory_table_name(dimension: int) -> str:
        """返回指定维度的 user_memory 向量表名。"""
        _validate_dimension(dimension)
        return f"{_USER_MEMORY_PREFIX}{dimension}"

    @staticmethod
    def get_knowledge_segment_table_name(dimension: int) -> str:
        """返回指定维度的 knowledge_segment 向量表名。"""
        _validate_dimension(dimension)
        return f"{_KNOWLEDGE_SEGMENT_PREFIX}{dimension}"

    # =========================================================
    # 自动建表
    # =========================================================

    def ensure_tables_for_dimension(self, dimension: int) -> bool:
        """确保指定维度的向量表已创建（含 HNSW 索引）。

        幂等：已创建过的维度不会重复执行 DDL。
        线程安全：使用 _cache_lock 保护。

        Args:
            dimension: 向量维度（必须在 SUPPORTED_DIMENSIONS 白名单中）

        Returns:
            True 表示表已就绪，False 表示建表失败
        """
        _validate_dimension(dimension)

        if dimension in self._ensured_dimensions:
            return True

        with self._cache_lock:
            if dimension in self._ensured_dimensions:
                return True

            db = self._get_db()
            if db is None:
                logger.warning("ensure_tables_for_dimension: db 不可用，无法建表")
                return False

            um_table = self.get_user_memory_table_name(dimension)
            ks_table = self.get_knowledge_segment_table_name(dimension)

            try:
                with db.engine.begin() as conn:
                    # 1. user_memory_embedding_{dim}
                    conn.execute(text(f"""
                        CREATE TABLE IF NOT EXISTS {um_table} (
                            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                            memory_id UUID REFERENCES user_memory(id) ON DELETE CASCADE,
                            owner_account_id UUID NOT NULL REFERENCES account(id),
                            embedding vector({dimension}) NOT NULL,
                            embedding_node_id VARCHAR(255),
                            created_at TIMESTAMP(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
                            updated_at TIMESTAMP(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0)
                        )
                    """))
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS {um_table}_owner_idx "
                        f"ON {um_table} (owner_account_id)"
                    ))
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS {um_table}_memory_idx "
                        f"ON {um_table} (memory_id)"
                    ))
                    # UNIQUE 索引：支持 ON CONFLICT (memory_id) DO UPDATE upsert
                    conn.execute(text(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS {um_table}_memory_id_uidx "
                        f"ON {um_table} (memory_id)"
                    ))
                    # HNSW 余弦相似度索引（维度 ≤ 2000 由 _validate_dimension 保证）
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS {um_table}_embedding_hnsw_idx "
                        f"ON {um_table} USING hnsw (embedding vector_cosine_ops)"
                    ))

                    # 2. knowledge_segment_embedding_{dim}
                    conn.execute(text(f"""
                        CREATE TABLE IF NOT EXISTS {ks_table} (
                            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                            segment_id UUID NOT NULL REFERENCES knowledge_segment(id) ON DELETE CASCADE,
                            knowledge_base_id UUID NOT NULL REFERENCES knowledge_base(id),
                            embedding vector({dimension}) NOT NULL,
                            created_at TIMESTAMP(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
                            updated_at TIMESTAMP(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0)
                        )
                    """))
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS {ks_table}_kb_idx "
                        f"ON {ks_table} (knowledge_base_id)"
                    ))
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS {ks_table}_segment_idx "
                        f"ON {ks_table} (segment_id)"
                    ))
                    # UNIQUE 索引：支持 ON CONFLICT (segment_id) DO UPDATE upsert
                    conn.execute(text(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS {ks_table}_segment_id_uidx "
                        f"ON {ks_table} (segment_id)"
                    ))
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS {ks_table}_embedding_hnsw_idx "
                        f"ON {ks_table} USING hnsw (embedding vector_cosine_ops)"
                    ))

                self._ensured_dimensions.add(dimension)
                logger.info(
                    "ensure_tables_for_dimension: 维度 %d 向量表已就绪 (%s, %s)",
                    dimension, um_table, ks_table,
                )
                return True
            except Exception:
                logger.warning(
                    "ensure_tables_for_dimension: 维度 %d 建表失败",
                    dimension,
                    exc_info=True,
                )
                return False

    # =========================================================
    # 维度解析（从 DB 配置读取）
    # =========================================================

    def resolve_dimension_for_app(self, app_id: UUID | str | None) -> int:
        """解析 App 绑定的 embedding 模型维度。

        优先级：
            1. app_config.embedding_model_id → ModelPoolConfig.embedding_dimension
            2. 系统默认 embedding 模型（priority 最高的 active 模型）的维度
            3. DEFAULT_FALLBACK_DIMENSION (1536)

        Args:
            app_id: 应用 ID，None 时直接走系统默认

        Returns:
            向量维度
        """
        if app_id is not None:
            cache_key = f"app:{app_id}"
            cached = self._get_cached_dimension(cache_key)
            if cached is not None:
                return cached

            dim = self._resolve_app_embedding_dimension(app_id)
            if dim is not None:
                self._set_cached_dimension(cache_key, dim)
                return dim

        # 回退到系统默认
        return self.resolve_system_default_dimension()

    def resolve_dimension_for_knowledge_base(self, kb_id: UUID | str | None) -> int:
        """解析知识库绑定的 embedding 模型维度。

        优先级：
            1. knowledge_base.embedding_model_id → ModelPoolConfig.embedding_dimension
            2. 系统默认 embedding 模型的维度
            3. DEFAULT_FALLBACK_DIMENSION (1536)

        Args:
            kb_id: 知识库 ID，None 时直接走系统默认

        Returns:
            向量维度
        """
        if kb_id is not None:
            cache_key = f"kb:{kb_id}"
            cached = self._get_cached_dimension(cache_key)
            if cached is not None:
                return cached

            dim = self._resolve_kb_embedding_dimension(kb_id)
            if dim is not None:
                self._set_cached_dimension(cache_key, dim)
                return dim

        return self.resolve_system_default_dimension()

    def resolve_system_default_dimension(self) -> int:
        """解析系统默认 embedding 模型的维度。

        从 DB 查询 priority 最高的 active embedding 模型，
        读取其 embedding_dimension 字段。
        """
        cache_key = "system_default"
        cached = self._get_cached_dimension(cache_key)
        if cached is not None:
            return cached

        dim = self._resolve_system_default_dimension_from_db()
        if dim is not None:
            self._set_cached_dimension(cache_key, dim)
            return dim

        return DEFAULT_FALLBACK_DIMENSION

    def invalidate_dimension_cache(self, scope: str = "all") -> None:
        """失效维度缓存。

        在 embedding 模型配置变更（创建/更新/删除）时调用。

        Args:
            scope: "all" 清空全部缓存，"system_default" 仅清系统默认
        """
        with self._cache_lock:
            if scope == "all":
                self._dimension_cache.clear()
            else:
                self._dimension_cache.pop(scope, None)

    # =========================================================
    # 维度解析内部实现
    # =========================================================

    def _resolve_app_embedding_dimension(self, app_id) -> Optional[int]:
        """从 app_config.embedding_model_id 解析维度。"""
        db = self._get_db()
        if db is None:
            return None
        try:
            from internal.model.app import AppConfig
            from internal.model.model_pool_entity import ModelPoolConfig

            # 查找 App 的已发布配置
            row = db.session.execute(
                text("""
                    SELECT ac.embedding_model_id
                    FROM app a
                    LEFT JOIN app_config ac ON a.app_config_id = ac.id
                    WHERE a.id = :app_id
                    LIMIT 1
                """),
                {"app_id": str(app_id)},
            ).first()

            if row and row.embedding_model_id:
                model = db.session.query(ModelPoolConfig).filter_by(
                    id=row.embedding_model_id
                ).first()
                if model and model.embedding_dimension and model.embedding_dimension > 0:
                    return int(model.embedding_dimension)

            return None
        except Exception:
            logger.warning(
                "_resolve_app_embedding_dimension: 解析失败 app_id=%s", app_id, exc_info=True
            )
            return None

    def _resolve_kb_embedding_dimension(self, kb_id) -> Optional[int]:
        """从 knowledge_base.embedding_model_id 解析维度。"""
        db = self._get_db()
        if db is None:
            return None
        try:
            from internal.model.knowledge import KnowledgeBase

            kb = db.session.query(KnowledgeBase).filter_by(id=kb_id).first()
            if kb and kb.embedding_model_id:
                from internal.model.model_pool_entity import ModelPoolConfig
                model = db.session.query(ModelPoolConfig).filter_by(
                    id=kb.embedding_model_id
                ).first()
                if model and model.embedding_dimension and model.embedding_dimension > 0:
                    return int(model.embedding_dimension)

            return None
        except Exception:
            logger.warning(
                "_resolve_kb_embedding_dimension: 解析失败 kb_id=%s", kb_id, exc_info=True
            )
            return None

    def _resolve_system_default_dimension_from_db(self) -> Optional[int]:
        """从 DB 查询系统默认 embedding 模型的维度。"""
        db = self._get_db()
        if db is None:
            return None
        try:
            from internal.model.model_pool_entity import ModelPoolConfig

            model = (
                db.session.query(ModelPoolConfig)
                .filter_by(status="active", model_type="embedding")
                .order_by(
                    ModelPoolConfig.priority.desc(),
                    ModelPoolConfig.created_at.asc(),
                )
                .first()
            )
            if model and model.embedding_dimension and model.embedding_dimension > 0:
                return int(model.embedding_dimension)

            # DB 未配置维度时，从 EmbeddingsService 内置字典兜底
            return self._resolve_dimension_from_embeddings_service()
        except Exception:
            logger.warning("_resolve_system_default_dimension_from_db: 解析失败", exc_info=True)
            return None

    def _resolve_dimension_from_embeddings_service(self) -> Optional[int]:
        """从 EmbeddingsService 内置字典兜底解析维度。"""
        try:
            from internal.service.embeddings_service import (
                DEFAULT_EMBEDDING_DIMENSION,
                _EMBEDDING_MODEL_DIMENSIONS,
            )
            from internal.model.model_pool_entity import ModelPoolConfig

            db = self._get_db()
            if db is None:
                return None

            model = (
                db.session.query(ModelPoolConfig)
                .filter_by(status="active", model_type="embedding")
                .order_by(
                    ModelPoolConfig.priority.desc(),
                    ModelPoolConfig.created_at.asc(),
                )
                .first()
            )
            if model:
                dim = _EMBEDDING_MODEL_DIMENSIONS.get(model.provider, {}).get(
                    model.model_name
                )
                if dim:
                    return dim

            return DEFAULT_EMBEDDING_DIMENSION
        except Exception:
            logger.warning("_resolve_dimension_from_embeddings_service: 兜底解析失败", exc_info=True)
            return None

    # =========================================================
    # 缓存读写
    # =========================================================

    def _get_cached_dimension(self, key: str) -> Optional[int]:
        with self._cache_lock:
            return self._dimension_cache.get(key)

    def _set_cached_dimension(self, key: str, value: int) -> None:
        with self._cache_lock:
            self._dimension_cache[key] = value

    # =========================================================
    # DB 获取
    # =========================================================

    def _get_db(self):
        """获取 SQLAlchemy 实例，不可用时返回 None。"""
        if self._db is not None:
            return self._db
        try:
            db = current_app.extensions.get("database")
            if db is not None:
                return db
        except RuntimeError:
            pass
        try:
            from internal.extension.database_extension import db
            return db
        except Exception:
            logger.warning("_get_db: 获取数据库失败", exc_info=True)
            return None


# =========================================================
# 模块级辅助函数
# =========================================================


def _validate_dimension(dimension: int) -> None:
    """校验维度是否在有效范围内（1-2000），防止 SQL 注入。

    pgvector 的 vector 类型最大支持 2000 维（HNSW/IVFFLAT 索引同此限制）。
    高维模型需通过 MRL 降维到 ≤2000 维使用。
    """
    if not isinstance(dimension, int) or dimension <= 0:
        raise ValueError(f"dimension 必须是正整数，得到 {dimension!r}")
    if dimension > MAX_SUPPORTED_DIMENSION:
        raise ValueError(
            f"dimension {dimension} 超过 pgvector 最大支持维度 "
            f"{MAX_SUPPORTED_DIMENSION}，请通过 MRL 降维（如 Qwen3-Embedding "
            f"配置 dimensions=1024 或 1536）"
        )
