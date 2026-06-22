from dataclasses import dataclass

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.service.admin_tool_governance_service import AdminToolGovernanceService
from pkg.response import success_json


@inject
@dataclass
class AdminResourceEntryHandler:
    admin_tool_governance_service: AdminToolGovernanceService

    @staticmethod
    def _empty_page():
        return {
            "list": [],
            "paginator": {
                "total_record": 0,
                "total_page": 0,
                "current_page": 1,
                "page_size": 20,
            },
        }

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
    @permission_required("dataset:read")
    def datasets(self):
        return success_json(self._empty_page())

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
        current_page, page_size, keyword = self._pagination_args()
        return success_json(self.admin_tool_governance_service.list_policies(
            source_type="mcp",
            current_page=current_page,
            page_size=page_size,
            keyword=keyword,
        ))

    @admin_login_required
    @permission_required("skill:read")
    def skills(self):
        current_page, page_size, keyword = self._pagination_args()
        return success_json(self.admin_tool_governance_service.list_policies(
            source_type="skill",
            current_page=current_page,
            page_size=page_size,
            keyword=keyword,
        ))
