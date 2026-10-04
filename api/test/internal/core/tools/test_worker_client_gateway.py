"""worker_client 设备网关路由测试：off/prefer/fallback 三模式与防重复执行语义。"""

import importlib
import json
import urllib.error

import pytest

module = importlib.import_module(
    "internal.core.tools.builtin_tools.providers.worker_client"
)


class _FakeGateway:
    def __init__(self, online=True, result=None):
        self.online = online
        self.result = result if result is not None else {"ok": True, "content": "via-gateway"}
        self.calls = []

    def is_online(self, device_id):
        self.calls.append(("is_online", device_id))
        return self.online

    def call_device(self, device_id, *, purpose, payload, timeout):
        self.calls.append(("call_device", device_id, purpose))
        return self.result


class _Resp:
    def read(self):
        return json.dumps({"ok": True, "from": "direct"}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


@pytest.fixture()
def env(monkeypatch):
    """构造：模式可控 + 假网关（经 injector 注入）+ 记录直连 urlopen 调用。"""
    from internal.service.desktop_device_service import DesktopDeviceService

    state = {"mode": "off"}
    monkeypatch.setattr(module, "_resolve_gateway_mode", lambda: state["mode"])

    gateway = _FakeGateway()

    class _Injector:
        def get(self, cls):
            return gateway

    monkeypatch.setattr("app.http.module.injector", _Injector())

    calls = {"urlopen": [], "raise": None}

    def _urlopen(request, timeout):
        calls["urlopen"].append(request)
        if calls["raise"] is not None:
            raise calls["raise"]
        return _Resp()

    monkeypatch.setattr(module.urllib.request, "urlopen", _urlopen)

    # 直连可解析：静态 env 兜底 + 设备 bridge 可解析（按需覆盖）
    monkeypatch.setenv("OS_AUTOMATION_URL", "http://worker:8765")
    monkeypatch.setenv("OS_AUTOMATION_TOKEN", "tok")
    monkeypatch.delenv("DESKTOP_BRIDGE_URL", raising=False)
    monkeypatch.delenv("DESKTOP_BRIDGE_TOKEN", raising=False)
    monkeypatch.setattr(DesktopDeviceService, "resolve_bridge", lambda self, account_id: None)
    monkeypatch.setattr(
        DesktopDeviceService,
        "resolve_bridge_for",
        lambda self, account_id, device_id: ("http://worker:8765", "tok"),
    )
    return state, gateway, calls


def test_off_mode_never_uses_gateway(env):
    """默认 off：即使网关在线也不走网关（零行为变化）。"""
    _state, gateway, calls = env

    result = module.call_host_worker(
        {"requester": "acct-1"}, purpose="/file", error_prefix="调用失败"
    )

    assert result == {"ok": True, "from": "direct"}
    assert gateway.calls == []
    assert len(calls["urlopen"]) == 1


def test_prefer_online_uses_gateway_and_skips_direct(env):
    state, gateway, calls = env
    state["mode"] = "prefer"

    result = module.call_host_worker(
        {"requester": "acct-1", "device_id": "dev-1"}, purpose="/file", error_prefix="调用失败"
    )

    assert result == {"ok": True, "content": "via-gateway"}
    assert ("call_device", "dev-1", "/file") in gateway.calls
    assert calls["urlopen"] == []


def test_prefer_gateway_error_is_final_no_double_exec(env):
    """网关一旦下发，其失败结果即最终结果——不得回退直连（防设备重复执行）。"""
    state, gateway, calls = env
    state["mode"] = "prefer"
    gateway.result = {"ok": False, "error": "设备响应超时，请稍后重试"}

    result = module.call_host_worker(
        {"requester": "acct-1", "device_id": "dev-1"}, purpose="/file", error_prefix="调用失败"
    )

    assert result == {"ok": False, "error": "设备响应超时，请稍后重试"}
    assert ("call_device", "dev-1", "/file") in gateway.calls
    assert calls["urlopen"] == []


def test_prefer_offline_falls_back_to_direct(env):
    state, gateway, calls = env
    state["mode"] = "prefer"
    gateway.online = False

    result = module.call_host_worker(
        {"requester": "acct-1", "device_id": "dev-1"}, purpose="/file", error_prefix="调用失败"
    )

    assert result == {"ok": True, "from": "direct"}
    assert not any(call[0] == "call_device" for call in gateway.calls)
    assert len(calls["urlopen"]) == 1


def test_fallback_retries_via_gateway_on_network_failure(env):
    state, gateway, calls = env
    state["mode"] = "fallback"
    calls["raise"] = OSError("connection refused")

    result = module.call_host_worker(
        {"requester": "acct-1", "device_id": "dev-1"}, purpose="/file", error_prefix="调用失败"
    )

    assert result == {"ok": True, "content": "via-gateway"}
    assert ("call_device", "dev-1", "/file") in gateway.calls


def test_fallback_offline_keeps_direct_error(env):
    state, gateway, calls = env
    state["mode"] = "fallback"
    gateway.online = False
    calls["raise"] = OSError("connection refused")

    result = module.call_host_worker(
        {"requester": "acct-1", "device_id": "dev-1"}, purpose="/file", error_prefix="调用失败"
    )

    assert result["ok"] is False
    assert "调用失败" in result["error"]
    assert not any(call[0] == "call_device" for call in gateway.calls)


def test_fallback_does_not_retry_after_http_error(env):
    """HTTPError 是设备已应答的业务错误——不是网络类失败，不触发网关重试。"""
    state, gateway, calls = env
    state["mode"] = "fallback"
    calls["raise"] = urllib.error.HTTPError("http://worker:8765/file", 500, "err", {}, None)

    result = module.call_host_worker(
        {"requester": "acct-1", "device_id": "dev-1"}, purpose="/file", error_prefix="调用失败"
    )

    assert result["ok"] is False
    assert not any(call[0] == "call_device" for call in gateway.calls)
