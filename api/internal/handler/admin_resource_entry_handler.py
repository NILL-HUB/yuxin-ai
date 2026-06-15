from dataclasses import dataclass

from injector import inject

from internal.middleware import admin_login_required, permission_required
from pkg.response import success_json


@inject
@dataclass
class AdminResourceEntryHandler:
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

    @admin_login_required
    @permission_required("dataset:read")
    def datasets(self):
        return success_json(self._empty_page())

    @admin_login_required
    @permission_required("tool:read")
    def tools(self):
        return success_json(self._empty_page())

    @admin_login_required
    @permission_required("mcp:read")
    def mcp(self):
        return success_json(self._empty_page())

    @admin_login_required
    @permission_required("skill:read")
    def skills(self):
        return success_json(self._empty_page())
