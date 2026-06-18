from dataclasses import dataclass

from flask_login import current_user, login_required
from injector import inject

from internal.service.user_routing_summary_service import UserRoutingSummaryService
from pkg.response import success_json


@inject
@dataclass
class RoutingLogHandler:
    user_routing_summary_service: UserRoutingSummaryService

    @login_required
    def summary(self):
        result = self.user_routing_summary_service.get_user_summary(current_user.id)
        return success_json(result)
