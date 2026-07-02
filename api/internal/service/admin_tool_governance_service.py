import math
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func

from internal.exception import NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import escape_like_pattern
from internal.model.tool_governance_entity import ToolGovernancePolicy, ToolInvocationAudit


RISK_LEVELS = ["low", "medium", "high", "critical"]
SOURCE_TYPES = ["api_tool", "mcp", "skill", "builtin"]
VISIBILITIES = ["private", "tenant", "public"]
INVOCATION_STATUSES = ["success", "failed", "blocked", "timeout"]


class AdminToolGovernanceService:
    def __init__(self, session=None):
        self.session = session or db.session

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _parse_bool(value) -> bool | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def list_policies(
        self,
        *,
        current_page: int = 1,
        page_size: int = 20,
        source_type: str = "",
        risk_level: str = "",
        visibility: str = "",
        enabled=None,
        keyword: str = "",
    ) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 100), 1)
        query = self.session.query(ToolGovernancePolicy)
        if source_type:
            query = query.filter(ToolGovernancePolicy.source_type == source_type)
        if risk_level:
            query = query.filter(ToolGovernancePolicy.risk_level == risk_level)
        if visibility:
            query = query.filter(ToolGovernancePolicy.visibility == visibility)
        enabled_value = self._parse_bool(enabled)
        if enabled_value is not None:
            query = query.filter(ToolGovernancePolicy.enabled.is_(enabled_value))
        keyword = (keyword or "").strip()
        if keyword:
            like_value = f"%{escape_like_pattern(keyword)}%"
            query = query.filter(
                (ToolGovernancePolicy.tool_name.ilike(like_value))
                | (ToolGovernancePolicy.tool_id.ilike(like_value))
            )
        total = query.count()
        policies = (
            query.order_by(ToolGovernancePolicy.created_at.desc())
            .offset((current_page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "list": [self._serialize_policy(policy) for policy in policies],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_policy(self, policy_id: UUID) -> dict:
        return self._serialize_policy(self._get_policy_or_raise(policy_id))

    def create_policy(self, payload: dict) -> dict:
        policy = ToolGovernancePolicy(
            tool_id=payload["tool_id"],
            tool_name=payload.get("tool_name") or payload["tool_id"],
            source_type=payload.get("source_type") or "builtin",
            provider_id=payload.get("provider_id"),
            risk_level=payload.get("risk_level") or "low",
            visibility=payload.get("visibility") or "private",
            allowed_pools=payload.get("allowed_pools") or [],
            enabled=self._parse_bool(payload.get("enabled")) if payload.get("enabled") is not None else True,
            max_invocations_per_request=int(payload.get("max_invocations_per_request") or 5),
            cooldown_seconds=int(payload.get("cooldown_seconds") or 0),
            require_confirmation=bool(payload.get("require_confirmation")),
            description=payload.get("description"),
        )
        self.session.add(policy)
        self.session.commit()
        return self._serialize_policy(policy)

    def update_policy(self, policy_id: UUID, payload: dict) -> dict:
        policy = self._get_policy_or_raise(policy_id)
        if "tool_id" in payload:
            policy.tool_id = payload["tool_id"]
        if "tool_name" in payload:
            policy.tool_name = payload["tool_name"] or policy.tool_id
        if "source_type" in payload:
            policy.source_type = payload["source_type"]
        if "provider_id" in payload:
            policy.provider_id = payload["provider_id"]
        if "risk_level" in payload:
            policy.risk_level = payload["risk_level"]
        if "visibility" in payload:
            policy.visibility = payload["visibility"]
        if "allowed_pools" in payload:
            policy.allowed_pools = payload["allowed_pools"] or []
        if "enabled" in payload:
            policy.enabled = self._parse_bool(payload.get("enabled"))
        if "max_invocations_per_request" in payload:
            policy.max_invocations_per_request = int(payload.get("max_invocations_per_request") or 5)
        if "cooldown_seconds" in payload:
            policy.cooldown_seconds = int(payload.get("cooldown_seconds") or 0)
        if "require_confirmation" in payload:
            policy.require_confirmation = bool(payload.get("require_confirmation"))
        if "description" in payload:
            policy.description = payload["description"]
        policy.updated_at = self._now()
        self.session.commit()
        return self._serialize_policy(policy)

    def delete_policy(self, policy_id: UUID) -> None:
        policy = self._get_policy_or_raise(policy_id)
        self.session.delete(policy)
        self.session.commit()

    def set_enabled(self, policy_id: UUID, enabled: bool) -> dict:
        policy = self._get_policy_or_raise(policy_id)
        policy.enabled = bool(enabled)
        policy.updated_at = self._now()
        self.session.commit()
        return self._serialize_policy(policy)

    def batch_update_risk(self, policy_ids: list[UUID], risk_level: str) -> dict:
        if not policy_ids:
            return {"updated": 0, "risk_level": risk_level}
        updated = (
            self.session.query(ToolGovernancePolicy)
            .filter(ToolGovernancePolicy.id.in_(policy_ids))
            .update(
                {ToolGovernancePolicy.risk_level: risk_level, ToolGovernancePolicy.updated_at: self._now()},
                synchronize_session=False,
            )
        )
        self.session.commit()
        return {"updated": int(updated), "risk_level": risk_level}

    def list_audit_logs(
        self,
        *,
        current_page: int = 1,
        page_size: int = 20,
        tool_id: str = "",
        status: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 100), 1)
        query = self.session.query(ToolInvocationAudit)
        if tool_id:
            query = query.filter(ToolInvocationAudit.tool_id == tool_id)
        if status:
            query = query.filter(ToolInvocationAudit.invocation_status == status)
        if start_date:
            query = query.filter(ToolInvocationAudit.created_at >= self._parse_date(start_date))
        if end_date:
            query = query.filter(ToolInvocationAudit.created_at <= self._parse_date(end_date, end_of_day=True))
        total = query.count()
        logs = (
            query.order_by(ToolInvocationAudit.created_at.desc())
            .offset((current_page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "list": [self._serialize_audit(log) for log in logs],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_governance_stats(self) -> dict:
        total = self.session.query(func.count(ToolGovernancePolicy.id)).scalar() or 0
        enabled_total = (
            self.session.query(func.count(ToolGovernancePolicy.id))
            .filter(ToolGovernancePolicy.enabled.is_(True))
            .scalar()
            or 0
        )
        risk_rows = (
            self.session.query(ToolGovernancePolicy.risk_level, func.count(ToolGovernancePolicy.id))
            .group_by(ToolGovernancePolicy.risk_level)
            .all()
        )
        source_rows = (
            self.session.query(ToolGovernancePolicy.source_type, func.count(ToolGovernancePolicy.id))
            .group_by(ToolGovernancePolicy.source_type)
            .all()
        )
        visibility_rows = (
            self.session.query(ToolGovernancePolicy.visibility, func.count(ToolGovernancePolicy.id))
            .group_by(ToolGovernancePolicy.visibility)
            .all()
        )
        risk_distribution = {level: 0 for level in RISK_LEVELS}
        for level, count in risk_rows:
            risk_distribution[level] = int(count)
        source_distribution = {source: 0 for source in SOURCE_TYPES}
        for source, count in source_rows:
            source_distribution[source] = int(count)
        visibility_distribution = {item: 0 for item in VISIBILITIES}
        for visibility, count in visibility_rows:
            visibility_distribution[visibility] = int(count)
        return {
            "total": int(total),
            "enabled": int(enabled_total),
            "disabled": int(total) - int(enabled_total),
            "enabled_rate": round(int(enabled_total) / int(total), 4) if total else 0.0,
            "risk_distribution": risk_distribution,
            "source_distribution": source_distribution,
            "visibility_distribution": visibility_distribution,
        }

    def _get_policy_or_raise(self, policy_id: UUID) -> ToolGovernancePolicy:
        policy = (
            self.session.query(ToolGovernancePolicy)
            .filter(ToolGovernancePolicy.id == policy_id)
            .one_or_none()
        )
        if policy is None:
            raise NotFoundException("工具治理策略不存在")
        return policy

    @staticmethod
    def _parse_date(value: str, end_of_day: bool = False):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            try:
                parsed = datetime.strptime(str(value), "%Y-%m-%d")
            except ValueError:
                return None
        parsed = parsed.replace(tzinfo=None)
        if end_of_day:
            parsed = parsed.replace(hour=23, minute=59, second=59)
        return parsed

    def _serialize_policy(self, policy: ToolGovernancePolicy) -> dict:
        return {
            "id": str(policy.id),
            "tool_id": policy.tool_id,
            "tool_name": policy.tool_name or "",
            "source_type": policy.source_type,
            "provider_id": policy.provider_id or "",
            "risk_level": policy.risk_level,
            "visibility": policy.visibility,
            "allowed_pools": list(policy.allowed_pools or []),
            "enabled": bool(policy.enabled),
            "max_invocations_per_request": int(policy.max_invocations_per_request or 0),
            "cooldown_seconds": int(policy.cooldown_seconds or 0),
            "require_confirmation": bool(policy.require_confirmation),
            "description": policy.description or "",
            "created_at": self._timestamp(policy.created_at),
            "updated_at": self._timestamp(policy.updated_at),
        }

    def _serialize_audit(self, log: ToolInvocationAudit) -> dict:
        return {
            "id": str(log.id),
            "tool_id": log.tool_id,
            "tool_name": log.tool_name or "",
            "account_id": str(log.account_id) if log.account_id else "",
            "conversation_id": str(log.conversation_id) if log.conversation_id else "",
            "invocation_status": log.invocation_status,
            "duration_ms": int(log.duration_ms) if log.duration_ms is not None else None,
            "error_message": log.error_message or "",
            "created_at": self._timestamp(log.created_at),
        }
