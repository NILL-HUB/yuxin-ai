"""系统推送通道模型：推送配置（单行 JSONB）与设备推送令牌注册表。

- PushConfig：admin 配置个推（主）/友盟（辅）凭证与开关，单行记录（id=1），
  照 mail_config / sms_config / desktop_client_config 同款模式；密钥字段落库前
  由 PushConfigService 加密（Fernet，复用工具凭证密钥）。
- PushDevice：App 侧上报的推送令牌（个推 cid / 友盟 device_token），
  按 (account_id, provider, token) 幂等；enabled 控制是否参与发送。
"""
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class PushConfig(Base):
    """系统推送配置：单行记录（id=1），configs 存两家凭证与主备开关。"""
    __tablename__ = "push_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 配置项（JSON）：
    # {enabled, primary_provider: "getui"|"umeng", fallback_enabled,
    #  getui: {app_id, app_key, app_secret, master_secret},
    #  umeng: {app_key, app_master_secret, production_mode}}
    # 其中 *secret* 字段为 Fernet 密文（非明文）
    configs = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )


class PushDevice(Base):
    """设备推送令牌：App 上报（个推 cid / 友盟 device_token），按账号维度管理。"""
    __tablename__ = "push_device"

    id = Column(UUID, primary_key=True, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    # 设备平台：android / ios
    platform = Column(String(16), nullable=False, server_default=text("''::character varying"))
    # 推送服务商：getui / umeng
    provider = Column(String(16), nullable=False)
    # 提供商侧令牌：个推 cid / 友盟 device_token（单一事实源，不做跨 provider 复用）
    token = Column(String(512), nullable=False)
    enabled = Column(Boolean, nullable=False, server_default=text("true"), default=True)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )

    __table_args__ = (
        Index("push_device_account_idx", "account_id"),
        UniqueConstraint("account_id", "provider", "token", name="uq_push_device_account_provider_token"),
    )
