# 视频分层抽帧与帧配额 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让视频抽帧从「固定 3 帧且只取开头」改为「随时长动态、全片均匀」，为帧补上 `time_offset` 定位能力，并让帧计入/释放存储配额。

**Architecture:** 抽帧策略抽为纯函数便于单测；底层新增「按间隔均匀抽帧 + 返回时间偏移」的入口，媒体提取器与索引链路逐层透传 `time_offset`；配额侧给 `consume_quota` 增加「预留但不计入」参数，并在回收站销毁时成对释放帧占用。

**Tech Stack:** Python 3.12、ffmpeg（系统或 `imageio-ffmpeg` 兜底）、SQLAlchemy、Celery、pytest。

**依据规格：** [2026-09-16-video-production-p4-design.md](../specs/2026-09-16-video-production-p4-design.md) §5、§6

---

## 范围说明

本规格含三个相互独立的子系统，拆为三份计划：

| 计划 | 内容 | 状态 |
| --- | --- | --- |
| **本计划** | 分层抽帧 + `time_offset` + 帧配额（计费/释放） | 本次实施 |
| 计划 2 | L2 区间密抽（窗口推导 + 600 帧上限 + 显式区间） | 待编写 |
| 计划 3 | HyperFrames 渲染（编/生/渲三层 + render 队列 + 成品库） | 待编写 |

**本计划是其余两份的前置**：`time_offset` 与帧配额是 L2 与渲染链路的共同依赖。

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `api/internal/core/vision/frame_sampling.py`（新建） | 抽帧策略纯函数：帧数、间隔、时间偏移计算。无 IO，易测。 |
| `api/internal/core/vision/vision_invoke.py`（修改） | 新增时长探测与「均匀抽帧 + 时间偏移」；保留既有返回 data URI 的接口不动 |
| `api/internal/entity/storage_quota_entity.py`（修改） | 新增解析预留常量 |
| `api/internal/service/storage_quota_service.py`（修改） | `consume_quota` 支持 `reserve_bytes`（校验含预留、但不计入已用） |
| `api/internal/service/chunked_upload_service.py`（修改） | 分片上传/秒传的配额校验带上解析预留 |
| `api/internal/service/storage/runtime_storage_service.py`（修改） | 运行时上传的配额校验带上解析预留 |
| `api/internal/service/knowledge_media_extractor_service.py`（修改） | 接入动态抽帧；帧 metadata 写入 `time_offset`；帧计入配额 |
| `api/internal/service/knowledge_indexing_service.py`（修改） | `_segment_frame` / `_collect_frames` 透传 `time_offset` |
| `api/internal/service/recycle_bin_handlers.py`（修改） | `snapshot_knowledge_document` 采集帧文件；`purge_knowledge_document` 清理帧并释放配额 |

---

## Task 1: 抽帧策略纯函数

**Files:**
- Create: `api/internal/core/vision/frame_sampling.py`
- Test: `api/test/internal/core/vision/test_frame_sampling.py`

- [ ] **Step 1: 写失败测试**

```python
"""抽帧策略纯函数测试：帧数随时长对数增长，1 小时触顶 60 帧。"""
import pytest

from internal.core.vision.frame_sampling import (
    L1_MAX_FRAMES,
    L1_MIN_FRAMES,
    plan_frame_offsets,
    resolve_l1_frame_count,
)


class TestResolveL1FrameCount:
    def test_short_video_hits_lower_bound(self):
        """10 秒视频取下限，不会稀疏到 1 帧。"""
        assert resolve_l1_frame_count(10) == L1_MIN_FRAMES

    def test_one_hour_hits_upper_bound(self):
        """1 小时恰好触顶 60 帧。"""
        assert resolve_l1_frame_count(3600) == L1_MAX_FRAMES

    def test_beyond_one_hour_stays_capped(self):
        """超过 1 小时不再增长（封顶）。"""
        assert resolve_l1_frame_count(7200) == L1_MAX_FRAMES
        assert resolve_l1_frame_count(14400) == L1_MAX_FRAMES

    def test_grows_monotonically_with_duration(self):
        durations = [10, 60, 300, 1800, 3600]
        counts = [resolve_l1_frame_count(d) for d in durations]
        assert counts == sorted(counts)

    def test_minute_video_has_more_frames_than_ten_seconds(self):
        assert resolve_l1_frame_count(60) > resolve_l1_frame_count(10)

    def test_zero_or_negative_duration_is_safe(self):
        """异常时长不得崩溃，退回下限。"""
        assert resolve_l1_frame_count(0) == L1_MIN_FRAMES
        assert resolve_l1_frame_count(-5) == L1_MIN_FRAMES


class TestPlanFrameOffsets:
    def test_offsets_are_evenly_spaced(self):
        offsets = plan_frame_offsets(60.0)
        count = resolve_l1_frame_count(60)
        assert len(offsets) == count
        gaps = [round(b - a, 6) for a, b in zip(offsets, offsets[1:])]
        assert len(set(gaps)) == 1, f"间隔应一致，实际 {gaps}"

    def test_first_offset_is_midpoint_of_first_slot(self):
        """首帧取第一个区间的中点，避免永远取到片头黑帧。"""
        offsets = plan_frame_offsets(60.0)
        count = resolve_l1_frame_count(60)
        assert offsets[0] == pytest.approx(60.0 / count / 2, abs=0.01)

    def test_offsets_cover_whole_video_not_only_opening(self):
        """关键回归：最后一帧必须落在视频后段，而非只覆盖开头。"""
        offsets = plan_frame_offsets(3600.0)
        assert offsets[-1] > 3600.0 * 0.9

    def test_offsets_are_within_duration(self):
        for duration in (10.0, 60.0, 3600.0):
            for offset in plan_frame_offsets(duration):
                assert 0 <= offset < duration

    def test_zero_duration_returns_empty(self):
        assert plan_frame_offsets(0) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/core/vision/test_frame_sampling.py -q --no-header --no-cov`
Expected: FAIL —— `ModuleNotFoundError: No module named 'internal.core.vision.frame_sampling'`

- [ ] **Step 3: 实现**

