# KB 视频内容时间线改造 + 衔接 KB-P4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把知识库 L1 视频解析从「逐帧独立调用」升级为「批次化时间线叙述」（调次数 N→N/块、输出连贯带段落结构），单测 + 真机测试通过后衔接 KB-P4（视频编辑出片）。

**Architecture:** 抽帧 / 音轨 ASR 保持不变；新增纯函数时间线规划模块（场景路由、锚点投影、分批、JSON 解析容错）→ `vision_invoke` 新增多图批喂 → `_extract_video` 改为批喂循环（失败重试 1 次 → 降级逐帧）→ 时间码一律由服务端投影（ASR cues / 抽帧偏移），模型只输出描述数组 → 落库 `MediaSegment`（`source=vision_timeline`）→ L2 窗口来源适配 `start_sec/end_sec`。

**Tech Stack:** Python 3.12 / GLM-5.3-Flash（`vision_analyze`）/ pytest / ffmpeg（`imageio_ffmpeg` 静态兜底）

---

## 0. 前置结论与约束（执行者必读）

**Spec 权威来源**：[2026-09-20-video-content-timeline-design.md](../superpowers-specs/2026-09-20-video-content-timeline-design.md)。以下已实测 / 已确认：

| # | 事实 | 处理 |
| --- | --- | --- |
| 1 | 形态 A 真机实测：stodownload.mp4（73.5s / 15 帧）15 次调用 104s → 2 次调用 27s | 本计划按形态 A 落地 |
| 2 | `vision_analyze` 已绑定 GLM-5.3-Flash（commit 7d155c57），billable=true | 无需再动模型配置 |
| 3 | ASR `cues` 是唯一可信时间码（`audio_to_text_with_segments` 已提供）；抽帧偏移是第二来源 | 视觉模型**不输出时间码** |
| 4 | 既有单图 `invoke_vision_model(data_uri, prompt)` 在 vision_tools 内置工具等还有调用方 | **签名与行为不变**，只新增多图函数 |
| 5 | L1 时间线段取代逐帧段后，`parse_profile.frames` / 帧清单 / L2 定位依赖 `_segment_frame` 读 `time_offset` | `_segment_frame` 增加 `start_sec/end_sec` → 窗口中点回退 |
| 6 | 关键帧留存（UploadFile + 配额）语义不变：主路径只留存**段落代表帧**（每锚点 1 帧），降级路径逐帧留存 | 见 Task 3 |
| 7 | **工作区有他人未提交改动**（`api/app/http/user_routes_9.py`、`api/test/app/http/test_user_routes_9.py`、`api/t2.txt~t7.txt`、`docs/superpowers/plans/2026-09-20-admin-agent-p3c4-subjectization-closure.md`） | **不得触碰、不得卷入自己的 commit** |

**本计划不涉及**：新数据表 / 迁移（时间线条目仍是 `MediaSegment`，无 schema 变更）、检索链路（content 仍是文本）、L2 Celery 任务签名、KB-P4 具体实现（见文末「衔接 KB-P4」节）。

## 1. 文件结构规划

### 新建

| 文件 | 职责 |
| --- | --- |
| `api/internal/core/vision/timeline_planning.py` | **纯函数**：场景路由、锚点规划/投影、分批、JSON 解析容错。无 IO |
| `api/test/internal/core/vision/test_timeline_planning.py` | 纯函数单测 |

### 修改

| 文件 | 改动 |
| --- | --- |
| `api/internal/core/vision/vision_invoke.py` | 抽取共享消息构建 `_invoke_vision_content`；新增 `invoke_vision_model_multi(image_data_uris, prompt)` |
| `api/test/internal/core/vision/test_vision_invoke.py` | 追加多图批喂用例（现有 `test_invoke_vision_model_raises_without_model` 保持通过） |
| `api/internal/service/knowledge_media_extractor_service.py` | `_extract_video` 改造为批喂循环；新增 `_invoke_vision_batch` / `_process_timeline_batch` / `_build_batch_prompt` / `_fallback_frame_segments`；新增 `_TIMELINE_PROMPT` 常量 |
| `api/test/internal/service/test_knowledge_media_extractor_service.py` | 改写 3 个逐帧用例 + 新增 6 个时间线用例 |
| `api/internal/service/knowledge_indexing_service.py` | `_segment_frame`（L527-543）：`time_offset` 缺失时用 `(start_sec+end_sec)/2` 回退 |
| `api/test/internal/service/test_knowledge_indexing_service.py` | 追加 `_segment_frame` 时间线 metadata 回退用例 |
| `docs/prd/modules/02-knowledge-base.md` | L1 视频解析小节更新为时间线叙述 |
| `docs/prd/execution-roadmap.md` | KB-P4.5 状态更新 |

