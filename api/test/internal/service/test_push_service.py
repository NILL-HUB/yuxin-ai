"""推送服务测试：请求构造（含签名）与主备编排（个推为主、友盟为辅）。"""

import hashlib
import json

import pytest

from internal.service import push_service as ps
from internal.service.push_config_service import PushConfigService
from internal.service.push_service import (
    PushGatewayService,
    build_getui_auth_request,
    build_getui_single_push_request,
    build_umeng_unicast_request,
    sign_getui_auth,
    sign_umeng,
)

GETUI_CREDS = {"app_id": "app-1", "app_key": "key-1", "app_secret": "as", "master_secret": "ms"}
UMENG_CREDS = {"app_key": "uk", "app_master_secret": "ums", "production_mode": False}


# ------------------------------------------------------------------ 请求构造

def test_sign_getui_auth_matches_documented_formula():
    assert sign_getui_auth("key-1", "1700000000000", "ms") == hashlib.sha256(
        b"key-11700000000000ms"
    ).hexdigest()


def test_build_getui_auth_request_shape():
    url, payload = build_getui_auth_request(GETUI_CREDS, timestamp="1700000000000")

    assert url == "https://restapi.getui.com/v2/app-1/auth"
    assert payload["appkey"] == "key-1"
    assert payload["timestamp"] == "1700000000000"
    assert payload["sign"] == sign_getui_auth("key-1", "1700000000000", "ms")


def test_build_getui_single_push_request_shape():
    url, payload = build_getui_single_push_request(
        GETUI_CREDS, cid="cid-1", title="标题", body="正文", click_url="https://example.com/x", ttl_ms=3600000
    )

    assert url == "https://restapi.getui.com/v2/app-1/push/single/cid"
    assert payload["audience"] == {"cid": ["cid-1"]}
    assert payload["settings"] == {"ttl": 3600000}
    assert len(payload["request_id"]) >= 10
    notification = payload["push_message"]["notification"]
    assert notification == {"title": "标题", "body": "正文", "click_type": "url", "url": "https://example.com/x"}


def test_build_getui_single_push_request_without_url_uses_startapp():
    _url, payload = build_getui_single_push_request(GETUI_CREDS, cid="cid-1", title="t", body="b")

    assert payload["push_message"]["notification"]["click_type"] == "startapp"
    assert "url" not in payload["push_message"]["notification"]


def test_build_umeng_unicast_request_shape_and_sign():
    url, body_str, payload = build_umeng_unicast_request(
        UMENG_CREDS, device_token="dt-1", title="标题", body="正文", timestamp="1700000000000"
    )

    assert url.startswith("https://msgapi.umeng.com/api/send?sign=")
    expected_sign = hashlib.md5(f"POST{ps.UMENG_SEND_URL}{body_str}ums".encode("utf-8")).hexdigest()
    assert url.endswith(expected_sign)
    assert payload["type"] == "unicast"
    assert payload["device_tokens"] == "dt-1"
    assert payload["production_mode"] is False
    assert payload["payload"]["body"]["after_open"] == "go_app"


# ------------------------------------------------------------------ 主备编排

def _gateway(monkeypatch, *, config, tokens, post_results):
    service = PushGatewayService(db=None)
    monkeypatch.setattr(PushConfigService, "get_runtime_config", lambda self: config)
    monkeypatch.setattr(service, "_enabled_tokens", lambda account_id: tokens)
    calls = []

    def _post(url, payload, headers=None, timeout=15):
        calls.append({"url": url, "payload": payload, "headers": headers or {}})
        if not post_results:
            raise AssertionError("unexpected extra request")
        return post_results.pop(0)

    monkeypatch.setattr(service, "_post_json", _post)
    return service, calls


ENABLED_CONFIG = {
    "enabled": True,
    "primary_provider": "getui",
    "fallback_enabled": True,
    "getui": GETUI_CREDS,
    "umeng": UMENG_CREDS,
}
GETUI_TOKEN = {"provider": "getui", "token": "cid-1", "platform": "android"}


def test_notify_skips_when_disabled(monkeypatch):
    service, calls = _gateway(monkeypatch, config={**ENABLED_CONFIG, "enabled": False}, tokens=[GETUI_TOKEN], post_results=[])

    result = service.notify_account("acct-1", title="t", body="b")

    assert result["skipped"] is True and result["reason"] == "disabled"
    assert calls == []


