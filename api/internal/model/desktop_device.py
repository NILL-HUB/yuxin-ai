"""桌面设备注册模型。

解决「服务端 → 宿主机 worker」调用断链：桌面端每次启动用随机 token 注入本机
worker，服务端**无从获知**该 token，导致 `DESKTOP_BRIDGE_*` 静态配置永远对不上。

本表让桌面端在登录后主动注册自己的 bridge 访问信息（origin + token 密文），
服务端按 `account_id` 动态解析，替代静态环境变量。
"""
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class DesktopDevice(Base):
    """桌面客户端设备注册记录。

    一个账号可注册多台设备；同一 device_id 重复注册为幂等更新（UPSERT）。
    """
    __tablename__ = "desktop_device"

    id = Column(UUID, primary_key=True, server_default=text("uuid_generate_v4()"))
    # 桌面端持久化的稳定设备标识（客户端生成，跨重启不变）
    device_id = Column(String(128), nullable=False)
    account_id = Column(UUID, nullable=False)
    # 设备展示名 / 平台（win32 / darwin / linux）
    name = Column(String(128), nullable=False, server_default=text("''::character varying"))
    platform = Column(String(32), nullable=False, server_default=text("''::character varying"))
    # 宿主机 bridge 地址：服务端容器内的可达地址（如 http://host.docker.internal:9876）
    bridge_origin = Column(String(255), nullable=False, server_default=text("''::character varying"))
    # bridge 访问令牌密文（Fernet 加密，复用工具凭证密钥）
    bridge_token_encrypted = Column(String(512), nullable=False, server_default=text("''::character varying"))
    # 是否作为该账号的默认设备（用于多设备时的解析优先级）
    is_default = Column(Boolean, nullable=False, server_default=text("true"), default=True)
    # online / offline / revoked
    status = Column(String(16), nullable=False, server_default=text("'online'::character varying"))
    last_seen_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )

    __table_args__ = (
        Index("desktop_device_account_idx", "account_id"),
        Index("desktop_device_device_id_idx", "device_id"),
    )