**接线自检（完成后逐项核对）**：

| 新符号 | 入口 |
| --- | --- |
| `build_timeline_plan` / `parse_timeline_descriptions` 等纯函数 | 唯一调用点 `knowledge_media_extractor_service._extract_video` |
| `invoke_vision_model_multi` | 唯一调用点 `_invoke_vision_batch`（service 层） |
| 时间线条目（`source=vision_timeline`） | 复用既有「MediaSegment → KnowledgeSegment → 索引」链路，入口 `extract()` |
| L2 窗口来源（start_sec/end_sec） | 既有入口 `POST /space/knowledge-bases/<kb_id>/documents/<document_id>/l2`，仅适配窗口字段 |

---

## Task 1: 时间线规划纯函数模块

**Files:**
- Create: `api/internal/core/vision/timeline_planning.py`
- Test: `api/test/internal/core/vision/test_timeline_planning.py`

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/core/vision/test_timeline_planning.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/core/vision/test_timeline_planning.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'internal.core.vision.timeline_planning'`

- [ ] **Step 3: 实现纯函数模块**

创建 `api/internal/core/vision/timeline_planning.py`：

```python
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
    """去掉模型常见的 ```json ... ``` 围栏。"""
    pattern = r"```(?:json)?\s*(.*?)```"
    match = re.search(pattern, text, flags=re.DOTALL)
    return match.group(1).strip() if match else text.strip()


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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/core/vision/test_timeline_planning.py -v`
Expected: PASS（16 passed）

- [ ] **Step 5: Commit**

```bash
git add api/internal/core/vision/timeline_planning.py api/test/internal/core/vision/test_timeline_planning.py
git commit -m "feat(kb): 视频内容时间线规划纯函数模块（场景路由/锚点投影/分批/JSON 容错）"
```

---

## Task 2: 多图批喂视觉调用

**Files:**
- Modify: `api/internal/core/vision/vision_invoke.py:56-77`
- Test: `api/test/internal/core/vision/test_vision_invoke.py`

- [ ] **Step 1: 写失败的测试**

在 `api/test/internal/core/vision/test_vision_invoke.py` 末尾追加：

```python
def test_invoke_vision_model_multi_sends_all_images(monkeypatch):
    """多图批喂应把每张图都作为 image_url 放进同一消息。"""
    import internal.core.vision.vision_invoke as module
    from internal.service.language_model_service import LanguageModelService

    captured = {}

    class _FakeLLM:
        def invoke(self, messages):
            captured["content"] = messages[0].content
            return type("R", (), {"content": "ok"})()

    monkeypatch.setattr(
        LanguageModelService, "get_feature_model", classmethod(lambda cls, _key: _FakeLLM())
    )

    result = module.invoke_vision_model_multi(
        ["data:image/jpeg;base64,AAAA", "data:image/jpeg;base64,BBBB"], "描述画面"
    )

    assert result == "ok"
    urls = [
        item["image_url"]["url"]
        for item in captured["content"]
        if item["type"] == "image_url"
    ]
    assert urls == ["data:image/jpeg;base64,AAAA", "data:image/jpeg;base64,BBBB"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/core/vision/test_vision_invoke.py -v`
Expected: FAIL — `AttributeError: module 'internal.core.vision.vision_invoke' has no attribute 'invoke_vision_model_multi'`

- [ ] **Step 3: 实现多图批喂**

修改 `api/internal/core/vision/vision_invoke.py`：把 L56-77 的单图函数重构为「共享消息构建 + 单图/多图两个入口」：

```python
def _invoke_vision_content(content: list) -> str:
    """把构造好的消息内容交给视觉模型，统一解析返回文本（无模型时抛错）。"""
    from langchain_core.messages import HumanMessage

    from internal.service.language_model_service import LanguageModelService

    llm = LanguageModelService.get_feature_model("vision_analyze")
    if llm is None:
        raise RuntimeError("未配置视觉分析模型")
    response = llm.invoke([HumanMessage(content=content)])
    text = getattr(response, "content", "")
    if isinstance(text, list):
        text = "\n".join(
            str(item.get("text", ""))
            for item in text
            if isinstance(item, dict) and item.get("text")
        )
    return str(text or "").strip()


def invoke_vision_model(data_uri: str, prompt: str) -> str:
    """调用平台视觉模型分析单张图片（入参为 data URI）。"""
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_uri}},
    ]
    return _invoke_vision_content(content)


