from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.entity.orchestration_feature_flag_entity import (
    get_default_orchestration_feature_flags,
)
from internal.model import OrchestrationFeatureFlagModel
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


@inject
@dataclass
class OrchestrationFeatureFlagService(BaseService):
    db: SQLAlchemy

    def ensure_defaults(self) -> list[dict]:
        result = []
        for flag in get_default_orchestration_feature_flags():
            existing = self._find_by_code(flag.code)
            if existing is None:
                existing = self.create(
                    OrchestrationFeatureFlagModel,
                    **flag.to_dict(),
                )
            result.append(self._serialize(existing))
        return result

    def list_flags(self) -> list[dict]:
        flags = (
            self.db.session.query(OrchestrationFeatureFlagModel)
            .order_by(OrchestrationFeatureFlagModel.code.asc())
            .all()
        )
        if not flags:
            return self.ensure_defaults()
        return [self._serialize(flag) for flag in flags]

    def is_enabled(self, code: str) -> bool:
        """查询开关是否启用。

        flag 不在已知列表中返回 False；在表中找不到记录时从
        get_default_orchestration_feature_flags() 查找代码默认值，
        避免数据库为空时所有开关返回 False 导致系统崩溃。
        """
        defaults = get_default_orchestration_feature_flags()
        known_codes = {flag.code for flag in defaults}
        if code not in known_codes:
            return False
        flag = self._find_by_code(code)
        if flag is None:
            # 数据库无记录时降级到代码默认值（而非统一返回 False）
            for default_flag in defaults:
                if default_flag.code == code:
                    return default_flag.enabled
            return False
        return bool(flag.enabled)

    def update_flag(self, *, code: str, enabled: bool, operator_id: UUID) -> dict:
        flag = self._find_by_code(code)
        if flag is None:
            raise ValueError(f"Unknown orchestration feature flag: {code}")
        with self.db.auto_commit():
            flag.enabled = bool(enabled)
            flag.updated_by = operator_id
        return self._serialize(flag)

    def _find_by_code(self, code: str):
        return (
            self.db.session.query(OrchestrationFeatureFlagModel)
            .filter(OrchestrationFeatureFlagModel.code == code)
            .first()
        )

    @staticmethod
    def _serialize(flag) -> dict:
        return {
            "code": flag.code,
            "name": flag.name,
            "description": flag.description,
            "enabled": bool(flag.enabled),
            "risk_level": flag.risk_level,
            "fallback_behavior": flag.fallback_behavior,
            "updated_by": str(flag.updated_by)
            if getattr(flag, "updated_by", None)
            else None,
        }
