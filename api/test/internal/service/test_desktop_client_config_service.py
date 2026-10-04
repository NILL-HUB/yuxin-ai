"""桌面客户端配置服务：gateway_mode 读取与校验（DB 优先、env 兜底、默认 off）。"""

import pytest

from internal.service.desktop_client_config_service import (
    DesktopClientConfigService,
    _normalize_gateway_mode,
)


def _service() -> DesktopClientConfigService:
    # 直连 DB session 的构造在单测中无意义：直接构造实例并覆盖 get_config
    return DesktopClientConfigService.__new__(DesktopClientConfigService)


def test_resolve_gateway_mode_prefers_db_value(monkeypatch):
    service = _service()
    monkeypatch.setattr(DesktopClientConfigService, "get_config", lambda self: {"gateway_mode": "Prefer"})

    assert service.resolve_gateway_mode() == "prefer"


def test_resolve_gateway_mode_env_fallback_and_default_off(monkeypatch):
    service = _service()
    monkeypatch.setattr(DesktopClientConfigService, "get_config", lambda self: {"gateway_mode": "bogus"})

    monkeypatch.setenv("DESKTOP_GATEWAY_MODE", "fallback")
    assert service.resolve_gateway_mode() == "fallback"

    monkeypatch.delenv("DESKTOP_GATEWAY_MODE", raising=False)
    assert service.resolve_gateway_mode() == "off"


def test_resolve_gateway_mode_fail_safe_when_db_unavailable(monkeypatch):
    service = _service()

    def _boom(self):
        raise RuntimeError("db down")

    monkeypatch.setattr(DesktopClientConfigService, "get_config", _boom)
    monkeypatch.setenv("DESKTOP_GATEWAY_MODE", "prefer")
    assert service.resolve_gateway_mode() == "prefer"

    monkeypatch.delenv("DESKTOP_GATEWAY_MODE", raising=False)
    assert service.resolve_gateway_mode() == "off"


def test_normalize_gateway_mode_rejects_invalid():
    assert _normalize_gateway_mode("OFF") == "off"
    assert _normalize_gateway_mode(" prefer ") == "prefer"
    with pytest.raises(ValueError):
        _normalize_gateway_mode("fast")
