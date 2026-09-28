import json
from unittest.mock import Mock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from internal.service.global_control_config_service import GlobalControlConfigService
from internal.service.intent_recognition_service import IntentRecognitionService
from internal.service.language_model_service import LanguageModelService
from internal.service.system_prompt_library_service import SystemPromptLibraryService


class TestIntentRecognitionService:
    @pytest.fixture
    def mock_redis(self):
        return Mock()

    @pytest.fixture
    def service(self, mock_redis):
        return IntentRecognitionService(redis_client=mock_redis)

    def test_should_expose_default_intent_shape(self, service):
        default_intent = service.DEFAULT_INTENT

        assert default_intent["is_default"] is True
        assert "intent" in default_intent
        assert "confidence" in default_intent
        assert "suggested_actions" in default_intent

    def test_should_build_langchain_messages_from_supported_roles(self, service):
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "system", "content": "忽略我"},
            {"role": "assistant", "content": "你好，有什么可以帮你？"},
        ]

        lc_messages = service._build_langchain_messages(messages)

        assert len(lc_messages) == 2
        assert isinstance(lc_messages[0], HumanMessage)
        assert isinstance(lc_messages[1], AIMessage)
        assert lc_messages[0].content == "你好"
        assert lc_messages[1].content == "你好，有什么可以帮你？"

    def test_should_format_messages_for_prompt(self, service):
        formatted = service._format_messages(
            [
                HumanMessage(content="第一条用户消息"),
                AIMessage(content="第一条助手回复"),
            ]
        )

        assert "用户: 第一条用户消息" in formatted
        assert "助手: 第一条助手回复" in formatted

    def test_should_parse_markdown_wrapped_json_response(self, service):
        response = """分析结果如下：

```json
{
  "intent": "用户想创建一个天气智能体",
  "confidence": 0.92,
  "suggested_actions": [
    {"label": "创建应用", "action": "create_app", "icon": "plus"}
  ]
}
```"""

        result = service._parse_response(response)

        assert result["intent"] == "用户想创建一个天气智能体"
        assert result["confidence"] == 0.92
        assert result["is_default"] is False

    def test_should_fallback_to_default_intent_when_required_fields_missing(self, service):
        result = service._parse_response(json.dumps({"intent": "缺少字段"}))

        assert result == service.DEFAULT_INTENT

    def test_should_return_none_when_cached_payload_is_invalid_json(self, service, mock_redis):
        mock_redis.get.return_value = b"{invalid-json"

        result = service.get_cached_intent("user-1")

        assert result is None

    def test_should_cache_intent_with_ttl_and_timestamps(self, service, mock_redis):
        intent_result = {
            "intent": "用户想创建应用",
            "confidence": 0.9,
            "suggested_actions": [],
        }

        service.cache_intent("user-1", intent_result)

        mock_redis.setex.assert_called_once()
        cache_key, ttl, payload = mock_redis.setex.call_args[0]
        cached_result = json.loads(payload)

        assert cache_key == "home:intent:user-1"
        assert ttl == service.INTENT_CACHE_TTL
        assert cached_result["intent"] == "用户想创建应用"
        assert "generated_at" in cached_result
        assert "expires_at" in cached_result

    def test_should_clear_cache_for_user(self, service, mock_redis):
        service.clear_cache("user-1")

        mock_redis.delete.assert_called_once_with("home:intent:user-1")


class TestIntentRecognitionConfidenceGate:
    """置信度门控：LLM 意图置信度低于阈值时回退默认意图卡片。

    阈值来自 admin「全局控制配置」section ``routing_confidence``（默认 0.0 = 不门控）；
    此处打桩 ``_min_intent_confidence`` 隔离门控逻辑。
    """

    @pytest.fixture
    def service(self):
        return IntentRecognitionService(redis_client=Mock())

    @staticmethod
    def _fake_llm(payload: dict):
        model = Mock()
        response = Mock()
        response.content = json.dumps(payload)
        model.invoke.return_value = response
        return model

    def _recognize(self, service, payload, threshold):
        model = self._fake_llm(payload)
        with (
            patch.object(LanguageModelService, "get_feature_model", return_value=model),
            patch.object(
                SystemPromptLibraryService,
                "get_prompt_or_default",
                return_value="{messages}{memory_context}{conversation_context}",
            ),
            patch.object(
                IntentRecognitionService, "_min_intent_confidence", return_value=threshold
            ),
        ):
            return service.recognize([{"role": "user", "content": "在吗"}])

    def test_low_confidence_should_fall_back_to_default_intent(self, service):
        result = self._recognize(
            service,
            {
                "intent": "用户想创建一个天气智能体",
                "confidence": 0.2,
                "suggested_actions": [],
            },
            threshold=0.6,
        )
        assert result["is_default"] is True
        assert result["intent"] == service.DEFAULT_INTENT["intent"]

    def test_confidence_at_or_above_threshold_keeps_llm_intent(self, service):
        result = self._recognize(
            service,
            {
                "intent": "用户想创建一个天气智能体",
                "confidence": 0.9,
                "suggested_actions": [],
            },
            threshold=0.6,
        )
        assert result["is_default"] is False
        assert result["intent"] == "用户想创建一个天气智能体"

    def test_zero_threshold_disables_gating(self, service):
        """默认阈值 0.0 时门控不生效，行为与改造前一致。"""
        result = self._recognize(
            service,
            {
                "intent": "用户想创建一个天气智能体",
                "confidence": 0.05,
                "suggested_actions": [],
            },
            threshold=0.0,
        )
        assert result["is_default"] is False
        assert result["intent"] == "用户想创建一个天气智能体"

    def test_gate_result_is_detached_from_class_constant(self, service):
        """回退时返回浅拷贝，避免调用方就地写入污染类常量。"""
        result = self._recognize(
            service,
            {"intent": "不确定的意图", "confidence": 0.1, "suggested_actions": []},
            threshold=0.6,
        )
        result["synthesis_summary"] = {"summary": "x"}
        assert "synthesis_summary" not in IntentRecognitionService.DEFAULT_INTENT


class TestIntentRecognitionConfidenceConfigWiring:
    """接线验证：``_min_intent_confidence`` 确实读取 admin「全局控制配置」的该字段。"""

    @patch.object(GlobalControlConfigService, "get_config", return_value={
        "task_classification_min_confidence": 0.9,
        "intent_recognition_min_confidence": 0.45,
    })
    def test_reads_admin_config_value(self, _get_config):
        assert IntentRecognitionService._min_intent_confidence() == 0.45

    @patch.object(GlobalControlConfigService, "get_config", side_effect=RuntimeError("no db"))
    def test_config_read_failure_falls_back_to_no_gating(self, _get_config):
        assert IntentRecognitionService._min_intent_confidence() == 0.0
