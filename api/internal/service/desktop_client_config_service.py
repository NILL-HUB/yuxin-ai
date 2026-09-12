"""桌面客户端连接配置服务：单行 JSONB 存储（id=1）。

admin 端配置桌面端 API 地址（api_origin）：开发环境配本地地址，
生产环境换域名；桌面端启动时经 GET /desktop-config 自动跟随。
"""
from __future__ import annotations

from urllib.parse import urlparse

from internal.extension.database_extension import db
from internal.model.auth_channel_config import DesktopClientConfig

DEFAULT_KEYS = {
    "api_origin": "",
}


def _normalize_api_origin(value) -> str:
    """校验并规整 api_origin：空值或合法 http(s) URL，其余抛 ValueError。"""
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("api_origin 必须是 http(s):// 开头的合法地址，或留空")
    return raw


class DesktopClientConfigService:
    """桌面客户端连接配置：单行记录（id=1），configs JSONB 持久化 api_origin。"""

    def __init__(self, session=None):
        self.session = session or db.session

    def _row(self) -> DesktopClientConfig:
        row = self.session.query(DesktopClientConfig).filter(DesktopClientConfig.id == 1).one_or_none()
        if row is None:
            row = DesktopClientConfig(id=1, configs={})
            self.session.add(row)
            self.session.flush()
        return row

    def get_config(self) -> dict:
        cfg = dict(DEFAULT_KEYS)
        row = self._row()
        if row.configs:
            cfg.update({k: v for k, v in row.configs.items() if k in DEFAULT_KEYS})
        return cfg

    def update_config(self, payload: dict) -> dict:
        cfg = self.get_config()
        for k in DEFAULT_KEYS:
            if k not in payload:
                continue
            cfg[k] = _normalize_api_origin(payload[k])
        row = self._row()
        row.configs = cfg
        self.session.commit()
        return cfg

    def resolve_api_origin(self, fallback_origin: str) -> str:
        """桌面端引导用：返回配置的 api_origin；未配置时回退同源。"""
        configured = str(self.get_config().get("api_origin") or "").strip().rstrip("/")
        return configured or fallback_origin
