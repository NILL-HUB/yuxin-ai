"""认证通道配置模型。

Admin 端运行时切换认证通道（邮箱 / 手机号）配置的基础：``mail_config`` 与
``sms_config`` 表记录各通道的配置项（发件箱 / 网关等），均为单行记录（id=1）。
"""
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, text
from sqlalchemy.dialects.postgresql import JSONB

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class MailConfig(Base):
    """邮箱认证通道配置：单行记录，configs 存发件箱等配置项。"""
    __tablename__ = "mail_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 通道配置项（JSON）：SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/SENDER 等
    configs = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )


class SmsConfig(Base):
    """手机号认证通道配置：单行记录，configs 存短信网关等配置项。"""
    __tablename__ = "sms_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 通道配置项（JSON）：SMS_PROVIDER/SMS_ACCESS_KEY/SMS_SIGN 等
    configs = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
