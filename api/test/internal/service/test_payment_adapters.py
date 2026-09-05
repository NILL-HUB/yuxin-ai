"""支付适配器单元测试：RSA 签名/验签、微信回调解密验签、支付宝下单/验签。"""
import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
from cryptography.hazmat.primitives.asymmetric import rsa


def _gen_keypair():
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


MERCHANT_PRIVATE, MERCHANT_PUBLIC = _gen_keypair()
PLATFORM_PRIVATE, PLATFORM_PUBLIC = _gen_keypair()


class _OrderStub:
    def __init__(self, order_no="PO202601010001", amount="60.00", plan_type="credits"):
        self.order_no = order_no
        self.amount = amount
        self.plan_type = plan_type


class TestWechatPay:
    def make_config(self):
        return {
            "app_id": "wx-test-appid",
            "mch_id": "1900000109",
            "serial_no": "ABC1234567",
            "private_key": MERCHANT_PRIVATE,
            "api_v3_key": "0123456789abcdef0123456789abcdef",
            "platform_public_key": PLATFORM_PUBLIC,
            "notify_url": "https://example.com/api/payments/notify/wechat",
        }

    def test_rsa_sign_verify_roundtrip(self):
        from internal.service.payment.wechat_pay import rsa_sign, rsa_verify

        message = "POST\n/v3/pay/transactions/native\n1680000000\ntest\n{}\n"
        signature = rsa_sign(MERCHANT_PRIVATE, message)
        assert rsa_verify(MERCHANT_PUBLIC, message, signature) is True
        assert rsa_verify(MERCHANT_PUBLIC, message + "tampered", signature) is False

    def test_missing_config_raises(self):
        from internal.exception import FailException
        from internal.service.payment.gateway_base import PaymentChannelNotConfigured
        from internal.service.payment.wechat_pay import WechatPayAdapter

        adapter = WechatPayAdapter({})
        with pytest.raises(PaymentChannelNotConfigured):
            adapter.create_payment(_OrderStub())

    def test_create_payment_requires_channel_config(self):
        from internal.service.payment.wechat_pay import WechatPayAdapter

        adapter = WechatPayAdapter(self.make_config())
        with pytest.raises(Exception):
            # 无网络环境下会请求微信 API 失败，但必须先通过配置校验
            adapter.create_payment(_OrderStub())

    def test_verify_callback_decrypt_and_verify(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        from internal.service.payment.wechat_pay import WechatPayAdapter

        config = self.make_config()
        resource = {
            "mchid": config["mch_id"],
            "out_trade_no": _OrderStub().order_no,
            "transaction_id": "420000123420250101000000",
            "trade_state": "SUCCESS",
            "amount": {"total": 6000, "payer_total": 6000, "currency": "CNY", "payer_currency": "CNY"},
        }
        nonce_bytes = b"abcdefghijkl"
        aesgcm = AESGCM(config["api_v3_key"].encode("utf-8"))
        ciphertext = aesgcm.encrypt(
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
        plat_key = serialization.load_pem_private_key(PLATFORM_PRIVATE.encode("utf-8"), password=None)
        signature = base64.b64encode(
            plat_key.sign(canonical.encode("utf-8"), rsa_padding.PKCS1v15(), hashes.SHA256())
        ).decode("utf-8")
        headers = {
            "Wechatpay-Timestamp": timestamp,
            "Wechatpay-Nonce": callback_nonce,
            "Wechatpay-Signature": signature,
            "Wechatpay-Serial": "PLATFORM-SERIAL",
        }
        result = WechatPayAdapter(config).verify_callback(body, headers)
        assert result["order_no"] == _OrderStub().order_no
        assert result["transaction_id"] == resource["transaction_id"]
        assert result["paid"] is True
        assert result["amount_fen"] == 6000

    def test_verify_callback_tampered_body_rejected(self):
        from internal.service.payment.wechat_pay import WechatPayAdapter

        config = self.make_config()
        body = json.dumps({"event_type": "TRANSACTION.SUCCESS"}).encode("utf-8")
        headers = {
            "Wechatpay-Timestamp": "1680000000",
            "Wechatpay-Nonce": "n",
            "Wechatpay-Signature": "bad",
        }
        with pytest.raises(Exception):
            WechatPayAdapter(config).verify_callback(body, headers)


class TestAlipay:
    def make_config(self):
        return {
            "app_id": "2021003122699999",
            "private_key": MERCHANT_PRIVATE,
            "ali_public_key": MERCHANT_PUBLIC,
            "notify_url": "https://example.com/api/payments/notify/alipay",
            "return_url": "https://example.com/membership",
        }

    def test_create_payment_builds_signed_url(self):
        from internal.service.payment.alipay import AlipayAdapter

        params = AlipayAdapter(self.make_config()).create_payment(_OrderStub())
        assert params["provider"] == "alipay"
        assert params["pay_type"] == "page"
        assert "gateway.do" in params["pay_url"]
        assert "PO202601010001" in params["pay_url"]
        assert "sign=" in params["pay_url"]
        assert params["amount"] == 60.0

    def test_verify_callback_signed_payload(self):
        from internal.service.payment.alipay import AlipayAdapter, rsa2_sign, _sign_str

        config = self.make_config()
        payload = {
            "app_id": config["app_id"],
            "charset": "utf-8",
            "sign_type": "RSA2",
            "out_trade_no": "PO202601010001",
            "trade_no": "2026010122001400000500000000",
            "trade_status": "TRADE_SUCCESS",
            "total_amount": "60.00",
            "seller_id": "2088102146225135",
        }
        sign = rsa2_sign(config["private_key"], _sign_str(payload))
        payload["sign"] = sign
        result = AlipayAdapter(config).verify_callback(payload)
        assert result["order_no"] == "PO202601010001"
        assert result["transaction_id"] == payload["trade_no"]
        assert result["paid"] is True
        assert result["amount"] == 60.0

    def test_verify_callback_rejects_bad_sign(self):
        from internal.service.payment.alipay import AlipayAdapter

        config = self.make_config()
        payload = {
            "app_id": config["app_id"],
            "out_trade_no": "PO202601010001",
            "trade_status": "TRADE_SUCCESS",
            "total_amount": "60.00",
            "sign": "invalid-signature",
        }
        with pytest.raises(Exception):
            AlipayAdapter(config).verify_callback(payload)


class TestNormalization:
    def test_normalize_provider_alias(self):
        from internal.service.payment.gateway_base import normalize_provider

        assert normalize_provider("wechatpay") == "wechat"
        assert normalize_provider("wechat") == "wechat"
        assert normalize_provider("alipay") == "alipay"
        assert normalize_provider("ALIPAY ") == "alipay"

    def test_get_adapter_registry(self):
        from internal.service.payment.gateway_base import get_payment_adapter

        assert get_payment_adapter("wechat").provider == "wechat"
        assert get_payment_adapter("wechatpay").provider == "wechat"
        assert get_payment_adapter("alipay").provider == "alipay"