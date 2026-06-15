from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from flask import g, request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_redeem_code_schema import (
    GenerateRedeemCodesResp,
    GetRedeemCodeBatchesReq,
    GetRedeemCodesReq,
    RedeemCodeBatchPageResp,
    RedeemCodePageResp,
    RedeemCodeResp,
)
from internal.service.admin_redeem_code_service import AdminRedeemCodeService
from pkg.response import success_json, validate_error_json


def _get_operator_context() -> tuple:
    current_admin = getattr(g, "current_admin_user", None) or {}
    operator_id = current_admin.get("id") if isinstance(current_admin, dict) else getattr(current_admin, "id", None)
    return (
        operator_id,
        request.headers.get("X-Forwarded-For", request.remote_addr or ""),
        request.headers.get("User-Agent", ""),
    )


def _parse_payload(payload: dict) -> dict:
    parsed = dict(payload)
    if parsed.get("plan_id"):
        parsed["plan_id"] = UUID(parsed["plan_id"])
    if parsed.get("expires_at"):
        parsed["expires_at"] = datetime.fromtimestamp(int(parsed["expires_at"]), tz=UTC).replace(tzinfo=None)
    return parsed


@inject
@dataclass
class AdminRedeemCodeHandler:
    admin_redeem_code_service: AdminRedeemCodeService

    @admin_login_required
    @permission_required("redeem_code:update")
    def generate(self):
        payload = request.get_json(silent=True) or {}
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_redeem_code_service.generate_codes(
            _parse_payload(payload),
            operator_id=operator_id,
            ip=ip,
            user_agent=user_agent,
        )
        resp = GenerateRedeemCodesResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("redeem_code:read")
    def list_batches(self):
        req = GetRedeemCodeBatchesReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_redeem_code_service.list_batches(
            keyword=req.keyword.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = RedeemCodeBatchPageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("redeem_code:read")
    def list_codes(self):
        req = GetRedeemCodesReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        batch_id = UUID(req.batch_id.data) if req.batch_id.data else None
        result = self.admin_redeem_code_service.list_codes(
            batch_id=batch_id,
            status=req.status.data,
            code_keyword=req.code_keyword.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = RedeemCodePageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("redeem_code:update")
    def disable(self, code_id: UUID):
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_redeem_code_service.disable_code(code_id, operator_id=operator_id, ip=ip, user_agent=user_agent)
        resp = RedeemCodeResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("redeem_code:update")
    def disable_batch(self, batch_id: UUID):
        operator_id, ip, user_agent = _get_operator_context()
        result = self.admin_redeem_code_service.disable_batch(batch_id, operator_id=operator_id, ip=ip, user_agent=user_agent)
        return success_json(result)
