import json

from internal.core.tools.builtin_tools.providers.x_search.x_search import (
    XSearchTool,
    _validate_date_range,
)


def test_requires_query():
    result = json.loads(XSearchTool()._run(query=""))
    assert result["ok"] is False


def test_requires_api_key(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    result = json.loads(XSearchTool()._run(query="AI news"))
    assert result["ok"] is False
    assert "XAI_API_KEY" in result["error"]


def test_validate_date_range():
    import pytest

    _validate_date_range("2026-01-01", "2026-12-31")  # ok
    with pytest.raises(ValueError):
        _validate_date_range("2026-12-31", "2026-01-01")  # inverted
    with pytest.raises(ValueError):
        _validate_date_range("bad", "")  # malformed


def test_validates_handle_conflict(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    result = json.loads(
        XSearchTool()._run(
            query="q", allowed_x_handles=["a"], excluded_x_handles=["b"]
        )
    )
    assert result["ok"] is False
    assert "不能同时使用" in result["error"]