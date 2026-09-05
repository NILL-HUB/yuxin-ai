"""支付宝电脑网站支付适配器（alipay.trade.page.pay）。

配置项（管理端「系统配置-支付配置」）：
  app_id              开放平台应用 ID（明文）
  private_key         应用私钥（PKCS1/PKCS8 PEM，密文保存）
  ali_public_key      支付宝公钥（PEM，密文保存）
  notify_url          异步通知地址（明文；不填则使用 PAY_NOTIFY_BASE_URL 拼接）
  return_url          同步跳转地址（明文，可选）
"""
import base64
import json
import os
import urllib.parse
from datetime import datetime

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from internal.exception import FailException
from internal.service.payment.protocol import PaymentChannelNotConfigured, PaymentGatewayProtocol

ALIPAY_GATEWAY = "https://openapi.alipay.com/gateway.do"
PAID_TRADE_STATUS = ("TRADE_SUCCESS", "TRADE_FINISHED")


def _load_private_key(pem: str):
    return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)


def _load_public_key(pem: str):
    return serialization.load_pem_public_key(pem.encode("utf-8"))


def rsa2_sign(private_key_pem: str, content: str) -> str:
    key = _load_private_key(private_key_pem)
    signature = key.sign(content.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode("utf-8")


def rsa2_verify(public_key_pem: str, content: str, signature_b64: str) -> bool:
    try:
        key = _load_public_key(public_key_pem)
        key.verify(
            base64.b64decode(signature_b64),
            content.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False


def _sign_str(params: dict) -> str:
    items = sorted(
        (str(k), str(v))
        for k, v in params.items()
        if k not in ("sign", "sign_type") and v is not None and str(v) != ""
    )
    return "&".join(f"{k}={v}" for k, v in items)


def _notify_url(config: dict) -> str:
    value = (config.get("notify_url") or "").strip()
    if value:
        return value
    base = (os.environ.get("PAY_NOTIFY_BASE_URL") or "").strip().rstrip("/")
    if not base:
        raise PaymentChannelNotConfigured("未配置通知地址：请在支付配置中填写 notify_url 或设置 PAY_NOTIFY_BASE_URL")
    return f"{base}/api/payments/notify/alipay"


class AlipayAdapter(PaymentGatewayProtocol):
    provider = "alipay"

    def _require(self, *keys: str) -> dict:
        missing = [key for key in keys if not (self.config.get(key) or "").strip()]
        if missing:
            raise PaymentChannelNotConfigured(f"支付宝渠道未完成配置，缺少字段: {', '.join(missing)}")
        return self.config

    def _common_params(self, method: str, biz_content: dict) -> dict:
        config = self._require("app_id", "private_key", "ali_public_key")
        params = {
            "app_id": config["app_id"],
            "method": method,
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "biz_content": json.dumps(biz_content, ensure_ascii=False, separators=(",", ":")),
        }
        if method == "alipay.trade.page.pay":
            notify = (config.get("notify_url") or "").strip()
            if notify:
                params["notify_url"] = notify
            ret = (config.get("return_url") or "").strip()
            if ret:
                params["return_url"] = ret
        elif method == "alipay.trade.query":
            notify = (config.get("notify_url") or "").strip()
            if notify:
                params["notify_url"] = notify
        return params

    def create_payment(self, order) -> dict:
        config = self._require("app_id", "private_key", "ali_public_key")
        try:
            biz_content = {
                "out_trade_no": order.order_no,
                "total_amount": f"{float(order.amount):.2f}",
                "subject": self._description(order),
                "product_code": "FAST_INSTANT_TRADE_PAY",
            }
            params = self._common_params("alipay.trade.page.pay", biz_content)
            params["sign"] = rsa2_sign(config["private_key"], _sign_str(params))
            pay_url = ALIPAY_GATEWAY + "?" + urllib.parse.urlencode(params)
        except PaymentChannelNotConfigured:
            raise
        except Exception as exc:
            raise FailException(f"支付宝下单失败：{exc}") from exc
        return {
            "provider": "alipay",
            "pay_type": "page",
            "pay_url": pay_url,
            "out_trade_no": order.order_no,
            "amount": float(order.amount),
        }

    def verify_callback(self, payload, headers: dict | None = None) -> dict:
        config = self._require("ali_public_key")
        params = dict(payload or {})
        sign = params.pop("sign", "") or ""
        params.pop("sign_type", None)
        if not sign or not rsa2_verify(config["ali_public_key"], _sign_str(params), sign):
            raise FailException("支付宝回调验签失败")
        status = params.get("trade_status") or ""
        return {
            "order_no": params.get("out_trade_no") or "",
            "transaction_id": params.get("trade_no") or "",
            "paid": status in PAID_TRADE_STATUS,
            "amount": float(params.get("total_amount") or 0),
        }

    def query_status(self, order_no: str) -> dict:
        config = self._require("app_id", "private_key", "ali_public_key")
        params = self._common_params("alipay.trade.query", {"out_trade_no": order_no})
        params["sign"] = rsa2_sign(config["private_key"], _sign_str(params))
        try:
            resp = requests.post(ALIPAY_GATEWAY, data=params, timeout=20)
        except Exception as exc:
            raise FailException(f"支付宝订单查询失败：{exc}") from exc
        try:
            data = (resp.json() or {}).get("alipay_trade_query_response") or {}
        except Exception:
            raise FailException("支付宝订单查询响应格式错误") from None
        return {
            "order_no": order_no,
            "status": data.get("trade_status") or "unknown",
            "transaction_id": data.get("trade_no") or None,
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