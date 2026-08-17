"""Realtime voice session over Socket.IO.

客户端把 16kHz 单声道 PCM 音频持续推送到 ``/rt-voice`` 命名空间，
服务端在会话内做能量 VAD：检测到停顿后冻结当前语音段，转写为文本，
再调用辅助 Agent 的流式会话链路，并把答案按句合成 TTS 音频实时回传。

会话支持打断（barge-in）与停止：用户开口时客户端发 ``rt.barge``，
服务端取消当前 Agent 任务并停止 TTS；``rt.stop`` 则完全停止当前任务。
"""

import asyncio
import base64
import io
import json
import logging
import re
import struct
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from werkzeug.datastructures import FileStorage

from internal.core.agent.entities.queue_entity import QueueEvent


logger = logging.getLogger(__name__)

VOICE_NAMESPACE = "/rt-voice"

# 客户端上传的音频格式约定（前端 AudioContext 采集后降采样）
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLE_WIDTH = 2  # Int16

# VAD 参数：能量阈值与停顿判定
_SPEECH_RMS_THRESHOLD = 620.0
_SILENCE_END_MS = 850
_MAX_UTTERANCE_SECONDS = 30.0

_STOP_WORDS = ("停止", "停一下", "停下", "stop", "quit", "cancel")
_PAUSE_WORDS = ("暂停", "pause")


def _rms_int16(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    sample_count = len(pcm) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm[: sample_count * 2])
    sum_squares = sum(sample * sample for sample in samples)
    return (sum_squares / sample_count) ** 0.5


def _pcm_to_wav_bytes(pcm: bytes, sample_rate: int, channels: int, sample_width: int) -> bytes:
    """把 Int16 PCM 包装为 WAV，供 ASR 接口直接使用。"""
    buffer = io.BytesIO()
    data_size = len(pcm)
    byte_rate = sample_rate * channels * sample_width
    block_align = channels * sample_width
    buffer.write(b"RIFF")
    buffer.write(struct.pack("<I", 36 + data_size))
    buffer.write(b"WAVE")
    buffer.write(b"fmt ")
    buffer.write(struct.pack("<I", 16))
    buffer.write(struct.pack("<HHIIHH", 1, channels, sample_rate, byte_rate, block_align, sample_width * 8))
    buffer.write(b"data")
    buffer.write(struct.pack("<I", data_size))
    buffer.write(pcm)
    return buffer.getvalue()


def _parse_sse_frame(frame: str) -> tuple[str, dict[str, Any]]:
    """解析辅助 Agent 流式 SSE 帧，返回 (event, data)。"""
    event = ""
    data_lines: list[str] = []
    for line in str(frame).splitlines():
        if not line:
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not data_lines:
        return event, {}
    try:
        return event, json.loads("\n".join(data_lines))
    except (TypeError, ValueError):
        return event, {"answer": "\n".join(data_lines)}


def _is_control_command(text: str, words: tuple[str, ...]) -> bool:
    normalized = re.sub(r"[\s，。,．!?！？]+", "", str(text or "").lower())
    return any(word.lower() in normalized for word in words)


def _resolve_session_services():
    from app.http.module import injector
    from internal.service.assistant_agent_service import AssistantAgentService
    from internal.service.audio_service import AudioService

    return injector.get(AudioService), injector.get(AssistantAgentService)


