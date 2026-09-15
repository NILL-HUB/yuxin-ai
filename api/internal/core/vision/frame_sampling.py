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
