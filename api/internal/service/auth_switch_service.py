"""认证业务开关读取与联动校验。复用 orchestration_feature_flag 表。"""
from __future__ import annotations

from internal.extension.database_extension import db
from internal.model.orchestration_feature_flag import OrchestrationFeatureFlagModel

AUTH_CODES = ("AUTH_EMAIL_ENABLED", "AUTH_PHONE_ENABLED", "AUTH_LOGIN_CHALLENGE_ENABLED")
DEFAULTS = {"AUTH_EMAIL_ENABLED": True, "AUTH_PHONE_ENABLED": False, "AUTH_LOGIN_CHALLENGE_ENABLED": True}


def _flag_enabled(session, code: str, default: bool) -> bool:
    try:
        row = session.query(OrchestrationFeatureFlagModel).filter(
            OrchestrationFeatureFlagModel.code == code
        ).one_or_none()
        if row is not None:
            return bool(row.enabled)
    except Exception:
        pass
    return default


def get_auth_switches(session=None) -> dict[str, bool]:
    session = session or db.session
    return {code: _flag_enabled(session, code, DEFAULTS[code]) for code in AUTH_CODES}


def validate_auth_switch_combination(switches: dict[str, bool]) -> str | None:
    """返回错误消息；None=通过。挑战开关需至少一个通道开启。"""
    if switches.get("AUTH_LOGIN_CHALLENGE_ENABLED") and not (
        switches.get("AUTH_EMAIL_ENABLED") or switches.get("AUTH_PHONE_ENABLED")
    ):
        return "新IP验证开关需至少启用邮箱或手机号通道之一"
    return None
