"""推送服务：Provider 请求构造（个推/友盟）+ 主备编排（个推为主、友盟为辅）。

- 请求构造为**纯函数**（含签名），单测锁定机械结构；HTTP 收敛到唯一 `_post_json` 缝。
- 个推 REST v2（官方文档 docs.getui.com/getui/server/rest_v2/）：
  鉴权 `POST {BaseUrl}/auth`（sign=sha256(appkey+timestamp+mastersecret)，token 约 1 天有效，
  业务返回 10001 视为 token 失效需被动刷新）；单推 `POST {BaseUrl}/push/single/cid`。
- 友盟 U-Push 服务端（msgapi.umeng.com/api/send）：sign=md5("POST"+url+body+app_master_secret)；
  **官方文档抓取受限，字段与签名按公开约定实现，资质开通后需按官方文档核对（未实测）。**
- 编排：按账号已注册令牌逐条发送；主通道失败自动切备（fallback_enabled）；全部失败聚合返回；
  未启用/无令牌静默跳过（不阻断业务主流程）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.request
import uuid
from typing import Any

from injector import inject

from internal.model.push_channel import PushDevice
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .push_config_service import PushConfigService

logger = logging.getLogger(__name__)

GETUI_BASE_URL = "https://restapi.getui.com/v2/{app_id}"
GETUI_INVALID_TOKEN_CODE = 10001
UMENG_SEND_URL = "https://msgapi.umeng.com/api/send"
DEFAULT_TTL_MS = 2 * 60 * 60 * 1000


# ---------------------------------------------------------------------- 个推

def sign_getui_auth(app_key: str, timestamp: str, master_secret: str) -> str:
    """个推鉴权签名：sha256(appkey + timestamp + mastersecret)。"""
    return hashlib.sha256(f"{app_key}{timestamp}{master_secret}".encode("utf-8")).hexdigest()


def build_getui_auth_request(credentials: dict, *, timestamp: str | None = None):
    """构造个推鉴权请求：返回 (url, payload)。"""
    ts = str(timestamp or int(time.time() * 1000))
    app_id = str(credentials.get("app_id") or "")
    app_key = str(credentials.get("app_key") or "")
    master_secret = str(credentials.get("master_secret") or "")
    url = f"{GETUI_BASE_URL.format(app_id=app_id)}/auth"
    payload = {"sign": sign_getui_auth(app_key, ts, master_secret), "timestamp": ts, "appkey": app_key}
    return url, payload


def build_getui_single_push_request(
    credentials: dict,
    *,
    cid: str,
    title: str,
    body: str,
    click_url: str = "",
    request_id: str = "",
    ttl_ms: int = DEFAULT_TTL_MS,
):
    """构造个推单推（按 cid）请求：返回 (url, payload)。"""
    app_id = str(credentials.get("app_id") or "")
    url = f"{GETUI_BASE_URL.format(app_id=app_id)}/push/single/cid"
    notification = {
        "title": title,
        "body": body,
        "click_type": "url" if click_url else "startapp",
    }
    if click_url:
        notification["url"] = click_url
    payload = {
        "request_id": request_id or uuid.uuid4().hex,
        "settings": {"ttl": int(ttl_ms)},
        "audience": {"cid": [cid]},
        "push_message": {"notification": notification},
    }
    return url, payload


# ---------------------------------------------------------------------- 友盟

def sign_umeng(app_master_secret: str, url: str, body: str) -> str:
    """友盟签名：md5("POST" + url + body + app_master_secret)。"""
    raw = f"POST{url}{body}{app_master_secret}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def build_umeng_unicast_request(
    credentials: dict,
    *,
    device_token: str,
    title: str,
    body: str,
    timestamp: str | None = None,
):
    """构造友盟单播请求：返回 (url_with_sign, body_str, payload)。"""
    ts = str(timestamp or int(time.time() * 1000))
    payload = {
        "appkey": str(credentials.get("app_key") or ""),
        "timestamp": ts,
        "type": "unicast",
        "device_tokens": device_token,
        "payload": {
            "display_type": "notification",
            "body": {
                "ticker": title,
                "title": title,
                "text": body,
                "after_open": "go_app",
            },
        },
        "production_mode": bool(credentials.get("production_mode", True)),
    }
    body_str = json.dumps(payload, ensure_ascii=False)
    sign = sign_umeng(str(credentials.get("app_master_secret") or ""), UMENG_SEND_URL, body_str)
    return f"{UMENG_SEND_URL}?sign={sign}", body_str, payload


# ---------------------------------------------------------------------- 编排

@inject
class PushGatewayService(BaseService):
    """账号维度推送编排：主通道（个推）→ 失败切备（友盟）。"""

    def __init__(self, db: SQLAlchemy = None):
        self.db = db
        self._getui_tokens: dict[str, tuple[str, int]] = {}

    # ------------------------------------------------ 对外入口

    def notify_account(
        self,
        account_id: Any,
        *,
        title: str,
        body: str,
        click_url: str = "",
        data: dict | None = None,
    ) -> dict:
        """向账号已注册的推送令牌发送通知（主备自动切换）。

        返回 {"ok": bool, "skipped": bool, "reason": str, "results": [...]}；
        任何异常都不抛出——推送是旁路能力，失败只记录（不阻断调用方业务主流程）。
        """
        try:
            config = PushConfigService().get_runtime_config()
        except Exception:
            logger.warning("推送配置读取失败，跳过推送 account=%s", account_id, exc_info=True)
            return {"ok": False, "skipped": True, "reason": "config_unavailable", "results": []}

        if not config.get("enabled"):
            return {"ok": True, "skipped": True, "reason": "disabled", "results": []}

        try:
            tokens = self._enabled_tokens(account_id)
        except Exception:
            logger.warning("推送令牌读取失败，跳过推送 account=%s", account_id, exc_info=True)
            return {"ok": False, "skipped": True, "reason": "tokens_unavailable", "results": []}
        if not tokens:
            return {"ok": True, "skipped": True, "reason": "no_device", "results": []}

        primary = str(config.get("primary_provider") or "getui")
        candidates = [primary]
        if config.get("fallback_enabled"):
            fallback = "umeng" if primary == "getui" else "getui"
            candidates.append(fallback)

        results: list[dict] = []
        for device in tokens:
            sent = False
            for provider in candidates:
                credentials = dict(config.get(provider) or {})
                if not self._credentials_ready(provider, credentials):
                    results.append(
                        {"device": device["token"], "provider": provider, "ok": False, "detail": "credentials_missing"}
                    )
                    continue
                ok, detail = self._send_via(
                    provider, credentials, device, title=title, body=body, click_url=click_url
                )
                results.append({"device": device["token"], "provider": provider, "ok": ok, "detail": detail})
                if ok:
                    sent = True
                    break  # 该设备已由候选通道成功送达，不再切备
            if not sent:
                logger.warning(
                    "推送全部通道失败 account=%s device=%s results=%s", account_id, device["token"], results[-2:]
                )
        return {"ok": any(r["ok"] for r in results), "skipped": False, "reason": "", "results": results}

    def send_test(self, *, provider: str, device_token: str, title: str = "钰见我测试推送", body: str = "如果你收到这条消息，说明推送通道配置成功。") -> dict:
        """admin 联调入口：用当前配置向指定令牌发一条测试推送。"""
        provider = str(provider or "").strip().lower()
        if provider not in ("getui", "umeng"):
            return {"ok": False, "detail": "provider 只能是 getui / umeng"}
        config = PushConfigService().get_runtime_config()
        credentials = dict(config.get(provider) or {})
        if not self._credentials_ready(provider, credentials):
            return {"ok": False, "detail": "该通道凭证未配置完整"}
        ok, detail = self._send_via(
            provider, credentials, {"provider": provider, "token": device_token}, title=title, body=body, click_url=""
        )
        return {"ok": ok, "detail": detail}

    # ------------------------------------------------ 内部

    def _credentials_ready(self, provider: str, credentials: dict) -> bool:
        if provider == "getui":
            return bool(
                credentials.get("app_id")
                and credentials.get("app_key")
                and credentials.get("master_secret")
            )
        if provider == "umeng":
            return bool(credentials.get("app_key") and credentials.get("app_master_secret"))
        return False

    def _enabled_tokens(self, account_id: Any) -> list[dict]:
        rows = (
            self.db.session.query(PushDevice)
            .filter(PushDevice.account_id == account_id, PushDevice.enabled.is_(True))
            .all()
        )
        return [{"provider": row.provider, "token": row.token, "platform": row.platform} for row in rows]

    def _send_via(
        self,
        provider: str,
        credentials: dict,
        device: dict,
        *,
        title: str,
        body: str,
        click_url: str,
    ) -> tuple[bool, str]:
        try:
            if provider == "getui":
                return self._send_getui(credentials, device["token"], title=title, body=body, click_url=click_url)
            if provider == "umeng":
                url, body_str, _payload = build_umeng_unicast_request(
                    credentials, device_token=device["token"], title=title, body=body
                )
                response = self._post_json(url, json.loads(body_str))
                ret = str((response or {}).get("ret") or "")
                if ret == "SUCCESS":
                    return True, ""
                return False, f"友盟返回 {ret or 'UNKNOWN'}: {str((response or {}).get('data') or '')[:200]}"
            return False, f"未知通道 {provider}"
        except Exception as exc:
            logger.warning("推送发送失败 provider=%s", provider, exc_info=True)
            return False, f"发送异常：{exc}"

    def _send_getui(self, credentials: dict, cid: str, *, title: str, body: str, click_url: str) -> tuple[bool, str]:
        token = self._getui_token(credentials)
        if not token:
            return False, "个推鉴权失败"
        url, payload = build_getui_single_push_request(
            credentials, cid=cid, title=title, body=body, click_url=click_url
        )
        response = self._post_json(url, payload, headers={"token": token})
        code = int((response or {}).get("code", -1))
        if code == 0:
            return True, ""
        if code == GETUI_INVALID_TOKEN_CODE:
            # token 失效：被动刷新一次后重试（官方建议）
            refreshed = self._getui_token(credentials, force_refresh=True)
            if refreshed:
                response = self._post_json(url, payload, headers={"token": refreshed})
                if int((response or {}).get("code", -1)) == 0:
                    return True, ""
        return False, f"个推返回 code={code}: {str((response or {}).get('msg') or '')[:200]}"

    def _getui_token(self, credentials: dict, *, force_refresh: bool = False) -> str:
        """个推 token 缓存（进程内，按 app_id）；过期或强制时重新鉴权。"""
        app_id = str(credentials.get("app_id") or "")
        now_ms = int(time.time() * 1000)
        cached = self._getui_tokens.get(app_id)
        if cached and not force_refresh and cached[1] > now_ms + 60_000:
            return cached[0]
        url, payload = build_getui_auth_request(credentials)
        try:
            response = self._post_json(url, payload)
        except Exception:
            logger.warning("个推鉴权请求失败 app_id=%s", app_id, exc_info=True)
            return ""
        data = (response or {}).get("data") or {}
        token = str(data.get("token") or "")
        expire_at = int(data.get("expire_time") or 0) or (now_ms + 24 * 60 * 60 * 1000)
        if token:
            self._getui_tokens[app_id] = (token, expire_at)
        return token

    # 唯一 HTTP 缝（单测注入 mock；超时与错误归一为异常，由调用方降级）
    def _post_json(self, url: str, payload: dict, *, headers: dict | None = None, timeout: int = 15) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json;charset=utf-8", **(headers or {})},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
