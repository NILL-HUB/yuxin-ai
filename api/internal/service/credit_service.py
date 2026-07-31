import math
from datetime import UTC, datetime
from uuid import UUID

from internal.extension.database_extension import db
from internal.model.billing import CreditAccount, CreditTransaction


class CreditService:
    TOKENS_PER_COMPUTE_UNIT = 1000

    def __init__(self, session=None):
        self.session = session or db.session

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @classmethod
    def compute_units_from_tokens(cls, token_count: int) -> int:
        token_count = int(token_count or 0)
        if token_count <= 0:
            return 0
        return math.ceil(token_count / cls.TOKENS_PER_COMPUTE_UNIT)

    def consume_for_message(self, account_id: UUID, message_id: UUID, *, token_count: int) -> dict:
        compute_units = self.compute_units_from_tokens(token_count)
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
                "idempotent": True,
            }

        credit_account = self._get_credit_account_for_update(account_id)
        if credit_account is None:
            credit_account = CreditAccount(account_id=account_id, balance=0, total_granted=0, total_consumed=0)
            self.session.add(credit_account)

        before_balance = int(credit_account.balance or 0)
        actual_compute_units = min(before_balance, compute_units)
        credit_account.balance = before_balance - actual_compute_units
        credit_account.total_consumed = int(credit_account.total_consumed or 0) + actual_compute_units
        credit_account.updated_at = self._now()
        insufficient = actual_compute_units < compute_units
        transaction = CreditTransaction(
            account_id=account_id,
            amount=-actual_compute_units,
            balance_after=credit_account.balance,
            transaction_type="consume",
            source="message",
            source_id=message_id,
            description=self._build_consume_description(token_count, compute_units, actual_compute_units, insufficient),
        )
        self.session.add(transaction)
        return {
            "id": str(transaction.id),
            "amount": -actual_compute_units,
            "balance_after": credit_account.balance,
            "compute_units": compute_units,
            "actual_compute_units": actual_compute_units,
            "token_count": int(token_count or 0),
            "insufficient": insufficient,
            "idempotent": False,
        }

    def consume_for_feature(
        self,
        account_id: UUID,
        feature_key: str,
        *,
        token_count: int,
        idempotency_key: str | None = None,
    ) -> dict:
        """扣减用户额度，用于非消息上下文的公共 AI 功能调用。

        与 consume_for_message 不同，此方法默认不基于 message_id 做幂等去重，
        每次调用都生成新的随机 ID，确保每次 LLM 调用都扣费。

        当传入 idempotency_key 时，会基于其生成确定性 synthetic_id，从而复用
        consume_for_message 的幂等去重逻辑，避免重试导致重复扣费。

        Args:
            account_id: 用户账户 ID
            feature_key: 公共 AI 功能标识（如 "prompt_optimization"）
            token_count: 本次 LLM 调用的总 token 数
            idempotency_key: 可选幂等键，传入时基于其生成确定性 synthetic_id 做去重

        Returns:
            与 consume_for_message 相同格式的字典
        """
        if token_count <= 0:
            return {"consumed": False, "reason": "no tokens", "token_count": 0}

        # 生成合成 message_id 用于复用 consume_for_message 的逻辑
        import uuid

        if idempotency_key:
            synthetic_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{idempotency_key}:{feature_key}")
        else:
            synthetic_id = uuid.uuid4()
        return self.consume_for_message(account_id, synthetic_id, token_count=token_count)

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

    @staticmethod
    def _build_consume_description(token_count: int, compute_units: int, actual_compute_units: int, insufficient: bool) -> str:
        if insufficient:
            return f"模型调用消耗算力值：{token_count} token，应扣 {compute_units}，余额不足实际扣减 {actual_compute_units}"
        return f"模型调用消耗算力值：{token_count} token，扣减 {actual_compute_units}"
