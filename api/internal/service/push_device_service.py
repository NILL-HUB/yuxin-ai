"""推送令牌注册服务：App 上报的个推 cid / 友盟 device_token 的幂等管理。

按 (account_id, provider, token) 幂等 UPSERT（唯一约束兜底并发）；
unregister 置 enabled=False（保留记录便于排障），不存在时按已停用返回（幂等）。
"""
from __future__ import annotations

import logging
from uuid import UUID

from injector import inject

from internal.exception import ValidateErrorException
from internal.model.push_channel import PushDevice
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

logger = logging.getLogger(__name__)

PROVIDERS = ("getui", "umeng")
PLATFORMS = ("android", "ios")


@inject
class PushDeviceService(BaseService):
    """设备推送令牌：单账号多令牌，多通道并存（个推与友盟同时注册）。"""

    def __init__(self, db: SQLAlchemy = None):
        self.db = db

    def register(self, *, account_id: UUID, platform: str, provider: str, token: str) -> dict:
        provider = str(provider or "").strip().lower()
        platform = str(platform or "").strip().lower()
        token = str(token or "").strip()
        if provider not in PROVIDERS:
            raise ValidateErrorException("provider 只能是 getui / umeng")
        if platform and platform not in PLATFORMS:
            raise ValidateErrorException("platform 只能是 android / ios（可留空）")
        if not token:
            raise ValidateErrorException("token 不能为空")
        if len(token) > 512:
            raise ValidateErrorException("token 过长（最多 512 字符）")

        existing = (
            self.db.session.query(PushDevice)
            .filter(
                PushDevice.account_id == account_id,
                PushDevice.provider == provider,
                PushDevice.token == token,
            )
            .one_or_none()
        )
        if existing is None:
            device = PushDevice(
                account_id=account_id,
                platform=platform,
                provider=provider,
                token=token,
                enabled=True,
            )
            self.db.session.add(device)
            self.db.session.commit()
            logger.info("推送令牌注册 account=%s provider=%s", account_id, provider)
            return self._to_dict(device)

        self.update(existing, enabled=True, platform=platform or existing.platform)
        return self._to_dict(existing)

    def unregister(self, *, account_id: UUID, provider: str, token: str) -> dict:
        provider = str(provider or "").strip().lower()
        token = str(token or "").strip()
        if provider not in PROVIDERS:
            raise ValidateErrorException("provider 只能是 getui / umeng")
        if not token:
            raise ValidateErrorException("token 不能为空")

        existing = (
            self.db.session.query(PushDevice)
            .filter(
                PushDevice.account_id == account_id,
                PushDevice.provider == provider,
                PushDevice.token == token,
            )
            .one_or_none()
        )
        if existing is None:
            return {"unregistered": True, "found": False}
        self.update(existing, enabled=False)
        logger.info("推送令牌停用 account=%s provider=%s", account_id, provider)
        return {"unregistered": True, "found": True}

    @staticmethod
    def _to_dict(device: PushDevice) -> dict:
        return {
            "provider": device.provider,
            "platform": device.platform,
            "token": device.token,
            "enabled": bool(device.enabled),
        }
