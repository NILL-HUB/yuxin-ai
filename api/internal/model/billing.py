from datetime import UTC, datetime
from decimal import Decimal
import json

from sqlalchemy import BigInteger, Column, DateTime, Index, Numeric, PrimaryKeyConstraint, String, UUID, text

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Plan(db.Model):
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
    duration_days = Column(BigInteger, nullable=False, server_default=text("0"))
    grant_token_credits = Column(BigInteger, nullable=False, server_default=text("0"))
    price = Column(Numeric(10, 2), nullable=False, server_default=text("0.00"))
    status = Column(String(64), nullable=False, server_default=text("'active'::character varying"))
    sort_order = Column(BigInteger, nullable=False, server_default=text("0"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    @property
    def is_active(self) -> bool:
        return self.status == "active"


class PlanEntitlement(db.Model):
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


class Membership(db.Model):
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


class CreditAccount(db.Model):
    __tablename__ = "credit_account"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_credit_account_id"),
        Index("credit_account_account_id_idx", "account_id", unique=True),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    balance = Column(BigInteger, nullable=False, server_default=text("0"))
    total_granted = Column(BigInteger, nullable=False, server_default=text("0"))
    total_consumed = Column(BigInteger, nullable=False, server_default=text("0"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    @property
    def available_tokens(self) -> int:
        return int(self.balance or 0)


class CreditTransaction(db.Model):
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


class RedeemCodeBatch(db.Model):
    __tablename__ = "redeem_code_batch"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_redeem_code_batch_id"),
        Index("redeem_code_batch_plan_id_idx", "plan_id"),
        Index("redeem_code_batch_only_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    name = Column(String(255), nullable=False)
    plan_id = Column(UUID, nullable=False)
    quantity = Column(BigInteger, nullable=False)
    status = Column(String(64), nullable=False, server_default=text("'active'::character varying"))
    expires_at = Column(DateTime, nullable=True)
    disabled_at = Column(DateTime, nullable=True)
    created_by = Column(UUID, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class RedeemCode(db.Model):
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
