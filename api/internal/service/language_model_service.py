import logging
import os
import mimetypes
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any
from copy import deepcopy
from flask import current_app, has_app_context
from injector import inject, provider
import httpx
from pydantic import PrivateAttr
from internal.core.language_model import LanguageModelManager
from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
from internal.exception import NotFoundException, ValidateErrorException
from internal.lib.helper import convert_model_to_dict
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


logger = logging.getLogger(__name__)

# 数据库未配置模型时的兜底档位（按 tier 升序取第一个 active 模型）
# "2" 对应标准型（原 "standard"）
_DEFAULT_FALLBACK_TIER = "2"
# 历史软超时常量，已废弃：_build_soft_timeout_model 不再压缩 timeout，
# LLM 死机检测完全由 LLMActivityProbe 活跃探针接管（60s 无 token 产出才判定死机）
_RUNTIME_FALLBACK_SOFT_TIMEOUT_SECONDS = 30.0
_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_RETRYABLE_EXCEPTION_NAME_PARTS = (
    "Timeout",
    "ConnectionError",
    "ConnectError",
    "TransportError",
    "NetworkError",
    "RemoteProtocolError",
    "ReadError",
    "WriteError",
    "PoolTimeout",
    "InternalServerError",
    "RateLimitError",
    "ServiceUnavailableError",
    "GatewayTimeout",
    "ServerDisconnectedError",
    "APIConnectionError",
    "APITimeoutError",
)
_NON_RETRYABLE_EXCEPTION_NAME_PARTS = (
    "BadRequestError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ValidationError",
    "OutputParserException",
    "JSONDecodeError",
    "ValueError",
    "TypeError",
)


def _normalize_model_ref(model_config: dict[str, Any] | None) -> dict[str, str]:
    """提取 provider/model 用于比较模型引用。"""
    normalized_model_config = deepcopy(model_config or {})
    return {
        "provider": str(normalized_model_config.get("provider", "")).strip(),
        "model": str(normalized_model_config.get("model", "")).strip(),
    }


def _extract_status_code(exc: Exception) -> int | None:
    """尽量提取运行时错误的状态码。"""
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(exc, "response", None)
    if response is not None:
        response_status_code = getattr(response, "status_code", None)
        if isinstance(response_status_code, int):
            return response_status_code

    return None


def _is_retryable_runtime_error(exc: Exception) -> bool:
    """判断 LLM 运行时错误是否允许切换到文本兜底模型。"""
    retryable = getattr(exc, "retryable", None)
    if isinstance(retryable, bool):
        return retryable

    status_code = _extract_status_code(exc)
    if status_code is not None:
        if status_code in _RETRYABLE_STATUS_CODES:
            return True
        if 400 <= status_code < 500:
            return False

    exception_name = type(exc).__name__
    if any(part in exception_name for part in _NON_RETRYABLE_EXCEPTION_NAME_PARTS):
        return False
    if any(part in exception_name for part in _RETRYABLE_EXCEPTION_NAME_PARTS):
        return True

    return isinstance(exc, TimeoutError) or isinstance(exc, httpx.TimeoutException)


def _contains_image_input(value: Any, _visited: set[int] | None = None) -> bool:
    """递归判断输入中是否包含图片输入。"""
    if value is None:
        return False

    if _visited is None:
        _visited = set()

    value_id = id(value)
    if value_id in _visited:
        return False
    _visited.add(value_id)

    if isinstance(value, str):
        normalized_value = value.lower()
        return "data:image/" in normalized_value

    if isinstance(value, dict):
        type_value = str(value.get("type", "")).strip().lower()
        if type_value in {"image", "image_url"}:
            return True

        nested_image_url = value.get("image_url")
        if isinstance(nested_image_url, dict):
            if _contains_image_input(nested_image_url, _visited):
                return True
            if nested_image_url.get("url"):
                return True
        elif isinstance(nested_image_url, str) and nested_image_url.strip():
            return True

        if isinstance(value.get("url"), str) and type_value in {"image", "image_url"}:
            return True

        return any(_contains_image_input(item, _visited) for item in value.values())

    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_image_input(item, _visited) for item in value)

    to_messages = getattr(value, "to_messages", None)
    if callable(to_messages):
        try:
            return _contains_image_input(to_messages(), _visited)
        except Exception:
            return False

    messages = getattr(value, "messages", None)
    if messages is not None:
        return _contains_image_input(messages, _visited)

    content = getattr(value, "content", None)
    if content is not None:
        return _contains_image_input(content, _visited)

    additional_kwargs = getattr(value, "additional_kwargs", None)
    if additional_kwargs is not None:
        return _contains_image_input(additional_kwargs, _visited)

    return False


def _build_soft_timeout_model(model: Any, timeout_seconds: float) -> Any:
    """构建禁用重试的模型副本（保留原始 timeout，由 LLMActivityProbe 接管死机检测）。

    历史上此函数会压缩 timeout 到 30s 以实现"快速失败切换兜底"，
    但这会误杀需要长耗时思考的 LLM（如编程 Agent 连续工作数小时）。
    现在仅设置 max_retries=0（不重试），timeout 保留原始值（由 LLM_REQUEST_TIMEOUT 控制），
    死机检测完全交给 LLMActivityProbe 活跃探针（60s 无 token 产出才判定死机）。
    """
    model_fields = getattr(model.__class__, "model_fields", {}) or {}
    update: dict[str, Any] = {}

    if "max_retries" in model_fields or hasattr(model, "max_retries"):
        current_max_retries = getattr(model, "max_retries", None)
        if current_max_retries != 0:
            update["max_retries"] = 0

    if not update:
        return model

    for clone_method_name in ("model_copy", "copy"):
        clone_method = getattr(model, clone_method_name, None)
        if callable(clone_method):
            try:
                return clone_method(update=update)
            except Exception:
                continue

    try:
        cloned_model = deepcopy(model)
        for key, value in update.items():
            setattr(cloned_model, key, value)
        return cloned_model
    except Exception:
        return model


