"""微信支付 V3 适配器（Native 扫码支付）。

配置项（管理端「系统配置-支付配置」）：
  app_id            微信开放平台 / 公众号 AppID（明文）
  mch_id            微信支付商户号（密文保存）
  serial_no         商户 API 证书序列号（密文保存）
  private_key       商户 API 私钥（PKCS8 PEM，密文保存）
  api_v3_key        APIv3 密钥（32 位，密文保存）
  platform_public_key 微信支付平台证书公钥（PEM，密文保存；可选，配置后回调将做完整验签）
  notify_url        支付结果通知地址（明文；不填则使用 PAY_NOTIFY_BASE_URL 拼接）
"""
import base64
import json
import os
import time
import uuid
from urllib.parse import quote

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from internal.exception import FailException
from internal.service.payment.protocol import PaymentChannelNotConfigured, PaymentGatewayProtocol

WECHAT_API_BASE = "https://api.mch.weixin.qq.com"
USER_AGENT = "yuxin-ai-payment/1.0"


def _load_private_key(pem: str):
    return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)


def _load_public_key(pem: str):
    return serialization.load_pem_public_key(pem.encode("utf-8"))


def rsa_sign(private_key_pem: str, message: str) -> str:
    key = _load_private_key(private_key_pem)
    signature = key.sign(message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("utf-8")


def rsa_verify(public_key_pem: str, message: str, signature_b64: str) -> bool:
    try:
        key = _load_public_key(public_key_pem)
        key.verify(
            base64.b64decode(signature_b64),
            message.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False


def _decrypt_resource(ciphertext_b64: str, nonce_b64: str, associated_data: str, api_v3_key: str) -> dict:
    aesgcm = AESGCM(api_v3_key.encode("utf-8"))
    plaintext = aesgcm.decrypt(
        base64.b64decode(nonce_b64),
        base64.b64decode(ciphertext_b64),
        associated_data.encode("utf-8"),
    )
    return json.loads(plaintext.decode("utf-8"))


def _authorization(method: str, url_path: str, body: str, config: dict) -> str:
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    canonical = f"{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n"
    signature = rsa_sign(config["private_key"], canonical)
    auth = (
        'WECHATPAY2-SHA256-RSA2048 mchid="{mchid}",nonce_str="{nonce}",'
        'signature="{signature}",timestamp="{timestamp}",serial_no="{serial_no}"'
    ).format(
        mchid=config["mch_id"],
        nonce=nonce,
        signature=signature,
        timestamp=timestamp,
        serial_no=config["serial_no"],
    )
    return auth


def _notify_url(config: dict) -> str:
    value = (config.get("notify_url") or "").strip()
    if value:
        return value
    base = (os.environ.get("PAY_NOTIFY_BASE_URL") or "").strip().rstrip("/")
    if not base:
        raise PaymentChannelNotConfigured("未配置通知地址：请在支付配置中填写 notify_url 或设置 PAY_NOTIFY_BASE_URL")
    return f"{base}/api/payments/notify/wechat"


class WechatPayAdapter(PaymentGatewayProtocol):
    provider = "wechat"

    def _require(self, *keys: str) -> dict:
        missing = [key for key in keys if not (self.config.get(key) or "").strip()]
        if missing:
            raise PaymentChannelNotConfigured(f"微信支付渠道未完成配置，缺少字段: {', '.join(missing)}")
        return self.config

    def create_payment(self, order) -> dict:
        config = self._require("app_id", "mch_id", "serial_no", "private_key", "api_v3_key")
        try:
            path = "/v3/pay/transactions/native"
            body = {
                "appid": config["app_id"],
                "mchid": config["mch_id"],
                "description": self._description(order),
                "out_trade_no": order.order_no,
                "notify_url": _notify_url(config),
                "amount": {"total": int(round(float(order.amount) * 100)), "currency": "CNY"},
            }
            body_text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
            headers = {
                "Authorization": _authorization("POST", path, body_text, config),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            }
            try:
                resp = requests.post(
                    WECHAT_API_BASE + path,
                    data=body_text.encode("utf-8"),
                    headers=headers,
                    timeout=20,
                )
            except Exception as exc:
                raise FailException(f"微信支付下单失败：{exc}") from exc
            if resp.status_code != 200:
                self._raise_api_error(resp)
            data = resp.json()
        except PaymentChannelNotConfigured:
            raise
        except FailException:
            raise
        except Exception as exc:
            raise FailException(f"微信支付下单失败：{exc}") from exc
        code_url = data.get("code_url") or ""
        if not code_url:
            raise FailException("微信支付下单失败：未返回二维码")
        return {
            "provider": "wechat",
            "pay_type": "native",
            "code_url": code_url,
            "out_trade_no": order.order_no,
            "amount": float(order.amount),
        }

    def verify_callback(self, payload, headers: dict | None = None) -> dict:
        config = self._require("api_v3_key")
        body = payload if isinstance(payload, (bytes, bytearray)) else str(payload).encode("utf-8")
        headers = headers or {}
        body_text = body.decode("utf-8")
        if config.get("platform_public_key"):
            timestamp = headers.get("Wechatpay-Timestamp") or headers.get("wechatpay-timestamp") or ""
            nonce = headers.get("Wechatpay-Nonce") or headers.get("wechatpay-nonce") or ""
            signature = headers.get("Wechatpay-Signature") or headers.get("wechatpay-signature") or ""
            canonical = f"{timestamp}\n{nonce}\n{body_text}\n"
            if not rsa_verify(config["platform_public_key"], canonical, signature):
                raise FailException("微信支付回调验签失败")
        try:
            envelope = json.loads(body_text)
            resource = envelope["resource"]
            data = _decrypt_resource(
                resource.get("ciphertext") or "",
                resource.get("nonce") or "",
                resource.get("associated_data") or "",
                config["api_v3_key"],
            )
        except Exception as exc:
            raise FailException("微信支付回调数据解密失败") from exc
        return {
            "order_no": data.get("out_trade_no") or "",
            "transaction_id": data.get("transaction_id") or "",
            "paid": (data.get("trade_state") or "") == "SUCCESS",
            "amount_fen": int((data.get("amount") or {}).get("total") or 0),
        }

    def query_status(self, order_no: str) -> dict:
        config = self._require("app_id", "mch_id", "serial_no", "private_key")
        path = f"/v3/pay/transactions/out-trade-no/{quote(order_no)}?mchid={config['mch_id']}"
        headers = {
            "Authorization": _authorization("GET", path, "", config),
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        try:
            resp = requests.get(WECHAT_API_BASE + path, headers=headers, timeout=20)
        except Exception as exc:
            raise FailException(f"微信支付订单查询失败：{exc}") from exc
        if resp.status_code != 200:
            self._raise_api_error(resp)
        data = resp.json()
        return {
            "order_no": order_no,
            "status": data.get("trade_state") or "unknown",
            "transaction_id": data.get("transaction_id"),
        }

    @staticmethod
    def _description(order) -> str:
        plan_type = (order.plan_type or "").strip()
        if plan_type == "membership":
            return "会员套餐购买"
        if plan_type == "credits":
            return "算力包购买"
        if plan_type == "balance":
            return "余额充值"
        return "订单支付"

    @staticmethod
    def _raise_api_error(resp) -> None:
        try:
            detail = resp.json()
            code = detail.get("code") or ""
            message = detail.get("message") or ""
        except Exception:
            code, message = "", resp.text[:200]
        raise FailException(f"微信支付接口错误({resp.status_code}) {code} {message}".strip())