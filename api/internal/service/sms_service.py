"""短信发送服务：读取 sms_config（provider: aliyun/tencent），httpx 直连发送。

配置以单行 JSONB 持久化（id=1），provider 为空表示通道未开启。
阿里云响应 ``body.Code == "OK"`` 才算成功；腾讯云响应中不存在
``body.Response.Error`` 才算成功。
"""
from __future__ import annotations

import httpx

from internal.extension.database_extension import db
from internal.model.auth_channel_config import SmsConfig
from internal.service.sms.aliyun import build_aliyun_request
from internal.service.sms.tencent import build_tencent_request

DEFAULTS = {
    "provider": "",
    "access_key": "",
    "access_secret": "",
    "sign_name": "",
    "region": "",
    "sdk_app_id": "",
    "verify_code_template": "",
}

VALID_PROVIDERS = ("", "aliyun", "tencent")


class SmsService:
    """短信发送配置与发送：单行记录（id=1），configs JSONB 持久化网关参数。"""

    def __init__(self, session=None, http: httpx.Client | None = None):
        self.session = session or db.session
        self._http = http or httpx.Client(timeout=15)

    def _row(self) -> SmsConfig:
        row = self.session.query(SmsConfig).filter(SmsConfig.id == 1).one_or_none()
        if row is None:
            row = SmsConfig(id=1, configs={})
            self.session.add(row)
            self.session.flush()
        return row

    def get_config(self) -> dict:
        cfg = dict(DEFAULTS)
        row = self._row()
        if row.configs:
            cfg.update({k: v for k, v in row.configs.items() if k in DEFAULTS})
        return cfg

    def update_config(self, payload: dict) -> dict:
        cfg = self.get_config()
        for k in DEFAULTS:
            if k not in payload:
                continue
            val = payload[k]
            if val is not None and str(val).strip() != "":
                cfg[k] = str(val).strip()
        if cfg["provider"] not in VALID_PROVIDERS:
            raise ValueError("provider 仅支持 aliyun/tencent")
        if cfg["provider"] and not (
            cfg["access_key"]
            and cfg["access_secret"]
            and cfg["sign_name"]
            and cfg["verify_code_template"]
        ):
            raise ValueError("开启短信需完整填写 access_key/access_secret/sign_name/验证码模板")
        row = self._row()
        row.configs = cfg
        return cfg

    def is_configured(self) -> bool:
        cfg = self.get_config()
        return bool(cfg["provider"] and cfg["access_key"] and cfg["verify_code_template"])

    def send_verification_code(self, phone: str, code: str) -> None:
        """发送短信验证码（供验证码统一入口调用）。"""
        cfg = self.get_config()
        if not self.is_configured():
            raise RuntimeError("短信发送未配置，请联系管理员配置短信通道")
        self._send(
            cfg,
            phone=phone,
            template_code=cfg["verify_code_template"],
            params={"code": code},
        )

    def _send(self, cfg: dict, *, phone: str, template_code: str, params: dict) -> dict:
        provider = cfg["provider"]
        if provider == "aliyun":
            req = build_aliyun_request(
                access_key=cfg["access_key"],
                access_secret=cfg["access_secret"],
                sign_name=cfg["sign_name"],
                phone=phone,
                template_code=template_code,
                params=params,
            )
            resp = self._http.post(req["url"], data=req["body"])
            body = resp.json()
            if body.get("Code") != "OK":
                raise RuntimeError(
                    f"阿里云短信失败: {body.get('Code')} {body.get('Message', '')[:200]}"
                )
            return {"provider": "aliyun", "code": body.get("Code")}
        if provider == "tencent":
            req = build_tencent_request(
                access_key=cfg["access_key"],
                access_secret=cfg["access_secret"],
                region=cfg.get("region", ""),
                sign_name=cfg["sign_name"],
                phone=phone,
                template_code=template_code,
                params=params,
            )
            resp = self._http.post(req["url"], headers=req["headers"], content=req["body"])
            body = resp.json()
            err = (body.get("Response") or {}).get("Error")
            if err:
                raise RuntimeError(
                    f"腾讯云短信失败: {err.get('Code')} {err.get('Message', '')[:200]}"
                )
            return {"provider": "tencent", "code": "OK"}
        raise RuntimeError("短信发送未配置")

    def send_test(self, *, recipient: str) -> dict:
        cfg = self.get_config()
        if not self.is_configured():
            raise RuntimeError("短信发送未配置")
        return {
            "ok": True,
            **self._send(
                cfg,
                phone=recipient,
                template_code=cfg["verify_code_template"],
                params={"code": "123456"},
            ),
        }
