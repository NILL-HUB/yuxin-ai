# api/test/internal/core/language_model/test_language_model_manager.py
import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from internal.exception import NotFoundException
from internal.core.language_model.entities.provider_entity import ProviderEntity
from internal.core.language_model.language_model_manager import LanguageModelManager
from internal.model.model_pool_entity import ModelPoolConfig


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


class TestBuildModelEntityPricingMetadata:
    def _manager(self):
        return LanguageModelManager()

    def _config(self):
        config = MagicMock()
        config.model_name = "deepseek-chat"
        config.display_name = ""
        config.model_type = "chat"
        config.capabilities = []
        config.max_input_tokens = 8000
        config.max_tokens = 0
        config.max_output_tokens = 2000
        config.price_per_1k_tokens = 0
        config.input_price_per_1k_tokens = Decimal("0.002")
        config.output_price_per_1k_tokens = Decimal("0.008")
        config.input_cached_price_per_1k_tokens = Decimal("0.0005")
        config.input_cost_per_1k_tokens = Decimal("0.0009")
        config.output_cost_per_1k_tokens = Decimal("0.0036")
        config.input_cached_cost_per_1k_tokens = Decimal("0.0002")
        config.peak_valley_enabled = True
        config.cache_pricing_enabled = True
        config.peak_input_price_per_1k_tokens = Decimal("0.003")
        config.peak_output_price_per_1k_tokens = Decimal("0.012")
        config.peak_input_cached_price_per_1k_tokens = Decimal("0.0008")
        config.peak_input_cost_per_1k_tokens = Decimal("0.001")
        config.peak_output_cost_per_1k_tokens = Decimal("0.004")
        config.peak_input_cached_cost_per_1k_tokens = Decimal("0.00025")
        config.valley_input_price_per_1k_tokens = Decimal("0.001")
        config.valley_output_price_per_1k_tokens = Decimal("0.004")
        config.valley_input_cached_price_per_1k_tokens = Decimal("0.0002")
        config.valley_input_cost_per_1k_tokens = Decimal("0.0005")
        config.valley_output_cost_per_1k_tokens = Decimal("0.002")
        config.valley_input_cached_cost_per_1k_tokens = Decimal("0.0001")
        config.peak_windows = [{"days": "0-6", "start": "09:00", "end": "23:00"}]
        config.compatible_api = "openai"
        config.tier = "2"
        config.priority = 10
        config.fallback_model_id = None
        return config

    def test_build_model_entity_pricing_contains_peak_valley_cost_windows(self):
        manager = self._manager()
        entity = manager._build_model_entity(self._config(), ProviderEntity(name="p"))
        pricing = entity.metadata["pricing"]

        assert pricing["peak_valley_enabled"] is True
        assert pricing["cache_pricing_enabled"] is True
        assert pricing["peak_windows"] == [{"days": "0-6", "start": "09:00", "end": "23:00"}]

        assert pricing["peak"] == {
            "input": 0.003,
            "output": 0.012,
            "input_cached": 0.0008,
            "input_cost": 0.001,
            "output_cost": 0.004,
            "input_cached_cost": 0.00025,
        }
        assert pricing["valley"] == {
            "input": 0.001,
            "output": 0.004,
            "input_cached": 0.0002,
            "input_cost": 0.0005,
            "output_cost": 0.002,
            "input_cached_cost": 0.0001,
        }

    def test_build_model_entity_pricing_keeps_flat_and_legacy_keys(self):
        manager = self._manager()
        entity = manager._build_model_entity(self._config(), ProviderEntity(name="p"))
        pricing = entity.metadata["pricing"]

        assert pricing["input"] == 0.002
        assert pricing["output"] == 0.008
        assert pricing["input_cached"] == 0.0005
        assert pricing["input_cost"] == 0.0009
        assert pricing["output_cost"] == 0.0036
        assert pricing["input_cached_cost"] == 0.0002
        assert pricing["unit"] == 0.001

        assert set(pricing) >= {"input", "output", "unit", "input_cached", "input_cost", "output_cost", "input_cached_cost", "peak_valley_enabled", "cache_pricing_enabled", "peak_windows", "peak", "valley"}
        assert isinstance(pricing["input"], float)
        assert isinstance(pricing["input_cost"], float)
        assert isinstance(pricing["peak"]["output"], float)

    def test_build_model_entity_pricing_zero_split_falls_back_to_legacy_price(self):
        config = self._config()
        config.input_price_per_1k_tokens = Decimal("0")
        config.output_price_per_1k_tokens = Decimal("0")
        config.price_per_1k_tokens = Decimal("0.02")

        manager = self._manager()
        entity = manager._build_model_entity(config, ProviderEntity(name="p"))
        pricing = entity.metadata["pricing"]

        assert pricing["input"] == 0.02
        assert pricing["output"] == 0.02

    def test_build_model_entity_pricing_disabled_tiers_use_zero(self):
        config = self._config()
        config.peak_valley_enabled = False
        config.cache_pricing_enabled = False

        manager = self._manager()
        entity = manager._build_model_entity(config, ProviderEntity(name="p"))
        pricing = entity.metadata["pricing"]

        assert pricing["peak_valley_enabled"] is False
        assert pricing["cache_pricing_enabled"] is False
        assert pricing["peak_windows"] == [{"days": "0-6", "start": "09:00", "end": "23:00"}]

    def test_build_model_entity_pricing_missing_attrs_default_to_zero(self):
        config = ModelPoolConfig(
            model_name="bare",
            display_name="",
            model_type="chat",
            capabilities=[],
            max_input_tokens=0,
            max_tokens=0,
            max_output_tokens=0,
            price_per_1k_tokens=None,
        )

        manager = self._manager()
        entity = manager._build_model_entity(config, ProviderEntity(name="p"))
        pricing = entity.metadata["pricing"]

        assert pricing["input"] == 0.0
        assert pricing["output"] == 0.0
        assert pricing["input_cached"] == 0.0
        assert pricing["input_cost"] == 0.0
        assert pricing["output_cost"] == 0.0
        assert pricing["input_cached_cost"] == 0.0
        assert pricing["peak_windows"] == []
        assert pricing["peak"] == {
            "input": 0.0,
            "output": 0.0,
            "input_cached": 0.0,
            "input_cost": 0.0,
            "output_cost": 0.0,
            "input_cached_cost": 0.0,
        }
        assert pricing["valley"] == {
            "input": 0.0,
            "output": 0.0,
            "input_cached": 0.0,
            "input_cost": 0.0,
            "output_cost": 0.0,
            "input_cached_cost": 0.0,
        }
