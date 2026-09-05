"""支付网关适配器注册表：渠道名规范化（wechatpay→wechat）与工厂获取。"""

from internal.service.payment.alipay import AlipayAdapter
from internal.service.payment.protocol import PaymentChannelNotConfigured, PaymentGatewayProtocol
from internal.service.payment.wechat_pay import WechatPayAdapter

_ADAPTERS = {
    "wechat": WechatPayAdapter,
    "wechatpay": WechatPayAdapter,
    "alipay": AlipayAdapter,
}


def normalize_provider(provider: str) -> str:
    provider = (provider or "").strip().lower()
    if provider == "wechatpay":
        return "wechat"
    return provider


def get_payment_adapter(provider: str, config: dict | None = None) -> PaymentGatewayProtocol:
    provider = normalize_provider(provider)
    adapter_cls = _ADAPTERS.get(provider)
    if adapter_cls is None:
        raise PaymentChannelNotConfigured(f"未知支付渠道: {provider}")
    return adapter_cls(config or {})