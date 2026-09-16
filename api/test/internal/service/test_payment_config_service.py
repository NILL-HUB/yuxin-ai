from types import SimpleNamespace

from internal.service.payment_config_service import (
    DEFAULT_PROVIDER_NAMES,
    PaymentConfigService,
)


class _QueryStub:
    def __init__(self, *, all_result=None, one_or_none_result=None):
        self._all_result = all_result or []
        self._one_or_none_result = one_or_none_result
        self.filters = []

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self._all_result

    def one_or_none(self):
        return self._one_or_none_result


class _SessionStub:
    def __init__(self, query_result):
        self._query_result = query_result

    def query(self, *_args, **_kwargs):
        return self._query_result


def _config(provider, *, name="", enabled=False):
    return SimpleNamespace(provider=provider, name=name, enabled=enabled, configs={})


def test_list_enabled_providers_returns_only_enabled_in_supported_order():
    rows = [
        _config("alipay", name="支付宝", enabled=True),
        _config("wechat", name="微信支付", enabled=True),
    ]
    svc = PaymentConfigService(session=_SessionStub(_QueryStub(all_result=rows)))
    result = svc.list_enabled_providers()
    # SUPPORTED_PROVIDERS 顺序固定为 wechat → alipay
    assert [item["provider"] for item in result] == ["wechat", "alipay"]
    assert result[0]["name"] == "微信支付"
    assert result[1]["name"] == "支付宝"


def test_list_enabled_providers_excludes_disabled_channels():
    rows = [
        _config("wechat", name="微信支付", enabled=False),
        _config("alipay", name="支付宝", enabled=False),
    ]
    svc = PaymentConfigService(session=_SessionStub(_QueryStub(all_result=rows)))
    assert svc.list_enabled_providers() == []


def test_list_enabled_providers_falls_back_to_default_name():
    rows = [_config("wechat", name="", enabled=True)]
    svc = PaymentConfigService(session=_SessionStub(_QueryStub(all_result=rows)))
    result = svc.list_enabled_providers()
    assert result == [{"provider": "wechat", "name": DEFAULT_PROVIDER_NAMES["wechat"]}]


def test_list_enabled_providers_hides_unknown_provider():
    rows = [_config("paypal", name="PayPal", enabled=True)]
    svc = PaymentConfigService(session=_SessionStub(_QueryStub(all_result=rows)))
    assert svc.list_enabled_providers() == []
