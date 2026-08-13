import base64
import json

from internal.core.tools.builtin_tools.providers.audio_tools.audio_tools import (
    AudioTranscribeTool,
    TtsSpeakTool,
    _fetch_audio_bytes,
)


class _FakeResponse:
    def iter_content(self, chunk_size):
        yield b"ID3"
        yield b"audio"


class _FakeAudioService:
    def __init__(self):
        self.tts_calls = []
        self.stt_calls = []

    def _create_tts_response(self, text, voice, language=""):
        self.tts_calls.append((text, voice, language))
        return _FakeResponse()

    def audio_to_text(self, storage, language="", provider="", model=""):
        self.stt_calls.append((language, provider, model))
        return "识别出来的文本"


def test_fetch_audio_bytes_from_data_uri():
    payload = base64.b64encode(b"abc").decode("ascii")
    assert _fetch_audio_bytes(f"data:audio/mpeg;base64,{payload}") == b"abc"


def test_tts_speak_returns_data_uri(monkeypatch):
    monkeypatch.setattr(
        "internal.core.tools.builtin_tools.providers.audio_tools.audio_tools._load_audio_service",
        lambda: _FakeAudioService(),
    )
    result = json.loads(TtsSpeakTool()._run(text="你好", voice="alex"))
    assert result["ok"] is True
    assert result["audio_data_uri"].startswith("data:audio/mpeg;base64,")
    assert base64.b64decode(result["audio_data_uri"].split(",", 1)[1]) == b"ID3audio"


def test_tts_speak_passes_language(monkeypatch):
    service = _FakeAudioService()
    monkeypatch.setattr(
        "internal.core.tools.builtin_tools.providers.audio_tools.audio_tools._load_audio_service",
        lambda: service,
    )
    result = json.loads(TtsSpeakTool()._run(text="你好", voice="alex", language="zh"))
    assert result["ok"] is True
    assert service.tts_calls == [("你好", "alex", "zh")]


def test_tts_speak_rejects_empty_text(monkeypatch):
    monkeypatch.setattr(
        "internal.core.tools.builtin_tools.providers.audio_tools.audio_tools._load_audio_service",
        lambda: _FakeAudioService(),
    )
    result = json.loads(TtsSpeakTool()._run(text="   "))
    assert result["ok"] is False


def test_audio_transcribe_returns_text(monkeypatch):
    service = _FakeAudioService()
    monkeypatch.setattr(
        "internal.core.tools.builtin_tools.providers.audio_tools.audio_tools._load_audio_service",
        lambda: service,
    )
    result = json.loads(AudioTranscribeTool()._run(audio_url="data:audio/wav;base64,AA=="))
    assert result["ok"] is True
    assert result["text"] == "识别出来的文本"
    assert service.stt_calls == [("", "", "")]


def test_audio_transcribe_passes_language_provider_model(monkeypatch):
    service = _FakeAudioService()
    monkeypatch.setattr(
        "internal.core.tools.builtin_tools.providers.audio_tools.audio_tools._load_audio_service",
        lambda: service,
    )
    result = json.loads(
        AudioTranscribeTool()._run(
            audio_url="data:audio/wav;base64,AA==",
            language="zh",
            provider="gpt_transcribe",
            model="custom/asr",
        )
    )
    assert result["ok"] is True
    assert service.stt_calls == [("zh", "gpt_transcribe", "custom/asr")]


def test_audio_transcribe_handles_failure(monkeypatch):
    class _BrokenService:
        def audio_to_text(self, storage, language="", provider="", model=""):
            raise RuntimeError("siliconflow down")

    monkeypatch.setattr(
        "internal.core.tools.builtin_tools.providers.audio_tools.audio_tools._load_audio_service",
        lambda: _BrokenService(),
    )
    result = json.loads(AudioTranscribeTool()._run(audio_url="data:audio/wav;base64,AA=="))
    assert result["ok"] is False
    assert "siliconflow down" in result["error"]
