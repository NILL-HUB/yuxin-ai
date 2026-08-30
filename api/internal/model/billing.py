from datetime import UTC, datetime
from decimal import Decimal
import json

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, Integer, Numeric, PrimaryKeyConstraint, String, Text, UUID, text
from sqlalchemy.dialects.postgresql import JSONB

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Plan(Base):
    __tablename__ = "plan"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_plan_id"),
        Index("plan_code_idx", "code", unique=True),
        Index("plan_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    code = Column(String(128), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    plan_type = Column(String(32), nullable=False, server_default=text("'membership'::character varying"))
    duration_days = Column(BigInteger, nullable=False, server_default=text("0"))
    grant_token_credits = Column(BigInteger, nullable=False, server_default=text("0"))
    auto_renew_threshold_percent = Column(BigInteger, nullable=False, server_default=text("5"))
    auto_renew_threshold_days = Column(BigInteger, nullable=False, server_default=text("1"))
    purchase_limit = Column(BigInteger, nullable=False, server_default=text("0"))
    purchase_limit_period = Column(String(16), nullable=False, server_default=text("'none'::character varying"))
    quota_refresh_period = Column(String(16), nullable=False, server_default=text("'none'::character varying"))
    auto_renew_default = Column(Boolean, nullable=False, server_default=text("false"))
    price = Column(Numeric(10, 2), nullable=False, server_default=text("0.00"))
    status = Column(String(64), nullable=False, server_default=text("'active'::character varying"))
    sort_order = Column(BigInteger, nullable=False, server_default=text("0"))
    deleted_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class BillingConfig(Base):
    __tablename__ = "billing_config"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_billing_config_id"),
        Index("billing_config_code_idx", "code", unique=True),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    code = Column(String(64), nullable=False)
    value_numeric = Column(Numeric(12, 6), nullable=False, server_default=text("0"))
    # 字符串配置值（文本/JSON 字符串）
    value_text = Column(Text, nullable=False, server_default=text("''"))
    description = Column(String(255), nullable=False, server_default=text("''::character varying"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class PlanEntitlement(Base):
    __tablename__ = "plan_entitlement"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_plan_entitlement_id"),
        Index("plan_entitlement_plan_feature_idx", "plan_id", "feature_key", unique=True),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    plan_id = Column(UUID, nullable=False)
    feature_key = Column(String(128), nullable=False)
    feature_value = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    value_type = Column(String(64), nullable=False, server_default=text("'string'::character varying"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    @property
    def parsed_value(self):
        if self.value_type == "number":
            return int(self.feature_value)
        if self.value_type == "decimal":
            return Decimal(self.feature_value)
        if self.value_type == "boolean":
            return self.feature_value.lower() == "true"
        if self.value_type == "json":
            return json.loads(self.feature_value or "{}")
        return self.feature_value


class Membership(Base):
    __tablename__ = "membership"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_membership_id"),
        Index("membership_account_status_idx", "account_id", "status"),
        Index("membership_account_expires_idx", "account_id", "expires_at"),
        Index("membership_source_idx", "source", "source_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    plan_id = Column(UUID, nullable=False)
    status = Column(String(64), nullable=False, server_default=text("'active'::character varying"))
    started_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    expires_at = Column(DateTime, nullable=False)
    source = Column(String(64), nullable=False, server_default=text("''::character varying"))
    source_id = Column(UUID, nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    @property
    def is_active(self) -> bool:
        return self.status == "active" and self.expires_at is not None and self.expires_at >= _utcnow_naive()


class CreditAccount(Base):
    __tablename__ = "credit_account"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_credit_account_id"),
        Index("credit_account_account_id_idx", "account_id", unique=True),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    permanent_credit = Column(BigInteger, nullable=False, server_default=text("0"))
    quota_credit = Column(BigInteger, nullable=False, server_default=text("0"))
    quota_granted = Column(BigInteger, nullable=False, server_default=text("0"))
    quota_cycle_days = Column(BigInteger, nullable=False, server_default=text("0"))
    quota_reset_at = Column(DateTime, nullable=True)
    total_granted = Column(BigInteger, nullable=False, server_default=text("0"))
    total_consumed = Column(BigInteger, nullable=False, server_default=text("0"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    @property
    def available_tokens(self) -> int:
        return int(self.permanent_credit or 0) + int(self.quota_credit or 0)


class CreditTransaction(Base):
    __tablename__ = "credit_transaction"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_credit_transaction_id"),
        Index("credit_transaction_account_created_idx", "account_id", "created_at"),
        Index("credit_transaction_source_idx", "source", "source_id"),
        Index("credit_transaction_source_type_unique_idx", "source", "source_id", "transaction_type", unique=True),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    amount = Column(BigInteger, nullable=False)
    balance_after = Column(BigInteger, nullable=False)
    transaction_type = Column(String(64), nullable=False)
    source = Column(String(64), nullable=False, server_default=text("''::character varying"))
    source_id = Column(UUID, nullable=True)
    description = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class RedeemCodeBatch(Base):
    __tablename__ = "redeem_code_batch"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_redeem_code_batch_id"),
        Index("redeem_code_batch_plan_id_idx", "plan_id"),
        Index("redeem_code_batch_only_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    name = Column(String(255), nullable=False)
    description = Column(String(500), nullable=False, server_default=text("''::character varying"))
    plan_id = Column(UUID, nullable=False)
    quantity = Column(BigInteger, nullable=False)
    status = Column(String(64), nullable=False, server_default=text("'active'::character varying"))
    expires_at = Column(DateTime, nullable=True)
    disabled_at = Column(DateTime, nullable=True)
    created_by = Column(UUID, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class RedeemCode(Base):
    __tablename__ = "redeem_code"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_redeem_code_id"),
        Index("redeem_code_hash_idx", "code_hash", unique=True),
        Index("redeem_code_batch_status_idx", "batch_id", "status"),
        Index("redeem_code_redeemed_by_idx", "redeemed_by"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    batch_id = Column(UUID, nullable=True)
    plan_id = Column(UUID, nullable=False)
    code_hash = Column(String(255), nullable=False)
    code_mask = Column(String(64), nullable=False)
    code_encrypted = Column(String(1024), nullable=True)
    status = Column(String(64), nullable=False, server_default=text("'unused'::character varying"))
    redeemed_by = Column(UUID, nullable=True)
    redeemed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    disabled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    @property
    def is_redeemable(self) -> bool:
        if self.status != "unused":
            return False
        if self.disabled_at is not None:
            return False
        if self.expires_at is not None and self.expires_at < _utcnow_naive():
            return False
        return True


class BillingUsageEvent(Base):
    __tablename__ = "billing_usage_event"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_billing_usage_event_id"),
        Index("billing_usage_event_task_idx", "task_id"),
        Index("billing_usage_event_model_idx", "model_id"),
        Index("billing_usage_event_created_idx", "created_at"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    # task_id: 对账聚合单元键（message.id / 编排 task_id）
    task_id = Column(String(128), nullable=False, server_default=text("''::character varying"))
    model_id = Column(String(64), nullable=True)
    source_type = Column(String(64), nullable=False, server_default=text("''::character varying"))
    input_tokens = Column(Integer, nullable=False, server_default=text("0"))
    # 缓存命中输入 token 数
    cached_input_tokens = Column(Integer, nullable=False, server_default=text("0"))
    # 计费档位：peak / valley / flat
    price_tier = Column(String(16), nullable=False, server_default=text("''"))
    # 计费时点（用于峰谷时段判定）
    moment = Column(DateTime, nullable=True)
    output_tokens = Column(Integer, nullable=False, server_default=text("0"))
    # billing_basis: provider_usage / tiktoken_estimate
    billing_basis = Column(String(64), nullable=False, server_default=text("''::character varying"))
    # is_estimated: 真实 usage 缺失、用估算兜底时为 true
    is_estimated = Column(Boolean, nullable=False, server_default=text("false"))
    estimated_credits = Column(Integer, nullable=False, server_default=text("0"))
    actual_credits = Column(Integer, nullable=False, server_default=text("0"))
    cost_credits = Column(Integer, nullable=False, server_default=text("0"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class BillingReconciliation(Base):
    __tablename__ = "billing_reconciliation"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_billing_reconciliation_id"),
        Index("billing_reconciliation_task_idx", "task_id", unique=True),
        Index("billing_reconciliation_account_idx", "account_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    task_id = Column(String(128), nullable=False, server_default=text("''::character varying"))
    account_id = Column(UUID, nullable=False)
    # 售价算力
    estimated_credits = Column(Integer, nullable=False, server_default=text("0"))
    actual_credits = Column(Integer, nullable=False, server_default=text("0"))
    # diff = actual - estimated（正=补扣、负=退还）
    diff_credits = Column(Integer, nullable=False, server_default=text("0"))
    # 成本算力（对账/毛利用）
    cost_credits = Column(Integer, nullable=False, server_default=text("0"))
    # 金额成本（人民币，用于报表与汇率敏感度）
    cost_amount = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    status = Column(String(32), nullable=False, server_default=text("'settled'::character varying"))
    # 告警标记列表：["ratio_deviation","negative_margin"] JSONB
    alert_flags = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    settled_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
