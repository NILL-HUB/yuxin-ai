import logging
import math
import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from internal.exception import ConflictException, NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import escape_like_pattern
from internal.model.model_pool_entity import (
    CostPolicy,
    ModelKeyConfig,
    ModelPoolConfig,
    ModelTierPolicy,
)


logger = logging.getLogger(__name__)

# 无上下文概念的模型类型：不展示也不校验 max_tokens，后端自动置 0
CONTEXT_LESS_MODEL_TYPES = frozenset(
    {"image_generation", "video_generation", "tts", "asr", "ocr"}
)

# OpenAI 兼容 Chat 类接口的路径后缀，完整地址模式下需要剥离，避免 langchain 重复追加
_OPENAI_COMPAT_PATH_SUFFIXES = (
    "/chat/completions",
    "/completions",
    "/embeddings",
    "/images/generations",
    "/audio/transcriptions",
    "/audio/speech",
    "/rerank",
)


def normalize_provider_base_url(base_url: str, is_full_url: bool = False) -> str:
    """将供应商 base_url 规范化为 langchain 可用的形式。

    - is_full_url=False（默认）：base_url 已填到 /v1 级，原样返回（langchain 会自行追加路径）。
    - is_full_url=True：base_url 为完整 endpoint（含 /chat/completions 等），
      剥离尾部路径后缀，让 langchain 自行追加，避免出现重复路径。
    """
    if not base_url:
        return base_url
    if not is_full_url:
        return base_url
    normalized = base_url.rstrip("/")
    for suffix in _OPENAI_COMPAT_PATH_SUFFIXES:
        if normalized.lower().endswith(suffix):
            return normalized[: -len(suffix)].rstrip("/")
    return normalized


def _load_fernet() -> Fernet:
    """加载 Fernet 密钥（复用 MODEL_KEY_ENCRYPTION_KEY）。

    未配置或为占位符时：生产环境直接抛错阻止启动，开发环境生成临时内存密钥并 WARNING。
    """
    from internal.service.tool_credential_encryptor import load_fernet_from_env

    return load_fernet_from_env("MODEL_KEY_ENCRYPTION_KEY", "模型池凭证")


_FERNET = _load_fernet()


