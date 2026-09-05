import math
import re
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from internal.exception import FailException, NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import escape_like_pattern
from internal.model.billing import Membership, Plan, PlanEntitlement
from internal.model.distribution import AutoRenewal, PurchaseOrder
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

    @staticmethod
    def _fix_mojibake_text(text) -> str:
        """尽力还原被错误多重编码的 UTF-8 中文（如 "Ã¥Â..." / "æœˆå…¡" → 正常中文）。

        仅当文本含 mojibake 特征字符（Ã/Â/æ/å/ç 等 Latin-1 可映射字节）时尝试还原；
        无法还原或产生替换符时原样返回，避免损坏正常内容。
        """
        if not isinstance(text, str) or not text:
            return text or ""
        if not re.search(r"[ÃÂæåçöØÿ]", text):
            return text
        candidate = text
        for _ in range(4):
            try:
                restored = candidate.encode("latin-1", errors="strict").decode("utf-8", errors="strict")
            except (UnicodeDecodeError, UnicodeEncodeError):
                break
            if restored == candidate:
                break
            candidate = restored
        if "\ufffd" in candidate or re.search(r"[ÃÂæåçöØÿ]", candidate):
            return text
        return candidate

    def list_plans(self, *, keyword: str = "", status: str = "", current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = self.session.query(Plan)
        query = query.filter(Plan.deleted_at.is_(None))
        keyword = (keyword or "").strip()
        if keyword:
            like_value = f"%{escape_like_pattern(keyword)}%"
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
        payload = dict(payload)
        payload["name"] = self._fix_mojibake_text(payload.get("name") or "")
        if payload.get("description"):
            payload["description"] = self._fix_mojibake_text(payload["description"])
        plan = Plan(
            code=payload["code"],
            name=payload["name"],
            description=payload.get("description") or "",
            plan_type=payload.get("plan_type") or "membership",
            duration_days=int(payload.get("duration_days") or 0),
            grant_token_credits=int(payload.get("grant_token_credits") or 0),
            auto_renew_threshold_percent=int(payload.get("auto_renew_threshold_percent") or 5),
            auto_renew_threshold_days=int(payload.get("auto_renew_threshold_days") or 1),
            purchase_limit=int(payload.get("purchase_limit") or 0),
            purchase_limit_period=(payload.get("purchase_limit_period") or "none").strip().lower(),
            quota_refresh_period=(payload.get("quota_refresh_period") or "none").strip().lower(),
            auto_renew_default=bool(payload.get("auto_renew_default") or False),
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
        payload = dict(payload)
        if payload.get("name"):
            payload["name"] = self._fix_mojibake_text(payload["name"])
        if payload.get("description"):
            payload["description"] = self._fix_mojibake_text(payload["description"])
        before_data = self._serialize_plan(plan)
        plan.name = payload.get("name", plan.name)
        plan.description = payload.get("description", plan.description) or ""
        plan.plan_type = payload.get("plan_type", plan.plan_type) or "membership"
        plan.duration_days = int(payload.get("duration_days", plan.duration_days) or 0)
        plan.grant_token_credits = int(payload.get("grant_token_credits", plan.grant_token_credits) or 0)
        plan.auto_renew_threshold_percent = int(payload.get("auto_renew_threshold_percent", plan.auto_renew_threshold_percent) or 5)
        plan.auto_renew_threshold_days = int(payload.get("auto_renew_threshold_days", plan.auto_renew_threshold_days) or 1)
        plan.purchase_limit = int(payload.get("purchase_limit", plan.purchase_limit) or 0)
        plan.purchase_limit_period = (payload.get("purchase_limit_period", plan.purchase_limit_period) or "none").strip().lower()
        plan.quota_refresh_period = (payload.get("quota_refresh_period", plan.quota_refresh_period) or "none").strip().lower()
        if "auto_renew_default" in payload:
            plan.auto_renew_default = bool(payload.get("auto_renew_default"))
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

    def delete_plan(self, plan_id: UUID, *, operator_id=None, ip: str = "", user_agent: str = "") -> dict:
        """软删除套餐。已有付费订单 / 进行中自动续费 / 生效中会员时禁止删除，提示改用下架。"""
        plan = self._get_plan_or_raise(plan_id)
        paid_orders = self.session.query(PurchaseOrder).filter(
            PurchaseOrder.plan_id == plan_id,
            PurchaseOrder.status == "paid",
        ).count()
        active_renewals = self.session.query(AutoRenewal).filter(
            AutoRenewal.plan_id == plan_id,
            AutoRenewal.status == "active",
        ).count()
        active_memberships = self.session.query(Membership).filter(
            Membership.plan_id == plan_id,
            Membership.status == "active",
            Membership.expires_at >= self._now(),
        ).count()
        if paid_orders or active_renewals or active_memberships:
            raise FailException("该套餐已有付费订单/自动续费/生效中的会员，不能删除，请改为下架")
        before_data = self._serialize_plan(plan)
        plan.deleted_at = self._now()
        plan.status = "archived"
        plan.updated_at = self._now()
        self._emit_audit(
            operator_id=operator_id,
            action="delete",
            resource_id=str(plan.id),
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data={"code": plan.code, "name": plan.name, "deleted_at": self._timestamp(plan.deleted_at)},
        )
        self.session.commit()
        return self._serialize_plan(plan)

    def _get_plan_or_raise(self, plan_id: UUID) -> Plan:
        plan = self.session.query(Plan).filter(Plan.id == plan_id, Plan.deleted_at.is_(None)).one_or_none()
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
            "plan_type": plan.plan_type or "membership",
            "duration_days": int(plan.duration_days or 0),
            "grant_token_credits": int(plan.grant_token_credits or 0),
            "auto_renew_threshold_percent": int(plan.auto_renew_threshold_percent or 5),
            "auto_renew_threshold_days": int(plan.auto_renew_threshold_days or 1),
            "purchase_limit": int(plan.purchase_limit or 0),
            "purchase_limit_period": (plan.purchase_limit_period or "none").strip().lower(),
            "quota_refresh_period": (plan.quota_refresh_period or "none").strip().lower(),
            "auto_renew_default": bool(plan.auto_renew_default),
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
