"""桌面设备注册与动态 bridge 解析服务。

链路：桌面端登录 → 上报 {device_id, bridge_origin, bridge_token} →
服务端加密存 desktop_device 表 → Agent 工具执行时按 account_id 动态解析
出该账号默认设备的 bridge 地址与 token，替代静态 DESKTOP_BRIDGE_* 配置。
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from injector import inject

from internal.exception import NotFoundException, ValidateErrorException
from internal.model import DesktopDevice
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .tool_credential_encryptor import _decrypt_value, _encrypt_value

logger = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@inject
class DesktopDeviceService(BaseService):
    """桌面设备注册：单账号多设备，按 account_id 解析默认设备 bridge。"""

    def __init__(self, db: SQLAlchemy = None):
        self.db = db

    def register(
        self,
        *,
        account_id: UUID,
        device_id: str,
        bridge_origin: str,
        bridge_token: str,
        name: str = "",
        platform: str = "",
    ) -> dict:
        """注册/更新设备（同一 account_id + device_id 幂等 UPSERT）。"""
        device_id = str(device_id or "").strip()
        bridge_origin = str(bridge_origin or "").strip().rstrip("/")
        bridge_token = str(bridge_token or "").strip()
        if not device_id:
            raise ValidateErrorException("device_id 不能为空")
        if not bridge_origin:
            raise ValidateErrorException("bridge_origin 不能为空")
        if not bridge_origin.startswith(("http://", "https://")):
            raise ValidateErrorException("bridge_origin 必须以 http:// 或 https:// 开头")
        if not bridge_token:
            raise ValidateErrorException("bridge_token 不能为空")

        token_encrypted = _encrypt_value(bridge_token)
        existing = (
            self.db.session.query(DesktopDevice)
            .filter(
                DesktopDevice.account_id == account_id,
                DesktopDevice.device_id == device_id,
            )
            .one_or_none()
        )
        if existing is None:
            device = DesktopDevice(
                account_id=account_id,
                device_id=device_id,
                name=name or "",
                platform=platform or "",
                bridge_origin=bridge_origin,
                bridge_token_encrypted=token_encrypted,
                is_default=True,
                status="online",
                last_seen_at=_utcnow_naive(),
            )
            self.db.session.add(device)
            self.db.session.commit()
            logger.info("桌面设备注册成功 account=%s device=%s", account_id, device_id)
        else:
            self.update(
                existing,
                name=name or existing.name,
                platform=platform or existing.platform,
                bridge_origin=bridge_origin,
                bridge_token_encrypted=token_encrypted,
                status="online",
                last_seen_at=_utcnow_naive(),
            )
            logger.info("桌面设备更新成功 account=%s device=%s", account_id, device_id)

        return self._to_dict(existing if existing is not None else device)

    def resolve_bridge(self, account_id: UUID) -> tuple[str, str] | None:
        """解析该账号可用的 bridge (origin, token)；无可用设备返回 None。

        优先级：默认设备 > 最近活跃设备。仅取 online 状态。
        """
        device = (
            self.db.session.query(DesktopDevice)
            .filter(
                DesktopDevice.account_id == account_id,
                DesktopDevice.status == "online",
            )
            .order_by(DesktopDevice.is_default.desc(), DesktopDevice.last_seen_at.desc())
            .first()
        )
        if device is None:
            return None
        if not device.bridge_origin or not device.bridge_token_encrypted:
            return None
        try:
            token = _decrypt_value(device.bridge_token_encrypted)
        except ValueError:
            logger.warning("桌面设备 token 解密失败 device=%s", device.device_id)
            return None
        return str(device.bridge_origin).rstrip("/"), token

    def list_devices(self, account_id: UUID) -> list[dict]:
        """列出该账号的设备（token 脱敏，不返回明文）。"""
        rows = (
            self.db.session.query(DesktopDevice)
            .filter(DesktopDevice.account_id == account_id)
            .order_by(DesktopDevice.created_at.desc())
            .all()
        )
        return [self._to_dict(row) for row in rows]

    def revoke(self, account_id: UUID, device_id: str) -> bool:
        """吊销设备（置为 revoked，resolver 随即不再返回）。"""
        device = (
            self.db.session.query(DesktopDevice)
            .filter(
                DesktopDevice.account_id == account_id,
                DesktopDevice.device_id == device_id,
            )
            .one_or_none()
        )
        if device is None:
            raise NotFoundException("设备不存在")
        self.update(device, status="revoked")
        return True

    @staticmethod
    def _to_dict(device: DesktopDevice) -> dict:
        return {
            "device_id": device.device_id,
            "name": device.name,
            "platform": device.platform,
            "bridge_origin": device.bridge_origin,
            "is_default": bool(device.is_default),
            "status": device.status,
            "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        }
