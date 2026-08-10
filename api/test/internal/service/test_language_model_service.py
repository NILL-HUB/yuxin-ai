from pathlib import Path
from types import SimpleNamespace

import pytest
from test.context import TestApp
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from internal.exception import NotFoundException, ValidateErrorException
from internal.core.language_model.entities.model_entity import BaseLanguageModel, ModelFeature
from internal.service.language_model_service import LanguageModelService, _build_soft_timeout_model
from langchain_openai import ChatOpenAI


class _Provider:
    def __init__(self, provider_entity, models):
        self.provider_entity = provider_entity
        self.name = getattr(provider_entity, "name", None)
        self.label = getattr(provider_entity, "label", None)
        self.icon = getattr(provider_entity, "icon", None)
        self.description = getattr(provider_entity, "description", None)
        self.background = getattr(provider_entity, "background", None)
        self.supported_model_types = getattr(provider_entity, "supported_model_types", None)
        self.position = 1
        self._models = models

    def get_model_entities(self):
        return list(self._models.values())

    def get_model_entity(self, model_name: str):
        return self._models.get(model_name)

    @staticmethod
    def get_model_class(_model_type: str):
        return lambda **kwargs: SimpleNamespace(**kwargs)


class _RuntimeFallbackFakeLLM:
    def __init__(self, **kwargs):
        self.model = kwargs.get("model", "fake-model")
        self.temperature = kwargs.get("temperature")
        self.max_tokens = kwargs.get("max_tokens")
        self.request_timeout = kwargs.get("request_timeout")
        self.max_retries = kwargs.get("max_retries")
        self.features = list(kwargs.get("features", []))
        self.metadata = dict(kwargs.get("metadata", {}))
        self.return_value = kwargs.get("return_value", "primary-result")
        self.stream_chunks = list(kwargs.get("stream_chunks", ["primary-chunk"]))
        self.fail_invoke_error = kwargs.get("fail_invoke_error")
        self.fail_stream_error = kwargs.get("fail_stream_error")
        self.invoke_inputs: list[object] = []
        self.stream_inputs: list[object] = []
        self.bound_tools = None
        self.bound_kwargs = None
        self.structured_schema = None

    def _clone(self, **overrides):
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "request_timeout": self.request_timeout,
            "max_retries": self.max_retries,
            "features": list(self.features),
            "metadata": dict(self.metadata),
            "return_value": self.return_value,
            "stream_chunks": list(self.stream_chunks),
            "fail_invoke_error": self.fail_invoke_error,
            "fail_stream_error": self.fail_stream_error,
        }
        payload.update(overrides)
        return _RuntimeFallbackFakeLLM(**payload)

    def invoke(self, input_value, *args, **kwargs):
        self.invoke_inputs.append(input_value)
        if self.fail_invoke_error is not None:
            raise self.fail_invoke_error
        return self.return_value

    def stream(self, input_value, *args, **kwargs):
        self.stream_inputs.append(input_value)
        if self.fail_stream_error is not None:
            raise self.fail_stream_error
        for chunk in self.stream_chunks:
            yield chunk

    def bind_tools(self, tools):
        bound = self._clone()
        bound.bound_tools = list(tools)
        return bound

    def with_structured_output(self, schema):
        bound = self._clone()
        bound.structured_schema = schema
        return bound

    def bind(self, **kwargs):
        bound = self._clone()
        bound.bound_kwargs = dict(kwargs)
        return bound

    def model_copy(self, update=None, **_kwargs):
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "request_timeout": self.request_timeout,
            "max_retries": self.max_retries,
            "features": list(self.features),
            "metadata": dict(self.metadata),
            "return_value": self.return_value,
            "stream_chunks": list(self.stream_chunks),
            "fail_invoke_error": self.fail_invoke_error,
            "fail_stream_error": self.fail_stream_error,
            "bound_tools": list(self.bound_tools) if self.bound_tools is not None else None,
            "bound_kwargs": dict(self.bound_kwargs) if self.bound_kwargs is not None else None,
            "structured_schema": self.structured_schema,
        }
        if update:
            payload.update(update)
        clone = _RuntimeFallbackFakeLLM(**payload)
        return clone

    def get_num_tokens_from_messages(self, messages):
        return len(messages)


