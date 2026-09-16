# L2 区间密集抽帧 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 L2 从「对全部 L1 帧逐帧详述」改为「用 L1 命中帧的 `time_offset` 定位 → 扩窗 → 仅在窗口内按 0.5 秒/帧密抽」，把 1 小时视频改 20 秒片段的视觉调用从 7200 次降到约 40 次。

**Architecture:** 窗口推导做成纯函数（`frame_sampling.py` 扩展），便于穷举单测；底层新增「按时间区间抽帧」入口（复用 ffmpeg `-ss`/`-t` + `fps=`，已由 PoC 实证）；索引服务的 `_enhance_l2` 改为「推导窗口 → 逐窗口密抽 → 为窗口内新帧新建 Segment 并写 `time_offset`」。

**Tech Stack:** Python 3.12、ffmpeg（`-ss`/`-t`/`-fps`/`-frames:v`）、SQLAlchemy、Celery、pytest。

**依据规格：** [2026-09-16-video-production-p4-design.md](../specs/2026-09-16-video-production-p4-design.md) §5.4、§5.5、§2（L2 密度 0.5s/帧、单窗上限 600 帧）

---

## 范围说明

承接 [计划 1（分层抽帧 + time_offset + 帧配额）](./2026-09-16-video-frame-sampling-and-quota.md)，本计划是**三份计划中的第二份**：

| 计划 | 内容 | 状态 |
| --- | --- | --- |
| 计划 1 | 分层抽帧 + `time_offset` + 帧配额（计费/释放） | ✅ 已完成 |
| **本计划** | L2 区间密抽（窗口推导 + 600 帧上限 + 显式区间） | 本次实施 |
| 计划 3 | HyperFrames 渲染（编/生/渲三层 + render 队列 + 成品库） | 待编写 |

**前置依赖已就绪**：`time_offset` 已随帧片段 metadata 与 `parse_profile.frames` 落库透传（计划 1 交付），这正是本计划「定位」步骤的输入。

---

## 已核实的事实（写代码前先读，避免重复踩坑）

| 事实 | 位置 / 证据 |
| --- | --- |
| ffmpeg 区间抽帧可行 | PoC 实测：`-ss 20 -t 10 -vf fps=2 -frames:v 600` 在 60s 源上抽出 20 帧；窗口 40s 的首帧与片头首帧 md5 不同，证明 `-ss` 生效 |
| 600 帧上限生效 | 同一 PoC：`-ss 0 -t 60 -vf fps=10 -frames:v 600` 输出恰 600 帧 |
| 现有 `extract_video_frames_with_offsets` 支持显式帧数 | `vision_invoke.py`：`frame_count` 传入时按该值抽（供 L2 复用），但**当前没有时间区间概念**——这是本计划要补的 |
| 现有 `_enhance_l2` 不抽新帧 | `knowledge_indexing_service.py`：只对既有 L1 帧逐帧详述并回写同一 Segment，**不产生新帧** |
| L2 触发入口 | 路由 `POST /space/knowledge-bases/<kb_id>/documents/<document_id>/l2` → `KnowledgeBaseService.trigger_document_l2` → `_dispatch_document_l2`（Celery 优先、失败回退同步） |
| Celery 任务 | `internal.task.knowledge_l2_tasks.build_document_l2_task`（`bind=True`、`max_retries=2`、`default_retry_delay=60`） |
| 帧片段 metadata 结构 | `media_type` / `scene_index` / `frame_count` / `frame_url` / `time_offset` |
| L2 帧也计配额 | 帧经 `RuntimeStorageProxy.upload_bytes` 隐式计费；重解析由 `_release_stale_frames` 清理旧帧（计划 1 交付） |

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `api/internal/core/vision/frame_sampling.py`（修改） | 新增 L2 窗口推导纯函数：`L2_WINDOW_PADDING_SEC`、`L2_MAX_FRAMES_PER_WINDOW`、`resolve_l2_window_frame_count`、`merge_time_windows`、`plan_l2_windows` |
| `api/internal/core/vision/vision_invoke.py`（修改） | 新增 `extract_video_frames_in_range`（按 `start_sec`/`duration_sec` 区间密抽，返回 `list[ExtractedFrame]`） |
| `api/internal/service/knowledge_media_extractor_service.py`（修改） | 新增 `_extract_frames_in_range`（独立方法便于测试替换） |
| `api/internal/service/knowledge_indexing_service.py`（修改） | `_enhance_l2` 改为「窗口推导 → 逐窗口密抽 → 新建窗口帧 Segment」；新增 `_resolve_l2_windows` / `_persist_window_segment` |
| `api/internal/service/knowledge_base_service.py`（修改） | `trigger_document_l2` 接受可选显式区间参数并透传 |
| `api/app/http/knowledge_mcp_routes.py`（修改） | L2 路由读取请求体中的可选 `start_sec` / `end_sec` 并透传 |

---

## Task 1: L2 窗口推导纯函数

**Files:**
- Modify: `api/internal/core/vision/frame_sampling.py`
- Test: `api/test/internal/core/vision/test_l2_windows.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/core/vision/test_l2_windows.py`：