class RuntimeFallbackLanguageModelProxy(BaseLanguageModel):
    """给文本模型调用加一层运行时兜底代理。"""

    _model: Any = PrivateAttr()
    _primary_model: Any = PrivateAttr()
    _fallback_loader: Callable[[], BaseLanguageModel] = PrivateAttr()
    _fallback_model: BaseLanguageModel | None = PrivateAttr(default=None)
    _requested_model_config: dict[str, Any] = PrivateAttr(default_factory=dict)
    _requested_model_ref: dict[str, str] = PrivateAttr(default_factory=dict)
    _runtime_fallback_enabled: bool = PrivateAttr(default=False)

    @classmethod
    def from_model(
        cls,
        model: Any,
        *,
        fallback_loader: Callable[[], BaseLanguageModel],
        requested_model_config: dict[str, Any],
        runtime_fallback_enabled: bool,
        features_source: list[Any] | None = None,
        metadata_source: dict[str, Any] | None = None,
    ) -> "RuntimeFallbackLanguageModelProxy":
        instance = cls(
            features=list(getattr(model, "features", None) or features_source or []),
            metadata=deepcopy(getattr(model, "metadata", None) or metadata_source or {}),
        )
        object.__setattr__(instance, "_model", model)
        # 仅在启用运行时兜底时才应用软超时（快速失败以触发兜底切换）。
        # 当 runtime_fallback_enabled=False 时保留原始模型超时（如 LLM_REQUEST_TIMEOUT=300s），
        # 避免 30s 软超时误杀深度思考模型（探针 60s 检测间隔 > 30s 软超时，探针尚未触发 httpx 已超时）。
        if runtime_fallback_enabled:
            primary_model = _build_soft_timeout_model(model, _RUNTIME_FALLBACK_SOFT_TIMEOUT_SECONDS)
        else:
            primary_model = model
        object.__setattr__(instance, "_primary_model", primary_model)
        object.__setattr__(instance, "_fallback_loader", fallback_loader)
        object.__setattr__(instance, "_fallback_model", None)
        object.__setattr__(instance, "_requested_model_config", deepcopy(requested_model_config or {}))
        object.__setattr__(instance, "_requested_model_ref", _normalize_model_ref(requested_model_config))
        object.__setattr__(instance, "_runtime_fallback_enabled", runtime_fallback_enabled)
        return instance

    def _get_fallback_model(self) -> BaseLanguageModel:
        """延迟加载文本兜底模型。"""
        if self._fallback_model is None:
            object.__setattr__(self, "_fallback_model", self._fallback_loader())
        return self._fallback_model

    def _can_fallback(self, input_value: Any, exc: Exception) -> bool:
        if not self._runtime_fallback_enabled:
            return False
        if _contains_image_input(input_value):
            return False
        return _is_retryable_runtime_error(exc)

    def _wrap_model(self, model: Any) -> Any:
        if not self._runtime_fallback_enabled:
            return model
        if isinstance(model, RuntimeFallbackLanguageModelProxy):
            return model
        if model is None:
            return model
        if not hasattr(model, "invoke") and not hasattr(model, "stream"):
            return model
        return RuntimeFallbackLanguageModelProxy.from_model(
            model,
            fallback_loader=self._fallback_loader,
            requested_model_config=self._requested_model_config,
            runtime_fallback_enabled=self._runtime_fallback_enabled,
            features_source=list(self.features or []),
            metadata_source=dict(self.metadata or {}),
        )

    def _call_method_with_fallback(self, method_name: str, *args, **kwargs):
        input_value = args[0] if args else kwargs.get("input")
        try:
            method = getattr(object.__getattribute__(self, "_primary_model"), method_name)
            return method(*args, **kwargs)
        except Exception as exc:
            if not self._can_fallback(input_value, exc):
                raise
            logger.warning(
                "LLM 运行时%s失败，切换到默认模型兜底: requested=%s error=%s",
                method_name,
                self._requested_model_ref,
                exc,
            )
            fallback_method = getattr(self._get_fallback_model(), method_name)
            return fallback_method(*args, **kwargs)

    async def _acall_method_with_fallback(self, method_name: str, *args, **kwargs):
        input_value = args[0] if args else kwargs.get("input")
        try:
            method = getattr(object.__getattribute__(self, "_primary_model"), method_name)
            return await method(*args, **kwargs)
        except Exception as exc:
            if not self._can_fallback(input_value, exc):
                raise
            logger.warning(
                "LLM 运行时%s失败，切换到默认模型兜底: requested=%s error=%s",
                method_name,
                self._requested_model_ref,
                exc,
            )
            fallback_method = getattr(self._get_fallback_model(), method_name)
            return await fallback_method(*args, **kwargs)

    def invoke(self, *args, **kwargs):
        return self._call_method_with_fallback("invoke", *args, **kwargs)

    def stream(self, *args, **kwargs):
        input_value = args[0] if args else kwargs.get("input")
        yielded_any_chunk = False
        try:
            for chunk in object.__getattribute__(self, "_primary_model").stream(*args, **kwargs):
                yielded_any_chunk = True
                yield chunk
        except Exception as exc:
            if yielded_any_chunk or not self._can_fallback(input_value, exc):
                raise
            logger.warning(
                "LLM 运行时stream失败，切换到默认模型兜底: requested=%s error=%s",
                self._requested_model_ref,
                exc,
            )
            yield from self._get_fallback_model().stream(*args, **kwargs)

    def generate_prompt(self, *args, **kwargs):
        return self._call_method_with_fallback("generate_prompt", *args, **kwargs)

    async def agenerate_prompt(self, *args, **kwargs):
        return await self._acall_method_with_fallback("agenerate_prompt", *args, **kwargs)

    def bind(self, *args, **kwargs):
        bound_model = object.__getattribute__(self, "_primary_model").bind(*args, **kwargs)
        return self._wrap_model(bound_model)

    def bind_tools(self, *args, **kwargs):
        bound_model = object.__getattribute__(self, "_primary_model").bind_tools(*args, **kwargs)
        return self._wrap_model(bound_model)

    def with_structured_output(self, *args, **kwargs):
        bound_model = object.__getattribute__(self, "_primary_model").with_structured_output(*args, **kwargs)
        return self._wrap_model(bound_model)

    def get_num_tokens_from_messages(self, messages):
        token_counter = getattr(object.__getattribute__(self, "_primary_model"), "get_num_tokens_from_messages", None)
        if callable(token_counter):
            return token_counter(messages)
        return super().get_num_tokens_from_messages(messages)

    def __getattr__(self, name: str):
        try:
            return getattr(object.__getattribute__(self, "_primary_model"), name)
        except AttributeError as exc:
            raise AttributeError(name) from exc


@dataclass
class RuntimeModelResolution:
    """运行时模型解析结果。"""
    llm: BaseLanguageModel
    requested_model_config: dict[str, Any]
    effective_model_config: dict[str, Any]
    capabilities: dict[str, Any]
    resolution_action: str


