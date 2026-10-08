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
    # 本轮对应的助手消息 id：扣费流水以它为 source_id（source='message'），
    # 使「单条消息消耗 / 会话累计消耗」可按 message_id 聚合回显（2026-10-08 反馈：
    # 此前用 task_id 派生合成 id，流水无法关联到消息 → 历史会话的算力显示恒为 0）。
    message_id: Any = None
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
        # 扣费先于事件记录（2026-10-07 调整）：把扣减结果里的「算力不足」带进
        # billing_final 事件的 metadata，供前端明确提示用户；此前扣费返回值被丢弃，
        # 余额耗尽时仅静默扣 0（用户无感知，且误以为正常工作）。
        insufficient = False
        insufficient_reason = ""
        # 本次**实际扣减**的算力值（套餐额度 + 永久算力）：final 事件必须回传它，
        # 否则前端「本次消耗 / 会话累计消耗」恒显示 0（2026-10-08 实测：
        # DB 已扣 5 算力、界面显示 0 —— 因为 final 的 delta 写死 0）。
        charged_credits = 0
        # 实际扣费：如果注入了 credit_service 和 account_id，则调用 CreditService。
        # 计价口径（2026-09 修复）：同任务同模型的多笔调用先合并 token，再按
        # 模型单价一次精确计价（一次 ceil），避免每笔独立 ceil 把不足 1 算力的
        # 小调用重复进位造成系统性多收。
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
                    # 按 model_id 合并 token（同模型多次调用归并为一次计费）
                    merged: dict[str, dict] = {}
                    for ev in detailed:
                        model_id = ev.get("model_id") or ""
                        group = merged.setdefault(model_id, {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cached_input_tokens": 0,
                            "moment": None,
                        })
                        group["input_tokens"] += max(int(ev.get("input_tokens") or 0), 0)
                        group["output_tokens"] += max(int(ev.get("output_tokens") or 0), 0)
                        group["cached_input_tokens"] += max(int(ev.get("cached_input_tokens") or 0), 0)
                        moment = ev.get("moment")
                        if group["moment"] is None or (moment is not None and moment > group["moment"]):
                            group["moment"] = moment
                    for model_id, group in merged.items():
                        ev_total = (
                            group["input_tokens"]
                            + group["cached_input_tokens"]
                            + group["output_tokens"]
                        )
                        if ev_total <= 0:
                            continue
                        consume_result = self.credit_service.consume_for_feature(
                            account_id=self.account_id,
                            feature_key=self.feature_key,
                            token_count=ev_total,
                            idempotency_key=f"{self.task_id}:{model_id}:merged",
                            model_id=model_id or None,
                            input_tokens=group["input_tokens"],
                            output_tokens=group["output_tokens"],
                            cached_input_tokens=group["cached_input_tokens"],
                            message_id=self.message_id,
                        )
                        charged_credits += self._charged_credits(consume_result)
                        if isinstance(consume_result, dict) and consume_result.get("insufficient"):
                            insufficient = True
                            insufficient_reason = str(consume_result.get("reason") or "")
                elif self.total_tokens > 0:
                    consume_result = self.credit_service.consume_for_feature(
                        account_id=self.account_id,
                        feature_key=self.feature_key,
                        token_count=self.total_tokens,
                        message_id=self.message_id,
                    )
                    charged_credits += self._charged_credits(consume_result)
                    if isinstance(consume_result, dict) and consume_result.get("insufficient"):
                        insufficient = True
                        insufficient_reason = str(consume_result.get("reason") or "")
            except Exception:
                logger.warning(
                    "BillingUsageAggregator 扣费失败 task_id=%s", self.task_id, exc_info=True
                )

        # final 是用户可见的权威数字：以**实际扣费**覆盖 delta 估算累计
        # （delta 用定价引擎估算，与扣费口径可能不同；界面与账单必须一致）。
        if charged_credits > 0:
            self.total_credits = charged_credits
        event = self._record(
            BillingEventType.FINAL.value,
            "summary",
            "billing",
            charged_credits,
            "billing_final",
            metadata=(
                {"insufficient": True, "reason": insufficient_reason or "credits_exhausted"}
                if insufficient
                else None
            ),
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

    @staticmethod
    def _charged_credits(consume_result: Any) -> int:
        """从扣费返回值里取**实际扣减**的算力值（套餐额度 + 永久算力）。

        - 正常路径：`actual_compute_units`（额度耗尽时可能小于应扣额，取真实值）；
        - 幂等命中路径：只回 `amount`（负数），取绝对值。
        """
        if not isinstance(consume_result, dict):
            return 0
        actual = consume_result.get("actual_compute_units")
        if actual is None:
            amount = consume_result.get("amount")
            actual = -int(amount) if isinstance(amount, (int, float)) and amount < 0 else 0
        try:
            return max(int(actual or 0), 0)
        except (TypeError, ValueError):
            return 0

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
