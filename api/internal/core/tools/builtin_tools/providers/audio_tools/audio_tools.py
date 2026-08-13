"""语音工具：文本转语音 + 音频转文本。

复用平台 AudioService（SiliconFlow ASR/TTS）。Agent 可通过这两个工具
朗读回复或理解用户语音，返回 data URI / 纯文本，便于前端直接播放。
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import urllib.request
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
from werkzeug.datastructures import FileStorage

logger = logging.getLogger(__name__)

_ALLOWED_VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer", "alex")


def _load_audio_service():
    from internal.service.audio_service import AudioService
    from app.http.module import injector

    return injector.get(AudioService)


def _fetch_audio_bytes(url_or_b64: str) -> bytes:
    value = str(url_or_b64 or "").strip()
    if not value:
        raise ValueError("音频地址不能为空")
    if value.startswith("data:"):
        head, _, payload = value.partition(",")
        if ";base64" in head:
            return base64.b64decode(payload)
        import urllib.parse

        return urllib.parse.unquote_to_bytes(payload)
    if value.startswith("http://") or value.startswith("https://"):
        with urllib.request.urlopen(value, timeout=30) as resp:
            return resp.read()
    # 兜底按 base64 解析
    return base64.b64decode(value)


class TtsSpeakInput(BaseModel):
    text: str = Field(..., description="要朗读的文本内容")
    voice: str = Field(
        default="alex",
        description="音色，可选 alloy/echo/fable/onyx/nova/shimmer/alex，默认 alex",
    )
    language: str = Field(
        default="",
        description="语言代码（如 zh/en），留空由服务端自动处理",
    )


class TtsSpeakTool(BaseTool):
    name: str = "tts_speak"
    description: str = (
        "将文本合成为语音并返回音频 data URI（mp3），前端可直接播放。"
        "用于朗读回复、生成语音通知等场景。"
    )
    args_schema: type[BaseModel] = TtsSpeakInput

    def _run(self, text: str, voice: str = "alex", language: str = "", **kwargs: Any) -> str:
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return json.dumps({"ok": False, "error": "文本不能为空"}, ensure_ascii=False)
        if voice not in _ALLOWED_VOICES:
            voice = "alex"
        try:
            service = _load_audio_service()
            response = service._create_tts_response(normalized_text, voice, language)
            chunks = []
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    chunks.append(chunk)
            audio_bytes = b"".join(chunks)
            if not audio_bytes:
                return json.dumps({"ok": False, "error": "TTS 未返回音频数据"}, ensure_ascii=False)
            data_uri = "data:audio/mpeg;base64," + base64.b64encode(audio_bytes).decode("ascii")
            return json.dumps(
                {
                    "ok": True,
                    "audio_data_uri": data_uri,
                    "voice": voice,
                    "char_count": len(normalized_text),
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            logger.warning("TTS 工具调用失败", exc_info=True)
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    async def _arun(self, text: str, voice: str = "alex", language: str = "", **kwargs: Any) -> str:
        return self._run(text=text, voice=voice, language=language, **kwargs)


class AudioTranscribeInput(BaseModel):
    audio_url: str = Field(
        ...,
        description="音频地址：http(s) URL 或 data:audio/...;base64,.... 格式",
    )
    language: str = Field(
        default="",
        description="音频语言代码（如 zh/en），留空由服务端自动检测",
    )
    provider: str = Field(
        default="",
        description="转写服务商，gpt_transcribe/gpt-transcribe 时切换增强模型，留空使用默认 ASR",
    )
    model: str = Field(
        default="",
        description="显式指定 ASR 模型名，留空按 provider 路由",
    )


class AudioTranscribeTool(BaseTool):
    name: str = "audio_transcribe"
    description: str = (
        "将语音音频转成文本。输入音频 URL 或 data URI，返回识别文本。"
        "用于理解用户语音留言、会议录音等场景。"
    )
    args_schema: type[BaseModel] = AudioTranscribeInput

    def _run(
        self,
        audio_url: str,
        language: str = "",
        provider: str = "",
        model: str = "",
        **kwargs: Any,
    ) -> str:
        try:
            audio_bytes = _fetch_audio_bytes(audio_url)
            if not audio_bytes:
                return json.dumps({"ok": False, "error": "音频内容为空"}, ensure_ascii=False)
            storage = FileStorage(
                stream=io.BytesIO(audio_bytes),
                filename="agent_audio.wav",
            )
            service = _load_audio_service()
            text = service.audio_to_text(
                storage,
                language=language,
                provider=provider,
                model=model,
            ).strip()
            return json.dumps({"ok": True, "text": text}, ensure_ascii=False)
        except Exception as exc:
            logger.warning("STT 工具调用失败", exc_info=True)
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    async def _arun(
        self,
        audio_url: str,
        language: str = "",
        provider: str = "",
        model: str = "",
        **kwargs: Any,
    ) -> str:
        return self._run(
            audio_url=audio_url,
            language=language,
            provider=provider,
            model=model,
            **kwargs,
        )


def tts_speak(**kwargs: Any) -> BaseTool:
    return TtsSpeakTool()


def audio_transcribe(**kwargs: Any) -> BaseTool:
    return AudioTranscribeTool()
