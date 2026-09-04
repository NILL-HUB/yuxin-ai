import math
from datetime import UTC, datetime, timedelta
from uuid import UUID

from internal.core.billing.pricing_engine import PricingEngine
from internal.exception import FailException
from internal.extension.database_extension import db
from internal.model.billing import BillingConfig, CreditAccount, CreditTransaction, Membership
from internal.model.public_ai_feature_config import PublicAIFeatureConfig


class CreditService:
    TOKENS_PER_COMPUTE_UNIT = 1000

    def __init__(self, session=None, pricing_engine=None):
        self.session = session or db.session
        self.pricing_engine = pricing_engine

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @classmethod
    def compute_units_from_tokens(cls, token_count: int) -> int:
        token_count = int(token_count or 0)
        if token_count <= 0:
            return 0
        return math.ceil(token_count / cls.TOKENS_PER_COMPUTE_UNIT)

    def _credits_per_1k_tokens(self) -> int:
        """统一汇率：billing_config.code='credits_per_1k_tokens'（每 1k token 消耗的算力值）。

        未配置时默认为 1（即 1000 token = 1 算力）。返回值为正整数。
        保持直查 billing_config 的独立实现（供 _compute_units 兜底分支与描述复用），不经过定价引擎避免递归。
        """
        try:
            row = (
                self.session.query(BillingConfig)
                .filter(BillingConfig.code == "credits_per_1k_tokens")
                .one_or_none()
            )
        except Exception:
            row = None
        if row is not None and row.value_numeric:
            return max(int(row.value_numeric) or 1, 1)
        return 1

    def _get_pricing_engine(self) -> PricingEngine:
        if self.pricing_engine is None:
            self.pricing_engine = PricingEngine(session=self.session)
        return self.pricing_engine

    def _compute_units(self, token_count: int, *, model_id=None, input_tokens=None, output_tokens=None, cached_input_tokens=None) -> tuple[int, str, dict]:
        """经定价引擎计算本次消费算力（售价口径）。

        有模型明细时按引擎计价（input×sell_in + output×sell_out + cached×sell_cached）；
        无模型明细（tiktoken 估算入口）时回退全局汇率，与旧行为 1:1 兼容。
        返回 (compute_units, billing_basis, price_detail)。
        """
        token_count = int(token_count or 0)
        if model_id:
            plan = self._get_pricing_engine().plan_usage(
                model_id,
                input_tokens=int(input_tokens or 0),
                output_tokens=int(output_tokens or 0),
                cached_input_tokens=int(cached_input_tokens or 0),
            )
            return plan.sell_credits, plan.billing_basis, {
                "cost_credits": plan.cost_credits,
                "margin_credits": plan.margin_credits,
            }
        credits_per_1k = self._credits_per_1k_tokens()
        units = math.ceil(token_count * credits_per_1k / 1000) if token_count > 0 else 0
        return units, "global_rate", {"credits_per_1k": credits_per_1k}

    def consume_for_message(
        self,
        account_id: UUID,
        message_id: UUID,
        *,
        token_count: int,
        model_id: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cached_input_tokens: int | None = None,
    ) -> dict:
        """按 message_id 幂等扣减算力值。

        扣减顺序：套餐额度（会员有效期内）→ 永久算力。
        两者均为 0 时不再静默放行，返回 insufficient=True（reason=credits_exhausted）；
        余额不参与任何直接计费。

        传入 model_id/input_tokens/output_tokens 时经定价引擎按模型售价精确计价
        （消除对全局汇率 1:1 预扣的依赖）；缺省时回退旧行为（token_count × 全局汇率）。
        """
        compute_units, billing_basis, price_detail = self._compute_units(
            token_count,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
        )
        credits_per_1k = price_detail.get("credits_per_1k") or 1
        token_count = int(token_count or 0)
        if compute_units <= 0:
            return {"skipped": True, "reason": "zero_token_usage"}

        existing_transaction = self._get_existing_message_consume(message_id)
        if existing_transaction is not None:
            return {
                "id": str(existing_transaction.id),
                "amount": int(existing_transaction.amount or 0),
                "balance_after": int(existing_transaction.balance_after or 0),
                "compute_units": compute_units,
                "token_count": int(token_count or 0),
                "billing_basis": billing_basis,
                "cost_credits": price_detail.get("cost_credits"),
                "margin_credits": price_detail.get("margin_credits"),
                "idempotent": True,
            }

        credit_account = self._get_credit_account_for_update(account_id)
        if credit_account is None:
            credit_account = CreditAccount(account_id=account_id, permanent_credit=0, quota_credit=0, total_granted=0, total_consumed=0)
            self.session.add(credit_account)

        membership = self._get_current_membership(account_id)
        self._refresh_quota_if_due(credit_account, membership)
        before_available = credit_account.available_tokens
        result = self._apply_consume(credit_account, membership, compute_units)

        total_used = result["quota_used"] + result["permanent_used"]
        credit_account.total_consumed = int(credit_account.total_consumed or 0) + total_used
        credit_account.updated_at = self._now()
        after_available = credit_account.available_tokens
        transaction = CreditTransaction(
            account_id=account_id,
            amount=-total_used,
            balance_after=after_available,
            transaction_type="consume",
            source="message",
            source_id=message_id,
            description=self._build_consume_description(token_count, compute_units, result, credits_per_1k),
        )
        self.session.add(transaction)
        self._maybe_check_auto_renew(account_id)
        return {
            "id": str(transaction.id),
            "amount": -total_used,
            "balance_after": after_available,
            "compute_units": compute_units,
            "actual_compute_units": total_used,
            "token_count": int(token_count or 0),
            "quota_used": result["quota_used"],
            "permanent_used": result["permanent_used"],
            "insufficient": result["insufficient"],
            "reason": result.get("reason"),
            "before_available": before_available,
            "credits_per_1k": credits_per_1k,
            "billing_basis": billing_basis,
            "cost_credits": price_detail.get("cost_credits"),
            "margin_credits": price_detail.get("margin_credits"),
            "idempotent": False,
        }

    def consume_for_feature(
        self,
        account_id: UUID,
        feature_key: str,
        *,
        token_count: int,
        idempotency_key: str | None = None,
        model_id: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cached_input_tokens: int | None = None,
    ) -> dict:
        """扣减用户算力值，用于非消息上下文的公共 AI 功能调用。

        与 consume_for_message 不同，此方法默认不基于 message_id 做幂等去重，
        每次调用都会生成确定性/随机 id；当传入 idempotency_key 时基于其生成
        synthetic_id 复用 consume_for_message 的幂等去重逻辑。

        model_id/input_tokens/output_tokens/cached_input_tokens 透传给
        consume_for_message，使预扣即按模型售价精确计价（不再依赖 1:1 全局汇率）。
        """
        if token_count <= 0:
            return {"consumed": False, "reason": "no tokens", "token_count": 0}

        try:
            feature_config = (
                self.session.query(PublicAIFeatureConfig)
                .filter(PublicAIFeatureConfig.feature_key == feature_key)
                .one_or_none()
            )
        except Exception:
            feature_config = None
        if feature_config is not None and not bool(feature_config.billable):
            return {
                "consumed": False,
                "reason": "system_borne",
                "token_count": token_count,
            }

        import uuid

        if idempotency_key:
            synthetic_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{idempotency_key}:{feature_key}")
        else:
            synthetic_id = uuid.uuid4()
        return self.consume_for_message(
            account_id,
            synthetic_id,
            token_count=token_count,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
        )

    def adjust_credits(
        self,
        account_id: UUID,
        *,
        diff_credits: int,
        source: str,
        source_id,
        description: str = "",
    ) -> dict:
        """对账多退少补：diff>0 补扣、diff<0 退还。幂等：同 (source, source_id) 只执行一次。

        金额 = -diff_credits（退款为正、补扣为负），与 credit_transaction 扣费符号约定一致。
        """
        diff_credits = int(diff_credits or 0)
        if diff_credits == 0:
            return {"skipped": True, "reason": "zero_diff", "amount": 0}

        tid = str(source_id)
        existing = self.session.query(CreditTransaction).filter(
            CreditTransaction.source == source,
            CreditTransaction.source_id == tid,
            CreditTransaction.transaction_type == "adjust",
        ).one_or_none()
        if existing is not None:
            return {
                "id": str(existing.id),
                "amount": int(existing.amount or 0),
                "balance_after": int(existing.balance_after or 0),
                "reconciliation": True,
                "idempotent": True,
            }

        credit_account = self._get_credit_account_for_update(account_id)
        if credit_account is None:
            raise FailException("账户算力账户不存在")

        amount = -diff_credits
        # 退还（amount>0）：永久算力优先；补扣（amount<0）：配额→永久 顺序扣
        if amount > 0:
            # 退还统一进永久算力（不区分周期包，简化并可追溯）
            credit_account.permanent_credit = int(credit_account.permanent_credit or 0) + amount
        else:
            remaining = -amount
            membership = self._get_current_membership(account_id)
            used_quota = 0
            used_permanent = 0
            if membership is not None and membership.is_active and int(credit_account.quota_credit or 0) > 0:
                used_quota = min(int(credit_account.quota_credit), remaining)
                credit_account.quota_credit = int(credit_account.quota_credit or 0) - used_quota
                remaining -= used_quota
            if remaining > 0 and int(credit_account.permanent_credit or 0) > 0:
                used_permanent = min(int(credit_account.permanent_credit), remaining)
                credit_account.permanent_credit = int(credit_account.permanent_credit or 0) - used_permanent
                remaining -= used_permanent
            if remaining > 0:
                raise FailException("算力不足，无法完成对账补扣")

        credit_account.updated_at = self._now()
        transaction = CreditTransaction(
            account_id=account_id,
            amount=amount,
            balance_after=credit_account.available_tokens,
            transaction_type="adjust",
            source=source,
            source_id=tid,
            description=description or "对账多退少补",
        )
        self.session.add(transaction)
        return {
            "id": str(transaction.id),
            "amount": amount,
            "balance_after": credit_account.available_tokens,
            "reconciliation": True,
            "idempotent": False,
        }

    def _maybe_check_auto_renew(self, account_id: UUID) -> None:
        """消费后触发算力包余量自动续费检测；失败静默，不阻断主链路。"""
        try:
            from internal.service.auto_renewal_service import AutoRenewalService

            AutoRenewalService(session=self.session).check_credits_threshold(account_id)
        except Exception:
            return

    def _refresh_quota_if_due(self, credit_account: CreditAccount, membership: Membership | None) -> None:
        """订购日滚动周期刷新：会员有效期内，到达周期边界时把配额池回满（不结转）。

        仅在开启「按购买周期刷新」的会员套餐授予时写入锚点（quota_granted / quota_cycle_days / quota_reset_at）。
        过期会员不刷新，剩余额度保留待到期清理。
        """
        if membership is None or not membership.is_active:
            return
        reset_at = credit_account.quota_reset_at
        granted = int(credit_account.quota_granted or 0)
        cycle_days = int(credit_account.quota_cycle_days or 0)
        if reset_at is None or granted <= 0 or cycle_days <= 0:
            return
        now = self._now()
        while now >= reset_at:
            credit_account.quota_credit = granted
            credit_account.quota_reset_at = reset_at + timedelta(days=cycle_days)
            reset_at = credit_account.quota_reset_at

    def _apply_consume(self, credit_account: CreditAccount, membership: Membership | None, compute_units: int) -> dict:
        """按顺序扣减：套餐额度 → 永久算力。两者均 0 时 insufficient=True。"""
        remaining = compute_units
        quota_used = 0
        if membership is not None and membership.is_active and int(credit_account.quota_credit or 0) > 0:
            quota_used = min(int(credit_account.quota_credit), remaining)
            credit_account.quota_credit = int(credit_account.quota_credit or 0) - quota_used
            remaining -= quota_used
        permanent_used = 0
        if remaining > 0 and int(credit_account.permanent_credit or 0) > 0:
            permanent_used = min(int(credit_account.permanent_credit), remaining)
            credit_account.permanent_credit = int(credit_account.permanent_credit or 0) - permanent_used
            remaining -= permanent_used
        insufficient = remaining > 0
        return {
            "quota_used": quota_used,
            "permanent_used": permanent_used,
            "insufficient": insufficient,
            "reason": "credits_exhausted" if insufficient else None,
        }

    def _get_existing_message_consume(self, message_id: UUID) -> CreditTransaction | None:
        return (
            self.session.query(CreditTransaction)
            .filter(
                CreditTransaction.source == "message",
                CreditTransaction.source_id == message_id,
                CreditTransaction.transaction_type == "consume",
            )
            .one_or_none()
        )

    def _get_credit_account_for_update(self, account_id: UUID) -> CreditAccount | None:
        return (
            self.session.query(CreditAccount)
            .filter(CreditAccount.account_id == account_id)
            .with_for_update()
            .one_or_none()
        )

    def _get_current_membership(self, account_id: UUID) -> Membership | None:
        return (
            self.session.query(Membership)
            .filter(Membership.account_id == account_id)
            .order_by(Membership.expires_at.desc())
            .first()
        )

    @staticmethod
    def _build_consume_description(token_count: int, compute_units: int, result: dict, credits_per_1k: int = 1) -> str:
        total_used = result["quota_used"] + result["permanent_used"]
        rate_text = f"{credits_per_1k} 算力/1k token" if credits_per_1k != 1 else "1000 token=1 算力"
        if result["insufficient"]:
            return (
                f"模型调用消耗算力值：{token_count} token，应扣 {compute_units}，"
                f"套餐额度与永久算力均已耗尽仅扣减 {total_used}，请充值算力（{rate_text}）"
            )
        return f"模型调用消耗算力值：{token_count} token，扣减 {total_used}（{rate_text}）"