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


def test_behavior_switch_features_not_in_builtin_features():
    """行为开关类 feature（runtime_fallback / media_fetch / agent_checkpoint_by_conversation）
    已迁移至「全局控制配置」板块（global_control_config 表），不得再被 seed。"""
    from internal.service.public_ai_feature_service import _BUILTIN_FEATURES

    keys = {f["feature_key"] for f in _BUILTIN_FEATURES}
    assert "media_fetch" not in keys
    assert "runtime_fallback" not in keys
    assert "agent_checkpoint_by_conversation" not in keys
    # 模型绑定类 feature 保留
    assert {"conductor", "schedule_intent_parser", "admin_agent", "vision_analyze"} <= keys


class TestRoutingFeaturesRegistered:
    """路由决策 feature 必须登记在 _BUILTIN_FEATURES，否则静默降级且 admin 不可见。

    背景（回归防护）：迁移 m8b9c0d1e2f3 曾以「指挥官已完全替代 orchestrator」为由
    删除 task_classification / pool_intent_resolution / tool_selection，但 home_service
    （首页，与 ENABLE_CONDUCTOR 无关）与 orchestrator_service 仍在调用它们。记录缺失时
    is_feature_enabled 返回 True、tier 回落默认档，功能会静默降级且管理员在
    /admin/public-ai-features 看不到、绑不了模型——违反「AI 配置走 admin」强制规则。
    """

    def test_legacy_orchestrator_routing_features_registered(self):
        from internal.service.public_ai_feature_service import _BUILTIN_FEATURES

        keys = {f["feature_key"] for f in _BUILTIN_FEATURES}
        assert {
            "task_classification",
            "pool_intent_resolution",
            "tool_selection",
            "public_agent_router",
        } <= keys

    def test_routing_features_default_tier_is_numeric(self):
        """档位必须是模型池数字档位口径（1~5），避免回落字符串档导致解析落空。"""
        from internal.service.public_ai_feature_service import _BUILTIN_FEATURES

        for feat in _BUILTIN_FEATURES:
            if feat["feature_key"] in {
                "task_classification",
                "pool_intent_resolution",
                "tool_selection",
                "public_agent_router",
            }:
                assert feat["fallback_tier"] in {"1", "2", "3", "4", "5"}
                assert feat["billable"] is False  # 平台路由决策，系统承担成本

    def test_every_registered_feature_has_required_keys(self):
        """每条登记项必须含 ensure_builtin_features 读取的全部字段。"""
        from internal.service.public_ai_feature_service import _BUILTIN_FEATURES

        required = {
            "feature_key",
            "feature_name",
            "feature_category",
            "feature_description",
            "model_type",
            "fallback_tier",
            "billable",
        }
        for feat in _BUILTIN_FEATURES:
            missing = required - set(feat)
            assert not missing, f"{feat.get('feature_key')} 缺少字段: {missing}"


def test_is_feature_enabled_reflects_record_flag():
    """is_feature_enabled 以表记录 enabled 为唯一事实源（无记录视为启用 fallback）。"""
    svc = _feature_service(SimpleNamespace(enabled=False))
    assert svc.is_feature_enabled("conductor") is False
    svc = _feature_service(SimpleNamespace(enabled=True))
    assert svc.is_feature_enabled("conductor") is True
    svc = _feature_service(None)
    assert svc.is_feature_enabled("conductor") is True