```python
"""视频抽帧策略（纯函数，无 IO）。

**为什么独立成模块**：抽帧帧数/间隔是产品策略（成本与覆盖度的折中），
与 ffmpeg 调用这种 IO 关注点分开，便于单测与后续调整。

L1 帧数随时长**对数增长**：
- 下限 6 帧：10 秒级短视频也能覆盖首中尾，不退化成 1 帧；
- 上限 60 帧且在 **1 小时处触顶**（即最长 1 分钟 1 帧），避免长视频帧数
  无界增长导致视觉模型调用成本失控。

公式 `round(8·log2(sec) − 35)` 经实测校验：3600s 恰为 60 帧。
"""
from __future__ import annotations

import math

# L1 帧数上下限
L1_MIN_FRAMES = 6
L1_MAX_FRAMES = 60
# 1 小时触顶（秒）
L1_CAP_DURATION_SEC = 3600

_LOG_MULTIPLIER = 8
_LOG_OFFSET = 35


def resolve_l1_frame_count(duration_sec: float) -> int:
    """按视频时长解析 L1 抽帧数量。

    异常/缺失时长（<=0）退回下限，保证调用方无需额外判空。
    """
    try:
        duration = float(duration_sec)
    except (TypeError, ValueError):
        return L1_MIN_FRAMES
    if duration <= 0:
        return L1_MIN_FRAMES
    raw = round(_LOG_MULTIPLIER * math.log2(duration) - _LOG_OFFSET)
    return max(L1_MIN_FRAMES, min(L1_MAX_FRAMES, raw))


def plan_frame_offsets(duration_sec: float) -> list[float]:
    """给出 L1 各帧在视频中的时间偏移（秒），全片均匀分布。

    取每个等分区间的**中点**：若取区间起点，首帧永远是 0（片头黑场/台标），
    对「能被找到」没有价值。
    """
    try:
        duration = float(duration_sec)
    except (TypeError, ValueError):
        return []
    if duration <= 0:
        return []
    count = resolve_l1_frame_count(duration)
    slot = duration / count
    return [round(slot * (index + 0.5), 3) for index in range(count)]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/core/vision/test_frame_sampling.py -q --no-header --no-cov`
Expected: PASS（11 个用例：`TestResolveL1FrameCount` 6 个 + `TestPlanFrameOffsets` 5 个）

- [ ] **Step 5: 提交**

```bash
git add api/internal/core/vision/frame_sampling.py api/test/internal/core/vision/test_frame_sampling.py
git commit -m "feat(vision): add duration-based L1 frame sampling policy"
```

---

## Task 2: 视频时长探测

**Files:**
- Modify: `api/internal/core/vision/vision_invoke.py`
- Test: `api/test/internal/core/vision/test_probe_duration.py`

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/core/vision/test_probe_duration.py -q --no-header --no-cov`
Expected: FAIL —— `AttributeError: module ... has no attribute 'probe_duration_sec'`

- [ ] **Step 3: 实现**

在 `vision_invoke.py` 的 `_duration_to_ms` 之后新增：

```python
def _run_ffmpeg_probe(exe: str, video_path: str):
    """执行 ffmpeg 探测（独立方法便于测试替换，避免单测依赖真实 ffmpeg）。"""
    return subprocess.run(
        [exe, "-i", video_path], capture_output=True, timeout=_FRAME_TIMEOUT
    )


def probe_duration_sec(video_path: str) -> float:
    """探测视频时长（秒）；无法探测时返回 0.0（由调用方退回默认帧数）。

    ffmpeg 无 ffprobe 依赖也能给出 Duration 行，故复用同一可执行文件，
    不额外要求 ffprobe 存在。
    """
    try:
        exe = _resolve_ffmpeg_exe()
        result = _run_ffmpeg_probe(exe, video_path)
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")
    except Exception:
        logger.warning("视频时长探测失败 path=%s", video_path, exc_info=True)
        return 0.0
    for line in stderr.splitlines():
        if "Duration:" in line:
            raw = line.split("Duration:")[1].split(",")[0].strip()
            return _duration_to_ms(raw) / 1000.0
    return 0.0
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/core/vision/test_probe_duration.py -q --no-header --no-cov`
Expected: PASS（3 个用例）

- [ ] **Step 5: 提交**

```bash
git add api/internal/core/vision/vision_invoke.py api/test/internal/core/vision/test_probe_duration.py
git commit -m "feat(vision): add video duration probe"
```

---

## Task 3: 均匀抽帧并返回时间偏移

**Files:**
- Modify: `api/internal/core/vision/vision_invoke.py`
- Test: `api/test/internal/core/vision/test_uniform_frame_extraction.py`

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/core/vision/test_uniform_frame_extraction.py -q --no-header --no-cov`
Expected: FAIL —— `AttributeError: module ... has no attribute 'extract_video_frames_with_offsets'`

- [ ] **Step 3: 实现**

在 `vision_invoke.py` 顶部 import 增补：

```python
from dataclasses import dataclass

from internal.core.vision.frame_sampling import (
    plan_frame_offsets,
    resolve_l1_frame_count,
)
```

在 `extract_video_frames_to_dir` 之后新增：

```python
@dataclass
class ExtractedFrame:
    """抽出的帧文件及其在视频中的时间偏移（秒）。"""

    path: str
    time_offset: float


def _extract_frames_by_interval(
    exe: str, video_path: str, out_dir: str, interval_sec: float, max_frames: int
) -> None:
    """按固定时间间隔抽帧。

    用 `fps=1/interval` 而非帧号取模：后者依赖源帧率，同一策略在不同帧率
    视频上会得到不同的采样密度；按时间间隔才与「时长」这一产品维度一致。
    """
    pattern = os.path.join(out_dir, "frame_%03d.jpg")
    fps = 1.0 / max(interval_sec, 0.001)
    cmd = [
        exe, "-y", "-i", video_path,
        "-vf", f"fps={fps:.6f}",
        "-frames:v", str(max_frames),
        "-q:v", "4", pattern,
    ]
    subprocess.run(cmd, capture_output=True, timeout=_FRAME_TIMEOUT * 6, check=True)


def extract_video_frames_with_offsets(
    video_path: str,
    out_dir: str,
    frame_count: int | None = None,
) -> list[ExtractedFrame]:
    """按视频时长均匀抽帧，返回帧文件与各自的时间偏移。

    与 `extract_video_frames_to_dir` 的区别：后者只给路径、无时间信息，
    且上层若传固定帧数会退化成「只取开头」。本函数按 `frame_sampling`
    的策略全片均匀取帧——这是「改细节」能定位到片段的前提。

    frame_count 显式传入时按传入值抽（供 L2 区间密抽复用）。
    """
    duration = probe_duration_sec(video_path)
    if frame_count is not None:
        count = max(1, int(frame_count))
        offsets = (
            [round(duration / count * (i + 0.5), 3) for i in range(count)]
            if duration > 0
            else [0.0] * count
        )
    else:
        count = resolve_l1_frame_count(duration)
        offsets = plan_frame_offsets(duration)
        if not offsets:
            # 时长不可得：退回下限帧数，偏移未知记 0
            count = resolve_l1_frame_count(0)
            offsets = [0.0] * count

    os.makedirs(out_dir, exist_ok=True)
    if duration > 0:
        _extract_frames_by_interval(
            _resolve_ffmpeg_exe(), video_path, out_dir, duration / count, count
        )

    paths = _list_frame_files(out_dir)
    if not paths:
        # 时长不可得（或按间隔抽帧未产出）：退回「抽首帧」保证仍有产物。
        # 注意顺序——必须先尝试兜底再判定失败，否则兜底分支不可达。
        first = os.path.join(out_dir, "frame_001.jpg")
        _dump_first_frame(video_path, first, _resolve_ffmpeg_exe())
        paths = _list_frame_files(out_dir)

    if not paths:
        raise RuntimeError("视频抽帧未产出任何文件")

    return [
        ExtractedFrame(
            path=path,
            time_offset=float(offsets[index]) if index < len(offsets) else 0.0,
        )
        for index, path in enumerate(paths)
    ]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/core/vision/test_uniform_frame_extraction.py -q --no-header --no-cov`
