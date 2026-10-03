"""桌面设备注册与动态 bridge 解析服务。

链路：桌面端登录 → 上报 {device_id, bridge_origin, bridge_token} →
服务端加密存 desktop_device 表 → Agent 工具执行时按 account_id 动态解析
出该账号默认设备的 bridge 地址与 token，替代静态 DESKTOP_BRIDGE_* 配置。
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from injector import inject

from internal.exception import NotFoundException, ValidateErrorException
from internal.model import DesktopDevice
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .tool_credential_encryptor import _decrypt_value, _encrypt_value

logger = logging.getLogger(__name__)

# 设备租约阈值：`last_seen_at` 超过该秒数即视为离线，不再参与 bridge 解析。
# 约束：必须显著大于桌面端心跳间隔（客户端 main.js 为 60s），以容忍网络抖动
# 与短时休眠；当前取 3 个心跳周期。判定为**读时计算**（见 _effective_status），
# 不写库、不依赖后台任务，避免心跳中断时的写放大。
DEVICE_ONLINE_TTL_SECONDS = 180


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
            # 心跳复用本接口（桌面端定时重新注册刷新 last_seen_at），故更新路径降为
            # debug 避免刷屏；首次注册仍保留 info，保证「设备上线」可观测。
            logger.debug("桌面设备心跳/更新 account=%s device=%s", account_id, device_id)

        return self._to_dict(existing if existing is not None else device)

    def resolve_bridge(self, account_id: UUID) -> tuple[str, str] | None:
        """解析该账号可用的 bridge (origin, token)；无可用设备返回 None。

        优先级：默认设备 > 最近活跃设备。要求 status=online **且心跳在租约内**
        （last_seen_at 距现在不超过 DEVICE_ONLINE_TTL_SECONDS）。设备关机或休眠后
        心跳中断，超过租约即不再返回，避免任务被派给已离线的设备。
        """
        lease_threshold = _utcnow_naive() - timedelta(seconds=DEVICE_ONLINE_TTL_SECONDS)
        device = (
            self.db.session.query(DesktopDevice)
            .filter(
                DesktopDevice.account_id == account_id,
                DesktopDevice.status == "online",
                DesktopDevice.last_seen_at >= lease_threshold,
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

    def resolve_bridge_for(self, account_id: UUID, device_id: str) -> tuple[str, str] | None:
        """解析**指定设备**的 bridge (origin, token)；不存在/非本人/离线返回 None。

        与 resolve_bridge 使用同一可用性判据（status=online 且心跳在租约内），
        保证「设备列表显示在线」与「指定设备能否执行」两处口径一致。
        """
        device_id = str(device_id or "").strip()
        if not device_id:
            return None
        lease_threshold = _utcnow_naive() - timedelta(seconds=DEVICE_ONLINE_TTL_SECONDS)
        device = (
            self.db.session.query(DesktopDevice)
            .filter(
                DesktopDevice.account_id == account_id,
                DesktopDevice.device_id == device_id,
                DesktopDevice.status == "online",
                DesktopDevice.last_seen_at >= lease_threshold,
            )
            .one_or_none()
        )
        if device is None:
            return None
        if not device.bridge_origin or not device.bridge_token_encrypted:
            return None
        try:
            token = _decrypt_value(device.bridge_token_encrypted)
        except ValueError:
            logger.warning("指定设备 token 解密失败 device=%s", device_id)
            return None
        return str(device.bridge_origin).rstrip("/"), token

    def device_bindable(self, account_id: UUID, device_id: str) -> bool:
        """会话绑定前校验：设备属于该账号且未被解绑（**是否在线不阻断绑定**）。

        离线设备允许绑定：执行时由 resolver 返回「指定设备离线」的明确错误，
        用户无需因设备临时离线而重新选择。
        """
        device_id = str(device_id or "").strip()
        if not device_id:
            return False
        device = (
            self.db.session.query(DesktopDevice)
            .filter(
                DesktopDevice.account_id == account_id,
                DesktopDevice.device_id == device_id,
            )
            .one_or_none()
        )
        return bool(device is not None and device.status != "revoked")

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

    def update_device(
        self,
        account_id: UUID,
        device_id: str,
        *,
        name: str | None = None,
        is_default: bool | None = None,
    ) -> dict:
        """更新设备展示名 / 默认标记（设备管理动作，仅限本人设备）。

        - name：去除首尾空白后写入；超长拒绝；空串表示清空展示名。
        - is_default=True：同账号其他设备一并置为非默认（互斥）；已解绑设备不允许设默认。
        - 两个字段都为 None 时拒绝，避免静默 no-op。
        """
        device_id = str(device_id or "").strip()
        if not device_id:
            raise ValidateErrorException("device_id 不能为空")
        if name is None and is_default is None:
            raise ValidateErrorException("缺少需要更新的字段（name / is_default）")

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

        updates: dict = {}
        if name is not None:
            normalized = str(name).strip()
            if len(normalized) > 128:
                raise ValidateErrorException("设备名称过长（最多 128 字符）")
            updates["name"] = normalized
        if is_default is not None:
            if is_default and device.status == "revoked":
                raise ValidateErrorException("已解绑的设备不能设为默认")
            updates["is_default"] = bool(is_default)

        if is_default:
            others = (
                self.db.session.query(DesktopDevice)
                .filter(
                    DesktopDevice.account_id == account_id,
                    DesktopDevice.device_id != device_id,
                    DesktopDevice.is_default.is_(True),
                )
                .all()
            )
            for other in others:
                self.update(other, is_default=False)

        self.update(device, **updates)
        return self._to_dict(device)

    @staticmethod
    def _effective_status(device: DesktopDevice) -> str:
        """读时计算的展示态：revoked/offline 原样返回；online 但心跳超租约则显示 offline。

        不写库：避免心跳中断时反复 UPDATE；同时保证展示态与 resolve_bridge 的可用性
        判定一致——否则界面显示「在线」、本机操作却解析不到设备。
        """
        if device.status != "online":
            return device.status
        last_seen = device.last_seen_at
        if last_seen is None:
            return "offline"
        if (_utcnow_naive() - last_seen).total_seconds() > DEVICE_ONLINE_TTL_SECONDS:
            return "offline"
        return "online"

    @staticmethod
    def _to_dict(device: DesktopDevice) -> dict:
        return {
            "device_id": device.device_id,
            "name": device.name,
            "platform": device.platform,
            "bridge_origin": device.bridge_origin,
            "is_default": bool(device.is_default),
            "status": DesktopDeviceService._effective_status(device),
            "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        }