@inject
@dataclass
class LanguageModelService(BaseService):
    """语言模型服务"""
    db: SQLAlchemy
    language_model_manager: LanguageModelManager

    IMAGE_REQUEST_POLICY_STRICT = "strict"
    IMAGE_REQUEST_POLICY_AUTO_UPGRADE = "auto_upgrade"
    ENTRYPOINT_DEBUGGER = "debugger"
    ENTRYPOINT_WEB_APP = "web_app"
    ENTRYPOINT_OPENAPI = "openapi"
    ENTRYPOINT_ASSISTANT_AGENT = "assistant_agent"
    ENTRYPOINT_PUBLIC_A2A = "public_a2a"

    def get_language_models(self) -> list[dict[str, Any]]:
        """获取 OpenAgent 项目中的所有模型列表信息

        从动态 model_pool_config 表中读取模型，
        使 AppConfig 选模型时能看到管理端配置的全部模型。
        """
        # 1.从数据库获取所有活跃模型，按 provider 分组
        from internal.model.model_pool_entity import ModelPoolConfig
        from internal.extension.database_extension import db

        dynamic_by_provider: dict[str, list[dict[str, Any]]] = {}
        try:
            dynamic_models = db.session.query(ModelPoolConfig).filter(
                ModelPoolConfig.status == "active",
            ).all()
            for m in dynamic_models:
                if m.provider not in dynamic_by_provider:
                    dynamic_by_provider[m.provider] = []
                dynamic_by_provider[m.provider].append({
                    "model_id": str(m.id),
                    "model_name": m.model_name,
                    "label": m.display_name or m.model_name,
                    "model_type": getattr(m, "model_type", None) or "chat",
                    "features": m.capabilities or [],
                    "context_windows": m.max_tokens or 0,
                    "max_output_tokens": m.max_tokens or 0,
                    "attributes": {"tier": m.tier, "base_url": ""},
                    "metadata": {
                        "price_per_1k_tokens": str(m.price_per_1k_tokens),
                        "embedding_dimension": int(getattr(m, "embedding_dimension", 0) or 0),
                    },
                    "parameters": [],
                })
        except Exception:
            logger.warning("查询 model_pool_config 动态模型失败", exc_info=True)

        # 2.获取 provider 元数据列表（从数据库懒加载）
        providers = self.language_model_manager.get_providers()

        # 3.合并 provider 元数据与模型列表
        language_models = []
        for idx, pe in enumerate(providers):
            language_models.append({
                "name": pe.name,
                "position": idx + 1,
                "label": pe.label,
                "icon": pe.icon,
                "description": pe.description,
                "background": pe.background,
                "support_model_types": pe.supported_model_types,
                "models": dynamic_by_provider.pop(pe.name, []),
            })

        # 4.添加有模型但无 provider 元数据的 provider
        next_position = len(language_models) + 1
        for provider_name, models in dynamic_by_provider.items():
            language_models.append({
                "name": provider_name,
                "position": next_position,
                "label": provider_name,
                "icon": "icon.png",
                "description": "",
                "background": "#FFFFFF",
                "support_model_types": ["chat"],
                "models": models,
            })
            next_position += 1

        return language_models

    def get_language_model(self, provider_name: str, model_name: str) -> dict[str, Any]:
        """根据传递的提供者名字+模型名字获取模型详细信息"""
        # 直接通过 manager 懒加载模型实体（内部会校验 provider 存在性）
        model_entity = self.language_model_manager.get_or_load_model_entity(provider_name, model_name)
        return convert_model_to_dict(model_entity)

    @classmethod
    def _get_config_value(cls, key: str, default: Any = None) -> Any:
        """优先从 Flask 配置读取，其次从环境变量读取。"""
        if has_app_context():
            return current_app.config.get(key, default)
        return os.getenv(key, default)

    @classmethod
    def get_default_model_config(cls) -> dict[str, Any]:
        """返回默认文本模型配置。

        通过 injector 获取自身实例，从数据库查询 priority 最高的 active 模型，
        不再硬编码任何 provider/model。
        """
        from flask import current_app

        _ctx = None
        try:
            current_app._get_current_object()
        except RuntimeError:
            from app.http.app import app
            _ctx = app.app_context()
            _ctx.push()
        try:
            from app.http.module import injector
            svc = injector.get(LanguageModelService)
            return svc._load_default_model_config_from_db(tier=None)
        finally:
            if _ctx is not None:
                _ctx.pop()

    @classmethod
    def get_assistant_agent_model_config(cls) -> dict[str, Any]:
        """返回辅助 Agent 的基础模型配置。

        从数据库查询 standard tier 中 priority 最高的 active 模型，
        不再硬编码 deepseek-chat。
        """
        from flask import current_app

        _ctx = None
        try:
            current_app._get_current_object()
        except RuntimeError:
            from app.http.app import app
            _ctx = app.app_context()
            _ctx.push()
        try:
            from app.http.module import injector
            svc = injector.get(LanguageModelService)
            return svc._load_default_model_config_from_db(tier="2")
        finally:
            if _ctx is not None:
                _ctx.pop()

    def _load_default_model_config_from_db(self, tier: str | None = None) -> dict[str, Any]:
        """从数据库查询默认模型配置。

        Args:
            tier: 指定档位时按 tier 过滤；None 时取 priority 最高的 active 模型

        Returns:
            {provider, model, parameters} 字典

        Raises:
            NotFoundException: 数据库无可用模型
        """
        from internal.model.model_pool_entity import ModelPoolConfig

        query = self.db.session.query(ModelPoolConfig).filter_by(status="active")
        if tier:
            query = query.filter(ModelPoolConfig.tier == tier)
        config = query.order_by(
            ModelPoolConfig.priority.desc(),
            ModelPoolConfig.created_at.asc(),
        ).first()
        if config is None:
            raise NotFoundException(
                f"数据库无可用 active 模型（tier={tier or 'any'}），请在 admin 中配置模型池"
            )
        return {
            "provider": config.provider,
            "model": config.model_name,
            "parameters": {},
        }

    @classmethod
    def get_provider_credentials(
        cls,
        provider: str | None = None,
        model_type: str | None = None,
    ) -> dict[str, str]:
        """从数据库查询 provider 的 API 凭证（api_key + base_url + model_name）。

        用于非 Chat 类的 LLM 服务（audio/rerank/embedding/image）从数据库获取凭证，
        替代原来从环境变量读取的方式。

        Args:
            provider: 指定 provider 名称（如 "SiliconFlow"）。为 None 时按 model_type 查询。
            model_type: 指定模型类型（如 "speech_to_text"/"rerank"/"embedding"/"text_to_image"）。
                       provider 和 model_type 至少传一个；同时提供时以 provider 优先。

        Returns:
            {"api_key": "...", "base_url": "...", "model": "...", "provider": "..."}
            查询失败或无配置时返回空字典。
        """
        from flask import current_app

        _ctx = None
        try:
            current_app._get_current_object()
        except RuntimeError:
            from app.http.app import app
            _ctx = app.app_context()
            _ctx.push()
        try:
            from app.http.module import injector
            svc = injector.get(LanguageModelService)
            return svc._load_provider_credentials_from_db(provider=provider, model_type=model_type)
        finally:
            if _ctx is not None:
                _ctx.pop()

    def _load_provider_credentials_from_db(
        self,
        provider: str | None = None,
        model_type: str | None = None,
    ) -> dict[str, str]:
        """从数据库查询 provider 凭证。"""
        from internal.model.model_pool_entity import ModelKeyConfig, ModelPoolConfig
        from internal.model.model_provider_entity import ModelProviderConfig
        from internal.service.admin_model_pool_service import _decrypt_key_value

        if not provider and not model_type:
            return {}

        query = self.db.session.query(ModelPoolConfig).filter_by(status="active")
        if provider:
            query = query.filter(ModelPoolConfig.provider == provider)
        if model_type:
            query = query.filter(ModelPoolConfig.model_type == model_type)
        model_record = query.order_by(
            ModelPoolConfig.priority.desc(),
            ModelPoolConfig.created_at.asc(),
        ).first()
        if model_record is None:
            return {}

        key = self.db.session.query(ModelKeyConfig).filter(
            ModelKeyConfig.provider == model_record.provider,
            ModelKeyConfig.status == "active",
        ).order_by(
            ModelKeyConfig.used_credits.asc(),
            ModelKeyConfig.created_at.asc(),
        ).first()
        if key is None:
            return {}

        provider_config = self.db.session.query(ModelProviderConfig).filter_by(
            name=model_record.provider,
        ).first()

        return {
            "api_key": _decrypt_key_value(key.key_value_encrypted),
            "base_url": (provider_config.default_base_url if provider_config else "") or "",
            "model": model_record.model_name,
            "provider": model_record.provider,
        }

    @classmethod
    def get_cheap_chat_model(cls):
        """返回用于意图判断等轻量任务的 cheap 档 LLM 实例。

        通过依赖注入获取 LanguageModelService 实例，走完整的 compatible_api 分发链路，
        根据数据库中模型的 compatible_api 字段选择正确的 Chat 类（如 ChatOpenAI）。
        """
        return cls._get_runtime_chat_model_by_tier("1")

    @classmethod
    def get_chat_model_by_tier(cls, tier: str = "1"):
        """根据档位返回对应 LLM 实例。走完整的 compatible_api 分发链路。"""
        return cls._get_runtime_chat_model_by_tier(tier)

    @classmethod
    def _get_runtime_chat_model_by_tier(cls, tier: str, model_type: str | None = None):
        """统一运行时 LLM 获取入口：通过 injector 获取 LanguageModelService 实例，
        走 _try_resolve_pool_llm → _instantiate_language_model → ModelClassRegistry 分发链路。

        在后台线程（记忆系统等）中调用时，手动 push/pop app context。
        所有 LLM 获取统一走数据库配置，不再有任何硬编码 provider/key。
        """
        tier = (tier or "1").strip()
        from flask import current_app

        _ctx = None
        try:
            current_app._get_current_object()
        except RuntimeError:
            from app.http.app import app
            _ctx = app.app_context()
            _ctx.push()

        try:
            from app.http.module import injector
            svc = injector.get(LanguageModelService)
            result = svc._try_resolve_pool_llm(tier, model_type)
            if result is not None:
                llm, _config = result
                return llm
            # 降级到默认模型（也走 DB 配置，无硬编码）
            return svc.load_default_language_model()
        finally:
            if _ctx is not None:
                _ctx.pop()

    @classmethod
    def get_feature_model(cls, feature_key: str):
        """根据公共 AI 功能键返回 LLM 实例。

        优先读取 public_ai_feature_config 表中该 feature_key 绑定的模型；
        未配置或模型不可用时，按 fallback_tier 自动降级到模型池中的对应档位模型。

        Args:
            feature_key: 功能键，如 "icon_prompt"、"memory_consolidation"、"intent_recognition"

        Returns:
            BaseLanguageModel 实例
        """
        from flask import current_app

        _ctx = None
        try:
            current_app._get_current_object()
        except RuntimeError:
            from app.http.app import app
            _ctx = app.app_context()
            _ctx.push()

        try:
            from app.http.module import injector
            from internal.service.public_ai_feature_service import PublicAIFeatureService

            svc = injector.get(PublicAIFeatureService)

            # 1. 优先使用功能绑定的模型
            model_config = svc.get_feature_model_config(feature_key)
            if model_config is not None:
                llm = cls._instantiate_model_from_pool_config(model_config)
                if llm is not None:
                    return llm
                logger.warning("get_feature_model: 绑定模型实例化失败 feature_key=%s model=%s", feature_key, model_config.model_name)

            # 2. 回退到 fallback_tier（按 model_type 过滤，防止类型不匹配）
            fallback_tier = svc.get_feature_fallback_tier(feature_key)
            model_type = svc.get_feature_model_type(feature_key)
            return cls._get_runtime_chat_model_by_tier(fallback_tier, model_type)
        finally:
            if _ctx is not None:
                _ctx.pop()

    @classmethod
    def get_feature_credentials(cls, feature_key: str) -> dict[str, str]:
        """根据公共 AI 功能键返回非 Chat 类凭证（api_key + base_url + model）。

        用于 image_generation / audio / rerank 等非 Chat 类功能的凭证获取。
        直接从功能绑定的 model_config_id 对应 ModelPoolConfig 记录读取凭证
        （provider + base_url + API Key）。未绑定模型时返回空字典。

        Args:
            feature_key: 功能键，如 "icon_image_generation"

        Returns:
            {"api_key": "...", "base_url": "...", "model": "...", "provider": "..."}
            未绑定模型时返回空字典。
        """
        from flask import current_app

        _ctx = None
        try:
            current_app._get_current_object()
        except RuntimeError:
            from app.http.app import app
            _ctx = app.app_context()
            _ctx.push()

        try:
            from app.http.module import injector
            from internal.service.public_ai_feature_service import PublicAIFeatureService

            svc = injector.get(PublicAIFeatureService)
            model_config = svc.get_feature_model_config(feature_key)

            if model_config is not None:
                # 使用绑定模型的 provider 凭证
                creds = cls.get_provider_credentials(provider=model_config.provider)
                if creds:
                    # 覆盖 model 为功能绑定的具体模型
                    creds["model"] = model_config.model_name
                    return creds

            return {}
        finally:
            if _ctx is not None:
                _ctx.pop()

    @classmethod
    def _instantiate_model_from_pool_config(cls, model_config) -> object | None:
        """从 ModelPoolConfig 记录实例化 LLM。"""
        try:
            svc = cls._get_service_instance()
            config_dict = {
                "provider": model_config.provider,
                "model": model_config.model_name,
                "parameters": {},
            }
            # 加载 key 覆盖（与 resolve_runtime_language_model 一致）
            # _try_load_key_overrides_for_config 返回 attribute_overrides（api_key/base_url），
            # 必须作为 attribute_overrides 传入，不能替换 config_dict（否则丢失 provider/model）
            attribute_overrides = svc._try_load_key_overrides_for_config(config_dict)

            return svc._instantiate_language_model(config_dict, attribute_overrides=attribute_overrides)
        except Exception:
            logger.warning("_instantiate_model_from_pool_config: 实例化失败", exc_info=True)
            return None

    @classmethod
    def _get_service_instance(cls):
        """获取 LanguageModelService 实例（通过 injector）。"""
        from flask import current_app

        try:
            current_app._get_current_object()
        except RuntimeError:
            from app.http.app import app
            ctx = app.app_context()
            ctx.push()
            try:
                from app.http.module import injector
                return injector.get(LanguageModelService)
            finally:
                ctx.pop()

        from app.http.module import injector
        return injector.get(LanguageModelService)

    def _load_model_components(self, model_config: dict[str, Any]) -> tuple[Any, Any, Any]:
        """从数据库懒加载 provider/model 实体和 model_class

        返回 (provider_entity, model_entity, model_class)
        """
        normalized_model_config = deepcopy(model_config or {})
        provider_name = str(normalized_model_config.get("provider", "")).strip()
        model_name = str(normalized_model_config.get("model", "")).strip()

        # 懒加载 provider 和 model entity（从 DB）
        provider_entity = self.language_model_manager.get_or_load_provider(provider_name)
        model_entity = self.language_model_manager.get_or_load_model_entity(provider_name, model_name)

        # 从 model_entity.metadata 获取 compatible_api，再通过 ModelClassRegistry 解析
        compatible_api = model_entity.metadata.get("compatible_api", "openai")
        model_type = model_entity.model_type if isinstance(model_entity.model_type, str) else (
            model_entity.model_type.value if hasattr(model_entity.model_type, 'value') else str(model_entity.model_type)
        )

        from internal.core.language_model.model_class_registry import ModelClassRegistry
        model_class = ModelClassRegistry.resolve(compatible_api, model_type)

        return provider_entity, model_entity, model_class

    def _instantiate_language_model(self, model_config: dict[str, Any], attribute_overrides: dict[str, Any] | None = None) -> BaseLanguageModel:
        """严格按模型配置实例化语言模型。"""
        _, model_entity, model_class = self._load_model_components(model_config)
        normalized_model_config = deepcopy(model_config or {})
        attributes = deepcopy(getattr(model_entity, "attributes", {}) or {})
        if attribute_overrides:
            for name, value in attribute_overrides.items():
                if value is not None:
                    attributes[name] = value
        parameters = normalized_model_config.get("parameters", {}) or {}
        allowed_parameter_names = {
            parameter.name for parameter in getattr(model_entity, "parameters", []) or []
            if getattr(parameter, "name", "")
        }
        if allowed_parameter_names:
            parameters = {
                name: value for name, value in parameters.items()
                if name in allowed_parameter_names
            }
        # 构造原生模型实例（如 ChatOpenAI）
        # 注入 LLM_REQUEST_TIMEOUT 超时配置（原 providers/_defaults.py 能力迁移至此）
        # 网络层兜底超时：探针每 60s 检测一次 token 活性，httpx 流式模式下每个 chunk
        # 会重置 read timeout，因此 300s 仅在模型完全静默时触发，作为探针的最后一道防线
        # LLM_REQUEST_TIMEOUT 环境变量优先于模型 attributes 中的 request_timeout，
        # 避免数据库中遗留的短超时（如 30s）导致深度思考模型被误杀
        raw_timeout = os.getenv("LLM_REQUEST_TIMEOUT", "").strip()
        if raw_timeout:
            try:
                attributes["timeout"] = float(raw_timeout)
                # 清除 request_timeout，避免与 timeout 冲突
                attributes.pop("request_timeout", None)
            except (TypeError, ValueError):
                pass
        elif attributes.get("timeout") is None and attributes.get("request_timeout") is None:
            attributes["timeout"] = 300.0
        instance = model_class(
            **attributes,
            **parameters,
        )
        # 用 RuntimeFallbackLanguageModelProxy 包装，使其继承 BaseLanguageModel 的
        # features/metadata/convert_to_human_message/get_pricing 等方法和字段
        features_source = list(getattr(model_entity, "features", []) or [])
        metadata_source = dict(getattr(model_entity, "metadata", {}) or {})
        try:
            return RuntimeFallbackLanguageModelProxy.from_model(
                instance,
                fallback_loader=lambda: instance,
                requested_model_config=normalized_model_config,
                runtime_fallback_enabled=False,
                features_source=features_source,
                metadata_source=metadata_source,
            )
        except Exception:
            # 包装失败时回退到直接注入方式
            try:
                object.__setattr__(instance, "features", features_source)
            except Exception:
                pass
            try:
                object.__setattr__(instance, "metadata", metadata_source)
            except Exception:
                pass
            return instance

    def _get_model_entity_or_none(self, model_config: dict[str, Any] | None) -> Any:
        """安全获取模型实体，失败时返回 None。"""
        if not model_config:
            return None
        try:
            _, model_entity, _ = self._load_model_components(model_config)
            return model_entity
        except Exception:
            return None

    @classmethod
    def _normalize_model_ref(cls, model_config: dict[str, Any] | None) -> dict[str, Any]:
        """抽取 provider/model 作为统一模型引用。"""
        normalized_model_config = deepcopy(model_config or {})
        return {
            "provider": str(normalized_model_config.get("provider", "")).strip(),
            "model": str(normalized_model_config.get("model", "")).strip(),
        }

    @classmethod
    def _entrypoint_prefix(cls, entrypoint: str) -> str:
        """将入口名字转换成环境变量前缀。"""
        normalized_entrypoint = str(entrypoint or "").strip().upper()
        if normalized_entrypoint == "":
            return ""
        return f"{normalized_entrypoint}_"

    def _resolve_image_request_policy(self, entrypoint: str) -> str:
        """解析入口对应的图片请求策略。"""
        entrypoint_prefix = self._entrypoint_prefix(entrypoint)
        policy = str(
            self._get_config_value(
                f"{entrypoint_prefix}IMAGE_REQUEST_POLICY",
                self._get_config_value("IMAGE_REQUEST_POLICY", self.IMAGE_REQUEST_POLICY_STRICT),
            )
            or self.IMAGE_REQUEST_POLICY_STRICT
        ).strip().lower()
        if policy not in {self.IMAGE_REQUEST_POLICY_STRICT, self.IMAGE_REQUEST_POLICY_AUTO_UPGRADE}:
            return self.IMAGE_REQUEST_POLICY_STRICT
        return policy

    def _resolve_fallback_model_config(
        self,
        requested_model_config: dict[str, Any],
        entrypoint: str,
    ) -> dict[str, Any] | None:
        """解析入口对应的视觉兜底模型配置。"""
        entrypoint_prefix = self._entrypoint_prefix(entrypoint)
        provider_name = str(
            self._get_config_value(
                f"{entrypoint_prefix}VISION_FALLBACK_PROVIDER",
                self._get_config_value("VISION_FALLBACK_PROVIDER", ""),
            )
            or ""
        ).strip()
        model_name = str(
            self._get_config_value(
                f"{entrypoint_prefix}VISION_FALLBACK_MODEL",
                self._get_config_value("VISION_FALLBACK_MODEL", ""),
            )
            or ""
        ).strip()
        if provider_name == "" or model_name == "":
            return None

        return {
            "provider": provider_name,
            "model": model_name,
            "parameters": deepcopy((requested_model_config or {}).get("parameters", {}) or {}),
        }

    def _build_capabilities(
        self,
        *,
        requested_model_config: dict[str, Any],
        effective_model_config: dict[str, Any],
        entrypoint: str,
        allow_image_input: bool,
        resolution_action: str,
        reason_code: str = "",
        fallback_model_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构建统一的运行时能力描述。"""
        effective_model_entity = self._get_model_entity_or_none(effective_model_config)
        requested_model_entity = self._get_model_entity_or_none(requested_model_config)
        fallback_model_entity = self._get_model_entity_or_none(fallback_model_config)
        policy = self._resolve_image_request_policy(entrypoint)

        effective_features = list(getattr(effective_model_entity, "features", []) or [])
        requested_features = list(getattr(requested_model_entity, "features", []) or [])
        fallback_features = list(getattr(fallback_model_entity, "features", []) or [])

        effective_supports_image = ModelFeature.IMAGE_INPUT.value in effective_features
        requested_supports_image = ModelFeature.IMAGE_INPUT.value in requested_features
        fallback_supports_image = ModelFeature.IMAGE_INPUT.value in fallback_features
        via_fallback = (
            resolution_action == "auto_upgrade"
            and self._normalize_model_ref(requested_model_config) != self._normalize_model_ref(effective_model_config)
        )

        image_input_enabled = allow_image_input and (
            requested_supports_image or (policy == self.IMAGE_REQUEST_POLICY_AUTO_UPGRADE and fallback_supports_image)
        )

        message = ""
        if not allow_image_input:
            message = "当前入口暂不支持图片输入"
        elif requested_supports_image:
            message = "当前模型支持图片输入"
        elif via_fallback and effective_supports_image:
            message = "当前请求会自动升级到视觉模型处理图片"
        elif policy == self.IMAGE_REQUEST_POLICY_AUTO_UPGRADE and not fallback_supports_image:
            message = "当前模型不支持图片输入，且未配置可用的视觉兜底模型"
        else:
            message = "当前模型不支持图片输入"

        return {
            "requested_model": self._normalize_model_ref(requested_model_config),
            "effective_model": self._normalize_model_ref(effective_model_config),
            "features": effective_features,
            "requested_features": requested_features,
            "image_input": {
                "enabled": image_input_enabled,
                "via_fallback": via_fallback,
                "policy": policy,
                "requested_model_supports": requested_supports_image,
                "effective_model_supports": effective_supports_image,
                "fallback_model": self._normalize_model_ref(fallback_model_config) if fallback_model_config else None,
                "fallback_model_supports": fallback_supports_image,
                "reason_code": reason_code,
                "message": message,
            },
            "image_output": {
                "enabled": True,
                "reason_code": "IMAGE_OUTPUT_SUPPORTED",
            },
            "artifact_output": {
                "enabled": True,
                "reason_code": "ARTIFACT_OUTPUT_SUPPORTED",
            },
        }

    def describe_runtime_capabilities(
        self,
        model_config: dict[str, Any],
        *,
        entrypoint: str,
        allow_image_input: bool = True,
    ) -> dict[str, Any]:
        """描述入口在当前模型配置下的有效能力。"""
        normalized_model_config = deepcopy(model_config or {}) or self.get_default_model_config()
        fallback_model_config = self._resolve_fallback_model_config(normalized_model_config, entrypoint)
        effective_model_config = normalized_model_config
        resolution_action = "passthrough"

        requested_model_entity = self._get_model_entity_or_none(normalized_model_config)
        if requested_model_entity is None:
            effective_model_config = self.get_default_model_config()

        if allow_image_input:
            requested_model_entity = self._get_model_entity_or_none(effective_model_config)
            requested_supports_image = ModelFeature.IMAGE_INPUT.value in list(
                getattr(requested_model_entity, "features", []) or []
            )
            fallback_model_entity = self._get_model_entity_or_none(fallback_model_config)
            fallback_supports_image = ModelFeature.IMAGE_INPUT.value in list(
                getattr(fallback_model_entity, "features", []) or []
            )
            if not requested_supports_image and fallback_supports_image:
                resolution_action = "auto_upgrade"
                effective_model_config = fallback_model_config or effective_model_config

        return self._build_capabilities(
            requested_model_config=normalized_model_config,
            effective_model_config=effective_model_config,
            entrypoint=entrypoint,
            allow_image_input=allow_image_input,
            resolution_action=resolution_action,
            fallback_model_config=fallback_model_config,
        )

    def resolve_runtime_language_model(
        self,
        model_config: dict[str, Any],
        *,
        image_urls: list[str] | None = None,
        entrypoint: str,
        allow_image_input: bool = True,
        tier: str | None = None,
    ) -> RuntimeModelResolution:
        """解析运行时要使用的语言模型，并在必要时执行图片能力兜底。"""
        normalized_model_config = deepcopy(model_config or {}) or self.get_default_model_config()
        fallback_model_config = self._resolve_fallback_model_config(normalized_model_config, entrypoint)
        image_urls = image_urls or []

        try:
            key_overrides = self._try_load_key_overrides_for_config(normalized_model_config)
            llm = self._instantiate_language_model(normalized_model_config, attribute_overrides=key_overrides)
            effective_model_config = normalized_model_config
        except Exception:
            llm = self.load_default_language_model()
            effective_model_config = self.get_default_model_config()

        if not image_urls:
            if tier is not None:
                pool_resolution = self._try_resolve_pool_llm(tier)
                if pool_resolution is not None:
                    pool_llm, pool_model_config = pool_resolution
                    capabilities = self._build_capabilities(
                        requested_model_config=normalized_model_config,
                        effective_model_config=pool_model_config,
                        entrypoint=entrypoint,
                        allow_image_input=allow_image_input,
                        resolution_action="passthrough",
                        fallback_model_config=fallback_model_config,
                    )
                    return RuntimeModelResolution(
                        llm=self._wrap_runtime_fallback_model(pool_llm, pool_model_config),
                        requested_model_config=normalized_model_config,
                        effective_model_config=pool_model_config,
                        capabilities=capabilities,
                        resolution_action="pool",
                    )
            capabilities = self._build_capabilities(
                requested_model_config=normalized_model_config,
                effective_model_config=effective_model_config,
                entrypoint=entrypoint,
                allow_image_input=allow_image_input,
                resolution_action="passthrough",
                fallback_model_config=fallback_model_config,
            )
            return RuntimeModelResolution(
                llm=self._wrap_runtime_fallback_model(llm, effective_model_config),
                requested_model_config=normalized_model_config,
                effective_model_config=effective_model_config,
                capabilities=capabilities,
                resolution_action="passthrough",
            )

        if not allow_image_input:
            capabilities = self._build_capabilities(
                requested_model_config=normalized_model_config,
                effective_model_config=effective_model_config,
                entrypoint=entrypoint,
                allow_image_input=False,
                resolution_action="reject",
                reason_code="IMAGE_INPUT_DISABLED_FOR_ENTRYPOINT",
                fallback_model_config=fallback_model_config,
            )
            raise ValidateErrorException(
                "当前入口暂不支持图片输入，请移除图片后重试",
                data=capabilities,
                reason_code="IMAGE_INPUT_DISABLED_FOR_ENTRYPOINT",
            )

        if ModelFeature.IMAGE_INPUT.value in llm.features:
            capabilities = self._build_capabilities(
                requested_model_config=normalized_model_config,
                effective_model_config=effective_model_config,
                entrypoint=entrypoint,
                allow_image_input=True,
                resolution_action="passthrough",
                fallback_model_config=fallback_model_config,
            )
            return RuntimeModelResolution(
                llm=self._wrap_runtime_fallback_model(llm, effective_model_config),
                requested_model_config=normalized_model_config,
                effective_model_config=effective_model_config,
                capabilities=capabilities,
                resolution_action="passthrough",
            )

        if self._resolve_image_request_policy(entrypoint) == self.IMAGE_REQUEST_POLICY_AUTO_UPGRADE and fallback_model_config:
            fallback_llm = self._instantiate_language_model(fallback_model_config)
            if ModelFeature.IMAGE_INPUT.value in fallback_llm.features:
                capabilities = self._build_capabilities(
                    requested_model_config=normalized_model_config,
                    effective_model_config=fallback_model_config,
                    entrypoint=entrypoint,
                    allow_image_input=True,
                    resolution_action="auto_upgrade",
                    fallback_model_config=fallback_model_config,
                )
                fallback_llm = self._wrap_runtime_fallback_model(fallback_llm, fallback_model_config)
                return RuntimeModelResolution(
                    llm=fallback_llm,
                    requested_model_config=normalized_model_config,
                    effective_model_config=fallback_model_config,
                    capabilities=capabilities,
                    resolution_action="auto_upgrade",
                )

        reason_code = "IMAGE_INPUT_UNSUPPORTED"
        if self._resolve_image_request_policy(entrypoint) == self.IMAGE_REQUEST_POLICY_AUTO_UPGRADE and not fallback_model_config:
            reason_code = "VISION_FALLBACK_NOT_CONFIGURED"
        elif self._resolve_image_request_policy(entrypoint) == self.IMAGE_REQUEST_POLICY_AUTO_UPGRADE:
            reason_code = "VISION_FALLBACK_UNSUPPORTED"

        capabilities = self._build_capabilities(
            requested_model_config=normalized_model_config,
            effective_model_config=effective_model_config,
            entrypoint=entrypoint,
            allow_image_input=True,
            resolution_action="reject",
            reason_code=reason_code,
            fallback_model_config=fallback_model_config,
        )
        raise ValidateErrorException(
            "当前模型不支持图片输入，请切换到支持视觉的模型或配置视觉兜底模型后重试",
            data=capabilities,
            reason_code=reason_code,
        )

    def _try_load_key_overrides_for_config(self, model_config: dict[str, Any]) -> dict[str, Any] | None:
        """根据 model_config 中的 provider+model 从数据库加载对应 key，返回 attribute_overrides。

        当用户配置了 provider+model 但系统未通过 pool 路径加载 key 时，
        需要主动从 model_key_config 表加载并解密 key，避免 api_key 为空导致 401。
        """
        try:
            from internal.service.runtime_model_pool_service import RuntimeModelPoolService
            from internal.model.model_pool_entity import ModelPoolConfig

            provider = (model_config or {}).get("provider", "")
            model_name = (model_config or {}).get("model", "")
            if not provider or not model_name:
                return None

            pool_service = RuntimeModelPoolService(db=self.db)
            # 按 provider + model_name 精确查找模型池记录
            model_record = (
                pool_service._session()
                .query(ModelPoolConfig)
                .filter(
                    ModelPoolConfig.provider == provider,
                    ModelPoolConfig.model_name == model_name,
                    ModelPoolConfig.status == "active",
                )
                .first()
            )
            if model_record is None:
                return None

            key = pool_service.select_key(model_record.id)
            if key is None:
                return None

            llm_config = pool_service.build_llm_config(model_record, key)
            overrides: dict[str, Any] = {}
            api_key = llm_config.get("api_key")
            if api_key:
                overrides["api_key"] = api_key
            base_url = llm_config.get("base_url")
            if base_url:
                overrides["base_url"] = base_url
            return overrides if overrides else None
        except Exception as exc:
            logger.warning("加载模型 key 失败，降级到默认行为: provider=%s model=%s error=%s",
                           (model_config or {}).get("provider"), (model_config or {}).get("model"), exc)
            return None

    def _try_resolve_pool_llm(self, tier: str, model_type: str | None = None) -> tuple[BaseLanguageModel, dict[str, Any]] | None:
        """尝试从 admin 模型池解析运行时模型与 Key，失败或无配置时返回 None。"""
        try:
            from internal.service.runtime_model_pool_service import RuntimeModelPoolService

            pool_service = RuntimeModelPoolService(db=self.db)
            primary, _fallback_candidates = pool_service.select_model_with_fallback(tier, model_type)
            if primary is None:
                return None
            pool_model_config = {
                "provider": primary.provider,
                "model": primary.model_name,
                "parameters": {},
            }
            key = pool_service.select_key(primary.id)
            attribute_overrides: dict[str, Any] | None = None
            if key is not None:
                llm_config = pool_service.build_llm_config(primary, key)
                attribute_overrides = {}
                api_key = llm_config.get("api_key")
                if api_key:
                    attribute_overrides["api_key"] = api_key
                base_url = llm_config.get("base_url")
                if base_url:
                    attribute_overrides["base_url"] = base_url
                if not attribute_overrides:
                    attribute_overrides = None
            pool_llm = self._instantiate_language_model(pool_model_config, attribute_overrides=attribute_overrides)
            return pool_llm, pool_model_config
        except Exception as exc:
            logger.warning("模型池解析失败: tier=%s error=%s", tier, exc)
            return None

    def invoke_with_model_pool_fallback(self, tier: str, messages: Any, **kwargs) -> Any:
        """通过模型池 + FallbackLLMWrapper 执行带故障转移的 LLM 调用。"""
        from internal.service.fallback_llm_wrapper import FallbackLLMWrapper
        from internal.service.runtime_model_pool_service import RuntimeModelPoolService

        wrapper = FallbackLLMWrapper(
            runtime_model_pool_service=RuntimeModelPoolService(db=self.db),
            language_model_service=self,
        )
        return wrapper.invoke_with_fallback(tier, messages, **kwargs)

    def stream_with_model_pool_fallback(self, tier: str, messages: Any, **kwargs):
        """通过模型池 + FallbackLLMWrapper 执行带故障转移的流式 LLM 调用。"""
        from internal.service.fallback_llm_wrapper import FallbackLLMWrapper
        from internal.service.runtime_model_pool_service import RuntimeModelPoolService

        wrapper = FallbackLLMWrapper(
            runtime_model_pool_service=RuntimeModelPoolService(db=self.db),
            language_model_service=self,
        )
        return wrapper.stream_with_fallback(tier, messages, **kwargs)

    def _wrap_runtime_fallback_model(
        self,
        llm: BaseLanguageModel,
        model_config: dict[str, Any],
    ) -> BaseLanguageModel:
        """为非默认文本模型添加运行时兜底代理。"""
        requested_model_ref = _normalize_model_ref(model_config)
        if requested_model_ref == _normalize_model_ref(self.get_default_model_config()):
            return llm

        # 如果已经是 RuntimeFallbackLanguageModelProxy（_instantiate_language_model 已包装），
        # 只更新运行时兜底相关字段，避免再次 from_model 导致 _build_soft_timeout_model
        # 克隆内层 proxy 时产生 _primary_model 损坏的副本（双重包装 Bug）
        if isinstance(llm, RuntimeFallbackLanguageModelProxy):
            object.__setattr__(llm, "_fallback_loader", self.load_default_language_model)
            object.__setattr__(llm, "_requested_model_config", deepcopy(model_config or {}))
            object.__setattr__(llm, "_requested_model_ref", _normalize_model_ref(model_config))
            object.__setattr__(llm, "_runtime_fallback_enabled", True)
            return llm

        return RuntimeFallbackLanguageModelProxy.from_model(
            llm,
            fallback_loader=self.load_default_language_model,
            requested_model_config=model_config,
            runtime_fallback_enabled=True,
            features_source=list(getattr(llm, "features", []) or []),
            metadata_source=dict(getattr(llm, "metadata", {}) or {}),
        )

    def get_language_model_icon(self, provider_name: str) -> tuple[bytes, str]:
        """根据传递的提供者名字获取提供商对应的图标信息

        新架构下 icon 数据从 DB 的 ModelProviderConfig.icon 字段读取，
        该字段存储的是图标 URL 或 base64 数据；若为空则抛 NotFoundException。
        """
        provider_entity = self.language_model_manager.get_or_load_provider(provider_name)
        icon_value = (provider_entity.icon or "").strip()
        if not icon_value:
            raise NotFoundException("该模型提供者未配置图标")

        # 如果 icon 是 URL（http/https），返回字节流形式的占位说明
        if icon_value.startswith(("http://", "https://")):
            # 返回 URL 本身的字节，由调用方决定如何处理
            return icon_value.encode("utf-8"), "text/plain"

        # 如果 icon 是 base64 data URI，直接返回原始字节
        if icon_value.startswith("data:"):
            # 解析 data URI: data:image/png;base64,xxxx
            header, _, data = icon_value.partition(",")
            mimetype = "application/octet-stream"
            if ";base64," in header:
                import base64
                try:
                    return base64.b64decode(data), mimetype
                except Exception:
                    pass
            return data.encode("utf-8"), mimetype

        # 其他情况视为纯文本图标标识
        return icon_value.encode("utf-8"), "text/plain"

    def load_language_model(self, model_config: dict[str, Any]) -> BaseLanguageModel:
        """根据传递的模型配置加载大语言模型，并返回其实例

        与 resolve_runtime_language_model（Agent 路径）保持一致，
        主动从 model_key_config 表加载并解密 key，避免 api_key 为空导致 401。
        工作流 LLM 节点通过此方法加载模型。
        """
        try:
            key_overrides = self._try_load_key_overrides_for_config(model_config)
            llm = self._instantiate_language_model(model_config, attribute_overrides=key_overrides)
        except Exception as _:
            return self.load_default_language_model()
        return self._wrap_runtime_fallback_model(llm, model_config)

    def load_default_language_model(self) -> BaseLanguageModel:
        """加载默认的大语言模型，在模型管理器中获取不到模型或者出错时使用默认模型进行兜底。

        所有路径都走数据库配置，无任何硬编码 provider/key。
        """
        # 优先尝试从模型池解析兜底模型（按 tier 升序取第一个 active 模型）
        try:
            pool_llm_result = self._try_resolve_pool_llm(_DEFAULT_FALLBACK_TIER)
            if pool_llm_result is not None:
                llm, _ = pool_llm_result
                return llm
        except Exception:
            logger.warning("模型池解析默认模型失败", exc_info=True)

        # 模型池无可用模型时，直接从数据库取任意 active 模型 + active key 构建实例
        # 不再回退到硬编码 deepseek/deepseek-chat
        from internal.core.language_model.model_class_registry import ModelClassRegistry
        from internal.model.model_pool_entity import ModelKeyConfig, ModelPoolConfig
        from internal.model.model_provider_entity import ModelProviderConfig
        from internal.service.admin_model_pool_service import _decrypt_key_value

        model = self.db.session.query(ModelPoolConfig).filter_by(status="active").order_by(
            ModelPoolConfig.priority.desc(),
            ModelPoolConfig.created_at.asc(),
        ).first()
        if model is None:
            raise RuntimeError("无可用兜底模型，请在 admin 中配置模型池")
        provider_config = self.db.session.query(ModelProviderConfig).filter_by(name=model.provider).first()
        key = self.db.session.query(ModelKeyConfig).filter(
            ModelKeyConfig.provider == model.provider,
            ModelKeyConfig.status == "active",
        ).first()
        if key is None:
            raise RuntimeError(f"provider={model.provider} 无可用 key，请在 admin 中配置")

        model_class = ModelClassRegistry.resolve(
            model.compatible_api or "openai",
            model.model_type or "chat",
        )
        kwargs = {
            "model": model.model_name,
            "api_key": _decrypt_key_value(key.key_value_encrypted),
            "temperature": 1,
            "max_tokens": 8000,
        }
        if provider_config and provider_config.default_base_url:
            kwargs["base_url"] = provider_config.default_base_url
        raw_instance = model_class(**kwargs)
        # 用 RuntimeFallbackLanguageModelProxy 包装，确保具有
        # features/metadata/convert_to_human_message/get_pricing 等方法
        # 注意：ModelPoolConfig 是 SQLAlchemy 模型，其 .metadata 是表元数据(MetaData)而非 dict
        safe_features: list[Any] = []
        try:
            raw_features = getattr(model, "features", None)
            if isinstance(raw_features, (list, tuple)):
                safe_features = list(raw_features)
        except Exception:
            pass
        safe_metadata: dict[str, Any] = {}
        try:
            raw_metadata = getattr(model, "metadata", None)
            if isinstance(raw_metadata, dict):
                safe_metadata = dict(raw_metadata)
        except Exception:
            pass
        try:
            return RuntimeFallbackLanguageModelProxy.from_model(
                raw_instance,
                fallback_loader=lambda: raw_instance,
                requested_model_config={
                    "provider": model.provider,
                    "model": model.model_name,
                },
                runtime_fallback_enabled=False,
                features_source=safe_features,
                metadata_source=safe_metadata,
            )
        except Exception:
            return raw_instance