class _RetryableRuntimeError(Exception):
    status_code = 504


class _NonRetryableRuntimeError(Exception):
    status_code = 400


class _RuntimeModelHolder(BaseModel):
    llm: BaseLanguageModel


def _build_service(manager):
    return LanguageModelService(db=SimpleNamespace(), language_model_manager=manager)


def _build_runtime_service(model_entity, model_class_factory, monkeypatch, default_model_config=None):
    """按当前架构构建服务：manager 使用 get_or_load_* 接口，隔离 DB / 注册表 / 默认模型配置。

    - get_or_load_provider / get_or_load_model_entity：新架构懒加载接口
    - ModelClassRegistry.resolve：返回测试用模型类工厂
    - _try_load_key_overrides_for_config：避免走真实 DB 加载 key
    - get_default_model_config：返回与请求模型不同的默认配置，确保运行时兜底代理被启用
    """
    manager = SimpleNamespace(
        get_or_load_provider=lambda _name: SimpleNamespace(name=_name),
        get_or_load_model_entity=lambda _provider, _model: model_entity,
    )
    service = _build_service(manager=manager)
    monkeypatch.setattr(
        "internal.core.language_model.model_class_registry.ModelClassRegistry.resolve",
        lambda _compatible_api, _model_type: model_class_factory,
    )
    monkeypatch.setattr(service, "_try_load_key_overrides_for_config", lambda _config: None)
    monkeypatch.setattr(
        LanguageModelService,
        "get_default_model_config",
        classmethod(
            lambda cls: default_model_config or {"provider": "default", "model": "default-model"}
        ),
    )
    return service


