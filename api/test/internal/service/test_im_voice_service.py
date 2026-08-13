from types import SimpleNamespace
import base64
import hashlib
import hmac
import json
import urllib.parse

import pytest

from internal.exception import FailException
from internal.service.im_voice_service import (
    ImVoiceService,
    _WECHAT_MEDIA_URL,
    _WECHAT_TOKEN_URL,
)


class _FakeAudioService:
    def __init__(self):
        self.captured = {}

    def audio_to_text(self, storage, language="", provider="", model=""):
        self.captured.update(
            {
                "filename": storage.filename,
                "language": language,
                "provider": provider,
                "model": model,
            }
        )
        return "识别文本"


class _JsonResponse:
    def __init__(self, data, headers=None):
        self._data = data
        self.headers = headers or {"Content-Type": "application/json"}

    def json(self):
        return self._data


class _MediaResponse:
    def __init__(self, content):
        self.content = content
        self.headers = {"Content-Type": "audio/amr"}

    def raise_for_status(self):
        return None


def _service():
    return ImVoiceService(audio_service=_FakeAudioService())


def _config():
    return SimpleNamespace(wechat_app_id="app-1", wechat_app_secret="secret-1")


def _feishu_config():
    return SimpleNamespace(feishu_app_id="feishu-app", feishu_app_secret="feishu-secret")


def test_transcribe_wechat_voice_downloads_and_transcribes(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if url == _WECHAT_TOKEN_URL:
            return _JsonResponse({"access_token": "token-1", "expires_in": 7200})
        if url == _WECHAT_MEDIA_URL:
            return _MediaResponse(b"audio-bytes")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)
    service = _service()

    result = service.transcribe_wechat_voice(
        _config(),
        "media-1",
        language="zh",
        provider="gpt_transcribe",
        model="custom/asr",
    )

    assert result == "识别文本"
    assert service.audio_service.captured["filename"] == "voice_media-1.amr"
    assert service.audio_service.captured["language"] == "zh"
    assert service.audio_service.captured["provider"] == "gpt_transcribe"
    assert service.audio_service.captured["model"] == "custom/asr"
    assert len(calls) == 2


def test_wechat_access_token_is_cached(monkeypatch):
    token_requests = []

    def fake_get(url, **kwargs):
        if url == _WECHAT_TOKEN_URL:
            token_requests.append(1)
            return _JsonResponse({"access_token": "token-1", "expires_in": 7200})
        if url == _WECHAT_MEDIA_URL:
            return _MediaResponse(b"audio-bytes")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)
    service = _service()

    service.transcribe_wechat_voice(_config(), "media-1")
    service.transcribe_wechat_voice(_config(), "media-2")

    assert len(token_requests) == 1


def test_transcribe_platform_voice_routes_wechat(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        if url == _WECHAT_TOKEN_URL:
            return _JsonResponse({"access_token": "token-1", "expires_in": 7200})
        if url == _WECHAT_MEDIA_URL:
            return _MediaResponse(b"audio-bytes")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)
    service = _service()

    result = service.transcribe_platform_voice(
        "wechat",
        {"media_id": "media-9", "format": "amr"},
        _config(),
    )

    assert result == "识别文本"


def test_transcribe_feishu_voice_downloads_and_transcribes(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return _JsonResponse({"tenant_access_token": "feishu-token", "expire": 7200})

    def fake_get(url, **kwargs):
        calls.append(("get", url, kwargs))
        return _MediaResponse(b"feishu-audio")

    monkeypatch.setattr("internal.service.im_voice_service.requests.post", fake_post)
    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)
    service = _service()

    result = service.transcribe_feishu_voice(
        _feishu_config(),
        "om_message_id",
        "file_key_1",
        language="zh",
    )

    assert result == "识别文本"
    assert service.audio_service.captured["filename"] == "feishu_voice_file_key_1.opus"
    assert service.audio_service.captured["language"] == "zh"
    assert any(
        call[1].endswith("/open-apis/auth/v3/tenant_access_token/internal")
        for call in calls
    )
    assert any(
        call[1].endswith("/open-apis/im/v1/messages/om_message_id/resources/file_key_1")
        and call[2]["params"]["type"] == "audio"
        for call in calls
    )


