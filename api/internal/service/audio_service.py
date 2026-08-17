import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from typing import Any, Generator, Union
from uuid import UUID
from internal.entity.audio_entity import ALLOWED_AUDIO_VOICES
from injector import inject
from werkzeug.datastructures import FileStorage
import requests
from internal.exception import NotFoundException, FailException
from internal.model import Account, Message, App, AppConfig, AppConfigVersion
from pkg.sqlalchemy import SQLAlchemy
from .app_service import AppService
from .base_service import BaseService
from .language_model_service import LanguageModelService
from ..entity.app_entity import AppStatus
from ..entity.conversation_entity import InvokeFrom


logger = logging.getLogger(__name__)

DEFAULT_ASR_MODEL = "TeleAI/TeleSpeechASR"
DEFAULT_GPT_TRANSCRIBE_MODEL = "OpenAI/whisper-large-v3"
DEFAULT_TTS_MODEL = "fnlp/MOSS-TTSD-v0.5"
_GPT_TRANSCRIBE_PROVIDERS = frozenset({"gpt_transcribe"})
_COSYVOICE_TTS_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
_MOSS_TTS_MODEL = "fnlp/MOSS-TTSD-v0.5"
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\u2600-\u27BF"
    "\uFE0F"
    "\u2B00-\u2BFF"
    "]"
)


class _SynthesizedTtsResponse:
    """把已完整合成的 TTS 音频包装成可迭代的响应对象。"""

    def __init__(self, audio: bytes) -> None:
        self._audio = audio
        self._offset = 0
        self.closed = False

    def iter_content(self, chunk_size: int = 1024) -> Generator[bytes, None, None]:
        while self._offset < len(self._audio):
            chunk = self._audio[self._offset:self._offset + chunk_size]
            self._offset += len(chunk)
            yield chunk

    def close(self) -> None:
        self.closed = True

