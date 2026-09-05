"""支付网关适配器协议基类与异常（独立模块，避免与具体渠道适配器循环导入）。

适配器通过 PaymentConfigService.decrypt_payload 获取解密后的商户配置，
管理端「系统配置-支付配置」页面填写正确的商户参数并启用渠道后即可直接使用：
  - wechat: 微信 Native 扫码支付（app_id/mch_id/serial_no/private_key/api_v3_key/notify_url）
  - alipay: 支付宝电脑网站支付（app_id/private_key/ali_public_key/notify_url/return_url）
"""


class PaymentChannelNotConfigured(Exception):
    """支付渠道未开通：未配置密钥或未启用。"""


class PaymentGatewayProtocol:
    provider: str = ""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def create_payment(self, order) -> dict:
        """返回前端支付参数（收银台 URL / 预支付单 / 二维码内容）。"""
        raise NotImplementedError

    def verify_callback(self, payload, headers: dict | None = None) -> dict:
        """校验异步回调签名并返回 {order_no, transaction_id, paid, amount}。"""
        raise NotImplementedError

    def query_status(self, order_no: str) -> dict:
        """主动查询订单状态，返回 {status, transaction_id}。"""
        raise NotImplementedError