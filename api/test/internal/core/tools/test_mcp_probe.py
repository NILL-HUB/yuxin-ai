# api/test/internal/core/tools/test_mcp_probe.py
"""MCP 工具探测：区分「无工具」与「失败/前置缺失」（体检 P0-5 回归）。"""
from internal.core.tools.mcp_tools.providers.mcp_tool_factory import McpToolFactory


def _http_binding(**overrides):
    binding = {"name": "x", "transport": "http", "url": "http://example.com/mcp", "enabled": True}
    binding.update(overrides)
    return binding


def test_probe_missing_runtime():
    factory = McpToolFactory()
    result = factory.probe_remote_tool_definitions(
        {"name": "x", "transport": "stdio", "command": "definitely-not-a-real-binary-xyz", "enabled": True}
    )
    assert result.tools == []
    assert result.reason_code == "missing_runtime"
    assert "找不到命令" in result.error


def test_probe_unsupported_transport():
    factory = McpToolFactory()
    result = factory.probe_remote_tool_definitions(
        {"name": "x", "transport": "smoke-signal", "url": "http://x", "enabled": True}
    )
    assert result.reason_code == "unsupported_transport"


def test_probe_request_failure(monkeypatch):
    factory = McpToolFactory()

    def _boom(_binding):
        raise RuntimeError("network down")

    monkeypatch.setattr(factory, "_list_remote_tools", _boom)
    result = factory.probe_remote_tool_definitions(_http_binding())
    assert result.reason_code == "request_failed"
    assert "network down" in result.error


def test_probe_success_and_tool_name_filter(monkeypatch):
    factory = McpToolFactory()
    monkeypatch.setattr(factory, "_list_remote_tools", lambda _b: [{"name": "a"}, {"name": "b"}])

    result = factory.probe_remote_tool_definitions(_http_binding())
    assert [t["name"] for t in result.tools] == ["a", "b"]
    assert result.error == ""

    filtered = factory.probe_remote_tool_definitions(_http_binding(tool_names=["a"]))
    assert [t["name"] for t in filtered.tools] == ["a"]


def test_list_remote_tool_definitions_backward_compatible(monkeypatch):
    """旧方法保持返回 list（异常时为空列表），不破坏既有调用方。"""
    factory = McpToolFactory()
    monkeypatch.setattr(factory, "_list_remote_tools", lambda _b: [{"name": "a"}])
    assert factory.list_remote_tool_definitions(_http_binding()) == [{"name": "a"}]

    def _boom(_binding):
        raise RuntimeError("down")

    monkeypatch.setattr(factory, "_list_remote_tools", _boom)
    assert factory.list_remote_tool_definitions(_http_binding()) == []
