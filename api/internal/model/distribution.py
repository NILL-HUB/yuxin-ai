from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    UUID,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    text,
)

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ReferralCode(Base):
    __tablename__ = "referral_code"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_referral_code_id"),
        UniqueConstraint("account_id", name="uq_referral_code_account_id"),
        UniqueConstraint("code", name="uq_referral_code_code"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    code = Column(String(64), nullable=False)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class DistributionRelation(Base):
    __tablename__ = "distribution_relation"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_distribution_relation_id"),
        UniqueConstraint("invitee_account_id", name="uq_distribution_relation_invitee"),
        Index("distribution_relation_inviter_idx", "inviter_account_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    invitee_account_id = Column(UUID, nullable=False)
    inviter_account_id = Column(UUID, nullable=False)
    bound_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    source = Column(String(32), nullable=False, server_default=text("'register'::character varying"))
    updated_by = Column(UUID, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )


class BalanceAccount(Base):
    __tablename__ = "balance_account"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_balance_account_id"),
        UniqueConstraint("account_id", name="uq_balance_account_account_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    balance = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    total_recharged = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    total_commission = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    total_withdrawn = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    total_purchased = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    high_rate_locked = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class BalanceTransaction(Base):
    __tablename__ = "balance_transaction"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_balance_transaction_id"),
        Index("balance_transaction_account_created_idx", "account_id", "created_at"),
        UniqueConstraint(
            "account_id",
            "source",
            "source_id",
            "amount_type",
            name="uq_balance_transaction_account_source_type",
        ),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    balance_after = Column(Numeric(12, 2), nullable=False)
    amount_type = Column(String(32), nullable=False)
    rate = Column(Numeric(5, 2), nullable=True)
    source = Column(String(32), nullable=False, server_default=text("''::character varying"))
    source_id = Column(UUID, nullable=True)
    description = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_request"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_withdrawal_request_id"),
        Index("withdrawal_request_account_idx", "account_id"),
        Index("withdrawal_request_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    status = Column(String(32), nullable=False, server_default=text("'pending'::character varying"))
    reviewed_by = Column(UUID, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_note = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class PaymentProviderConfig(Base):
    __tablename__ = "payment_provider_config"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_payment_provider_config_id"),
        UniqueConstraint("provider", name="uq_payment_provider_config_provider"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    provider = Column(String(32), nullable=False)
    name = Column(String(64), nullable=False, server_default=text("''::character varying"))
    configs = Column(JSON, nullable=False, server_default=text("'{}'::json"))
    enabled = Column(Boolean, nullable=False, server_default=text("false"))
    updated_by = Column(UUID, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class PurchaseOrder(Base):
    __tablename__ = "purchase_order"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_purchase_order_id"),
        UniqueConstraint("order_no", name="uq_purchase_order_order_no"),
        Index("purchase_order_account_status_idx", "account_id", "status"),
        Index("purchase_order_status_idx", "status"),
        Index("purchase_order_source_idx", "order_source"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    order_no = Column(String(64), nullable=False)
    account_id = Column(UUID, nullable=False)
    plan_id = Column(UUID, nullable=False)
    plan_type = Column(String(32), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    pay_method = Column(String(32), nullable=False)
    order_source = Column(String(32), nullable=False, server_default=text("'normal'::character varying"))
    status = Column(String(32), nullable=False, server_default=text("'pending'::character varying"))
    transaction_id = Column(String(255), nullable=True)
    paid_at = Column(DateTime, nullable=True)
    refund_at = Column(DateTime, nullable=True)
    client_ip = Column(String(64), nullable=False, server_default=text("''::character varying"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )

    @property
    def is_paid(self) -> bool:
        return self.status == "paid"


class ReturnRequest(Base):
    __tablename__ = "return_request"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_return_request_id"),
        UniqueConstraint("order_id", name="uq_return_request_order_id"),
        Index("return_request_account_idx", "account_id"),
        Index("return_request_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    order_id = Column(UUID, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    reason = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    status = Column(String(32), nullable=False, server_default=text("'pending'::character varying"))
    reviewed_by = Column(UUID, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_note = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class AutoRenewal(Base):
    __tablename__ = "auto_renewal"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_auto_renewal_id"),
        Index("auto_renewal_account_idx", "account_id"),
        Index("auto_renewal_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    plan_id = Column(UUID, nullable=False)
    plan_type = Column(String(32), nullable=False)
    pay_method = Column(String(32), nullable=False, server_default=text("'balance'::character varying"))
    status = Column(String(32), nullable=False, server_default=text("'active'::character varying"))
    next_renew_at = Column(DateTime, nullable=True)
    last_renewed_at = Column(DateTime, nullable=True)
    renew_count = Column(BigInteger, nullable=False, server_default=text("0"))
    fail_count = Column(BigInteger, nullable=False, server_default=text("0"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )

    @property
    def is_active(self) -> bool:
        return self.status == "active"