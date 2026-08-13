from internal.core.agent.adapters.hermes.redact import (
    _mask_secret,
    redact_sensitive_text,
)


def test_mask_secret_short():
    assert _mask_secret("short") == "***"


def test_mask_secret_keeps_edges():
    masked = _mask_secret("sk-abcdefghijklmnopqrstuvwxyz")
    assert masked.startswith("sk-abc")
    assert masked.endswith("wxyz")
    assert "abcdefghijklmnopqrstuv" not in masked


def test_redact_openai_key():
    assert "sk-1234567890abcdefghij" not in redact_sensitive_text(
        "key=sk-1234567890abcdefghij"
    )


def test_redact_github_pat():
    assert "ghp_1234567890abcdefghij" not in redact_sensitive_text(
        "token ghp_1234567890abcdefghij used"
    )


def test_redact_env_assignment():
    out = redact_sensitive_text("OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz")
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in out
    assert "OPENAI_API_KEY=" in out


def test_redact_json_field():
    out = redact_sensitive_text('{"api_key": "sk-abcdefghijklmnopqrstuvwxyz"}')
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in out
    assert '"api_key":' in out


def test_redact_auth_header():
    out = redact_sensitive_text(
        "Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz"
    )
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in out
    assert "Authorization: Bearer" in out


def test_redact_url_query_param():
    out = redact_sensitive_text(
        "https://example.com/api?access_token=abcdefghijklmnopqrstuvwxyz&x=1"
    )
    assert "abcdefghijklmnopqrstuvwxyz" not in out
    assert "x=1" in out


def test_redact_leaves_plain_text():
    text = "今天天气不错，帮我写一首诗。token 这个词不该被误伤。"
    assert redact_sensitive_text(text) == text
