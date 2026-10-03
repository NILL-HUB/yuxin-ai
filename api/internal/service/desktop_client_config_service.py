"""桌面客户端连接与更新推送配置服务：单行 JSONB 存储（id=1）。

admin 端配置项：
- api_origin：桌面端 API 服务器地址（开发配本地、生产换域名），
  启动时经 GET /desktop-config 自动跟随；
- update_feed_url：更新包托管地址（electron-builder generic provider 的 base url，
  目录下需有 latest.yml / *.exe / *.blockmap）；
- update_enabled：是否向客户端下发更新。关闭后客户端检查更新被静默跳过，
  是「管理员决定是否推送」的开关。

客户端运行时读取点为公开接口 GET /desktop/update-manifest。
"""
from __future__ import annotations

from urllib.parse import urlparse

from internal.extension.database_extension import db
from internal.model.auth_channel_config import DesktopClientConfig

DEFAULT_KEYS = {
    "api_origin": "",
    "update_feed_url": "",
    "update_enabled": False,
}


def _normalize_http_url(value, field_label: str) -> str:
    """校验并规整 http(s) URL：空值或合法地址，其余抛 ValueError。"""
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"{field_label}必须是 http(s):// 开头的合法地址，或留空")
    return raw


def _normalize_bool(value) -> bool:
    """把表单/JSON 传入的任意真值表示归一为 bool。"""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


class DesktopClientConfigService:
    """桌面客户端连接与更新推送配置：单行记录（id=1），configs JSONB 持久化。"""

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
        if "api_origin" in payload:
            cfg["api_origin"] = _normalize_http_url(payload["api_origin"], "连接地址")
        if "update_feed_url" in payload:
            cfg["update_feed_url"] = _normalize_http_url(payload["update_feed_url"], "更新包地址")
        if "update_enabled" in payload:
            cfg["update_enabled"] = _normalize_bool(payload["update_enabled"])
        row = self._row()
        row.configs = cfg
        self.session.commit()
        return cfg

    def resolve_api_origin(self, fallback_origin: str) -> str:
        """桌面端引导用：返回配置的 api_origin；未配置时回退同源。"""
        configured = str(self.get_config().get("api_origin") or "").strip().rstrip("/")
        return configured or fallback_origin

    def resolve_update_manifest(self) -> dict:
        """客户端检查更新前的门控清单：管理员关闭推送时 enabled=False，客户端静默跳过。"""
        cfg = self.get_config()
        return {
            "enabled": bool(cfg.get("update_enabled")),
            "feed_url": str(cfg.get("update_feed_url") or "").strip().rstrip("/"),
        }