def test_transcribe_platform_voice_routes_feishu(monkeypatch):
    def fake_post(url, **kwargs):
        return _JsonResponse({"tenant_access_token": "feishu-token", "expire": 7200})

    def fake_get(url, **kwargs):
        return _MediaResponse(b"feishu-audio")

    monkeypatch.setattr("internal.service.im_voice_service.requests.post", fake_post)
    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)
    service = _service()

    result = service.transcribe_platform_voice(
        "feishu",
        {"message_id": "om_message_id", "file_key": "file_key_1", "format": "opus"},
        _feishu_config(),
    )

    assert result == "识别文本"


def test_feishu_tenant_token_is_cached(monkeypatch):
    token_requests = []

    def fake_post(url, **kwargs):
        token_requests.append(url)
        return _JsonResponse({"tenant_access_token": "feishu-token", "expire": 7200})

    def fake_get(url, **kwargs):
        return _MediaResponse(b"feishu-audio")

    monkeypatch.setattr("internal.service.im_voice_service.requests.post", fake_post)
    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)
    service = _service()

    service.transcribe_feishu_voice(_feishu_config(), "m1", "f1")
    service.transcribe_feishu_voice(_feishu_config(), "m2", "f2")

    assert len(token_requests) == 1


def test_transcribe_line_voice_downloads_and_transcribes(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _MediaResponse(b"line-audio")

    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)
    service = _service()

    result = service.transcribe_line_voice(
        SimpleNamespace(line_channel_access_token="line-token"),
        "message-1",
        language="zh",
    )

    assert result == "识别文本"
    assert service.audio_service.captured["filename"] == "line_voice_message-1.opus"
    assert service.audio_service.captured["language"] == "zh"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer line-token"


def test_transcribe_platform_voice_routes_line(monkeypatch):
    def fake_get(url, **kwargs):
        return _MediaResponse(b"line-audio")

    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)

    result = _service().transcribe_platform_voice(
        "line",
        {"message_id": "message-1"},
        SimpleNamespace(line_channel_access_token="line-token"),
    )

    assert result == "识别文本"


def test_transcribe_whatsapp_voice_downloads_and_transcribes(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if "cdn" in url or "download" in url:
            return _MediaResponse(b"whatsapp-audio")
        return _JsonResponse({"url": "https://cdn.example.com/audio.ogg"})

    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)
    service = _service()

    result = service.transcribe_whatsapp_voice(
        SimpleNamespace(
            whatsapp_access_token="wa-token",
            whatsapp_graph_version="v19.0",
        ),
        "media-1",
        language="zh",
    )

    assert result == "识别文本"
    assert service.audio_service.captured["filename"] == "whatsapp_voice_media-1.ogg"
    assert calls[0][0].endswith("/v19.0/media-1")
    assert calls[0][1]["headers"]["Authorization"] == "Bearer wa-token"


def test_transcribe_dingtalk_voice_downloads_and_transcribes(monkeypatch):
    token_requests = []

    def fake_post(url, **kwargs):
        token_requests.append(url)
        return _JsonResponse({"accessToken": "dingtalk-token", "expireIn": 7200})

    def fake_get(url, **kwargs):
        return _MediaResponse(b"dingtalk-audio")

    monkeypatch.setattr("internal.service.im_voice_service.requests.post", fake_post)
    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)
    service = _service()

    result = service.transcribe_dingtalk_voice(
        SimpleNamespace(dingtalk_app_key="key", dingtalk_app_secret="secret"),
        "code-1",
        language="zh",
    )
    service.transcribe_dingtalk_voice(
        SimpleNamespace(dingtalk_app_key="key", dingtalk_app_secret="secret"),
        "code-2",
    )

    assert result == "识别文本"
    assert service.audio_service.captured["filename"] == "dingtalk_voice_code-2.amr"
    assert len(token_requests) == 1


def test_transcribe_platform_voice_qq_uses_asr_refer_text():
    service = _service()

    result = service.transcribe_platform_voice(
        "qq",
        {"asr_refer_text": "QQ 自带识别结果"},
        None,
    )

    assert result == "QQ 自带识别结果"


