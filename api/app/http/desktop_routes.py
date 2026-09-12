"""桌面客户端路由模块。

- GET /desktop-config：引导配置（公开、无鉴权）
- POST /desktop/devices/register：设备注册（需登录）
- GET /desktop/devices：设备列表（需登录）
- POST /desktop/devices/<device_id>/revoke：吊销设备（需登录）

设备注册用于打通「服务端 → 宿主机 worker」链路：桌面端上报 bridge 地址与
随机 token，服务端按账号动态解析，替代静态 DESKTOP_BRIDGE_* 配置。
"""

import logging

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
        """返回桌面客户端连接地址：优先 admin 配置的 api_origin（desktop_client_config 表），
        未配置时回退当前服务器同源。公开、无鉴权；该接口是桌面端引导入口，
        DB 不可用（如迁移未执行）时必须回退同源，不得 500。"""
        scheme = request.headers.get("X-Forwarded-Proto") or request.scheme
        host = request.headers.get("X-Forwarded-Host") or request.host
        same_origin = f"{scheme}://{host}"
        api_origin = same_origin
        try:
            from app.http.support import _to_thread
            from internal.service.desktop_client_config_service import (
                DesktopClientConfigService,
            )

            service = DesktopClientConfigService()
            api_origin = await _to_thread(service.resolve_api_origin, same_origin)
        except Exception:
            logging.exception("读取桌面客户端连接配置失败，回退同源 %s", same_origin)
        return _ok(
            {
                "app_name": ASSISTANT_AGENT_DISPLAY_NAME,
                "api_origin": api_origin,
                "api_prefix": "/api",
            }
        )

    @quart_app.post("/desktop/devices/register")
    async def async_desktop_device_register() -> Response:
        """桌面端登录后注册设备：上报 bridge 地址与访问 token（服务端加密存储）。"""
        from app.http import asgi_app as a
        from internal.service.desktop_device_service import DesktopDeviceService

        account, err = await a._resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True, silent=True) or {}
        try:
            device = await a._to_thread(
                a._get_service(DesktopDeviceService).register,
                account_id=account.id,
                device_id=str(payload.get("device_id") or ""),
                bridge_origin=str(payload.get("bridge_origin") or ""),
                bridge_token=str(payload.get("bridge_token") or ""),
                name=str(payload.get("name") or ""),
                platform=str(payload.get("platform") or ""),
            )
        except Exception as exc:
            from internal.exception import CustomException

            if isinstance(exc, CustomException):
                return a._json_resp(code="validate_error", message=str(exc.message), data={}, status=400)
            logging.exception("设备注册失败")
            return a._json_resp(code="fail", message="设备注册失败", data={}, status=500)
        return a._ok(device)

    @quart_app.get("/desktop/devices")
    async def async_desktop_device_list() -> Response:
        """列出当前账号已注册的桌面设备（token 脱敏）。"""
        from app.http import asgi_app as a
        from internal.service.desktop_device_service import DesktopDeviceService

        account, err = await a._resolve_account()
        if err is not None:
            return err

        devices = await a._to_thread(
            a._get_service(DesktopDeviceService).list_devices, account.id
        )
        return a._ok(devices)

    @quart_app.post("/desktop/devices/<string:device_id>/revoke")
    async def async_desktop_device_revoke(device_id: str) -> Response:
        """吊销设备：吊销后服务端不再向该设备转发本机操作。"""
        from app.http import asgi_app as a
        from internal.service.desktop_device_service import DesktopDeviceService

        account, err = await a._resolve_account()
        if err is not None:
            return err

        await a._to_thread(
            a._get_service(DesktopDeviceService).revoke, account.id, device_id
        )
        return a._ok({"revoked": True})
