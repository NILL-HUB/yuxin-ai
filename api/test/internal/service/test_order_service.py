from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from internal.exception import FailException, NotFoundException
from internal.model.billing import CreditAccount, CreditTransaction, Membership, Plan
from internal.model.distribution import AutoRenewal, BalanceAccount, PurchaseOrder
from internal.service.order_service import OrderService


def _gen_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


_MERCHANT_PRIVATE, _MERCHANT_PUBLIC = _gen_keypair()
_PLATFORM_PRIVATE, _PLATFORM_PUBLIC = _gen_keypair()
_API_V3_KEY = "0123456789abcdef0123456789abcdef"


def _wechat_notify_config():
    return {
        "app_id": "wx-test-appid",
        "mch_id": "1900000109",
        "serial_no": "ABC1234567",
        "private_key": _MERCHANT_PRIVATE,
        "api_v3_key": _API_V3_KEY,
        "platform_public_key": _PLATFORM_PUBLIC,
    }


def _wechat_callback(order_no, transaction_id, total_fen, trade_state="SUCCESS"):
    import base64
    import json

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    resource = {
        "out_trade_no": order_no,
        "transaction_id": transaction_id,
        "trade_state": trade_state,
        "amount": {"total": total_fen, "payer_total": total_fen, "currency": "CNY", "payer_currency": "CNY"},
    }
    nonce_bytes = b"abcdefghijkl"
    ciphertext = AESGCM(_API_V3_KEY.encode("utf-8")).encrypt(
        nonce_bytes, json.dumps(resource).encode("utf-8"), b"transaction"
    )
    body = json.dumps({
        "id": "evt-test",
        "event_type": "TRANSACTION.SUCCESS",
        "resource_type": "encrypt-resource",
        "resource": {
            "algorithm": "AEAD_AES_256_GCM",
            "ciphertext": base64.b64encode(ciphertext).decode("utf-8"),
            "nonce": base64.b64encode(nonce_bytes).decode("utf-8"),
            "associated_data": "transaction",
        },
    }).encode("utf-8")
    timestamp = "1680000000"
    callback_nonce = "callnonce123"
    canonical = f"{timestamp}\n{callback_nonce}\n{body.decode('utf-8')}\n"
    plat_key = serialization.load_pem_private_key(_PLATFORM_PRIVATE.encode("utf-8"), password=None)
    signature = base64.b64encode(
        plat_key.sign(canonical.encode("utf-8"), rsa_padding.PKCS1v15(), hashes.SHA256())
    ).decode("utf-8")
    headers = {
        "Wechatpay-Timestamp": timestamp,
        "Wechatpay-Nonce": callback_nonce,
        "Wechatpay-Signature": signature,
        "Wechatpay-Serial": "PLATFORM-SERIAL",
    }
    return body, headers


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None, count_result=0, first_result=None):
        self._one_or_none_result = one_or_none_result
        self._all_result = [] if all_result is None else all_result
        self._count_result = count_result
        self._first_result = first_result
        self.filters = []
        self.locked = False

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def order_by(self, *args, **kwargs):
        return self

    def with_for_update(self):
        self.locked = True
        return self

    def one_or_none(self):
        return self._one_or_none_result

    def first(self):
        return self._first_result

    def all(self):
        return self._all_result

    def count(self):
        return self._count_result

    def offset(self, _value):
        return self

    def limit(self, _value):
        return self


class _SessionStub:
    def __init__(self, queries=None, commit_error=None):
        self._queries = list(queries or [])
        self._commit_error = commit_error
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1
        if self._commit_error:
            raise self._commit_error

    def rollback(self):
        self.rollbacks += 1


class _BalanceStub:
    def __init__(self, balance=Decimal("100.00")):
        self.balance = balance
        self.credits = []
        self.debits = []

    def ensure_account(self, account_id):
        return BalanceAccount(account_id=account_id, balance=self.balance, high_rate_locked=False)

    def get_account(self, account_id):
        return None

    def credit(self, account_id, amount, *, source, source_id, amount_type, rate=None, description=""):
        self.credits.append({"account_id": account_id, "amount": amount, "source": source, "source_id": source_id, "amount_type": amount_type})
        return object()

    def debit(self, account_id, amount, *, source, source_id, amount_type, description=""):
        self.debits.append({"account_id": account_id, "amount": amount, "source": source, "source_id": source_id, "amount_type": amount_type})
        return object()


