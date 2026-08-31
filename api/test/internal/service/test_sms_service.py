import json

import pytest

from internal.service.sms.aliyun import build_aliyun_request
from internal.service.sms.tencent import build_tencent_request


class _FakeSession:
    """内存版单行 sms_config session（id=1 惰性创建），模拟 SQLAlchemy session。"""

    def __init__(self):
        self.row = None

    def query(self, model):
        return _FakeQuery(self)

    def add(self, row):
        if self.row is None:
            self.row = row

    def flush(self):
        pass


class _FakeQuery:
    def __init__(self, session):
        self._session = session

    def filter(self, *args, **kwargs):
        return self

    def one_or_none(self):
        return self._session.row


class _FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse(self.responses.pop(0))


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _configured_service(fake_http, provider="aliyun"):
    from internal.service.sms_service import SmsService

    svc = SmsService(session=_FakeSession(), http=fake_http)
    svc.update_config(
        {
            "provider": provider,
            "access_key": "AKID",
            "access_secret": "SECRET",
            "sign_name": "平台",
            "region": "ap-guangzhou",
            "sdk_app_id": "1400000000",
            "verify_code_template": "SMS_1" if provider == "aliyun" else "123456",
        }
    )
    return svc


def test_aliyun_build_request_shape():
    req = build_aliyun_request(
        access_key="AKID",
        access_secret="SECRET",
        sign_name="平台",
        phone="13800138000",
        template_code="SMS_1",
        params={"code": "123456"},
    )
    assert req["url"] == "https://dysmsapi.aliyuncs.com/"
    assert req["body"]["PhoneNumbers"] == "13800138000"
    assert req["body"]["SignName"] == "平台"
    assert req["body"]["TemplateCode"] == "SMS_1"
    assert req["body"]["Action"] == "SendSms"
    assert req["body"]["RegionId"] == "cn-hangzhou"
    assert req["body"]["Format"] == "JSON"
    assert req["body"]["SignatureMethod"] == "HMAC-SHA1"
    assert req["body"]["SignatureVersion"] == "1.0"
    assert req["body"]["Version"] == "2017-05-25"
    assert req["body"]["AccessKeyId"] == "AKID"
    assert req["body"]["Timestamp"]
    assert req["body"]["SignatureNonce"]
    assert "Signature" in req["body"]
    assert json.loads(req["body"]["TemplateParam"]) == {"code": "123456"}


def test_aliyun_percent_encode_rfc3986():
    req = build_aliyun_request(
        access_key="AKID",
        access_secret="SECRET",
        sign_name="平台",
        phone="13800138000",
        template_code="SMS_1",
        params={"code": "123456"},
    )
    assert req["body"]["SignName"] == "平台"
    assert req["body"]["TemplateParam"] == '{"code": "123456"}'


def test_tencent_build_request_shape():
    req = build_tencent_request(
        access_key="AKID",
        access_secret="SECRET",
        region="ap-guangzhou",
        sign_name="平台",
        phone="13800138000",
        template_code="123456",
        params={"code": "123456"},
    )
    assert req["url"] == "https://sms.tencentcloudapi.com/"
    assert req["host"] if "host" in req else req["headers"]["Host"] == "sms.tencentcloudapi.com"
    assert req["headers"]["Content-Type"] == "application/json; charset=utf-8"
    assert req["headers"]["X-TC-Action"] == "SendSms"
    assert req["headers"]["X-TC-Version"] == "2021-01-11"
    assert req["headers"]["X-TC-Region"] == "ap-guangzhou"
    assert "Authorization" in req["headers"]
    assert req["headers"]["Authorization"].startswith("TC3-HMAC-SHA256 Credential=")
    assert "SignedHeaders=content-type;host;x-tc-action" in req["headers"]["Authorization"]
    assert "Signature=" in req["headers"]["Authorization"]
    assert "13800138000" in req["body"]
    assert "123456" in req["body"]
    payload = json.loads(req["body"])
    assert payload["PhoneNumberSet"] == ["13800138000"]
    assert payload["TemplateParamSet"] == ["123456"]
    assert payload["SignName"] == "平台"


