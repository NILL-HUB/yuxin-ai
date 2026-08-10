from dataclasses import dataclass
from datetime import datetime, UTC

from injector import inject
from sqlalchemy import func, cast, Integer, literal_column
from sqlalchemy.types import Text

from internal.model.routing_log import RoutingLog
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


@inject
@dataclass
class CostStatsService(BaseService):
    db: SQLAlchemy

    @staticmethod
    def _credits_col():
        return cast(literal_column("cost_summary->>'total_credits'"), Integer)

    def overview(self, *, start_at: int | None = None, end_at: int | None = None) -> dict:
        credits_col = self._credits_col()
        query = self.db.session.query(
            func.coalesce(func.sum(credits_col), 0).label("total_credits"),
            func.count().label("total_requests"),
        ).select_from(RoutingLog)

        query = self._apply_time_filter(query, start_at, end_at)
        row = query.first()

        total_credits = int(row.total_credits or 0)
        total_requests = int(row.total_requests or 0)
        avg_cost = round(total_credits / total_requests, 2) if total_requests > 0 else 0.0

        return {
            "total_credits": total_credits,
            "total_requests": total_requests,
            "avg_cost_per_request": avg_cost,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }

    def by_dimension(
        self,
        *,
        dimension: str = "user",
        start_at: int | None = None,
        end_at: int | None = None,
        limit: int = 10,
    ) -> dict:
        dimension_expr = self._dimension_expression(dimension)
        credits_col = self._credits_col()

        query = self.db.session.query(
            dimension_expr.label("name"),
            func.coalesce(func.sum(credits_col), 0).label("total_credits"),
            func.count().label("request_count"),
        ).select_from(RoutingLog)

        query = self._apply_time_filter(query, start_at, end_at)
        query = query.group_by(dimension_expr).order_by(
            func.sum(credits_col).desc()
        ).limit(limit)

        rows = query.all()
        grand_total = sum(int(r.total_credits or 0) for r in rows)

        items = []
        for r in rows:
            credits = int(r.total_credits or 0)
            count = int(r.request_count or 0)
            avg = round(credits / count, 2) if count > 0 else 0.0
            pct = round(credits / grand_total * 100, 1) if grand_total > 0 else 0.0
            items.append({
                "name": str(r.name or "unknown"),
                "total_credits": credits,
                "request_count": count,
                "avg_credits": avg,
                "percentage": pct,
            })

        return {
            "dimension": dimension,
            "items": items,
            "total_credits": grand_total,
        }

    def timeseries(
        self,
        *,
        granularity: str = "day",
        start_at: int | None = None,
        end_at: int | None = None,
    ) -> dict:
        trunc = "day" if granularity == "day" else "hour"
        credits_col = self._credits_col()
        ts_col = func.date_trunc(trunc, RoutingLog.created_at).label("ts")

        query = self.db.session.query(
            ts_col,
            func.coalesce(func.sum(credits_col), 0).label("total_credits"),
            func.count().label("request_count"),
        ).select_from(RoutingLog)

        query = self._apply_time_filter(query, start_at, end_at)
        query = query.group_by(ts_col).order_by(ts_col)

        rows = query.all()

        points = []
        for r in rows:
            ts_val = r.ts
            if ts_val and ts_val.tzinfo is None:
                ts_val = ts_val.replace(tzinfo=UTC)
            ts = int(ts_val.timestamp()) if ts_val else 0
            points.append({
                "timestamp": ts,
                "total_credits": int(r.total_credits or 0),
                "request_count": int(r.request_count or 0),
            })

        return {
            "granularity": granularity,
            "points": points,
        }

    def _dimension_expression(self, dimension: str):
        if dimension == "user":
            return RoutingLog.account_id.cast(Text()).label("name")
        if dimension == "model":
            return literal_column("model_selection->>'model_id'").label("name")
        if dimension == "status":
            return RoutingLog.status.label("name")
        if dimension == "agent_pool":
            return literal_column("model_selection->>'model_tier'").label("name")
        if dimension == "source":
            return RoutingLog.invoke_from.label("name")
        return RoutingLog.account_id.cast(Text()).label("name")

    def _apply_time_filter(self, query, start_at: int | None, end_at: int | None):
        if start_at:
            query = query.filter(
                RoutingLog.created_at >= datetime.fromtimestamp(start_at, tz=UTC).replace(tzinfo=None)
            )
        if end_at:
            query = query.filter(
                RoutingLog.created_at <= datetime.fromtimestamp(end_at, tz=UTC).replace(tzinfo=None)
            )
        return query
