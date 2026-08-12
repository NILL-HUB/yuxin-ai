from dataclasses import dataclass
from datetime import datetime, UTC

from injector import inject
from sqlalchemy import func, cast, Integer, literal_column
from sqlalchemy.types import Text

from internal.model.routing_log import RoutingLog
from internal.model.account import Account
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


@inject
@dataclass
class CostStatsService(BaseService):
    db: SQLAlchemy

    @staticmethod
    def _credits_col():
        # routing_log.cost_summary 实际写入的是 estimated_credits，
        # 老数据可能只有 total_credits，统一兼容两种键。
        return cast(
            literal_column(
                "COALESCE(NULLIF(cost_summary->>'estimated_credits', ''), "
                "NULLIF(cost_summary->>'total_credits', ''), '0')"
            ),
            Integer,
        )

    @staticmethod
    def _dimension_value_expr(expr):
        """把空串/缺失值统一归一到 unknown，避免面板出现空白维度名。"""
        return literal_column(f"COALESCE(NULLIF(({expr})::text, ''), 'unknown')")

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
        limit: int = 100,
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
        )

        # 先算全量分组总成本，确保 limit 截断后百分比仍基于完整数据集
        grand_total_query = self.db.session.query(
            func.coalesce(func.sum(credits_col), 0).label("total_credits")
        ).select_from(RoutingLog)
        grand_total_query = self._apply_time_filter(grand_total_query, start_at, end_at)
        grand_total = int(grand_total_query.first().total_credits or 0)

        rows = query.limit(limit).all()

        items = []
        account_ids = []
        for r in rows:
            try:
                account_ids.append(r.name)
            except Exception:
                pass

        account_name_map = {}
        if dimension == "user" and account_ids:
            account_name_map = self._resolve_account_names(account_ids)

        for r in rows:
            credits = int(r.total_credits or 0)
            count = int(r.request_count or 0)
            avg = round(credits / count, 2) if count > 0 else 0.0
            pct = round(credits / grand_total * 100, 1) if grand_total > 0 else 0.0
            raw_name = str(r.name or "unknown")
            items.append({
                "name": account_name_map.get(raw_name, raw_name) if dimension == "user" else raw_name,
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

    def _resolve_account_names(self, account_ids):
        # 只解析 UUID 形态的账号 ID，避免把非 user 维度的原始值误当成账号查询
        uuid_like_ids = []
        try:
            from uuid import UUID
            for value in account_ids:
                try:
                    UUID(str(value))
                    uuid_like_ids.append(value)
                except (ValueError, TypeError):
                    continue
        except Exception:
            return {}

        if not uuid_like_ids:
            return {}

        try:
            accounts = self.db.session.query(Account).filter(
                Account.id.in_(uuid_like_ids)
            ).all()
        except Exception:
            return {}

        name_map = {}
        for account in accounts:
            account_id = str(account.id)
            display_name = (account.name or "").strip() or (account.username or "").strip()
            if not display_name and (account.email or "").strip():
                display_name = account.email.strip()
            name_map[account_id] = display_name or account_id
        return name_map

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
            # 实际数据主要写 execution_model / model_tier，model_id 可能为空
            return self._dimension_value_expr(
                "COALESCE(NULLIF(model_selection->>'model_display_name', ''), "
                "NULLIF(model_selection->>'model_id', ''), "
                "NULLIF(model_selection->>'execution_model', ''), "
                "NULLIF(model_selection->>'model_tier', ''))"
            ).label("name")
        if dimension == "status":
            return self._dimension_value_expr("routing_log.status").label("name")
        if dimension == "agent_pool":
            return self._dimension_value_expr("model_selection->>'model_tier'").label("name")
        if dimension == "source":
            return self._dimension_value_expr("routing_log.invoke_from").label("name")
        return self._dimension_value_expr("routing_log.account_id::text").label("name")

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