class _DistributionStub:
    def __init__(self):
        self.settles = []

    def settle_commission_for_order(self, account_id, order):
        self.settles.append({"account_id": account_id, "plan_type": order.plan_type, "order_id": order.id})


class _PaymentConfigStub:
    def __init__(self, enabled=False, config=None):
        self.enabled = enabled
        self._config = config

    def is_enabled(self, provider):
        return self.enabled

    def get(self, provider):
        return self._config

    def decrypt_payload(self, config):
        return config or {}


def _plan(plan_type="membership", price="100.00", duration_days=30, grant=100):
    return Plan(id=uuid4(), code="pro", name="Pro", plan_type=plan_type, price=price, duration_days=duration_days, grant_token_credits=grant, status="active")


def _membership(account_id):
    return Membership(
        account_id=account_id,
        plan_id=uuid4(),
        status="active",
        started_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=10),
        source="order",
        source_id=uuid4(),
    )


def _credit_account(account_id, quota=0, permanent=0):
    return CreditAccount(account_id=account_id, quota_credit=quota, permanent_credit=permanent, total_granted=0, total_consumed=0)


def make_service(session, balance_stub, distribution_stub, payment_stub):
    return OrderService(
        session=session,
        balance_service=balance_stub,
        distribution_service=distribution_stub,
        payment_config_service=payment_stub,
    )


class TestCreateOrder:
    def test_create_and_handle_should_pay_balance_in_one_call(self):
        account_id = uuid4()
        plan = _plan()
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),     # create_order: plan
            _QueryStub(first_result=None),           # order_no 唯一性
            _QueryStub(one_or_none_result=plan),     # confirm_paid 履约查套餐
            _QueryStub(first_result=None),           # membership
            _QueryStub(one_or_none_result=None),     # credit account
        ])
        balance_stub = _BalanceStub(balance=Decimal("100.00"))
        distribution_stub = _DistributionStub()
        service = make_service(session, balance_stub, distribution_stub, _PaymentConfigStub())

        order, payment_params = service.create_and_handle(account_id, plan.id, "balance")

        assert order.status == "paid"
        assert payment_params is None
        assert len(balance_stub.debits) == 1
        assert len(distribution_stub.settles) == 1

    def test_create_order_should_validate_plan_and_online_method(self):
        plan = _plan()
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),
            _QueryStub(first_result=None),   # order_no 唯一性检查
        ])
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub(enabled=False))
        order = service.create_order(uuid4(), plan.id, "balance")
        assert order.status == "pending"
        assert order.pay_method == "balance"
        assert order.plan_type == "membership"
        assert float(order.amount) == 100.00
        assert order.order_no.startswith("PO")

    def test_create_order_should_reject_online_when_channel_disabled(self):
        plan = _plan()
        session = _SessionStub([_QueryStub(one_or_none_result=plan)])
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub(enabled=False))
        with pytest.raises(FailException, match="支付渠道暂未开通"):
            service.create_order(uuid4(), plan.id, "wechatpay")

    def test_create_order_should_reject_online_method_for_balance_plan(self):
        plan = _plan(plan_type="balance", price="50.00")
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),
            _QueryStub(first_result=None),
        ])
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub(enabled=True))
        with pytest.raises(FailException, match="仅支持在线支付"):
            service.create_order(uuid4(), plan.id, "balance")

    def test_create_order_should_allow_online_when_channel_enabled(self):
        plan = _plan()
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),
            _QueryStub(first_result=None),
        ])
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub(enabled=True))
        order = service.create_order(uuid4(), plan.id, "alipay")
        assert order.pay_method == "alipay"

    def test_create_order_should_reject_when_purchase_limit_reached(self):
        account_id = uuid4()
        plan = _plan(price="0.00", duration_days=7, grant=1000)
        plan.purchase_limit = 1
        plan.purchase_limit_period = "all"
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),
            _QueryStub(count_result=1),   # 限购统计：累计已有 1 笔 paid
        ])
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub())

        with pytest.raises(FailException, match="限购"):
            service.create_order(account_id, plan.id, "balance")

    def test_create_order_should_allow_when_under_purchase_limit(self):
        account_id = uuid4()
        plan = _plan(price="0.00", duration_days=7, grant=1000)
        plan.purchase_limit = 1
        plan.purchase_limit_period = "all"
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),
            _QueryStub(count_result=0),   # 限购统计：尚无 paid
            _QueryStub(first_result=None),# order_no 唯一性
        ])
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub())

        order = service.create_order(account_id, plan.id, "balance")

        assert order.status == "pending"