Expected: PASS（5 个用例）

> 不变量：`time_offset` 与帧文件按下标一一对应，**不得**因实际产出帧数少而把全片重排。
> `fps=1/interval` 自片头起算，少产必然是同一条时间线上的前 k 帧，其真实位置是计划偏移的前 k 项；
> 重排会给位于片头 2.5s 的帧标上 5.0s，属伪造元数据，会让 L2 静默抽错片段。


- [ ] **Step 5: 提交**

```bash
git add api/internal/core/vision/vision_invoke.py api/test/internal/core/vision/test_uniform_frame_extraction.py
git commit -m "feat(vision): extract frames uniformly by duration with time offsets"
```

---

## Task 4: 媒体提取器接入动态抽帧并写入 `time_offset`

**Files:**
- Modify: `api/internal/service/knowledge_media_extractor_service.py:147-152,216-278`
- Test: `api/test/internal/service/test_video_frame_offsets.py`

- [ ] **Step 1: 写失败测试**

```python
"""视频帧 time_offset 落库测试。

设计稿 §4.2「改细节」依赖片段时间定位，而现状帧 metadata 只有 scene_index，
无任何时间信息——本测试锁定该能力。
"""
from types import SimpleNamespace
from uuid import uuid4

from internal.core.vision.vision_invoke import ExtractedFrame
from internal.service.knowledge_media_extractor_service import (
    KnowledgeMediaExtractorService,
)


class _FakeStorage:
    """模拟对象存储：下载写字节，上传返回带 key 的产物记录。

    必须实现 upload_bytes——否则 _persist_frame 抛错被降级为 frame_url=""，
    用例按 frame_url 过滤会得到 0 个片段，断言「看起来失败」而非「确实校验」。
    """

    def download_file(self, key, target_path):
        with open(target_path, "wb") as fh:
            fh.write(b"video-bytes")

    def upload_bytes(self, filename, content, **_kwargs):
        return SimpleNamespace(key=f"frames/{filename}", size=len(content))


class _FakeUploadFileService:
    def __init__(self):
        self.calls = []

    def create_upload_file(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(key=kwargs["key"])


def _upload():
    return SimpleNamespace(
        id=uuid4(), key=f"2026/09/16/{uuid4()}.mp4", name="clip.mp4",
        extension="mp4", mime_type="video/mp4",
    )


def _document():
    return SimpleNamespace(
        id=uuid4(), media_type="video",
        knowledge_base_id=uuid4(), owner_account_id=uuid4(),
    )


def _video_service(frames):
    """构造视频分支所需依赖；抽帧/音轨/视觉调用均以桩替换。

    frames 为 None 时不替换抽帧方法——实例属性会遮蔽类方法，使模块级
    monkeypatch 失效（校验转调行为的用例必须走真实方法）。
    """
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(),
        audio_service=SimpleNamespace(),
        upload_file_service=_FakeUploadFileService(),
    )
    if frames is not None:
        service._extract_frames_with_offsets = lambda path, out_dir: frames
    service._transcribe_video_track = lambda path, upload: ""
    service._invoke_vision = lambda data_uri, prompt: "画面描述"
    return service


def _mk_frames(tmp_path, count):
    frames = []
    for index in range(count):
        path = tmp_path / f"frame_{index + 1:03d}.jpg"
        path.write_bytes(b"\xff\xd8\xff\xe0x")
        frames.append(ExtractedFrame(path=str(path), time_offset=float(index * 5)))
    return frames


def test_frame_segments_carry_time_offset(tmp_path):
    frames = _mk_frames(tmp_path, 3)
    service = _video_service(frames)

    segments = service.extract(
        _document(), _upload(), account_id=uuid4(), document_id=uuid4()
    )

    frame_segments = [s for s in segments if s.metadata.get("frame_url")]
    assert len(frame_segments) == 3
    assert [s.metadata["time_offset"] for s in frame_segments] == [0.0, 5.0, 10.0]
    assert [s.metadata["scene_index"] for s in frame_segments] == [1, 2, 3]


def test_extract_frames_with_offsets_delegates(monkeypatch, tmp_path):
    """`_extract_frames_with_offsets` 应转调 vision_invoke 的新函数。"""
    import internal.service.knowledge_media_extractor_service as module

    captured = {}

    def _fake(video_path, out_dir):
        captured["video_path"] = video_path
        captured["out_dir"] = out_dir
        return [ExtractedFrame(path="/tmp/frame_001.jpg", time_offset=1.0)]

    monkeypatch.setattr(module, "extract_video_frames_with_offsets", _fake)
    service = _video_service(None)

    result = service._extract_frames_with_offsets("in.mp4", str(tmp_path))

    assert [frame.path for frame in result] == ["/tmp/frame_001.jpg"]
    assert [frame.time_offset for frame in result] == [1.0]
    assert captured == {"video_path": "in.mp4", "out_dir": str(tmp_path)}
```

