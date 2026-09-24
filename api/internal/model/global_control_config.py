"""全局控制配置模型。

``global_control_config`` 表以单行 JSONB（id=1）集中承载系统级全局行为配置，
按 section 分组存放：模型运行时降级（runtime_fallback）、外部素材获取（media_fetch）、
会话级 Checkpoint（agent_checkpoint）、技能目录同步（skill_catalog_sync）、
图像请求策略（image_request_policy）、视觉兜底模型（vision_fallback）。

与 mail_config / sms_config / desktop_client_config 同款单行模式。
"""
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Integer, text
from sqlalchemy.dialects.postgresql import JSONB

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class GlobalControlConfig(Base):
    """全局控制配置：单行记录，configs 按 section 分组存放各项全局行为配置。"""
    __tablename__ = "global_control_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 配置项（JSON）：按 section 分组，形如
    # {"runtime_fallback": {"enabled": true, "retry_attempts": 5}, ...}
    configs = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
