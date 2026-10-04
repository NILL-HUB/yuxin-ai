"""设备网关服务：手机远控的「云端 → 设备」常驻下行通道（子项目 B）。

设计（spec §4.3 / 计划 `docs/superpowers/plans/2026-10-04-device-gateway-p1.md`）：

- 设备侧经 Socket.IO ``/device`` 命名空间建立常驻连接，鉴权用 ``device_id + bridge_token``
  （复用注册凭证，不新增 token 类型；吊销设备即失效）。
- **链路在线标记**写入 Redis 键 ``device-link:<device_id>``（TTL 由设备端 ``device_ping`` 续），
  任意进程都能判定「可下发性」——compose 下 ASGI_WORKER_AMOUNT>1，与设备连接不在同一进程
  也必须成立，因此不能用进程内状态。
- **下行**：``RedisManager.emit("device_dispatch", ..., room="device-link:<id>", namespace="/device")``
  广播下发（设备连接所在进程负责转发）。
- **上行**：设备执行后 **HTTP 回传** ``POST /desktop/gateway/result``（上行方向无 NAT 问题），
  服务端 publish 到 ``device-gw-resp:<request_id>``，由**发起进程**的等待侧唤醒——
  闭环不依赖发起进程持有设备连接，天然支持多 worker。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from injector import inject
from redis import Redis

from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

logger = logging.getLogger(__name__)

# Socket.IO 设备命名空间（与 UI 通知的默认命名空间、/rt-voice 并列）
DEVICE_NAMESPACE = "/device"
# 链路在线标记键 / 广播房间（同一前缀，语义一致：链路存在）
DEVICE_LINK_KEY_PREFIX = "device-link:"
# TTL：设备端 ping 间隔（30s）的 6 倍，容忍抖动与短时断网；崩溃后自然过期
DEVICE_LINK_TTL_SECONDS = 180
# 结果回传频道前缀（一次性频道，按 request_id 隔离）
DEVICE_RESP_CHANNEL_PREFIX = "device-gw-resp:"
# 下行事件名（设备侧监听同名事件）
DEVICE_DISPATCH_EVENT = "device_dispatch"
# 默认等待时长（秒）
DEFAULT_CALL_TIMEOUT_SECONDS = 60


def device_link_room(device_id: str) -> str:
    """设备链路房间键（与在线标记键同源，单一事实源）。"""
    return f"{DEVICE_LINK_KEY_PREFIX}{str(device_id or '').strip()}"


@inject
class DeviceGatewayService(BaseService):
    """设备网关：链路在线判定 + 下行调用（同步等待结果）。"""

    def __init__(self, db: SQLAlchemy = None, redis_client: Redis = None):
        self.db = db
        self.redis_client = redis_client

    # ------------------------------------------------------------------ 链路标记

    def mark_link_online(self, device_id: str) -> None:
        """标记设备链路在线（连接建立 / device_ping 续期时调用）。"""
        device_id = str(device_id or "").strip()
        if not device_id:
            return
        try:
            self.redis_client.set(device_link_room(device_id), "1", ex=DEVICE_LINK_TTL_SECONDS)
        except Exception:
            logger.warning("设备链路标记写入失败 device=%s", device_id, exc_info=True)

    def mark_link_offline(self, device_id: str) -> None:
        """清除设备链路标记（断开时调用；异常按已离线处理）。"""
        device_id = str(device_id or "").strip()
        if not device_id:
            return
        try:
            self.redis_client.delete(device_link_room(device_id))
        except Exception:
            logger.warning("设备链路标记清除失败 device=%s", device_id, exc_info=True)

    def is_online(self, device_id: str) -> bool:
        """设备链路是否在线（可下发性判定；Redis 不可用时按离线处理，fail-safe）。"""
        device_id = str(device_id or "").strip()
        if not device_id:
            return False
        try:
            return bool(self.redis_client.exists(device_link_room(device_id)))
        except Exception:
            logger.warning("设备链路在线判定失败 device=%s", device_id, exc_info=True)
            return False

    # ------------------------------------------------------------------ 下行调用

    def call_device(
        self,
        device_id: str,
        *,
        purpose: str,
        payload: dict[str, Any],
        timeout: int = DEFAULT_CALL_TIMEOUT_SECONDS,
    ) -> dict[str, Any] | None:
        """经网关下发一次调用并等待结果。

        返回：
        - 设备链路离线 / device_id 为空 → ``None``（调用方按「设备离线」文案处理）；
        - 设备执行完成 → **worker 的原始 JSON**（与直连 bridge 的返回同形，便于调用方无差别消费）；
        - 传输层失败 / 超时 → ``{"ok": False, "error": ...}``（明确可读的中文文案）。
        """
        device_id = str(device_id or "").strip()
        if not device_id or not self.is_online(device_id):
            return None

        request_id = uuid.uuid4().hex
        channel = f"{DEVICE_RESP_CHANNEL_PREFIX}{request_id}"
        pubsub = None
        try:
            pubsub = self.redis_client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(channel)

            try:
                from internal.extension.socketio_extension import get_redis_manager

                get_redis_manager().emit(
                    DEVICE_DISPATCH_EVENT,
                    {
                        "request_id": request_id,
                        "purpose": purpose,
                        "payload": payload,
                        "timeout_ms": int(max(1, timeout) * 1000),
                    },
                    room=device_link_room(device_id),
                    namespace=DEVICE_NAMESPACE,
                )
            except Exception:
                logger.warning("设备网关下发失败 device=%s purpose=%s", device_id, purpose, exc_info=True)
                return {"ok": False, "error": "设备网关暂不可用，请稍后重试"}

            deadline = time.monotonic() + max(1, timeout)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.info("设备网关等待超时 device=%s purpose=%s request=%s", device_id, purpose, request_id)
                    return {"ok": False, "error": "设备响应超时，请稍后重试"}
                message = pubsub.get_message(timeout=min(remaining, 1.0))
                if not message or message.get("type") != "message":
                    continue
                raw = message.get("data")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                try:
                    response = json.loads(raw or "{}")
                except Exception:
                    logger.warning("设备网关回传解析失败 device=%s request=%s", device_id, request_id, exc_info=True)
                    return {"ok": False, "error": "设备回传格式异常"}
                if not response.get("ok"):
                    return {
                        "ok": False,
                        "error": str(response.get("error") or "设备执行失败"),
                    }
                result = response.get("result")
                if isinstance(result, dict):
                    return result
                return {"ok": False, "error": "设备回传结果格式异常"}
        finally:
            if pubsub is not None:
                try:
                    pubsub.unsubscribe(channel)
                except Exception:
                    pass
                try:
                    pubsub.close()
                except Exception:
                    pass

    def publish_result(
        self,
        request_id: str,
        *,
        ok: bool,
        result: Any = None,
        error: str = "",
    ) -> bool:
        """设备侧回传结果 → 唤醒等待侧（HTTP 回传端点调用）。

        频道无人订阅（等待已超时/进程重启）时静默丢弃——回传是**一次性**语义。
        """
        request_id = str(request_id or "").strip()
        if not request_id:
            return False
        payload = {"ok": bool(ok), "result": result if ok else None, "error": "" if ok else str(error or "")}
        try:
            self.redis_client.publish(
                f"{DEVICE_RESP_CHANNEL_PREFIX}{request_id}",
                json.dumps(payload, ensure_ascii=False, default=str),
            )
            return True
        except Exception:
            logger.warning("设备结果回传发布失败 request=%s", request_id, exc_info=True)
            return False