def invoke_vision_model_multi(image_data_uris: list[str], prompt: str) -> str:
    """一次调用分析多张图片（时间线批喂）：文本 + 多张 image_url 同消息。"""
    content: list = [{"type": "text", "text": prompt}]
    content.extend(
        {"type": "image_url", "image_url": {"url": uri}} for uri in image_data_uris
    )
    return _invoke_vision_content(content)
```

- [ ] **Step 4: 运行测试确认通过（含既有单图用例回归）**

Run: `cd api && python -m pytest test/internal/core/vision/test_vision_invoke.py -v`
Expected: PASS（既有 8 个用例 + 新增 1 个全部通过；`test_invoke_vision_model_raises_without_model` 必须仍通过）

- [ ] **Step 5: Commit**

```bash
git add api/internal/core/vision/vision_invoke.py api/test/internal/core/vision/test_vision_invoke.py
git commit -m "feat(kb): vision 多图批喂 invoke_vision_model_multi（时间线批喂调用入口）"
```

---

## Task 3: `_extract_video` 批喂改造

**Files:**
- Modify: `api/internal/service/knowledge_media_extractor_service.py`
- Test: `api/test/internal/service/test_knowledge_media_extractor_service.py`

- [ ] **Step 1: 写失败的测试（先改既有用例，再加新用例）**

在 `api/test/internal/service/test_knowledge_media_extractor_service.py`：

1. **改写** `test_video_extraction_returns_segment_per_frame`（L253-284）为无音轨场景 A 用例：

```python
def test_video_extraction_scene_a_batches_into_timeline_segments(tmp_path):
    """无音轨视频走场景 A：一批锚点一次批喂，产出 timeline 段而非逐帧段。"""
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    frames = _write_frames(tmp_path, 12)
    service._extract_frames_with_offsets = lambda path, out_dir: frames
    service._transcribe_video_track = lambda path, upload: ("", [])
    calls = []

    def _batch(uris, prompt):
        calls.append(len(uris))
        return '[{"anchor_index": 0, "description": "块0"}, {"anchor_index": 1, "description": "块1"}]'

    service._invoke_vision_batch = _batch  # type: ignore[assignment]
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="promo.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    segments = service.extract(_document("video"), upload)

    timeline = [s for s in segments if s.metadata.get("source") == "vision_timeline"]
    assert len(timeline) == 2
    assert calls == [13]  # 12 帧 + 块间重叠 1 帧，全部一次批喂
    assert timeline[0].metadata["anchor_type"] == "time_slot"
    assert timeline[0].metadata["start_sec"] == 0.0
    assert timeline[0].metadata["end_sec"] == 9.0
    assert timeline[1].metadata["start_sec"] == 9.0  # 重叠帧归属下一块
    assert timeline[1].metadata["end_sec"] == 11.0
    assert timeline[0].content == "块0"
```

2. **改写** `test_video_extraction_skips_frames_that_fail_analysis`（L287-315）为「批喂两次失败 → 降级逐帧」用例：

```python
def test_video_extraction_falls_back_to_per_frame_after_batch_failures(tmp_path):
    """批喂连续失败（含重试）→ 降级为批内逐帧独立调用，仍产出片段。"""
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    frames = _write_frames(tmp_path, 3)
    service._extract_frames_with_offsets = lambda path, out_dir: frames
    service._transcribe_video_track = lambda path, upload: ("", [])
    batch_calls = {"n": 0}

    def _batch(uris, prompt):
        batch_calls["n"] += 1
        raise RuntimeError("vision down")

    service._invoke_vision_batch = _batch  # type: ignore[assignment]
    single_calls = {"n": 0}

    def _single(uri, prompt):
        single_calls["n"] += 1
        return "降级描述"

    service._invoke_vision = _single  # type: ignore[assignment]
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="clip.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    segments = service.extract(_document("video"), upload)

    assert batch_calls["n"] == 2  # 初次 + 重试 1 次
    assert single_calls["n"] == 3
    assert len(segments) == 3
    assert segments[0].metadata["time_offset"] == 0.0  # 降级段保留逐帧定位坐标
