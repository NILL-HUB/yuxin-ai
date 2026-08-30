"""管理端对账查询：任务对账列表、按模型/按用户毛利聚合、告警筛选。"""
import math
from datetime import UTC

from internal.model.billing import BillingReconciliation


class AdminBillingReconciliationService:
    def __init__(self, session=None):
        from internal.extension.database_extension import db

        self.session = session or db.session

    def list_reconciliations(self, *, keyword="", alert=None, current_page=1, page_size=20) -> dict:
        query = self.session.query(BillingReconciliation)
        if alert:
            query = query.filter(BillingReconciliation.alert_flags.op("@>")([alert]))
        total = query.count()
        rows = (
            query.order_by(BillingReconciliation.created_at.desc())
            .offset((current_page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return {
            "list": [self._serialize(r) for r in rows],
            "paginator": {
                "total_record": total,
                "total_page": math.ceil(total / page_size) if page_size else 0,
                "current_page": current_page,
                "page_size": page_size,
            },
        }

    def model_margin_summary(self, *, current_page=1, page_size=20) -> dict:
        rows = self.session.query(BillingReconciliation).all()
        agg = {}
        for r in rows:
            # 简化：按 task 维度聚合毛利（模型级拆分依赖 usage_event join，首期按对账行聚合）
            key = "all"
            bucket = agg.setdefault(key, {"calls": 0, "actual": 0, "cost": 0, "margin": 0})
            bucket["calls"] += 1
            bucket["actual"] += int(r.actual_credits or 0)
            bucket["cost"] += int(r.cost_credits or 0)
            bucket["margin"] += int(r.actual_credits or 0) - int(r.cost_credits or 0)
        items = [{"model_name": "汇总", **v} for v in agg.values()]
        total_margin = sum(int(v["actual"]) - int(v["cost"]) for v in agg.values())
        total_actual = sum(int(v["actual"]) for v in agg.values())
        # P2：按档位/缓存维度聚合 usage event，随现有 dict 一并透传，前端键兼容
        from internal.service.billing_reconciliation_service import BillingReconciliationService

        tier_summary = BillingReconciliationService(session=self.session).margin_summary()
        return {
            "list": items,
            "total_margin": total_margin,
            "total_actual": total_actual,
            **tier_summary,
        }

    @staticmethod
    def _serialize(r) -> dict:
        return {
            "id": str(r.id),
            "task_id": r.task_id,
            "account_id": str(r.account_id),
            "estimated_credits": int(r.estimated_credits or 0),
            "actual_credits": int(r.actual_credits or 0),
            "cost_credits": int(r.cost_credits or 0),
            "diff_credits": int(r.diff_credits or 0),
            "status": r.status,
            "alert_flags": list(r.alert_flags or []),
            "created_at": int(r.created_at.replace(tzinfo=UTC).timestamp()) if r.created_at else 0,
        }