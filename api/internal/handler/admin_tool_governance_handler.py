from dataclasses import dataclass
from uuid import UUID

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_tool_governance_schema import (
    AdminToolGovernanceAuditPageResp,
    AdminToolGovernanceBatchRiskResp,
    AdminToolGovernancePolicyPageResp,
    AdminToolGovernancePolicyResp,
    AdminToolGovernanceStatsResp,
    BatchUpdateToolGovernanceRiskReq,
    GetAdminToolGovernanceAuditReq,
    GetAdminToolGovernancePoliciesReq,
)
from internal.service.admin_tool_governance_service import AdminToolGovernanceService
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class AdminToolGovernanceHandler:
    admin_tool_governance_service: AdminToolGovernanceService

    @admin_login_required
    @permission_required("tool_governance:read")
    def list_policies(self):
        req = GetAdminToolGovernancePoliciesReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_tool_governance_service.list_policies(
            current_page=req.current_page.data,
            page_size=req.page_size.data,
            source_type=req.source_type.data,
            risk_level=req.risk_level.data,
            visibility=req.visibility.data,
            enabled=req.enabled.data,
            keyword=req.keyword.data,
        )
        resp = AdminToolGovernancePolicyPageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("tool_governance:manage")
    def create_policy(self):
        payload = request.get_json(silent=True) or {}
        result = self.admin_tool_governance_service.create_policy(payload)
        resp = AdminToolGovernancePolicyResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("tool_governance:read")
    def get_policy(self, policy_id: UUID):
        resp = AdminToolGovernancePolicyResp()
        return success_json(resp.dump(self.admin_tool_governance_service.get_policy(policy_id)))

    @admin_login_required
    @permission_required("tool_governance:manage")
    def update_policy(self, policy_id: UUID):
        payload = request.get_json(silent=True) or {}
        result = self.admin_tool_governance_service.update_policy(policy_id, payload)
        resp = AdminToolGovernancePolicyResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("tool_governance:manage")
    def delete_policy(self, policy_id: UUID):
        self.admin_tool_governance_service.delete_policy(policy_id)
        return success_message("删除工具治理策略成功")

    @admin_login_required
    @permission_required("tool_governance:manage")
    def set_status(self, policy_id: UUID):
        payload = request.get_json(silent=True) or {}
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            return validate_error_json({"enabled": ["enabled 必须为布尔值"]})
        result = self.admin_tool_governance_service.set_enabled(policy_id, enabled)
        resp = AdminToolGovernancePolicyResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("tool_governance:manage")
    def batch_update_risk(self):
        req = BatchUpdateToolGovernanceRiskReq()
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_tool_governance_service.batch_update_risk(req.policy_ids.data, req.risk_level.data)
        resp = AdminToolGovernanceBatchRiskResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("tool_governance:read")
    def list_audit_logs(self):
        req = GetAdminToolGovernanceAuditReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_tool_governance_service.list_audit_logs(
            current_page=req.current_page.data,
            page_size=req.page_size.data,
            tool_id=req.tool_id.data,
            status=req.status.data,
            start_date=req.start_date.data,
            end_date=req.end_date.data,
        )
        resp = AdminToolGovernanceAuditPageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("tool_governance:read")
    def stats(self):
        result = self.admin_tool_governance_service.get_governance_stats()
        resp = AdminToolGovernanceStatsResp()
        return success_json(resp.dump(result))
