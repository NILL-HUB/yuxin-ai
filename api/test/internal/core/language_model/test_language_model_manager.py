# api/test/internal/core/language_model/test_language_model_manager.py
import time
from unittest.mock import MagicMock, patch

import pytest

from internal.exception import NotFoundException
from internal.core.language_model.language_model_manager import LanguageModelManager


class TestLanguageModelManager:
    def test_get_or_load_provider_cache_hit(self):
        """第二次调用不查询 DB"""
        manager = LanguageModelManager()

        with patch.object(manager, '_db') as mock_db:
            mock_session = MagicMock()
            mock_db.session = mock_session
            mock_provider_config = MagicMock()
            mock_provider_config.name = "siliconflow"
            mock_provider_config.label = "硅基流动"
            mock_provider_config.description = ""
            mock_provider_config.icon = ""
            mock_provider_config.background = "#FFFFFF"
            mock_provider_config.default_base_url = "https://api.siliconflow.cn/v1"
            mock_provider_config.supported_model_types = ["chat"]
            mock_provider_config.status = "active"
            mock_session.query.return_value.filter_by.return_value.first.return_value = mock_provider_config

            # 第一次调用
            entity1 = manager.get_or_load_provider("siliconflow")
            assert entity1.name == "siliconflow"

            # 第二次调用应命中缓存
            first_call_count = mock_session.query.call_count
            entity2 = manager.get_or_load_provider("siliconflow")
            assert entity2 is entity1
            assert mock_session.query.call_count == first_call_count  # 无额外 DB 查询

    def test_get_or_load_provider_not_found(self):
        """DB 无记录抛 NotFoundException"""
        manager = LanguageModelManager()

        with patch.object(manager, '_db') as mock_db:
            mock_session = MagicMock()
            mock_db.session = mock_session
            mock_session.query.return_value.filter_by.return_value.first.return_value = None

            with pytest.raises(NotFoundException):
                manager.get_or_load_provider("nonexistent")

    def test_get_or_load_provider_disabled(self):
        """status='disabled' 抛 NotFoundException"""
        manager = LanguageModelManager()

        with patch.object(manager, '_db') as mock_db:
            mock_session = MagicMock()
            mock_db.session = mock_session
            mock_session.query.return_value.filter_by.return_value.first.return_value = None

            with pytest.raises(NotFoundException):
                manager.get_or_load_provider("disabled_provider")

    def test_invalidate_provider_clears_both_levels(self):
        """失效 provider 同时清空其下所有 model 缓存"""
        manager = LanguageModelManager()
        manager._provider_cache["test_provider"] = ("entity", time.time())
        manager._model_cache["test_provider"] = {"model_a": ("entity", time.time())}

        manager.invalidate_provider("test_provider")

        assert "test_provider" not in manager._provider_cache
        assert "test_provider" not in manager._model_cache

    def test_invalidate_model_only_clears_one(self):
        """失效单个 model 不影响同 provider 其他 model"""
        manager = LanguageModelManager()
        manager._model_cache["test_provider"] = {
            "model_a": ("entity_a", time.time()),
            "model_b": ("entity_b", time.time()),
        }

        manager.invalidate_model("test_provider", "model_a")

        assert "model_a" not in manager._model_cache["test_provider"]
        assert "model_b" in manager._model_cache["test_provider"]

    def test_invalidate_all(self):
        """全量失效"""
        manager = LanguageModelManager()
        manager._provider_cache["a"] = ("entity", time.time())
        manager._model_cache["a"] = {"m": ("entity", time.time())}

        manager.invalidate_all()

        assert len(manager._provider_cache) == 0
        assert len(manager._model_cache) == 0

    def test_get_providers_returns_list_from_db(self):
        """get_providers 从 DB 查询所有 active provider"""
        manager = LanguageModelManager()

        with patch.object(manager, '_db') as mock_db:
            mock_session = MagicMock()
            mock_db.session = mock_session
            mock_provider = MagicMock()
            mock_provider.name = "openai"
            mock_provider.label = "OpenAI"
            mock_provider.description = ""
            mock_provider.icon = ""
            mock_provider.background = "#FFFFFF"
            mock_provider.default_base_url = "https://api.openai.com/v1"
            mock_provider.supported_model_types = ["chat"]
            mock_provider.status = "active"
            mock_session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [mock_provider]

            providers = manager.get_providers()
            assert len(providers) == 1
            assert providers[0].name == "openai"
