"""视频内容时间线规划纯函数单测（无 IO）。"""
import pytest

from internal.core.vision.timeline_planning import (
    TimelineAnchor,
    TimelineParseError,
    anchor_representative_frame,
    build_timeline_plan,
    chunk_anchors,
    parse_timeline_descriptions,
    plan_scene_a_blocks,
    plan_scene_b_anchors,
)
from internal.core.vision.vision_invoke import ExtractedFrame


def _frames(offsets: list[float]) -> list[ExtractedFrame]:
    return [
        ExtractedFrame(path=f"/tmp/f{i}.jpg", time_offset=float(t))
        for i, t in enumerate(offsets)
    ]


def test_plan_scene_b_uses_cue_window_and_groups_frames():
    cues = [
        {"start": 0.0, "end": 3.0, "text": "今天天气很好。"},
        {"start": 3.5, "end": 8.0, "text": "我们去公园散步。"},
    ]
    frames = _frames([1.0, 4.0, 6.0])

    anchors = plan_scene_b_anchors(cues, frames)

    assert [a.anchor_type for a in anchors] == ["speech_sentence", "speech_sentence"]
    assert anchors[0].start_sec == 0.0 and anchors[0].end_sec == 3.0
    assert anchors[0].anchor_text == "今天天气很好。"
    assert anchors[0].speech_text == "今天天气很好。"
    assert [f.time_offset for f in anchors[0].frames] == [1.0]
    assert [f.time_offset for f in anchors[1].frames] == [4.0, 6.0]


def test_plan_scene_b_keeps_anchor_when_cue_has_no_frame():
    anchors = plan_scene_b_anchors([{"start": 0.0, "end": 1.0, "text": "空窗"}], _frames([5.0]))

    assert len(anchors) == 1
    assert anchors[0].frames == []


def test_plan_scene_a_blocks_with_overlap():
    frames = _frames([0.0, 1.0, 2.0, 3.0, 4.0])

    anchors = plan_scene_a_blocks(frames, block_size=3, overlap=1)

    assert len(anchors) == 2
    assert anchors[0].start_sec == 0.0 and anchors[0].end_sec == 2.0
    assert anchors[1].start_sec == 2.0 and anchors[1].end_sec == 4.0
    assert [f.time_offset for f in anchors[1].frames] == [2.0, 3.0, 4.0]


def test_plan_scene_a_single_trailing_block():
    anchors = plan_scene_a_blocks(_frames([0.0, 1.0]), block_size=3, overlap=1)

    assert len(anchors) == 1
    assert anchors[0].start_sec == 0.0 and anchors[0].end_sec == 1.0


def test_build_timeline_plan_routes_by_cues():
    scenario_b, anchors_b = build_timeline_plan(
        [{"start": 0, "end": 1, "text": "x"}], _frames([0.5])
    )
    scenario_a, anchors_a = build_timeline_plan([], _frames([0.5]))

    assert scenario_b == "B" and anchors_b[0].anchor_type == "speech_sentence"
    assert scenario_a == "A" and anchors_a[0].anchor_type == "time_slot"


def test_chunk_anchors_splits_by_batch_size():
    anchors = [
        TimelineAnchor("time_slot", "", float(i), float(i + 1), "")
        for i in range(25)
    ]

    batches = chunk_anchors(anchors, batch_size=10)

    assert [len(b) for b in batches] == [10, 10, 5]


def test_anchor_representative_frame_is_midpoint():
    anchor = TimelineAnchor(
        "speech_sentence", "t", 0.0, 5.0, "t", frames=_frames([1.0, 2.0, 3.0])
    )

    assert anchor_representative_frame(anchor).time_offset == 2.0


def test_anchor_representative_frame_none_when_no_frames():
    anchor = TimelineAnchor("speech_sentence", "t", 0.0, 5.0, "t", frames=[])
    assert anchor_representative_frame(anchor) is None


def test_parse_timeline_descriptions_valid_array():
    text = '[{"anchor_index": 0, "description": "画面一"}, {"anchor_index": 1, "description": "画面二"}]'

    results = parse_timeline_descriptions(text, anchor_count=3)

    assert results == [(0, "画面一"), (1, "画面二")]


def test_parse_timeline_descriptions_accepts_code_fence():
    text = '```json\n[{"anchor_index": 0, "description": "画面"}]'
    assert parse_timeline_descriptions(text, 1) == [(0, "画面")]


def test_parse_timeline_descriptions_raises_on_invalid_json():
    with pytest.raises(TimelineParseError):
        parse_timeline_descriptions("不是 JSON", anchor_count=2)


def test_parse_timeline_descriptions_raises_on_empty():
    with pytest.raises(TimelineParseError):
        parse_timeline_descriptions("   ", anchor_count=2)


def test_parse_timeline_descriptions_skips_blank_and_out_of_range():
    text = (
        '[{"anchor_index": 0, "description": "  "},'
        '{"anchor_index": 99, "description": "越界"},'
        '{"anchor_index": 1, "description": "有效"}]'
    )
    assert parse_timeline_descriptions(text, anchor_count=2) == [(1, "有效")]
