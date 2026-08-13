import pytest

from scripts.browser_automation_worker import _run_playwright, _safe_url


def test_safe_url_allows_public_https():
    assert _safe_url("https://example.com/path") == "https://example.com/path"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://localhost",
        "http://192.168.1.10",
        "http://10.0.0.1",
        "ftp://example.com",
    ],
)
def test_safe_url_rejects_private_or_non_http(url):
    with pytest.raises(ValueError):
        _safe_url(url)


def test_run_playwright_rejects_unsupported_action():
    result = _run_playwright({"action": "delete", "url": "https://example.com"})
    assert result["ok"] is False
    assert "不支持的浏览器操作" in result["error"]


def test_run_playwright_navigate_requires_url():
    result = _run_playwright({"action": "navigate"})
    assert result["ok"] is False
    assert "需要 url" in result["error"]