class TestPaymentFlow:
    def test_pay_with_balance_should_debit_and_confirm(self):
        account_id = uuid4()
        plan = _plan()
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),     # create_order: plan
            _QueryStub(first_result=None),           # order_no 唯一性
            _QueryStub(one_or_none_result=plan),     # confirm_paid 履约查套餐
            _QueryStub(first_result=None),           # membership（无）
            _QueryStub(one_or_none_result=None),     # credit account（无）
        ])
        balance_stub = _BalanceStub(balance=Decimal("100.00"))
        distribution_stub = _DistributionStub()
        service = make_service(session, balance_stub, distribution_stub, _PaymentConfigStub())
        order = service.create_order(account_id, plan.id, "balance")
        order = service.pay_with_balance(order)

        assert order.status == "paid"
        assert order.paid_at is not None
        assert len(balance_stub.debits) == 1
        assert balance_stub.debits[0]["amount_type"] == "purchase"
        assert len(distribution_stub.settles) == 1
        assert distribution_stub.settles[0]["plan_type"] == "membership"
        assert any(isinstance(item, Membership) for item in session.added)
        assert any(isinstance(item, CreditTransaction) for item in session.added)

    def test_membership_cycle_pay_should_seed_quota_refresh_anchor(self):
        account_id = uuid4()
        plan = _plan(plan_type="membership", price="100.00", grant=50000, duration_days=30)
        plan.quota_refresh_period = "cycle"
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),     # create_order: plan
            _QueryStub(first_result=None),           # order_no 唯一性
            _QueryStub(one_or_none_result=plan),     # confirm_paid 履约查套餐
            _QueryStub(first_result=None),           # membership（无）
            _QueryStub(one_or_none_result=None),     # credit account（无）
        ])
        service = make_service(session, _BalanceStub(balance=Decimal("100.00")), _DistributionStub(), _PaymentConfigStub())

        order = service.create_order(account_id, plan.id, "balance")
        order = service.pay_with_balance(order)

        assert order.status == "paid"
        credit = next(item for item in session.added if isinstance(item, CreditAccount))
        assert credit.quota_granted == 50000
        assert credit.quota_cycle_days == 30
        assert credit.quota_credit == 50000           # cycle：新周期回满（不叠加）
        assert credit.quota_reset_at is not None

    def test_pay_with_balance_should_reject_insufficient(self):
        account_id = uuid4()
        plan = _plan()
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),
            _QueryStub(first_result=None),
        ])
        service = make_service(session, _BalanceStub(balance=Decimal("1.00")), _DistributionStub(), _PaymentConfigStub())
        order = service.create_order(account_id, plan.id, "balance")
        with pytest.raises(FailException, match="余额不足"):
            service.pay_with_balance(order)

    def test_confirm_paid_should_be_idempotent(self):
        account_id = uuid4()
        order = PurchaseOrder(account_id=account_id, plan_type="membership", amount="100.00", status="paid")
        session = _SessionStub()
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub())
        assert service.confirm_paid(order) is order

    def test_online_order_should_raise_channel_not_configured_when_stub(self):
        account_id = uuid4()
        plan = _plan()
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),
            _QueryStub(first_result=None),
        ])
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub(enabled=True))
        order = service.create_order(account_id, plan.id, "wechatpay")
        with pytest.raises(FailException, match="渠道未完成配置"):
            service.pay_with_online(order)

    def test_balance_type_order_confirm_should_recharge_balance_without_commission(self):
        account_id = uuid4()
        plan = _plan(plan_type="balance", price="50.00")
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),
            _QueryStub(first_result=None),
        ])
        balance_stub = _BalanceStub()
        distribution_stub = _DistributionStub()
        service = make_service(session, balance_stub, distribution_stub, _PaymentConfigStub(enabled=True))
        order = service.create_order(account_id, plan.id, "alipay")
        order = service.confirm_paid(order, transaction_id="T123")
        assert order.status == "paid"
        assert order.transaction_id == "T123"
        assert len(balance_stub.credits) == 1
        assert balance_stub.credits[0]["amount_type"] == "recharge"
        assert distribution_stub.settles == []

    def test_mock_paid_should_confirm_with_mock_transaction(self):
        account_id = uuid4()
        plan = _plan(plan_type="credits", price="60.00", grant=1000)
        order = PurchaseOrder(account_id=account_id, order_no="PO-M", plan_type="credits", amount="60.00", status="pending")
        session = _SessionStub([
            _QueryStub(one_or_none_result=order),     # _get_order
            _QueryStub(one_or_none_result=plan),      # _fulfill_rights 查套餐
            _QueryStub(one_or_none_result=None),      # credit account
        ])
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub())

        order = service.mock_paid("PO-M")

        assert order.status == "paid"
        assert order.transaction_id.startswith("MOCK-")
        assert any(isinstance(item, CreditAccount) for item in session.added)

    def test_balance_pay_should_skip_debit_for_zero_amount(self):
        account_id = uuid4()
        plan = _plan(plan_type="membership", price="0.00", grant=1000, duration_days=7)
        order = PurchaseOrder(
            account_id=account_id,
            order_no="PO-FREE",
            plan_id=plan.id,
            plan_type="membership",
            amount="0.00",
            pay_method="balance",
            order_source="normal",
            status="pending",
        )
        balance_stub = _BalanceStub()
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),       # _fulfill_rights 查套餐
            _QueryStub(first_result=None),             # membership
            _QueryStub(one_or_none_result=None),       # credit account
        ])
        service = make_service(session, balance_stub, _DistributionStub(), _PaymentConfigStub())

        order = service.pay_with_balance(order)

        assert order.status == "paid"
        assert balance_stub.debits == []
        assert any(isinstance(item, CreditAccount) for item in session.added)

    def test_cancel_should_only_close_pending(self):
        account_id = uuid4()
        pending = PurchaseOrder(account_id=account_id, order_no="PO1", plan_type="membership", amount="100.00", status="pending")
        session = _SessionStub([_QueryStub(one_or_none_result=pending)])
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub())
        order = service.cancel("PO1", account_id)
        assert order.status == "closed"

        paid = PurchaseOrder(account_id=account_id, order_no="PO2", plan_type="membership", amount="100.00", status="paid")
        session = _SessionStub([_QueryStub(one_or_none_result=paid)])
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub())
        with pytest.raises(FailException, match="仅待支付"):
            service.cancel("PO2", account_id)

    def test_notify_should_confirm_paid_and_idempotent_on_repeat(self):
        account_id = uuid4()
        plan = _plan()
        order = PurchaseOrder(account_id=account_id, order_no="PO-N-1", plan_type="membership", amount="100.00", status="pending", plan_id=plan.id)
        body, headers = _wechat_callback("PO-N-1", "TX1", 10000)
        session = _SessionStub([
            _QueryStub(one_or_none_result=order),
            _QueryStub(one_or_none_result=plan),   # _fulfill_rights 查套餐
            _QueryStub(first_result=None),         # membership
            _QueryStub(one_or_none_result=None),   # credit account
            _QueryStub(one_or_none_result=plan),   # _maybe_enable_auto_renewal 查套餐
            _QueryStub(one_or_none_result=order),
        ])
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub(enabled=True, config=_wechat_notify_config()))

        result = service.handle_notify("wechatpay", body, headers)
        assert result == {"success": True, "order_no": "PO-N-1"}
        assert order.status == "paid"
        assert order.transaction_id == "TX1"

        result2 = service.handle_notify("wechatpay", body, headers)
        assert result2 == {"success": True, "order_no": "PO-N-1"}
        assert order.transaction_id == "TX1"

    def test_notify_should_reject_invalid_payload(self):
        account_id = uuid4()
        session = _SessionStub([])
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub(enabled=True, config=_wechat_notify_config()))
        with pytest.raises(FailException, match="验签失败"):
            service.handle_notify("wechatpay", {})


