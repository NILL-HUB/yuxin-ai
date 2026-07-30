from contextlib import contextmanager
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
import json

import pytest
from werkzeug.datastructures import FileStorage

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.app_entity import DEFAULT_APP_CONFIG
from internal.entity.conversation_entity import InvokeFrom
from internal.entity.workflow_entity import WorkflowStatus
from internal.exception import FailException, NotFoundException
from internal.model import ApiTool, Message, Workflow
from internal.service.app_config_service import AppConfigService
from internal.service.assistant_agent_service import AssistantAgentService
from internal.service.cos_service import CosService
from internal.service.embeddings_service import EmbeddingsService
from internal.service.faiss_service import FaissService
from internal.service.upload_file_service import UploadFileService


@contextmanager
def _null_context():
    yield


class _QueryStub:
    def __init__(self, *, all_result=None):
        self._all_result = all_result if all_result is not None else []

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self._all_result


class TestEmbeddingsService:
    def test_init_should_construct_store_embeddings_and_cache(self, monkeypatch):
        store = object()
        embeddings = object()
        cache_embeddings = object()

        monkeypatch.setattr("internal.service.embeddings_service.RedisStore", lambda client: store)
        monkeypatch.setattr("internal.service.embeddings_service.OpenAIEmbeddings", lambda **kwargs: embeddings)
        monkeypatch.setattr(
            "internal.service.embeddings_service.CacheBackedEmbeddings.from_bytes_store",
            staticmethod(lambda _embeddings, _store, namespace, key_encoder: cache_embeddings),
        )
        from internal.service.language_model_service import LanguageModelService
        monkeypatch.setattr(
            LanguageModelService,
            "get_provider_credentials",
            classmethod(lambda cls, provider=None, model_type=None: {
                "api_key": "test-key",
                "base_url": "https://api.example.com/v1",
                "model": "Qwen/Qwen3-Embedding-8B",
                "provider": "SiliconFlow",
            } if model_type == "embedding" else {}),
        )

        service = EmbeddingsService(redis=SimpleNamespace())

        assert service.embeddings is embeddings
        assert service.cache_backed_embeddings is cache_embeddings

    def test_calculate_token_count_should_use_tiktoken_encoder(self, monkeypatch):
        monkeypatch.setattr(
            "internal.service.embeddings_service.tiktoken.encoding_for_model",
            lambda _model: SimpleNamespace(encode=lambda text: list(text)),
        )

        assert EmbeddingsService.calculate_token_count("abcd") == 4
