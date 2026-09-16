"""按时间区间密抽测试（L2 扩窗后的实际抽帧）。

与 `extract_video_frames_with_offsets` 的区别：后者总是从片头起算全片均匀，
本函数只在 `[start_sec, start_sec+duration_sec)` 内抽——这是 L2 成本可控的关键。
"""
import os

from internal.core.vision import vision_invoke


def _write_fake_frames(out_dir, count):
    paths = []
    for index in range(1, count + 1):
        path = os.path.join(out_dir, f"frame_{index:03d}.jpg")
        with open(path, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0fake")
        paths.append(path)
    return paths


class TestExtractFramesInRange:
    def test_returns_offsets_relative_to_video_timeline(self, monkeypatch, tmp_path):
        """偏移必须是**视频时间轴上的绝对位置**（start 起算再加窗口内偏移）。

        L2 新建的帧要与 L1 帧同处一条时间轴，否则「改细节」定位错位。
        """
        out_dir = str(tmp_path)
        captured = {}

        def _fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            _write_fake_frames(out_dir, 20)

            class _R:
                returncode = 0
                stderr = b""

            return _R()

        monkeypatch.setattr(vision_invoke, "_resolve_ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(vision_invoke.subprocess, "run", _fake_run)

        frames = vision_invoke.extract_video_frames_in_range(
            "v.mp4", out_dir, start_sec=20.0, duration_sec=10.0
        )

        assert len(frames) == 20
        offsets = [frame.time_offset for frame in frames]
        assert offsets == sorted(offsets)
        assert offsets[0] > 20.0, "窗口从 20s 起，首帧偏移必须大于 20s"
        assert offsets[-1] < 30.0, "末帧必须落在窗口内（30s 前）"

    def test_passes_ss_and_t_to_ffmpeg(self, monkeypatch, tmp_path):
        """必须用 -ss / -t 限定区间，否则会重扫全片（成本失控）。"""
        out_dir = str(tmp_path)
        captured = {}

        def _fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            _write_fake_frames(out_dir, 4)

            class _R:
                returncode = 0
                stderr = b""

            return _R()

        monkeypatch.setattr(vision_invoke, "_resolve_ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(vision_invoke.subprocess, "run", _fake_run)

        vision_invoke.extract_video_frames_in_range(
            "v.mp4", out_dir, start_sec=12.0, duration_sec=2.0
        )

        cmd = captured["cmd"]
        assert "-ss" in cmd and cmd[cmd.index("-ss") + 1] == "12.0"
        assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "2.0"
        joined = " ".join(cmd)
        assert "select=" not in joined, "不得用帧号取模"

    def test_respects_frame_count_override(self, monkeypatch, tmp_path):
        out_dir = str(tmp_path)
        captured = {}

        def _fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            _write_fake_frames(out_dir, 600)

            class _R:
                returncode = 0
                stderr = b""

            return _R()

        monkeypatch.setattr(vision_invoke, "_resolve_ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(vision_invoke.subprocess, "run", _fake_run)

        vision_invoke.extract_video_frames_in_range(
            "v.mp4", out_dir, start_sec=0.0, duration_sec=3600.0, frame_count=600
        )

        assert "-frames:v" in captured["cmd"]
        assert captured["cmd"][captured["cmd"].index("-frames:v") + 1] == "600"

    def test_raises_when_no_frame_produced(self, monkeypatch, tmp_path):
        def _fake_run(cmd, **kwargs):
            class _R:
                returncode = 0
                stderr = b""

            return _R()

        monkeypatch.setattr(vision_invoke, "_resolve_ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(vision_invoke.subprocess, "run", _fake_run)

        import pytest

        with pytest.raises(RuntimeError):
            vision_invoke.extract_video_frames_in_range(
                "v.mp4", str(tmp_path), start_sec=5.0, duration_sec=1.0
            )