class TestOrderQueries:
    def test_get_order_not_found(self):
        session = _SessionStub([_QueryStub(one_or_none_result=None)])
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub())
        with pytest.raises(NotFoundException, match="订单不存在"):
            service.get_order("PO-X", uuid4())

    def test_list_orders_should_return_pagination(self):
        account_id = uuid4()
        order = PurchaseOrder(account_id=account_id, order_no="PO1", plan_type="membership", amount="100.00", status="paid")
        session = _SessionStub([
            _QueryStub(count_result=1, all_result=[order]),
        ])
        service = make_service(session, _BalanceStub(), _DistributionStub(), _PaymentConfigStub())
        result = service.list_orders(account_id, 1, 20)
        assert result["list"][0]["order_no"] == "PO1"
        assert result["paginator"]["total_record"] == 1


class TestAutoRenewalDefault:
    def test_membership_auto_renew_plan_should_create_active_renewal_after_pay(self):
        account_id = uuid4()
        plan = _plan(plan_type="membership", price="100.00", grant=50000, duration_days=30)
        plan.auto_renew_default = True
        plan.auto_renew_threshold_days = 2
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),     # create_order: plan
            _QueryStub(first_result=None),           # order_no 唯一性
            _QueryStub(one_or_none_result=plan),     # _fulfill_rights 查套餐
            _QueryStub(first_result=None),           # membership（新建）
            _QueryStub(one_or_none_result=None),     # credit account
            _QueryStub(one_or_none_result=plan),     # _maybe_enable_auto_renewal 查套餐
            _QueryStub(one_or_none_result=None),     # existing AutoRenewal（无）
            _QueryStub(first_result=_membership(account_id)),  # _membership_next_renew
        ])
        service = make_service(session, _BalanceStub(balance=Decimal("100.00")), _DistributionStub(), _PaymentConfigStub())

        order = service.create_order(account_id, plan.id, "balance")
        order = service.pay_with_balance(order)

        assert order.status == "paid"
        renewal = next(item for item in session.added if isinstance(item, AutoRenewal))
        assert renewal.account_id == account_id
        assert renewal.plan_id == plan.id
        assert renewal.status == "active"
        assert renewal.pay_method == "balance"
        assert renewal.next_renew_at is not None

    def test_auto_renew_default_false_should_not_create_renewal(self):
        account_id = uuid4()
        plan = _plan(plan_type="membership", price="100.00", grant=50000, duration_days=30)
        plan.auto_renew_default = False
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),     # create_order: plan
            _QueryStub(first_result=None),           # order_no 唯一性
            _QueryStub(one_or_none_result=plan),     # _fulfill_rights 查套餐
            _QueryStub(first_result=None),           # membership（新建）
            _QueryStub(one_or_none_result=None),     # credit account
            _QueryStub(one_or_none_result=plan),     # _maybe_enable_auto_renewal 查套餐
        ])
        service = make_service(session, _BalanceStub(balance=Decimal("100.00")), _DistributionStub(), _PaymentConfigStub())

        order = service.create_order(account_id, plan.id, "balance")
        order = service.pay_with_balance(order)

        assert order.status == "paid"
        assert all(not isinstance(item, AutoRenewal) for item in session.added)

    def test_auto_renew_plan_should_not_duplicate_when_active_renewal_exists(self):
        account_id = uuid4()
        plan = _plan(plan_type="membership", price="100.00", grant=50000, duration_days=30)
        plan.auto_renew_default = True
        existing = AutoRenewal(
            account_id=account_id,
            plan_id=plan.id,
            plan_type="membership",
            pay_method="balance",
            status="active",
        )
        session = _SessionStub([
            _QueryStub(one_or_none_result=plan),     # create_order: plan
            _QueryStub(first_result=None),           # order_no 唯一性
            _QueryStub(one_or_none_result=plan),     # _fulfill_rights 查套餐
            _QueryStub(first_result=None),           # membership（新建）
            _QueryStub(one_or_none_result=None),     # credit account
            _QueryStub(one_or_none_result=plan),     # _maybe_enable_auto_renewal 查套餐
            _QueryStub(one_or_none_result=existing), # existing ActiveRenewal（active）
        ])
        service = make_service(session, _BalanceStub(balance=Decimal("100.00")), _DistributionStub(), _PaymentConfigStub())

        order = service.create_order(account_id, plan.id, "balance")
        order = service.pay_with_balance(order)

        assert order.status == "paid"
        assert all(not isinstance(item, AutoRenewal) for item in session.added)


class TestPaymentConfigService:
    def test_upsert_and_sanitize_should_hide_secret(self):
        from internal.service.payment_config_service import PaymentConfigService

        session = _SessionStub([_QueryStub(one_or_none_result=None)])
        service = PaymentConfigService(session=session)
        config = service.upsert("wechatpay", "微信支付", {"app_id": "wx123", "mch_id": "secret_mch", "mch_key": "very-secret-key"})
        assert config.configs["app_id"] == "wx123"
        assert config.configs["mch_id"].startswith("gAAAAA") is True  # Fernet token 特征前缀
        assert "very-secret-key" not in str(config.configs)