@dataclass
class RealtimeVoiceSession:
    """单个 Socket 的实时语音会话状态。"""

    sid: str
    account_id: UUID
    sample_rate: int = DEFAULT_SAMPLE_RATE
    channels: int = DEFAULT_CHANNELS
    sample_width: int = DEFAULT_SAMPLE_WIDTH
    buffer: bytearray = field(default_factory=bytearray)
    pending_turn: bytes = b""
    lock: threading.Lock = field(default_factory=threading.Lock)
    turn_task: asyncio.Task | None = None
    drain_task: asyncio.Task | None = None
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    current_turn_id: str = ""
    current_message_id: str = ""
    paused: bool = False
    cancelled: bool = False
    _speech_active: bool = False
    _speech_seen: bool = False
    _last_voice_at: float = 0.0
    _last_silence_at: float = 0.0
    _turn_seq: int = 0

    def reset(self, sample_rate: int | None = None) -> None:
        with self.lock:
            self.buffer.clear()
            self._speech_active = False
            self._speech_seen = False
            self._last_voice_at = 0.0
            self._last_silence_at = 0.0
            if sample_rate:
                self.sample_rate = int(sample_rate)

    def append_audio(self, chunk: bytes) -> tuple[bool, bytes]:
        """追加音频并更新 VAD。

        返回 (是否结束本段语音, 冻结的语音字节)。语音段结束后立即冻结，
        避免新一轮音频混入本轮转写。
        """
        if not chunk:
            return False, b""
        with self.lock:
            if self.paused or self.cancelled:
                return False, b""
            self.buffer.extend(chunk)
            now = time.monotonic()
            rms = _rms_int16(bytes(chunk))
            if rms >= _SPEECH_RMS_THRESHOLD:
                self._speech_active = True
                self._speech_seen = True
                self._last_voice_at = now
                self._last_silence_at = now
                return False, b""
            if not self._speech_active:
                # 语音未开始或上一段已冻结：静音不触发新一轮转写
                if len(self.buffer) > self.sample_rate * self.channels * self.sample_width * 10:
                    self.buffer.clear()
                return False, b""
            self._last_silence_at = now
            silence_ms = (now - self._last_voice_at) * 1000.0
            if silence_ms < _SILENCE_END_MS:
                return False, b""
            max_seconds = self.sample_rate * self.channels * self.sample_width * _MAX_UTTERANCE_SECONDS
            if len(self.buffer) >= max_seconds:
                if self._speech_seen:
                    return True, self._freeze_locked()
                self.buffer.clear()
                self._speech_seen = False
                return False, b""
            if self._speech_seen:
                return True, self._freeze_locked()
            self.buffer.clear()
            self._speech_seen = False
            return False, b""

    def take_utterance(self) -> bytes:
        """冻结当前语音段，供转写线程使用。"""
        with self.lock:
            return self._freeze_locked()

    def _freeze_locked(self) -> bytes:
        """调用方必须已持有 lock。"""
        data = bytes(self.buffer)
        self.buffer.clear()
        self._speech_active = False
        self._speech_seen = False
        self._last_voice_at = 0.0
        self._last_silence_at = 0.0
        return data

    def pending_bytes(self) -> int:
        with self.lock:
            return len(self.buffer)

    def pending_turn_ready(self) -> tuple[bool, bytes]:
        with self.lock:
            if self.pending_turn:
                utterance, self.pending_turn = self.pending_turn, b""
                return True, utterance
            return False, b""

    def cancel(self) -> None:
        with self.lock:
            self.cancelled = True

    def resume(self) -> None:
        with self.lock:
            self.cancelled = False