def test_transcribe_qq_voice_downloads_wav_url(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _MediaResponse(b"qq-audio")

    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)
    service = _service()

    result = service.transcribe_qq_voice(
        SimpleNamespace(qq_access_token="qq-token"),
        "https://multimedia.qq.com/voice/abc",
        audio_format="wav",
        language="zh",
    )

    assert result == "识别文本"
    assert service.audio_service.captured["filename"] == "qq_voice_abc.wav"
    assert service.audio_service.captured["language"] == "zh"
    assert calls[0][1]["headers"]["Authorization"] == "QQBot qq-token"


def test_transcribe_platform_voice_unsupported_raises():
    with pytest.raises(FailException, match="尚未接入"):
        _service().transcribe_platform_voice("photon", {"media_id": "m"})


def test_handle_line_webhook_transcribes_and_replies(monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "line-token")
    get_calls = []
    post_calls = []

    def fake_get(url, **kwargs):
        get_calls.append((url, kwargs))
        return _MediaResponse(b"line-audio")

    class _PostResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, **kwargs):
        post_calls.append((url, kwargs))
        return _PostResponse()

    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)
    monkeypatch.setattr("internal.service.im_voice_service.requests.post", fake_post)
    service = _service()

    raw = (
        b'{"events":[{"type":"message","replyToken":"reply-1",'
        b'"message":{"type":"audio","id":"line-msg-1"}}]}'
    )
    replies = service.handle_line_webhook(raw)

    assert replies == ["识别文本"]
    assert any(url == "https://api-data.line.me/v2/bot/message/line-msg-1/content" for url, _ in get_calls)
    assert any(
        url == "https://api.line.me/v2/bot/message/reply"
        and kwargs["json"]["replyToken"] == "reply-1"
        for url, kwargs in post_calls
    )


def test_line_signature_verification(monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "line-secret")
    raw = b'{"events":[]}'
    expected = hmac.new(b"line-secret", raw, hashlib.sha256).hexdigest()
    service = _service()

    assert service.verify_line_signature(raw, expected, "line-secret") is True
    with pytest.raises(FailException, match="签名校验失败"):
        service.handle_line_webhook(raw, "bad-signature")


def test_handle_whatsapp_webhook_transcribes_and_replies(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "wa-token")
    get_calls = []
    post_calls = []

    def fake_get(url, **kwargs):
        get_calls.append(url)
        if "cdn" in url:
            return _MediaResponse(b"whatsapp-audio")
        return _JsonResponse({"url": "https://cdn.example.com/audio.ogg"})

    class _PostResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, **kwargs):
        post_calls.append((url, kwargs))
        return _PostResponse()

    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)
    monkeypatch.setattr("internal.service.im_voice_service.requests.post", fake_post)
    service = _service()

    raw = (
        b'{"entry":[{"changes":[{"value":{"metadata":{"phone_number_id":"pn-1"},'
        b'"messages":[{"type":"audio","id":"media-1","from":"user-1"}]}}]}]}'
    )
    replies = service.handle_whatsapp_webhook(raw)

    assert replies == ["识别文本"]
    assert any(url.endswith("/v19.0/media-1") for url in get_calls)
    assert any(
        url.endswith("/pn-1/messages") and kwargs["json"]["to"] == "user-1"
        for url, kwargs in post_calls
    )


def test_whatsapp_signature_verification():
    raw = b'{"entry":[]}'
    expected = "sha256=" + hmac.new(b"wa-secret", raw, hashlib.sha256).hexdigest()
    service = _service()

    assert service.verify_whatsapp_signature(raw, expected, "wa-secret") is True
    assert service.verify_whatsapp_signature(raw, "sha256=bad", "wa-secret") is False


