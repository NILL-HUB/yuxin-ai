from dataclasses import dataclass

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_audit_log_schema import AuditLogPageResp, GetAuditLogsReq
from internal.service.audit_log_service import AuditLogService
from pkg.response import success_json, validate_error_json


@inject
@dataclass
class AdminAuditLogHandler:
    audit_log_service: AuditLogService

    @admin_login_required
    @permission_required("audit_log:read")
    def list(self):
        req = GetAuditLogsReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.audit_log_service.list_audit_logs(
            action=req.action.data,
            resource_type=req.resource_type.data,
            admin_user_id=req.admin_user_id.data,
            start_time=req.start_time.data or None,
            end_time=req.end_time.data or None,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = AuditLogPageResp()
        return success_json(resp.dump(result))
