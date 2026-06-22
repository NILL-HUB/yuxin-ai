import logging
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from injector import inject

from internal.service.language_model_service import LanguageModelService
from internal.service.runtime_model_pool_service import RuntimeModelPoolService


logger = logging.getLogger(__name__)


@inject
@dataclass
class FallbackLLMWrapper:
    """带故障转移的 LLM 调用包装器"""

    runtime_model_pool_service: RuntimeModelPoolService
    language_model_service: LanguageModelService

    def _build_llm(self, model: Any, key: Any) -> Any:
        config = self.runtime_model_pool_service.build_llm_config(model, key)
        provider, model_entity, model_class = self.language_model_service._load_model_components(
            {"provider": config["provider"], "model": config["model"]}
        )
        attributes = dict(model_entity.attributes or {})
        api_key = config.get("api_key")
        if api_key:
            attributes["api_key"] = api_key
            for base_url_field in ("base_url", "api_base"):
                if base_url_field in attributes and not attributes.get(base_url_field):
                    attributes.pop(base_url_field, None)
        parameters = config.get("parameters") or {}
        allowed_parameter_names = {
            parameter.name for parameter in getattr(model_entity, "parameters", []) or []
            if getattr(parameter, "name", "")
        }
        if allowed_parameter_names:
            parameters = {name: value for name, value in parameters.items() if name in allowed_parameter_names}
        return model_class(
            **attributes,
            **parameters,
            features=model_entity.features,
            metadata=model_entity.metadata,
        )

    def _invoke_llm(self, llm: Any, messages: Any, **kwargs) -> Any:
        return llm.invoke(messages, **kwargs)

    def _stream_llm(self, llm: Any, messages: Any, **kwargs) -> Generator:
        yield from llm.stream(messages, **kwargs)

    def _invoke_default(self, messages: Any, **kwargs) -> Any:
        default_llm = self.language_model_service.load_default_language_model()
        return self._invoke_llm(default_llm, messages, **kwargs)

    def _stream_default(self, messages: Any, **kwargs) -> Generator:
        default_llm = self.language_model_service.load_default_language_model()
        yield from self._stream_llm(default_llm, messages, **kwargs)

    @staticmethod
    def _estimate_credits(_result: Any) -> float:
        return 0.0

    def invoke_with_fallback(self, tier: str, messages: Any, **kwargs) -> Any:
        primary, candidates = self.runtime_model_pool_service.select_model_with_fallback(tier)
        if primary is None:
            return self._invoke_default(messages, **kwargs)

        for model in [primary, *candidates]:
            keys = self.runtime_model_pool_service.get_keys_for_model(model.id)
            for key in keys:
                try:
                    llm = self._build_llm(model, key)
                    result = self._invoke_llm(llm, messages, **kwargs)
                    self.runtime_model_pool_service.record_key_success(key.id, self._estimate_credits(result))
                    return result
                except Exception as exc:
                    logger.warning(
                        "模型池调用失败，切换下一个 Key/模型: tier=%s provider=%s model=%s key_id=%s error=%s",
                        tier,
                        getattr(model, "provider", None),
                        getattr(model, "model_name", None),
                        getattr(key, "id", None),
                        exc,
                    )
                    self.runtime_model_pool_service.record_key_failure(key.id)
                    continue

        logger.warning("模型池所有模型与 Key 均不可用，降级到默认模型: tier=%s", tier)
        return self._invoke_default(messages, **kwargs)

    def stream_with_fallback(self, tier: str, messages: Any, **kwargs) -> Generator:
        primary, candidates = self.runtime_model_pool_service.select_model_with_fallback(tier)
        if primary is None:
            yield from self._stream_default(messages, **kwargs)
            return

        for model in [primary, *candidates]:
            keys = self.runtime_model_pool_service.get_keys_for_model(model.id)
            for key in keys:
                yielded_any_chunk = False
                try:
                    llm = self._build_llm(model, key)
                    for chunk in self._stream_llm(llm, messages, **kwargs):
                        yielded_any_chunk = True
                        yield chunk
                    self.runtime_model_pool_service.record_key_success(key.id, self._estimate_credits(None))
                    return
                except Exception as exc:
                    if yielded_any_chunk:
                        raise
                    logger.warning(
                        "模型池流式调用失败，切换下一个 Key/模型: tier=%s provider=%s model=%s key_id=%s error=%s",
                        tier,
                        getattr(model, "provider", None),
                        getattr(model, "model_name", None),
                        getattr(key, "id", None),
                        exc,
                    )
                    self.runtime_model_pool_service.record_key_failure(key.id)
                    continue

        logger.warning("模型池所有模型与 Key 均不可用，流式降级到默认模型: tier=%s", tier)
        yield from self._stream_default(messages, **kwargs)