def test_handle_feishu_webhook_transcribes_and_replies(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "feishu-app")
    monkeypatch.setenv("FEISHU_APP_SECRET", "feishu-secret")
    post_calls = []
    get_calls = []

    class _PostResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, **kwargs):
        post_calls.append((url, kwargs))
        if url.endswith("/open-apis/im/v1/messages"):
            return _PostResponse()
        return _JsonResponse({"tenant_access_token": "feishu-token", "expire": 7200})

    def fake_get(url, **kwargs):
        get_calls.append((url, kwargs))
        return _MediaResponse(b"feishu-audio")

    monkeypatch.setattr("internal.service.im_voice_service.requests.post", fake_post)
    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)
    service = _service()

    raw = json.dumps(
        {
            "schema": "2.0",
            "header": {"event_id": "e1", "event_type": "im.message.receive_v1", "token": "t"},
            "event": {
                "message": {
                    "message_id": "om_msg",
                    "message_type": "audio",
                    "chat_id": "oc_1",
                    "content": json.dumps({"file_key": "fk1", "format": "opus"}),
                },
                "chat_id": "oc_1",
            },
        }
    ).encode("utf-8")

    replies = service.handle_feishu_webhook(raw)

    assert replies == ["识别文本"]
    assert any(url.endswith("/om_msg/resources/fk1") for url, _ in get_calls)
    assert any(
        url.endswith("/open-apis/im/v1/messages")
        and kwargs["params"]["receive_id_type"] == "chat_id"
        and kwargs["json"]["receive_id"] == "oc_1"
        for url, kwargs in post_calls
    )


def test_feishu_signature_verification(monkeypatch):
    monkeypatch.setenv("FEISHU_ENCRYPT_KEY", "encrypt-key")
    raw = b'{"schema":"2.0","header":{"token":"t"},"event":{}}'
    timestamp = "1700000000"
    nonce = "nonce-1"
    expected = hashlib.sha256(
        f"{timestamp}{nonce}encrypt-key{raw.decode('utf-8')}".encode("utf-8")
    ).hexdigest()
    service = _service()

    assert (
        service.verify_feishu_signature(raw, expected, timestamp, nonce, "encrypt-key")
        is True
    )
    with pytest.raises(FailException, match="签名校验失败"):
        service.handle_feishu_webhook(raw, "bad-signature", timestamp, nonce)


def test_handle_dingtalk_webhook_transcribes_and_replies(monkeypatch):
    monkeypatch.setenv("DINGTALK_APP_KEY", "key")
    monkeypatch.setenv("DINGTALK_APP_SECRET", "secret")
    post_calls = []
    get_calls = []

    class _PostResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, **kwargs):
        post_calls.append((url, kwargs))
        if "robot/send" in url:
            return _PostResponse()
        return _JsonResponse({"accessToken": "dingtalk-token", "expireIn": 7200})

    def fake_get(url, **kwargs):
        get_calls.append((url, kwargs))
        return _MediaResponse(b"dingtalk-audio")

    monkeypatch.setattr("internal.service.im_voice_service.requests.post", fake_post)
    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)
    service = _service()

    raw = json.dumps(
        {
            "msgtype": "audio",
            "content": {"downloadCode": "code-1"},
            "sessionWebhook": "https://oapi.dingtalk.com/robot/send?access_token=x",
        }
    ).encode("utf-8")

    replies = service.handle_dingtalk_webhook(raw)

    assert replies == ["识别文本"]
    assert any(url.endswith("/v1.0/robot/messageFiles/download") for url, _ in get_calls)
    assert any(
        "robot/send" in url and kwargs["json"]["text"]["content"] == "识别文本"
        for url, kwargs in post_calls
    )


def test_dingtalk_signature_verification(monkeypatch):
    monkeypatch.setenv("DINGTALK_WEBHOOK_SECRET", "dingtalk-secret")
    raw = b'{"msgtype":"text"}'
    timestamp = "1700000000"
    string_to_sign = f"{timestamp}\ndingtalk-secret".encode("utf-8")
    digest = hmac.new(b"dingtalk-secret", string_to_sign, hashlib.sha256).digest()
    expected = urllib.parse.quote_plus(base64.b64encode(digest))
    service = _service()

    assert service.verify_dingtalk_signature(timestamp, expected, "dingtalk-secret") is True
    with pytest.raises(FailException, match="加签校验失败"):
        service.handle_dingtalk_webhook(raw, timestamp, "bad-sign")


def test_download_wechat_media_error_json_raises(monkeypatch):
    def fake_get(url, **kwargs):
        if url == _WECHAT_TOKEN_URL:
            return _JsonResponse({"access_token": "token-1", "expires_in": 7200})
        if url == _WECHAT_MEDIA_URL:
            return _JsonResponse({"errmsg": "invalid media_id"})
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("internal.service.im_voice_service.requests.get", fake_get)

    with pytest.raises(FailException, match="invalid media_id"):
        _service().transcribe_wechat_voice(_config(), "media-1")
