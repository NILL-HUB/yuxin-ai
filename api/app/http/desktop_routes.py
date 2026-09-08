"""桌面客户端引导路由模块：GET /desktop-config（公开、无鉴权）。"""

from quart import Response, request

from app.http.support import _ok
from internal.entity.assistant_agent_entity import ASSISTANT_AGENT_DISPLAY_NAME

_registered = False


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.get("/desktop-config")
    async def async_desktop_config() -> Response:
        """返回当前服务器同源信息，供桌面客户端首次启动拉取与校验（公开、无鉴权）。"""
        scheme = request.headers.get("X-Forwarded-Proto") or request.scheme
        host = request.headers.get("X-Forwarded-Host") or request.host
        return _ok(
            {
                "app_name": ASSISTANT_AGENT_DISPLAY_NAME,
                "api_origin": f"{scheme}://{host}",
                "api_prefix": "/api",
            }
        )
