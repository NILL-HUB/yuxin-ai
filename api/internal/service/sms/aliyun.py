"""阿里云短信 SendSms：RPC 签名（HMAC-SHA1 SignatureVersion=1.0）—— 纯函数。

供测试与发送复用：``build_aliyun_request`` 返回完整的 url + body（含
Signature），不发起任何网络请求。
"""
import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from urllib.parse import quote

ALIYUN_ENDPOINT = "https://dysmsapi.aliyuncs.com/"
ALIYUN_VERSION = "2017-05-25"


def _percent_encode(s: str) -> str:
    """阿里云 RPC 规范 percent-encode（RFC3986）。

    字母数字与 ``-`` ``_`` ``.`` ``~`` 不转义，其余字符按字节转义为大写
    ``%XX``，空格编码为 ``%20``（不能用 ``+``）。
    """
    return quote(str(s), safe="-_.~")


def build_aliyun_request(
    *,
    access_key,
    access_secret,
    sign_name,
    phone,
    template_code,
    params: dict,
) -> dict:
    """构造阿里云 SendSms 请求；返回 ``{"url": ..., "body": {...}}``。"""
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    common = {
        "AccessKeyId": access_key,
        "Action": "SendSms",
        "Format": "JSON",
        "PhoneNumbers": phone,
        "RegionId": "cn-hangzhou",
        "SignName": sign_name,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": str(uuid.uuid4()),
        "SignatureVersion": "1.0",
        "TemplateCode": template_code,
        "TemplateParam": json.dumps(params, ensure_ascii=False),
        "Timestamp": ts,
        "Version": ALIYUN_VERSION,
    }
    sorted_keys = sorted(common.items())
    query = "&".join(f"{_percent_encode(k)}={_percent_encode(str(v))}" for k, v in sorted_keys)
    string_to_sign = f"GET&%2F&{_percent_encode(query)}"
    digest = hmac.new(
        (access_secret + "&").encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    common["Signature"] = base64.b64encode(digest).decode("utf-8")
    return {"url": ALIYUN_ENDPOINT, "body": common}
