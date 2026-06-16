from dataclasses import dataclass

from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_orchestration_release_schema import (
    OrchestrationReleaseCheckResp,
)
from internal.service.orchestration_release_check_service import (
    OrchestrationReleaseCheckService,
)
from pkg.response import success_json


@inject
@dataclass
class AdminOrchestrationReleaseHandler:
    orchestration_release_check_service: OrchestrationReleaseCheckService

    @admin_login_required
    @permission_required("orchestration_release:read")
    def get(self):
        report = self.orchestration_release_check_service.build_report()
        return success_json(OrchestrationReleaseCheckResp().dump(report))