def _encrypt_key_value(value: str) -> str:
    if not value:
        return ""
    return _FERNET.encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt_key_value(token: str) -> str:
    if not token:
        return ""
    try:
        return _FERNET.decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def _mask_key_value(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


class AdminModelPoolService:
    def __init__(self, session=None):
        self.session = session or db.session

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _decimal(value, default: str = "0.000000") -> Decimal:
        try:
            return Decimal(str(value if value is not None else default))
        except Exception:
            return Decimal(default)

    @staticmethod
    def _parse_datetime(value) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=None) if value.tzinfo else value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                return datetime.fromtimestamp(int(value), tz=UTC).replace(tzinfo=None)
            except (OverflowError, OSError, ValueError):
                return None
        if isinstance(value, str):
            text = value.strip()
            if text.isdigit():
                try:
                    return datetime.fromtimestamp(int(text), tz=UTC).replace(tzinfo=None)
                except (OverflowError, OSError, ValueError):
                    return None
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed
            except ValueError:
                return None
        return None

    def list_models(self, *, search: str = "", provider: str = "", tier: str = "", status: str = "", current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 100), 1)
        query = self.session.query(ModelPoolConfig)
        search = (search or "").strip()
        if search:
            like_value = f"%{escape_like_pattern(search)}%"
            query = query.filter(
                (ModelPoolConfig.model_name.ilike(like_value))
                | (ModelPoolConfig.display_name.ilike(like_value))
            )
        if provider:
            query = query.filter(ModelPoolConfig.provider == provider)
        if tier:
            query = query.filter(ModelPoolConfig.tier == tier)
        if status:
            query = query.filter(ModelPoolConfig.status == status)
        total = query.count()
        models = query.order_by(ModelPoolConfig.created_at.desc()).offset((current_page - 1) * page_size).limit(page_size).all()
        return {
            "list": [self._serialize_model(model) for model in models],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_model(self, model_id: UUID) -> dict:
        return self._serialize_model(self._get_model_or_raise(model_id))

    def create_model(self, payload: dict) -> dict:
        # 校验 provider 存在且 active
        provider_name = payload["provider"]
        from internal.model.model_provider_entity import ModelProviderConfig
        provider = self.session.query(ModelProviderConfig).filter_by(
            name=provider_name, status="active"
        ).first()
        if not provider:
            raise NotFoundException(f"供应商 {provider_name} 不存在或已禁用")

        # 校验同 provider 下 model_name 唯一
        existing = self.session.query(ModelPoolConfig).filter_by(
            provider=provider_name, model_name=payload["model_name"]
        ).first()
        if existing:
            raise ConflictException(f"模型 {payload['model_name']} 在供应商 {provider_name} 下已存在")

        model_type = payload.get("model_type") or "chat"
        # embedding 模型自动探测维度（忽略前端传入的 embedding_dimension）
        embedding_dimension = 0
        if model_type == "embedding":
            embedding_dimension = self._auto_probe_dimension(
                provider_name, payload["model_name"]
            )
        # 无上下文概念的模型类型（图片/视频生成、TTS/ASR/OCR），token 上限强制 0
        if model_type in CONTEXT_LESS_MODEL_TYPES:
            max_input_tokens = 0
            max_output_tokens = 0
        else:
            # 新字段优先；兼容仅传 max_tokens 的旧客户端（输入沿用总窗口，输出给安全默认）
            max_input_tokens = int(
                payload.get("max_input_tokens")
                if payload.get("max_input_tokens") is not None
                else (payload.get("max_tokens") or 0)
            )
            max_output_tokens = int(
                payload.get("max_output_tokens")
                if payload.get("max_output_tokens") is not None
                else 4096
            )

        model = ModelPoolConfig(
            provider=payload["provider"],
            model_name=payload["model_name"],
            display_name=payload.get("display_name") or "",
            description=payload.get("description") or "",
            tier=payload.get("tier") or "2",
            capabilities=payload.get("capabilities") or [],
            price_per_1k_tokens=self._decimal(payload.get("price_per_1k_tokens")),
            max_tokens=max_input_tokens + max_output_tokens,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            status=payload.get("status") or "active",
            model_type=model_type,
            compatible_api=payload.get("compatible_api") or "openai",
            fallback_model_id=payload.get("fallback_model_id") or None,
            priority=int(payload.get("priority") or 0),
            embedding_dimension=embedding_dimension,
        )
        self.session.add(model)
        self.session.commit()

        self._invalidate_model_cache(model.provider, model.model_name)
        # embedding 模型维度变更时失效 EmbeddingsService 和 EmbeddingTableRouter 缓存
        self._invalidate_embedding_caches()
        return self._serialize_model(model)

    def update_model(self, model_id: UUID, payload: dict) -> dict:
        model = self._get_model_or_raise(model_id)
        # 记录变更前的关键字段，用于判断是否需要重新探测维度
        old_provider = model.provider
        old_model_name = model.model_name
        old_model_type = model.model_type

        if "provider" in payload:
            model.provider = payload["provider"]
        if "model_name" in payload:
            model.model_name = payload["model_name"]
        if "display_name" in payload:
            model.display_name = payload["display_name"] or ""
        if "description" in payload:
            model.description = payload["description"] or ""
        if "tier" in payload:
            model.tier = payload["tier"]
        if "capabilities" in payload:
            model.capabilities = payload["capabilities"] or []
        if "price_per_1k_tokens" in payload:
            model.price_per_1k_tokens = self._decimal(payload.get("price_per_1k_tokens"))
        if "max_input_tokens" in payload:
            model.max_input_tokens = int(payload.get("max_input_tokens") or 0)
        if "max_output_tokens" in payload:
            model.max_output_tokens = int(payload.get("max_output_tokens") or 0)
        if "status" in payload:
            model.status = payload["status"]
        if "fallback_model_id" in payload:
            model.fallback_model_id = payload["fallback_model_id"] or None
        if "priority" in payload:
            model.priority = int(payload.get("priority") or 0)
        if "model_type" in payload:
            model.model_type = payload["model_type"]
        if "compatible_api" in payload:
            model.compatible_api = payload["compatible_api"]
        # 忽略前端传入的 embedding_dimension，由系统自动探测

        # 无上下文概念的模型类型（图片/视频生成、TTS/ASR/OCR），token 上限强制 0
        if model.model_type in CONTEXT_LESS_MODEL_TYPES:
            model.max_input_tokens = 0
            model.max_output_tokens = 0
            model.max_tokens = 0
        else:
            # 兼容旧客户端：仅传 max_tokens（总窗口）时，作为输入窗口更新，输出侧保持原值
            if "max_input_tokens" not in payload and "max_tokens" in payload:
                model.max_input_tokens = int(payload.get("max_tokens") or 0)
            # 兼容字段 = 输入 + 输出总窗口
            model.max_tokens = (model.max_input_tokens or 0) + (model.max_output_tokens or 0)

        # 判断是否需要重新探测维度：
        # 1. model_type 变为 embedding（之前不是）
        # 2. model_type 仍为 embedding，但 provider 或 model_name 变更
        new_model_type = model.model_type
        need_probe = False
        if new_model_type == "embedding":
            if old_model_type != "embedding":
                need_probe = True
            elif old_provider != model.provider or old_model_name != model.model_name:
                need_probe = True
        else:
            # 非 embedding 类型，维度清零
            model.embedding_dimension = 0

        if need_probe:
            model.embedding_dimension = self._auto_probe_dimension(
                model.provider, model.model_name
            )

        model.updated_at = self._now()
        self.session.commit()
        # embedding 模型维度变更时失效 EmbeddingsService 和 EmbeddingTableRouter 缓存
        self._invalidate_embedding_caches()
        return self._serialize_model(model)

    def delete_model(self, model_id: UUID) -> None:
        model = self._get_model_or_raise(model_id)
        # 前置校验：无 model_id 精确关联的 Key
        precise_keys_count = (
            self.session.query(ModelKeyConfig)
            .filter(ModelKeyConfig.model_id == str(model.id))
            .count()
        )
        if precise_keys_count > 0:
            raise ConflictException(
                f"存在 {precise_keys_count} 个 model_id 精确关联的 Key，请先删除或解绑"
            )
        provider_name = model.provider
        model_name = model.model_name
        # 记录是否为 embedding 模型，删除后需失效维度缓存
        is_embedding = model.model_type == "embedding"
        self.session.delete(model)
        self.session.commit()

        self._invalidate_model_cache(provider_name, model_name)
        if is_embedding:
            self._invalidate_embedding_caches()

    def set_model_status(self, model_id: UUID, status: str) -> dict:
        model = self._get_model_or_raise(model_id)
        model.status = status
        model.updated_at = self._now()
        self.session.commit()
        self._invalidate_model_cache(model.provider, model.model_name)
        if model.model_type == "embedding":
            self._invalidate_embedding_caches()
        return self._serialize_model(model)

    def list_keys(self, *, provider: str = "", status: str = "", current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 100), 1)
        query = self.session.query(ModelKeyConfig)
        if provider:
            query = query.filter(ModelKeyConfig.provider == provider)
        if status:
            query = query.filter(ModelKeyConfig.status == status)
        total = query.count()
        keys = query.order_by(ModelKeyConfig.created_at.desc()).offset((current_page - 1) * page_size).limit(page_size).all()
        return {
            "list": [self._serialize_key(key) for key in keys],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def create_key(self, payload: dict) -> dict:
        # 校验 provider 存在且 active
        from internal.model.model_provider_entity import ModelProviderConfig
        provider = self.session.query(ModelProviderConfig).filter_by(
            name=payload["provider"], status="active"
        ).first()
        if not provider:
            raise NotFoundException(f"供应商 {payload['provider']} 不存在或已禁用")

        # 若填了 model_id，校验模型存在且 provider 一致
        if payload.get("model_id"):
            model = self.session.query(ModelPoolConfig).filter_by(id=payload["model_id"]).first()
            if not model:
                raise NotFoundException("关联模型不存在")
            if model.provider != payload["provider"]:
                raise ConflictException("模型的供应商与 Key 的供应商不一致")

        key = ModelKeyConfig(
            provider=payload["provider"],
            key_alias=payload["key_alias"],
            key_value_encrypted=_encrypt_key_value(payload.get("key_value") or ""),
            tenant_quota=self._decimal(payload.get("tenant_quota"), "0.0000"),
            status=payload.get("status") or "active",
            model_id=payload.get("model_id") or None,
            effective_at=self._parse_datetime(payload.get("effective_at")),
            expires_at=self._parse_datetime(payload.get("expires_at")),
            used_credits=self._decimal(payload.get("used_credits"), "0.0000"),
        )
        self.session.add(key)
        self.session.commit()
        return self._serialize_key(key)

    def update_key(self, key_id: UUID, payload: dict) -> dict:
        key = self._get_key_or_raise(key_id)
        if "provider" in payload:
            key.provider = payload["provider"]
        if "key_alias" in payload:
            key.key_alias = payload["key_alias"]
        if "key_value" in payload and payload["key_value"]:
            key.key_value_encrypted = _encrypt_key_value(payload["key_value"])
        if "tenant_quota" in payload:
            key.tenant_quota = self._decimal(payload.get("tenant_quota"), "0.0000")
        if "status" in payload:
            key.status = payload["status"]
        if "model_id" in payload:
            key.model_id = payload["model_id"] or None
        if "effective_at" in payload:
            key.effective_at = self._parse_datetime(payload.get("effective_at"))
        if "expires_at" in payload:
            key.expires_at = self._parse_datetime(payload.get("expires_at"))
        if "used_credits" in payload:
            key.used_credits = self._decimal(payload.get("used_credits"), "0.0000")
        key.updated_at = self._now()
        self.session.commit()
        return self._serialize_key(key)

    def delete_key(self, key_id: UUID) -> None:
        key = self._get_key_or_raise(key_id)
        self.session.delete(key)
        self.session.commit()

    def set_key_status(self, key_id: UUID, status: str) -> dict:
        key = self._get_key_or_raise(key_id)
        key.status = status
        key.updated_at = self._now()
        self.session.commit()
        return self._serialize_key(key)

    def list_tier_policies(self) -> dict:
        # 不再自动 seed 硬编码档位，档位由用户通过 CRUD 自定义
        policies = self.session.query(ModelTierPolicy).order_by(
            ModelTierPolicy.sort_order.asc(),
            ModelTierPolicy.tier_code.asc(),
        ).all()
        # 首次访问且表为空时，seed 默认的 5 个数字档位
        if not policies:
            self._ensure_default_tier_policies()
            policies = self.session.query(ModelTierPolicy).order_by(
                ModelTierPolicy.sort_order.asc(),
                ModelTierPolicy.tier_code.asc(),
            ).all()
        return {"list": [self._serialize_tier_policy(policy) for policy in policies]}

    def _ensure_default_tier_policies(self) -> None:
        """首次查询表为空时 seed 5 个默认数字档位。"""
        default_tiers = [
            ("1", "经济型", 1),
            ("2", "标准型", 2),
            ("3", "强力型", 3),
            ("4", "视觉型", 4),
            ("5", "长上下文型", 5),
        ]
        now = self._now()
        for tier_code, tier_name, sort_order in default_tiers:
            existing = self.session.query(ModelTierPolicy).filter(ModelTierPolicy.tier_code == tier_code).one_or_none()
            if existing is None:
                self.session.add(ModelTierPolicy(
                    tier_code=tier_code,
                    tier_name=tier_name,
                    sort_order=sort_order,
                    allowed_models=[],
                    default_model="",
                    routing_rules={},
                    created_at=now,
                    updated_at=now,
                ))
        self.session.commit()

    def create_tier_policy(self, payload: dict) -> dict:
        tier_code = str(payload.get("tier_code") or "").strip()
        if not tier_code:
            raise ValueError("tier_code 不能为空")
        existing = self.session.query(ModelTierPolicy).filter(ModelTierPolicy.tier_code == tier_code).one_or_none()
        if existing is not None:
            raise ConflictException(f"档位标识 {tier_code} 已存在")
        tier_name = str(payload.get("tier_name") or "").strip()
        if not tier_name:
            raise ValueError("tier_name 不能为空")
        policy = ModelTierPolicy(
            tier_code=tier_code,
            tier_name=tier_name,
            sort_order=int(payload.get("sort_order") or 0),
            allowed_models=payload.get("allowed_models") or [],
            default_model=payload.get("default_model") or "",
            routing_rules=payload.get("routing_rules") or {},
            created_at=self._now(),
            updated_at=self._now(),
        )
        self.session.add(policy)
        self.session.commit()
        return self._serialize_tier_policy(policy)

    def update_tier_policy(self, tier_code: str, payload: dict) -> dict:
        policy = self.session.query(ModelTierPolicy).filter(ModelTierPolicy.tier_code == tier_code).one_or_none()
        if policy is None:
            raise NotFoundException("档位策略不存在")
        if "tier_name" in payload and payload["tier_name"]:
            policy.tier_name = str(payload["tier_name"]).strip()
        if "sort_order" in payload:
            policy.sort_order = int(payload.get("sort_order") or 0)
        if "allowed_models" in payload:
            policy.allowed_models = payload["allowed_models"] or []
        if "default_model" in payload:
            policy.default_model = payload["default_model"] or ""
        if "routing_rules" in payload:
            policy.routing_rules = payload["routing_rules"] or {}
        policy.updated_at = self._now()
        self.session.commit()
        return self._serialize_tier_policy(policy)

    def delete_tier_policy(self, tier_code: str) -> None:
        policy = self.session.query(ModelTierPolicy).filter(ModelTierPolicy.tier_code == tier_code).one_or_none()
        if policy is None:
            raise NotFoundException("档位策略不存在")
        # 前置校验：仍有模型引用该档位时不允许删除
        ref_count = self.session.query(ModelPoolConfig).filter(ModelPoolConfig.tier == tier_code).count()
        if ref_count > 0:
            raise ConflictException(f"仍有 {ref_count} 个模型引用该档位，请先迁移后再删除")
        self.session.delete(policy)
        self.session.commit()

    def get_tier_name_map(self) -> dict[str, str]:
        """返回 {tier_code: tier_name} 映射，用于前端下拉选择和显示。"""
        policies = self.session.query(ModelTierPolicy).all()
        return {p.tier_code: p.tier_name for p in policies}

    def list_cost_policies(self) -> dict:
        policies = self.session.query(CostPolicy).order_by(CostPolicy.created_at.desc()).all()
        return {"list": [self._serialize_cost_policy(policy) for policy in policies]}

    def create_cost_policy(self, payload: dict) -> dict:
        policy = CostPolicy(
            policy_name=payload.get("policy_name") or "default",
            model_tier=payload.get("model_tier") or "2",
            max_cost_per_request=self._decimal(payload.get("max_cost_per_request"), "0.000000"),
            billing_mode=payload.get("billing_mode") or "token",
            upgrade_threshold=self._decimal(payload.get("upgrade_threshold"), "0.000000"),
        )
        self.session.add(policy)
        self.session.commit()
        return self._serialize_cost_policy(policy)

    def update_cost_policy(self, policy_id: UUID, payload: dict) -> dict:
        policy = self._get_cost_policy_or_raise(policy_id)
        if "policy_name" in payload:
            policy.policy_name = payload["policy_name"]
        if "model_tier" in payload:
            policy.model_tier = payload["model_tier"]
        if "max_cost_per_request" in payload:
            policy.max_cost_per_request = self._decimal(payload.get("max_cost_per_request"))
        if "billing_mode" in payload:
            policy.billing_mode = payload["billing_mode"]
        if "upgrade_threshold" in payload:
            policy.upgrade_threshold = self._decimal(payload.get("upgrade_threshold"))
        policy.updated_at = self._now()
        self.session.commit()
        return self._serialize_cost_policy(policy)

    def _get_model_or_raise(self, model_id: UUID) -> ModelPoolConfig:
        model = self.session.query(ModelPoolConfig).filter(ModelPoolConfig.id == model_id).one_or_none()
        if model is None:
            raise NotFoundException("模型配置不存在")
        return model

    def _invalidate_model_cache(self, provider_name: str, model_name: str) -> None:
        """失效 LanguageModelManager 中的 model 缓存"""
        try:
            from internal.core.language_model.language_model_manager import LanguageModelManager
            from injector import Injector
            injector = Injector()
            manager = injector.get(LanguageModelManager)
            manager.invalidate_model(provider_name, model_name)
        except Exception:
            pass

    @staticmethod
    def _invalidate_embedding_caches() -> None:
        """失效 EmbeddingsService 和 EmbeddingTableRouter 的维度缓存。

        在 embedding 模型创建/更新/删除/状态变更时调用，确保后续请求读取最新维度配置。
        """
        try:
            from internal.service.embedding_table_router import EmbeddingTableRouter
            router = EmbeddingTableRouter.get_instance()
            router.invalidate_dimension_cache()
        except Exception:
            pass
        try:
            from app.http.module import injector
            from internal.service.embeddings_service import EmbeddingsService
            svc = injector.get(EmbeddingsService)
            svc.invalidate_model_cache()
            # 重置系统默认 embeddings（触发下次访问时重新从 DB 加载）
            svc._embeddings = None
            svc._cache_backed_embeddings = None
            svc._dimension = None
            svc._provider = None
            svc._model = None
        except Exception:
            pass

    @staticmethod
    def _probe_embedding_dimension(
        provider: str,
        model_name: str,
        api_key: str,
        base_url: str | None = None,
    ) -> int:
        """探测 embedding 模型的实际输出维度。

        通过调用 embed_query 获取一个真实向量，返回其维度。
        如果原生维度 > 2000（pgvector 限制），自动尝试 MRL 降维。

        降维策略：部分供应商（如 SiliconFlow）只支持特定维度值（如 512/1024/1536/2048/4096），
        不支持任意值。因此按候选维度列表从大到小尝试，找到第一个 ≤2000 且成功的维度。

        Args:
            provider: 供应商名称
            model_name: 模型名称
            api_key: API Key
            base_url: API 基础 URL

        Returns:
            探测到的维度（1-2000），探测失败返回 0
        """
        from langchain_openai import OpenAIEmbeddings
        from internal.service.embedding_table_router import MAX_SUPPORTED_DIMENSION
        from internal.service.embeddings_service import _EMBEDDING_MODEL_DIMENSIONS

        probe_text = "维度探测测试"
        # MRL 降维候选维度（从大到小尝试，均为 ≤2000 的常用值，避免浪费 API 调用）
        mrl_candidates = [1536, 1024, 768, 512]

        try:
            # 1. 先不传 dimensions，探测原生维度
            embeddings = OpenAIEmbeddings(
                model=model_name,
                api_key=api_key,
                base_url=base_url or None,
            )
            vector = embeddings.embed_query(probe_text)
            native_dim = len(vector)
            logger.info(
                "_probe_embedding_dimension: %s/%s 原生维度 %d",
                provider, model_name, native_dim,
            )

            # 2. 原生维度 ≤ 2000，直接使用
            if native_dim <= MAX_SUPPORTED_DIMENSION:
                return native_dim

            # 3. 原生维度 > 2000，按候选维度列表尝试 MRL 降维
            logger.info(
                "_probe_embedding_dimension: %s/%s 原生维度 %d > %d，尝试 MRL 降维候选 %s",
                provider, model_name, native_dim, MAX_SUPPORTED_DIMENSION, mrl_candidates,
            )
            for candidate_dim in mrl_candidates:
                try:
                    embeddings_mrl = OpenAIEmbeddings(
                        model=model_name,
                        api_key=api_key,
                        base_url=base_url or None,
                        dimensions=candidate_dim,
                    )
                    vector_mrl = embeddings_mrl.embed_query(probe_text)
                    actual_dim = len(vector_mrl)
                    if actual_dim <= MAX_SUPPORTED_DIMENSION:
                        logger.info(
                            "_probe_embedding_dimension: %s/%s MRL 降维成功 %d -> %d",
                            provider, model_name, native_dim, actual_dim,
                        )
                        return actual_dim
                except Exception as e:
                    logger.info(
                        "_probe_embedding_dimension: %s/%s 候选维度 %d 不支持，尝试下一个: %s",
                        provider, model_name, candidate_dim, str(e)[:80],
                    )
                    continue

            # 4. 所有候选维度都失败，使用内置字典兜底
            logger.warning(
                "_probe_embedding_dimension: %s/%s 所有 MRL 候选维度都失败，使用内置字典兜底",
                provider, model_name,
            )
            fallback_dim = _EMBEDDING_MODEL_DIMENSIONS.get(provider, {}).get(model_name)
            if fallback_dim and fallback_dim <= MAX_SUPPORTED_DIMENSION:
                return fallback_dim
            return 0
        except Exception as e:
            logger.warning(
                "_probe_embedding_dimension: 探测失败 %s/%s，错误: %s",
                provider, model_name, str(e),
            )
            # 探测失败时使用内置字典兜底
            fallback_dim = _EMBEDDING_MODEL_DIMENSIONS.get(provider, {}).get(model_name)
            if fallback_dim:
                return min(fallback_dim, MAX_SUPPORTED_DIMENSION)
            return 0

    def _resolve_api_key_and_base_url(self, provider: str) -> tuple[str, str | None]:
        """解析供应商的 API Key 和 base_url（用于维度探测）。

        优先使用 provider 级别的 active key，找不到则返回空字符串。
        """
        from internal.model.model_provider_entity import ModelProviderConfig
        provider_config = self.session.query(ModelProviderConfig).filter_by(
            name=provider
        ).first()
        base_url = (
            normalize_provider_base_url(
                provider_config.default_base_url,
                is_full_url=bool(getattr(provider_config, "is_full_url", False)),
            ) if provider_config and provider_config.default_base_url else None
        )

        key = self.session.query(ModelKeyConfig).filter(
            ModelKeyConfig.provider == provider,
            ModelKeyConfig.status == "active",
        ).order_by(
            ModelKeyConfig.used_credits.asc(),
            ModelKeyConfig.created_at.asc(),
        ).first()
        if key is None:
            return "", base_url
        api_key = _decrypt_key_value(key.key_value_encrypted)
        return api_key, base_url

    def _auto_probe_dimension(self, provider: str, model_name: str) -> int:
        """自动探测 embedding 模型维度。

        解析 provider 的 API Key，调用 _probe_embedding_dimension。
        探测失败时记录警告，返回 0（由内置字典兜底）。
        """
        api_key, base_url = self._resolve_api_key_and_base_url(provider)
        if not api_key:
            logger.warning(
                "_auto_probe_dimension: provider=%s 无可用 API Key，跳过维度探测",
                provider,
            )
            # 使用内置字典兜底
            from internal.service.embeddings_service import _EMBEDDING_MODEL_DIMENSIONS
            from internal.service.embedding_table_router import MAX_SUPPORTED_DIMENSION
            dim = _EMBEDDING_MODEL_DIMENSIONS.get(provider, {}).get(model_name)
            return min(dim, MAX_SUPPORTED_DIMENSION) if dim else 0
        return self._probe_embedding_dimension(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
        )

    def _get_key_or_raise(self, key_id: UUID) -> ModelKeyConfig:
        key = self.session.query(ModelKeyConfig).filter(ModelKeyConfig.id == key_id).one_or_none()
        if key is None:
            raise NotFoundException("模型Key不存在")
        return key

    def _get_cost_policy_or_raise(self, policy_id: UUID) -> CostPolicy:
        policy = self.session.query(CostPolicy).filter(CostPolicy.id == policy_id).one_or_none()
        if policy is None:
            raise NotFoundException("成本策略不存在")
        return policy

    def _serialize_model(self, model: ModelPoolConfig) -> dict:
        return {
            "id": str(model.id),
            "provider": model.provider,
            "model_name": model.model_name,
            "display_name": model.display_name or "",
            "description": model.description or "",
            "tier": model.tier,
            "capabilities": list(model.capabilities or []),
            "price_per_1k_tokens": f"{Decimal(str(model.price_per_1k_tokens or 0)):.6f}",
            "max_tokens": int((model.max_input_tokens or 0) + (model.max_output_tokens or 0)),
            "max_input_tokens": int(model.max_input_tokens or 0),
            "max_output_tokens": int(model.max_output_tokens or 0),
            "status": model.status,
            "model_type": model.model_type,
            "compatible_api": model.compatible_api,
            "embedding_dimension": int(model.embedding_dimension or 0),
            "fallback_model_id": model.fallback_model_id or None,
            "priority": int(model.priority or 0),
            "created_at": self._timestamp(model.created_at),
            "updated_at": self._timestamp(model.updated_at),
        }

    def _serialize_key(self, key: ModelKeyConfig) -> dict:
        raw_value = _decrypt_key_value(key.key_value_encrypted)
        return {
            "id": str(key.id),
            "provider": key.provider,
            "key_alias": key.key_alias,
            "key_mask": _mask_key_value(raw_value),
            "tenant_quota": f"{Decimal(str(key.tenant_quota or 0)):.4f}",
            "status": key.status,
            "failure_count": int(key.failure_count or 0),
            "used_credits": f"{Decimal(str(key.used_credits or 0)):.4f}",
            "model_id": key.model_id or None,
            "last_used_at": self._timestamp(key.last_used_at),
            "effective_at": self._timestamp(key.effective_at),
            "expires_at": self._timestamp(key.expires_at),
            "created_at": self._timestamp(key.created_at),
            "updated_at": self._timestamp(key.updated_at),
        }

    def _serialize_tier_policy(self, policy: ModelTierPolicy) -> dict:
        return {
            "id": str(policy.id),
            "tier_code": policy.tier_code,
            "tier_name": policy.tier_name or "",
            "sort_order": int(policy.sort_order or 0),
            "allowed_models": list(policy.allowed_models or []),
            "default_model": policy.default_model or "",
            "routing_rules": dict(policy.routing_rules or {}),
            "created_at": self._timestamp(policy.created_at),
            "updated_at": self._timestamp(policy.updated_at),
        }

    def _serialize_cost_policy(self, policy: CostPolicy) -> dict:
        return {
            "id": str(policy.id),
            "policy_name": policy.policy_name,
            "model_tier": policy.model_tier,
            "max_cost_per_request": f"{Decimal(str(policy.max_cost_per_request or 0)):.6f}",
            "billing_mode": policy.billing_mode,
            "upgrade_threshold": f"{Decimal(str(policy.upgrade_threshold or 0)):.6f}",
            "created_at": self._timestamp(policy.created_at),
            "updated_at": self._timestamp(policy.updated_at),
        }