def test_notify_skips_without_tokens(monkeypatch):
    service, calls = _gateway(monkeypatch, config=ENABLED_CONFIG, tokens=[], post_results=[])

    result = service.notify_account("acct-1", title="t", body="b")

    assert result["skipped"] is True and result["reason"] == "no_device"
    assert calls == []


def test_notify_primary_success_does_not_touch_fallback(monkeypatch):
    service, calls = _gateway(
        monkeypatch,
        config=ENABLED_CONFIG,
        tokens=[GETUI_TOKEN],
        post_results=[
            {"code": 0, "data": {"token": "gt-token", "expire_time": 9_999_999_999_999}},
            {"code": 0, "msg": "", "data": {}},
        ],
    )

    result = service.notify_account("acct-1", title="t", body="b")

    assert result["ok"] is True
    assert len(calls) == 2  # auth + push
    assert calls[0]["url"].endswith("/auth")
    assert calls[1]["url"].endswith("/push/single/cid")
    assert calls[1]["headers"]["token"] == "gt-token"
    assert not any("umeng" in c["url"] for c in calls)


def test_notify_falls_back_to_umeng_when_getui_fails(monkeypatch):
    service, calls = _gateway(
        monkeypatch,
        config=ENABLED_CONFIG,
        tokens=[GETUI_TOKEN],
        post_results=[
            {"code": 0, "data": {"token": "gt-token", "expire_time": 9_999_999_999_999}},
            {"code": 500, "msg": "server error"},
            {"ret": "SUCCESS", "data": {}},
        ],
    )

    result = service.notify_account("acct-1", title="t", body="b")

    assert result["ok"] is True
    providers = [r["provider"] for r in result["results"]]
    assert providers == ["getui", "umeng"]
    assert result["results"][0]["ok"] is False
    assert result["results"][1]["ok"] is True
    assert calls[-1]["url"].startswith("https://msgapi.umeng.com/api/send")


def test_notify_reports_failure_when_both_channels_fail(monkeypatch):
    service, _calls = _gateway(
        monkeypatch,
        config=ENABLED_CONFIG,
        tokens=[GETUI_TOKEN],
        post_results=[
            {"code": 0, "data": {"token": "gt-token", "expire_time": 9_999_999_999_999}},
            {"code": 500, "msg": "boom"},
            {"ret": "FAIL", "data": {"error": "invalid token"}},
        ],
    )

    result = service.notify_account("acct-1", title="t", body="b")

    assert result["ok"] is False
    assert [r["ok"] for r in result["results"]] == [False, False]


def test_notify_skips_primary_without_credentials(monkeypatch):
    config = {**ENABLED_CONFIG, "getui": {"app_id": "", "app_key": "", "app_secret": "", "master_secret": ""}}
    service, calls = _gateway(
        monkeypatch, config=config, tokens=[GETUI_TOKEN], post_results=[{"ret": "SUCCESS", "data": {}}]
    )

    result = service.notify_account("acct-1", title="t", body="b")

    assert result["ok"] is True
    assert result["results"][0]["detail"] == "credentials_missing"
    assert len(calls) == 1  # 仅友盟被调用


def test_getui_invalid_token_triggers_refresh_and_retry(monkeypatch):
    service, calls = _gateway(
        monkeypatch,
        config=ENABLED_CONFIG,
        tokens=[GETUI_TOKEN],
        post_results=[
            {"code": 0, "data": {"token": "stale", "expire_time": 9_999_999_999_999}},
            {"code": 10001, "msg": "token invalid"},
            {"code": 0, "data": {"token": "fresh", "expire_time": 9_999_999_999_999}},
            {"code": 0, "msg": "", "data": {}},
        ],
    )

    result = service.notify_account("acct-1", title="t", body="b")

    assert result["ok"] is True
    assert len(calls) == 4
    assert calls[2]["url"].endswith("/auth")
    assert calls[3]["headers"]["token"] == "fresh"


@pytest.mark.parametrize("provider,expected", [("getui", True), ("umeng", True), ("wechat", False)])
def test_send_test_validates_provider(monkeypatch, provider, expected):
    service = PushGatewayService(db=None)
    monkeypatch.setattr(PushConfigService, "get_runtime_config", lambda self: ENABLED_CONFIG)
    monkeypatch.setattr(service, "_post_json", lambda *a, **k: {"code": 0, "data": {"token": "t", "expire_time": 9_999_999_999_999}} if a[0].endswith("/auth") else {"code": 0} if "getui" in a[0] else {"ret": "SUCCESS"})

    result = service.send_test(provider=provider, device_token="dt-1")

    assert result["ok"] is expected
