"""视频内容时间线规划（纯函数，无 IO）。

L1 视频解析从「逐帧独立调用」升级为「批次化时间线叙述」的核心纯逻辑：
- 场景路由：有 ASR cues → 场景 B（台词句锚点）；无 cues → 场景 A（时间片锚点）；
- 锚点规划：把 cues / 帧块投影成带时间窗口的锚点（时间码一律来自测量，模型不生成）；
- 分批：每批 ≈10 个锚点，批间连续；
- 解析容错：把模型返回的 JSON 数组按锚点顺序对齐，非法 JSON / 越界索引 / 空描述分别处理。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from internal.core.vision.vision_invoke import ExtractedFrame

# 每批锚点数（成本与上下文窗口的折中）
TIMELINE_BATCH_SIZE = 10
# 场景 A 分块：块间重叠帧数（保证时间连续性）
TIMELINE_BLOCK_OVERLAP = 1


class TimelineParseError(ValueError):
    """模型返回无法解析为描述数组。"""


@dataclass
class TimelineAnchor:
    """一个内容时间线锚点（= 一个编辑挂载点 / 一个 MediaSegment 段落）。"""

    anchor_type: str  # "speech_sentence" | "time_slot"
    anchor_text: str
    start_sec: float
    end_sec: float
    speech_text: str
    frames: list[ExtractedFrame] = field(default_factory=list)


def _cue_text(cue: dict) -> str:
    return str(cue.get("text") or "").strip()


def _cue_start(cue: dict) -> float:
    return float(cue.get("start") or 0.0)


def _cue_end(cue: dict) -> float:
    return float(cue.get("end") or _cue_start(cue))


def _frame_in_window(frame: ExtractedFrame, start: float, end: float) -> bool:
    return start <= float(frame.time_offset or 0.0) <= end


def plan_scene_b_anchors(
    cues: list[dict], frames: list[ExtractedFrame]
) -> list[TimelineAnchor]:
    """场景 B：以 ASR 句子为骨架，把帧按 cue 时间范围归组。"""
    anchors: list[TimelineAnchor] = []
    for cue in cues:
        text = _cue_text(cue)
        start = _cue_start(cue)
        end = max(_cue_end(cue), start)
        in_window = [f for f in frames if _frame_in_window(f, start, end)]
        anchors.append(
            TimelineAnchor(
                anchor_type="speech_sentence",
                anchor_text=text,
                start_sec=start,
                end_sec=end,
                speech_text=text,
                frames=in_window,
            )
        )
    return anchors


def plan_scene_a_blocks(
    frames: list[ExtractedFrame],
    block_size: int = TIMELINE_BATCH_SIZE,
    overlap: int = TIMELINE_BLOCK_OVERLAP,
) -> list[TimelineAnchor]:
    """场景 A：无语音时把 L1 帧按连续块分组，块间重叠 1 帧保证时间连续性。"""
    if not frames:
        return []
    ordered = sorted(frames, key=lambda f: float(f.time_offset or 0.0))
    anchors: list[TimelineAnchor] = []
    index = 0
    while index < len(ordered):
        block = ordered[index : index + block_size]
        start_sec = float(block[0].time_offset or 0.0)
        end_sec = float(block[-1].time_offset or start_sec)
        anchors.append(
            TimelineAnchor(
                anchor_type="time_slot",
                anchor_text="",
                start_sec=start_sec,
                end_sec=end_sec,
                speech_text="",
                frames=block,
            )
        )
        index += block_size
        if index < len(ordered):
            index -= overlap
    return anchors


def build_timeline_plan(
    cues: list[dict], frames: list[ExtractedFrame]
) -> tuple[str, list[TimelineAnchor]]:
    """路由判定：有 cues → 场景 B；无 cues → 场景 A。"""
    if cues:
        return "B", plan_scene_b_anchors(cues, frames)
    return "A", plan_scene_a_blocks(frames)


def chunk_anchors(
    anchors: list[TimelineAnchor], batch_size: int = TIMELINE_BATCH_SIZE
) -> list[list[TimelineAnchor]]:
    """按批大小连续切分锚点（每批 ≈10 锚点）。"""
    return [anchors[i : i + batch_size] for i in range(0, len(anchors), batch_size)]


def anchor_representative_frame(anchor: TimelineAnchor) -> ExtractedFrame | None:
    """段落代表帧：取锚点内时间居中的帧；无帧返回 None。"""
    if not anchor.frames:
        return None
    ordered = sorted(anchor.frames, key=lambda f: float(f.time_offset or 0.0))
    return ordered[len(ordered) // 2]


def _strip_code_fence(text: str) -> str:
    """去掉模型常见的 ```json ... ``` 围栏（含未闭合的开头围栏）。"""
    stripped = text.strip()
    pattern = r"```(?:json)?\s*(.*?)```"
    match = re.search(pattern, stripped, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    if stripped.startswith("```"):
        # 模型输出以围栏开头但未闭合（内容直接在围栏后）：去掉开头围栏
        remainder = stripped[3:].lstrip()
        if remainder.lower().startswith("json"):
            remainder = remainder[4:].lstrip()
        return remainder
    return stripped


def parse_timeline_descriptions(text: str, anchor_count: int) -> list[tuple[int, str]]:
    """解析模型返回的 JSON 描述数组，返回 [(anchor_index, description)]。

    - 非法 JSON / 空返回 → TimelineParseError（调用方据此重试 / 降级）；
    - 锚点索引越界 → 丢弃该条目（容错，不抛错）；
    - description 为空（strip 后空串）→ 跳过该锚点。
    """
    raw = _strip_code_fence(str(text or ""))
    if not raw:
        raise TimelineParseError("模型返回为空")
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise TimelineParseError(f"模型返回非法 JSON: {raw[:200]}") from exc
    if not isinstance(payload, list):
        raise TimelineParseError(f"模型返回不是数组: {raw[:200]}")

    results: list[tuple[int, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("anchor_index", -1))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= anchor_count:
            continue
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        results.append((index, description))
    return results
