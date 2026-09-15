"""视频时长探测测试：解析 ffmpeg stderr 的 Duration 行，异常一律返回 0。"""
from internal.core.vision import vision_invoke


class TestProbeDurationSec:
    def test_parses_hh_mm_ss(self, monkeypatch):
        class _Result:
            stderr = b"  Duration: 00:01:30.50, start: 0.000000, bitrate: 1757 kb/s"

        monkeypatch.setattr(
            vision_invoke, "_run_ffmpeg_probe", lambda exe, path: _Result()
        )
        assert vision_invoke.probe_duration_sec("v.mp4") == 90.5

    def test_returns_zero_when_duration_line_absent(self, monkeypatch):
        class _Result:
            stderr = b"some unrelated ffmpeg output"

        monkeypatch.setattr(
            vision_invoke, "_run_ffmpeg_probe", lambda exe, path: _Result()
        )
        assert vision_invoke.probe_duration_sec("v.mp4") == 0.0

    def test_returns_zero_on_probe_exception(self, monkeypatch):
        def _boom(exe, path):
            raise RuntimeError("ffmpeg missing")

        monkeypatch.setattr(vision_invoke, "_run_ffmpeg_probe", _boom)
        assert vision_invoke.probe_duration_sec("v.mp4") == 0.0
