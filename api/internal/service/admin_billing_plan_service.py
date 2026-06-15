import math
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from internal.exception import NotFoundException
from internal.extension.database_extension import db
from internal.model.billing import Plan, PlanEntitlement
from internal.service.audit_log_service import AuditLogService


class AdminBillingPlanService:
    def __init__(self, session=None, audit_log_service=None):
        self.session = session or db.session
        self.audit_log_service = audit_log_service or AuditLogService(session=self.session)

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    def list_plans(self, *, keyword: str = "", status: str = "", current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = self.session.query(Plan)
        keyword = (keyword or "").strip()
        if keyword:
            like_value = f"%{keyword}%"
            query = query.filter((Plan.code.ilike(like_value)) | (Plan.name.ilike(like_value)))
        if status:
            query = query.filter(Plan.status == status)
        total = query.count()
        plans = query.order_by(Plan.sort_order.asc(), Plan.created_at.desc()).offset((current_page - 1) * page_size).limit(page_size).all()
        return {
            "list": [self._serialize_plan(plan) for plan in plans],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def get_plan(self, plan_id: UUID) -> dict:
        plan = self._get_plan_or_raise(plan_id)
        result = self._serialize_plan(plan)
        result["entitlements"] = [self._serialize_entitlement(entitlement) for entitlement in self._list_entitlements(plan.id)]
        return result

    def create_plan(self, payload: dict, *, operator_id=None, ip: str = "", user_agent: str = "") -> dict:
        plan = Plan(
            code=payload["code"],
            name=payload["name"],
            description=payload.get("description") or "",
            duration_days=int(payload.get("duration_days") or 0),
            grant_token_credits=int(payload.get("grant_token_credits") or 0),
            price=Decimal(str(payload.get("price") or "0.00")),
            status=payload.get("status") or "active",
            sort_order=int(payload.get("sort_order") or 0),
        )
        self.session.add(plan)
        self.session.flush()
        self._replace_entitlements(plan.id, payload.get("entitlements") or [])
        self._emit_audit(
            operator_id=operator_id,
            action="create",
            resource_id=str(plan.id),
            ip=ip,
            user_agent=user_agent,
            before_data=None,
            after_data={"code": plan.code, "name": plan.name, "status": plan.status},
        )
        self.session.commit()
        return self._serialize_plan(plan)

    def update_plan(self, plan_id: UUID, payload: dict, *, operator_id=None, ip: str = "", user_agent: str = "") -> dict:
        plan = self._get_plan_or_raise(plan_id)
        before_data = self._serialize_plan(plan)
        plan.name = payload.get("name", plan.name)
        plan.description = payload.get("description", plan.description) or ""
        plan.duration_days = int(payload.get("duration_days", plan.duration_days) or 0)
        plan.grant_token_credits = int(payload.get("grant_token_credits", plan.grant_token_credits) or 0)
        plan.price = Decimal(str(payload.get("price", plan.price) or "0.00"))
        plan.status = payload.get("status", plan.status)
        plan.sort_order = int(payload.get("sort_order", plan.sort_order) or 0)
        plan.updated_at = self._now()
        if "entitlements" in payload:
            self._delete_entitlements(plan.id)
            self._replace_entitlements(plan.id, payload.get("entitlements") or [])
        self._emit_audit(
            operator_id=operator_id,
            action="update",
            resource_id=str(plan.id),
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data=self._serialize_plan(plan),
        )
        self.session.commit()
        return self._serialize_plan(plan)

    def set_plan_status(self, plan_id: UUID, status: str, *, operator_id=None, ip: str = "", user_agent: str = "") -> dict:
        plan = self._get_plan_or_raise(plan_id)
        before_status = plan.status
        plan.status = status
        plan.updated_at = self._now()
        self._emit_audit(
            operator_id=operator_id,
            action="set_status",
            resource_id=str(plan.id),
            ip=ip,
            user_agent=user_agent,
            before_data={"status": before_status},
            after_data={"status": status},
        )
        self.session.commit()
        return self._serialize_plan(plan)

    def _get_plan_or_raise(self, plan_id: UUID) -> Plan:
        plan = self.session.query(Plan).filter(Plan.id == plan_id).one_or_none()
        if plan is None:
            raise NotFoundException("套餐不存在")
        return plan

    def _list_entitlements(self, plan_id: UUID) -> list[PlanEntitlement]:
        return self.session.query(PlanEntitlement).filter(PlanEntitlement.plan_id == plan_id).order_by(PlanEntitlement.feature_key.asc()).all()

    def _delete_entitlements(self, plan_id: UUID) -> None:
        self.session.query(PlanEntitlement).filter(PlanEntitlement.plan_id == plan_id).delete()

    def _replace_entitlements(self, plan_id: UUID, entitlements: list[dict]) -> None:
        for entitlement in entitlements:
            self.session.add(PlanEntitlement(
                plan_id=plan_id,
                feature_key=entitlement["feature_key"],
                feature_value=str(entitlement.get("feature_value") or ""),
                value_type=entitlement.get("value_type") or "string",
            ))

    def _emit_audit(self, *, operator_id, action: str, resource_id: str, ip: str, user_agent: str, before_data: dict | None, after_data: dict | None) -> None:
        if not operator_id:
            return
        self.audit_log_service.record_for_write(
            admin_user_id=operator_id,
            action=action,
            resource_type="plan",
            resource_id=resource_id,
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data=after_data,
        )

    def _serialize_plan(self, plan: Plan) -> dict:
        return {
            "id": str(plan.id),
            "code": plan.code,
            "name": plan.name,
            "description": plan.description or "",
            "duration_days": int(plan.duration_days or 0),
            "grant_token_credits": int(plan.grant_token_credits or 0),
            "price": f"{Decimal(str(plan.price or 0)):.2f}",
            "status": plan.status,
            "sort_order": int(plan.sort_order or 0),
            "created_at": self._timestamp(plan.created_at),
            "updated_at": self._timestamp(plan.updated_at),
        }

    def _serialize_entitlement(self, entitlement: PlanEntitlement) -> dict:
        return {
            "id": str(entitlement.id),
            "feature_key": entitlement.feature_key,
            "feature_value": entitlement.feature_value,
            "value_type": entitlement.value_type,
            "parsed_value": entitlement.parsed_value,
        }
