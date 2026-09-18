"""本机渲染 worker：鉴权、入参校验、渲染调用、错误包装。"""
import json
from pathlib import Path

import pytest

from scripts import render_worker


def test_authorized_accepts_matching_bearer(monkeypatch):
    monkeypatch.setenv("RENDER_WORKER_TOKEN", "secret-token")
    assert render_worker._authorized("Bearer secret-token") is True


def test_authorized_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("RENDER_WORKER_TOKEN", "secret-token")
    assert render_worker._authorized("Bearer wrong") is False


def test_authorized_rejects_when_token_unset(monkeypatch):
    monkeypatch.delenv("RENDER_WORKER_TOKEN", raising=False)
    assert render_worker._authorized("Bearer anything") is False


def test_validate_payload_requires_segments():
    error = render_worker._validate_payload({"composition": {"duration": 10}})
    assert error is not None
    assert "segments" in error["error"]


def test_validate_payload_requires_composition_dict():
    error = render_worker._validate_payload({"composition": "not-a-dict"})
    assert error is not None
    assert "composition" in error["error"]


def test_validate_payload_accepts_valid():
    payload = {
        "composition": {
            "composition_id": "main",
            "width": 1920,
            "height": 1080,
            "duration": 10.0,
            "segments": [{"start": 0.0, "duration": 10.0, "text": "hi"}],
        }
    }
    assert render_worker._validate_payload(payload) is None


def test_run_render_returns_error_when_env_missing(monkeypatch):
    """缺少 HYPERFRAMES_* 路径时返回可读错误，不抛异常。"""
    for key in (
        "HYPERFRAMES_BROWSER_PATH",
        "HYPERFRAMES_FFMPEG_PATH",
        "HYPERFRAMES_FFPROBE_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    payload = {
        "composition": {
            "composition_id": "main",
            "width": 1920,
            "height": 1080,
            "duration": 10.0,
            "segments": [{"start": 0.0, "duration": 10.0, "text": "hi"}],
        }
    }
    result = render_worker._run_render(payload)
    assert result["ok"] is False
    assert "HYPERFRAMES" in result["error"]


def test_run_render_invokes_renderer_with_composition(monkeypatch, tmp_path):
    """渲染成功时返回产物字节与落盘路径，并保持与原产物一致。"""
    fake_mp4 = tmp_path / "out.mp4"
    fake_mp4.write_bytes(b"FAKE_MP4_BYTES")
    captured = {}

    def fake_render(composition_spec, *, output_path, settings):
        captured["spec"] = composition_spec
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(fake_mp4.read_bytes())
        return str(output_path)

    monkeypatch.setattr(render_worker, "_render_composition", fake_render)

    payload = {
        "composition": {
            "composition_id": "main",
            "width": 1920,
            "height": 1080,
            "duration": 10.0,
            "segments": [{"start": 0.0, "duration": 10.0, "text": "hi"}],
        },
        "name": "demo",
    }
    result = render_worker._run_render(payload)

    assert result["ok"] is True
    assert result["size_bytes"] == len(b"FAKE_MP4_BYTES")
    assert captured["spec"]["segments"][0]["text"] == "hi"
