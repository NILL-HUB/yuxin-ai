"""均匀抽帧测试：替换 `select=not(mod(n,100))` + 硬截断的旧实现。

旧实现无论视频多长都只取开头若干帧（关键缺陷）。
"""
import os

from internal.core.vision import vision_invoke


def _write_fake_frames(out_dir, count):
    """预置帧文件，模拟 ffmpeg 产出。"""
    paths = []
    for index in range(1, count + 1):
        path = os.path.join(out_dir, f"frame_{index:03d}.jpg")
        with open(path, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0fake")
        paths.append(path)
    return paths


def _requested_frames(cmd):
    """取出命令里的 `-frames:v` 值，模拟真实 ffmpeg「按请求帧数产出」。"""
    return int(cmd[cmd.index("-frames:v") + 1])


class TestExtractVideoFramesWithOffsets:
    def test_returns_offset_per_frame(self, monkeypatch, tmp_path):
        out_dir = str(tmp_path)

        def _fake_run(cmd, **kwargs):
            _write_fake_frames(out_dir, _requested_frames(cmd))

            class _R:
                returncode = 0
                stderr = b""

            return _R()

        monkeypatch.setattr(vision_invoke, "_resolve_ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(vision_invoke, "probe_duration_sec", lambda p: 60.0)
        monkeypatch.setattr(vision_invoke.subprocess, "run", _fake_run)

        frames = vision_invoke.extract_video_frames_with_offsets("v.mp4", out_dir)

        assert len(frames) == 12
        assert all(frame.time_offset is not None for frame in frames)
        # 时间偏移必须递增且覆盖全片
        offsets = [frame.time_offset for frame in frames]
        assert offsets == sorted(offsets)
        assert offsets[-1] > 60.0 * 0.8

    def test_keeps_real_offsets_when_fewer_frames_produced(self, monkeypatch, tmp_path):
        """少产帧时保留真实前缀偏移，不得把全片重新摊开（否则元数据失真）。

        `fps=1/interval` 自片头起算，少产必然是同一条时间线上的前 k 帧，
        其真实位置就是计划偏移的前 k 项。L2 靠 time_offset 定位区间，
        若按实际帧数重排会静默抽错片段。
        """
        out_dir = str(tmp_path)

        def _fake_run(cmd, **kwargs):
            _write_fake_frames(out_dir, 6)

            class _R:
                returncode = 0
                stderr = b""

            return _R()

        monkeypatch.setattr(vision_invoke, "_resolve_ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(vision_invoke, "probe_duration_sec", lambda p: 60.0)
        monkeypatch.setattr(vision_invoke.subprocess, "run", _fake_run)

        frames = vision_invoke.extract_video_frames_with_offsets("v.mp4", out_dir)

        expected = [round(5.0 * (index + 0.5), 3) for index in range(6)]
        assert [frame.time_offset for frame in frames] == expected

    def test_uses_duration_based_count_not_fixed_three(self, monkeypatch, tmp_path):
        """关键回归：60 秒视频应抽 12 帧，而非固定 3 帧。"""
        out_dir = str(tmp_path)
        captured = {}

        def _fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            _write_fake_frames(out_dir, 12)

            class _R:
                returncode = 0
                stderr = b""

            return _R()

        monkeypatch.setattr(vision_invoke, "_resolve_ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(vision_invoke, "probe_duration_sec", lambda p: 60.0)
        monkeypatch.setattr(vision_invoke.subprocess, "run", _fake_run)

        frames = vision_invoke.extract_video_frames_with_offsets("v.mp4", out_dir)

        assert len(frames) == 12
        joined = " ".join(captured["cmd"])
        assert "select=" not in joined, "不得再用帧号取模的旧采样方式"

    def test_falls_back_to_single_frame_when_duration_unknown(self, monkeypatch, tmp_path):
        """时长探测失败时退回首帧兜底，不崩溃（避免无时长视频直接解析失败）。"""
        out_dir = str(tmp_path)
        dumped = {}

        def _fake_dump(video_path, target_path, exe):
            dumped["called"] = True
            with open(target_path, "wb") as fh:
                fh.write(b"\xff\xd8\xff\xe0first")
            return target_path

        monkeypatch.setattr(vision_invoke, "_resolve_ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(vision_invoke, "probe_duration_sec", lambda p: 0.0)
        monkeypatch.setattr(vision_invoke, "_dump_first_frame", _fake_dump)

        frames = vision_invoke.extract_video_frames_with_offsets("v.mp4", out_dir)

        assert dumped["called"] is True
        assert len(frames) == 1
        assert frames[0].time_offset == 0.0

    def test_raises_when_no_frame_produced(self, monkeypatch, tmp_path):
        def _fake_run(cmd, **kwargs):
            class _R:
                returncode = 0
                stderr = b""

            return _R()

        def _fake_dump(video_path, target_path, exe):
            raise RuntimeError("ffmpeg 无法解码")

        monkeypatch.setattr(vision_invoke, "_resolve_ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(vision_invoke, "probe_duration_sec", lambda p: 30.0)
        monkeypatch.setattr(vision_invoke.subprocess, "run", _fake_run)
        monkeypatch.setattr(vision_invoke, "_dump_first_frame", _fake_dump)

        import pytest

        with pytest.raises(RuntimeError):
            vision_invoke.extract_video_frames_with_offsets("v.mp4", str(tmp_path))
