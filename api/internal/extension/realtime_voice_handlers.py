"""Socket.IO 实时语音命名空间处理器。

命名空间：``/rt-voice``

客户端事件：
- ``rt.start``：初始化会话（携带 sample_rate 等音频参数）
- ``rt.audio``：PCM 音频帧（二进制）
- ``rt.barge``：用户开口打断当前 Agent 输出
- ``rt.pause``：暂停聆听
- ``rt.resume``：恢复聆听
- ``rt.stop``：完全停止当前任务

服务端事件：
- ``rt.state``：会话状态（listening / transcribing / thinking / speaking / paused）
- ``rt.transcript``：转写结果（final=True 表示本段语音结束）
- ``rt.agent``：Agent 流式文本增量
- ``rt.audio``：TTS 音频段（base64 MP3）
- ``rt.control``：语音控制指令执行结果
- ``rt.error``：错误信息
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

from internal.service import JwtService
from internal.service.account_service import AccountService
from internal.service.realtime_voice_service import (
    DEFAULT_SAMPLE_RATE,
    RealtimeVoiceService,
    VOICE_NAMESPACE,
)


logger = logging.getLogger(__name__)


def _get_voice_service() -> RealtimeVoiceService:
    from app.http.module import injector

    return injector.get(RealtimeVoiceService)


def _resolve_account_id(auth: dict[str, Any] | None = None) -> UUID | None:
    from app.http.module import injector

    payload = auth or {}
    token = str(payload.get("token", "") or "").strip()
    if not token:
        return None
    try:
        jwt_service = injector.get(JwtService)
        account_service = injector.get(AccountService)
        token_payload = jwt_service.parse_token(token)
        account_service.validate_access_session(token_payload)
        account_id = str(token_payload.get("sub", "") or "").strip()
        if not account_id:
            return None
        return UUID(account_id)
    except Exception:
        logger.warning("[rt-voice] auth failed", exc_info=True)
        return None


async def _drain_session(
    socketio,
    sid: str,
    session_queue: asyncio.Queue,
) -> None:
    """把会话事件队列转发到 Socket 客户端。"""
    try:
        while True:
            payload = await session_queue.get()
            if payload is None:
                break
            event = payload.get("event")
            data = payload.get("data") or {}
            try:
                await socketio.emit(event, data, to=sid, namespace=VOICE_NAMESPACE)
            except Exception:
                logger.warning("[rt-voice] emit failed event=%s sid=%s", event, sid, exc_info=True)
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning("[rt-voice] drain loop exited sid=%s", sid, exc_info=True)


async def handle_connect(sid: str, environ: dict[str, Any] | None = None, auth: dict[str, Any] | None = None) -> bool:
    account_id = _resolve_account_id(auth)
    if account_id is None:
        logger.warning("[rt-voice] rejected sid=%s", sid)
        return False

    service = _get_voice_service()
    session = service.create_session(sid, account_id)
    session.sample_rate = DEFAULT_SAMPLE_RATE

    from internal.extension.socketio_extension import get_socketio

    socketio = get_socketio()
    if socketio is not None:
        session.drain_task = asyncio.create_task(
            _drain_session(socketio, sid, session.queue)
        )
    await socketio.emit(
        "rt.state",
        {"state": "listening", "sample_rate": session.sample_rate},
        to=sid,
        namespace=VOICE_NAMESPACE,
    )
    return True


async def handle_disconnect(sid: str) -> None:
    service = _get_voice_service()
    session = service.get_session(sid)
    if session is not None:
        session.cancel()
        drain_task = getattr(session, "drain_task", None)
        if drain_task is not None:
            drain_task.cancel()
    service.remove_session(sid)


async def handle_start(sid: str, data: dict[str, Any] | None = None) -> None:
    service = _get_voice_service()
    session = service.get_session(sid)
    if session is None:
        return
    payload = data or {}
    try:
        sample_rate = int(payload.get("sample_rate") or DEFAULT_SAMPLE_RATE)
    except (TypeError, ValueError):
        sample_rate = DEFAULT_SAMPLE_RATE
    session.reset(sample_rate=sample_rate)
    session.paused = False
    session.resume()

    from internal.extension.socketio_extension import get_socketio

    await get_socketio().emit(
        "rt.state",
        {"state": "listening", "sample_rate": sample_rate},
        to=sid,
        namespace=VOICE_NAMESPACE,
    )


async def handle_audio(sid: str, chunk: Any) -> None:
    if not isinstance(chunk, (bytes, bytearray, memoryview)):
        logger.warning("[rt-voice] audio chunk unexpected type sid=%s type=%s", sid, type(chunk).__name__)
        return
    await _get_voice_service().handle_audio(sid, bytes(chunk))


async def handle_barge(sid: str, data: dict[str, Any] | None = None) -> None:
    await _get_voice_service().handle_barge(sid)


async def handle_pause(sid: str, data: dict[str, Any] | None = None) -> None:
    await _get_voice_service().handle_pause(sid)


async def handle_resume(sid: str, data: dict[str, Any] | None = None) -> None:
    await _get_voice_service().handle_resume(sid)


async def handle_stop(sid: str, data: dict[str, Any] | None = None) -> None:
    await _get_voice_service().handle_stop(sid)


def register_realtime_voice_handlers(socketio) -> None:
    socketio.on("connect", handle_connect, namespace=VOICE_NAMESPACE)
    socketio.on("disconnect", handle_disconnect, namespace=VOICE_NAMESPACE)
    socketio.on("rt.start", handle_start, namespace=VOICE_NAMESPACE)
    socketio.on("rt.audio", handle_audio, namespace=VOICE_NAMESPACE)
    socketio.on("rt.barge", handle_barge, namespace=VOICE_NAMESPACE)
    socketio.on("rt.pause", handle_pause, namespace=VOICE_NAMESPACE)
    socketio.on("rt.resume", handle_resume, namespace=VOICE_NAMESPACE)
    socketio.on("rt.stop", handle_stop, namespace=VOICE_NAMESPACE)
