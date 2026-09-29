# api/test/internal/core/language_model/test_capability_normalization.py
"""capabilities 标签归一化测试。

覆盖历史缺陷：中文能力标签（如"工具调用"）不被识别，导致 ModelFeature 丢失，
进而使 FunctionCallAgent 的 bind_tools 闸门误判为"模型不支持工具调用"。
"""
from internal.core.language_model.entities.model_entity import ModelFeature
from internal.core.language_model.language_model_manager import (
    _normalize_capability_to_feature,
)
from internal.model.model_pool_entity import ModelPoolConfig

from internal.core.language_model.entities.provider_entity import ProviderEntity
from internal.core.language_model.language_model_manager import LanguageModelManager


class TestNormalizeCapabilityToFeature:
    def test_english_aliases(self):
        assert _normalize_capability_to_feature("tool_call") == ModelFeature.TOOL_CALL
        assert _normalize_capability_to_feature("Tools") == ModelFeature.TOOL_CALL
        assert _normalize_capability_to_feature("function calling") == ModelFeature.TOOL_CALL
        assert _normalize_capability_to_feature("reasoning") == ModelFeature.AGENT_THOUGHT

    def test_enum_values(self):
        assert _normalize_capability_to_feature("tool_call") == ModelFeature.TOOL_CALL
        assert _normalize_capability_to_feature("agent_thought") == ModelFeature.AGENT_THOUGHT
        assert _normalize_capability_to_feature("image_input") == ModelFeature.IMAGE_INPUT

    def test_chinese_labels(self):
        assert _normalize_capability_to_feature("工具调用") == ModelFeature.TOOL_CALL
        assert _normalize_capability_to_feature("函数调用") == ModelFeature.TOOL_CALL
        assert _normalize_capability_to_feature("深度推理") == ModelFeature.AGENT_THOUGHT
        assert _normalize_capability_to_feature("视觉") == ModelFeature.IMAGE_INPUT
        assert _normalize_capability_to_feature("多模态") == ModelFeature.IMAGE_INPUT

    def test_chinese_compound_label_substring_fallback(self):
        assert _normalize_capability_to_feature("多模态理解和识别") == ModelFeature.IMAGE_INPUT
        assert _normalize_capability_to_feature("内置工具调用能力") == ModelFeature.TOOL_CALL
        assert _normalize_capability_to_feature("深度推理模型") == ModelFeature.AGENT_THOUGHT

    def test_unknown_and_non_string(self):
        assert _normalize_capability_to_feature("JSON输出") is None
        assert _normalize_capability_to_feature("1M上下文") is None
        assert _normalize_capability_to_feature("高性价比") is None
        assert _normalize_capability_to_feature("") is None
        assert _normalize_capability_to_feature(None) is None


class TestBuildModelEntityFeatures:
    def _build(self, capabilities):
        config = ModelPoolConfig(
            model_name="m",
            display_name="",
            model_type="chat",
            capabilities=capabilities,
            max_input_tokens=0,
            max_tokens=0,
            max_output_tokens=0,
            price_per_1k_tokens=None,
        )
        manager = LanguageModelManager()
        return manager._build_model_entity(config, ProviderEntity(name="p"))

    def test_chinese_capabilities_produce_features(self):
        """DB 中中文标注的能力必须能产出对应 ModelFeature（修复后）。"""
        entity = self._build(["1M上下文", "工具调用", "JSON输出", "深度推理", "高性价比"])
        assert ModelFeature.TOOL_CALL in entity.features
        assert ModelFeature.AGENT_THOUGHT in entity.features
        assert ModelFeature.IMAGE_INPUT not in entity.features

    def test_empty_capabilities_produce_no_features(self):
        entity = self._build([])
        assert entity.features == []