@inject
@dataclass
class AudioService(BaseService):
    """语音服务，涵盖语音转文本、消息流式输出语音"""
    db: SQLAlchemy
    app_service: AppService

    @classmethod
    def _resolve_siliconflow_credentials(cls, model_type: str | None = None) -> tuple[str, str, str]:
        """从数据库查询 SiliconFlow 凭证（api_key + base_url + model）。

        替代原来从环境变量 SILICONFLOW_API_KEY/SILICONFLOW_API_BASE 读取的方式，
        统一走 admin 数据库管理。ASR 调用方应传入 model_type="asr"，避免取到
        同 provider 下其他类型的模型。
        """
        creds = LanguageModelService.get_provider_credentials(
            provider="SiliconFlow",
            model_type=model_type,
        )
        api_key = (creds.get("api_key") or "").strip()
        base_url = (creds.get("base_url") or "").strip()
        model = (creds.get("model") or "").strip()

        missing_configs = []
        if api_key == "":
            missing_configs.append("api_key")
        if base_url == "":
            missing_configs.append("base_url")

        if missing_configs:
            raise FailException(
                f"语音服务配置缺失（数据库 model_provider_config / model_key_config 中 "
                f"SiliconFlow 缺少: {', '.join(missing_configs)}），请在 admin 中配置"
            )

        return api_key, base_url, model

    @staticmethod
    def _env_flag(name: str) -> bool:
        return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _resolve_asr_model(
        provider: str = "",
        model: str = "",
        configured_model: str = "",
    ) -> str:
        """按 provider 解析 ASR 模型名。

        显式 model 优先；provider 为 gpt_transcribe/gpt-transcribe 或环境变量
        GPT_TRANSCRIBE_ENABLED 打开时使用 GPT_TRANSCRIBE_MODEL（默认
        OpenAI/whisper-large-v3）；其余回落到凭证里配置的模型或默认模型。
        """
        normalized_model = str(model or "").strip()
        if normalized_model:
            return normalized_model
        normalized_provider = str(provider or "").strip().lower().replace("-", "_")
        if (
            normalized_provider in _GPT_TRANSCRIBE_PROVIDERS
            or AudioService._env_flag("GPT_TRANSCRIBE_ENABLED")
        ):
            return os.getenv("GPT_TRANSCRIBE_MODEL", "").strip() or DEFAULT_GPT_TRANSCRIBE_MODEL
        return str(configured_model or "").strip() or DEFAULT_ASR_MODEL

    @staticmethod
    def _resolve_tts_model() -> str:
        """从数据库读取 SiliconFlow tts 模型，未配置时回退到默认模型。"""
        try:
            creds = LanguageModelService.get_provider_credentials(
                provider="SiliconFlow",
                model_type="tts",
            )
            model = (creds.get("model") or "").strip()
        except Exception:
            model = ""
        return model or DEFAULT_TTS_MODEL

    @staticmethod
    def sanitize_tts_text(text: str) -> str:
        """去掉 Markdown/Emoji/表格等不适合朗读的符号，转成纯文本。"""
        if not text:
            return ""
        t = str(text)
        t = re.sub(r"```.*?```", " ", t, flags=re.S)
        t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
        t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
        t = re.sub(r"<[^>]+>", " ", t)
        t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
        t = re.sub(r"`([^`]*)`", r"\1", t)
        t = re.sub(r"[*_~`]+", "", t)
        t = re.sub(r"^\s*>\s?", "", t, flags=re.M)
        lines: list[str] = []
        for line in t.splitlines():
            stripped = line.strip()
            if re.fullmatch(r"\|?[\s:\-|]+\|?", stripped):
                continue
            if "|" in stripped:
                cells = [cell.strip() for cell in stripped.strip("|").split("|")]
                line = "，".join(cell for cell in cells if cell)
            lines.append(line)
        t = "\n".join(lines)
        t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.M)
        t = re.sub(r"^\s*\d+[.、]\s+", "", t, flags=re.M)
        t = _EMOJI_RE.sub(" ", t)
        t = (
            t.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&nbsp;", " ")
        )
        t = re.sub(r"https?://\S+", " ", t)
        t = re.sub(r"\s+", " ", t)
        return t.strip()

    @staticmethod
    def _tts_candidates(configured_model: str, text_len: int) -> list[str]:
        """按文本长度给出 TTS 模型候选，长文本优先 CosyVoice2，短文本优先 MOSS。"""
        candidates: list[str] = []
        if configured_model:
            candidates.append(configured_model)
        if configured_model == _COSYVOICE_TTS_MODEL and text_len < 6:
            candidates.insert(0, _MOSS_TTS_MODEL)
        for fallback in (_MOSS_TTS_MODEL, _COSYVOICE_TTS_MODEL):
            if fallback not in candidates:
                candidates.append(fallback)
        return candidates

    def audio_to_text(
        self,
        audio: FileStorage,
        language: str = "",
        provider: str = "",
        model: str = "",
    ) -> str:
        """将语音转换为文本（SiliconFlow ASR，可指定语言/provider/模型）."""
        if not audio or not (content := audio.stream.read()):
            raise FailException("音频文件无效或为空")
        api_key, base_url, configured_model = self._resolve_siliconflow_credentials(model_type="asr")
        endpoint = f"{base_url.rstrip('/')}/audio/transcriptions"
        payload = {
            "model": self._resolve_asr_model(
                provider=provider,
                model=model,
                configured_model=configured_model,
            ),
        }
        normalized_language = str(language or "").strip()
        if normalized_language:
            payload["language"] = normalized_language

        try:
            resp = self._get_requests_session().post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (getattr(audio, "filename", "audio.wav"), BytesIO(content))},
                data=payload,
                timeout=60
            )
            resp.raise_for_status()
            return resp.json()["text"].strip()
        except Exception as e:
            logger.exception("语音转文本请求失败", exc_info=e)
            raise FailException("语音识别请求失败，请稍后重试")

    def message_to_audio(self, message_id: UUID, account: Account) -> Generator:
        """将消息转换成流式事件输出语音（SiliconFlow TTS）"""
        message, conversation = self._get_valid_message(message_id, account)

        input_text = (message.answer or "").strip()
        if input_text == "":
            raise NotFoundException("该消息不存在，请核实后重试")

        voice = self._resolve_voice(message, conversation, account)
        common_data = {
            "conversation_id": str(conversation.id),
            "message_id": str(message.id),
            "audio": "",
        }
        response = self._create_tts_response(input_text, voice)
        return self._stream_tts_response(response, common_data)

    def text_to_audio(self, message_id: Union[str, None], text: str, account: Account) -> Generator:
        """根据消息上下文配置将任意文本转换成流式语音"""
        normalized_text = (text or "").strip()
        if normalized_text == "":
            raise FailException("文本内容不能为空")

        normalized_message_id = str(message_id or "").strip()
        voice = "alex"
        conversation_id = ""
        resolved_message_id = ""

        if normalized_message_id != "":
            message, conversation = self._get_valid_message(normalized_message_id, account)
            voice = self._resolve_voice(message, conversation, account)
            conversation_id = str(conversation.id)
            resolved_message_id = str(message.id)

        common_data = {
            "conversation_id": conversation_id,
            "message_id": resolved_message_id,
            "audio": "",
        }
        response = self._create_tts_response(normalized_text, voice)
        return self._stream_tts_response(response, common_data)

    def _get_valid_message(self, message_id: Union[str, UUID], account: Account) -> tuple[Message, Any]:
        """根据消息ID获取并校验消息及会话归属"""
        try:
            normalized_message_id = UUID(str(message_id))
        except (TypeError, ValueError):
            raise NotFoundException("该消息不存在，请核实后重试")

        message = self.get(Message, normalized_message_id)
        if not message or message.is_deleted or message.created_by != account.id:
            raise NotFoundException("该消息不存在，请核实后重试")

        conversation = message.conversation
        if conversation is None or conversation.is_deleted or conversation.created_by != account.id:
            raise NotFoundException("该消息会话不存在，请核实后重试")

        return message, conversation

    def _resolve_voice(self, message: Message, conversation: Any, account: Account) -> str:
        """根据消息上下文解析语音配置并返回合法音色"""
        enable = True
        voice = "alex"

        if message.invoke_from in [InvokeFrom.WEB_APP.value, InvokeFrom.DEBUGGER.value]:
            app = self.get(App, conversation.app_id)
            if not app:
                raise NotFoundException("该消息会话归属应用不存在或校验失败，请核实后重试")
            if message.invoke_from == InvokeFrom.DEBUGGER.value and app.account_id != account.id:
                raise NotFoundException("该消息会话归属的应用不存在或校验失败，请核实后重试")
            if message.invoke_from == InvokeFrom.WEB_APP.value and app.status != AppStatus.PUBLISHED.value:
                raise NotFoundException("该消息会话归属的应用未发布，请核实后重试")

            app_config: Union[AppConfig, AppConfigVersion] = (
                app.draft_app_config
                if message.invoke_from == InvokeFrom.DEBUGGER.value
                else app.app_config
            )
            text_to_speech = app_config.text_to_speech
            enable = text_to_speech.get("enable", False)
            voice = text_to_speech.get("voice", "alex")
        elif message.invoke_from == InvokeFrom.ASSISTANT_AGENT.value:
            enable = True
            voice = "alex"
        elif message.invoke_from == InvokeFrom.SERVICE_API.value:
            raise NotFoundException("开放API消息不支持文本转语音服务")

        if enable is False:
            raise FailException("该应用未开启文字转语音功能，请核实后重试")

        if voice not in ALLOWED_AUDIO_VOICES:
            return "alex"
        return voice

    def _create_tts_response(
        self,
        input_text: str,
        voice: str,
        language: str = "",
    ) -> requests.Response:
        """合成 TTS 音频并返回可迭代响应。

        先清洗 Markdown/Emoji，再按文本长度选择模型：长文本优先 CosyVoice2，
        短文本优先 MOSS；返回空音频时自动切换到备用模型。
        """
        normalized_text = self.sanitize_tts_text(input_text)
        if not normalized_text:
            raise FailException("文本内容不能为空")

        api_key, base_url, _ = self._resolve_siliconflow_credentials()
        endpoint = f"{base_url.rstrip('/')}/audio/speech"

        normalized_language = str(language or "").strip()
        configured_model = self._resolve_tts_model()
        last_error: Exception | None = None

        for model in self._tts_candidates(configured_model, len(normalized_text)):
            full_voice = f"{model}:{voice}"
            payload = {
                "model": model,
                "input": normalized_text,
                "voice": full_voice,
                "response_format": "mp3",
                "stream": True,
                "speed": 1.0,
                "gain": 0,
            }
            if normalized_language:
                payload["language"] = normalized_language

            try:
                response = self._get_requests_session().post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    stream=True,
                    timeout=120,
                )
                response.raise_for_status()
                chunks = list(response.iter_content(chunk_size=1024))
                response.close()
                audio = b"".join(chunk for chunk in chunks if chunk)
                if audio:
                    return _SynthesizedTtsResponse(audio)
                last_error = FailException("TTS 返回空音频，请稍后重试")
                logger.warning("TTS 返回空音频，尝试备用模型: model=%s", model)
            except requests.exceptions.HTTPError as error:
                # 解析错误响应以提供更友好的错误信息
                error_message = "文字转语音请求失败，请稍后重试"
                try:
                    error_data = error.response.json()
                    if error.response.status_code == 403:
                        if "balance is insufficient" in error_data.get("message", ""):
                            error_message = "TTS服务余额不足，请充值后继续使用"
                        else:
                            error_message = "TTS服务访问被拒绝，请检查API Key权限"
                    elif error.response.status_code == 429:
                        error_message = "TTS服务请求过于频繁，请稍后重试"
                except Exception:
                    pass
                logger.error("文字转语音请求失败: %(error)s", {"error": error}, exc_info=True)
                raise FailException(error_message)
            except requests.exceptions.RequestException as error:
                logger.error("文字转语音请求失败: %(error)s", {"error": error}, exc_info=True)
                last_error = error
            except Exception as error:
                logger.error("文字转语音失败: %(error)s", {"error": error}, exc_info=True)
                last_error = error

        if isinstance(last_error, FailException):
            raise last_error
        raise FailException("文字转语音请求失败，请稍后重试")

    @staticmethod
    @lru_cache(maxsize=1)
    def _get_requests_session() -> requests.Session:
        """复用 HTTP Session，减少音频请求的连接建立开销。"""
        session = requests.Session()
        session.trust_env = True
        return session

    @classmethod
    def _stream_tts_response(cls, response: requests.Response, common_data: dict[str, str]) -> Generator:
        """将TTS响应转换成SSE流式事件"""
        def tts() -> Generator:
            try:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        data = {**common_data, "audio": base64.b64encode(chunk).decode("utf-8")}
                        yield f"event: tts_message\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
                yield f"event: tts_end\ndata: {json.dumps(common_data)}\n\n"
            except Exception as error:
                logger.error("流式输出语音数据失败: %(error)s", {"error": error}, exc_info=True)
                error_data = {**common_data, "error": "流式输出失败"}
                yield f"event: tts_error\ndata: {json.dumps(error_data)}\n\n"
            finally:
                response.close()

        return tts()

    @staticmethod
    def split_sentences(text: str, max_length: int = 120) -> list[str]:
        """把文本切成适合逐句 TTS 的句子列表。

        优先按中文/英文句子边界切分；超长片段按标点或长度折行，避免
        单句过长导致 TTS 延迟高或截断。
        """
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if not normalized:
            return []
        parts = re.split(r"(?<=[。！？!?；;])\s*", normalized)
        sentences: list[str] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if len(part) <= max_length:
                sentences.append(part)
                continue
            # 超长片段：按逗号/顿号/空格切分后聚合成 <= max_length 的短句。
            sub_parts = re.split(r"(?<=[，,、])\s*", part)
            current = ""
            for sub in sub_parts:
                sub = sub.strip()
                if not sub:
                    continue
                if current and len(current) + len(sub) + 1 > max_length:
                    sentences.append(current)
                    current = sub
                else:
                    current = f"{current} {sub}".strip()
            if current:
                sentences.append(current)
        return sentences

    def text_to_audio_sentences(
        self,
        message_id: Union[str, None],
        text: str,
        account: Account,
    ) -> Generator:
        """按句合成 TTS，逐句推送 `tts_sentence` 事件，实现“边说边生成”。"""
        normalized_text = (text or "").strip()
        if normalized_text == "":
            raise FailException("文本内容不能为空")

        normalized_message_id = str(message_id or "").strip()
        voice = "alex"
        conversation_id = ""
        resolved_message_id = ""
        if normalized_message_id != "":
            message, conversation = self._get_valid_message(normalized_message_id, account)
            voice = self._resolve_voice(message, conversation, account)
            conversation_id = str(conversation.id)
            resolved_message_id = str(message.id)

        sentences = self.split_sentences(normalized_text)
        if not sentences:
            raise FailException("文本内容不能为空")

        def stream() -> Generator:
            try:
                for index, sentence in enumerate(sentences):
                    response = self._create_tts_response(sentence, voice)
                    chunks: list[bytes] = []
                    try:
                        for chunk in response.iter_content(chunk_size=1024):
                            if chunk:
                                chunks.append(chunk)
                        audio = base64.b64encode(b"".join(chunks)).decode("ascii")
                        data = {
                            "conversation_id": conversation_id,
                            "message_id": resolved_message_id,
                            "sentence_index": index,
                            "sentence_count": len(sentences),
                            "sentence": sentence,
                            "audio": audio,
                        }
                        yield f"event: tts_sentence\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
                    finally:
                        response.close()
                yield f"event: tts_end\ndata: {json.dumps({'conversation_id': conversation_id, 'message_id': resolved_message_id})}\n\n"
            except Exception as error:
                logger.error("逐句语音输出失败: %(error)s", {"error": error}, exc_info=True)
                yield f"event: tts_error\ndata: {json.dumps({'error': '逐句语音输出失败'})}\n\n"

        return stream()
