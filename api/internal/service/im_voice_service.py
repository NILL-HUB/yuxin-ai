"""IM 平台语音笔记接入服务。

统一处理各 IM 平台发来的语音消息：下载媒体 -> ASR 转写 -> 文本进入 Agent。
当前已实现微信公众号（wechat/weixin）、飞书（feishu/lark）、钉钉（dingtalk）、
LINE、WhatsApp、QQ；Photon 等平台按同一入口逐步接入，避免每个平台各自造一套转写链路。
"""

import logging
import json
import threading
import time
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import requests
from injector import inject
from werkzeug.datastructures import FileStorage

from internal.exception import FailException
from .audio_service import AudioService


logger = logging.getLogger(__name__)

_WECHAT_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
_WECHAT_MEDIA_URL = "https://api.weixin.qq.com/cgi-bin/media/get"
_WECHAT_TOKEN_SAFE_TTL = 5400
_FEISHU_TOKEN_URL = "/open-apis/auth/v3/tenant_access_token/internal"
_FEISHU_RESOURCE_URL = "/open-apis/im/v1/messages/{message_id}/resources/{file_key}"
_FEISHU_MESSAGE_URL = "/open-apis/im/v1/messages"
_FEISHU_TOKEN_SAFE_TTL = 7000
_LINE_CONTENT_URL = "https://api-data.line.me/v2/bot/message/{message_id}/content"
_LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
_WHATSAPP_GRAPH_BASE = "https://graph.facebook.com"
_DINGTALK_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
_DINGTALK_DOWNLOAD_URL = "https://api.dingtalk.com/v1.0/robot/messageFiles/download"
_DINGTALK_TOKEN_SAFE_TTL = 7000


