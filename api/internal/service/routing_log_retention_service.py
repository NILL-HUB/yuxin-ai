from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.model import OrchestrationFeatureFlagModel
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


ROUTING_LOG_RETENTION_FLAG_CODE = "ROUTING_LOG_RETENTION_DAYS"
DEFAULT_ROUTING_LOG_RETENTION_DAYS = 30
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650


@inject
@dataclass
class RoutingLogRetentionService(BaseService):
    db: SQLAlchemy

    def get_retention_days(self) -> int:
        flag = self._find_flag()
        if flag is None:
            return DEFAULT_ROUTING_LOG_RETENTION_DAYS
        days = self._parse_days(flag.fallback_behavior)
        return days if days is not None else DEFAULT_ROUTING_LOG_RETENTION_DAYS

    def set_retention_days(self, days: int, admin_user_id: UUID) -> int:
        normalized = self._normalize_days(days)
        with self.db.auto_commit():
            flag = self._find_flag()
            if flag is None:
                flag = OrchestrationFeatureFlagModel(
                    code=ROUTING_LOG_RETENTION_FLAG_CODE,
                    name="Routing log retention days",
                    description="Configurable retention window (days) for routing logs",
                    enabled=True,
                    risk_level="low",
                    fallback_behavior=str(normalized),
                    updated_by=admin_user_id,
                )
                self.db.session.add(flag)
            else:
                flag.fallback_behavior = str(normalized)
                flag.enabled = True
                flag.updated_by = admin_user_id
        return normalized

    def describe(self) -> dict:
        return {
            "retention_days": self.get_retention_days(),
            "default_retention_days": DEFAULT_ROUTING_LOG_RETENTION_DAYS,
            "min_retention_days": MIN_RETENTION_DAYS,
            "max_retention_days": MAX_RETENTION_DAYS,
            "code": ROUTING_LOG_RETENTION_FLAG_CODE,
        }

    def _find_flag(self):
        return (
            self.db.session.query(OrchestrationFeatureFlagModel)
            .filter(OrchestrationFeatureFlagModel.code == ROUTING_LOG_RETENTION_FLAG_CODE)
            .first()
        )

    @staticmethod
    def _parse_days(value) -> int | None:
        if value is None:
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_days(days) -> int:
        try:
            normalized = int(days)
        except (TypeError, ValueError):
            raise ValueError("retention_days 必须是整数")
        if normalized < MIN_RETENTION_DAYS or normalized > MAX_RETENTION_DAYS:
            raise ValueError(
                f"retention_days 必须在 {MIN_RETENTION_DAYS}-{MAX_RETENTION_DAYS} 之间"
            )
        return normalized