```python
"""L2 区间窗口推导测试（纯函数，无 IO）。

L2 不重扫全片：由 L1 命中帧的 time_offset 推出「要密抽的时间窗口」，
从而把 1 小时视频改 20 秒片段的视觉调用从 7200 次降到约 40 次。
"""
import pytest

from internal.core.vision.frame_sampling import (
    L2_MAX_FRAMES_PER_WINDOW,
    L2_WINDOW_PADDING_SEC,
    merge_time_windows,
    plan_l2_windows,
    resolve_l2_window_frame_count,
)


class TestResolveL2WindowFrameCount:
    def test_half_second_per_frame(self):
        """窗口内每 0.5 秒 1 帧。"""
        assert resolve_l2_window_frame_count(10.0) == 20

    def test_one_second_window(self):
        assert resolve_l2_window_frame_count(1.0) == 2

    def test_at_least_one_frame(self):
        """极短窗口也要产出至少 1 帧，不能退化为 0。"""
        assert resolve_l2_window_frame_count(0.1) == 1

    def test_capped_at_max_frames(self):
        """超长窗口被 600 帧上限截断（= 5 分钟 @0.5s/帧）。"""
        assert resolve_l2_window_frame_count(3600.0) == L2_MAX_FRAMES_PER_WINDOW

    def test_invalid_duration_falls_back_to_one(self):
        assert resolve_l2_window_frame_count(0.0) == 1
        assert resolve_l2_window_frame_count(-3.0) == 1
        assert resolve_l2_window_frame_count("bad") == 1


class TestMergeTimeWindows:
    def test_merges_overlapping_windows(self):
        assert merge_time_windows([(10.0, 20.0), (18.0, 30.0)]) == [(10.0, 30.0)]

    def test_keeps_disjoint_windows_separate(self):
        assert merge_time_windows([(10.0, 20.0), (50.0, 60.0)]) == [(10.0, 20.0), (50.0, 60.0)]

    def test_merges_touching_windows(self):
        """首尾相接（end == next.start）视为同一窗口，避免碎片化。"""
        assert merge_time_windows([(10.0, 20.0), (20.0, 30.0)]) == [(10.0, 30.0)]

    def test_sorts_before_merging(self):
        assert merge_time_windows([(50.0, 60.0), (10.0, 20.0)]) == [(10.0, 20.0), (50.0, 60.0)]

    def test_empty_input(self):
        assert merge_time_windows([]) == []

    def test_swapped_bounds_are_normalized(self):
        """传入 (end, start) 颠倒时按升序归一，不产生负长度窗口。"""
        assert merge_time_windows([(20.0, 10.0)]) == [(10.0, 20.0)]


class TestPlanL2Windows:
    def test_hit_offset_expands_by_padding(self):
        """单个命中时刻向两侧各留白 L2_WINDOW_PADDING_SEC。"""
        windows = plan_l2_windows([100.0], duration_sec=600.0)

        assert windows == [(100.0 - L2_WINDOW_PADDING_SEC, 100.0 + L2_WINDOW_PADDING_SEC)]

    def test_clamps_to_video_bounds(self):
        """窗口不得越过视频首尾（0 ~ duration）。"""
        assert plan_l2_windows([2.0], duration_sec=60.0) == [(0.0, 2.0 + L2_WINDOW_PADDING_SEC)]
        assert plan_l2_windows([59.0], duration_sec=60.0) == [(59.0 - L2_WINDOW_PADDING_SEC, 60.0)]

    def test_merges_nearby_hits(self):
        """相邻命中（扩窗后重叠）合并成一个窗口，避免重复抽帧。"""
        windows = plan_l2_windows([100.0, 105.0], duration_sec=600.0)

        assert windows == [(100.0 - L2_WINDOW_PADDING_SEC, 105.0 + L2_WINDOW_PADDING_SEC)]

    def test_multiple_disjoint_hits(self):
        windows = plan_l2_windows([50.0, 300.0], duration_sec=600.0)

        assert windows == [
            (50.0 - L2_WINDOW_PADDING_SEC, 50.0 + L2_WINDOW_PADDING_SEC),
            (300.0 - L2_WINDOW_PADDING_SEC, 300.0 + L2_WINDOW_PADDING_SEC),
        ]

    def test_no_hits_yields_no_windows(self):
        """没有命中就不该抽任何帧（L2 是按需，不是全片重扫）。"""
        assert plan_l2_windows([], duration_sec=600.0) == []

    def test_unknown_duration_does_not_clamp_upper_bound(self):
        """时长未知（<=0）时只做下界保护，不把窗口截成空。"""
        windows = plan_l2_windows([100.0], duration_sec=0.0)

        assert windows == [(100.0 - L2_WINDOW_PADDING_SEC, 100.0 + L2_WINDOW_PADDING_SEC)]

    def test_explicit_range_overrides_hits(self):
        """显式区间优先于命中推导（规格 §2「A+B」）。"""
        windows = plan_l2_windows(
            [100.0], duration_sec=600.0, explicit_range=(200.0, 260.0)
        )

        assert windows == [(200.0, 260.0)]

    def test_explicit_range_clamped_and_ordered(self):
        windows = plan_l2_windows(
            [], duration_sec=600.0, explicit_range=(700.0, -5.0)
        )

        assert windows == [(0.0, 600.0)]

    def test_invalid_offsets_ignored(self):
        """非数值/负偏移不参与推导，避免污染窗口。"""
        windows = plan_l2_windows([-5.0, "bad", 100.0], duration_sec=600.0)

        assert windows == [(100.0 - L2_WINDOW_PADDING_SEC, 100.0 + L2_WINDOW_PADDING_SEC)]

    def test_merging_can_cover_many_hits(self):
        """一串密集命中最终只产生一个窗口（这就是成本降低的来源）。"""
        hits = [100.0, 102.0, 104.0, 106.0]

        assert len(plan_l2_windows(hits, duration_sec=600.0)) == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/core/vision/test_l2_windows.py -q --no-header --no-cov`
Expected: FAIL —— `ImportError: cannot import name 'L2_MAX_FRAMES_PER_WINDOW'`

- [ ] **Step 3: 实现**

在 `frame_sampling.py` 末尾追加（**同时**在文件顶部常量区加入两个常量）：

```python
# L2 区间密抽：命中时刻两侧留白（秒）
L2_WINDOW_PADDING_SEC = 10.0
# L2 区间内抽帧密度：每 0.5 秒 1 帧
L2_INTERVAL_SEC = 0.5
# 单次窗口抽帧上限（600 帧 = 5 分钟 @0.5s/帧），挡住「整段触发 L2」
L2_MAX_FRAMES_PER_WINDOW = 600


def resolve_l2_window_frame_count(duration_sec: float) -> int:
    """按窗口时长解析要抽取的帧数（每 0.5 秒 1 帧，上限 600）。

    极短窗口至少 1 帧（否则「定位到了却什么都没抽」）；时长非法时同样退回 1，
    让调用方无需额外判空。
    """
    try:
        duration = float(duration_sec)
    except (TypeError, ValueError):
        return 1
    if duration <= 0:
        return 1
    raw = int(duration / L2_INTERVAL_SEC)
    return max(1, min(L2_MAX_FRAMES_PER_WINDOW, raw))


def merge_time_windows(windows: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """合并重叠或首尾相接的时间窗口，返回按起点升序的规范窗口列表。

    合并是成本控制的关键：一串相邻命中若各自成窗，会重复抽取重叠区间。
    """
    normalized: list[tuple[float, float]] = []
    for start, end in windows:
        low, high = (start, end) if start <= end else (end, start)
        normalized.append((float(low), float(high)))
    normalized.sort(key=lambda item: item[0])

    merged: list[tuple[float, float]] = []
    for start, end in normalized:
        if merged and start <= merged[-1][1]:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def plan_l2_windows(
    hit_offsets: list[float],
    duration_sec: float,
    explicit_range: tuple[float, float] | None = None,
) -> list[tuple[float, float]]:
    """推导 L2 要密抽的时间窗口（秒）。

    - `explicit_range` 给出时直接用它（用户显式指定时间段，规格 §2「A+B」）；
    - 否则由 L1 命中帧的 `time_offset` 各自向两侧扩 `L2_WINDOW_PADDING_SEC` 再合并；
    - 窗口裁剪到 `[0, duration_sec]`；时长未知（<=0）时只保下界，不把窗口截空。
    """
    if explicit_range is not None:
        candidates = [explicit_range]
    else:
        candidates = []
        for offset in hit_offsets or []:
            try:
                position = float(offset)
            except (TypeError, ValueError):
                continue
            if position < 0:
                continue
            candidates.append(
                (position - L2_WINDOW_PADDING_SEC, position + L2_WINDOW_PADDING_SEC)
            )

    if not candidates:
        return []

    windows = merge_time_windows(candidates)

    try:
        duration = float(duration_sec)
    except (TypeError, ValueError):
        duration = 0.0

    clamped: list[tuple[float, float]] = []
    for start, end in windows:
        low = max(0.0, start)
        high = end if duration <= 0 else min(duration, end)
        if high <= low:
            continue
        clamped.append((low, high))
    return clamped
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/core/vision/test_l2_windows.py -q --no-header --no-cov`
Expected: PASS（21 个用例）

- [ ] **Step 5: 运行 vision 目录回归**

Run: `python -m pytest test/internal/core/vision -q --no-header --no-cov`
Expected: PASS（含既有 27 个用例，无回归）

- [ ] **Step 6: 提交**

```bash
git add api/internal/core/vision/frame_sampling.py api/test/internal/core/vision/test_l2_windows.py
git commit -m "feat(vision): add L2 range window derivation"
```

---

## Task 2: 按时间区间密抽

**Files:**
- Modify: `api/internal/core/vision/vision_invoke.py`
- Test: `api/test/internal/core/vision/test_range_extraction.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/core/vision/test_range_extraction.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/core/vision/test_range_extraction.py -q --no-header --no-cov`
Expected: FAIL —— `AttributeError: module ... has no attribute 'extract_video_frames_in_range'`

- [ ] **Step 3: 实现**

在 `vision_invoke.py` 的 `extract_video_frames_with_offsets` 之后新增：