@inject
@dataclass
class ImVoiceService:
    """IM 语音笔记统一转写入口。"""

    audio_service: AudioService
    _wechat_token_cache: dict[str, tuple[str, float]] = field(default_factory=dict)
    _wechat_token_lock: threading.Lock = field(default_factory=threading.Lock)
    _feishu_token_cache: dict[str, tuple[str, float]] = field(default_factory=dict)
    _feishu_token_lock: threading.Lock = field(default_factory=threading.Lock)
    _dingtalk_token_cache: dict[str, tuple[str, float]] = field(default_factory=dict)
    _dingtalk_token_lock: threading.Lock = field(default_factory=threading.Lock)

    def transcribe_platform_voice(
        self,
        platform: str,
        payload: dict[str, Any] | None = None,
        config: Any = None,
        **kwargs: Any,
    ) -> str:
        """按平台路由语音笔记转写，返回识别文本。"""
        normalized_platform = str(platform or "").strip().lower()
        if normalized_platform in ("wechat", "weixin"):
            media_id = str((payload or {}).get("media_id") or "")
            if not media_id:
                raise FailException("微信语音消息缺少 media_id")
            return self.transcribe_wechat_voice(
                config,
                media_id,
                audio_format=str((payload or {}).get("format") or "amr"),
                **kwargs,
            )
        if normalized_platform in ("feishu", "lark"):
            message_id = str((payload or {}).get("message_id") or "")
            file_key = str((payload or {}).get("file_key") or "")
            if not message_id or not file_key:
                raise FailException("飞书语音消息缺少 message_id 或 file_key")
            return self.transcribe_feishu_voice(
                config,
                message_id,
                file_key,
                audio_format=str((payload or {}).get("format") or "opus"),
                **kwargs,
            )
        if normalized_platform == "line":
            message_id = str((payload or {}).get("message_id") or "")
            if not message_id:
                raise FailException("LINE 语音消息缺少 message_id")
            return self.transcribe_line_voice(
                config,
                message_id,
                audio_format=str((payload or {}).get("format") or "opus"),
                **kwargs,
            )
        if normalized_platform in ("whatsapp", "wa"):
            media_id = str((payload or {}).get("media_id") or "")
            if not media_id:
                raise FailException("WhatsApp 语音消息缺少 media_id")
            return self.transcribe_whatsapp_voice(
                config,
                media_id,
                audio_format=str((payload or {}).get("format") or "ogg"),
                **kwargs,
            )
        if normalized_platform == "dingtalk":
            download_code = str((payload or {}).get("download_code") or "")
            if not download_code:
                raise FailException("钉钉语音消息缺少 download_code")
            return self.transcribe_dingtalk_voice(
                config,
                download_code,
                audio_format=str((payload or {}).get("format") or "amr"),
                **kwargs,
            )
        if normalized_platform in ("qq", "qqbot"):
            asr_refer_text = str((payload or {}).get("asr_refer_text") or "").strip()
            if asr_refer_text:
                return asr_refer_text
            audio_url = str((payload or {}).get("voice_wav_url") or "").strip() or str(
                (payload or {}).get("url") or ""
            ).strip()
            if not audio_url:
                raise FailException("QQ 语音消息缺少附件 url")
            return self.transcribe_qq_voice(
                config,
                audio_url,
                audio_format=str((payload or {}).get("format") or "wav")
                if (payload or {}).get("voice_wav_url")
                else str((payload or {}).get("format") or "silk"),
                **kwargs,
            )
        raise FailException(f"平台语音笔记尚未接入：{normalized_platform or 'unknown'}")

    def transcribe_feishu_voice(
        self,
        feishu_config: Any,
        message_id: str,
        file_key: str,
        audio_format: str = "opus",
        language: str = "",
        provider: str = "",
        model: str = "",
    ) -> str:
        """下载飞书语音资源并转写为文本。"""
        access_token = self._get_feishu_tenant_access_token(feishu_config)
        audio_bytes = self._download_feishu_resource(
            access_token,
            message_id,
            file_key,
        )
        if not audio_bytes:
            raise FailException("飞书语音媒体下载为空")
        safe_format = "".join(ch for ch in str(audio_format or "opus") if ch.isalnum()) or "opus"
        storage = FileStorage(
            stream=BytesIO(audio_bytes),
            filename=f"feishu_voice_{file_key}.{safe_format}",
        )
        return self.audio_service.audio_to_text(
            storage,
            language=language,
            provider=provider,
            model=model,
        ).strip()

    def transcribe_wechat_voice(
        self,
        wechat_config: Any,
        media_id: str,
        audio_format: str = "amr",
        language: str = "",
        provider: str = "",
        model: str = "",
    ) -> str:
        """下载微信公众号语音媒体并转写为文本。"""
        access_token = self._get_wechat_access_token(wechat_config)
        audio_bytes = self._download_wechat_media(access_token, media_id)
        if not audio_bytes:
            raise FailException("微信语音媒体下载为空")
        safe_format = "".join(ch for ch in str(audio_format or "amr") if ch.isalnum()) or "amr"
        storage = FileStorage(
            stream=BytesIO(audio_bytes),
            filename=f"voice_{media_id}.{safe_format}",
        )
        return self.audio_service.audio_to_text(
            storage,
            language=language,
            provider=provider,
            model=model,
        ).strip()

    def _get_wechat_access_token(self, wechat_config: Any) -> str:
        app_id = str(getattr(wechat_config, "wechat_app_id", "") or "").strip()
        secret = str(getattr(wechat_config, "wechat_app_secret", "") or "").strip()
        if not app_id or not secret:
            raise FailException("微信语音转写需要配置 wechat_app_id / wechat_app_secret")

        cache_key = f"{app_id}:{secret}"
        now = time.monotonic()
        with self._wechat_token_lock:
            cached = self._wechat_token_cache.get(cache_key)
            if cached and cached[1] > now:
                return cached[0]

        try:
            resp = requests.get(
                _WECHAT_TOKEN_URL,
                params={
                    "grant_type": "client_credential",
                    "appid": app_id,
                    "secret": secret,
                },
                timeout=20,
            )
            data = resp.json()
        except Exception as exc:
            logger.warning("获取微信公众号 access_token 失败", exc_info=exc)
            raise FailException("获取微信公众号 access_token 失败，请稍后重试")

        token = str(data.get("access_token") or "").strip()
        if not token:
            error_message = str(data.get("errmsg") or "unknown error")
            raise FailException(f"获取微信公众号 access_token 失败: {error_message}")
        expires_in = max(int(data.get("expires_in") or 7200), 60)
        ttl = min(expires_in - 300, _WECHAT_TOKEN_SAFE_TTL)
        with self._wechat_token_lock:
            self._wechat_token_cache[cache_key] = (token, now + max(ttl, 60))
        return token

    def _download_wechat_media(self, access_token: str, media_id: str) -> bytes:
        try:
            resp = requests.get(
                _WECHAT_MEDIA_URL,
                params={"access_token": access_token, "media_id": media_id},
                timeout=30,
            )
            content_type = resp.headers.get("Content-Type", "") or ""
            if content_type.startswith("application/json") or content_type.startswith("text/"):
                data = resp.json()
                raise FailException(f"下载微信语音媒体失败: {data.get('errmsg') or 'unknown error'}")
            return resp.content
        except FailException:
            raise
        except Exception as exc:
            logger.warning("下载微信语音媒体失败 media_id=%s", media_id, exc_info=exc)
            raise FailException("下载微信语音媒体失败，请稍后重试")

    def _get_feishu_tenant_access_token(self, feishu_config: Any) -> str:
        import os

        app_id = str(
            getattr(feishu_config, "feishu_app_id", "")
            or os.getenv("FEISHU_APP_ID", "")
        ).strip()
        app_secret = str(
            getattr(feishu_config, "feishu_app_secret", "")
            or os.getenv("FEISHU_APP_SECRET", "")
        ).strip()
        if not app_id or not app_secret:
            raise FailException("飞书语音转写需要配置 FEISHU_APP_ID / FEISHU_APP_SECRET")

        cache_key = f"{app_id}:{app_secret}"
        now = time.monotonic()
        with self._feishu_token_lock:
            cached = self._feishu_token_cache.get(cache_key)
            if cached and cached[1] > now:
                return cached[0]

        base_url = str(os.getenv("FEISHU_BASE_URL", "https://open.feishu.cn")).rstrip("/")
        try:
            resp = requests.post(
                f"{base_url}{_FEISHU_TOKEN_URL}",
                json={"app_id": app_id, "app_secret": app_secret},
                timeout=20,
            )
            data = resp.json()
        except Exception as exc:
            logger.warning("获取飞书 tenant_access_token 失败", exc_info=exc)
            raise FailException("获取飞书 tenant_access_token 失败，请稍后重试")

        token = str(data.get("tenant_access_token") or "").strip()
        if not token:
            error_message = str(data.get("msg") or "unknown error")
            raise FailException(f"获取飞书 tenant_access_token 失败: {error_message}")
        expires_in = max(int(data.get("expire") or 7200), 60)
        ttl = min(expires_in - 300, _FEISHU_TOKEN_SAFE_TTL)
        with self._feishu_token_lock:
            self._feishu_token_cache[cache_key] = (token, now + max(ttl, 60))
        return token

    def _download_feishu_resource(
        self,
        access_token: str,
        message_id: str,
        file_key: str,
    ) -> bytes:
        import os

        base_url = str(os.getenv("FEISHU_BASE_URL", "https://open.feishu.cn")).rstrip("/")
        url = base_url + _FEISHU_RESOURCE_URL.format(
            message_id=message_id,
            file_key=file_key,
        )
        headers = {"Authorization": f"Bearer {access_token}"}
        last_error = "unknown error"
        for resource_type in ("audio", "file"):
            try:
                resp = requests.get(
                    url,
                    params={"type": resource_type},
                    headers=headers,
                    timeout=30,
                )
                content_type = resp.headers.get("Content-Type", "") or ""
                if content_type.startswith("application/json") or content_type.startswith("text/"):
                    data = resp.json()
                    last_error = str(data.get("msg") or "unknown error")
                    continue
                if resp.content:
                    return resp.content
            except Exception as exc:
                logger.warning(
                    "下载飞书语音资源失败 message_id=%s file_key=%s type=%s",
                    message_id,
                    file_key,
                    resource_type,
                    exc_info=exc,
                )
                last_error = str(exc)
        raise FailException(f"下载飞书语音媒体失败: {last_error}")

    def transcribe_line_voice(
        self,
        line_config: Any,
        message_id: str,
        audio_format: str = "opus",
        language: str = "",
        provider: str = "",
        model: str = "",
    ) -> str:
        """下载 LINE 语音消息并转写为文本。"""
        import os

        access_token = str(
            getattr(line_config, "line_channel_access_token", "")
            or os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
        ).strip()
        if not access_token:
            raise FailException("LINE 语音转写需要配置 LINE_CHANNEL_ACCESS_TOKEN")
        audio_bytes = self._download_line_audio(access_token, message_id)
        safe_format = "".join(ch for ch in str(audio_format or "opus") if ch.isalnum()) or "opus"
        storage = FileStorage(
            stream=BytesIO(audio_bytes),
            filename=f"line_voice_{message_id}.{safe_format}",
        )
        return self.audio_service.audio_to_text(
            storage,
            language=language,
            provider=provider,
            model=model,
        ).strip()

    def _download_line_audio(self, access_token: str, message_id: str) -> bytes:
        try:
            resp = requests.get(
                _LINE_CONTENT_URL.format(message_id=message_id),
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=30,
            )
            content_type = resp.headers.get("Content-Type", "") or ""
            if content_type.startswith("application/json") or content_type.startswith("text/"):
                data = resp.json()
                raise FailException(f"下载 LINE 语音媒体失败: {data.get('message') or 'unknown error'}")
            if not resp.content:
                raise FailException("LINE 语音媒体下载为空")
            return resp.content
        except FailException:
            raise
        except Exception as exc:
            logger.warning("下载 LINE 语音媒体失败 message_id=%s", message_id, exc_info=exc)
            raise FailException("下载 LINE 语音媒体失败，请稍后重试")

    def transcribe_whatsapp_voice(
        self,
        whatsapp_config: Any,
        media_id: str,
        audio_format: str = "ogg",
        language: str = "",
        provider: str = "",
        model: str = "",
    ) -> str:
        """下载 WhatsApp 语音消息并转写为文本。"""
        import os

        access_token = str(
            getattr(whatsapp_config, "whatsapp_access_token", "")
            or os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        ).strip()
        if not access_token:
            raise FailException("WhatsApp 语音转写需要配置 WHATSAPP_ACCESS_TOKEN")
        graph_version = str(
            getattr(whatsapp_config, "whatsapp_graph_version", "")
            or os.getenv("WHATSAPP_GRAPH_VERSION", "v19.0")
        ).strip() or "v19.0"
        audio_bytes = self._download_whatsapp_audio(access_token, media_id, graph_version)
        safe_format = "".join(ch for ch in str(audio_format or "ogg") if ch.isalnum()) or "ogg"
        storage = FileStorage(
            stream=BytesIO(audio_bytes),
            filename=f"whatsapp_voice_{media_id}.{safe_format}",
        )
        return self.audio_service.audio_to_text(
            storage,
            language=language,
            provider=provider,
            model=model,
        ).strip()

    def _download_whatsapp_audio(
        self,
        access_token: str,
        media_id: str,
        graph_version: str,
    ) -> bytes:
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            resp = requests.get(
                f"{_WHATSAPP_GRAPH_BASE}/{graph_version}/{media_id}",
                headers=headers,
                timeout=30,
            )
            data = resp.json()
        except Exception as exc:
            logger.warning("获取 WhatsApp 媒体元数据失败 media_id=%s", media_id, exc_info=exc)
            raise FailException("获取 WhatsApp 语音媒体失败，请稍后重试")
        media_url = str(data.get("url") or "").strip()
        if not media_url:
            raise FailException(f"获取 WhatsApp 语音媒体失败: {data.get('error', {}).get('message') or 'missing url'}")
        try:
            media_resp = requests.get(media_url, headers=headers, timeout=60)
            media_resp.raise_for_status()
            if not media_resp.content:
                raise FailException("WhatsApp 语音媒体下载为空")
            return media_resp.content
        except FailException:
            raise
        except Exception as exc:
            logger.warning("下载 WhatsApp 语音媒体失败 media_id=%s", media_id, exc_info=exc)
            raise FailException("下载 WhatsApp 语音媒体失败，请稍后重试")

    def transcribe_dingtalk_voice(
        self,
        dingtalk_config: Any,
        download_code: str,
        audio_format: str = "amr",
        language: str = "",
        provider: str = "",
        model: str = "",
    ) -> str:
        """下载钉钉语音消息并转写为文本。"""
        access_token = self._get_dingtalk_access_token(dingtalk_config)
        audio_bytes = self._download_dingtalk_audio(access_token, download_code)
        safe_format = "".join(ch for ch in str(audio_format or "amr") if ch.isalnum()) or "amr"
        storage = FileStorage(
            stream=BytesIO(audio_bytes),
            filename=f"dingtalk_voice_{download_code}.{safe_format}",
        )
        return self.audio_service.audio_to_text(
            storage,
            language=language,
            provider=provider,
            model=model,
        ).strip()

    def _get_dingtalk_access_token(self, dingtalk_config: Any) -> str:
        import os

        app_key = str(
            getattr(dingtalk_config, "dingtalk_app_key", "")
            or os.getenv("DINGTALK_APP_KEY", "")
        ).strip()
        app_secret = str(
            getattr(dingtalk_config, "dingtalk_app_secret", "")
            or os.getenv("DINGTALK_APP_SECRET", "")
        ).strip()
        if not app_key or not app_secret:
            raise FailException("钉钉语音转写需要配置 DINGTALK_APP_KEY / DINGTALK_APP_SECRET")

        cache_key = f"{app_key}:{app_secret}"
        now = time.monotonic()
        with self._dingtalk_token_lock:
            cached = self._dingtalk_token_cache.get(cache_key)
            if cached and cached[1] > now:
                return cached[0]

        try:
            resp = requests.post(
                _DINGTALK_TOKEN_URL,
                json={"appKey": app_key, "appSecret": app_secret},
                timeout=20,
            )
            data = resp.json()
        except Exception as exc:
            logger.warning("获取钉钉 access_token 失败", exc_info=exc)
            raise FailException("获取钉钉 access_token 失败，请稍后重试")

        token = str(data.get("accessToken") or "").strip()
        if not token:
            error_message = str(data.get("message") or "unknown error")
            raise FailException(f"获取钉钉 access_token 失败: {error_message}")
        expires_in = max(int(data.get("expireIn") or 7200), 60)
        ttl = min(expires_in - 300, _DINGTALK_TOKEN_SAFE_TTL)
        with self._dingtalk_token_lock:
            self._dingtalk_token_cache[cache_key] = (token, now + max(ttl, 60))
        return token

    def _download_dingtalk_audio(self, access_token: str, download_code: str) -> bytes:
        try:
            resp = requests.get(
                _DINGTALK_DOWNLOAD_URL,
                params={"downloadCode": download_code},
                headers={"x-acs-dingtalk-access-token": access_token},
                timeout=30,
            )
            content_type = resp.headers.get("Content-Type", "") or ""
            if content_type.startswith("application/json") or content_type.startswith("text/"):
                data = resp.json()
                raise FailException(f"下载钉钉语音媒体失败: {data.get('message') or 'unknown error'}")
            if not resp.content:
                raise FailException("钉钉语音媒体下载为空")
            return resp.content
        except FailException:
            raise
        except Exception as exc:
            logger.warning("下载钉钉语音媒体失败 download_code=%s", download_code, exc_info=exc)
            raise FailException("下载钉钉语音媒体失败，请稍后重试")

    def transcribe_qq_voice(
        self,
        qq_config: Any,
        audio_url: str,
        audio_format: str = "silk",
        language: str = "",
        provider: str = "",
        model: str = "",
    ) -> str:
        """下载 QQ 语音附件并转写为文本。"""
        import os

        access_token = str(
            getattr(qq_config, "qq_access_token", "")
            or os.getenv("QQ_ACCESS_TOKEN", "")
        ).strip()
        audio_bytes = self._download_qq_audio(audio_url, access_token)
        safe_format = "".join(ch for ch in str(audio_format or "silk") if ch.isalnum()) or "silk"
        safe_name = "".join(
            ch for ch in audio_url.rstrip("/").rsplit("/", 1)[-1] if ch.isalnum()
        )[:32] or "audio"
        storage = FileStorage(
            stream=BytesIO(audio_bytes),
            filename=f"qq_voice_{safe_name}.{safe_format}",
        )
        return self.audio_service.audio_to_text(
            storage,
            language=language,
            provider=provider,
            model=model,
        ).strip()

    def _download_qq_audio(self, audio_url: str, access_token: str) -> bytes:
        headers = {}
        if access_token:
            headers["Authorization"] = f"QQBot {access_token}"
        try:
            resp = requests.get(
                audio_url,
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            if not resp.content:
                raise FailException("QQ 语音媒体下载为空")
            return resp.content
        except FailException:
            raise
        except Exception as exc:
            logger.warning("下载 QQ 语音媒体失败 url=%s", audio_url[:80], exc_info=exc)
            raise FailException("下载 QQ 语音媒体失败，请稍后重试")

    @staticmethod
    def verify_line_signature(raw_body: bytes, signature: str, channel_secret: str) -> bool:
        import hashlib
        import hmac

        expected = hmac.new(
            str(channel_secret or "").encode("utf-8"),
            raw_body or b"",
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, str(signature or ""))

    @staticmethod
    def verify_whatsapp_signature(raw_body: bytes, signature: str, app_secret: str) -> bool:
        import hashlib
        import hmac

        expected = hmac.new(
            str(app_secret or "").encode("utf-8"),
            raw_body or b"",
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", str(signature or "").strip())

    def handle_line_webhook(self, raw_body: bytes, signature: str = "") -> list[str]:
        """处理 LINE 语音消息 webhook：校验签名、转写并回复原会话。"""
        import os

        channel_secret = str(os.getenv("LINE_CHANNEL_SECRET", "")).strip()
        if channel_secret and not self.verify_line_signature(raw_body, signature, channel_secret):
            raise FailException("LINE webhook 签名校验失败")
        try:
            body = json.loads(raw_body or b"{}")
        except ValueError:
            body = {}
        replies: list[str] = []
        for event in body.get("events") or []:
            if not isinstance(event, dict) or event.get("type") != "message":
                continue
            message = event.get("message") or {}
            if message.get("type") != "audio":
                continue
            message_id = str(message.get("id") or "")
            reply_token = str(event.get("replyToken") or "")
            if not message_id or not reply_token:
                continue
            text = self.transcribe_line_voice(None, message_id)
            if text:
                self._reply_line(reply_token, text)
                replies.append(text)
        return replies

    def _reply_line(self, reply_token: str, text: str) -> None:
        import os

        access_token = str(os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")).strip()
        if not access_token:
            raise FailException("LINE 回复需要配置 LINE_CHANNEL_ACCESS_TOKEN")
        try:
            resp = requests.post(
                _LINE_REPLY_URL,
                json={
                    "replyToken": reply_token,
                    "messages": [{"type": "text", "text": text}],
                },
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=20,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("回复 LINE 消息失败", exc_info=exc)
            raise FailException("回复 LINE 消息失败，请稍后重试")

    def handle_whatsapp_webhook(self, raw_body: bytes, signature: str = "") -> list[str]:
        """处理 WhatsApp 语音消息 webhook：校验签名、转写并回复原会话。"""
        import os

        app_secret = str(os.getenv("WHATSAPP_APP_SECRET", "")).strip()
        if app_secret and not self.verify_whatsapp_signature(raw_body, signature, app_secret):
            raise FailException("WhatsApp webhook 签名校验失败")
        try:
            body = json.loads(raw_body or b"{}")
        except ValueError:
            body = {}
        replies: list[str] = []
        for entry in body.get("entry") or []:
            for change in (entry.get("changes") if isinstance(entry, dict) else []) or []:
                if not isinstance(change, dict):
                    continue
                value = change.get("value") or {}
                metadata = value.get("metadata") or {}
                phone_number_id = str(metadata.get("phone_number_id") or "")
                for message in value.get("messages") or []:
                    if not isinstance(message, dict) or message.get("type") != "audio":
                        continue
                    media_id = str(message.get("id") or "")
                    recipient = str(message.get("from") or "")
                    if not media_id or not recipient or not phone_number_id:
                        continue
                    text = self.transcribe_whatsapp_voice(None, media_id)
                    if text:
                        self._reply_whatsapp(phone_number_id, recipient, text)
                        replies.append(text)
        return replies

    def _reply_whatsapp(
        self,
        phone_number_id: str,
        recipient: str,
        text: str,
    ) -> None:
        import os

        access_token = str(os.getenv("WHATSAPP_ACCESS_TOKEN", "")).strip()
        graph_version = str(os.getenv("WHATSAPP_GRAPH_VERSION", "v19.0")).strip() or "v19.0"
        if not access_token:
            raise FailException("WhatsApp 回复需要配置 WHATSAPP_ACCESS_TOKEN")
        try:
            resp = requests.post(
                f"{_WHATSAPP_GRAPH_BASE}/{graph_version}/{phone_number_id}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "to": recipient,
                    "type": "text",
                    "text": {"body": text},
                },
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=20,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("回复 WhatsApp 消息失败", exc_info=exc)
            raise FailException("回复 WhatsApp 消息失败，请稍后重试")

    @staticmethod
    def verify_feishu_signature(
        raw_body: bytes,
        signature: str,
        timestamp: str,
        nonce: str,
        encrypt_key: str,
    ) -> bool:
        import hashlib
        import hmac

        body_str = (raw_body or b"").decode("utf-8", errors="replace")
        content = f"{timestamp}{nonce}{encrypt_key}{body_str}"
        computed = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return hmac.compare_digest(computed, str(signature or ""))

    def handle_feishu_webhook(
        self,
        raw_body: bytes,
        signature: str = "",
        timestamp: str = "",
        nonce: str = "",
    ) -> list[str]:
        """处理飞书语音消息事件：校验签名、转写并回复原会话。"""
        import os

        try:
            body = json.loads(raw_body or b"{}")
        except ValueError:
            body = {}
        encrypt_key = str(os.getenv("FEISHU_ENCRYPT_KEY", "")).strip()
        if encrypt_key and not self.verify_feishu_signature(
            raw_body,
            signature,
            timestamp,
            nonce,
            encrypt_key,
        ):
            raise FailException("飞书 webhook 签名校验失败")

        verification_token = str(os.getenv("FEISHU_VERIFICATION_TOKEN", "")).strip()
        if verification_token:
            header = body.get("header") if isinstance(body.get("header"), dict) else {}
            incoming_token = str(header.get("token") or body.get("token") or "")
            import hmac

            if not incoming_token or not hmac.compare_digest(
                incoming_token.encode("utf-8"),
                verification_token.encode("utf-8"),
            ):
                raise FailException("飞书 webhook verification token 校验失败")

        event = body.get("event") if isinstance(body.get("event"), dict) else {}
        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        if message.get("message_type") != "audio":
            return []
        try:
            content = json.loads(str(message.get("content") or "{}"))
        except ValueError:
            content = {}
        file_key = str(content.get("file_key") or "")
        message_id = str(message.get("message_id") or "")
        chat_id = str(message.get("chat_id") or event.get("chat_id") or "")
        if not file_key or not message_id or not chat_id:
            return []
        text = self.transcribe_feishu_voice(
            None,
            message_id,
            file_key,
            audio_format=str(content.get("format") or "opus"),
        )
        if text:
            self._reply_feishu(chat_id, text)
            return [text]
        return []

    def _reply_feishu(self, chat_id: str, text: str) -> None:
        import os

        access_token = self._get_feishu_tenant_access_token(None)
        base_url = str(os.getenv("FEISHU_BASE_URL", "https://open.feishu.cn")).rstrip("/")
        try:
            resp = requests.post(
                f"{base_url}{_FEISHU_MESSAGE_URL}",
                params={"receive_id_type": "chat_id"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text}, ensure_ascii=False),
                },
                timeout=20,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("回复飞书消息失败 chat_id=%s", chat_id, exc_info=exc)
            raise FailException("回复飞书消息失败，请稍后重试")

    @staticmethod
    def verify_dingtalk_signature(timestamp: str, sign: str, secret: str) -> bool:
        import base64
        import hashlib
        import hmac
        import urllib.parse

        string_to_sign = f"{timestamp}\n{secret}"
        digest = hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        expected = urllib.parse.quote_plus(base64.b64encode(digest))
        return hmac.compare_digest(expected, str(sign or ""))

    @staticmethod
    def _extract_dingtalk_voice(payload: dict) -> dict:
        """从钉钉机器人回调事件中提取语音下载码与回复地址。"""
        content = payload.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except ValueError:
                content = {}
        if not isinstance(content, dict):
            content = {}
        text = payload.get("text")
        if isinstance(text, str):
            try:
                text = json.loads(text)
            except ValueError:
                text = {}
        if not isinstance(text, dict):
            text = {}

        download_code = (
            content.get("downloadCode")
            or content.get("download_code")
            or text.get("downloadCode")
            or text.get("download_code")
            or payload.get("downloadCode")
            or payload.get("download_code")
        )
        recognition = (
            content.get("recognition")
            or text.get("recognition")
            or payload.get("recognition")
        )
        session_webhook = (
            payload.get("sessionWebhook")
            or payload.get("session_webhook")
            or ""
        )
        msg_type = str(
            payload.get("msgtype") or payload.get("message_type") or ""
        ).lower()
        return {
            "is_voice": bool(download_code)
            or msg_type in {"audio", "voice"},
            "download_code": str(download_code or ""),
            "recognition": str(recognition or ""),
            "session_webhook": str(session_webhook or ""),
        }

    def handle_dingtalk_webhook(
        self,
        raw_body: bytes,
        timestamp: str = "",
        sign: str = "",
    ) -> list[str]:
        """处理钉钉语音消息回调：校验加签、转写并回复 sessionWebhook。"""
        import os

        secret = str(os.getenv("DINGTALK_WEBHOOK_SECRET", "")).strip()
        if secret and not self.verify_dingtalk_signature(timestamp, sign, secret):
            raise FailException("钉钉 webhook 加签校验失败")
        try:
            body = json.loads(raw_body or b"{}")
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            return []
        voice = self._extract_dingtalk_voice(body)
        if not voice["is_voice"]:
            return []
        if voice["recognition"]:
            text = voice["recognition"].strip()
        else:
            if not voice["download_code"]:
                return []
            text = self.transcribe_dingtalk_voice(None, voice["download_code"])
        if text and voice["session_webhook"]:
            self._reply_dingtalk(voice["session_webhook"], text)
            return [text]
        return []

    def _reply_dingtalk(self, session_webhook: str, text: str) -> None:
        try:
            resp = requests.post(
                session_webhook,
                json={"msgtype": "text", "text": {"content": text}},
                timeout=20,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("回复钉钉消息失败", exc_info=exc)
            raise FailException("回复钉钉消息失败，请稍后重试")
