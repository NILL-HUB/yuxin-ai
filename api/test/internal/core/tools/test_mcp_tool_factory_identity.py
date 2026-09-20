"""McpToolFactory 动态身份注入侧单测（ADMIN-P5，设计 §7.2）。

覆盖：
- `_binding_hash` 计算前剥离下划线开头的内部字段 → 含 `_principal_token`
  与不含的 binding 产出相同 hash，快照复用不受影响；
- `_jsonrpc_request` 读 `_principal_token` 并注入 `X-Admin-Agent-Principal`
  header；无该字段时保持原 header 不变。
"""
import json

import pytest

from internal.core.tools.mcp_tools.providers.mcp_tool_factory import McpToolFactory


@pytest.fixture(autouse=True)
def _clear_session_cache():
    """清空 `_get_session` 的 lru_cache，避免跨测试复用被 monkeypatch 的 session。

    `McpToolFactory._get_session` 带 `@lru_cache(maxsize=1)`：前一测试
    monkeypatch `requests.Session` 后，缓存的 session 会带着旧 handler 泄漏
    到后续测试（含其他测试文件），导致 post 走错 handler。
    """
    McpToolFactory._get_session.cache_clear()
    yield
    McpToolFactory._get_session.cache_clear()


class _FakeResponse:
    def __init__(self, payload: dict):
        self.text = json.dumps(payload, ensure_ascii=False)

    def raise_for_status(self):
        return None


class _FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.trust_env = True

    def post(self, url, json, headers, timeout):
        return self.handler(url, json, headers, timeout)


def test_binding_hash_strips_internal_underscore_fields():
    """含 `_principal_token` 的 binding 与剥离后的同一 binding hash 相同。

    为什么关键：动态签名每次不同（JWT 含 iat/exp），若参与 hash，快照
    每次刷新都失配 → 周期性多打 tools/list。剥离后快照复用不受影响。
    """
    binding = {
        "name": "global-mcp",
        "transport": "streamable_http",
        "url": "https://mcp.example.com",
        "enabled": True,
    }
    with_token = dict(binding)
    with_token["_principal_token"] = "signed-token-123"
    with_token["_other_internal"] = "internal"

    assert McpToolFactory._binding_hash(with_token) == McpToolFactory._binding_hash(
        binding
    )


def test_jsonrpc_request_injects_principal_header(monkeypatch):
    """带 `_principal_token` 时请求头含 X-Admin-Agent-Principal。"""
    captured = {}

    def _fake_post(url, json, headers, timeout):
        captured.update({"url": url, "headers": headers})
        return _FakeResponse({"jsonrpc": "2.0", "id": json["id"], "result": {}})

    monkeypatch.setattr(
        "internal.core.tools.mcp_tools.providers.mcp_tool_factory.requests.Session",
        lambda: _FakeSession(_fake_post),
    )

    factory = McpToolFactory()
    factory._jsonrpc_request(
        {
            "name": "global-mcp",
            "transport": "streamable_http",
            "url": "https://mcp.example.com",
            "_principal_token": "signed-token-123",
        },
        "tools/call",
        {"name": "weather", "arguments": {"city": "杭州"}},
    )

    assert captured["headers"].get("X-Admin-Agent-Principal") == "signed-token-123"


def test_jsonrpc_request_without_token_keeps_default_headers(monkeypatch):
    """无 `_principal_token` 时不注入动态 header（用户端等既有链路不受影响）。"""
    captured = {}

    def _fake_post(url, json, headers, timeout):
        captured.update({"headers": dict(headers)})
        return _FakeResponse({"jsonrpc": "2.0", "id": json["id"], "result": {}})

    monkeypatch.setattr(
        "internal.core.tools.mcp_tools.providers.mcp_tool_factory.requests.Session",
        lambda: _FakeSession(_fake_post),
    )

    factory = McpToolFactory()
    factory._jsonrpc_request(
        {
            "name": "global-mcp",
            "transport": "streamable_http",
            "url": "https://mcp.example.com",
        },
        "tools/call",
        {"name": "weather", "arguments": {}},
    )

    assert "X-Admin-Agent-Principal" not in captured["headers"]
