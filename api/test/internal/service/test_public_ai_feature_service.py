from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.http import module
from internal.exception import FailException
import internal.service.language_model_service as language_model_service


@contextmanager
def _no_app_context():
    yield


def test_get_feature_model_should_raise_when_feature_disabled(monkeypatch):
    feature_service = SimpleNamespace(is_feature_enabled=lambda feature_key: False)
    monkeypatch.setattr(language_model_service, "_ensure_app_context", _no_app_context)
    monkeypatch.setattr(
        module,
        "injector",
        SimpleNamespace(get=lambda _cls: feature_service),
    )

    with pytest.raises(FailException):
        language_model_service.LanguageModelService.get_feature_model("conductor")


class _FeatureQueryStub:
    def __init__(self, config):
        self._config = config

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self._config


class _FeatureDbStub:
    def __init__(self, config):
        self.session = SimpleNamespace(query=lambda _cls: _FeatureQueryStub(config))


def _feature_service(config):
    from internal.service.public_ai_feature_service import PublicAIFeatureService

    return PublicAIFeatureService(db=_FeatureDbStub(config))


def test_get_feature_fallback_tier_returns_numeric_default_when_missing():
    from internal.service.public_ai_feature_service import DEFAULT_FALLBACK_TIER

    svc = _feature_service(None)
    assert svc.get_feature_fallback_tier("conductor") == DEFAULT_FALLBACK_TIER == "2"


def test_get_feature_fallback_tier_normalizes_legacy_string_alias():
    # 历史遗留的字符串档位应归一化为数字档位，避免与模型池数字档位体系断层
    svc = _feature_service(SimpleNamespace(fallback_tier="cheap"))
    assert svc.get_feature_fallback_tier("memory_consolidation") == "1"


def test_get_feature_fallback_tier_passes_through_numeric_value():
    svc = _feature_service(SimpleNamespace(fallback_tier="3"))
    assert svc.get_feature_fallback_tier("conductor") == "3"
