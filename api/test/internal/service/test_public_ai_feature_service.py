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
