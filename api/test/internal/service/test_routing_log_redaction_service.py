from copy import deepcopy

from internal.service.routing_log_redaction_service import (
    RoutingLogRedactionService,
)


def test_redaction_should_return_original_payload_when_disabled():
    payload = {"prompt": "secret prompt", "nested": {"token": "abc"}}

    result = RoutingLogRedactionService().redact(payload, redaction_enabled=False)

    assert result == payload


def test_redaction_should_recursively_redact_default_sensitive_fields():
    payload = {
        "prompt": "secret prompt",
        "raw_prompt": "raw",
        "api_key": "key",
        "nested": {
            "token": "abc",
            "headers": {"Authorization": "Bearer abc"},
            "arguments": {"query": "private"},
            "safe": "visible",
        },
        "items": [{"secret": "value", "name": "tool"}],
    }
    original = deepcopy(payload)

    result = RoutingLogRedactionService().redact(payload, redaction_enabled=True)

    assert result["prompt"] == "[REDACTED]"
    assert result["raw_prompt"] == "[REDACTED]"
    assert result["api_key"] == "[REDACTED]"
    assert result["nested"]["token"] == "[REDACTED]"
    assert result["nested"]["headers"] == "[REDACTED]"
    assert result["nested"]["arguments"] == "[REDACTED]"
    assert result["nested"]["safe"] == "visible"
    assert result["items"][0]["secret"] == "[REDACTED]"
    assert result["items"][0]["name"] == "tool"
    assert payload == original


def test_redaction_should_support_custom_sensitive_fields():
    payload = {"model_selection": {"key_id": "key-1", "model_id": "m1"}}

    result = RoutingLogRedactionService().redact(
        payload,
        redaction_enabled=True,
        sensitive_fields=["key_id"],
    )

    assert result == {
        "model_selection": {"key_id": "[REDACTED]", "model_id": "m1"}
    }
