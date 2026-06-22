from types import SimpleNamespace

import pytest

from internal.service.embeddings_service import EmbeddingsService


@pytest.fixture(autouse=True)
def _stub_redis_store(monkeypatch):
    monkeypatch.setattr(
        "internal.service.embeddings_service.RedisStore",
        lambda client: SimpleNamespace(),
    )


def _build_service(language_model_service=None):
    return EmbeddingsService(
        redis=SimpleNamespace(),
        language_model_service=language_model_service,
    )


class TestEmbeddingsServiceConfig:
    def test_default_provider_is_openai(self, monkeypatch):
        monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
        calls = []
        monkeypatch.setattr(
            "internal.service.embeddings_service.OpenAIEmbeddings",
            lambda model=None, **_kwargs: calls.append(model) or object(),
        )

        service = _build_service()
        _ = service.embeddings

        assert service.embedding_provider == "openai"
        assert calls == ["text-embedding-3-small"]

    def test_env_switches_provider_to_tongyi(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "tongyi")
        monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-v3")
        calls = []
        monkeypatch.setattr(
            "internal.service.embeddings_service.DashScopeEmbeddings",
            lambda model=None, **_kwargs: calls.append(model) or object(),
        )

        service = _build_service()
        _ = service.embeddings

        assert service.embedding_provider == "tongyi"
        assert calls == ["text-embedding-v3"]

    def test_dimension_from_config(self, monkeypatch):
        monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
        monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")

        service = _build_service()

        assert service.embedding_dimension == 3072

    def test_invalid_provider_falls_back_to_openai(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "invalid-provider")
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
        calls = []
        monkeypatch.setattr(
            "internal.service.embeddings_service.OpenAIEmbeddings",
            lambda model=None, **_kwargs: calls.append(model) or object(),
        )

        service = _build_service()
        _ = service.embeddings

        assert service.embedding_provider == "openai"
        assert calls == ["text-embedding-3-small"]