class RealtimeVoiceService:
    """管理实时语音会话，并把音频转写/Agent 流/TTS 编排成 Socket 事件。"""

    def __init__(self) -> None:
        self._sessions: dict[str, RealtimeVoiceSession] = {}
        self._lock = threading.Lock()

    def create_session(self, sid: str, account_id: UUID) -> RealtimeVoiceSession:
        session = RealtimeVoiceSession(sid=sid, account_id=account_id)
        with self._lock:
            existing = self._sessions.get(sid)
            if existing:
                existing.cancel()
                existing.turn_task = None
            self._sessions[sid] = session
        return session

    def get_session(self, sid: str) -> RealtimeVoiceSession | None:
        with self._lock:
            return self._sessions.get(sid)

    def remove_session(self, sid: str) -> None:
        session = None
        with self._lock:
            session = self._sessions.pop(sid, None)
        if session:
            session.cancel()

    async def handle_audio(self, sid: str, chunk: bytes) -> None:
        """处理客户端上传的音频帧；语音段结束后启动转写任务。"""
        session = self.get_session(sid)
        if not session or not chunk:
            return
        turn_ready, utterance = session.append_audio(chunk)
        if turn_ready and utterance:
            if session.turn_task is None:
                await self._start_turn(session, utterance)
            else:
                # 上一轮仍在处理：挂起本轮，结束后再启动
                session.pending_turn = utterance

    async def _start_turn(self, session: RealtimeVoiceSession, utterance: bytes | None = None) -> None:
        if utterance is None:
            utterance = session.take_utterance()
        if not utterance or len(utterance) < 512:
            return
        if _rms_int16(utterance) < 400:
            # 无有效语音能量（背景噪声/静音），不进入转写
            return
        if session.turn_task is not None:
            return
        session._turn_seq += 1
        session.current_turn_id = str(session._turn_seq)
        turn_id = session.current_turn_id
        session.cancelled = False
        await session.queue.put({
            "event": "rt.state",
            "data": {"turn_id": turn_id, "state": "transcribing", "text": ""},
        })

        async def _run() -> None:
            try:
                await self._process_turn(session, turn_id, utterance)
            except asyncio.CancelledError:
                pass
            except Exception as error:
                logger.exception("realtime voice turn failed: %s", error)
                await self._emit(session, "rt.error", {"message": "语音会话处理失败"})
            finally:
                session.turn_task = None
                ready, queued = session.pending_turn_ready()
                if ready and _rms_int16(queued) >= 400:
                    await self._start_turn(session, queued)
                    return
                if not session.paused:
                    await self._emit(session, "rt.state", {"turn_id": turn_id, "state": "listening"})

        session.turn_task = asyncio.create_task(_run())

    async def _process_turn(self, session: RealtimeVoiceSession, turn_id: str, utterance: bytes) -> None:
        audio_service, assistant_service = await asyncio.to_thread(_resolve_session_services)

        transcript = await asyncio.to_thread(
            self._transcribe,
            audio_service,
            session,
            utterance,
        )
        transcript = str(transcript or "").strip()
        if not transcript:
            return

        await session.queue.put({
            "event": "rt.transcript",
            "data": {"turn_id": turn_id, "text": transcript, "final": True},
        })

        if session.cancelled:
            return
        if _is_control_command(transcript, _STOP_WORDS) or _is_control_command(transcript, _PAUSE_WORDS):
            self._stop_active_task(session, assistant_service)
            await session.queue.put({
                "event": "rt.control",
                "data": {"turn_id": turn_id, "action": "stop", "text": transcript},
            })
            session.paused = True
            await asyncio.sleep(1.2)
            session.paused = False
            session.resume()
            await self._emit(session, "rt.state", {"turn_id": turn_id, "state": "listening"})
            return

        await session.queue.put({
            "event": "rt.state",
            "data": {"turn_id": turn_id, "state": "thinking", "text": transcript},
        })
        await asyncio.to_thread(
            self._run_agent_turn,
            assistant_service,
            audio_service,
            session,
            transcript,
            turn_id,
        )

    @staticmethod
    def _transcribe(audio_service, session: RealtimeVoiceSession, utterance: bytes) -> str:
        wav_bytes = _pcm_to_wav_bytes(
            utterance,
            session.sample_rate,
            session.channels,
            session.sample_width,
        )
        storage = FileStorage(
            stream=io.BytesIO(wav_bytes),
            filename="realtime-voice.wav",
        )
        return audio_service.audio_to_text(storage, language="zh")

    @staticmethod
    def _stop_active_task(session: RealtimeVoiceSession, assistant_service) -> None:
        from internal.model import Account

        task_id = session.current_message_id
        if not task_id:
            session.cancel()
            return
        try:
            account = assistant_service.db.session.query(Account).filter_by(id=session.account_id).first()
        except Exception:
            account = None
        if account is not None:
            try:
                assistant_service.stop_chat(UUID(task_id), account, service=assistant_service)
            except Exception as error:
                logger.warning("realtime voice stop_chat failed: %s", error)
        session.cancel()

    @staticmethod
    def _run_agent_turn(
        assistant_service,
        audio_service,
        session: RealtimeVoiceSession,
        transcript: str,
        turn_id: str,
    ) -> None:
        from app.http.app import app as flask_app
        from internal.model import Account

        try:
            account = assistant_service.db.session.query(Account).filter_by(id=session.account_id).first()
        except Exception:
            account = None
        if account is None:
            return

        req = SimpleNamespace(
            query=SimpleNamespace(data=transcript),
            conversation_id=SimpleNamespace(data=""),
            image_urls=SimpleNamespace(data=[]),
            confirm_deep_thinking=SimpleNamespace(data=False),
        )
        try:
            with flask_app.app_context():
                generator = assistant_service.chat(req, account)
                RealtimeVoiceService._speak_agent_stream(generator, audio_service, session, turn_id)
        except Exception as error:
            logger.exception("realtime voice agent turn failed: %s", error)
            session.queue.put_nowait({
                "event": "rt.error",
                "data": {"turn_id": turn_id, "message": "Agent 执行失败"},
            })
        finally:
            from internal.extension.database_extension import db

            remove_session = getattr(db.session, "remove", None)
            if callable(remove_session):
                remove_session()

    @staticmethod
    def _speak_agent_stream(
        generator,
        audio_service,
        session: RealtimeVoiceSession,
        turn_id: str,
    ) -> None:
        answer_parts: list[str] = []
        message_id = ""
        conversation_id = ""

        for frame in generator:
            if session.cancelled:
                break
            event, data = _parse_sse_frame(frame)
            session.queue.put_nowait({
                "event": "rt.stream",
                "data": {
                    "turn_id": turn_id,
                    "event": event,
                    "data": data,
                },
            })
            if event == QueueEvent.AGENT_MESSAGE.value:
                if not message_id:
                    message_id = str(data.get("message_id") or data.get("id") or "")
                    if message_id:
                        session.current_message_id = message_id
                answer_chunk = str(data.get("answer") or data.get("thought") or "")
                if answer_chunk:
                    answer_parts.append(answer_chunk)
                    session.queue.put_nowait({
                        "event": "rt.agent",
                        "data": {"turn_id": turn_id, "delta": answer_chunk},
                    })
            elif event == QueueEvent.AGENT_END.value:
                message_id = str(data.get("message_id") or data.get("id") or "")
                conversation_id = str(data.get("conversation_id") or "")
                if message_id:
                    session.current_message_id = message_id
                break
            elif event == "error":
                session.queue.put_nowait({
                    "event": "rt.error",
                    "data": {"turn_id": turn_id, "message": "Agent 返回错误"},
                })
                break

        if session.cancelled:
            return

        answer = "".join(answer_parts).strip()
        if not answer:
            return

        sentences = audio_service.split_sentences(answer)
        if not sentences:
            sentences = [answer]
        session.queue.put_nowait({
            "event": "rt.state",
            "data": {"turn_id": turn_id, "state": "speaking", "text": answer},
        })
        for index, sentence in enumerate(sentences):
            if session.cancelled:
                break
            try:
                response = audio_service._create_tts_response(sentence, "alex", language="zh")
            except Exception as error:
                logger.warning("realtime voice TTS failed for sentence: %s", error)
                continue
            try:
                chunks: list[bytes] = []
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        chunks.append(chunk)
                audio = base64.b64encode(b"".join(chunks)).decode("ascii")
                session.queue.put_nowait({
                    "event": "rt.audio",
                    "data": {
                        "turn_id": turn_id,
                        "message_id": message_id,
                        "conversation_id": conversation_id,
                        "sentence_index": index,
                        "sentence_count": len(sentences),
                        "sentence": sentence,
                        "audio": audio,
                        "final": index == len(sentences) - 1,
                    },
                })
            finally:
                response.close()

        session.queue.put_nowait({
            "event": "rt.state",
            "data": {"turn_id": turn_id, "state": "listening", "text": answer},
        })
        session.queue.put_nowait({
            "event": "rt.turn-complete",
            "data": {"turn_id": turn_id},
        })

    async def _emit(self, session: RealtimeVoiceSession, event: str, data: dict[str, Any]) -> None:
        await session.queue.put({"event": event, "data": data})

    async def handle_barge(self, sid: str) -> None:
        """用户开口打断：取消当前 Agent 任务与 TTS，立即回到聆听态。"""
        session = self.get_session(sid)
        if not session:
            return
        session.cancel()
        if session.turn_task is not None:
            session.turn_task.cancel()
            session.turn_task = None
        _, assistant_service = await asyncio.to_thread(_resolve_session_services)
        await asyncio.to_thread(self._stop_active_task, session, assistant_service)
        session.paused = False
        session.resume()
        await self._emit(session, "rt.state", {"turn_id": session.current_turn_id, "state": "listening"})

    async def handle_pause(self, sid: str) -> None:
        session = self.get_session(sid)
        if not session:
            return
        session.cancel()
        if session.turn_task is not None:
            session.turn_task.cancel()
            session.turn_task = None
        session.paused = True
        await self._emit(session, "rt.state", {"turn_id": session.current_turn_id, "state": "paused"})

    async def handle_stop(self, sid: str) -> None:
        """完全停止当前任务并暂停会话，等待用户再次恢复。"""
        session = self.get_session(sid)
        if not session:
            return
        session.cancel()
        if session.turn_task is not None:
            session.turn_task.cancel()
            session.turn_task = None
        _, assistant_service = await asyncio.to_thread(_resolve_session_services)
        await asyncio.to_thread(self._stop_active_task, session, assistant_service)
        session.paused = True
        await self._emit(session, "rt.state", {"turn_id": session.current_turn_id, "state": "paused"})

    async def handle_resume(self, sid: str) -> None:
        session = self.get_session(sid)
        if not session:
            return
        session.paused = False
        session.resume()
        await self._emit(session, "rt.state", {"turn_id": session.current_turn_id, "state": "listening"})