def test_sms_config_update_and_get_roundtrip():
    from internal.service.sms_service import SmsService

    svc = SmsService(session=_FakeSession())
    svc.update_config(
        {
            "provider": "aliyun",
            "access_key": "AKID",
            "access_secret": "SECRET",
            "sign_name": "平台",
            "region": "cn-hangzhou",
            "sdk_app_id": "",
            "verify_code_template": "SMS_1",
        }
    )
    cfg = svc.get_config()
    assert cfg["provider"] == "aliyun"
    assert cfg["access_key"] == "AKID"
    assert cfg["sign_name"] == "平台"
    assert cfg["verify_code_template"] == "SMS_1"
    assert cfg["region"] == "cn-hangzhou"
    assert svc.is_configured() is True


def test_sms_config_update_invalid_provider():
    from internal.service.sms_service import SmsService

    svc = SmsService(session=_FakeSession())
    with pytest.raises(ValueError, match="provider 仅支持"):
        svc.update_config({"provider": "aws"})


def test_sms_config_update_provider_requires_four_fields():
    from internal.service.sms_service import SmsService

    svc = SmsService(session=_FakeSession())
    with pytest.raises(ValueError, match="开启短信需完整填写"):
        svc.update_config(
            {
                "provider": "aliyun",
                "access_key": "AKID",
                "access_secret": "",
                "sign_name": "平台",
                "verify_code_template": "SMS_1",
            }
        )


def test_sms_service_unconfigured_raises():
    from internal.service.sms_service import SmsService

    svc = SmsService(session=_FakeSession())
    assert svc.is_configured() is False
    with pytest.raises(RuntimeError, match="短信发送未配置"):
        svc.send_verification_code("13800138000", "123456")


def test_sms_service_send_verification_code_aliyun_ok():
    fake_http = _FakeHttp([{"Code": "OK", "Message": "OK"}])
    svc = _configured_service(fake_http, provider="aliyun")
    svc.send_verification_code("13800138000", "123456")
    assert len(fake_http.calls) == 1
    url, kwargs = fake_http.calls[0]
    assert url == "https://dysmsapi.aliyuncs.com/"
    assert kwargs["data"]["PhoneNumbers"] == "13800138000"
    assert json.loads(kwargs["data"]["TemplateParam"]) == {"code": "123456"}


def test_sms_service_send_aliyun_error_raises():
    fake_http = _FakeHttp([{"Code": "isv.SMS_SIGNATURE_ILLEGAL", "Message": "签名不合法"}])
    svc = _configured_service(fake_http, provider="aliyun")
    with pytest.raises(RuntimeError, match="阿里云短信失败: isv.SMS_SIGNATURE_ILLEGAL"):
        svc.send_verification_code("13800138000", "123456")


def test_sms_service_send_tencent_ok():
    fake_http = _FakeHttp([{"Response": {}}])
    svc = _configured_service(fake_http, provider="tencent")
    svc.send_verification_code("13800138000", "123456")
    assert len(fake_http.calls) == 1
    url, kwargs = fake_http.calls[0]
    assert url == "https://sms.tencentcloudapi.com/"
    assert kwargs["headers"]["X-TC-Action"] == "SendSms"
    assert "13800138000" in kwargs["content"]


def test_sms_service_send_tencent_error_raises():
    fake_http = _FakeHttp(
        [{"Response": {"Error": {"Code": "FailedOperation", "Message": "模板不匹配"}}}]
    )
    svc = _configured_service(fake_http, provider="tencent")
    with pytest.raises(RuntimeError, match="腾讯云短信失败: FailedOperation"):
        svc.send_verification_code("13800138000", "123456")


def test_sms_service_send_test_aliyun_ok():
    fake_http = _FakeHttp([{"Code": "OK"}])
    svc = _configured_service(fake_http, provider="aliyun")
    result = svc.send_test(recipient="13800138000")
    assert result["ok"] is True
    assert result["provider"] == "aliyun"
    assert result["code"] == "OK"


def test_sms_service_send_test_unconfigured_raises():
    from internal.service.sms_service import SmsService

    svc = SmsService(session=_FakeSession())
    with pytest.raises(RuntimeError, match="短信发送未配置"):
        svc.send_test(recipient="13800138000")
