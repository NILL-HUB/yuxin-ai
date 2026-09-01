"""腾讯云短信 SendSms：TC3-HMAC-SHA256 签名 —— 纯函数。

供测试与发送复用：``build_tencent_request`` 返回 ``{"url", "headers",
"body"}``，headers 中携带 TC3 规范的 Authorization。``x-tc-action``
与 canonical 请求行统一使用小写 ``send sms``，与 TC3 签名规则一致。
"""
import hashlib
import hmac
import json
from datetime import UTC, datetime

TENCENT_HOST = "sms.tencentcloudapi.com"
TENCENT_SERVICE = "sms"
TENCENT_VERSION = "2021-01-11"


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def build_tencent_request(
    *,
    access_key,
    access_secret,
    region,
    sign_name,
    phone,
    template_code,
    params: dict,
) -> dict:
    """构造腾讯云 SendSms 请求；返回 ``{"url", "headers", "body"}``。"""
    now = datetime.now(UTC)
    date = now.strftime("%Y-%m-%d")
    timestamp = str(int(now.timestamp()))
    payload_obj = {
        "PhoneNumberSet": [phone],
        "SmsSdkAppId": "",
        "SignName": sign_name,
        "TemplateId": template_code,
        "TemplateParamSet": [str(params.get("code", ""))],
        "SenderId": "",
    }
    body_str = json.dumps(payload_obj, ensure_ascii=False, separators=(",", ":"))
    action = "send sms"
    canonical_headers = (
        f"content-type:application/json; charset=utf-8\n"
        f"host:{TENCENT_HOST}\n"
        f"x-tc-action:{action}\n"
    )
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = hashlib.sha256(body_str.encode("utf-8")).hexdigest()
    canonical_request = "\n".join(
        ["POST", "/", "", canonical_headers, signed_headers, hashed_payload]
    )
    credential_scope = f"{date}/{TENCENT_SERVICE}/tc3_request"
    string_to_sign = "\n".join(
        [
            "TC3-HMAC-SHA256",
            timestamp,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    secret_date = _hmac_sha256(("TC3" + access_secret).encode("utf-8"), date)
    secret_service = _hmac_sha256(secret_date, TENCENT_SERVICE)
    secret_signing = _hmac_sha256(secret_service, "tc3_request")
    signature = hmac.new(
        secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    authorization = (
        f"TC3-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "url": f"https://{TENCENT_HOST}/",
        "headers": {
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": TENCENT_HOST,
            "X-TC-Action": "SendSms",
            "X-TC-Timestamp": timestamp,
            "X-TC-Version": TENCENT_VERSION,
            "X-TC-Region": region or "ap-guangzhou",
        },
        "body": body_str,
    }
