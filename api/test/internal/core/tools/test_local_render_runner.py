"""服务端侧本机渲染客户端：bridge 解析优先级、产物取回、错误包装。"""
import json

import pytest

from internal.core.tools.builtin_tools.providers.video_render_tools import (
    local_render_runner,
)


def _spec():
    return {
        "composition_id": "main",
        "width": 1920,
        "height": 1080,
        "duration": 10.0,
        "segments": [{"start": 0.0, "duration": 10.0, "text": "hi"}],
    }


def test_returns_not_available_when_no_bridge(monkeypatch):
    """无设备且无静态配置时返回不可用，供上层回退云端。"""
    monkeypatch.setattr(
        local_render_runner, "resolve_desktop_bridge", lambda *a, **k: None
    )
    result = local_render_runner.render_on_local_device(
        composition=_spec(), account_id="acc-1", name="demo"
    )
    assert result["ok"] is False
    assert result["unavailable"] is True


def test_prefers_account_scoped_bridge(monkeypatch):
    calls = []

    def fake_resolve(account_id, *, purpose=""):
        calls.append((account_id, purpose))
        return ("http://host:9876", "bridge-token")

    monkeypatch.setattr(local_render_runner, "resolve_desktop_bridge", fake_resolve)
    monkeypatch.setattr(
        local_render_runner,
        "_post_render",
        lambda **kwargs: {"ok": True, "path": "/tmp/out.mp4", "size_bytes": 10},
    )
    result = local_render_runner.render_on_local_device(
        composition=_spec(), account_id="acc-1", name="demo"
    )

    assert result["ok"] is True
    assert calls == [("acc-1", "/render")]


def test_posts_composition_to_render_route(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        local_render_runner,
        "resolve_desktop_bridge",
        lambda *a, **k: ("http://host:9876", "bridge-token"),
    )

    def fake_post(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "path": "/tmp/out.mp4", "size_bytes": 10}

    monkeypatch.setattr(local_render_runner, "_post_render", fake_post)
    local_render_runner.render_on_local_device(
        composition=_spec(), account_id="acc-1", name="demo"
    )

    assert captured["endpoint"] == "http://host:9876/render"
    assert captured["token"] == "bridge-token"
    assert captured["payload"]["name"] == "demo"
    assert captured["payload"]["composition"]["segments"][0]["text"] == "hi"


def test_worker_error_is_not_unavailable(monkeypatch):
    """worker 明确返回失败 ≠ 通道不可用：不应触发云端回退。"""
    monkeypatch.setattr(
        local_render_runner,
        "resolve_desktop_bridge",
        lambda *a, **k: ("http://host:9876", "bridge-token"),
    )
    monkeypatch.setattr(
        local_render_runner,
        "_post_render",
        lambda **kwargs: {"ok": False, "error": "渲染环境缺少必需配置：HYPERFRAMES_BROWSER_PATH"},
    )
    result = local_render_runner.render_on_local_device(
        composition=_spec(), account_id="acc-1", name="demo"
    )
    assert result["ok"] is False
    assert result.get("unavailable") is not True
    assert "HYPERFRAMES" in result["error"]


def test_connection_failure_is_unavailable(monkeypatch):
    """连不上桌面 bridge 视为通道不可用，允许回退云端。"""
    monkeypatch.setattr(
        local_render_runner,
        "resolve_desktop_bridge",
        lambda *a, **k: ("http://host:9876", "bridge-token"),
    )

    def boom(**kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(local_render_runner, "_post_render", boom)
    result = local_render_runner.render_on_local_device(
        composition=_spec(), account_id="acc-1", name="demo"
    )
    assert result["ok"] is False
    assert result["unavailable"] is True
