import logging
from dataclasses import dataclass, field
from typing import Any

from internal.entity.billing_metering_entity import (
    BillingEventType,
    BillingUsageCancelled,
    BillingUsageDelta,
)

logger = logging.getLogger(__name__)


@dataclass
class BillingUsageAggregator:
    task_id: str
    total_credits: int = 0
    credits_per_1k_tokens: int = 1
    events: list[BillingUsageDelta | BillingUsageCancelled] = field(default_factory=list)
    # 可选注入：注入后 final() 会实际调用 CreditService 扣费
    credit_service: Any = None
    account_id: Any = None
    feature_key: str = "assistant_agent"
    # 累计原始 token 数，用于 final() 调用 consume_for_feature(token_count=...)
    total_tokens: int = 0
    # 可选注入：定价引擎。注入后 model_tokens 按模型售价（plan_usage.sell_credits）计价；
    # 未注入时回退全局汇率（credits_per_1k_tokens），与旧逻辑 1:1 兼容
    pricing_engine: Any = None
    # 原始 usage 事件缓冲（估算口径），final() 对账回调时落库并结算
    usage_event_buf: list[dict] = field(default_factory=list)
    # SSE 流式请求无请求级提交点，final() 末尾显式提交账单写入；
    # 单元测试（fake service/fake session）置 False 跳过真实 commit
    _should_commit: bool = True

    def started(self) -> BillingUsageDelta:
        return self._record(
            BillingEventType.STARTED.value,
            "summary",
            "billing",
            0,
            "billing_started",
        )

    def delta(
        self,
        source_type: str,
        source_name: str,
        delta_credits: int,
        *,
        reason: str = "",
        metadata: dict | None = None,
    ) -> BillingUsageDelta:
        self.total_credits += delta_credits
        # 累计 model 来源的原始 token，供 final() 实际扣费使用
        if source_type == "model" and metadata:
            self.total_tokens += int(metadata.get("input_tokens", 0) or 0) + int(
                metadata.get("output_tokens", 0) or 0
            )
        return self._record(
            BillingEventType.DELTA.value,
            source_type,
            source_name,
            delta_credits,
            reason,
            metadata or {},
        )

    def model_tokens(
        self,
        source_name: str,
        *,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        reason: str,
        cached_input_tokens: int = 0,
        moment=None,
    ) -> BillingUsageDelta:
        sell_credits = 0
        if self.pricing_engine is not None:
            plan = self.pricing_engine.plan_usage(
                model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_input_tokens,
                moment=moment,
            )
            sell_credits = plan.sell_credits
        else:
            total_tokens = max(input_tokens, 0) + max(output_tokens, 0)
            sell_credits = int(total_tokens * self.credits_per_1k_tokens / 1000)
        self.usage_event_buf.append(
            {
                "model_id": model_id,
                "source_type": source_name,
                "input_tokens": max(input_tokens - max(int(cached_input_tokens or 0), 0), 0),
                "cached_input_tokens": max(int(cached_input_tokens or 0), 0),
                "output_tokens": max(output_tokens, 0),
                "estimated_credits": sell_credits,
                "billing_basis": "provider_usage",
                "is_estimated": False,
                "price_tier": getattr(plan, "price_tier", None) if self.pricing_engine is not None else None,
                "moment": moment,
            }
        )
        return self.delta(
            "model",
            source_name,
            sell_credits,
            reason=reason,
            metadata={
                "model_id": model_id,
                "input_tokens": max(input_tokens - max(int(cached_input_tokens or 0), 0), 0),
                "cached_input_tokens": max(int(cached_input_tokens or 0), 0),
                "output_tokens": max(output_tokens, 0),
            },
        )

    def summary(self) -> BillingUsageDelta:
        return self._record(
            BillingEventType.SUMMARY.value,
            "summary",
            "billing",
            0,
            "billing_summary",
        )

    def cancelled(
        self,
        *,
        reason: str = "user_stop",
        pending_phases: list[str] | None = None,
    ) -> BillingUsageCancelled:
        event = BillingUsageCancelled(
            event_type=BillingEventType.CANCELLED.value,
            task_id=self.task_id,
            total_credits=self.total_credits,
            reason=reason,
            pending_phases=list(pending_phases or []),
        )
        self.events.append(event)
        return event

    def final(self, reconciliation_service: Any = None) -> BillingUsageDelta:
        event = self._record(
            BillingEventType.FINAL.value,
            "summary",
            "billing",
            0,
            "billing_final",
        )
        # 实际扣费：如果注入了 credit_service 和 account_id，则调用 CreditService。
        # 优先按 usage 明细逐条精确计价（model_id+input/output/cached，消除对 1:1
        # 全局汇率的依赖）；无明细可查时回退旧行为（累计 token_count × 全局汇率）。
        if (
            self.credit_service is not None
            and self.account_id is not None
        ):
            try:
                detailed = [
                    ev for ev in self.usage_event_buf
                    if (ev.get("input_tokens") or 0) + (ev.get("output_tokens") or 0) > 0
                ]
                if detailed:
                    for idx, ev in enumerate(detailed):
                        ev_total = (
                            int(ev.get("input_tokens") or 0)
                            + int(ev.get("cached_input_tokens") or 0)
                            + int(ev.get("output_tokens") or 0)
                        )
                        if ev_total <= 0:
                            continue
                        self.credit_service.consume_for_feature(
                            account_id=self.account_id,
                            feature_key=self.feature_key,
                            token_count=ev_total,
                            idempotency_key=f"{self.task_id}:{ev.get('model_id') or ''}:{ev.get('source_type') or ''}:{idx}",
                            model_id=ev.get("model_id") or None,
                            input_tokens=int(ev.get("input_tokens") or 0),
                            output_tokens=int(ev.get("output_tokens") or 0),
                            cached_input_tokens=int(ev.get("cached_input_tokens") or 0),
                        )
                elif self.total_tokens > 0:
                    self.credit_service.consume_for_feature(
                        account_id=self.account_id,
                        feature_key=self.feature_key,
                        token_count=self.total_tokens,
                    )
            except Exception:
                logger.warning(
                    "BillingUsageAggregator 扣费失败 task_id=%s", self.task_id, exc_info=True
                )

        # P2：对账回调——把事件落库并结算（幂等）
        if (
            reconciliation_service is not None
            and self.account_id is not None
            and self.usage_event_buf
        ):
            try:
                for ev in self.usage_event_buf:
                    reconciliation_service.persist_event(
                        task_id=self.task_id,
                        model_id=ev["model_id"],
                        source_type=ev["source_type"],
                        input_tokens=ev.get("input_tokens", 0),
                        cached_input_tokens=ev.get("cached_input_tokens", 0),
                        output_tokens=ev.get("output_tokens", 0),
                        billing_basis=ev.get("billing_basis", "provider_usage"),
                        estimated_credits=ev.get("estimated_credits", 0),
                        is_estimated=ev.get("is_estimated", False),
                        price_tier=ev.get("price_tier", ""),
                        moment=ev.get("moment") or None,
                    )
                reconciliation_service.settle(
                    task_id=self.task_id,
                    account_id=self.account_id,
                    events=self.usage_event_buf,
                )
            except Exception:
                # B3：对账失败不再静默。预扣（final 前半段）已按真实模型价完成，
                # 此处失败只会导致"多退少补"未执行，用户余额停留在预扣值。
                # 提升为 error 级结构化日志，便于运维巡检与告警接入。
                logger.error(
                    "billing_reconciliation_failed task_id=%s account_id=%s "
                    "events=%d phase=settle error_type=%s error=%s",
                    self.task_id,
                    self.account_id,
                    len(self.usage_event_buf),
                    type(exc).__name__,
                    str(exc)[:300],
                    exc_info=True,
                )

        # SSE 流式请求没有统一的请求级提交点：消息持久化（save_agent_thoughts）
        # 走独立 auto_commit，而账单行属于本聚合器的会话，若不显式提交会随
        # 请求结束被静默回滚（实测扣费/对账全部丢失）。此处显式提交，且在
        # 非流式/测试路径（fake service 无真实 Session）自动跳过。
        if self._should_commit:
            try:
                session = None
                for svc in (self.credit_service, reconciliation_service):
                    if svc is None:
                        continue
                    session = getattr(svc, "session", None)
                    if session is not None and hasattr(session, "commit"):
                        break
                if session is not None:
                    session.commit()
            except Exception:
                logger.warning(
                    "BillingUsageAggregator 提交失败 task_id=%s", self.task_id, exc_info=True
                )
        return event

    def _record(
        self,
        event_type: str,
        source_type: str,
        source_name: str,
        delta_credits: int,
        reason: str,
        metadata: dict | None = None,
    ) -> BillingUsageDelta:
        event = BillingUsageDelta(
            event_type=event_type,
            task_id=self.task_id,
            source_type=source_type,
            source_name=source_name,
            delta_credits=delta_credits,
            total_credits=self.total_credits,
            reason=reason,
            metadata=metadata or {},
        )
        self.events.append(event)
        return event


class BillingMetering(BillingUsageAggregator):
    pass