class TestLanguageModelService:
    def test_get_language_models_should_map_provider_and_models(self, monkeypatch):
        provider_entity = SimpleNamespace(
            name="openai",
            label="OpenAI",
            icon="openai.png",
            description="desc",
            background="#fff",
            supported_model_types=["chat"],
        )
        provider = _Provider(provider_entity=provider_entity, models={})
        manager = SimpleNamespace(get_providers=lambda: [provider])
        service = _build_service(manager=manager)

        class _PoolModel:
            id = "m1"
            provider = "openai"
            model_name = "gpt-4o-mini"
            display_name = "GPT-4o mini"
            model_type = "chat"
            capabilities = ["chat"]
            max_tokens = 128000
            max_input_tokens = 124000
            max_output_tokens = 4000
            tier = "standard"
            price_per_1k_tokens = 0.03
            embedding_dimension = 0
            status = "active"

        class _Query:
            def filter(self, *_args, **_kwargs):
                return self

            def all(self):
                return [_PoolModel()]

        # get_language_models 内部通过 database_extension 按需 import db，需 patch 该模块属性
        monkeypatch.setattr(
            "internal.extension.database_extension.db",
            SimpleNamespace(session=SimpleNamespace(query=lambda _model: _Query())),
        )

        result = service.get_language_models()

        assert result[0]["name"] == "openai"
        assert result[0]["label"] == "OpenAI"
        assert result[0]["models"][0]["model_name"] == "gpt-4o-mini"
        # 上下文窗口与输出上限拆分：输入侧来自 max_input_tokens，输出侧来自 max_output_tokens
        assert result[0]["models"][0]["context_windows"] == 124000
        assert result[0]["models"][0]["max_output_tokens"] == 4000

    def test_get_language_model_should_raise_when_provider_not_found(self):
        def _raise_not_found(_provider_name, _model_name):
            raise NotFoundException()

        service = _build_service(
            manager=SimpleNamespace(get_or_load_model_entity=_raise_not_found)
        )

        with pytest.raises(NotFoundException):
            service.get_language_model("missing", "gpt-4o-mini")

    def test_get_language_model_should_raise_when_model_not_found(self):
        def _raise_not_found(_provider_name, _model_name):
            raise NotFoundException()

        service = _build_service(
            manager=SimpleNamespace(get_or_load_model_entity=_raise_not_found)
        )

        with pytest.raises(NotFoundException):
            service.get_language_model("openai", "missing-model")

    def test_get_language_model_should_return_serialized_model(self, monkeypatch):
        model_entity = SimpleNamespace(name="gpt-4o-mini")
        provider = _Provider(provider_entity=SimpleNamespace(name="openai"), models={"gpt-4o-mini": model_entity})
        service = _build_service(
            manager=SimpleNamespace(
                get_or_load_model_entity=lambda _provider_name, _model_name: provider.get_model_entity(_model_name)
            )
        )
        monkeypatch.setattr(
            "internal.service.language_model_service.convert_model_to_dict",
            lambda model: {"name": model.name, "model_type": "chat"},
        )

        result = service.get_language_model("openai", "gpt-4o-mini")

        assert result["name"] == "gpt-4o-mini"
        assert result["model_type"] == "chat"

    def test_get_language_model_icon_should_return_bytes_and_mimetype(self, tmp_path):
        root_path = Path(tmp_path)
        icon_path = root_path / "internal/core/language_model/providers/openai/_asset/openai.png"
        icon_path.parent.mkdir(parents=True, exist_ok=True)
        icon_path.write_bytes(b"icon-bytes")

        # current_app.root_path 会向上回退两级，因此这里构造 api/app 目录让计算后回到 tmp_root。
        (root_path / "api/app").mkdir(parents=True, exist_ok=True)
        flask_app = TestApp(__name__, root_path=str(root_path / "api/app"))

        provider_entity = SimpleNamespace(icon="openai.png")
        service = _build_service(
            manager=SimpleNamespace(get_or_load_provider=lambda _name: provider_entity)
        )

        with flask_app.app_context():
            content, mimetype = service.get_language_model_icon("openai")

        # 新架构下 icon 从 DB 读取，本地文件名按纯文本图标标识返回
        assert content == b"openai.png"
        assert mimetype == "text/plain"

    def test_get_language_model_icon_should_raise_when_provider_missing(self):
        def _raise_not_found(_provider_name):
            raise NotFoundException()

        service = _build_service(manager=SimpleNamespace(get_or_load_provider=_raise_not_found))

        with pytest.raises(NotFoundException):
            service.get_language_model_icon("missing")

    def test_get_language_model_icon_should_raise_when_icon_missing(self):
        # 新架构下 icon 从 DB 读取；icon 为空字符串时抛 NotFoundException
        provider_entity = SimpleNamespace(icon="")
        service = _build_service(
            manager=SimpleNamespace(get_or_load_provider=lambda _name: provider_entity)
        )

        with pytest.raises(NotFoundException):
            service.get_language_model_icon("openai")

    def test_load_language_model_should_fallback_to_default_model(self, monkeypatch):
        service = _build_service(manager=SimpleNamespace(get_provider=lambda _name: None))
        marker = SimpleNamespace(name="fallback-model")
        monkeypatch.setattr(service, "load_default_language_model", lambda: marker)

        result = service.load_language_model({"provider": "missing", "model": "x"})

        assert result is marker

    def test_load_language_model_should_build_model_instance_when_config_valid(self, monkeypatch):
        model_entity = SimpleNamespace(
            model_type="chat",
            attributes={"model": "gpt-4o-mini", "temperature": 0.5},
            parameters=[
                SimpleNamespace(name="max_tokens"),
            ],
            features=[ModelFeature.TOOL_CALL.value],
            metadata={"ctx": 8192},
        )
        service = _build_runtime_service(
            model_entity=model_entity,
            model_class_factory=lambda **kwargs: SimpleNamespace(**kwargs),
            monkeypatch=monkeypatch,
        )

        llm = service.load_language_model(
            {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "parameters": {"max_tokens": 4096},
            }
        )

        assert llm.model == "gpt-4o-mini"
        assert llm.temperature == 0.5
        assert llm.max_tokens == 4096
        assert llm.features == [ModelFeature.TOOL_CALL.value]
        assert llm.metadata.get("ctx") == 8192

    def test_load_language_model_should_satisfy_base_language_model_field_validation(self, monkeypatch):
        model_entity = SimpleNamespace(
            model_type="chat",
            attributes={"model": "gpt-4o-mini", "temperature": 0.5},
            parameters=[],
            features=[ModelFeature.TOOL_CALL.value],
            metadata={"ctx": 8192},
        )
        service = _build_runtime_service(
            model_entity=model_entity,
            model_class_factory=lambda **kwargs: SimpleNamespace(**kwargs),
            monkeypatch=monkeypatch,
        )

        llm = service.load_language_model(
            {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "parameters": {},
            }
        )

        holder = _RuntimeModelHolder(llm=llm)

        assert isinstance(holder.llm, BaseLanguageModel)
        assert holder.llm.model == "gpt-4o-mini"

    def test_load_language_model_should_enable_runtime_fallback_and_apply_soft_timeout_on_bind(self, monkeypatch):
        model_entity = SimpleNamespace(
            model_type="chat",
            attributes={"model": "gpt-4o-mini", "temperature": 0.5},
            parameters=[],
            features=[ModelFeature.TOOL_CALL.value],
            metadata={"ctx": 8192},
        )
        service = _build_runtime_service(
            model_entity=model_entity,
            model_class_factory=lambda **kwargs: _RuntimeFallbackFakeLLM(
                **kwargs,
                request_timeout=1800,
                max_retries=2,
                fail_invoke_error=_RetryableRuntimeError("gateway timeout"),
                return_value="primary-result",
            ),
            monkeypatch=monkeypatch,
        )
        monkeypatch.setattr(
            service,
            "load_default_language_model",
            lambda: _RuntimeFallbackFakeLLM(
                model="deepseek-chat",
                return_value="fallback-result",
            ),
        )

        llm = service.load_language_model(
            {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "parameters": {},
            }
        )

        bound_llm = llm.bind_tools(["tool-a"])

        # load_language_model 路径保留原始超时（软超时仅禁重试，不压缩 timeout）
        assert llm.request_timeout == 1800.0
        assert llm.max_retries == 2
        # bind 后的新代理应用软超时：保留 timeout，仅禁重试
        assert bound_llm.request_timeout == 1800.0
        assert bound_llm.max_retries == 0
        # 运行时兜底：主模型抛可重试错误时切换到默认模型
        assert llm.invoke("hello") == "fallback-result"

    def test_build_soft_timeout_model_should_disable_retries_and_preserve_timeout(self):
        original_model = ChatOpenAI(
            model="openai/gpt-5.2",
            api_key="test-key",
            base_url="https://api.atlascloud.ai/v1",
            request_timeout=1800,
            max_retries=2,
        )

        soft_timeout_model = _build_soft_timeout_model(original_model, 30.0)

        # 软超时模型不再压缩 timeout（由 LLMActivityProbe 接管死机检测），仅禁用重试
        assert soft_timeout_model.request_timeout == 1800.0
        assert soft_timeout_model.max_retries == 0
        assert soft_timeout_model is not original_model

    def test_load_language_model_should_strip_unsupported_parameters(self, monkeypatch):
        model_entity = SimpleNamespace(
            model_type="chat",
            attributes={"model": "gpt-5.2"},
            parameters=[
                SimpleNamespace(name="temperature"),
                SimpleNamespace(name="top_p"),
                SimpleNamespace(name="max_tokens"),
            ],
            features=[ModelFeature.TOOL_CALL.value],
            metadata={"ctx": 200000},
        )
        service = _build_runtime_service(
            model_entity=model_entity,
            model_class_factory=lambda **kwargs: SimpleNamespace(**kwargs),
            monkeypatch=monkeypatch,
        )

        llm = service.load_language_model(
            {
                "provider": "atlascloud",
                "model": "gpt-5.2",
                "parameters": {
                    "temperature": 0.7,
                    "top_p": 1,
                    "max_tokens": 4096,
                    "repetition_penalty": 1.2,
                },
            }
        )

        assert llm.temperature == 0.7
        assert llm.top_p == 1
        assert llm.max_tokens == 4096
        assert not hasattr(llm, "repetition_penalty")

    def test_load_default_language_model_should_use_expected_defaults(self, monkeypatch):
        from internal.model.model_pool_entity import ModelKeyConfig, ModelPoolConfig
        from internal.model.model_provider_entity import ModelProviderConfig

        class _OneResultQuery:
            def __init__(self, result):
                self._result = result

            def filter(self, *_args, **_kwargs):
                return self

            def filter_by(self, *_args, **_kwargs):
                return self

            def order_by(self, *_args, **_kwargs):
                return self

            def first(self):
                return self._result

            def all(self):
                return [self._result] if self._result is not None else []

            def one_or_none(self):
                return self._result

        class _DefaultModelSession:
            def __init__(self, model, provider_record, key_record):
                self._model = model
                self._provider_record = provider_record
                self._key_record = key_record

            def query(self, model_class):
                if model_class is ModelPoolConfig:
                    return _OneResultQuery(self._model)
                if model_class is ModelProviderConfig:
                    return _OneResultQuery(self._provider_record)
                return _OneResultQuery(self._key_record)

        model = SimpleNamespace(
            provider="openai",
            model_name="gpt-4o-mini",
            compatible_api="openai",
            model_type="chat",
            max_output_tokens=8192,
            features=[ModelFeature.TOOL_CALL.value],
            metadata={"ctx": 8192},
        )
        provider_record = SimpleNamespace(default_base_url="https://api.example.com")
        key_record = SimpleNamespace(key_value_encrypted="not-a-real-token")

        service = LanguageModelService(
            db=SimpleNamespace(session=_DefaultModelSession(model, provider_record, key_record)),
            language_model_manager=SimpleNamespace(),
        )
        monkeypatch.setattr(service, "_try_resolve_pool_llm", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            "internal.core.language_model.model_class_registry.ModelClassRegistry.resolve",
            lambda _compatible_api, _model_type: (lambda **kwargs: SimpleNamespace(**kwargs)),
        )

        llm = service.load_default_language_model()

        # 默认模型注入 temperature=1，输出上限取模型池配置 max_output_tokens
        assert llm.temperature == 1
        assert llm.max_tokens == 8192
        assert llm.features == [ModelFeature.TOOL_CALL.value]
        assert llm.metadata.get("ctx") == 8192

    def test_describe_runtime_capabilities_should_report_native_image_input(self, monkeypatch):
        image_model_entity = SimpleNamespace(
            model_type="chat",
            attributes={"model": "gpt-4o-mini"},
            features=[ModelFeature.TOOL_CALL.value, ModelFeature.IMAGE_INPUT.value],
            metadata={},
        )
        service = _build_runtime_service(
            model_entity=image_model_entity,
            model_class_factory=lambda **kwargs: SimpleNamespace(**kwargs),
            monkeypatch=monkeypatch,
        )

        capabilities = service.describe_runtime_capabilities(
            {"provider": "openai", "model": "gpt-4o-mini"},
            entrypoint=LanguageModelService.ENTRYPOINT_WEB_APP,
        )

        assert capabilities["image_input"]["enabled"] is True
        assert capabilities["image_input"]["via_fallback"] is False
        assert capabilities["effective_model"]["model"] == "gpt-4o-mini"
        assert capabilities["image_output"]["enabled"] is True
        assert capabilities["artifact_output"]["enabled"] is True

    def test_resolve_runtime_language_model_should_auto_upgrade_to_vision_fallback(self, monkeypatch):
        model_entities = {
            ("deepseek", "deepseek-chat"): SimpleNamespace(
                model_type="chat",
                attributes={"model": "deepseek-chat"},
                features=[ModelFeature.TOOL_CALL.value],
                metadata={},
            ),
            ("openai", "gpt-4o-mini"): SimpleNamespace(
                model_type="chat",
                attributes={"model": "gpt-4o-mini"},
                features=[ModelFeature.TOOL_CALL.value, ModelFeature.IMAGE_INPUT.value],
                metadata={},
            ),
        }

        manager = SimpleNamespace(
            get_or_load_provider=lambda _name: SimpleNamespace(name=_name),
            get_or_load_model_entity=lambda provider_name, model_name: model_entities.get(
                (provider_name, model_name)
            ),
        )
        service = _build_service(manager=manager)
        monkeypatch.setattr(
            "internal.core.language_model.model_class_registry.ModelClassRegistry.resolve",
            lambda _compatible_api, _model_type: (lambda **kwargs: SimpleNamespace(**kwargs)),
        )
        monkeypatch.setattr(service, "_try_load_key_overrides_for_config", lambda _config: None)
        monkeypatch.setattr(
            LanguageModelService,
            "get_default_model_config",
            classmethod(lambda cls: {"provider": "default", "model": "default-model"}),
        )
        monkeypatch.setattr(
            service,
            "_get_config_value",
            lambda key, default=None: {
                "IMAGE_REQUEST_POLICY": "auto_upgrade",
                "VISION_FALLBACK_PROVIDER": "openai",
                "VISION_FALLBACK_MODEL": "gpt-4o-mini",
            }.get(key, default),
        )

        resolution = service.resolve_runtime_language_model(
            {"provider": "deepseek", "model": "deepseek-chat"},
            image_urls=["https://example.com/cat.png"],
            entrypoint=LanguageModelService.ENTRYPOINT_WEB_APP,
        )

        assert resolution.llm.model == "gpt-4o-mini"
        assert resolution.resolution_action == "auto_upgrade"
        assert resolution.capabilities["image_input"]["via_fallback"] is True

    def test_resolve_runtime_language_model_should_raise_when_image_input_not_supported(self, monkeypatch):
        text_model_entity = SimpleNamespace(
            model_type="chat",
            attributes={"model": "deepseek-chat"},
            features=[ModelFeature.TOOL_CALL.value],
            metadata={},
        )
        service = _build_runtime_service(
            model_entity=text_model_entity,
            model_class_factory=lambda **kwargs: SimpleNamespace(**kwargs),
            monkeypatch=monkeypatch,
        )
        monkeypatch.setattr(service, "_get_config_value", lambda _key, default=None: default)

        with pytest.raises(ValidateErrorException) as exc:
            service.resolve_runtime_language_model(
                {"provider": "deepseek", "model": "deepseek-chat"},
                image_urls=["https://example.com/cat.png"],
                entrypoint=LanguageModelService.ENTRYPOINT_WEB_APP,
            )

        assert exc.value.data["image_input"]["reason_code"] == "IMAGE_INPUT_UNSUPPORTED"

    def test_load_language_model_should_fallback_to_default_model_for_retryable_text_errors(self, monkeypatch):
        model_entity = SimpleNamespace(
            model_type="chat",
            attributes={"model": "gpt-4o-mini", "temperature": 0.5},
            parameters=[],
            features=[ModelFeature.TOOL_CALL.value],
            metadata={"ctx": 8192},
        )

        service = _build_runtime_service(
            model_entity=model_entity,
            model_class_factory=lambda **kwargs: _RuntimeFallbackFakeLLM(
                **kwargs,
                fail_invoke_error=_RetryableRuntimeError("gateway timeout"),
                return_value="primary-result",
            ),
            monkeypatch=monkeypatch,
        )
        fallback_calls = []
        monkeypatch.setattr(
            service,
            "load_default_language_model",
            lambda: fallback_calls.append(1) or _RuntimeFallbackFakeLLM(
                model="deepseek-chat",
                return_value="fallback-result",
            ),
        )

        llm = service.load_language_model(
            {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "parameters": {},
            }
        )

        assert llm.model == "gpt-4o-mini"
        assert llm.features == [ModelFeature.TOOL_CALL.value]
        assert llm.metadata.get("ctx") == 8192
        assert llm.invoke("hello") == "fallback-result"
        assert fallback_calls == [1]

    def test_load_language_model_should_keep_runtime_fallback_after_structured_binding(self, monkeypatch):
        model_entity = SimpleNamespace(
            model_type="chat",
            attributes={"model": "gpt-4o-mini"},
            parameters=[],
            features=[ModelFeature.TOOL_CALL.value],
            metadata={},
        )
        provider = SimpleNamespace(
            get_model_entity=lambda _name: model_entity,
            get_model_class=lambda _type: (
                lambda **kwargs: _RuntimeFallbackFakeLLM(
                    **kwargs,
                    fail_invoke_error=_RetryableRuntimeError("gateway timeout"),
                    return_value="primary-result",
                )
            ),
        )
        service = _build_service(manager=SimpleNamespace(get_provider=lambda _name: provider))
        monkeypatch.setattr(
            service,
            "load_default_language_model",
            lambda: _RuntimeFallbackFakeLLM(
                model="deepseek-chat",
                return_value="fallback-result",
            ),
        )

        llm = service.load_language_model(
            {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "parameters": {},
            }
        )
        structured_llm = llm.with_structured_output(SimpleNamespace(name="Schema"))

        assert structured_llm.invoke("hello") == "fallback-result"

    def test_resolve_runtime_language_model_should_fallback_to_default_model_for_retryable_text_stream_errors(self, monkeypatch):
        model_entity = SimpleNamespace(
            model_type="chat",
            attributes={"model": "gpt-4o-mini"},
            parameters=[],
            features=[ModelFeature.TOOL_CALL.value],
            metadata={},
        )
        service = _build_runtime_service(
            model_entity=model_entity,
            model_class_factory=lambda **kwargs: _RuntimeFallbackFakeLLM(
                **kwargs,
                fail_stream_error=_RetryableRuntimeError("gateway timeout"),
            ),
            monkeypatch=monkeypatch,
        )
        fallback_calls = []
        monkeypatch.setattr(
            service,
            "load_default_language_model",
            lambda: fallback_calls.append(1) or _RuntimeFallbackFakeLLM(
                model="deepseek-chat",
                stream_chunks=["fallback-a", "fallback-b"],
            ),
        )

        resolution = service.resolve_runtime_language_model(
            {"provider": "openai", "model": "gpt-4o-mini"},
            image_urls=[],
            entrypoint=LanguageModelService.ENTRYPOINT_WEB_APP,
        )

        assert list(resolution.llm.stream("hello")) == ["fallback-a", "fallback-b"]
        assert fallback_calls == [1]

    def test_load_language_model_should_not_fallback_for_image_inputs(self, monkeypatch):
        model_entity = SimpleNamespace(
            model_type="chat",
            attributes={"model": "gpt-4o-mini"},
            parameters=[],
            features=[ModelFeature.TOOL_CALL.value],
            metadata={},
        )
        service = _build_runtime_service(
            model_entity=model_entity,
            model_class_factory=lambda **kwargs: _RuntimeFallbackFakeLLM(
                **kwargs,
                fail_invoke_error=_RetryableRuntimeError("gateway timeout"),
            ),
            monkeypatch=monkeypatch,
        )
        fallback_calls = []
        monkeypatch.setattr(
            service,
            "load_default_language_model",
            lambda: fallback_calls.append(1) or _RuntimeFallbackFakeLLM(
                model="deepseek-chat",
                return_value="fallback-result",
            ),
        )

        llm = service.load_language_model(
            {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "parameters": {},
            }
        )

        with pytest.raises(_RetryableRuntimeError):
            llm.invoke([
                HumanMessage(
                    content=[
                        {"type": "text", "text": "hello"},
                        {"type": "image_url", "image_url": {"url": "https://example.com/cat.png"}},
                    ]
                )
            ])

        assert fallback_calls == []

    def test_load_language_model_should_not_fallback_for_non_retryable_errors(self, monkeypatch):
        model_entity = SimpleNamespace(
            model_type="chat",
            attributes={"model": "gpt-4o-mini"},
            parameters=[],
            features=[ModelFeature.TOOL_CALL.value],
            metadata={},
        )
        service = _build_runtime_service(
            model_entity=model_entity,
            model_class_factory=lambda **kwargs: _RuntimeFallbackFakeLLM(
                **kwargs,
                fail_invoke_error=_NonRetryableRuntimeError("bad request"),
            ),
            monkeypatch=monkeypatch,
        )
        fallback_calls = []
        monkeypatch.setattr(
            service,
            "load_default_language_model",
            lambda: fallback_calls.append(1) or _RuntimeFallbackFakeLLM(
                model="deepseek-chat",
                return_value="fallback-result",
            ),
        )

        llm = service.load_language_model(
            {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "parameters": {},
            }
        )

        with pytest.raises(_NonRetryableRuntimeError):
            llm.invoke("hello")

        assert fallback_calls == []