```python
def extract_video_frames_in_range(
    video_path: str,
    out_dir: str,
    start_sec: float,
    duration_sec: float,
    frame_count: int | None = None,
) -> list[ExtractedFrame]:
    """只在 [start_sec, start_sec + duration_sec) 内按 0.5 秒间隔密抽帧。

    L2「扩窗密抽」的落地入口：相比从片头全片均匀抽，本函数用 ffmpeg 的
    `-ss` / `-t` 把解码范围限定在窗口内，这是「1 小时视频改 20 秒片段只花
    约 40 次视觉调用」而非 7200 次的根本原因。

    frame_count 缺省时按 `resolve_l2_window_frame_count(duration_sec)` 推导。
    返回的 `time_offset` 是**视频时间轴上的绝对位置**（与 L1 帧同一坐标系）。
    """
    start = max(0.0, float(start_sec))
    duration = max(0.0, float(duration_sec))
    count = (
        max(1, int(frame_count))
        if frame_count is not None
        else resolve_l2_window_frame_count(duration)
    )

    os.makedirs(out_dir, exist_ok=True)
    interval = duration / count if count else L2_INTERVAL_SEC

    pattern = os.path.join(out_dir, "frame_%03d.jpg")
    fps = 1.0 / max(interval, 0.001)
    cmd = [
        _resolve_ffmpeg_exe(), "-y",
        "-ss", f"{start}",
        "-i", video_path,
        "-t", f"{duration}",
        "-vf", f"fps={fps:.6f}",
        "-frames:v", str(count),
        "-q:v", "4", pattern,
    ]
    subprocess.run(cmd, capture_output=True, timeout=_FRAME_TIMEOUT * 6, check=True)

    paths = _list_frame_files(out_dir)
    if not paths:
        raise RuntimeError("视频区间抽帧未产出任何文件")

    offsets = [start + round(interval * (index + 0.5), 3) for index in range(len(paths))]
    return [
        ExtractedFrame(path=path, time_offset=float(offsets[index]))
        for index, path in enumerate(paths)
    ]
```

并在文件顶部 import 补上 `plan_l2_windows` 之外所需符号（**常量不重复定义**，统一从
`frame_sampling` 引入，避免两处取值漂移）：

```python
from internal.core.vision.frame_sampling import (
    L2_INTERVAL_SEC,
    plan_frame_offsets,
    resolve_l1_frame_count,
    resolve_l2_window_frame_count,
)
```

> **注意**：`L2_INTERVAL_SEC` 已在 Task 1 定义于 `frame_sampling.py`，此处**直接 import 复用**，
> 不要在本文件再写一遍常量定义。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/core/vision/test_range_extraction.py -q --no-header --no-cov`
Expected: PASS（4 个用例）

- [ ] **Step 5: 运行 vision 目录回归**

Run: `python -m pytest test/internal/core/vision -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add api/internal/core/vision/vision_invoke.py api/test/internal/core/vision/test_range_extraction.py
git commit -m "feat(vision): extract frames within an explicit time range"
```

---

## Task 3: 媒体提取器暴露区间抽帧

**Files:**
- Modify: `api/internal/service/knowledge_media_extractor_service.py`
- Test: `api/test/internal/service/test_media_range_extraction.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/test_media_range_extraction.py`：

```python
"""媒体提取器的区间抽帧入口（供 L2 复用）。

做成独立方法（而非直接调 vision_invoke）：L2 的单测需要替换抽帧行为，
不必依赖真实 ffmpeg。
"""
from types import SimpleNamespace

from internal.core.vision.vision_invoke import ExtractedFrame
from internal.service.knowledge_media_extractor_service import (
    KnowledgeMediaExtractorService,
)


def _service():
    return KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=SimpleNamespace(),
        audio_service=SimpleNamespace(),
        upload_file_service=SimpleNamespace(),
    )


