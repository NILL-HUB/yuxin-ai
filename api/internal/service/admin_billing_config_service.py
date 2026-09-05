from decimal import Decimal, InvalidOperation

from internal.exception import FailException
from internal.extension.database_extension import db
from internal.model.billing import BillingConfig
from internal.service.audit_log_service import AuditLogService
from internal.schema.admin_billing_config_schema import (
    BILLING_CONFIG_CREDITS_PER_YUAN,
    BILLING_CONFIG_GLOBAL_RATE,
)


class AdminBillingConfigService:
    DEFAULT_CREDITS_PER_1K = 1
    DEFAULT_CREDITS_PER_YUAN = 100

    def __init__(self, session=None, audit_log_service=None):
        self.session = session or db.session
        self.audit_log_service = audit_log_service or AuditLogService(session=self.session)

    def get_config(self, code: str | None = None) -> dict:
        code = code or BILLING_CONFIG_GLOBAL_RATE
        row = self._get_row(code)
        if row is None:
            if code == BILLING_CONFIG_CREDITS_PER_YUAN:
                return {
                    "code": code,
                    "value_numeric": self.DEFAULT_CREDITS_PER_YUAN,
                    "description": "汇率锚：1 元人民币折合的算力值（成本→算力折算，默认 100）",
                }
            return {
                "code": code,
                "value_numeric": self.DEFAULT_CREDITS_PER_1K,
                "description": "每 1000 token 消耗的算力值（默认 1）",
            }
        return self._serialize(row)

    def upsert_config(self, payload: dict, *, code: str | None = None, operator_id=None, ip: str = "", user_agent: str = "") -> dict:
        code = code or BILLING_CONFIG_GLOBAL_RATE
        value, err = self._parse_value(payload.get("value_numeric"))
        if err:
            raise FailException("请填写 1-1000000 之间的整数（算力/元 或 算力/1k token）")
        description = (payload.get("description") or "").strip()
        row = self._get_row(code)
        before_data = self._serialize(row) if row is not None else None
        if row is None:
            row = BillingConfig(code=code, value_numeric=value, description=description)
            self.session.add(row)
        else:
            row.value_numeric = value
            row.description = description
        self._emit_audit(
            operator_id=operator_id,
            action="upsert",
            resource_type="billing_config",
            resource_id=str(row.id) if row.id else code,
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data=self._serialize(row),
        )
        self.session.commit()
        return self._serialize(row)

    def _get_row(self, code: str) -> BillingConfig | None:
        return (
            self.session.query(BillingConfig)
            .filter(BillingConfig.code == code)
            .one_or_none()
        )

    @staticmethod
    def _parse_value(raw) -> tuple[int, str | None]:
        try:
            value = int(Decimal(str(raw)))
        except (InvalidOperation, TypeError, ValueError):
            return 0, "invalid"
        if value < 1 or value > 1_000_000:
            return 0, "out_of_range"
        return value, None

    @staticmethod
    def _serialize(row: BillingConfig) -> dict:
        return {
            "code": row.code,
            "value_numeric": int(row.value_numeric or 0),
            "description": row.description or "",
        }

    def _emit_audit(self, *, operator_id, action, resource_type, resource_id, ip, user_agent, before_data, after_data) -> None:
        self.audit_log_service.record_for_write(
            admin_user_id=operator_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_data=before_data or {},
            after_data=after_data or {},
            ip=ip,
            user_agent=user_agent,
        )