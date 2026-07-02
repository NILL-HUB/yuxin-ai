from dataclasses import dataclass

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.mcp_schema import GetMcpProvidersWithPageReq, McpProviderResp
from internal.schema.skill_schema import GetSkillsWithPageReq, SkillPackageResp
from internal.service.admin_tool_governance_service import AdminToolGovernanceService
from internal.service.mcp_service import McpService
from internal.service.skill_service import SkillService
from pkg.paginator import PageModel
from pkg.response import success_json, validate_error_json


@inject
@dataclass
class AdminResourceEntryHandler:
    admin_tool_governance_service: AdminToolGovernanceService
    mcp_service: McpService
    skill_service: SkillService

    @staticmethod
    def _pagination_args():
        try:
            current_page = max(int(request.args.get("current_page", 1)), 1)
        except (TypeError, ValueError):
            current_page = 1
        try:
            page_size = max(min(int(request.args.get("page_size", 20)), 50), 1)
        except (TypeError, ValueError):
            page_size = 20
        keyword = (request.args.get("keyword") or "").strip()
        return current_page, page_size, keyword

    @admin_login_required
    @permission_required("tool:read")
    def tools(self):
        current_page, page_size, keyword = self._pagination_args()
        return success_json(self.admin_tool_governance_service.list_policies(
            source_type="api_tool",
            current_page=current_page,
            page_size=page_size,
            keyword=keyword,
        ))

    @admin_login_required
    @permission_required("mcp:read")
    def mcp(self):
        req = GetMcpProvidersWithPageReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)

        providers, paginator = self.mcp_service.get_admin_mcp_providers_with_page(req)
        resp = McpProviderResp(many=True)
        return success_json(PageModel(list=resp.dump(providers), paginator=paginator))

    @admin_login_required
    @permission_required("skill:read")
    def skills(self):
        req = GetSkillsWithPageReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)

        skills, paginator = self.skill_service.get_skill_packages_with_page(req)
        resp = SkillPackageResp(many=True)
        return success_json(PageModel(list=resp.dump(skills), paginator=paginator))