def test_delegates_to_vision_invoke_range(monkeypatch, tmp_path):
    captured = {}

    def _fake(video_path, out_dir, start_sec, duration_sec):
        captured["video_path"] = video_path
        captured["out_dir"] = out_dir
        captured["start_sec"] = start_sec
        captured["duration_sec"] = duration_sec
        return [ExtractedFrame(path="/tmp/f1.jpg", time_offset=21.0)]

    import internal.service.knowledge_media_extractor_service as module
    monkeypatch.setattr(module, "extract_video_frames_in_range", _fake)

    frames = _service()._extract_frames_in_range(
        "in.mp4", str(tmp_path), start_sec=20.0, duration_sec=10.0
    )

    assert [frame.time_offset for frame in frames] == [21.0]
    assert captured["start_sec"] == 20.0
    assert captured["duration_sec"] == 10.0
    assert captured["out_dir"] == str(tmp_path)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_media_range_extraction.py -q --no-header --no-cov`
Expected: FAIL —— `AttributeError: ... has no attribute '_extract_frames_in_range'`（或 `monkeypatch` 目标不存在）

- [ ] **Step 3: 实现**

`knowledge_media_extractor_service.py` 顶部 import 补上：

```python
from internal.core.vision.vision_invoke import (
    ExtractedFrame,
    extract_video_audio,
    extract_video_frames_in_range,
    extract_video_frames_with_offsets,
    invoke_vision_model,
    path_to_data_uri,
)
```

在 `_extract_frames_with_offsets` 之后新增：

```python
    def _extract_frames_in_range(
        self, video_path: str, out_dir: str, *, start_sec: float, duration_sec: float
    ) -> list[ExtractedFrame]:
        """在指定时间区间内密抽帧（独立方法便于测试替换，供 L2 扩窗使用）。

        与 `_extract_frames_with_offsets`（全片均匀）相对：本方法只解出窗口内的
        画面，这是 L2「按需放大」而非重扫全片的实现基础。
        """
        return extract_video_frames_in_range(
            video_path, out_dir, start_sec=start_sec, duration_sec=duration_sec
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_media_range_extraction.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 5: 运行媒体提取器既有测试防回归**

Run: `python -m pytest test/internal/service/test_knowledge_media_extractor_service.py test/internal/service/test_frame_persistence.py test/internal/service/test_video_frame_offsets.py test/internal/service/test_video_audio_extraction.py test/internal/service/test_media_range_extraction.py -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add api/internal/service/knowledge_media_extractor_service.py api/test/internal/service/test_media_range_extraction.py
git commit -m "feat(knowledge): expose range frame extraction on media extractor"
```

---

## Task 4: L2 改为窗口化密抽

> **这是本计划的核心改动**：现有 `_enhance_l2` 只对既有 L1 帧逐帧详述，不抽新帧；本任务把它改为「推导窗口 → 逐窗口密抽 → 为窗口内新帧新建 Segment」。

**Files:**
- Modify: `api/internal/service/knowledge_indexing_service.py`
- Test: `api/test/internal/service/test_l2_range_sampling.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/test_l2_range_sampling.py`：

```python
"""L2 窗口化密抽测试。

规格 §5.4：L2 不重扫全片——由 L1 命中帧的 time_offset 推导窗口，
只在窗口内按 0.5 秒/帧密抽。本测试锁定该行为与「窗口内新帧落库」。
"""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from internal.core.vision.vision_invoke import ExtractedFrame
from internal.service.knowledge_indexing_service import KnowledgeIndexingService


@contextmanager
def _auto_commit():
    yield


class _QueryStub:
    def __init__(self, one_or_none_result=None, all_result=None):
        self._one_or_none = one_or_none_result
        self._all = [] if all_result is None else all_result

    def filter(self, *_a, **_kw):
        return self

    def filter_by(self, **_kw):
        return self

    def all(self):
        return self._all

    def one_or_none(self):
        return self._one_or_none


class _SessionStub:
    """按 model 返回桩查询：KnowledgeSegment 恒返回给定片段，其余返回空。

    `_enhance_l2` 与 `_next_segment_position` 都会查 KnowledgeSegment，
    故这里必须对同一批片段**可重复读取**（不能像队列那样消费一次就空）。
    """

    def __init__(self, segments=None, upload_rows=None):
        self._segments = list(segments or [])
        self._upload_rows = list(upload_rows or [])

    def query(self, model, *_a, **_kw):
        name = getattr(model, "__name__", "")
        if name == "UploadFile":
            return _QueryStub(all_result=self._upload_rows)
        return _QueryStub(all_result=self._segments)


def _document(duration_sec=600.0):
    return SimpleNamespace(
        id=uuid4(),
        media_type="video",
        knowledge_base_id=uuid4(),
        owner_account_id=uuid4(),
        upload_file_id=uuid4(),
        parse_profile={"tier1": {"status": "completed"}},
        knowledge_base=SimpleNamespace(id=uuid4(), embedding_model_id=uuid4()),
    )


def _l1_frame_segment(frame_url, time_offset, scene_index=1):
    return SimpleNamespace(
        id=uuid4(),
        content="L1 粗描述",
        position=scene_index,
        metadata_={
            "media_type": "video",
            "frame_url": frame_url,
            "scene_index": scene_index,
            "frame_count": 6,
            "time_offset": time_offset,
        },
    )


def _build_service(segments, upload_rows=None):
    created = []

    service = KnowledgeIndexingService(
        db=SimpleNamespace(
            session=_SessionStub(segments=segments, upload_rows=upload_rows),
            auto_commit=lambda: _auto_commit(),
        ),
        file_extractor=SimpleNamespace(),
        embeddings_service=SimpleNamespace(calculate_token_count=lambda text: len(text)),
        jieba_service=SimpleNamespace(extract_keywords=lambda text, n: ["kw"]),
        knowledge_vector_service=SimpleNamespace(
            index_segment=lambda *a, **kw: "id", remove_segment=lambda *a: None
        ),
        media_extractor=SimpleNamespace(
            _extract_frames_in_range=lambda video_path, out_dir, *, start_sec, duration_sec: []
        ),
        visual_embedding_service=None,
        cos_service=SimpleNamespace(download_file=lambda key, path: None),
    )
    service.update = lambda instance, **kwargs: instance
    service.create = lambda model, **kwargs: created.append(kwargs) or SimpleNamespace(
        id=uuid4(), **kwargs
    )
    service.delete = lambda instance: None
    service._resolve_document_duration = lambda document: 600.0
    service._delete_frame_object = lambda key, backend: None
    service._release_frame_quota = lambda account_id, size: None
    return service, created


class TestL2WindowSampling:
    def test_uses_l1_offsets_to_derive_windows(self):
        """命中帧的 time_offset 决定窗口位置——窗口内才抽帧。"""
        calls = []

        def _extract(video_path, out_dir, *, start_sec, duration_sec):
            calls.append((start_sec, duration_sec))
            return [ExtractedFrame(path="/tmp/f1.jpg", time_offset=start_sec + 1.0)]

        service, _created = _build_service(
            [_l1_frame_segment("frames/l1.jpg", time_offset=100.0)]
        )
        service.media_extractor = SimpleNamespace(_extract_frames_in_range=_extract)
        service._download_document_video = lambda document: "/tmp/v.mp4"
        service._persist_window_frame = lambda frame, document: "frames/w1.jpg"
        service._invoke_l2_vision = lambda data_uri: "窗口内详述"
        service._load_frame_data_uri = lambda key: "data:image/jpeg;base64,AAA"

        service._enhance_l2(_document())

        assert len(calls) == 1
        start_sec, duration_sec = calls[0]
        assert start_sec == 90.0, "100s 命中扩窗 ±10s -> 起点 90s"
        assert duration_sec == 20.0

    def test_creates_segment_per_window_frame(self):
        """窗口内每帧都建新 Segment（带 time_offset），不与 L1 片段混淆。"""
        service, created = _build_service(
            [_l1_frame_segment("frames/l1.jpg", time_offset=100.0)]
        )
        service.media_extractor = SimpleNamespace(
            _extract_frames_in_range=lambda video_path, out_dir, *, start_sec, duration_sec: [
                ExtractedFrame(path="/tmp/f1.jpg", time_offset=91.0),
                ExtractedFrame(path="/tmp/f2.jpg", time_offset=91.5),
            ]
        )
        service._download_document_video = lambda document: "/tmp/v.mp4"
        service._persist_window_frame = lambda frame, document: "frames/w1.jpg"
        service._invoke_l2_vision = lambda data_uri: "窗口内详述"
        service._load_frame_data_uri = lambda key: "data:image/jpeg;base64,AAA"

        service._enhance_l2(_document())

        assert len(created) == 2
        assert created[0]["metadata_"]["tier2_window"] is True
        assert created[0]["metadata_"]["time_offset"] == 91.0
        assert created[0]["metadata_"]["scene_index"] == 1
        assert created[1]["metadata_"]["scene_index"] == 2

    def test_window_frames_are_indexed(self):
        """窗口帧必须同时写文本向量与视觉向量。

        只建 Segment 不索引，用户永远检索不到这些片段——L2 就白跑了。
        """
        indexed_text = []
        indexed_visual = []

        service, _created = _build_service(
            [_l1_frame_segment("frames/l1.jpg", time_offset=100.0)]
        )
        service.knowledge_vector_service = SimpleNamespace(
            index_segment=lambda segment, kb: indexed_text.append(segment.id),
            remove_segment=lambda *a: None,
        )
        service._index_visual_vectors = lambda document, segments: indexed_visual.extend(
            s.id for s in segments
        )
        service.media_extractor = SimpleNamespace(
            _extract_frames_in_range=lambda video_path, out_dir, *, start_sec, duration_sec: [
                ExtractedFrame(path="/tmp/f1.jpg", time_offset=91.0),
            ]
        )
        service._download_document_video = lambda document: "/tmp/v.mp4"
        service._persist_window_frame = lambda frame, document: "frames/w1.jpg"
        service._invoke_l2_vision = lambda data_uri: "窗口内详述"
        service._load_frame_data_uri = lambda key: "data:image/jpeg;base64,AAA"

        service._enhance_l2(_document())

        assert len(indexed_text) == 1, "文本向量必须写入（否则文本检索不到）"
        assert len(indexed_visual) == 1, "视觉向量必须写入（否则画面检索不到）"

    def test_window_segment_position_follows_existing(self):
        """L2 新片段序号接在既有片段之后，避免与 L1 片段 position 冲突。"""
        service, created = _build_service(
            [
                _l1_frame_segment("frames/l1.jpg", time_offset=100.0, scene_index=1),
                _l1_frame_segment("frames/l1b.jpg", time_offset=200.0, scene_index=2),
            ]
        )
        service.media_extractor = SimpleNamespace(
            _extract_frames_in_range=lambda video_path, out_dir, *, start_sec, duration_sec: [
                ExtractedFrame(path="/tmp/f1.jpg", time_offset=91.0),
            ]
        )
        service._download_document_video = lambda document: "/tmp/v.mp4"
        service._persist_window_frame = lambda frame, document: "frames/w1.jpg"
        service._invoke_l2_vision = lambda data_uri: "窗口内详述"
        service._load_frame_data_uri = lambda key: "data:image/jpeg;base64,AAA"

        service._enhance_l2(_document())

        assert created, "应有新片段"
        assert created[0]["position"] == 3, "既有 position 最大为 2，新片段应为 3"

    def test_no_hits_means_no_extraction(self):
        """没有 L1 命中帧就不抽任何帧（L2 是按需，不是全片重扫）。"""
        calls = []
        service, created = _build_service([])
        service.media_extractor = SimpleNamespace(
            _extract_frames_in_range=lambda *a, **kw: calls.append(1) or []
        )
        service._download_document_video = lambda document: "/tmp/v.mp4"

        result = service._enhance_l2(_document())

        assert calls == []
        assert created == []
        assert result["window_frames"] == 0

    def test_l2_frames_do_not_drive_window_derivation(self):
        """上一轮的 L2 窗口帧不得参与窗口推导（否则窗口逐轮自我放大）。"""
        calls = []

        def _extract(video_path, out_dir, *, start_sec, duration_sec):
            calls.append((start_sec, duration_sec))
            return [ExtractedFrame(path="/tmp/f1.jpg", time_offset=start_sec + 1.0)]

        l1 = _l1_frame_segment("frames/l1.jpg", time_offset=100.0, scene_index=1)
        l2 = _l1_frame_segment("frames/l2old.jpg", time_offset=500.0, scene_index=2)
        l2.metadata_["tier2_window"] = True

        service, _created = _build_service([l1, l2])
        service.media_extractor = SimpleNamespace(_extract_frames_in_range=_extract)
        service._download_document_video = lambda document: "/tmp/v.mp4"
        service._persist_window_frame = lambda frame, document: "frames/w1.jpg"
        service._invoke_l2_vision = lambda data_uri: "详述"
        service._load_frame_data_uri = lambda key: "data:image/jpeg;base64,AAA"

        service._enhance_l2(_document())

        assert len(calls) == 1, "只应由 L1 命中（100s）导出一个窗口，l2 的 500s 不参与"
        assert calls[0][0] == 90.0

    def test_previous_l2_windows_are_cleared(self):
        """重复触发 L2 时必须清掉上一轮窗口片段与帧（否则累积重复 + 帧泄漏）。"""
        deleted_records = []
        deleted_objects = []
        released = []

        l1 = _l1_frame_segment("frames/l1.jpg", time_offset=100.0, scene_index=1)
        old_l2 = _l1_frame_segment("frames/old_l2.jpg", time_offset=95.0, scene_index=2)
        old_l2.metadata_["tier2_window"] = True

        old_frame_row = SimpleNamespace(
            key="frames/old_l2.jpg", size=10, account_id=uuid4(), storage_backend="local"
        )

        service, _created = _build_service([l1, old_l2], upload_rows=[old_frame_row])
        service.media_extractor = SimpleNamespace(
            _extract_frames_in_range=lambda *a, **kw: []
        )
        service._download_document_video = lambda document: "/tmp/v.mp4"
        # 片段与帧记录都经 self.delete(...) 删除，统一记录被删对象
        service.delete = lambda instance: deleted_records.append(instance)
        service._delete_frame_object = lambda key, backend: deleted_objects.append(key)
        service._release_frame_quota = lambda account_id, size: released.append((account_id, size))

        service._enhance_l2(_document())

        assert any(s is old_l2 for s in deleted_records), "旧 L2 片段必须删除"
        assert any(row is old_frame_row for row in deleted_records), "旧 L2 帧记录必须删除"
        assert deleted_objects == ["frames/old_l2.jpg"], "旧 L2 帧对象必须删除"
        assert released == [(old_frame_row.account_id, 10)], "旧 L2 帧配额必须释放"

    def test_non_video_is_skipped(self):
        service, _created = _build_service([])
        document = _document()
        document.media_type = "image"

        result = service._enhance_l2(document)

        assert result["media_type"] == "image"

    def test_frame_vision_failure_does_not_abort_other_frames(self):
        """单帧视觉失败只跳过该帧，不影响同窗口其他帧。"""
        service, created = _build_service(
            [_l1_frame_segment("frames/l1.jpg", time_offset=100.0)]
        )
        service.media_extractor = SimpleNamespace(
            _extract_frames_in_range=lambda video_path, out_dir, *, start_sec, duration_sec: [
                ExtractedFrame(path="/tmp/f1.jpg", time_offset=91.0),
                ExtractedFrame(path="/tmp/f2.jpg", time_offset=91.5),
            ]
        )
        service._download_document_video = lambda document: "/tmp/v.mp4"
        service._persist_window_frame = lambda frame, document: "frames/w1.jpg"
        service._load_frame_data_uri = lambda key: "data:image/jpeg;base64,AAA"

        def _vision(data_uri):
            if data_uri.endswith("AAA"):
                raise RuntimeError("vision down")
            return "ok"

        service._invoke_l2_vision = _vision

        service._enhance_l2(_document())

        assert created == []

    def test_window_frame_without_persist_is_skipped(self):
        """留存失败（key 为空）时不建 Segment——否则 frame_url 空会让视觉索引失效。"""
        service, created = _build_service(
            [_l1_frame_segment("frames/l1.jpg", time_offset=100.0)]
        )
        service.media_extractor = SimpleNamespace(
            _extract_frames_in_range=lambda video_path, out_dir, *, start_sec, duration_sec: [
                ExtractedFrame(path="/tmp/f1.jpg", time_offset=91.0),
            ]
        )
        service._download_document_video = lambda document: "/tmp/v.mp4"
        service._persist_window_frame = lambda frame, document: ""
        service._invoke_l2_vision = lambda data_uri: "详述"

        service._enhance_l2(_document())

        assert created == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_l2_range_sampling.py -q --no-header --no-cov`
Expected: FAIL —— 现有 `_enhance_l2` 不接收窗口推导，`window_frames` 键不存在 / 调用次数不符

- [ ] **Step 3: 实现**

`knowledge_indexing_service.py` 顶部 import 补上：

```python
import os as _os  # 若已 import os 则跳过本行
```

（该文件已有 `import tempfile` / `import os`，确认后无需重复引入。）

在 `_enhance_l2` 之前新增常量（文件顶部常量区）：

```python
# L2 密抽窗口的临时子目录名
_L2_WINDOW_DIR = "l2_windows"
```

把 `_enhance_l2` 整体替换为：

```python
    def _enhance_l2(
        self, document: KnowledgeDocument, explicit_range: tuple[float, float] | None = None
    ) -> dict:
        """L2 增强主体：由 L1 命中帧定位窗口，只在窗口内密抽并详述。

        规格 §5.4：L2 是「放大镜」不是「重扫」。L1 帧的 `time_offset` 给出
        目标时刻，扩窗后仅在窗口内按 0.5 秒/帧抽取——这是成本从「整片逐帧」
        降到「按需区间」的关键。

        其余媒体类型（图片/音频）的 L2 增强仍是后续增量，此处直接返回。
        """
        media_type = getattr(document, "media_type", None) or DocumentMediaType.DOCUMENT.value
        if media_type != DocumentMediaType.VIDEO.value:
            return {"media_type": media_type, "window_frames": 0}

        segments = self.db.session.query(KnowledgeSegment).filter(
            KnowledgeSegment.knowledge_document_id == document.id,
        ).all()

        # 窗口只能由 **L1 片段**推导：L2 自己产生的窗口帧若参与推导，会形成
        # 「上一轮窗口 → 下一轮更大窗口」的自我放大（帧数逐轮膨胀）。
        l1_segments = [
            s for s in segments if not (getattr(s, "metadata_", None) or {}).get("tier2_window")
        ]
        hit_offsets = [
            frame["time_offset"]
            for frame in (self._segment_frame(s) for s in l1_segments)
            if frame is not None
        ]

        # 重新触发 L2 前先清掉上一轮的窗口片段与帧：否则会累积重复片段，
        # 且旧帧对象永不释放（帧已计配额，等于配额泄漏）。
        self._clear_previous_l2_windows(document, segments)

        windows = plan_l2_windows(
            hit_offsets,
            duration_sec=self._resolve_document_duration(document),
            explicit_range=explicit_range,
        )
        if not windows:
            logger.info("L2 无可用窗口（无 L1 命中帧），跳过 document_id=%s", document.id)
            return {"media_type": media_type, "window_frames": 0, "windows": 0}

        created = 0
        for index, (start_sec, duration_sec) in enumerate(windows, start=1):
            created += self._extract_and_persist_window(
                document, start_sec, duration_sec, window_index=index
            )
        return {
            "media_type": media_type,
            "window_frames": created,
            "windows": len(windows),
        }

    def _clear_previous_l2_windows(self, document: KnowledgeDocument, segments) -> None:
        """删除上一轮 L2 窗口片段及其帧对象、记录与配额。

        L2 的窗口帧是**新建**的持久化产物（与 L1 帧不同，L1 每轮由
        `_release_stale_frames` 统一清理）。若不清理旧窗口，重复触发会：
        1. 累积重复片段（同一时间段出现多份详述）；
        2. 旧帧对象与配额永不释放（泄漏）。
        """
        stale = [
            s for s in segments if (getattr(s, "metadata_", None) or {}).get("tier2_window")
        ]
        if not stale:
            return

        keys: list[str] = []
        for segment in stale:
            metadata = getattr(segment, "metadata_", None) or {}
            frame_url = str(metadata.get("frame_url") or "").strip()
            if frame_url and frame_url not in keys:
                keys.append(frame_url)

        rows = (
            self.db.session.query(UploadFile)
            .filter(UploadFile.key.in_(keys))
            .all()
            if keys
            else []
        )
        seen: set[str] = set()
        for row in rows:
            key = getattr(row, "key", None)
            if not key or key in seen:
                continue
            seen.add(key)
            try:
                self._delete_frame_object(key, getattr(row, "storage_backend", None))
            except Exception:
                logger.warning(
                    "清理旧 L2 帧对象失败 document_id=%s key=%s", document.id, key, exc_info=True,
                )
            try:
                account_id = getattr(row, "account_id", None)
                size = int(getattr(row, "size", 0) or 0)
                if account_id is not None and size > 0:
                    self._release_frame_quota(account_id, size)
            except Exception:
                logger.warning(
                    "释放旧 L2 帧配额失败 document_id=%s key=%s", document.id, key, exc_info=True,
                )
            try:
                self.delete(row)
            except Exception:
                logger.warning(
                    "删除旧 L2 帧记录失败 document_id=%s key=%s", document.id, key, exc_info=True,
                )

        for segment in stale:
            try:
                self.knowledge_vector_service.remove_segment(segment)
            except Exception:
                logger.warning(
                    "清理旧 L2 片段向量失败 segment_id=%s", segment.id, exc_info=True,
                )
            try:
                self.delete(segment)
            except Exception:
                logger.warning(
                    "删除旧 L2 片段失败 segment_id=%s", segment.id, exc_info=True,
                )

    def _resolve_document_duration(self, document: KnowledgeDocument) -> float:
        """解析视频时长（独立方法便于测试替换）；探测失败返回 0.0（不裁剪上界）。

        注意：`probe_duration_sec` 需要**本地文件路径**，而 `upload_file.key`
        是对象存储 key——必须先下载到临时文件再探测，否则恒为 0.0（窗口上界失效）。
        本方法在 `_download_document_video` 之外单独下载，是为了保证「时长探测」
        与「实际抽帧」互不复用同一临时文件的生命周期。
        """
        try:
            upload_file = self._get_upload_file(document)
            with tempfile.TemporaryDirectory() as temp_dir:
                local_path = os.path.join(
                    temp_dir, os.path.basename(upload_file.key) or "material.mp4"
                )
                self.cos_service.download_file(upload_file.key, local_path)
                duration = probe_duration_sec(local_path)
        except Exception:
            logger.warning("L2 时长解析失败 document_id=%s", document.id, exc_info=True)
            duration = 0.0
        return float(duration or 0.0)

    def _extract_and_persist_window(
        self, document: KnowledgeDocument, start_sec: float, duration_sec: float, *, window_index: int
    ) -> int:
        """对单个窗口密抽并逐帧建 Segment；返回成功入库的帧数。

        单帧失败只跳过该帧——L2 是增强能力，不应因个别帧失败丢弃整个窗口。

        **必须同时写文本向量与视觉向量**：L2 的价值就是让窗口内的细节「能被搜到」。
        只建 Segment 不索引，用户永远检索不到这些片段，等于白跑。
        """
        knowledge_base = document.knowledge_base
        if knowledge_base is None:
            return 0

        video_path = self._download_document_video(document)
        if not video_path:
            return 0

        created = 0
        next_position = self._next_segment_position(document)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                out_dir = os.path.join(temp_dir, _L2_WINDOW_DIR, str(window_index))
                frames = self.media_extractor._extract_frames_in_range(
                    video_path, out_dir, start_sec=start_sec, duration_sec=duration_sec
                )
                for frame in frames:
                    try:
                        frame_url = self._persist_window_frame(frame, document)
                    except Exception:
                        logger.warning(
                            "L2 窗口帧留存失败 document_id=%s offset=%s",
                            document.id, frame.time_offset, exc_info=True,
                        )
                        frame_url = ""
                    if not frame_url:
                        continue
                    try:
                        data_uri = self._load_frame_data_uri(frame_url)
                        detailed = self._invoke_l2_vision(data_uri)
                    except Exception:
                        logger.warning(
                            "L2 窗口帧视觉详述失败 document_id=%s frame_url=%s",
                            document.id, frame_url, exc_info=True,
                        )
                        continue
                    if not str(detailed or "").strip():
                        continue
                    segment = self.create(
                        KnowledgeSegment,
                        knowledge_base_id=document.knowledge_base_id,
                        knowledge_document_id=document.id,
                        owner_account_id=document.owner_account_id,
                        position=next_position,
                        content=detailed,
                        keywords=self.jieba_service.extract_keywords(detailed, 10),
                        metadata_={
                            "media_type": DocumentMediaType.VIDEO.value,
                            "scene_index": created + 1,
                            "frame_url": frame_url,
                            "time_offset": float(frame.time_offset or 0.0),
                            # 标记为 L2 窗口帧，区别于 L1 全片粗抽帧
                            "tier2_window": True,
                            "tier2_window_start": float(start_sec),
                            "tier2_window_duration": float(duration_sec),
                            "tier2_status": "completed",
                        },
                        character_count=len(detailed),
                        token_count=self.embeddings_service.calculate_token_count(detailed),
                        status=SegmentStatus.INDEXING.value,
                        enabled=False,
                    )
                    # 文本向量：让窗口细节可被文本检索命中
                    self.knowledge_vector_service.index_segment(segment, knowledge_base)
                    # 视觉向量：让窗口细节可被画面检索命中（与 L1 帧共用同一通道）
                    self._index_visual_vectors(document, [segment])
                    # 置为完成并启用（与 L1 收尾语义一致）
                    self.update(
                        segment,
                        status=SegmentStatus.COMPLETED.value,
                        enabled=True,
                    )
                    next_position += 1
                    created += 1
        except Exception:
            logger.warning(
                "L2 窗口抽帧失败 document_id=%s window=%s", document.id, start_sec, exc_info=True
            )
        return created

    def _next_segment_position(self, document: KnowledgeDocument) -> int:
        """返回该文档下一个可用的片段序号（L2 新片段接在既有片段之后）。"""
        existing = self.db.session.query(KnowledgeSegment).filter(
            KnowledgeSegment.knowledge_document_id == document.id,
        ).all()
        return max((int(getattr(s, "position", 0) or 0) for s in existing), default=0) + 1

    def _download_document_video(self, document: KnowledgeDocument) -> str:
        """把素材视频下载到临时文件；失败返回空串（单窗口失败不中断整轮 L2）。"""
        try:
            upload_file = self._get_upload_file(document)
            directory = tempfile.mkdtemp()
            target = os.path.join(directory, os.path.basename(upload_file.key) or "material.mp4")
            self.cos_service.download_file(upload_file.key, target)
            return target
        except Exception:
            logger.warning("L2 素材下载失败 document_id=%s", document.id, exc_info=True)
            return ""

    def _load_frame_data_uri(self, frame_url: str) -> str:
        """把留存帧下载并转为 data URI（独立方法便于测试替换）。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = os.path.join(temp_dir, os.path.basename(frame_url))
            self.cos_service.download_file(frame_url, local_path)
            return path_to_data_uri(local_path)

    def _persist_window_frame(self, frame, document: KnowledgeDocument) -> str:
        """把窗口帧留存为 UploadFile，返回对象 key（失败抛错由调用方降级）。"""
        return str(
            self.media_extractor._persist_frame(
                frame.path,
                account_id=getattr(document, "owner_account_id", None),
                document_id=document.id,
            ).key
            or ""
        )
```

并在顶部 import 补上：

```python
from internal.core.vision.frame_sampling import plan_l2_windows
from internal.core.vision.vision_invoke import path_to_data_uri, probe_duration_sec
```

（原 `from internal.core.vision.vision_invoke import path_to_data_uri` 一行改为上面的合并写法。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_l2_range_sampling.py -q --no-header --no-cov`
Expected: PASS（6 个用例）

- [ ] **Step 5: 运行索引链路回归**

Run: `python -m pytest test/internal/service/test_visual_indexing.py test/internal/service/test_knowledge_media_ingest.py test/internal/service/test_knowledge_l2_trigger.py test/internal/task/test_knowledge_l2_tasks.py test/internal/service/test_l2_range_sampling.py -q --no-header --no-cov`
Expected: PASS

> **注意**：若 `test_visual_indexing.py` 中已有对旧 `_enhance_l2` 行为的断言（如 `enhanced_segments`），需按新语义更新——新返回值键为 `window_frames` / `windows`。

- [ ] **Step 6: 提交**

```bash
git add api/internal/service/knowledge_indexing_service.py api/test/internal/service/test_l2_range_sampling.py
git commit -m "feat(knowledge): L2 samples only derived hit windows"
```

---

## Task 5: 显式区间透传（路由 → 服务 → 任务）

**Files:**
- Modify: `api/internal/service/knowledge_base_service.py`
- Modify: `api/app/http/knowledge_mcp_routes.py`
- Modify: `api/internal/task/knowledge_l2_tasks.py`
- Test: `api/test/internal/service/test_l2_explicit_range.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/test_l2_explicit_range.py`：

```python
"""L2 显式区间透传测试（规格 §2「A+B」：自动推导 + 支持显式指定）。"""
from types import SimpleNamespace
from uuid import uuid4

from internal.service.knowledge_base_service import KnowledgeBaseService


class _Task:
    def __init__(self):
        self.calls = []

    def delay(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})


