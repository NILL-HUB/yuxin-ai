"""系统推送的客户端侧路由（账号 Bearer 鉴权）。

- POST /push/devices/register：App 上报推送令牌（个推 cid / 友盟 device_token），
  按 (account_id, provider, token) 幂等启用；
- POST /push/devices/unregister：登出/换机时停用令牌（保留记录，便于排障）。

admin 侧配置入口（/admin/push-config）在 admin_routes_8.py，与 mail/sms 配置同源模式。
"""

import logging

from quart import Response, request

from app.http.support import _ok

_registered = False


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.post("/push/devices/register")
    async def async_push_device_register() -> Response:
        """注册/刷新推送令牌（幂等：同账号同通道同令牌置 enabled）。"""
        from app.http import asgi_app as a
        from internal.service.push_device_service import PushDeviceService

        account, err = await a._resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True, silent=True) or {}
        try:
            device = await a._to_thread(
                a._get_service(PushDeviceService).register,
                account_id=account.id,
                platform=str(payload.get("platform") or ""),
                provider=str(payload.get("provider") or ""),
                token=str(payload.get("token") or ""),
            )
        except Exception as exc:
            from internal.exception import CustomException

            if isinstance(exc, CustomException):
                return a._json_resp(code="validate_error", message=str(exc.message), data={}, status=400)
            logging.exception("推送令牌注册失败")
            return a._json_resp(code="fail", message="推送令牌注册失败", data={}, status=500)
        return _ok(device)

    @quart_app.post("/push/devices/unregister")
    async def async_push_device_unregister() -> Response:
        """停用推送令牌（登出/换机；不存在时按成功返回，幂等）。"""
        from app.http import asgi_app as a
        from internal.service.push_device_service import PushDeviceService

        account, err = await a._resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True, silent=True) or {}
        try:
            result = await a._to_thread(
                a._get_service(PushDeviceService).unregister,
                account_id=account.id,
                provider=str(payload.get("provider") or ""),
                token=str(payload.get("token") or ""),
            )
        except Exception as exc:
            from internal.exception import CustomException

            if isinstance(exc, CustomException):
                return a._json_resp(code="validate_error", message=str(exc.message), data={}, status=400)
            logging.exception("推送令牌停用失败")
            return a._json_resp(code="fail", message="推送令牌停用失败", data={}, status=500)
        return _ok(result)
