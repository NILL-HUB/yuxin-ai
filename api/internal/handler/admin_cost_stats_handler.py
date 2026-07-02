from dataclasses import dataclass

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_cost_stats_schema import (
    CostStatsByDimensionResp,
    CostStatsOverviewResp,
    CostStatsTimeseriesResp,
    GetCostStatsByDimensionReq,
    GetCostStatsOverviewReq,
    GetCostStatsTimeseriesReq,
)
from internal.service.cost_stats_service import CostStatsService
from pkg.response import success_json, validate_error_json


@inject
@dataclass
class AdminCostStatsHandler:
    cost_stats_service: CostStatsService

    @admin_login_required
    @permission_required("cost_stats:read")
    def overview(self):
        req = GetCostStatsOverviewReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.cost_stats_service.overview(
            start_at=req.start_at.data or None,
            end_at=req.end_at.data or None,
        )
        return success_json(CostStatsOverviewResp().dump(result))

    @admin_login_required
    @permission_required("cost_stats:read")
    def by_dimension(self):
        req = GetCostStatsByDimensionReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.cost_stats_service.by_dimension(
            dimension=req.dimension.data or "user",
            start_at=req.start_at.data or None,
            end_at=req.end_at.data or None,
            limit=req.limit.data or 10,
        )
        return success_json(CostStatsByDimensionResp().dump(result))

    @admin_login_required
    @permission_required("cost_stats:read")
    def timeseries(self):
        req = GetCostStatsTimeseriesReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.cost_stats_service.timeseries(
            granularity=req.granularity.data or "day",
            start_at=req.start_at.data or None,
            end_at=req.end_at.data or None,
        )
        return success_json(CostStatsTimeseriesResp().dump(result))