> **注**：这是新文件，所需的 `_FakeStorage` / `_FakeUploadFileService` / `_upload` / `_document`
> 必须在**本文件内**定义（不要指望从其他测试文件 import）。`_FakeStorage` **必须**实现
> `upload_bytes`，否则 `_persist_frame` 会抛错降级、`frame_url` 恒为空字符串。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_video_frame_offsets.py -q --no-header --no-cov`
Expected: FAIL —— `AttributeError: ... has no attribute '_extract_frames_with_offsets'` 或 `KeyError: 'time_offset'`

- [ ] **Step 3: 实现**

`knowledge_media_extractor_service.py` 顶部 import 增补（**必须顶层导入**：既有模块与
`test_frame_persistence.py` 都按 `monkeypatch.setattr(module, "extract_video_frames_to_dir", ...)`
的方式替换，函数内 import 会让补丁失效并直接 `AttributeError`）：

```python
from internal.core.vision.vision_invoke import (
    ExtractedFrame,
    extract_video_audio,
    extract_video_frames_with_offsets,
    invoke_vision_model,
    path_to_data_uri,
)
```

> 注意：`extract_video_frames_to_dir` 在服务层不再被引用（改名后无调用方），
> 应从该 import 列表移除，避免遗留未使用导入。`vision_invoke` 中该函数本身保留
> （仍有 `test_frame_persistence.py` 的直接用例覆盖）。

替换 `_extract_frames_to_dir` 为带偏移的版本：

```python
    def _extract_frames_with_offsets(self, video_path: str, out_dir: str) -> list[ExtractedFrame]:
        """视频抽帧（独立方法便于测试替换），返回帧与其时间偏移。

        L1 按视频时长动态决定帧数并全片均匀取帧——固定帧数会让长视频只覆盖
        开头（历史缺陷），导致「改细节」无法定位到中后段片段。
        """
        return extract_video_frames_with_offsets(video_path, out_dir)
```

在 `_extract_video` 中，把 `frames = self._extract_frames_to_dir(file_path, frames_dir)` 改为：

```python
            frames = self._extract_frames_with_offsets(file_path, frames_dir)
```

并把帧循环改为使用 `frame.path` / `frame.time_offset`：

```python
            for index, frame in enumerate(frames, start=1):
                frame_url = ""
                if account_id is not None and document_id is not None:
                    try:
                        frame_url = self._persist_frame(
                            frame.path, account_id=account_id, document_id=document_id,
                        ).key or ""
                    except Exception:
                        logger.warning(
                            "关键帧留存失败 file=%s scene_index=%s，降级为空 frame_url",
                            upload_file.name, index, exc_info=True,
                        )
                        frame_url = ""

                try:
                    description = self._invoke_vision(
                        path_to_data_uri(frame.path), _VIDEO_FRAME_PROMPT,
                    )
                except Exception:
                    logger.warning(
                        "视频帧视觉分析失败 document_file=%s scene_index=%s",
                        upload_file.name, index, exc_info=True,
                    )
                    continue
                if not str(description or "").strip():
                    continue
                segments.append(
                    MediaSegment(
                        content=description,
                        metadata={
                            "media_type": DocumentMediaType.VIDEO.value,
                            "scene_index": index,
                            "frame_count": len(frames),
                            "frame_url": frame_url,
                            # 帧在视频中的时间偏移（秒）：L2 区间密抽与「改细节」定位的
                            # 唯一依据，缺失则检索到的片段无法换算成时间轴位置。
                            "time_offset": float(frame.time_offset or 0.0),
                        },
                    )
                )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_video_frame_offsets.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 5: 运行既有相关测试防回归**

Run: `python -m pytest test/internal/service/test_knowledge_media_extractor_service.py test/internal/service/test_knowledge_media_ingest.py test/internal/service/test_frame_persistence.py test/internal/service/test_video_audio_extraction.py -q --no-header --no-cov`

**必改的既有测试（已逐文件实测清点，否则会因方法改名/返回类型变化而失败）**：

| 文件 | 需改动 |
| --- | --- |
| `test_frame_persistence.py` | 6 处 `service._extract_frames_to_dir = ...` 桩（L191/207/225/241/254/268）→ 改名 `_extract_frames_with_offsets`，且返回值由 `list[str]` 变为 `list[ExtractedFrame]`。既有辅助 `_write_frame(tmp_path, index=1) -> str` 保持返回路径，另加包装：桩写成 `lambda _v, _d: [ExtractedFrame(path=_write_frame(tmp_path), time_offset=0.0)]`，多处（L253）需按 index 生成多条 |
| `test_frame_persistence.py` | `TestExtractFramesToDirDelegation` 整个类（L276-295）需重写：改名 `TestExtractFramesWithOffsetsDelegation`，patch 目标由 `module.extract_video_frames_to_dir` 改为 `module.extract_video_frames_with_offsets`，断言返回值由 `["/tmp/frame_001.jpg"]` 改为 `ExtractedFrame` 列表 |
| `test_knowledge_media_extractor_service.py` | 4 处桩（L162/196/225/249）改名 `_extract_frames_with_offsets`；辅助 `_write_frames(tmp_path, count)` 改为直接返回 `list[ExtractedFrame]`（`_write_frames` 目前被 L161/249 两处使用；L225 传空列表可直接保留） |
| `test_video_audio_extraction.py` | **6 处桩（L132/148/161/177/196/209）同样必须改名**——当前计划正文遗漏了该文件，其 `_extract_frames_to_dir` 桩会因方法改名而失效（`monkeypatch.setattr` 在方法不存在时抛 `AttributeError`，6 个用例直接报错）。该文件的 `_write_frame(tmp_path, index=1) -> str` 同样需要 `ExtractedFrame` 包装 |

