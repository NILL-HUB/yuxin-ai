"""Realtime voice service unit tests."""

import asyncio
import math
import struct
import time

import pytest

from internal.service.realtime_voice_service import (
    RealtimeVoiceSession,
    RealtimeVoiceService,
    _is_control_command,
    _parse_sse_frame,
    _pcm_to_wav_bytes,
    _rms_int16,
)


@pytest.fixture(autouse=True)
def anyio_backend():
    # 环境未安装 trio，仅使用 asyncio 后端
    return "asyncio"


def _speech_chunk(seconds: float = 0.25, amplitude: int = 12000) -> bytes:
    sample_count = int(16000 * seconds)
    return b"".join(
        struct.pack(
            "<h",
            int(amplitude * math.sin(2 * math.pi * 220 * index / 16000)),
        )
        for index in range(sample_count)
    )


def _silence(seconds: float = 0.25) -> bytes:
    return bytes(int(16000 * seconds * 2))


def test_pcm_to_wav_bytes_writes_16bit_header() -> None:
    pcm = _speech_chunk(0.1)
    wav = _pcm_to_wav_bytes(pcm, 16000, 1, 2)
    fmt = struct.unpack("<HHIIHH", wav[20:36])
    assert fmt == (1, 1, 16000, 32000, 2, 16)
    assert wav[36:40] == b"data"
    assert struct.unpack("<I", wav[40:44])[0] == len(pcm)


def test_rms_int16() -> None:
    assert _rms_int16(b"") == 0.0
    assert _rms_int16(struct.pack("<hh", -32768, 32767)) > 20000
    assert _rms_int16(bytes(4000)) == 0.0


def test_parse_sse_frame() -> None:
    event, data = _parse_sse_frame("event: agent_message\ndata:{\"answer\":\"你好\"}\n\n")
    assert event == "agent_message"
    assert data == {"answer": "你好"}


def test_control_command_detection() -> None:
    assert _is_control_command("停止任务", ("停止",))
    assert _is_control_command("暂停一下", ("暂停",))
    assert not _is_control_command("请帮我继续处理", ("停止", "暂停"))


def test_vad_finalizes_after_silence() -> None:
    session = RealtimeVoiceSession(sid="s", account_id=0)
    assert session.append_audio(_speech_chunk(0.3)) == (False, b"")
    ready = False
    utterance = b""
    for _ in range(6):
        # 模拟真实时序：每 200ms 到达一个静音块
        ready, utterance = session.append_audio(_silence(0.2))
        time.sleep(0.21)
        if ready:
            break
    assert ready is True
    assert len(utterance) > 0


def test_vad_does_not_finalize_pure_silence() -> None:
    session = RealtimeVoiceSession(sid="s", account_id=0)
    ready, utterance = session.append_audio(_silence(1.0))
    assert ready is False
    assert utterance == b""
    assert session.pending_turn_ready() == (False, b"")


@pytest.mark.anyio
async def test_handle_audio_starts_turn_and_restarts_after_end(monkeypatch) -> None:
    service = RealtimeVoiceService()
    session = service.create_session("sid", account_id=0)

    processed = {}

    async def _fake_process(self, session_ref, turn_id, utterance):
        processed["turn_id"] = turn_id
        processed["bytes"] = len(utterance)

    monkeypatch.setattr(
        "internal.service.realtime_voice_service.RealtimeVoiceService._process_turn",
        _fake_process,
    )

    await service.handle_audio("sid", _speech_chunk(0.3))
    for _ in range(6):
        await service.handle_audio("sid", _silence(0.2))
        await asyncio.sleep(0.21)
    await asyncio.sleep(0.05)
    assert session._turn_seq == 1
    assert session.current_turn_id == "1"
    assert processed["turn_id"] == "1"
    assert processed["bytes"] > 0

    session.cancel()
    if session.turn_task is not None:
        session.turn_task.cancel()
        session.turn_task = None
    service.remove_session("sid")
