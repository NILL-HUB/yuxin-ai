"""对账服务：任务结束后把 usage 事件落库、按定价引擎重算实际/成本算力，
求差多退少补，写对账摘要行，按阈值判定告警。"""
import math
from decimal import Decimal
from typing import Any

from internal.model.billing import BillingReconciliation, BillingUsageEvent
from internal.service.credit_service import CreditService


class BillingReconciliationService:
    DEFAULT_ALERT_RATIO = 0.30
    DEFAULT_ALERT_MIN_ABS = 10
    DEFAULT_COST_COVER_RATIO = 1.0

    def __init__(self, session=None, pricing_engine=None, credit_service=None,
                 alert_ratio=None, alert_min_abs=None, cost_cover_ratio=None):
        from internal.extension.database_extension import db
        from internal.core.billing.pricing_engine import PricingEngine
        self.session = session or db.session
        self.pricing_engine = pricing_engine or PricingEngine()
        self.credit_service = credit_service or CreditService(session=self.session)
        self.alert_ratio = alert_ratio if alert_ratio is not None else self.DEFAULT_ALERT_RATIO
        self.alert_min_abs = alert_min_abs if alert_min_abs is not None else self.DEFAULT_ALERT_MIN_ABS
        self.cost_cover_ratio = cost_cover_ratio if cost_cover_ratio is not None else self.DEFAULT_COST_COVER_RATIO

    def persist_event(self, *, task_id: str, model_id, source_type: str, input_tokens: int,
                      output_tokens: int, billing_basis: str, estimated_credits: int,
                      actual_credits: int = 0, cost_credits: int = 0, is_estimated: bool = False,
                      cached_input_tokens: int = 0, price_tier: str = "", moment=None) -> BillingUsageEvent:
        event = BillingUsageEvent(
            task_id=task_id, model_id=model_id or None, source_type=source_type,
            input_tokens=max(int(input_tokens or 0), 0),
            cached_input_tokens=max(int(cached_input_tokens or 0), 0),
            output_tokens=max(int(output_tokens or 0), 0),
            billing_basis=billing_basis or "provider_usage",
            is_estimated=bool(is_estimated),
            estimated_credits=max(int(estimated_credits or 0), 0),
            actual_credits=max(int(actual_credits or 0), 0),
            cost_credits=max(int(cost_credits or 0), 0),
            price_tier=str(price_tier or "")[:16],
            moment=moment,
        )
        self.session.add(event)
        return event

    def settle(self, *, task_id: str, account_id, events: list[dict]) -> dict:
        """结算一个任务：重算 → 退补 → 写对账行 → 判定告警。重复调用幂等。"""
        existing = self.session.query(BillingReconciliation).filter(
            BillingReconciliation.task_id == task_id
        ).one_or_none()
        if existing is not None:
            return {"task_id": task_id, "idempotent": True, "status": existing.status,
                    "alert_flags": list(existing.alert_flags or [])}

        if not events:
            return {"task_id": task_id, "skipped": True, "reason": "no_events"}

        total_estimated = 0
        total_actual = 0
        total_cost = 0
        total_cost_amount = Decimal("0.000000")
        for ev in events:
            total_estimated += max(int(ev.get("estimated_credits") or 0), 0)
            input_tokens = max(int(ev.get("input_tokens") or 0), 0)
            output_tokens = max(int(ev.get("output_tokens") or 0), 0)
            model_id = ev.get("model_id") or ""
            plan = self.pricing_engine.plan_usage(
                model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=ev.get("cached_input_tokens", 0),
                moment=ev.get("moment") or None,
            )
            total_actual += plan.sell_credits
            total_cost += plan.cost_credits
            # 人民币成本 = tokens × 成本单价/1000（BillingPlan 提供 cost_input_per_1k/cost_output_per_1k）
            cost_rmb = (input_tokens * plan.cost_input_per_1k + output_tokens * plan.cost_output_per_1k) / 1000
            total_cost_amount += Decimal(str(round(cost_rmb, 6)))

        diff = total_actual - total_estimated
        if diff != 0:
            self.credit_service.adjust_credits(
                account_id, diff_credits=diff,
                source="reconciliation", source_id=task_id,
                description=f"对账多退少补 task={task_id}",
            )

        alert_flags = []
        if total_estimated > 0:
            ratio = abs(total_actual - total_estimated) / total_estimated
            if ratio > self.alert_ratio and abs(total_actual - total_estimated) > self.alert_min_abs:
                alert_flags.append("ratio_deviation")
        if total_actual > 0 and total_cost > 0 and (total_cost / total_actual) > self.cost_cover_ratio:
            alert_flags.append("negative_margin")

        row = BillingReconciliation(
            task_id=task_id, account_id=account_id,
            estimated_credits=total_estimated, actual_credits=total_actual,
            diff_credits=diff, cost_credits=total_cost, cost_amount=total_cost_amount,
            status="settled", alert_flags=alert_flags,
        )
        self.session.add(row)
        return {
            "task_id": task_id,
            "estimated_credits": total_estimated,
            "actual_credits": total_actual,
            "cost_credits": total_cost,
            "diff_credits": diff,
            "alert_flags": alert_flags,
            "idempotent": False,
        }