> 建议：全局搜索 `_extract_frames_to_dir`（排除 `vision_invoke.py` 内的旧函数定义）
> 确认无遗漏后再跑回归——这是改名类改动最易漏的地方。

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add api/internal/service/knowledge_media_extractor_service.py api/test/internal/service/test_video_frame_offsets.py api/test/internal/service/test_knowledge_media_extractor_service.py api/test/internal/service/test_knowledge_media_ingest.py api/test/internal/service/test_frame_persistence.py
git commit -m "feat(knowledge): record frame time_offset from uniform extraction"
```

---

## Task 5: 索引链路透传 `time_offset`

**Files:**
- Modify: `api/internal/service/knowledge_indexing_service.py:278-296`
- Test: `api/test/internal/service/test_visual_indexing.py`（补充用例）

- [ ] **Step 1: 写失败测试**

在 `test_visual_indexing.py` 追加（复用该文件既有的 `SimpleNamespace` / `uuid4` /
`_FakeVisualService` / `_FakeStorage` / `_build_service` / `_document` / `_frame_segment`；
注意 `_frame_segment()` 返回的是 `MediaSegment`，其字段名是 **`metadata`**（不是 `metadata_`），
只有 `SimpleNamespace` 桩才用 `metadata_`）：

```python
class TestFrameManifestCarriesTimeOffset:
    """parse_profile.frames 必须带 time_offset，供「改细节」定位与 L2 扩抽。

    缺该字段时帧清单只能排序、无法把命中的帧换算成视频时间轴位置，
    即「改细节」无从定位到具体片段。
    """

    def test_frame_segment_includes_time_offset(self):
        segment = SimpleNamespace(
            id=uuid4(),
            metadata_={
                "media_type": "video",
                "frame_url": "2026/09/16/frame_001.jpg",
                "scene_index": 1,
                "time_offset": 7.5,
            },
        )

        frame = KnowledgeIndexingService._segment_frame(segment)

        assert frame["time_offset"] == 7.5

    def test_frame_segment_defaults_time_offset_to_zero(self):
        """旧数据无 time_offset 时不得抛错，退化为 0.0。"""
        segment = SimpleNamespace(
            id=uuid4(),
            metadata_={"media_type": "video", "frame_url": "frames/f1.jpg", "scene_index": 1},
        )

        assert KnowledgeIndexingService._segment_frame(segment)["time_offset"] == 0.0

    def test_frame_segment_returns_none_without_frame_url(self):
        segment = SimpleNamespace(
            id=uuid4(),
            metadata_={"media_type": "video", "frame_url": "", "time_offset": 1.0},
        )

        assert KnowledgeIndexingService._segment_frame(segment) is None

    def test_parse_profile_manifest_carries_time_offset(self):
        visual = _FakeVisualService()
        doc = _document()
        segment = _frame_segment()
        segment.metadata = {**segment.metadata, "time_offset": 12.5}
        service, _ = _build_service([segment], visual, _FakeStorage())
        captured = {}
        service._finalize_segments = (
            lambda document, segment_ids, parse_profile=None: captured.update(parse_profile)
        )

        service._build_media_document(doc)

        assert captured["frames"][0]["time_offset"] == 12.5
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_visual_indexing.py -q --no-header --no-cov -k TimeOffset`
Expected: FAIL —— `KeyError: 'time_offset'`

- [ ] **Step 3: 实现**

修改 `_segment_frame`：

```python
    @staticmethod
    def _segment_frame(segment) -> dict | None:
        """取出片段的帧信息；非视频帧片段返回 None。"""
        metadata = getattr(segment, "metadata_", None) or {}
        if metadata.get("media_type") != DocumentMediaType.VIDEO.value:
            return None
        frame_url = str(metadata.get("frame_url") or "")
        if not frame_url:
            return None
        return {
            "segment_id": str(segment.id),
            "frame_url": frame_url,
            "scene_index": int(metadata.get("scene_index") or 0),
            # 时间偏移是帧的定位坐标：缺它则帧清单只能排序、无法换算时间轴位置
            "time_offset": float(metadata.get("time_offset") or 0.0),
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_visual_indexing.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/knowledge_indexing_service.py api/test/internal/service/test_visual_indexing.py
git commit -m "feat(knowledge): carry frame time_offset into parse_profile manifest"
```

> **接线状态（务必如实标注）**：`parse_profile.frames[].time_offset` 目前**只写不读**——
> 全仓尚无读取该字段的代码。读取端（L2 区间密抽、以 L1 命中帧换算出时间窗口）属
> **Plan 2**，本任务只交付「写入路径」。在 Plan 2 落地前，不得把「改细节可定位到片段」
> 描述为已可用能力。

---

## Task 6: 配额服务支持「预留但不计入」

**Files:**
- Modify: `api/internal/entity/storage_quota_entity.py`
- Modify: `api/internal/service/storage_quota_service.py:159-202`
- Test: `api/test/internal/service/test_storage_quota_service.py`（补充用例）

- [ ] **Step 1: 写失败测试**

在 `test_storage_quota_service.py` 末尾追加（复用该文件既有的 `_new_service` / `_SessionStub` / `_QueryStub` 桩）：

```python
class TestConsumeQuotaWithReserve:
    """上传准入需把「解析预留」纳入校验，但预留本身不计入已用。

    若不纳入：用户剩 2G、传 2G 视频会通过校验，随后帧留存把用量顶穿配额。
    若把预留也计入已用：用户被白扣一笔从未占用的空间。
    """

    def test_reserve_blocks_upload_when_total_insufficient():
        """used=0，配额 2048；传 1024 本可通过，加预留 2048 后超额 -> 拒绝。"""
        service = _new_service(_SessionStub([
            _QueryStub(first_result=None, all_result=[]),          # resolve_total_quota_bytes
            _QueryStub(one_or_none_result=SimpleNamespace(used_bytes=0)),  # usage
        ]))
        # 配额基线 5GB，改用显式 stub 控制总量更直接
        service.resolve_total_quota_bytes = lambda account_id: 2048

        with pytest.raises(ForbiddenException):
            service.consume_quota(uuid4(), 1024, reserve_bytes=2048)

    def test_reserve_not_counted_into_used_bytes():
        """累加值只含 incoming_bytes，不含 reserve。"""
        usage = SimpleNamespace(used_bytes=0)
        service = _new_service(_SessionStub([
            _QueryStub(one_or_none_result=usage),
        ]))
        service.resolve_total_quota_bytes = lambda account_id: 10_000

        result = service.consume_quota(uuid4(), 1_000, reserve_bytes=5_000)

        assert result == 1_000
        assert usage.used_bytes == 1_000

    def test_without_reserve_behaves_as_before():
        usage = SimpleNamespace(used_bytes=0)
        service = _new_service(_SessionStub([
            _QueryStub(one_or_none_result=usage),
        ]))
        service.resolve_total_quota_bytes = lambda account_id: 1_000

        assert service.consume_quota(uuid4(), 1_000) == 1_000
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_storage_quota_service.py -q --no-header --no-cov -k Reserve`
Expected: FAIL —— `TypeError: consume_quota() got an unexpected keyword argument 'reserve_bytes'`

- [ ] **Step 3: 实现**

`storage_quota_entity.py` 新增常量：

```python
# 素材解析预留：L1 帧数上限(60) × 单帧上限(最坏 4K ≈110KB) ≈ 6.6MB。
# 实测（testsrc 合成源）帧开销是绝对量、与源大小无关，故用固定上界而非倍率。
PARSE_RESERVE_BYTES = 8 * 1024 * 1024
```

`storage_quota_service.py` 修改 `consume_quota` 签名与校验：

```python
    def consume_quota(
        self, account_id: UUID, incoming_bytes: int, reserve_bytes: int = 0
    ) -> int:
        """原子预占：在同一把行锁内完成「校验 + 累加」，返回累加后的已用字节数。

        reserve_bytes 是**准入预留**：参与超额校验，但**不计入已用**。
        用于素材上传时把「解析将产生的帧占用」一并纳入门槛——否则用户可传满
        配额，随后帧留存把用量顶穿。预留只是门槛，真实占用由帧落库时按实际
        字节 add_usage 计入。
        """
        if incoming_bytes <= 0:
            return self.get_used_bytes(account_id)

        total = self.resolve_total_quota_bytes(account_id)
        usage = (
            self.db.session.query(AccountStorageUsage)
            .filter_by(account_id=account_id)
            .with_for_update()
            .one_or_none()
        )
        if usage is None:
            self._assert_within_quota(total, 0, incoming_bytes + reserve_bytes)
            try:
                created = self.create(
                    AccountStorageUsage, account_id=account_id, used_bytes=incoming_bytes
                )
                return int(created.used_bytes)
            except IntegrityError:
                self.db.session.rollback()
                usage = (
                    self.db.session.query(AccountStorageUsage)
                    .filter_by(account_id=account_id)
                    .with_for_update()
                    .one_or_none()
                )
                if usage is None:
                    return self.get_used_bytes(account_id)

        used = int(usage.used_bytes or 0)
        self._assert_within_quota(total, used, incoming_bytes + reserve_bytes)
        new_value = used + incoming_bytes
        self.update(usage, used_bytes=new_value)
        return new_value
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_storage_quota_service.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/entity/storage_quota_entity.py api/internal/service/storage_quota_service.py api/test/internal/service/test_storage_quota_service.py
git commit -m "feat(quota): support parse reserve in consume_quota gate"
```

---

## Task 7: 上传路径带上解析预留

**Files:**
- Modify: `api/internal/service/chunked_upload_service.py:90,162,292`
- Modify: `api/internal/service/storage/runtime_storage_service.py:95,139`
- Test: `api/test/internal/service/test_chunked_upload_service.py`（补充用例）

- [ ] **Step 1: 写失败测试**

在 `test_chunked_upload_service.py` 末尾追加（**照抄该文件既有的 `_service` 夹具用法与 `init`/`save_chunk`/`complete` 真实签名**）：

```python
def test_complete_passes_parse_reserve_to_consume_quota():
    """分片 complete 的配额预占必须带解析预留，挡住「刚好传满」的场景。"""
    from internal.entity.storage_quota_entity import PARSE_RESERVE_BYTES

    session_service = _FakeSessionService()
    storage = _FakeStorage()
    service, calls = _service(storage=storage, session_service=session_service)
    account = _account()
    session_id = service.init(
        account=account, filename="final.mp4", total_size=1024,
        chunk_size=512, total_chunks=2, fingerprint="fp-reserve",
    )["session_id"]
    calls.clear()
    service.save_chunk(session_id=session_id, index=0, content=b"a" * 512, account=account)
    service.save_chunk(session_id=session_id, index=1, content=b"b" * 512, account=account)

    service.complete(session_id=session_id, account=account)

    assert calls == [("consume", account.id, 1024, PARSE_RESERVE_BYTES)]
```

> **必须同步修改的既有测试（否则会失败）**：该文件 `_service` 夹具的 `_Quota` 桩当前签名不含预留，且**既有两个用例对 `calls` 做精确相等断言**：
>
> - 第 104-108 行 `consume_quota` 桩 → 改为 `def consume_quota(self, account_id, incoming_bytes, reserve_bytes=0):` 并把元组追加为 `("consume", account_id, incoming_bytes, reserve_bytes)`
> - 第 99-102 行 `check_quota` 桩 → 同样加 `reserve_bytes=0` 并记入元组
> - 第 406 行 `assert calls == [("consume", account.id, 8192)]` → 改为 `[("consume", account.id, 8192, PARSE_RESERVE_BYTES)]`
> - 第 425 行 `assert calls == [("consume", account.id, 1024)]` → 改为 `[("consume", account.id, 1024, PARSE_RESERVE_BYTES)]`
> - 第 426 行 `assert not any(call[0] == "add" for call in calls)` 不受影响（按元组首元素判断）
>
> 其余使用 `release_usage` 断言的用例（如第 429、451 行）不受影响。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_chunked_upload_service.py -q --no-header --no-cov -k reserve`
Expected: FAIL —— `assert 0 == 8388608`

- [ ] **Step 3: 实现**

两个文件均 import：

```python
from internal.entity.storage_quota_entity import PARSE_RESERVE_BYTES
```

`chunked_upload_service.py` 的 `complete` 预占改为：

```python
            self.storage_quota_service.consume_quota(
                account.id, session.total_size, reserve_bytes=PARSE_RESERVE_BYTES
            )
```

秒传分支（第 292 行附近）同样：

```python
        self.storage_quota_service.consume_quota(
            account.id, source_size, reserve_bytes=PARSE_RESERVE_BYTES
        )
```

init 阶段的快速预检（第 90 行）保持 `check_quota` 不变（它只是预检，真实闸门在 complete）。

`runtime_storage_service.py` 的两处 `check_quota` 改为带预留的校验：

```python
            self.storage_quota_service.check_quota(
                account_id, file_size + PARSE_RESERVE_BYTES
            )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_chunked_upload_service.py test/internal/service/test_upload_quota_guard.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/chunked_upload_service.py api/internal/service/storage/runtime_storage_service.py api/test/internal/service/test_chunked_upload_service.py
git commit -m "feat(quota): include parse reserve in upload admission"
```

---

## Task 8: 帧计入配额

**Files:**
- Modify: `api/internal/service/knowledge_media_extractor_service.py:177-201`
- Test: `api/test/internal/service/test_frame_quota_charge.py`

- [ ] **Step 1: 写失败测试**

```python
"""帧留存计费测试：帧是持久化产物，须计入存储配额。

设计决策（规格 §6.1）：判据是「是否堆积」——帧落 COS 且落 upload_file 记录，
属堆积，计入；音轨/中间文件用完即删，不计入。

反转 P3 决定：P3 曾明确「帧不计配额」，本设计有意改为计入。
"""
from types import SimpleNamespace
from uuid import uuid4

from internal.service.knowledge_media_extractor_service import (
    KnowledgeMediaExtractorService,
)


class _FakeStorage:
    def upload_bytes(self, filename, content, account_id, mime_type):
        return SimpleNamespace(key=f"frames/{filename}")


class _FakeQuota:
    def __init__(self):
        self.calls = []

    def add_usage(self, account_id, bytes_delta):
        self.calls.append((account_id, bytes_delta))
        return bytes_delta


class _FakeUploadFileService:
    def create_upload_file(self, **kwargs):
        return SimpleNamespace(key=kwargs["key"])


def test_persist_frame_charges_quota(tmp_path):
    quota = _FakeQuota()
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(),
        audio_service=SimpleNamespace(),
        upload_file_service=_FakeUploadFileService(),
    )
    service._get_storage_quota_service = lambda: quota

    frame_path = tmp_path / "frame_001.jpg"
    frame_path.write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)
    account_id = uuid4()

    service._persist_frame(str(frame_path), account_id=account_id, document_id=uuid4())

    assert len(quota.calls) == 1
    charged_account, charged_bytes = quota.calls[0]
    assert charged_account == account_id
    assert charged_bytes == frame_path.stat().st_size


def test_persist_frame_does_not_charge_when_no_account(tmp_path):
    """无账号上下文时不留存、也不计费（既有兼容行为）。"""
    quota = _FakeQuota()
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(),
        audio_service=SimpleNamespace(),
        upload_file_service=_FakeUploadFileService(),
    )
    service._get_storage_quota_service = lambda: quota

    frame_path = tmp_path / "frame_001.jpg"
    frame_path.write_bytes(b"\xff\xd8\xff\xe0x")

    service._persist_frame(str(frame_path), account_id=None, document_id=uuid4())

    assert quota.calls == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_frame_quota_charge.py -q --no-header --no-cov`
Expected: FAIL —— `assert [] == [(UUID(...), 104)]`

- [ ] **Step 3: 实现**

在 `KnowledgeMediaExtractorService` 中新增依赖获取方法：

```python
    def _get_storage_quota_service(self):
        """延迟获取配额服务（独立方法便于测试替换，避免循环依赖）。"""
        from internal.context import current_app

        from .storage_quota_service import StorageQuotaService

        return current_app.injector.get(StorageQuotaService)
```

`_persist_frame` 改为：

```python
    def _persist_frame(self, frame_path: str, *, account_id, document_id) -> UploadFile:
        """把关键帧留存为 UploadFile，并计入存储配额。

        关键帧必须留存：视觉向量属可后补能力，留存后无需重跑整个视频解析
        （设计稿 §3.4）。

        **计配额**：帧是持久化产物（落 COS + 落 upload_file），符合「堆积即计费」
        判据。计费与「释放」必须成对——释放见 `purge_knowledge_document`，
        否则用户删素材后帧仍占额，造成配额泄漏。
        """
        with open(frame_path, "rb") as fh:
            content = fh.read()
        filename = os.path.basename(frame_path)
        stored = self.cos_service.upload_bytes(
            filename=filename,
            content=content,
            account_id=account_id,
            mime_type="image/jpeg",
        )
        upload_file = self.upload_file_service.create_upload_file(
            account_id=account_id,
            name=filename,
            key=stored.key,
            size=len(content),
            extension="jpg",
            mime_type="image/jpeg",
            hash=hashlib.sha3_256(content).hexdigest(),
            storage_backend="local",
        )
        if account_id is not None and content:
            try:
                self._get_storage_quota_service().add_usage(account_id, len(content))
            except Exception:
                # 计费失败只记 warning：帧已落库，抛错会让整段视频解析失败，
                # 代价远大于少记的这点用量。
                logger.warning(
                    "关键帧配额计费失败 file=%s", filename, exc_info=True
                )
        return upload_file
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_frame_quota_charge.py -q --no-header --no-cov`
Expected: PASS（2 个用例）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/knowledge_media_extractor_service.py api/test/internal/service/test_frame_quota_charge.py
git commit -m "feat(quota): charge storage quota for persisted keyframes"
```

---

## Task 9: 素材删除时释放帧占用（成对修复）

**Files:**
- Modify: `api/internal/service/recycle_bin_handlers.py:359-385,484-498`
- Test: `api/test/internal/service/test_recycle_bin_handlers.py`（补充用例）

- [ ] **Step 1: 写失败测试**

在 `test_recycle_bin_handlers.py` 追加：

```python
class TestFrameFilesReleasedOnPurge:
    """删除素材必须连带清理帧文件并释放其配额。

    背景：帧的 upload_file 记录此前**既不计费也永不清理**（purge 只删主文件），
    已是孤儿记录。Task 8 让帧开始计配额后，若不补释放，就变成配额泄漏——
    用户删掉素材，帧还在，扣掉的空间永不归还。
    """

    def test_purge_deletes_and_releases_frame_files(self, monkeypatch):
        """主文件 + 全部帧文件都要删对象并释放配额。"""
        deleted = []
        released = []

        # _delete_object 是在函数内 `from ... import` 的，因此必须 patch 其**定义处**，
        # patch handlers 上的同名属性不会生效。
        monkeypatch.setattr(
            "internal.service.storage.storage_migration_service._delete_object",
            lambda backend, key: deleted.append(key),
        )
        monkeypatch.setattr(
            handlers, "_release_storage_quota",
            lambda data: released.append(data.get("key")),
        )

        handlers.purge_knowledge_document(
            {
                "upload_file": {"key": "main.mp4", "size": 100, "account_id": "a",
                                "storage_backend": "local"},
                "frames": [
                    {"key": "f1.jpg", "size": 10, "account_id": "a", "storage_backend": "local"},
                    {"key": "f2.jpg", "size": 20, "account_id": "a", "storage_backend": "local"},
                ],
            }
        )

        assert deleted == ["main.mp4", "f1.jpg", "f2.jpg"]
        assert released == ["main.mp4", "f1.jpg", "f2.jpg"]

    def test_purge_tolerates_snapshot_without_frames(self, monkeypatch):
        """老快照无 frames 字段时不得报错（向后兼容）。"""
        deleted = []
        monkeypatch.setattr(
            "internal.service.storage.storage_migration_service._delete_object",
            lambda backend, key: deleted.append(key),
        )
        monkeypatch.setattr(handlers, "_release_storage_quota", lambda data: None)

        handlers.purge_knowledge_document(
            {"upload_file": {"key": "main.mp4", "size": 1, "account_id": "a",
                             "storage_backend": "local"}}
        )

        assert deleted == ["main.mp4"]

    def test_collect_document_frame_files_queries_by_frame_url(self, monkeypatch):
        """快照需按 frame_url 采集帧 UploadFile 记录，否则销毁时无从释放。"""
        captured = {}

        class _Query:
            def filter(self, *args, **kwargs):
                captured["filtered"] = True
                return self

            def all(self):
                return [SimpleNamespace(key="f1.jpg", size=10, account_id="a",
                                        storage_backend="local")]

        monkeypatch.setattr(
            handlers, "db",
            SimpleNamespace(session=SimpleNamespace(query=lambda *a, **k: _Query())),
        )

        segment = SimpleNamespace(metadata_={"frame_url": "f1.jpg"})
        frames = handlers._collect_document_frame_files([segment])

        assert captured["filtered"] is True
        assert frames[0]["key"] == "f1.jpg"

    def test_collect_document_frame_files_skips_segments_without_frame(self, monkeypatch):
        """无 frame_url 的片段（非视频帧、或留存失败置空）不应参与查询。"""
        segments = [
            SimpleNamespace(metadata_={"media_type": "video", "frame_url": ""}),
            SimpleNamespace(metadata_={"media_type": "audio"}),
        ]

        assert handlers._collect_document_frame_files(segments) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_recycle_bin_handlers.py -q --no-header --no-cov -k FrameFiles`
Expected: FAIL —— `AttributeError: module ... has no attribute '_collect_document_frame_files'`

- [ ] **Step 3: 实现**

在 `recycle_bin_handlers.py` 中 `snapshot_knowledge_document` 之前新增辅助：

```python
def _collect_document_frame_files(segments: list) -> list[dict[str, Any]]:
    """采集视频帧片段的 UploadFile 记录，供销毁时清理与释放配额。

    帧文件是独立于文档主文件的 upload_file 记录（`_persist_frame` 创建），
    不采集则销毁时既不删文件也不释放配额。
    """
    keys: list[str] = []
    for segment in segments or []:
        metadata = getattr(segment, "metadata_", None) or {}
        frame_url = str(metadata.get("frame_url") or "").strip()
        if frame_url:
            keys.append(frame_url)
    if not keys:
        return []
    rows = (
        db.session.query(UploadFile)
        .filter(UploadFile.key.in_(keys))
        .all()
    )
    return [_row_to_dict(row) for row in rows]
```

修改 `snapshot_knowledge_document` 的 return：

```python
    return {
        "main": _row_to_dict(doc),
        "segments": [_row_to_dict(s) for s in segments],
        "upload_file": _row_to_dict(upload_file) if upload_file is not None else None,
        # 帧文件独立于主文件：不采集则销毁时既不删文件也不释放配额
        "frames": _collect_document_frame_files(segments),
    }
```

修改 `purge_knowledge_document`：

```python
def purge_knowledge_document(snapshot: dict[str, Any]) -> None:
    """留存期结束彻底销毁：删除底层存储对象（local 物理文件 / COS、OSS 对象）。

    删除失败向上抛异常：由 ``purge_expired`` 捕获后保持 pending 待重试，
    避免"状态已销毁但实际文件仍在"。

    除主文件外，**必须一并清理帧文件并释放其配额**：帧自 Task 8 起计入配额，
    只删主文件会导致用户删除素材后帧仍占额（配额泄漏）。
    """
    upload_file_data = snapshot.get("upload_file") or {}
    targets = [upload_file_data] if upload_file_data.get("key") else []
    targets.extend(snapshot.get("frames") or [])

    from internal.service.storage.storage_migration_service import _delete_object

    for data in targets:
        key = data.get("key")
        if not key:
            continue
        backend = (data.get("storage_backend") or "local").strip() or "local"
        _delete_object(backend, key)
        _release_storage_quota(data)
        logger.info("回收站销毁文档存储文件 key=%s backend=%s", key, backend)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_recycle_bin_handlers.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 5: 运行全量回归**

Run: `python -m pytest test/internal/service test/internal/core/tools test/internal/model test/internal/schema test/internal/migration test/internal/task test/app/http -q --no-header --no-cov`
Expected: 全绿（若其他会话改动导致个别失败，需确认与本计划无关）

- [ ] **Step 6: 提交**

```bash
git add api/internal/service/recycle_bin_handlers.py api/test/internal/service/test_recycle_bin_handlers.py
git commit -m "fix(knowledge): release frame files and quota on document purge"
```

---

## Task 10: 同步架构文档

**Files:**
- Modify: `docs/prd/modules/02-knowledge-base.md`
- Modify: `docs/prd/knowledge-base-product-form-design.md`

- [ ] **Step 1: 更新 02-knowledge-base.md**

在 §11.8.3（MediaSegment 产物结构）的视频帧行补 `time_offset`；在 §11.10.5（帧留存不计配额）**改写为计入**：

```markdown
#### 11.10.5 帧留存计入用户存储配额（P3 决定已反转）

关键帧是**持久化产物**（落 COS + 落 `upload_file` 记录），按「堆积即计费」判据
**计入**存储配额——P3 曾定「不计配额」，本设计有意反转。

- **写入**：`_persist_frame` 在落库后调 `StorageQuotaService.add_usage`，按帧实际字节计。
- **释放**：`purge_knowledge_document` 除主文件外**一并清理帧文件并 `release_usage`**。
  二者必须成对——只计费不释放会造成配额泄漏（用户删素材后帧仍占额）。
- **准入预留**：素材上传校验量为「素材大小 + `PARSE_RESERVE_BYTES`」，
  把解析将产生的帧占用一并纳入门槛（预留只是门槛，不计入已用）。
```

在 §11.8 抽帧处补 L1 动态策略：

```markdown
**L1 抽帧随时长动态**：帧数 `clamp(round(8·log2(sec) − 35), 6, 60)`，
**1 小时触顶 60 帧**，全片均匀取帧（取代此前「固定 3 帧且只取开头」）。
```

- [ ] **Step 2: 更新设计稿**

在 `knowledge-base-product-form-design.md` §5 补抽帧策略与配额口径的修正说明，并在 §9.2 的 P4 行标注「分层抽帧与帧配额已落地」。

- [ ] **Step 3: 提交**

```bash
git add docs/prd/modules/02-knowledge-base.md docs/prd/knowledge-base-product-form-design.md
git commit -m "docs(knowledge): sync frame sampling policy and quota semantics"
```

- [ ] **Step 4: 刷新知识图谱**

Run: `python -m graphify update .`
Expected: 完成，无 topology 变化或正常增量更新

---

## 验收对照（规格 §10 摘取）

| 规格验收项 | 对应任务 |
| --- | --- |
| L1 动态抽帧（10 秒 6 帧、1 小时 60 帧、覆盖全片） | Task 1、3 |
| `time_offset` 落库并被检索结果使用 | Task 4、5 |
| 素材配额含解析预留 | Task 6、7 |
| 帧配额对账（删除后释放，无泄漏） | Task 8、9 |

> L2 区间密抽、成品库、HyperFrames 渲染的验收项属计划 2 / 计划 3，不在本计划范围。

---

## 风险提示

| 风险 | 说明 |
| --- | --- |
| 既有测试桩需同步改名 | `_extract_frames_to_dir` → `_extract_frames_with_offsets`，返回类型由 `list[str]` 变为 `list[ExtractedFrame]`（Task 4 Step 5） |
| 抽帧性能变化 | 60 帧视频需抽 60 张（原 3 张），ffmpeg 耗时增加；已设 `_FRAME_TIMEOUT * 6` 上限 |
| 单帧上限为合成源测得 | `PARSE_RESERVE_BYTES` 取 8MB（4K 最坏 331KB 的约 24 倍余量）；上线后若实测超界，仅需调整该常量 |
