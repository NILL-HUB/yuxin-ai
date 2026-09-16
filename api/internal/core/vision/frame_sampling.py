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

# L2 区间密抽：命中时刻两侧留白（秒）
L2_WINDOW_PADDING_SEC = 10.0
# L2 区间内抽帧密度：每 0.5 秒 1 帧
L2_INTERVAL_SEC = 0.5
# 单次窗口抽帧上限（600 帧 = 5 分钟 @0.5s/帧），挡住「整段触发 L2」
L2_MAX_FRAMES_PER_WINDOW = 600


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
