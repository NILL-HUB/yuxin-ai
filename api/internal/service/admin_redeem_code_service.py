import hashlib
import math
import secrets
from datetime import UTC, datetime
from uuid import UUID

from internal.exception import FailException, NotFoundException
from internal.extension.database_extension import db
from internal.lib.helper import escape_like_pattern
from internal.model.billing import Plan, RedeemCode, RedeemCodeBatch
from internal.service.audit_log_service import AuditLogService


class AdminRedeemCodeService:
    def __init__(self, session=None, audit_log_service=None):
        self.session = session or db.session
        self.audit_log_service = audit_log_service or AuditLogService(session=self.session)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _timestamp(value) -> int | None:
        if value is None:
            return None
        return int(value.replace(tzinfo=UTC).timestamp())

    @staticmethod
    def hash_code(plain_code: str) -> str:
        return "sha256:" + hashlib.sha256(plain_code.encode("utf-8")).hexdigest()

    @staticmethod
    def mask_code(plain_code: str) -> str:
        compact = plain_code.replace("-", "")
        return f"{compact[:4]}****{compact[-4:]}"

    @staticmethod
    def generate_plain_code() -> str:
        return "OA-" + secrets.token_urlsafe(18).replace("_", "A").replace("-", "B")[:24].upper()

    def generate_codes(self, payload: dict, *, operator_id=None, ip: str = "", user_agent: str = "") -> dict:
        plan = self._get_plan_or_raise(payload["plan_id"])
        if not plan.is_active:
            raise FailException("套餐已停用，不能生成卡密")
        quantity = max(int(payload.get("quantity") or 1), 1)
        if quantity > 1000:
            raise FailException("单批最多生成 1000 张卡密")
        batch = RedeemCodeBatch(
            name=payload["name"],
            plan_id=plan.id,
            quantity=quantity,
            expires_at=payload.get("expires_at"),
            created_by=operator_id,
        )
        self.session.add(batch)
        self.session.flush()
        codes = []
        for _ in range(quantity):
            plain_code = self.generate_plain_code()
            redeem_code = RedeemCode(
                batch_id=batch.id,
                plan_id=plan.id,
                code_hash=self.hash_code(plain_code),
                code_mask=self.mask_code(plain_code),
                status="unused",
                expires_at=batch.expires_at,
            )
            self.session.add(redeem_code)
            codes.append({"plain_code": plain_code, "code_mask": redeem_code.code_mask})
        self._emit_audit(
            operator_id=operator_id,
            action="generate",
            resource_type="redeem_code_batch",
            resource_id=str(batch.id),
            ip=ip,
            user_agent=user_agent,
            before_data=None,
            after_data={"name": batch.name, "plan_id": str(plan.id), "quantity": quantity},
        )
        self.session.commit()
        return {"batch": self._serialize_batch(batch), "codes": codes}

    def list_batches(self, *, keyword: str = "", current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = self.session.query(RedeemCodeBatch)
        keyword = (keyword or "").strip()
        if keyword:
            query = query.filter(RedeemCodeBatch.name.ilike(f"%{escape_like_pattern(keyword)}%"))
        total = query.count()
        batches = query.order_by(RedeemCodeBatch.created_at.desc()).offset((current_page - 1) * page_size).limit(page_size).all()
        return {
            "list": [self._serialize_batch(batch) for batch in batches],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def list_codes(self, *, batch_id: UUID | None = None, status: str = "", code_keyword: str = "", current_page: int = 1, page_size: int = 20) -> dict:
        current_page = max(int(current_page or 1), 1)
        page_size = max(min(int(page_size or 20), 50), 1)
        query = self.session.query(RedeemCode)
        now = self._now()
        code_keyword = (code_keyword or "").strip()
        if batch_id:
            query = query.filter(RedeemCode.batch_id == batch_id)
        if code_keyword:
            query = query.filter(RedeemCode.code_mask.ilike(f"%{escape_like_pattern(code_keyword)}%"))
        if status == "expired":
            query = query.filter(RedeemCode.status == "unused", RedeemCode.expires_at < now)
        elif status:
            query = query.filter(RedeemCode.status == status)
        total = query.count()
        codes = query.order_by(RedeemCode.created_at.desc()).offset((current_page - 1) * page_size).limit(page_size).all()
        return {
            "list": [self._serialize_code(code) for code in codes],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if total else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def disable_code(self, code_id: UUID, *, operator_id=None, ip: str = "", user_agent: str = "") -> dict:
        redeem_code = self._get_code_or_raise(code_id)
        before_status = redeem_code.status
        redeem_code.status = "disabled"
        redeem_code.disabled_at = self._now()
        self._emit_audit(
            operator_id=operator_id,
            action="disable",
            resource_type="redeem_code",
            resource_id=str(redeem_code.id),
            ip=ip,
            user_agent=user_agent,
            before_data={"status": before_status},
            after_data={"status": "disabled"},
        )
        self.session.commit()
        return self._serialize_code(redeem_code)

    def disable_batch(self, batch_id: UUID, *, operator_id=None, ip: str = "", user_agent: str = "") -> dict:
        batch = self._get_batch_or_raise(batch_id)
        before_status = batch.status
        batch.status = "disabled"
        batch.disabled_at = self._now()
        self._emit_audit(
            operator_id=operator_id,
            action="disable",
            resource_type="redeem_code_batch",
            resource_id=str(batch.id),
            ip=ip,
            user_agent=user_agent,
            before_data={"status": before_status},
            after_data={"status": "disabled"},
        )
        self.session.commit()
        return self._serialize_batch(batch)

    def _get_plan_or_raise(self, plan_id: UUID) -> Plan:
        plan = self.session.query(Plan).filter(Plan.id == plan_id).one_or_none()
        if plan is None:
            raise NotFoundException("套餐不存在")
        return plan

    def _get_code_or_raise(self, code_id: UUID) -> RedeemCode:
        redeem_code = self.session.query(RedeemCode).filter(RedeemCode.id == code_id).one_or_none()
        if redeem_code is None:
            raise NotFoundException("卡密不存在")
        return redeem_code

    def _get_batch_or_raise(self, batch_id: UUID) -> RedeemCodeBatch:
        batch = self.session.query(RedeemCodeBatch).filter(RedeemCodeBatch.id == batch_id).one_or_none()
        if batch is None:
            raise NotFoundException("卡密批次不存在")
        return batch

    def _emit_audit(self, *, operator_id, action: str, resource_type: str, resource_id: str, ip: str, user_agent: str, before_data: dict | None, after_data: dict | None) -> None:
        if not operator_id:
            return
        self.audit_log_service.record_for_write(
            admin_user_id=operator_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data=after_data,
        )

    def _serialize_batch(self, batch: RedeemCodeBatch) -> dict:
        return {
            "id": str(batch.id),
            "name": batch.name,
            "plan_id": str(batch.plan_id),
            "quantity": int(batch.quantity or 0),
            "status": batch.status,
            "expires_at": self._timestamp(batch.expires_at),
            "disabled_at": self._timestamp(batch.disabled_at),
            "created_by": str(batch.created_by) if batch.created_by else None,
            "created_at": self._timestamp(batch.created_at),
        }

    def _serialize_code(self, redeem_code: RedeemCode) -> dict:
        status = redeem_code.status
        if status == "unused" and redeem_code.expires_at is not None and redeem_code.expires_at < self._now():
            status = "expired"
        return {
            "id": str(redeem_code.id),
            "batch_id": str(redeem_code.batch_id) if redeem_code.batch_id else None,
            "plan_id": str(redeem_code.plan_id),
            "code_mask": redeem_code.code_mask,
            "status": status,
            "redeemed_by": str(redeem_code.redeemed_by) if redeem_code.redeemed_by else None,
            "redeemed_at": self._timestamp(redeem_code.redeemed_at),
            "expires_at": self._timestamp(redeem_code.expires_at),
            "disabled_at": self._timestamp(redeem_code.disabled_at),
            "created_at": self._timestamp(redeem_code.created_at),
        }