def _service(monkeypatch):
    service = KnowledgeBaseService.__new__(KnowledgeBaseService)
    service.get_user_content_base = lambda kb_id, account: SimpleNamespace(id=kb_id)
    document = SimpleNamespace(id=uuid4(), knowledge_base_id=uuid4())
    service.get = lambda model, doc_id: document
    task = _Task()
    import internal.task.knowledge_l2_tasks as module
    monkeypatch.setattr(module, "build_document_l2_task", task)
    return service, document, task


def test_explicit_range_is_forwarded_to_task(monkeypatch):
    service, document, task = _service(monkeypatch)
    account = SimpleNamespace(id=uuid4())

    service.trigger_document_l2(
        document.knowledge_base_id, document.id, account,
        start_sec=120.0, end_sec=140.0,
    )

    assert task.calls, "必须派发任务"
    assert task.calls[0]["kwargs"]["start_sec"] == 120.0
    assert task.calls[0]["kwargs"]["end_sec"] == 140.0


def test_without_explicit_range_kwargs_are_none(monkeypatch):
    service, document, task = _service(monkeypatch)
    account = SimpleNamespace(id=uuid4())

    service.trigger_document_l2(document.knowledge_base_id, document.id, account)

    assert task.calls[0]["kwargs"]["start_sec"] is None
    assert task.calls[0]["kwargs"]["end_sec"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_l2_explicit_range.py -q --no-header --no-cov`
Expected: FAIL —— `TypeError: trigger_document_l2() got an unexpected keyword argument 'start_sec'`

- [ ] **Step 3: 实现**

`knowledge_base_service.py` 的 `trigger_document_l2` 签名与派发改为：

```python
    def trigger_document_l2(
            self,
            knowledge_base_id: UUID,
            document_id: UUID,
            account: Account,
            start_sec: float | None = None,
            end_sec: float | None = None,
    ) -> dict:
        """按需触发某素材的 L2 深度解析（用户显式要求）。

        L1 上传即跑、保证素材「能被找到」；L2 逐帧视觉详述最贵，故**只在显式要求时触发**，
        不做定时轮询。派发走 Celery，不可用时回退同步执行，避免请求静默丢失。

        `start_sec` / `end_sec` 均给出时按显式区间密抽（规格 §2「A+B」）；
        缺省时由 L1 命中帧的 time_offset 自动推导窗口。

        校验顺序与 `get_document_detail` 一致：先校验知识库归属，再校验文档是否属于该库，
        防止越权触发他人素材的付费解析。
        """
        # 1.校验知识库归属
        self.get_user_content_base(knowledge_base_id, account)

        # 2.查询文档并校验归属
        document = self.get(KnowledgeDocument, document_id)
        if document is None or str(document.knowledge_base_id) != str(knowledge_base_id):
            raise NotFoundException("该文档不存在，请核实后重试")

        # 3.派发 L2 任务（Celery 优先，不可用时同步兜底）
        return self._dispatch_document_l2(
            document.id, start_sec=start_sec, end_sec=end_sec
        )

    def _dispatch_document_l2(
        self, document_id, *, start_sec: float | None = None, end_sec: float | None = None
    ) -> dict:
        """派发 L2 深度解析：优先 Celery 后台执行，不可用时回退同步，保证解析不丢失。"""
        try:
            from internal.task.knowledge_l2_tasks import build_document_l2_task

            build_document_l2_task.delay(
                str(document_id), start_sec=start_sec, end_sec=end_sec
            )
            logging.info("L2 深度解析已派发 Celery document_id=%s", document_id)
            return {"document_id": str(document_id), "dispatched": True}
        except Exception:
            logging.warning(
                "L2 派发 Celery 失败，回退同步执行 document_id=%s", document_id, exc_info=True,
            )
            return self._get_knowledge_indexing_service().build_document_l2(
                document_id, start_sec=start_sec, end_sec=end_sec
            )
```

`knowledge_l2_tasks.py` 的任务签名改为：

```python
@shared_task(
    name="internal.task.knowledge_l2_tasks.build_document_l2_task",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def build_document_l2_task(
    self, document_id: str, start_sec: float | None = None, end_sec: float | None = None
):
    """对指定文档执行 L2 深度解析。

    幂等：重复执行会覆盖同一批 Segment，不产生重复片段。
    `start_sec` / `end_sec` 均给出时按显式区间密抽，否则由 L1 命中帧自动推导窗口。
    """
    from app.http.module import injector
    from internal.service.knowledge_indexing_service import KnowledgeIndexingService

    indexing_service = injector.get(KnowledgeIndexingService)
    try:
        return indexing_service.build_document_l2(
            document_id, start_sec=start_sec, end_sec=end_sec
        )
    except Exception as exc:
        logger.exception("L2 深度解析失败 document_id=%s", document_id)
        raise self.retry(exc=exc)
```

`knowledge_indexing_service.py` 的 `build_document_l2` 改为接收区间并传给 `_enhance_l2`：

```python
    def build_document_l2(
        self,
        document_id: UUID,
        start_sec: float | None = None,
        end_sec: float | None = None,
    ) -> dict:
        """对已完成的素材执行 L2 深度解析（按需触发）。

        L2 让素材「能被精细修改」：由 L1 命中帧定位窗口，只在窗口内按 0.5 秒/帧
        密抽并逐帧详述，**不重扫全片**（规格 §5.4）。窗口内新帧新建 Segment，
        与 L1 片段区分（`tier2_window=True`）。
        状态写入 parse_profile.tier2，失败只标记 error 不回滚 L1 产物——
        L1 的「能被找到」能力必须保留。

        Returns:
            {"document_id": ..., "tier2": {...}}，供任务侧记录。
        """
        document = self.get(KnowledgeDocument, document_id)
        if document is None:
            raise NotFoundException("知识库文档不存在")

        parse_profile = dict(getattr(document, "parse_profile", None) or {})
        parse_profile["tier2"] = {"status": "running"}
        self.update(document, parse_profile=parse_profile)

        explicit_range = (
            (float(start_sec), float(end_sec))
            if start_sec is not None and end_sec is not None
            else None
        )

        try:
            result = self._enhance_l2(document, explicit_range=explicit_range)
        except Exception as exc:
            logger.exception("L2 深度解析失败 document_id=%s", document_id)
            parse_profile["tier2"] = {"status": "error", "error": str(exc)}
            self.update(document, parse_profile=parse_profile)
            raise

        parse_profile["tier2"] = {"status": "completed", **result}
        self.update(document, parse_profile=parse_profile)
        return {"document_id": str(document_id), "tier2": parse_profile["tier2"]}
```

（`_enhance_l2` 已接受 `explicit_range` 参数——Task 4 已实现；Task 5 只需把 `build_document_l2` 的区间透传下去。）

`knowledge_mcp_routes.py` 的 L2 路由改为读取可选区间：

```python
    @quart_app.post("/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>/l2")
    async def async_trigger_document_l2(knowledge_base_id, document_id) -> Response:
        """async 触发某素材的 L2 深度解析（按需，不做定时轮询）。

        请求体可选 `start_sec` / `end_sec`：给出时按显式区间密抽，
        否则由 L1 命中帧自动推导窗口。
        """
        account, err = await _resolve_account()
        if err is not None:
            return err

        from internal.service import KnowledgeBaseService

        payload = await request.get_json(force=True, silent=True) or {}
        await _to_thread(
            _get_service(KnowledgeBaseService).trigger_document_l2,
            knowledge_base_id,
            document_id,
            account,
            start_sec=payload.get("start_sec"),
            end_sec=payload.get("end_sec"),
        )
        return _ok_msg("L2 深度解析已触发")
```

> 请求体读取方式**照抄同文件既有 POST 路由**（统一为
> `payload = await request.get_json(force=True, silent=True) or {}`，
> 见该文件 L819 等约 20 处）；**不要**引入新 helper。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_l2_explicit_range.py -q --no-header --no-cov`
Expected: PASS（2 个用例）

- [ ] **Step 5: 运行 L2 全链路回归**

Run: `python -m pytest test/internal/service/test_l2_explicit_range.py test/internal/service/test_knowledge_l2_trigger.py test/internal/service/test_l2_range_sampling.py test/internal/task/test_knowledge_l2_tasks.py test/app/http -q --no-header --no-cov`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add api/internal/service/knowledge_base_service.py api/internal/service/knowledge_indexing_service.py api/internal/task/knowledge_l2_tasks.py api/app/http/knowledge_mcp_routes.py api/test/internal/service/test_l2_explicit_range.py
git commit -m "feat(knowledge): accept explicit time range for L2 sampling"
```

---

## Task 6: 同步架构文档

**Files:**
- Modify: `docs/prd/modules/02-knowledge-base.md`
- Modify: `docs/prd/execution-roadmap.md`

- [ ] **Step 1: 更新 02-knowledge-base.md §11.11**

把 §11.11.2「状态与回写语义」中关于 L2 的描述改写为窗口化密抽：

```markdown
#### 11.11.2 区间窗口密抽（规格 §5.4）

`KnowledgeIndexingService.build_document_l2(document_id, start_sec=None, end_sec=None)`：

- **窗口推导**：`plan_l2_windows(hit_offsets, duration_sec, explicit_range)`（纯函数，`frame_sampling.py`）。命中帧的 `time_offset` 各向两侧扩 `L2_WINDOW_PADDING_SEC`（10s），重叠/相接窗口合并；`start_sec`+`end_sec` 均给出时按其显式区间。窗口裁剪到 `[0, duration]`。
- **窗口内密抽**：`extract_video_frames_in_range`（`vision_invoke.py`）用 ffmpeg `-ss`/`-t` 限定解码范围 + `-vf fps=1/0.5` 控制密度 + `-frames:v` 封顶。帧数 = `resolve_l2_window_frame_count(duration)` = 窗口秒数 × 2，上限 `L2_MAX_FRAMES_PER_WINDOW`（600 帧 = 5 分钟）。
- **回写语义**：窗口内帧**新建 Segment**（`metadata.tier2_window=True` + `tier2_window_start` / `tier2_window_duration` / `time_offset`），与 L1 全片粗抽帧区分；不再改写 L1 片段 content。
- **无命中即不抽**：没有 L1 命中帧且未给显式区间时，窗口列表为空 → 不抽任何帧（L2 是「放大镜」不是「重扫全片」）。
- **成本**：1 小时视频改 20 秒片段，视觉调用从 7,200 次降到约 40 次。
- **配额**：窗口帧是新的持久化产物，经存储代理计入配额（同 L1 帧口径）；重解析会由 `_release_stale_frames` 清理上一轮帧。
- 状态写入 `parse_profile.tier2`，失败只标 error 不回滚 L1 产物。
```

- [ ] **Step 2: 更新 execution-roadmap.md**

在 P3.5 小节之后追加：

```markdown
### 知识库产品形态 P3.6：L2 区间密抽（已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **L2 窗口推导纯函数** | `frame_sampling.py`（`plan_l2_windows` / `merge_time_windows` / `resolve_l2_window_frame_count` / `L2_WINDOW_PADDING_SEC` / `L2_MAX_FRAMES_PER_WINDOW`） | ✅ 已落地；命中帧 ±10s 扩窗并合并，单窗上限 600 帧 |
| **按区间抽帧** | `vision_invoke.py`（`extract_video_frames_in_range`，ffmpeg `-ss`/`-t`/`fps=`/`-frames:v`） | ✅ 已落地；偏移是视频时间轴绝对位置，与 L1 同一坐标系 |
| **L2 改为窗口化密抽** | `knowledge_indexing_service.py`（`_enhance_l2` / `_extract_and_persist_window` / `_persist_window_frame`） | ✅ 已落地；窗口内帧新建 Segment（`tier2_window=True`），无命中不抽 |
| **显式区间透传** | `knowledge_base_service.py` / `knowledge_l2_tasks.py` / `knowledge_mcp_routes.py` | ✅ 已落地；`start_sec`+`end_sec` 均给出时按其密抽 |

> **尚未落地**：HyperFrames 渲染（计划 3）。场景切分（`select='gt(scene,...)'`）仍为后续增量——当前 L2 按时间窗口密抽，非按场景。
```

- [ ] **Step 3: 提交**

```bash
git add docs/prd/modules/02-knowledge-base.md docs/prd/execution-roadmap.md
git commit -m "docs(knowledge): document L2 range sampling"
```

- [ ] **Step 4: 刷新知识图谱**

Run: `python -m graphify update .`

---

## 自检清单（实施者收尾前逐项确认）

- [ ] 每个新符号都有生产调用方（`plan_l2_windows` → `_enhance_l2`；`extract_video_frames_in_range` → `_extract_frames_in_range` → `_enhance_l2`；`_persist_window_frame` → `_extract_and_persist_window`）
- [ ] 新符号若暂未被生产代码调用，必须在回复与文档中标注「已提供能力但未接入」，不得写成「已实现」
- [ ] `time_offset` 在 L1 与 L2 帧中**同一坐标系**（绝对视频时间），可由测试断言
- [ ] 600 帧上限有测试覆盖（`resolve_l2_window_frame_count(3600) == 600`）
- [ ] 无命中时不抽帧（成本保护），有测试覆盖
- [ ] 窗口帧的 `UploadFile` 只创建一条记录（复用 `_persist_frame`，不重复建）
- [ ] 全量回归：`python -m pytest test -q --no-header --no-cov`