```

3. **改写** `test_video_extraction_raises_when_all_descriptions_blank`（L340-356）为场景 A 描述全空用例：

```python
def test_video_extraction_scene_a_all_blank_descriptions_raise(tmp_path):
    """场景 A 批喂返回全空描述时应抛错而不是产出空片段。"""
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames_with_offsets = lambda path, out_dir: _write_frames(tmp_path, 3)
    service._transcribe_video_track = lambda path, upload: ("", [])
    service._invoke_vision_batch = lambda uris, prompt: (  # type: ignore[assignment]
        '[{"anchor_index": 0, "description": "  "}]'
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="blank.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    with pytest.raises(RuntimeError):
        service.extract(_document("video"), upload)
```

4. **追加** 场景 B 用例（有台词）与解析容错用例，文件末尾新增：

```python
def test_video_extraction_scene_b_injects_speech_and_window(tmp_path):
    """有 ASR cues 走场景 B：锚点窗口 = cue 区间，speech_text 注入。"""
    cues = [
        {"start": 0.0, "end": 5.0, "text": "第一句台词。"},
        {"start": 5.5, "end": 9.0, "text": "第二句台词。"},
    ]
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames_with_offsets = lambda path, out_dir: _write_frames(tmp_path, 6)
    service._transcribe_video_track = lambda path, upload: ("两句台词", cues)
    service._invoke_vision_batch = lambda uris, prompt: (  # type: ignore[assignment]
        '[{"anchor_index": 0, "description": "画面A"}, {"anchor_index": 1, "description": "画面B"}]'
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="talk.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    segments = service.extract(_document("video"), upload)

    timeline = [s for s in segments if s.metadata.get("source") == "vision_timeline"]
    assert len(timeline) == 2
    assert timeline[0].metadata["anchor_type"] == "speech_sentence"
    assert timeline[0].metadata["start_sec"] == 0.0
    assert timeline[0].metadata["end_sec"] == 5.0
    assert timeline[0].metadata["speech_text"] == "第一句台词。"
    assert timeline[0].metadata["anchor_text"] == "第一句台词。"
    assert timeline[0].content == "画面A"
    assert timeline[1].metadata["speech_text"] == "第二句台词。"


def test_video_extraction_batch_retries_once_then_succeeds(tmp_path):
    """批喂首次失败重试一次成功，不降级。"""
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames_with_offsets = lambda path, out_dir: _write_frames(tmp_path, 2)
    service._transcribe_video_track = lambda path, upload: ("", [])
    calls = {"n": 0}

    def _batch(uris, prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return '[{"anchor_index": 0, "description": "重试成功"}]'

    service._invoke_vision_batch = _batch  # type: ignore[assignment]
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="r.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    segments = service.extract(_document("video"), upload)

    assert calls["n"] == 2
    timeline = [s for s in segments if s.metadata.get("source") == "vision_timeline"]
    assert timeline[0].content == "重试成功"


def test_video_extraction_scene_b_blank_description_falls_back_to_speech(tmp_path):
    """场景 B 模型未给描述时保留仅台词段落（可检索）。"""
    cues = [{"start": 0.0, "end": 3.0, "text": "只有台词。"}]
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames_with_offsets = lambda path, out_dir: _write_frames(tmp_path, 2)
    service._transcribe_video_track = lambda path, upload: ("只有台词。", cues)
    service._invoke_vision_batch = lambda uris, prompt: (  # type: ignore[assignment]
        '[{"anchor_index": 0, "description": "  "}]'
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="speech.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    segments = service.extract(_document("video"), upload)

    timeline = [s for s in segments if s.metadata.get("source") == "vision_timeline"]
    assert len(timeline) == 1
    assert timeline[0].content == "只有台词。"
    assert timeline[0].metadata["speech_text"] == "只有台词。"


def test_video_extraction_scene_a_empty_description_skips_anchor(tmp_path):
    """场景 A 某锚点描述为空时跳过该条，其余照常产出。"""
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames_with_offsets = lambda path, out_dir: _write_frames(tmp_path, 12)
    service._transcribe_video_track = lambda path, upload: ("", [])
    service._invoke_vision_batch = lambda uris, prompt: (  # type: ignore[assignment]
        '[{"anchor_index": 0, "description": "有效"}, {"anchor_index": 1, "description": "  "}]'
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="mixed.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    segments = service.extract(_document("video"), upload)

    timeline = [s for s in segments if s.metadata.get("source") == "vision_timeline"]
    assert len(timeline) == 1
    assert timeline[0].content == "有效"
```

注意：`test_video_extraction_raises_when_no_frames_extracted`（L317-332）保持不变（抽帧为空先抛）。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_media_extractor_service.py -v`
Expected: FAIL — 既有逐帧用例因行为变更失败（断言不匹配）+ 新用例报 `AttributeError: 'KnowledgeMediaExtractorService' object has no attribute '_invoke_vision_batch'`

- [ ] **Step 3: 实现批喂改造**

修改 `api/internal/service/knowledge_media_extractor_service.py`：

3.1 顶部 import 与常量：

```python
from internal.core.vision.timeline_planning import (
    TimelineAnchor,
    anchor_representative_frame,
    build_timeline_plan,
    chunk_anchors,
    parse_timeline_descriptions,
)
from internal.core.vision.vision_invoke import (
    ExtractedFrame,
    extract_video_audio,
    extract_video_frames_in_range,
    extract_video_frames_with_offsets,
    invoke_vision_model,
    invoke_vision_model_multi,
    path_to_data_uri,
)
```

在 `_VIDEO_FRAME_PROMPT` 之后新增：

```python
_TIMELINE_PROMPT = (
    "这是视频内容时间线描述任务。下面给出若干锚点（台词句或时间片）及对应画面帧。\n"
    "请按锚点顺序，为每个锚点描述其代表画面：画面主体、场景、动作与镜头类型。\n"
    "输出要求：\n"
    "1. 只输出一个 JSON 数组，形如 [{\"anchor_index\": 0, \"description\": \"...\"}]\n"
    "2. 数组元素与锚点一一对应，anchor_index 必须等于锚点序号\n"
    "3. 禁止输出时间码（时间由系统换算）\n"
    "4. 禁止识别画面内字幕文字（字幕由语音转写提供）\n"
    "5. 用简洁的中文段落描述"
)
```

3.2 新增三个方法（放在 `_invoke_vision` 之后）：

```python
    def _invoke_vision_batch(self, image_data_uris: list[str], prompt: str) -> str:
        """多图批喂视觉模型（独立方法便于测试替换）。"""
        return invoke_vision_model_multi(image_data_uris, prompt)

    def _build_batch_prompt(self, scenario: str, batch: list[TimelineAnchor]) -> str:
        """构造一批锚点的提示词正文（锚点列表 + 帧序号对应关系）。"""
        parts = [_TIMELINE_PROMPT, ""]
        cursor = 0
        for index, anchor in enumerate(batch):
            count = len(anchor.frames)
            frame_range = f"帧号 {cursor}~{cursor + count - 1}" if count else "无对应画面帧"
            if scenario == "B":
                if count:
                    parts.append(
                        f"锚点 {index}：台词「{anchor.anchor_text}」"
                        f"（时间 {anchor.start_sec:.2f}-{anchor.end_sec:.2f}s），对应{frame_range}"
                    )
                else:
                    parts.append(
                        f"锚点 {index}：台词「{anchor.anchor_text}」"
                        f"（时间 {anchor.start_sec:.2f}-{anchor.end_sec:.2f}s），无对应画面帧，仅按台词上下文描述"
                    )
            else:
                parts.append(
                    f"锚点 {index}：时间片 {anchor.start_sec:.2f}-{anchor.end_sec:.2f}s，对应{frame_range}"
                )
            cursor += count
        return "\n".join(parts)
```

3.3 新增批处理与降级方法（放在 `_persist_frame` 之后）：

```python
    def _process_timeline_batch(
        self, batch: list[TimelineAnchor], scenario: str, *, account_id, document_id
    ) -> list[MediaSegment]:
        """处理一批锚点：留存代表帧 → 批喂视觉 → 解析 → 投影落库。

        失败链：批喂/解析失败 → 重试 1 次 → 仍失败 → 降级为该批内逐帧独立调用
        （等价改造前逐帧路径，保证最坏情况仍产出片段）。
        """
        batch_frames: list[ExtractedFrame] = []
        for anchor in batch:
            batch_frames.extend(anchor.frames)

        label = getattr(next((f for a in batch for f in a.frames), None), "path", "?")

        frame_urls: dict[int, str] = {}
        for index, frame in enumerate(batch_frames):
            frame_url = ""
            if account_id is not None and document_id is not None:
                try:
                    frame_url = self._persist_frame(
                        frame.path, account_id=account_id, document_id=document_id
                    ).key or ""
                except Exception:
                    logger.warning(
                        "关键帧留存失败 file=%s frame_index=%s，降级为空 frame_url",
                        label, index, exc_info=True,
                    )
                    frame_url = ""
            frame_urls[index] = frame_url

        data_uris = [path_to_data_uri(frame.path) for frame in batch_frames]
        prompt = self._build_batch_prompt(scenario, batch)

        descriptions: list[tuple[int, str]] = []
        try:
            descriptions = parse_timeline_descriptions(
                self._invoke_vision_batch(data_uris, prompt), len(batch)
            )
        except Exception:
            logger.warning("时间线批喂失败，重试一次 file=%s", label, exc_info=True)
            try:
                descriptions = parse_timeline_descriptions(
                    self._invoke_vision_batch(data_uris, prompt), len(batch)
                )
            except Exception:
                logger.warning("时间线批喂重试仍失败，降级逐帧 file=%s", label, exc_info=True)
                return self._fallback_frame_segments(
                    batch, frame_urls, account_id=account_id, document_id=document_id
                )

        description_map = dict(descriptions)
        segments: list[MediaSegment] = []
        cursor = 0
        for anchor_index, anchor in enumerate(batch):
            rep = anchor_representative_frame(anchor)
            rep_url = ""
            if rep is not None:
                rep_url = frame_urls.get(cursor + anchor.frames.index(rep), "")
            cursor += len(anchor.frames)

            description = description_map.get(anchor_index)
            if scenario == "B" and not description and anchor.speech_text:
                # 场景 B：模型未给描述也保留仅台词段落（可检索）
                description = anchor.speech_text
            if not description:
                # 场景 A 空描述跳过；场景 B 无台词又无描述则跳过
                continue

            metadata: dict[str, Any] = {
                "media_type": DocumentMediaType.VIDEO.value,
                "source": "vision_timeline",
                "anchor_type": anchor.anchor_type,
                "anchor_text": anchor.anchor_text,
                "start_sec": float(anchor.start_sec),
                "end_sec": float(anchor.end_sec),
                "frame_url": rep_url,
            }
            if anchor.speech_text:
                metadata["speech_text"] = anchor.speech_text
            segments.append(MediaSegment(content=description, metadata=metadata))
        return segments

    def _fallback_frame_segments(
        self, batch: list[TimelineAnchor], frame_urls: dict[int, str], *, account_id, document_id
    ) -> list[MediaSegment]:
        """降级：对该批内帧逐帧独立调用，产出与改造前一致的逐帧片段。"""
        segments: list[MediaSegment] = []
        cursor = 0
        for anchor in batch:
            for rel, frame in enumerate(anchor.frames):
                frame_url = frame_urls.get(cursor + rel, "")
                try:
                    description = self._invoke_vision(
                        path_to_data_uri(frame.path), _VIDEO_FRAME_PROMPT
                    )
                except Exception:
                    logger.warning(
                        "降级逐帧视觉分析失败 frame_index=%s", cursor + rel, exc_info=True
                    )
                    continue
                if not str(description or "").strip():
                    continue
                segments.append(
                    MediaSegment(
                        content=description,
                        metadata={
                            "media_type": DocumentMediaType.VIDEO.value,
                            "scene_index": cursor + rel + 1,
                            "frame_url": frame_url,
                            "time_offset": float(frame.time_offset or 0.0),
                        },
                    )
                )
            cursor += len(anchor.frames)
        return segments
```

3.4 改写 `_extract_video` 的帧循环（L270-309）为批喂循环：

```python
            scenario, anchors = build_timeline_plan(cues, frames)
            if not anchors:
                raise RuntimeError("视频解析未产出任何可用内容")

            for batch in chunk_anchors(anchors):
                segments.extend(
                    self._process_timeline_batch(
                        batch, scenario, account_id=account_id, document_id=document_id
                    )
                )
```

> 保留其余部分：抽帧、`_transcribe_video_track`、`audio_transcript` 段、`if not segments: raise RuntimeError` 收尾均不变。删除原 L270-309 的逐帧循环（被 `_process_timeline_batch` 取代）。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_media_extractor_service.py -v`
Expected: PASS（既有 audio/image 用例 + 改写的 3 个视频用例 + 新增 6 个时间线用例全部通过）

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/knowledge_media_extractor_service.py api/test/internal/service/test_knowledge_media_extractor_service.py
git commit -m "feat(kb): L1 视频解析改为批次化时间线叙述（场景 B/A + 重试 + 逐帧降级）"
```

---

## Task 4: L2 窗口来源适配 start_sec/end_sec

**Files:**
- Modify: `api/internal/service/knowledge_indexing_service.py:527-543`
- Test: `api/test/internal/service/test_knowledge_indexing_service.py`

- [ ] **Step 1: 写失败的测试**

在 `api/test/internal/service/test_knowledge_indexing_service.py` 追加：

```python
def test_segment_frame_falls_back_to_window_midpoint_for_timeline_segment():
    """时间线段（无 time_offset）应回退 (start_sec+end_sec)/2 作为定位坐标。"""
    from types import SimpleNamespace

    from internal.service.knowledge_indexing_service import KnowledgeIndexingService

    segment = SimpleNamespace(
        metadata_={
            "media_type": "video",
            "frame_url": "key-frame-1.jpg",
            "source": "vision_timeline",
            "start_sec": 3.2,
            "end_sec": 8.7,
        }
    )

    frame = KnowledgeIndexingService._segment_frame(segment)

    assert frame is not None
    assert frame["time_offset"] == pytest.approx(5.95)
    assert frame["frame_url"] == "key-frame-1.jpg"


def test_segment_frame_keeps_explicit_time_offset_when_present():
    """逐帧段仍读 time_offset，不受 start/end 影响。"""
    from types import SimpleNamespace

    from internal.service.knowledge_indexing_service import KnowledgeIndexingService

    segment = SimpleNamespace(
        metadata_={"media_type": "video", "frame_url": "k.jpg", "time_offset": 4.0}
    )

    frame = KnowledgeIndexingService._segment_frame(segment)

    assert frame["time_offset"] == 4.0
```

> 确认该测试文件顶部已 import `pytest`；若未 import，补 `import pytest`。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_indexing_service.py -k "segment_frame" -v`
Expected: FAIL — `frame["time_offset"] == 5.95` 处得到 `0.0`（当前实现 `metadata.get("time_offset") or 0.0`）

- [ ] **Step 3: 实现回退逻辑**

修改 `api/internal/service/knowledge_indexing_service.py` 的 `_segment_frame`（L527-543）：

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
        # 时间线段（source=vision_timeline）无逐帧 time_offset，用段落窗口中点
        # 作为定位坐标；普通逐帧段回退原 time_offset。
        time_offset = metadata.get("time_offset")
        if time_offset is None:
            start = metadata.get("start_sec")
            end = metadata.get("end_sec")
            time_offset = (float(start) + float(end)) / 2.0 if start is not None and end is not None else 0.0
        return {
            "segment_id": str(segment.id),
            "frame_url": frame_url,
            "scene_index": int(metadata.get("scene_index") or 0),
            "time_offset": float(time_offset or 0.0),
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_indexing_service.py -k "segment_frame" -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/knowledge_indexing_service.py api/test/internal/service/test_knowledge_indexing_service.py
git commit -m "feat(kb): L2 窗口来源适配时间线段 start_sec/end_sec 回退"
```

---

## Task 5: 全量单测回归

- [ ] **Step 1: 跑全量测试**

Run: `cd api && python -m pytest -q`
Expected: PASS（既有全部用例 + 本计划新增用例；若出现与本计划无关的失败，先确认是否为他人未提交改动导致，不擅自修复他人代码）

- [ ] **Step 2: Commit（如有未提交的测试修正）**

```bash
git add -u api/
git commit -m "test(kb): 时间线改造后单测回归修正"
```

---

## Task 6: 真机集成验证（场景 B / 场景 A）

**前置**：`vision_analyze` 已绑定 GLM-5.3-Flash；需真实 ffmpeg + 真实模型调用（耗时约 1-2 分钟/视频）。

- [ ] **Step 1: 场景 B 验证（stodownload.mp4）**

用 Glob 定位仓库中 stodownload.mp4 的绝对路径，跑以下脚本（真实 ffmpeg 抽帧 + 真实 ASR + 真实多图批喂；仅 COS 持久化用 account_id=None 跳过，不影响核心契约断言）：

```bash
cd api && python - <<'PY'
import os, tempfile
import internal.core.vision.vision_invoke as vi
from internal.core.vision.timeline_planning import build_timeline_plan, chunk_anchors
from internal.core.vision.vision_invoke import extract_video_frames_with_offsets
from app.http.module import injector
from internal.service.knowledge_media_extractor_service import KnowledgeMediaExtractorService

VIDEO = r"<stodownload.mp4 绝对路径>"   # 用 Glob 定位后替换

service = injector.get(KnowledgeMediaExtractorService)
with tempfile.TemporaryDirectory() as td:
    frames = extract_video_frames_with_offsets(VIDEO, os.path.join(td, "frames"))
    wav = service._extract_audio_track(VIDEO)
    try:
        transcript, cues = service._transcribe_audio_file(wav)
    finally:
        os.remove(wav)
    print("frames:", len(frames), "cues:", len(cues))

    calls = {"n": 0}
    orig = vi.invoke_vision_model_multi
    def counted(uris, prompt):
        calls["n"] += 1
        return orig(uris, prompt)
    service._invoke_vision_batch = lambda uris, prompt: counted(uris, prompt)  # type: ignore[assignment]

    scenario, anchors = build_timeline_plan(cues, frames)
    segments = []
    for batch in chunk_anchors(anchors):
        segments.extend(
            service._process_timeline_batch(batch, scenario, account_id=None, document_id=None)
        )

    print("scenario:", scenario, "vision calls:", calls["n"])
    timeline = [s for s in segments if s.metadata.get("source") == "vision_timeline"]
    print("timeline segments:", len(timeline))
    for s in timeline:
        m = s.metadata
        print(
            round(m.get("start_sec", 0), 2), round(m.get("end_sec", 0), 2),
            (m.get("speech_text") or "")[:18], "|", s.content[:24],
        )
PY
```

Expected:
- `vision calls == 2`（15 帧 → 场景 B 锚点数按 cues 计，每批 10 锚点 → 2 批）；
- 每条 timeline 段的 `start_sec/end_sec` 与 ASR cues 一致、`speech_text` 非空、`content` 非空；
- 无报错（`_process_timeline_batch` 内部 parse 成功，无降级触发）。

- [ ] **Step 2: 场景 A 验证（构造无音轨视频）**

```bash
ffmpeg -y -f lavfi -i testsrc=duration=30:size=640x360:rate=10 -an -pix_fmt yuv420p /tmp/silent.mp4
cd api && python - <<'PY'
# 与 Step 1 脚本相同，仅替换 VIDEO 为 /tmp/silent.mp4
PY
```

Expected:
- `scenario == "A"`：`anchor_type == "time_slot"`、`speech_text` 为空、`start_sec/end_sec` 来自分块；
- 视觉调用次数 = ceil(锚点数/10)（锚点数 = 块数，由 `resolve_l1_frame_count(30)` 帧数按块大小 10、重叠 1 推导）；

- [ ] **Step 3: 跑既有知识库相关全量回归**

Run: `cd api && python -m pytest test/internal/service test/internal/core/vision test/internal/task -q`
Expected: PASS

- [ ] **Step 4: Commit（如无产物改动可跳过）**

---

## Task 7: 文档同步 + 接线审查

- [ ] **Step 1: 更新 `docs/prd/modules/02-knowledge-base.md`**

定位 L1 视频解析小节，改写为：
- L1 视频 = 音轨 ASR（`source=audio_transcript`）+ **批次化时间线叙述**（`source=vision_timeline`，替换逐帧描述）；
- 时间线段落结构：`anchor_type=speech_sentence|time_slot`、`start_sec/end_sec`（服务端投影）、`speech_text`（ASR 注入）、`frame_url`（段落代表帧）；
- 帧留存：主路径只留存段落代表帧（每锚点 1 帧）；批喂失败重试 1 次 → 降级逐帧；
- L2 窗口来源：优先段落窗口，`_segment_frame` 回退 `(start_sec+end_sec)/2`。

- [ ] **Step 2: 更新 `docs/prd/execution-roadmap.md`** 中 KB-P4.5 状态为已完成（完成后）。

- [ ] **Step 3: 接线自检（AGENTS.md 强制）**

逐一核对：

| 检查项 | 结果 |
| --- | --- |
| 时间线条目入口 | `extract()` → `_extract_video` → `_process_timeline_batch` → `MediaSegment` → 既有「段落 → 索引」链路 |
| 批喂调用入口 | `_invoke_vision_batch`（唯一）→ `invoke_vision_model_multi`（唯一） |
| 降级路径可达 | `_fallback_frame_segments` 由重试仍失败的 catch 分支调用 |
| L2 窗口来源 | `_segment_frame` 读 `start_sec/end_sec` 回退，`_enhance_l2` 无需改动；触发入口 `POST /space/knowledge-bases/<kb_id>/documents/<document_id>/l2`（既有） |
| 无调用方的新符号 | 无（纯函数调用方均为 `_extract_video`） |

- [ ] **Step 4: 更新知识图谱**

```bash
python -m graphify update .
```

- [ ] **Step 5: Commit**

```bash
git add docs/prd/modules/02-knowledge-base.md docs/prd/execution-roadmap.md
git commit -m "docs(kb): 02-knowledge-base L1 时间线叙述 + roadmap KB-P4.5 状态"
```

---

## 衔接 KB-P4（本计划交付后继续，不在本计划内实现）

时间线段落结构（`anchor_type` / `anchor_text` / `start_sec` / `end_sec` / `speech_text`）即 **KB-P4 的编辑挂载点**：特效 / 贴纸 / 转场 / 字幕未来都挂载在段落上随段移动。本计划只产出段落结构，不实现元素绑定。

**衔接入口**（测试全部通过后）：
1. 读 P4 spec：[2026-09-16-video-production-p4-design.md](../superpowers-specs/2026-09-16-video-production-p4-design.md)；
2. 按既有 P4 计划执行：[2026-09-19-kb-p4-video-edit.md](./2026-09-19-kb-p4-video-edit.md)（trim / concat / subtitle 三件套 + HyperFrames 渲染，不引入 Hypit）；
3. P4 计划中的「字幕自动对齐」已由既有 `transcript_segments` 承载；本次新增的 `speech_text` 段落进一步为「按台词定位出片区间」提供锚点。

**验收口径**：真机测试通过（调用次数 = N/块、时间码与 ASR 一致、条目含完整 start/end/speech_text）+ 全量回归绿，即为本计划完成，可进入 KB-P4。
