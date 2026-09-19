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


# ── 超龄残留目录清扫（sweep_stale_work_dirs） ──────────────────────────────
#
# 背景：成功渲染的目录刻意保留待 /artifact 取回后删除；若取回失败或根本没取
# （进程被杀 / 网络中断），用户设备 %TEMP% 下的 hf-local-render-* 会缓慢堆积。
# 故 worker 启动时清扫超龄残留。以下用例锁定安全边界与行为。


def _mk_work_dir(root: Path, name: str, *, age_sec: float, now: float) -> Path:
    """造一个 mtime 为 now-age_sec 的残留目录。"""
    import os as _os

    target = root / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "output.mp4").write_bytes(b"x")
    stamp = now - age_sec
    _os.utime(target, (stamp, stamp))
    return target


def test_sweep_removes_only_aged_render_dirs(tmp_path):
    now = 1_000_000.0
    stale = _mk_work_dir(tmp_path, "hf-local-render-old", age_sec=25 * 3600, now=now)
    fresh = _mk_work_dir(tmp_path, "hf-local-render-new", age_sec=60, now=now)
    # 非渲染目录：即便超龄也不能删（避免误删用户/其他程序的临时数据）
    unrelated = _mk_work_dir(tmp_path, "some-other-temp", age_sec=99 * 3600, now=now)

    removed = render_worker.sweep_stale_work_dirs(
        now=now, ttl_sec=24 * 3600, tmp_root=str(tmp_path)
    )

    assert removed == [str(stale)]
    assert not stale.exists(), "超龄残留目录应被删除"
    assert fresh.exists(), "未超龄目录不应被删除"
    assert unrelated.exists(), "非 hf-local-render- 前缀目录不应被删除"


def test_sweep_ignores_plain_files_with_matching_prefix(tmp_path):
    now = 1_000_000.0
    stray = tmp_path / "hf-local-render-not-a-dir"
    stray.write_text("x", encoding="utf-8")
    import os as _os

    _os.utime(stray, (now - 99 * 3600, now - 99 * 3600))

    removed = render_worker.sweep_stale_work_dirs(
        now=now, ttl_sec=3600, tmp_root=str(tmp_path)
    )

    assert removed == []
    assert stray.exists(), "同名文件不应被清扫逻辑删除"


def test_sweep_returns_empty_for_missing_root(tmp_path):
    missing = tmp_path / "does-not-exist"
    removed = render_worker.sweep_stale_work_dirs(
        now=1_000_000.0, ttl_sec=3600, tmp_root=str(missing)
    )
    assert removed == []


def test_work_dir_ttl_defaults_to_24h(monkeypatch):
    monkeypatch.delenv("RENDER_WORKER_WORK_DIR_TTL_SEC", raising=False)
    assert render_worker._work_dir_ttl_sec() == 24 * 3600


def test_work_dir_ttl_falls_back_on_invalid_value(monkeypatch):
    for bad in ("abc", "0", "-5"):
        monkeypatch.setenv("RENDER_WORKER_WORK_DIR_TTL_SEC", bad)
        assert render_worker._work_dir_ttl_sec() == 24 * 3600, f"{bad} 应回落默认值"


def test_work_dir_ttl_honors_env_override(monkeypatch):
    monkeypatch.setenv("RENDER_WORKER_WORK_DIR_TTL_SEC", "600")
    assert render_worker._work_dir_ttl_sec() == 600


def test_main_sweeps_before_serving(monkeypatch):
    """启动时必须调用清扫，否则残留仍会堆积（接线回归）。"""
    calls = {"swept": 0, "served": 0}

    def _fake_sweep(**kwargs):
        calls["swept"] += 1
        return []

    class _FakeServer:
        def __init__(self, addr, handler):
            pass

        def serve_forever(self):
            calls["served"] += 1
            raise KeyboardInterrupt  # 立即退出，避免阻塞测试

    monkeypatch.setenv("RENDER_WORKER_TOKEN", "tok")
    monkeypatch.setattr(render_worker, "sweep_stale_work_dirs", _fake_sweep)
    monkeypatch.setattr(render_worker, "ThreadingHTTPServer", _FakeServer)
    monkeypatch.setattr("sys.argv", ["render_worker"])

    with pytest.raises(KeyboardInterrupt):
        render_worker.main()

    assert calls["swept"] == 1, "main() 必须在 serve 前执行清扫"
    assert calls["served"] == 1


def test_main_ignores_sweep_failure(monkeypatch):
    """清扫失败不能阻断 worker 启动（否则一个临时目录问题就让渲染全挂）。"""
    served = {"n": 0}

    def _boom(**kwargs):
        raise OSError("permission denied")

    class _FakeServer:
        def __init__(self, addr, handler):
            pass

        def serve_forever(self):
            served["n"] += 1
            raise KeyboardInterrupt

    monkeypatch.setenv("RENDER_WORKER_TOKEN", "tok")
    monkeypatch.setattr(render_worker, "sweep_stale_work_dirs", _boom)
    monkeypatch.setattr(render_worker, "ThreadingHTTPServer", _FakeServer)
    monkeypatch.setattr("sys.argv", ["render_worker"])

    with pytest.raises(KeyboardInterrupt):
        render_worker.main()

    assert served["n"] == 1, "清扫失败仍应继续启动 worker"
