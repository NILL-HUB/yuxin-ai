"""Socket.IO 设备网关命名空间处理器（``/device``）。

设备侧（桌面客户端主进程）建立常驻连接，用于「云端 → 设备」的**下行指令**：

- ``connect``：``auth = {device_id, bridge_token}`` → 校验归属与凭证 → 加入房间
  ``device-link:<device_id>`` 并写入链路在线标记（Redis 键，TTL 由 ping 续期）。
- ``device_ping``：续期链路标记（设备端周期发送）。
- ``disconnect``：清理链路标记（以「本进程是否还有该设备连接」为准，避免多连接误删；
  异常崩溃的场景由标记 TTL 兜底）。

结果上行**不走本命名空间**：设备执行后经 HTTP ``POST /desktop/gateway/result`` 回传
（上行方向无 NAT 问题），见 `desktop_routes.py`。
"""

import logging
from typing import Any

from internal.extension.socketio_extension import get_socketio
from internal.service.device_gateway_service import (
    DEVICE_NAMESPACE,
    DeviceGatewayService,
    device_link_room,
)

logger = logging.getLogger(__name__)

# 进程内 sid → device_id 映射（仅用于断开时判定本进程是否仍有该设备连接，
# 多进程各自维护本进程视图；「可下发性」以 Redis 标记为权威）。
_sid_devices: dict[str, str] = {}


def _get_gateway_service() -> DeviceGatewayService:
    from app.http.module import injector

    return injector.get(DeviceGatewayService)


def _get_device_service():
    from app.http.module import injector
    from internal.service.desktop_device_service import DesktopDeviceService

    return injector.get(DesktopDeviceService)


async def handle_device_connect(
    sid: str,
    environ: dict[str, Any] | None = None,
    auth: dict[str, Any] | None = None,
) -> bool:
    """设备接入：校验 device_id + bridge_token，通过则进入链路房间。"""
    payload = auth or {}
    device_id = str(payload.get("device_id") or "").strip()
    token = str(payload.get("bridge_token") or "").strip()
    if not device_id or not token:
        logger.warning("[device-gw] rejected sid=%s: missing credentials", sid)
        return False

    try:
        verified = bool(_get_device_service().verify_bridge_token(device_id, token))
    except Exception:
        logger.warning("[device-gw] auth check failed sid=%s device=%s", sid, device_id, exc_info=True)
        return False
    if not verified:
        logger.warning("[device-gw] rejected sid=%s device=%s: invalid credentials", sid, device_id)
        return False

    sio = get_socketio()
    if sio is not None:
        await sio.enter_room(sid, device_link_room(device_id), namespace=DEVICE_NAMESPACE)
    _sid_devices[sid] = device_id
    try:
        _get_gateway_service().mark_link_online(device_id)
    except Exception:
        logger.warning("[device-gw] mark link online failed device=%s", device_id, exc_info=True)
    logger.info("[device-gw] link up device=%s sid=%s", device_id, sid)
    return True


async def handle_device_ping(sid: str, data: dict[str, Any] | None = None) -> None:
    """设备心跳：续期链路标记（异常一律吞掉，不影响连接）。"""
    device_id = _sid_devices.get(sid)
    if not device_id:
        return
    try:
        _get_gateway_service().mark_link_online(device_id)
    except Exception:
        logger.warning("[device-gw] ping refresh failed device=%s", device_id, exc_info=True)


async def handle_device_disconnect(sid: str) -> None:
    """设备断开：本进程已无该设备连接时清除链路标记。"""
    device_id = _sid_devices.pop(sid, None)
    if not device_id:
        return
    if device_id in _sid_devices.values():
        return
    try:
        _get_gateway_service().mark_link_offline(device_id)
    except Exception:
        logger.warning("[device-gw] mark link offline failed device=%s", device_id, exc_info=True)
    logger.info("[device-gw] link down device=%s sid=%s", device_id, sid)


def register_device_gateway_handlers(socketio: Any) -> None:
    """注册 /device 命名空间处理器（在 AsyncServer 初始化后调用）。"""
    socketio.on("connect", handle_device_connect, namespace=DEVICE_NAMESPACE)
    socketio.on("disconnect", handle_device_disconnect, namespace=DEVICE_NAMESPACE)
    socketio.on("device_ping", handle_device_ping, namespace=DEVICE_NAMESPACE)
