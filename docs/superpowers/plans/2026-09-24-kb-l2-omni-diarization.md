# 知识库多模态 L2 补齐（说话人切分 / 场景切分 / OCR 坐标）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Qwen-Omni（`qwen3.8-omni-flash`）补齐 `docs/prd/modules/02-knowledge-base.md` 中明确登记为「未实现」的三项能力：音频**说话人切分**、视频**场景切分**、图片**细粒度 OCR 区块坐标**。

**Architecture:** 新增一条**直连 DashScope 兼容模式**的 Omni 调用层（`api/internal/core/vision/omni_invoke.py`），与既有 `vision_invoke.py`（视觉模型调用 + 抽帧）职责并列、互不耦合。说话人切分在 **L1 解析期**落地（cues 补 `speaker`，直接惠及字幕与时间线锚点）；场景切分在 **L2 按需解析期**落地（新增 `tier2_scene` 片段，不改变 L1 既有锚点语义）；OCR 坐标复用既有 `vision_analyze` 视觉模型（不新增 feature_key）。

**Tech Stack:** Python 3.12、`requests`（SSE 流式）、ffmpeg（16k 单声道 MP3 编码）、SQLAlchemy、Celery、pytest。

**依据调研：**
- 插件仓库：<https://github.com/QwenLM/Qwen-MM-Plugins>（Apache-2.0）
- Omni 协议与工具实现（本计划借鉴其 prompt 与媒体准备策略）：`src/shared/api_omni.py`、`src/shared/omni_media.py`、`src/capabilities/api/qwen_mm_plugins_api/omni/omni_multi_speaker_asr.py`、`src/capabilities/api/qwen_mm_plugins_api/omni/omni_av_caption.py`
- 能力现状登记：`docs/prd/modules/02-knowledge-base.md` §「资料内容库需要支持」与 §11.11 档位表

---

## 范围说明

本计划是**两份计划中的第二份**，只做知识库解析链路，**不碰对话内 MCP 通道**：

| 计划 | 内容 | 状态 |
| --- | --- | --- |
| [计划 A](./2026-09-24-qwen-mm-plugins-assistant-omni.md) | 对话内多说话人转写（MCP stdio 通道） | 另见该计划 |
| **本计划（B）** | 知识库 L1/L2 补齐（直连 API + Celery） | 本次实施 |

**为什么 B 不走 MCP**：知识库入库是 Celery 批处理长任务，而 MCP stdio 是短连接（每次调用重新 spawn 子进程、默认 30s 超时、无并发控制）。用 MCP 做批量入库会在并发与长音频上直接崩掉。B 复用插件的**协议细节与 prompt**，但调用路径自建。

**明确不做（YAGNI）：**
- 不做音频「章节切分」（本次只做说话人切分；章节切分需另一套语义切分策略，无明确产品需求）
- 不改动 L1 既有时间线锚点算法（`build_timeline_plan`）——场景切分以**新增** L2 片段形式落地，避免破坏既有检索语义与测试
- 不接入 SAM3 分割、不做 3D 空间推理（无产品场景）
- 不把 Omni 用于图片理解（图片走既有 `vision_analyze`，Omni 的价值在音视频联合）

---

## 已核实的事实（写代码前先读，避免重复踩坑）

| 事实 | 位置 / 证据 |
| --- | --- |
| Omni 调用有**硬协议约束** | 插件 `shared/api_omni.py` 模块头明写：Omni「**must** be called with `stream=True` + `modalities=["text"]` (+ `stream_options.include_usage`)」，与普通 VL 路径不同。照普通 chat 调用会失败 |
| 音频 part 的准确形状 | `shared/api_omni.py::omni_audio_part`：`{"type":"input_audio","input_audio":{"data":"data:;base64,…","format":"<suffix>"}}`；DashScope 形态是 `data:;base64,` 前缀（**省略 mime**），类型由 `format` 字段承载 |
| 单条内联媒体上限 10MB（base64 后） | 插件 `OMNI_MAX_B64_BYTES = 10 MB`；`omni_multi_speaker_asr` 文档注明「local file travels inline… the endpoint caps a media item at 10 MB of base64, so the audio is downmixed to 16 kHz mono and MP3-compressed at a duration-fitted bitrate when needed — good for roughly 55 min」 |
| 说话人切分的返回结构 | `omni_multi_speaker_asr`：`{"speakers":[...], "segments":[{"speaker","start","end","text"}]}`，另附带 speaker 标签的 SRT |
| 说话人切分的 prompt 要点 | 同文件 `_PROMPT`：要求「assign each segment to a consistent speaker label… give an accurate start and end time in seconds」+「Output STRICTLY this JSON and nothing else」，并用 `num_speakers` 作为 hint |
| 场景切分可一次调用拿到边界 | `omni_av_caption` 的 prompt 要求按 `<xx:xx.xxx> - <xx:xx.xxx>` 输出带时间戳的 Storyline 段——证明 Omni 能给出**时间轴分段**；本计划用更窄的专用 prompt 直接要边界数组 |
| 本系统音频 cue 结构 | `knowledge_media_extractor_service.py::_call_asr_with_segments` → `(text, cues)`，cue 形如 `{"text","start","end"}`（秒）；`parse_subtitle_cues_from_text` 产出同构 cues |
| cues 是「自动加字幕」的唯一时间码来源 | `_extract_audio` 注释与 `video_edit_service._load_stored_cues`：字幕生成复用 `metadata.transcript_segments`，**重跑 ASR 既慢又可能不一致** |
| L2 目前只处理视频 | `knowledge_indexing_service._enhance_l2`：`if media_type != VIDEO: return {"media_type": ..., "window_frames": 0}` |
| L2 窗口片段有既定清理与标记模式 | 同文件：`tier2_window=True` 标记 + `_clear_previous_l2_windows` 清理（不清理会累积重复片段 + 帧配额泄漏）。新增的 scene 片段必须照此模式实现自己的清理 |
| L2 触发入口 | 路由 `POST /space/knowledge-bases/<kb_id>/documents/<document_id>/l2` → `KnowledgeBaseService.trigger_document_l2` → `_dispatch_document_l2`；Celery 任务 `internal.task.knowledge_l2_tasks.build_document_l2_task`（**无 beat 条目**，按需触发） |
| 视觉模型调用入口 | `vision_invoke.py::invoke_vision_model(data_uri, prompt)` → `LanguageModelService.get_feature_model("vision_analyze")`，走 OpenAI 兼容 `image_url` 多模态消息 |
| 视觉 feature 已注册 | `public_ai_feature_service._BUILTIN_FEATURES` 中 `vision_analyze`（category `assistant`、model_type `chat`、fallback_tier `2`、billable True）——**OCR 坐标复用它，不新增 feature_key** |
| 非 Chat 类凭证获取方式 | `LanguageModelService.get_feature_credentials(feature_key)` → `{"api_key","base_url","model","provider"}`（先例：`icon_generator_service` 用它取 `icon_image_generation` 凭证后直接 `requests.post`） |
| 音频抽取已有公共入口 | `vision_invoke.py::extract_video_audio(video_path, target_path)` → 16k 单声道 WAV（ASR 友好）；本计划需在其基础上再加一层 MP3 编码 |
| 服务依赖注入要求 | `KnowledgeMediaExtractorService` 的依赖字段**必须带具体类型注解**（injector 按注解解析，写 `Any` 会静默注入失败——见项目记忆与 `test_external_data_source_service.py` 先例） |
| 可替换方法约定 | 服务内外部 IO 一律抽成 `_invoke_xxx` / `_extract_xxx` 独立方法，便于单测替换（既有 `_invoke_vision` / `_extract_frames_with_offsets` / `_call_asr_with_segments` 均如此） |

---

## 文件结构

| 文件 | 职责 | 动作 |
| --- | --- | --- |
| `api/internal/service/public_ai_feature_service.py` | 注册新 feature_key `media_omni_analyze` | 修改 |
| `api/internal/core/vision/omni_invoke.py` | Omni 调用层：音频编码预算（纯函数）、16k 单声道 MP3 编码、SSE 流式调用、说话人分段解析、场景边界解析 | 新建 |
| `api/internal/core/vision/scene_planning.py` | 场景边界 → 场景区间（纯函数：去噪、最小场景时长、合并过短场景、补齐首尾） | 新建 |
| `api/internal/core/vision/vision_invoke.py` | 新增 OCR 区块 prompt 常量与 `parse_ocr_blocks()`（纯函数） | 修改 |
| `api/internal/service/knowledge_media_extractor_service.py` | `_extract_audio` 补说话人标签；`_extract_video` 的 cues 补说话人标签；`_extract_image` 补 OCR 区块坐标 | 修改 |
| `api/internal/service/knowledge_indexing_service.py` | `_enhance_l2` 新增视频场景切分分支；新增 `_enhance_l2_scenes` / `_clear_previous_l2_scenes` | 修改 |
| `api/test/internal/core/vision/test_omni_invoke.py` | Omni 编码预算与解析纯函数测试 | 新建 |
| `api/test/internal/core/vision/test_scene_planning.py` | 场景区间规划纯函数测试 | 新建 |
| `api/test/internal/service/test_knowledge_media_extractor_service.py` | 扩展：说话人标签、OCR 区块测试 | 修改 |
| `api/test/internal/service/test_knowledge_indexing_l2_scenes.py` | L2 场景切分测试 | 新建 |
| `docs/prd/modules/02-knowledge-base.md` | 更新三项「未实现」登记为已落地 | 修改 |

---

## Task 1: 注册 Omni feature_key

**Files:**
- Modify: `api/internal/service/public_ai_feature_service.py`
- Test: `api/test/internal/service/test_public_ai_feature_omni.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/test_public_ai_feature_omni.py`：

```python
"""media_omni_analyze feature_key 注册测试。

Omni 是独立模型家族（需 stream + modalities 协议），凭证与 VL 模型不同，
必须有自己的 feature_key，才能在 /admin/public-ai-features 绑定模型。
"""
from internal.service.public_ai_feature_service import _BUILTIN_FEATURES


def _feature(feature_key: str) -> dict:
    for feat in _BUILTIN_FEATURES:
        if feat["feature_key"] == feature_key:
            return feat
    raise AssertionError(f"未注册 feature_key: {feature_key}")


def test_media_omni_analyze_is_registered():
    feat = _feature("media_omni_analyze")
    assert feat["feature_name"] == "音视频联合理解（说话人切分/场景切分）"
    assert feat["feature_category"] == "assistant"
    assert feat["model_type"] == "chat"
    assert feat["fallback_tier"] == "2"
    assert feat["billable"] is True


def test_vision_analyze_still_registered_for_ocr_blocks():
    """OCR 区块坐标复用既有视觉 feature，不得因本计划被改动。"""
    assert _feature("vision_analyze")["fallback_tier"] == "2"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
docker exec llmops-api pytest test/internal/service/test_public_ai_feature_omni.py -v
```

Expected：FAIL —— `AssertionError: 未注册 feature_key: media_omni_analyze`。

- [ ] **Step 3: 注册 feature_key**

在 `api/internal/service/public_ai_feature_service.py` 的 `_BUILTIN_FEATURES` 列表末尾（`vision_analyze` 之后）追加：

```python
    {
        "feature_key": "media_omni_analyze",
        "feature_name": "音视频联合理解（说话人切分/场景切分）",
        "feature_category": "assistant",
        "feature_description": "Qwen-Omni 音视频联合理解：音频多说话人切分（说话人标签+时间戳）、视频场景边界切分",
        "model_type": "chat",   # Omni 走 OpenAI 兼容 chat 接口（需 stream + modalities 协议）
        "fallback_tier": "2",   # 标准型 Flash 级即可（qwen3.8-omni-flash 即属此档）
        "billable": True,       # 用户素材解析触发，按用量计费
    },
```

- [ ] **Step 4: 运行测试确认通过**

```bash
docker exec llmops-api pytest test/internal/service/test_public_ai_feature_omni.py -v
```

Expected：2 passed。

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/public_ai_feature_service.py api/test/internal/service/test_public_ai_feature_omni.py
git commit -m "feat(kb): 注册 media_omni_analyze 公共 AI feature_key"
```

---

## Task 2: Omni 音频编码预算（纯函数）

**Files:**
- Create: `api/internal/core/vision/omni_invoke.py`
- Test: `api/test/internal/core/vision/test_omni_invoke.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/core/vision/test_omni_invoke.py`：

```python
"""Omni 调用层纯函数测试（无网络、无 ffmpeg）。"""
import pytest

from internal.core.vision.omni_invoke import (
    OMNI_MAX_B64_BYTES,
    resolve_mp3_bitrate_kbps,
    resolve_raw_audio_budget_bytes,
)


def test_raw_budget_is_base64_decoded_size():
    """base64 膨胀 4/3，故原始字节预算 = 上限 * 3 / 4。"""
    assert resolve_raw_audio_budget_bytes() == OMNI_MAX_B64_BYTES * 3 // 4


def test_bitrate_falls_with_longer_duration():
    short = resolve_mp3_bitrate_kbps(60.0)
    long = resolve_mp3_bitrate_kbps(3600.0)
    assert short > long


def test_bitrate_is_clamped_to_audio_sane_range():
    # 极短音频不得给出荒谬高码率
    assert resolve_mp3_bitrate_kbps(0.5) <= 128
    # 极长音频不得低于可听下限（否则说话人特征丢失、切分质量崩坏）
    assert resolve_mp3_bitrate_kbps(100000.0) >= 32


def test_bitrate_handles_non_positive_duration():
    """时长不可得时回退到上限码率，而不是抛错或返回 0。"""
    assert resolve_mp3_bitrate_kbps(0.0) == 128
    assert resolve_mp3_bitrate_kbps(-5.0) == 128


@pytest.mark.parametrize("duration", [30.0, 600.0, 3300.0])
def test_chosen_bitrate_fits_budget(duration):
    """所选码率必须真的能把该时长压进预算内。"""
    kbps = resolve_mp3_bitrate_kbps(duration)
    projected_bytes = kbps * 1000 / 8 * duration
    assert projected_bytes <= resolve_raw_audio_budget_bytes()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
docker exec llmops-api pytest test/internal/core/vision/test_omni_invoke.py -v
```

Expected：FAIL —— `ModuleNotFoundError: No module named 'internal.core.vision.omni_invoke'`。

- [ ] **Step 3: 创建模块并实现两个纯函数**

新建 `api/internal/core/vision/omni_invoke.py`：

```python
"""Qwen-Omni 音视频联合理解调用层。

与 ``vision_invoke.py`` 的分工：
- ``vision_invoke`` 负责「视觉」——图片/视频帧的 VL 模型调用与 ffmpeg 抽帧；
- 本模块负责「音视频联合」——音频多说话人切分、视频场景边界切分。

两者共用上游 provider 体系，但**协议不同**：Omni 必须走
``stream=True`` + ``modalities=["text"]`` + ``stream_options.include_usage``
（普通 chat 调用会失败），故单独成层、不塞进 vision_invoke。

内联媒体上限对齐插件实现：单条 base64 后不得超过 10MB。本地音频按
16kHz 单声道 MP3 编码，码率按时长反推——这是「约 55 分钟音频可内联」的原因。
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 单条内联媒体的 base64 上限，与 Qwen-MM-Plugins 的 OMNI_MAX_B64_BYTES 对齐。
OMNI_MAX_B64_BYTES = 10 * 1024 * 1024

# MP3 码率上下限（kbps）：低于 32k 说话人音色特征丢失、切分质量崩坏；
# 高于 128k 对语音无增益，只浪费预算。
_MIN_MP3_KBPS = 32
_MAX_MP3_KBPS = 128


def resolve_raw_audio_budget_bytes() -> int:
    """可用的原始音频字节预算（base64 前的字节数）。

    base64 编码后体积约为原始的 4/3，故原始预算 = 上限 * 3 / 4。
    """
    return OMNI_MAX_B64_BYTES * 3 // 4


def resolve_mp3_bitrate_kbps(duration_sec: float, budget_bytes: int | None = None) -> int:
    """按时长反推能把音频压进预算的 MP3 码率（kbps）。

    时长不可得（<=0）时回退上限码率：宁可让调用方在编码后自己判断体积，
    也不要返回 0 或抛错——0 会让 ffmpeg 编码出空文件，是更难排查的静默失败。
    """
    budget = resolve_raw_audio_budget_bytes() if budget_bytes is None else int(budget_bytes)
    if duration_sec <= 0:
        return _MAX_MP3_KBPS
    # 预算(字节) * 8 / 时长(秒) / 1000 => kbps
    raw_kbps = budget * 8 / duration_sec / 1000
    return max(_MIN_MP3_KBPS, min(_MAX_MP3_KBPS, int(raw_kbps)))
```

- [ ] **Step 4: 运行测试确认通过**

```bash
docker exec llmops-api pytest test/internal/core/vision/test_omni_invoke.py -v
```

Expected：7 passed。

- [ ] **Step 5: 提交**

```bash
git add api/internal/core/vision/omni_invoke.py api/test/internal/core/vision/test_omni_invoke.py
git commit -m "feat(kb): 新增 Omni 调用层与音频编码预算纯函数"
```

---

## Task 3: Omni 流式调用与结果解析

**Files:**
- Modify: `api/internal/core/vision/omni_invoke.py`
- Test: `api/test/internal/core/vision/test_omni_invoke.py`

- [ ] **Step 1: 追加失败测试**

在 `api/test/internal/core/vision/test_omni_invoke.py` 末尾追加：

```python
# ---------------------------------------------------------------- 解析纯函数

from internal.core.vision.omni_invoke import (
    build_diarization_prompt,
    parse_diarization_segments,
    parse_scene_boundaries,
)


def test_diarization_prompt_includes_speaker_hint_and_json_contract():
    prompt = build_diarization_prompt(num_speakers=2, language="zh")
    assert "2" in prompt
    assert "zh" in prompt
    # 必须锁定 JSON 契约，否则模型会输出自然语言导致解析失败
    assert '"segments"' in prompt and '"speaker"' in prompt


def test_parse_diarization_segments_strips_code_fence():
    text = '```json\n{"segments":[{"speaker":"Speaker 1","start":0,"end":2.5,"text":"你好"}]}\n```'
    segments = parse_diarization_segments(text)
    assert segments == [{"speaker": "Speaker 1", "start": 0.0, "end": 2.5, "text": "你好"}]


def test_parse_diarization_segments_accepts_bare_array():
    text = '[{"speaker":"A","start":1,"end":3,"text":"hi"}]'
    assert parse_diarization_segments(text) == [
        {"speaker": "A", "start": 1.0, "end": 3.0, "text": "hi"}
    ]


def test_parse_diarization_segments_returns_empty_on_garbage():
    """解析失败必须返回空列表（调用方降级为纯文本），不得抛错中断解析链路。"""
    assert parse_diarization_segments("模型拒绝回答") == []
    assert parse_diarization_segments("") == []
    assert parse_diarization_segments('{"segments":[{"start":"x"}]}') == []


def test_parse_diarization_segments_skips_entries_without_text():
    text = '{"segments":[{"speaker":"A","start":0,"end":1,"text":""},{"speaker":"B","start":1,"end":2,"text":"ok"}]}'
    assert [s["speaker"] for s in parse_diarization_segments(text)] == ["B"]


def test_parse_scene_boundaries_returns_sorted_unique_floats():
    text = '{"boundaries":[12, 0, 30.5, 12]}'
    assert parse_scene_boundaries(text) == [0.0, 12.0, 30.5]


def test_parse_scene_boundaries_returns_empty_on_garbage():
    assert parse_scene_boundaries("no json here") == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
docker exec llmops-api pytest test/internal/core/vision/test_omni_invoke.py -v
```

Expected：FAIL —— `ImportError: cannot import name 'build_diarization_prompt'`。

- [ ] **Step 3: 实现 prompt 构造与解析**

在 `api/internal/core/vision/omni_invoke.py` 追加：

```python
# ---------------------------------------------------------------- prompt 构造

_DIARIZATION_PROMPT = (
    "请转写这段媒体中的全部语音，并做说话人区分：为每个语音段分配一个"
    '一致的说话人标签（如 "Speaker 1"、"Speaker 2"），并给出准确的开始与结束时间（秒）。'
    "{speakers}{lang}"
    "严格只输出如下 JSON，不要输出任何其他内容："
    '{{\"segments\": [{{\"speaker\": \"<标签>\", \"start\": <秒>, \"end\": <秒>, \"text\": \"<文本>\"}}]}}'
)

_SCENE_PROMPT = (
    "请识别这段视频的场景切换点（画面主体/场景/镜头发生明显变化的时刻）。"
    "严格只输出如下 JSON，不要输出任何其他内容："
    '{\"boundaries\": [<切换时刻秒数>, ...]}'
    "要求：升序、去重、不包含 0 与视频总时长；场景变化不明显时返回空数组。"
)


def build_diarization_prompt(num_speakers: int | None = None, language: str = "") -> str:
    """构造说话人切分提示词。

    与 Qwen-MM-Plugins 的 prompt 同构：显式给出说话人数 hint（已知时显著提升
    标签一致性），并锁定 JSON 契约（不锁死则模型会输出自然语言，解析必失败）。
    """
    speakers = f" 已知共有 {int(num_speakers)} 位说话人。" if num_speakers else ""
    lang = f" 语音语言是 {language}。" if language else ""
    return _DIARIZATION_PROMPT.format(speakers=speakers, lang=lang)


def build_scene_prompt() -> str:
    """构造场景边界识别提示词。"""
    return _SCENE_PROMPT


def _extract_json_payload(text: str) -> Any:
    """从模型输出中抽出 JSON（容忍 ```json 围栏与前后杂讯）。"""
    normalized = str(text or "").strip()
    if not normalized:
        return None
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)```", normalized, re.DOTALL)
    candidate = fenced.group(1).strip() if fenced else normalized
    try:
        return json.loads(candidate)
    except (TypeError, ValueError):
        pass
    # 退化路径：截取首个 { 或 [ 到最后一个 } 或 ]
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = candidate.find(opener), candidate.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except (TypeError, ValueError):
                continue
    return None


def _coerce_seconds(value: Any) -> float | None:
    """把模型给的时间值转为秒；不可解析时返回 None（由调用方丢弃该条）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_diarization_segments(text: str) -> list[dict[str, Any]]:
    """解析说话人分段；任何解析失败都返回空列表。

    契约：返回 ``[{"speaker","start","end","text"}]``，start/end 为秒。
    无 text 或缺时间戳的条目直接丢弃——它们无法映射为可检索片段，
    保留只会产生空片段污染检索结果。
    """
    payload = _extract_json_payload(text)
    if isinstance(payload, dict):
        raw_segments = payload.get("segments") or payload.get("results") or []
    elif isinstance(payload, list):
        raw_segments = payload
    else:
        return []

    segments: list[dict[str, Any]] = []
    for item in raw_segments if isinstance(raw_segments, list) else []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("text") or "").strip()
        start = _coerce_seconds(item.get("start"))
        end = _coerce_seconds(item.get("end"))
        if not content or start is None or end is None:
            continue
        segments.append({
            "speaker": str(item.get("speaker") or "Speaker 1").strip() or "Speaker 1",
            "start": start,
            "end": end,
            "text": content,
        })
    return segments


def parse_scene_boundaries(text: str) -> list[float]:
    """解析场景切换点；返回升序去重后的秒数列表，解析失败返回空列表。

    0 与负值一律剔除：0 不是「切换点」而是片头，保留会让第一个场景长度为零。
    """
    payload = _extract_json_payload(text)
    if isinstance(payload, dict):
        raw = payload.get("boundaries") or payload.get("scenes") or []
    elif isinstance(payload, list):
        raw = payload
    else:
        return []

    values: list[float] = []
    for item in raw if isinstance(raw, list) else []:
        seconds = _coerce_seconds(item)
        if seconds is None or seconds <= 0:
            continue
        values.append(seconds)
    return sorted(set(values))
```

- [ ] **Step 4: 运行测试确认通过**

```bash
docker exec llmops-api pytest test/internal/core/vision/test_omni_invoke.py -v
```

Expected：14 passed。

- [ ] **Step 5: 提交**

```bash
git add api/internal/core/vision/omni_invoke.py api/test/internal/core/vision/test_omni_invoke.py
git commit -m "feat(kb): Omni 说话人切分与场景边界 prompt 及解析"
```

---

## Task 4: Omni 实际调用与 MP3 编码

**Files:**
- Modify: `api/internal/core/vision/omni_invoke.py`
- Test: `api/test/internal/core/vision/test_omni_invoke.py`

- [ ] **Step 1: 追加失败测试**

在 `api/test/internal/core/vision/test_omni_invoke.py` 末尾追加：

```python
# ---------------------------------------------------------------- 流式调用

import json as _json

from internal.core.vision.omni_invoke import (
    build_omni_audio_part,
    iter_sse_text,
    resolve_omni_credentials,
)


def test_build_omni_audio_part_uses_dashscope_shape(tmp_path):
    """DashScope 形态：data:;base64, 前缀（省略 mime），类型由 format 承载。"""
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"\x00\x01\x02")
    part = build_omni_audio_part(str(audio), audio_format="mp3")
    assert part["type"] == "input_audio"
    assert part["input_audio"]["format"] == "mp3"
    assert part["input_audio"]["data"].startswith("data:;base64,")


def test_iter_sse_text_accumulates_deltas_and_stops_at_done():
    lines = [
        'data: {"choices":[{"delta":{"content":"你好"}}]}',
        "",
        'data: {"choices":[{"delta":{"content":"世界"}}]}',
        "",
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"不应被计入"}}]}',
    ]
    assert iter_sse_text(lines) == "你好世界"


def test_iter_sse_text_ignores_malformed_lines():
    lines = ["data: not-json", "", "data: {\"choices\":[{\"delta\":{\"content\":\"ok\"}}]}"]
    assert iter_sse_text(lines) == "ok"


def test_resolve_omni_credentials_returns_empty_without_binding(monkeypatch):
    """未绑定模型时返回空字典，调用方据此降级（不抛错）。"""
    monkeypatch.setattr(
        "internal.core.vision.omni_invoke._feature_credentials", lambda key: {}
    )
    assert resolve_omni_credentials() == {}


def test_resolve_omni_credentials_fills_default_model(monkeypatch):
    monkeypatch.setattr(
        "internal.core.vision.omni_invoke._feature_credentials",
        lambda key: {"api_key": "sk-x", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
    )
    creds = resolve_omni_credentials()
    assert creds["api_key"] == "sk-x"
    assert creds["model"] == "qwen3.8-omni-flash"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
docker exec llmops-api pytest test/internal/core/vision/test_omni_invoke.py -v
```

Expected：FAIL —— `ImportError: cannot import name 'build_omni_audio_part'`。

- [ ] **Step 3: 实现凭证解析、音频 part、SSE 累积与编码**

在 `api/internal/core/vision/omni_invoke.py` 追加（并在文件顶部 `import` 区补 `import os`、`import subprocess`、`import tempfile`、`import requests`）：

```python
# 未绑定模型时的兜底模型名：与 Qwen-MM-Plugins 的 DEFAULT_OMNI_MODEL 一致。
DEFAULT_OMNI_MODEL = "qwen3.8-omni-flash"
# Omni 流式调用超时（秒）：长音频联合理解会跑很久，不能用普通 chat 的超时。
DEFAULT_OMNI_TIMEOUT_SECONDS = 1800
# 16k 单声道是语音模型的标准输入（与 extract_video_audio 口径一致）。
_OMNI_SAMPLE_RATE = 16000


def _feature_credentials(feature_key: str) -> dict[str, str]:
    """读公共 AI 配置中该 feature 绑定的模型凭证（独立函数便于测试替换）。"""
    from internal.service.language_model_service import LanguageModelService

    return LanguageModelService.get_feature_credentials(feature_key) or {}


def resolve_omni_credentials(feature_key: str = "media_omni_analyze") -> dict[str, str]:
    """解析 Omni 调用凭证；未绑定模型时返回空字典（调用方降级）。

    不抛错：素材解析链路里 Omni 是**增强项**，未配置时应退回纯 ASR，
    而不是让整个素材解析失败。
    """
    creds = _feature_credentials(feature_key)
    if not creds or not creds.get("api_key"):
        return {}
    return {
        "api_key": str(creds.get("api_key") or ""),
        "base_url": str(creds.get("base_url") or "").rstrip("/"),
        "model": str(creds.get("model") or "").strip() or DEFAULT_OMNI_MODEL,
    }


def build_omni_audio_part(audio_path: str, audio_format: str = "mp3") -> dict[str, Any]:
    """构造 Omni 音频内容 part（DashScope 兼容模式形态）。

    形态为 ``data:;base64,<b64>``（**省略 mime**，类型由 ``format`` 字段承载）。
    注意与 OpenAI 官方规范不同（官方要裸 base64）——按官方形态发送会被
    DashScope 拒（Incorrect padding），这是插件里 ``QWEN_MM_AUDIO_RAW_B64``
    开关存在的原因。
    """
    with open(audio_path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    return {
        "type": "input_audio",
        "input_audio": {"data": f"data:;base64,{encoded}", "format": audio_format},
    }


def iter_sse_text(lines: Any) -> str:
    """累积 OpenAI 兼容 SSE 流中的文本增量，遇 ``[DONE]`` 停止。

    独立成纯函数（入参为可迭代行）以便单测覆盖解析逻辑，不依赖真实网络。
    """
    chunks: list[str] = []
    for raw_line in lines:
        if not raw_line:
            continue
        line = str(raw_line).strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            frame = json.loads(payload)
        except (TypeError, ValueError):
            continue
        for choice in frame.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") or {}
            content = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(content, str) and content:
                chunks.append(content)
    return "".join(chunks).strip()


def encode_audio_for_omni(source_path: str, out_path: str, *, duration_sec: float) -> str:
    """把音频/视频音轨转成 16k 单声道 MP3（码率按时长反推），返回 out_path。

    为什么必须转码：DashScope 单条内联媒体上限 10MB(base64)，而 16k 单声道
    WAV 约 32KB/s——1 小时就是 115MB，远超上限。MP3 按时长自适应码率后
    可内联约 55 分钟（与插件实测口径一致）。
    """
    from internal.core.vision.vision_invoke import _resolve_ffmpeg_exe  # noqa: PLC0415

    kbps = resolve_mp3_bitrate_kbps(duration_sec)
    cmd = [
        _resolve_ffmpeg_exe(), "-y", "-i", source_path,
        "-vn",                       # 丢弃视频流
        "-ac", "1",                  # 单声道
        "-ar", str(_OMNI_SAMPLE_RATE),
        "-b:a", f"{kbps}k",
        "-f", "mp3",
        out_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=600, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Omni 音频编码失败: {getattr(exc, 'stderr', b'')[:200]}") from exc
    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError("Omni 音频编码未产出有效文件")
    return out_path


def invoke_omni_audio(audio_path: str, prompt: str, *, audio_format: str = "mp3") -> str:
    """对音频调用 Omni 并返回文本结果。

    协议硬约束（照普通 chat 调用会失败）：``stream=True`` +
    ``modalities=["text"]`` + ``stream_options.include_usage``。
    未绑定模型时抛 RuntimeError，由调用方降级。
    """
    creds = resolve_omni_credentials()
    if not creds:
        raise RuntimeError("未配置 media_omni_analyze 模型，无法执行音视频联合理解")

    part = build_omni_audio_part(audio_path, audio_format=audio_format)
    body = {
        "model": creds["model"],
        "messages": [{"role": "user", "content": [part, {"type": "text", "text": prompt}]}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "modalities": ["text"],
    }
    response = requests.post(
        f"{creds['base_url']}/chat/completions",
        json=body,
        headers={
            "Authorization": f"Bearer {creds['api_key']}",
            "Content-Type": "application/json",
        },
        timeout=DEFAULT_OMNI_TIMEOUT_SECONDS,
        stream=True,
    )
    response.raise_for_status()
    return iter_sse_text(response.iter_lines(decode_unicode=True))
```

- [ ] **Step 4: 运行测试确认通过**

```bash
docker exec llmops-api pytest test/internal/core/vision/test_omni_invoke.py -v
```

Expected：19 passed。

- [ ] **Step 5: 提交**

```bash
git add api/internal/core/vision/omni_invoke.py api/test/internal/core/vision/test_omni_invoke.py
git commit -m "feat(kb): Omni 流式调用、SSE 累积与自适应码率音频编码"
```

---

## Task 5: L1 音频补说话人标签

**Files:**
- Modify: `api/internal/service/knowledge_media_extractor_service.py`
- Test: `api/test/internal/service/test_knowledge_media_extractor_service.py`

- [ ] **Step 1: 写失败测试**

在 `api/test/internal/service/test_knowledge_media_extractor_service.py` 末尾追加：

```python
# ------------------------------------------------------------ 说话人切分（L1 音频）

def test_audio_extraction_attaches_speaker_to_cues():
    """说话人切分成功后，cues 每条带 speaker，且 metadata 记录说话人清单。

    speaker 必须落到 cue 上而非只放 metadata：cues 是「自动加字幕」的唯一
    时间码来源，字幕要按句显示说话人，speaker 不在 cue 上就取不到。
    """
    audio_service = _FakeAudioService(
        text="你好。你好。",
        segments=[
            {"text": "你好。", "start": 0.0, "end": 1.5},
            {"text": "你好。", "start": 1.5, "end": 3.0},
        ],
    )
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"audio-bytes"),
        audio_service=audio_service,
    )
    service._invoke_diarization = lambda path: [
        {"speaker": "Speaker 1", "start": 0.0, "end": 1.5, "text": "你好。"},
        {"speaker": "Speaker 2", "start": 1.5, "end": 3.0, "text": "你好。"},
    ]

    segments = service.extract(_document("audio"), _upload_file("mp3"))

    cues = segments[0].metadata["transcript_segments"]
    assert [cue["speaker"] for cue in cues] == ["Speaker 1", "Speaker 2"]
    assert segments[0].metadata["speakers"] == ["Speaker 1", "Speaker 2"]


def test_audio_extraction_degrades_when_diarization_fails():
    """说话人切分失败必须降级为纯 ASR 结果，不得让素材解析失败。"""
    audio_service = _FakeAudioService(
        text="你好。",
        segments=[{"text": "你好。", "start": 0.0, "end": 1.5}],
    )
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"audio-bytes"),
        audio_service=audio_service,
    )

    def _boom(path):
        raise RuntimeError("omni unavailable")

    service._invoke_diarization = _boom

    segments = service.extract(_document("audio"), _upload_file("mp3"))

    cues = segments[0].metadata["transcript_segments"]
    assert "speaker" not in cues[0]
    assert "speakers" not in segments[0].metadata
    assert segments[0].content == "你好。"


def test_audio_extraction_skips_diarization_when_no_cues():
    """没有 ASR 时间轴时不该调 Omni：没有可对齐的锚点，纯属浪费一次调用。"""
    audio_service = _FakeAudioService(text="你好。", segments=[])
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"audio-bytes"),
        audio_service=audio_service,
    )
    called = []
    service._invoke_diarization = lambda path: called.append(path) or []

    service.extract(_document("audio"), _upload_file("mp3"))

    assert called == []


def test_diarization_fails_fast_without_model_config(monkeypatch, tmp_path):
    """未配置 Omni 模型时立刻抛错，不做 ffmpeg 转码。

    未配置模型（例如只部署了 ASR 的实例）是常见状态，白跑一次转码纯属浪费；
    这条测试锁定「先校验凭证再编码」的顺序。
    """
    service = _new_service()
    encoded = []
    monkeypatch.setattr(
        "internal.core.vision.omni_invoke.resolve_omni_credentials", lambda *a, **kw: {}
    )
    monkeypatch.setattr(
        "internal.core.vision.omni_invoke.encode_audio_for_omni",
        lambda *a, **kw: encoded.append(a) or a[1],
    )

    with pytest.raises(RuntimeError):
        service._invoke_diarization(str(tmp_path / "a.mp3"))

    assert encoded == [], "未配置模型时不应进行任何音频编码"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
docker exec llmops-api pytest test/internal/service/test_knowledge_media_extractor_service.py -v -k speaker
```

Expected：FAIL —— `AttributeError: 'KnowledgeMediaExtractorService' object has no attribute '_invoke_diarization'`（且 `_extract_audio` 不会给 cue 补 speaker）。

- [ ] **Step 3: 实现 `_invoke_diarization` 与 `_attach_speakers`**

在 `api/internal/service/knowledge_media_extractor_service.py` 中：

(a) 文件顶部 `_VIDEO_FRAME_PROMPT` 附近新增提示词/常量不需要；直接加方法。

(b) 在 `_call_asr_with_segments` 之后新增两个方法：

```python
    def _invoke_diarization(self, audio_path: str) -> list[dict[str, Any]]:
        """对本地音频执行说话人切分（独立方法便于测试替换）。

        返回 ``[{"speaker","start","end","text"}]``；未配置 Omni 模型或调用
        失败时抛错，由调用方降级——说话人标签是增强项，不该拖垮素材解析。

        **先校验凭证再编码**：未配置模型时直接抛错，避免白白跑一次 ffmpeg
        转码（未配置是常见状态，例如仅部署了 ASR 的实例）。
        """
        from internal.core.vision.omni_invoke import (
            build_diarization_prompt,
            encode_audio_for_omni,
            invoke_omni_audio,
            parse_diarization_segments,
            resolve_omni_credentials,
        )

        if not resolve_omni_credentials():
            raise RuntimeError("未配置 media_omni_analyze 模型，跳过说话人切分")

        duration = self._probe_audio_duration(audio_path)
        with tempfile.TemporaryDirectory(prefix="omni-audio-") as work:
            encoded = os.path.join(work, "audio.mp3")
            encode_audio_for_omni(audio_path, encoded, duration_sec=duration)
            text = invoke_omni_audio(encoded, build_diarization_prompt())
        return parse_diarization_segments(text)

    def _probe_audio_duration(self, audio_path: str) -> float:
        """探测音频时长（秒）；探测失败返回 0.0（编码器会退回上限码率）。"""
        from internal.core.vision.vision_invoke import probe_duration_sec

        return probe_duration_sec(audio_path)

    @staticmethod
    def _attach_speakers(
        cues: list[dict[str, Any]], diarization: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """把说话人标签对齐到 ASR cues 上（按时间重叠最大者归属）。

        为什么按重叠而不是按序号：ASR 与 Omni 的分句边界**不保证一致**，
        按序号对齐会在边界错位时整段说话人串位；按重叠取最大者是唯一
        与「两条时间轴各自独立」这一事实相容的对齐方式。
        """
        if not cues or not diarization:
            return cues

        aligned: list[dict[str, Any]] = []
        for cue in cues:
            start = float(cue.get("start") or 0.0)
            end = float(cue.get("end") or start)
            best_speaker, best_overlap = "", 0.0
            for segment in diarization:
                overlap = min(end, float(segment["end"])) - max(start, float(segment["start"]))
                if overlap > best_overlap:
                    best_overlap, best_speaker = overlap, str(segment["speaker"])
            enriched = dict(cue)
            if best_speaker:
                enriched["speaker"] = best_speaker
            aligned.append(enriched)
        return aligned
```

(c) 整段替换 `_extract_audio`。

**重要**：`_extract_audio` 现有实现里 `with tempfile.TemporaryDirectory() as temp_dir:` **只包住下载**，`file_path` 指向的文件在 `with` 退出时已被删除。说话人切分需要真实音频文件，因此**必须把 `with` 块扩到覆盖 `_invoke_diarization`**。直接整段替换 `_extract_audio` 为：

```python
    def _extract_audio(self, upload_file: UploadFile) -> list[MediaSegment]:
        """音频：下载后经 ASR 转写为文本片段，并补说话人切分。

        metadata 一并保留 ASR 时间轴（`transcript_segments`）——它是「给素材
        自动加字幕」的唯一时间码来源，不留存则事后只能重新跑一遍 ASR。

        临时目录必须覆盖到说话人切分结束：`file_path` 指向的文件在 `with`
        退出时即被删除，提前退出会让切分拿到不存在的路径。
        """
        from io import BytesIO

        from werkzeug.datastructures import FileStorage

        filename = (
            getattr(upload_file, "name", None)
            or os.path.basename(getattr(upload_file, "key", "") or "")
            or "material.audio"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = self._download_to(upload_file, temp_dir)
            with open(file_path, "rb") as fh:
                content = fh.read()

            file_storage = FileStorage(
                stream=BytesIO(content),
                filename=filename,
                content_type=getattr(upload_file, "mime_type", None) or "audio/mpeg",
            )
            transcript, cues = self._call_asr_with_segments(file_storage)
            if not transcript:
                return []

            # 说话人切分是增强项：只在已有 ASR 时间轴时执行（无时间轴则无可对齐
            # 锚点，跑一次纯属浪费）；失败只记 warning 并退回纯 ASR 结果——
            # 素材「能被找到」的能力必须保留。
            speakers: list[str] = []
            if cues:
                try:
                    diarization = self._invoke_diarization(file_path)
                    cues = self._attach_speakers(cues, diarization)
                    speakers = sorted(
                        {str(s["speaker"]) for s in diarization if s.get("speaker")}
                    )
                except Exception:
                    logger.warning(
                        "说话人切分失败，降级为纯 ASR 转写 filename=%s",
                        filename, exc_info=True,
                    )

        metadata: dict[str, Any] = {"media_type": DocumentMediaType.AUDIO.value}
        if cues:
            metadata["transcript_segments"] = cues
        if speakers:
            metadata["speakers"] = speakers
        return [MediaSegment(content=transcript, metadata=metadata)]
```

- [ ] **Step 4: 运行测试确认通过**

```bash
docker exec llmops-api pytest test/internal/service/test_knowledge_media_extractor_service.py -v
```

Expected：全部 passed（含 4 条新增：说话人标签 / 失败降级 / 无 cues 跳过 / 未配置快速失败）。

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/knowledge_media_extractor_service.py api/test/internal/service/test_knowledge_media_extractor_service.py
git commit -m "feat(kb): L1 音频解析补说话人切分（cue 级 speaker 标签）"
```

---

## Task 6: L1 视频 cues 补说话人标签

**Files:**
- Modify: `api/internal/service/knowledge_media_extractor_service.py`
- Test: `api/test/internal/service/test_knowledge_media_extractor_service.py`

- [ ] **Step 1: 写失败测试**

在 `api/test/internal/service/test_knowledge_media_extractor_service.py` 末尾追加：

```python
# ------------------------------------------------------------ 说话人切分（L1 视频）

def test_video_cues_get_speaker_from_diarization(tmp_path, monkeypatch):
    """视频的 cues 也要带 speaker：字幕与时间线锚点都消费同一份 cues。"""
    service = _new_service()
    service._extract_frames_with_offsets = lambda video_path, out_dir: _write_frames(tmp_path, 3)
    service._consume_subtitle_first = lambda *a, **kw: (
        "甲说你好。乙说你好。",
        [
            {"text": "甲说你好。", "start": 0.0, "end": 2.0},
            {"text": "乙说你好。", "start": 2.0, "end": 4.0},
        ],
        False,
    )
    service._invoke_diarization = lambda path: [
        {"speaker": "Speaker 1", "start": 0.0, "end": 2.0, "text": "甲说你好。"},
        {"speaker": "Speaker 2", "start": 2.0, "end": 4.0, "text": "乙说你好。"},
    ]
    service._process_timeline_batch = lambda batch, scenario, **kw: []

    segments = service._extract_video(
        _upload_file("mp4"), account_id=None, document_id=None, document=None
    )

    transcript_segment = next(s for s in segments if "transcript_segments" in s.metadata)
    cues = transcript_segment.metadata["transcript_segments"]
    assert [cue["speaker"] for cue in cues] == ["Speaker 1", "Speaker 2"]
    assert transcript_segment.metadata["speakers"] == ["Speaker 1", "Speaker 2"]


def test_video_degrades_when_diarization_fails(tmp_path):
    service = _new_service()
    service._extract_frames_with_offsets = lambda video_path, out_dir: _write_frames(tmp_path, 3)
    service._consume_subtitle_first = lambda *a, **kw: (
        "你好。",
        [{"text": "你好。", "start": 0.0, "end": 1.0}],
        False,
    )

    def _boom(path):
        raise RuntimeError("omni unavailable")

    service._invoke_diarization = _boom
    service._process_timeline_batch = lambda batch, scenario, **kw: []

    segments = service._extract_video(
        _upload_file("mp4"), account_id=None, document_id=None, document=None
    )

    transcript_segment = next(s for s in segments if "transcript_segments" in s.metadata)
    assert "speaker" not in transcript_segment.metadata["transcript_segments"][0]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
docker exec llmops-api pytest test/internal/service/test_knowledge_media_extractor_service.py -v -k video_cues
```

Expected：FAIL —— `KeyError: 'speaker'`。

- [ ] **Step 3: 在 `_extract_video` 中接入**

在 `_extract_video` 里 `transcript, cues, is_subtitle = self._consume_subtitle_first(...)` 之后、构造 `segments` 之前插入：

```python
            # 说话人切分（增强项）：字幕与音轨两条来源都需要补 speaker——
            # 字幕路径没有音频 ASR，但音轨仍在视频里，可抽出来单独做切分。
            speakers: list[str] = []
            if cues:
                try:
                    audio_path = self._extract_audio_track(file_path)
                    diarization = self._invoke_diarization(audio_path)
                    cues = self._attach_speakers(cues, diarization)
                    speakers = sorted(
                        {str(s["speaker"]) for s in diarization if s.get("speaker")}
                    )
                except Exception:
                    logger.warning(
                        "视频说话人切分失败，降级为无说话人标签 file=%s",
                        os.path.basename(file_path), exc_info=True,
                    )
```

并把随后的 metadata 构造改为：

```python
                if cues:
                    metadata["transcript_segments"] = cues
                if speakers:
                    metadata["speakers"] = speakers
```

- [ ] **Step 4: 运行测试确认通过**

```bash
docker exec llmops-api pytest test/internal/service/test_knowledge_media_extractor_service.py -v
```

Expected：全部 passed（含 2 条新增）。

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/knowledge_media_extractor_service.py api/test/internal/service/test_knowledge_media_extractor_service.py
git commit -m "feat(kb): L1 视频解析 cues 补说话人标签"
```

---

## Task 7: L1 图片补 OCR 区块坐标

**Files:**
- Modify: `api/internal/core/vision/vision_invoke.py`
- Modify: `api/internal/service/knowledge_media_extractor_service.py`
- Test: `api/test/internal/core/vision/test_ocr_blocks.py`
- Test: `api/test/internal/service/test_knowledge_media_extractor_service.py`

- [ ] **Step 1: 写失败测试（解析纯函数）**

新建 `api/test/internal/core/vision/test_ocr_blocks.py`：

```python
"""OCR 区块坐标解析测试（纯函数，无模型调用）。

坐标以 0-1000 归一化值返回（与 Qwen-VL grounding 输出口径一致），
由前端按显示尺寸换算像素——存归一化值可避免图片被缩放后坐标失真。
"""
from internal.core.vision.vision_invoke import (
    OCR_BLOCKS_PROMPT,
    parse_ocr_blocks,
)


def test_prompt_demands_normalized_boxes_and_json_only():
    assert "0-1000" in OCR_BLOCKS_PROMPT
    assert "bbox_2d" in OCR_BLOCKS_PROMPT
    assert "JSON" in OCR_BLOCKS_PROMPT


def test_parse_ocr_blocks_reads_json_array():
    text = '[{"text":"限时五折","bbox_2d":[10,20,300,80]}]'
    assert parse_ocr_blocks(text) == [{"text": "限时五折", "bbox": [10, 20, 300, 80]}]


def test_parse_ocr_blocks_accepts_dict_wrapper_and_code_fence():
    text = '```json\n{"blocks":[{"text":"A","bbox_2d":[0,0,100,100]}]}\n```'
    assert parse_ocr_blocks(text) == [{"text": "A", "bbox": [0, 0, 100, 100]}]


def test_parse_ocr_blocks_clamps_out_of_range_and_drops_invalid():
    text = (
        '[{"text":"x","bbox_2d":[-5,0,1007,1000]},'   # 越界 → 夹紧到 0/1000
        '{"text":"y","bbox_2d":[1,2,3]},'             # bbox 非 4 元 → 丢弃
        '{"text":"","bbox_2d":[1,2,3,4]}]'            # text 为空 → 丢弃
    )
    assert parse_ocr_blocks(text) == [{"text": "x", "bbox": [0, 0, 1000, 1000]}]


def test_parse_ocr_blocks_returns_empty_on_garbage():
    assert parse_ocr_blocks("no json") == []
    assert parse_ocr_blocks("") == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
docker exec llmops-api pytest test/internal/core/vision/test_ocr_blocks.py -v
```

Expected：FAIL —— `ImportError: cannot import name 'OCR_BLOCKS_PROMPT'`。

- [ ] **Step 3: 在 `vision_invoke.py` 实现 prompt 与解析**

在 `api/internal/core/vision/vision_invoke.py` 顶部常量区追加：

```python
# OCR 区块坐标提示词：要求归一化坐标（0-1000），避免图片被缩放后坐标失真。
# 与 Qwen-VL grounding 的输出口径一致（同一模型家族，无需二次换算）。
OCR_BLOCKS_PROMPT = (
    "请识别这张图片中的所有文字，并为每段文字给出位置框。"
    "以 JSON 数组输出，每个元素形如：\n"
    '[{"text": "文字内容", "bbox_2d": [x1, y1, x2, y2]}]\n'
    "bbox_2d 为归一化坐标（0-1000），表示左上角与右下角。仅输出 JSON。"
)
```

并在 `invoke_vision_model_multi` 之后追加解析函数。

**注意**：`vision_invoke.py` 当前**没有**导入 `json` / `re`（已实测：只有 `base64`/`logging`/`os`/`shutil`/`subprocess`/`tempfile`/`dataclass`）。必须在文件顶部导入区补：

```python
import json
import re
```

然后追加：

```python
def parse_ocr_blocks(text: str) -> list[dict]:
    """解析视觉模型返回的 OCR 区块（文本 + 归一化坐标）。

    容错策略与 Omni 解析一致：容忍 ```json 围栏、dict 包装（blocks/results）、
    数组直出；bbox 非 4 元或文本为空一律丢弃（无法定位或无法检索的区块留着
    只会污染结果）；越界坐标夹紧到 0-1000 而非丢弃（模型偶发给 1001 属噪声，
    整块丢掉会漏掉真实文字）。
    """
    normalized = str(text or "").strip()
    if not normalized:
        return []
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)```", normalized, re.DOTALL)
    candidate = fenced.group(1).strip() if fenced else normalized
    try:
        payload = json.loads(candidate)
    except (TypeError, ValueError):
        start, end = candidate.find("["), candidate.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            payload = json.loads(candidate[start : end + 1])
        except (TypeError, ValueError):
            return []

    if isinstance(payload, dict):
        raw_blocks = payload.get("blocks") or payload.get("results") or []
    else:
        raw_blocks = payload

    blocks: list[dict] = []
    for item in raw_blocks if isinstance(raw_blocks, list) else []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("text") or "").strip()
        bbox = item.get("bbox_2d") or item.get("bbox")
        if not content or not isinstance(bbox, list) or len(bbox) != 4:
            continue
        try:
            coords = [max(0, min(1000, int(round(float(value))))) for value in bbox]
        except (TypeError, ValueError):
            continue
        blocks.append({"text": content, "bbox": coords})
    return blocks
```

- [ ] **Step 4: 运行测试确认通过**

```bash
docker exec llmops-api pytest test/internal/core/vision/test_ocr_blocks.py -v
```

Expected：5 passed。

- [ ] **Step 5: 写失败测试（服务接入）**

在 `api/test/internal/service/test_knowledge_media_extractor_service.py` 末尾追加：

```python
# ------------------------------------------------------------ 图片 OCR 区块坐标

def test_image_extraction_attaches_ocr_blocks():
    """图片解析除摘要外，还需产出带坐标的 OCR 区块。"""
    service = _new_service(vision_text="画面为促销海报，含文字「限时五折」")
    service._invoke_ocr_blocks = lambda data_uri: [
        {"text": "限时五折", "bbox": [10, 20, 300, 80]}
    ]

    segments = service.extract(_document("image"), _upload_file("jpg"))

    assert segments[0].metadata["ocr_blocks"] == [
        {"text": "限时五折", "bbox": [10, 20, 300, 80]}
    ]


def test_image_extraction_degrades_when_ocr_blocks_fail():
    """坐标识别失败只丢坐标，摘要片段必须保留。"""
    service = _new_service(vision_text="一张产品截图")

    def _boom(data_uri):
        raise RuntimeError("grounding unavailable")

    service._invoke_ocr_blocks = _boom

    segments = service.extract(_document("image"), _upload_file("jpg"))

    assert len(segments) == 1
    assert "ocr_blocks" not in segments[0].metadata
    assert segments[0].content == "一张产品截图"
```

- [ ] **Step 6: 运行测试确认失败**

```bash
docker exec llmops-api pytest test/internal/service/test_knowledge_media_extractor_service.py -v -k ocr_blocks
```

Expected：FAIL —— `AttributeError: … has no attribute '_invoke_ocr_blocks'`。

- [ ] **Step 7: 接入 `_extract_image`**

在 `knowledge_media_extractor_service.py` 的 `_invoke_vision_batch` 之后新增：

```python
    def _invoke_ocr_blocks(self, data_uri: str) -> list[dict]:
        """识别图片中的文字区块与坐标（独立方法便于测试替换）。

        复用既有 ``vision_analyze`` 视觉模型（同属 Qwen-VL 家族），不新增
        feature_key——OCR 坐标与视觉摘要用的是同一模型、同一计费口径。
        """
        from internal.core.vision.vision_invoke import OCR_BLOCKS_PROMPT, parse_ocr_blocks

        return parse_ocr_blocks(self._invoke_vision(data_uri, OCR_BLOCKS_PROMPT))
```

并把 `_extract_image` 改为：

```python
    def _extract_image(self, upload_file: UploadFile) -> list[MediaSegment]:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = self._download_to(upload_file, temp_dir)
            data_uri = path_to_data_uri(file_path)
            summary = str(self._invoke_vision(data_uri, _IMAGE_PROMPT) or "").strip()
            # OCR 区块坐标是增强项：失败只丢坐标，摘要片段必须保留
            ocr_blocks: list[dict] = []
            try:
                ocr_blocks = self._invoke_ocr_blocks(data_uri)
            except Exception:
                logger.warning(
                    "图片 OCR 区块识别失败，降级为纯摘要 file=%s",
                    os.path.basename(file_path), exc_info=True,
                )
        if not summary:
            return []
        metadata: dict[str, Any] = {
            "media_type": DocumentMediaType.IMAGE.value,
            "vision_summary": summary,
        }
        if ocr_blocks:
            metadata["ocr_blocks"] = ocr_blocks
        return [MediaSegment(content=summary, metadata=metadata)]
```

- [ ] **Step 8: 运行测试确认通过**

```bash
docker exec llmops-api pytest test/internal/service/test_knowledge_media_extractor_service.py test/internal/core/vision/test_ocr_blocks.py -v
```

Expected：全部 passed。

- [ ] **Step 9: 提交**

```bash
git add api/internal/core/vision/vision_invoke.py api/internal/service/knowledge_media_extractor_service.py api/test/internal/core/vision/test_ocr_blocks.py api/test/internal/service/test_knowledge_media_extractor_service.py
git commit -m "feat(kb): L1 图片解析补 OCR 区块坐标"
```

---

## Task 8: L2 视频场景切分

**Files:**
- Create: `api/internal/core/vision/scene_planning.py`
- Modify: `api/internal/service/knowledge_indexing_service.py`
- Test: `api/test/internal/core/vision/test_scene_planning.py`
- Test: `api/test/internal/service/test_knowledge_indexing_l2_scenes.py`

- [ ] **Step 1: 写失败测试（场景区间规划纯函数）**

新建 `api/test/internal/core/vision/test_scene_planning.py`：

```python
"""场景边界 → 场景区间 规划测试（纯函数，无 IO）。"""
from internal.core.vision.scene_planning import (
    MIN_SCENE_SEC,
    plan_scene_ranges,
)


def test_boundaries_become_contiguous_ranges_covering_whole_duration():
    ranges = plan_scene_ranges([10.0, 25.0], duration_sec=40.0)
    assert ranges == [(0.0, 10.0), (10.0, 25.0), (25.0, 40.0)]


def test_short_scenes_are_merged_into_neighbour():
    """过短场景会被合并：秒级碎片场景检索价值低，只会灌入噪声片段。"""
    ranges = plan_scene_ranges([10.0, 10.4], duration_sec=40.0)
    assert all(end - start >= MIN_SCENE_SEC for start, end in ranges)
    assert ranges[0] == (0.0, 40.0)


def test_boundaries_beyond_duration_are_dropped():
    assert plan_scene_ranges([10.0, 999.0], duration_sec=40.0) == [
        (0.0, 10.0),
        (10.0, 40.0),
    ]


def test_no_boundaries_yields_single_scene():
    assert plan_scene_ranges([], duration_sec=40.0) == [(0.0, 40.0)]


def test_zero_duration_yields_no_scene():
    """时长不可得时不产出场景（无时间轴的片段无法被时间检索命中）。"""
    assert plan_scene_ranges([10.0], duration_sec=0.0) == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
docker exec llmops-api pytest test/internal/core/vision/test_scene_planning.py -v
```

Expected：FAIL —— `ModuleNotFoundError: No module named 'internal.core.vision.scene_planning'`。

- [ ] **Step 3: 实现 `scene_planning.py`**

新建 `api/internal/core/vision/scene_planning.py`：

```python
"""场景区间规划（纯函数）。

输入 Omni 给出的场景切换点，输出**连续覆盖全片**的场景区间列表。

为什么强调「连续覆盖」：检索时用户问「视频第 3 段讲了什么」，若区间之间有
缝隙，落在缝隙里的内容任何场景都检索不到——静默丢失。故区间首尾必须补齐
到 0 与总时长，且相邻区间首尾相接（前一个 end == 后一个 start）。
"""
from __future__ import annotations

# 最短场景时长（秒）：低于此值的场景会被并入相邻场景。
# 秒级碎片场景对检索无价值（内容太短、语义不完整），保留只会灌入噪声片段。
MIN_SCENE_SEC = 2.0


def plan_scene_ranges(
    boundaries: list[float],
    *,
    duration_sec: float,
    min_scene_sec: float = MIN_SCENE_SEC,
) -> list[tuple[float, float]]:
    """把场景切换点转为连续场景区间。

    - 丢弃越界（<=0 或 >= 总时长）的切换点；
    - 合并短于 ``min_scene_sec`` 的相邻区间；
    - 首尾补齐到 0 与 ``duration_sec``；
    - 时长不可得（<=0）时返回空列表。
    """
    if duration_sec <= 0:
        return []

    points = sorted({float(value) for value in boundaries if 0 < float(value) < duration_sec})
    edges = [0.0, *points, float(duration_sec)]

    merged: list[tuple[float, float]] = []
    for start, end in zip(edges, edges[1:]):
        if end - start <= 0:
            continue
        if merged and end - start < min_scene_sec:
            # 过短：并入前一个场景（而不是自成一个碎片场景）
            merged[-1] = (merged[-1][0], end)
            continue
        merged.append((start, end))

    # 首段过短时并入后一段：否则会留下一个以 0 开头、时长不足的场景
    if len(merged) > 1 and merged[0][1] - merged[0][0] < min_scene_sec:
        merged[1] = (merged[0][0], merged[1][1])
        merged.pop(0)

    return merged
```

- [ ] **Step 4: 运行测试确认通过**

```bash
docker exec llmops-api pytest test/internal/core/vision/test_scene_planning.py -v
```

Expected：5 passed。

- [ ] **Step 5: 写失败测试（L2 场景片段）**

新建 `api/test/internal/service/test_knowledge_indexing_l2_scenes.py`：

```python
"""L2 视频场景切分测试。

场景片段以 tier2_scene=True 标记，与 L1 片段、L2 窗口片段三者互不混淆；
重复触发必须先清理上一轮场景片段；无正文的场景不建片段（检索价值为零）。
"""
from types import SimpleNamespace
from uuid import uuid4

from internal.service.knowledge_indexing_service import KnowledgeIndexingService


class _Session:
    """最小 session 替身：只支持 query().filter().all() 与 delete()。"""

    def __init__(self, segments):
        self.segments = segments
        self.deleted = []

    def query(self, *args, **kwargs):
        session = self

        class _Q:
            def filter(self, *a, **kw):
                return self

            def all(self):
                return session.segments

        return _Q()

    def delete(self, obj):
        self.deleted.append(obj)


def _service(segments):
    """构造服务：桩掉 create/update 与向量、分词、embedding 依赖。

    用桩而不是真 DB：本测试只验证「片段建了没有、标记对不对、正文取自哪里」，
    向量写入由 KnowledgeVectorService 自己的测试覆盖。
    """
    session = _Session(segments)
    service = KnowledgeIndexingService(db=SimpleNamespace(session=session))
    service.jieba_service = SimpleNamespace(extract_keywords=lambda text, n: ["k"])
    service.embeddings_service = SimpleNamespace(calculate_token_count=lambda text: 1)
    service.knowledge_vector_service = SimpleNamespace(index_segment=lambda seg, kb: None)

    created = []

    def _create(model, **kwargs):
        obj = SimpleNamespace(id=uuid4(), **kwargs)
        created.append(obj)
        return obj

    service.create = _create
    service.update = lambda obj, **kwargs: None
    service.created_segments = created
    return service


def _document(media_type="video"):
    return SimpleNamespace(
        id=uuid4(),
        media_type=media_type,
        parse_profile={},
        knowledge_base_id=uuid4(),
        owner_account_id=uuid4(),
        knowledge_base=SimpleNamespace(),
    )


def _l1_segment(content, start_sec, end_sec=0.0):
    return SimpleNamespace(
        id=uuid4(),
        position=1,
        content=content,
        metadata_={"media_type": "video", "start_sec": start_sec, "end_sec": end_sec},
    )


def test_scene_segment_uses_overlapping_l1_content():
    """场景正文必须取自落在该区间内的 L1 时间线片段正文。

    为什么不能写「场景 1（0-10s）」这种占位正文：那种片段没有任何可检索
    语义，向量检索永远匹配不到，等于建了一堆死片段。
    """
    service = _service([_l1_segment("开场：主播介绍产品", start_sec=0.0, end_sec=8.0)])
    service._resolve_document_duration = lambda doc: 40.0
    service._invoke_scene_boundaries = lambda doc: [10.0, 25.0]

    created = service._enhance_l2_scenes(_document())

    # 只有 0-10s 场景内有 L1 正文，另两个场景无正文 → 不建片段
    assert created == 1
    segment = service.created_segments[0]
    assert segment.content == "开场：主播介绍产品"
    assert segment.metadata_["tier2_scene"] is True
    assert segment.metadata_["start_sec"] == 0.0
    assert segment.metadata_["end_sec"] == 10.0


def test_scene_segments_are_indexed_and_enabled():
    """必须写文本向量并置为 completed/enabled，否则检索不到。"""
    indexed = []
    service = _service([_l1_segment("正文", start_sec=1.0)])
    service.knowledge_vector_service = SimpleNamespace(
        index_segment=lambda seg, kb: indexed.append(seg.id)
    )
    updated = []
    service.update = lambda obj, **kwargs: updated.append(kwargs)
    service._resolve_document_duration = lambda doc: 40.0
    service._invoke_scene_boundaries = lambda doc: []

    service._enhance_l2_scenes(_document())

    assert indexed == [service.created_segments[0].id]
    assert updated[-1]["status"] == "completed"
    assert updated[-1]["enabled"] is True


def test_previous_scene_segments_are_cleared():
    stale = SimpleNamespace(
        id=uuid4(), metadata_={"tier2_scene": True, "start_sec": 0.0}
    )
    service = _service([stale])
    service._resolve_document_duration = lambda doc: 40.0
    service._invoke_scene_boundaries = lambda doc: []

    service._enhance_l2_scenes(_document())

    assert stale in service.db.session.deleted


def test_scene_enhancement_is_noop_for_audio():
    service = _service([])
    assert service._enhance_l2_scenes(_document("audio")) == 0


def test_scene_enhancement_is_noop_without_knowledge_base():
    """文档未关联知识库时无法索引向量，直接跳过而不是建一堆不可检索片段。"""
    document = _document()
    document.knowledge_base = None
    service = _service([])

    assert service._enhance_l2_scenes(document) == 0
```

- [ ] **Step 6: 运行测试确认失败**

```bash
docker exec llmops-api pytest test/internal/service/test_knowledge_indexing_l2_scenes.py -v
```

Expected：FAIL —— `AttributeError: 'KnowledgeIndexingService' object has no attribute '_enhance_l2_scenes'`。

- [ ] **Step 7: 在索引服务实现场景切分**

在 `api/internal/service/knowledge_indexing_service.py` 中：

(a) 把 `_enhance_l2` **整段**替换为下面这版（场景切分独立于窗口，且必须放在窗口的空分支**之外**——没有 L1 命中帧不代表没有场景）。

关键改动点（逐条核对）：
1. 场景切分放在 `_clear_previous_l2_windows` 之后、`plan_l2_windows` 之前；
2. 窗口为空时的提前返回也带上 `scenes` 键；
3. 两个返回分支都补 `scenes`。

```python
    def _enhance_l2(
        self, document: KnowledgeDocument, explicit_range: tuple[float, float] | None = None
    ) -> dict:
        """L2 增强主体：窗口密抽（视频） + 场景切分（视频）。

        规格 §5.4：L2 是「放大镜」不是「重扫」。L1 帧的 `time_offset` 给出
        目标时刻，扩窗后仅在窗口内按 0.5 秒/帧抽取——这是成本从「整片逐帧」
        降到「按需区间」的关键。

        两条增强相互独立：
        - **窗口密抽**由 L1 命中帧驱动（帧级，用于「改细节」）；
        - **场景切分**由画面切换驱动（段级，用于「按语义分段」），
          故不放在窗口的空分支之内——没有命中帧也可能存在场景。

        其余媒体类型（图片/音频）的 L2 增强仍是后续增量，此处直接返回。
        """
        media_type = getattr(document, "media_type", None) or DocumentMediaType.DOCUMENT.value
        if media_type != DocumentMediaType.VIDEO.value:
            return {"media_type": media_type, "window_frames": 0, "scenes": 0}

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

        # 场景切分不依赖 hit_offsets，必须在窗口空分支之前执行
        scene_count = self._enhance_l2_scenes(document)

        windows = plan_l2_windows(
            hit_offsets,
            duration_sec=self._resolve_document_duration(document),
            explicit_range=explicit_range,
        )
        if not windows:
            logger.info("L2 无可用窗口（无 L1 命中帧），跳过 document_id=%s", document.id)
            return {
                "media_type": media_type,
                "window_frames": 0,
                "windows": 0,
                "scenes": scene_count,
            }

        created = 0
        for index, (window_start, window_end) in enumerate(windows, start=1):
            created += self._extract_and_persist_window(
                document, window_start, window_end - window_start, window_index=index
            )
        return {
            "media_type": media_type,
            "window_frames": created,
            "windows": len(windows),
            "scenes": scene_count,
        }
```

(b) 在 `_clear_previous_l2_windows` 之后新增四个方法。

**实现必须对齐 `_extract_and_persist_window` 的既有模式**（用 `self.create(KnowledgeSegment, …)`、写文本向量、置 `completed` + `enabled=True`）——只建片段不索引等于白跑，用户永远检索不到。

```python
    def _enhance_l2_scenes(self, document: KnowledgeDocument) -> int:
        """按 Omni 识别的场景边界重建场景片段，返回新建片段数。

        只处理视频：音频的场景语义与说话人切分重叠，图片无时间轴。
        场景片段以 ``tier2_scene=True`` 标记，与 L1 片段、L2 窗口片段区分。

        正文取自**落在该场景区间内的 L1 时间线片段正文**（时间重叠即归属）——
        不能写「场景 1（0-10s）」这类占位正文：那种文本没有任何可检索语义，
        向量检索永远匹配不到，等于建了一堆死片段。
        """
        media_type = getattr(document, "media_type", None) or DocumentMediaType.DOCUMENT.value
        if media_type != DocumentMediaType.VIDEO.value:
            return 0

        knowledge_base = document.knowledge_base
        if knowledge_base is None:
            # 无知识库则无法写向量，建出来的片段也检索不到，直接跳过
            return 0

        duration = self._resolve_document_duration(document)
        # 先取边界再清旧片段：取边界失败时旧片段保持原样（本次不改动），
        # 避免「已删旧片段、又没建成新片段」的空窗。
        # 失败只在方法内降级返回 0（场景是增强项，且既有 L2 调用方没有
        # 为场景准备兜底——抛出去会变成其它测试里的偶发噪声）。
        try:
            boundaries = self._invoke_scene_boundaries(document)
        except Exception:
            logger.warning(
                "L2 场景边界识别失败，跳过场景切分 document_id=%s", document.id, exc_info=True
            )
            return 0
        ranges = plan_scene_ranges(boundaries, duration_sec=duration)

        segments = self.db.session.query(KnowledgeSegment).filter(
            KnowledgeSegment.knowledge_document_id == document.id,
        ).all()
        self._clear_previous_l2_scenes(segments)
        if not ranges:
            logger.info("L2 无可用场景区间，跳过 document_id=%s", document.id)
            return 0

        # 正文来源：L1 时间线片段（带 start_sec/end_sec），排除两轮 L2 产物
        l1_timeline = [
            s
            for s in segments
            if not (getattr(s, "metadata_", None) or {}).get("tier2_window")
            and not (getattr(s, "metadata_", None) or {}).get("tier2_scene")
            and (getattr(s, "metadata_", None) or {}).get("start_sec") is not None
        ]

        created = 0
        next_position = self._next_segment_position(document)
        for index, (start, end) in enumerate(ranges):
            content = self._collect_scene_content(l1_timeline, start, end)
            if not content:
                continue
            segment = self.create(
                KnowledgeSegment,
                knowledge_base_id=document.knowledge_base_id,
                knowledge_document_id=document.id,
                owner_account_id=document.owner_account_id,
                position=next_position,
                content=content,
                keywords=self.jieba_service.extract_keywords(content, 10),
                metadata_={
                    "media_type": DocumentMediaType.VIDEO.value,
                    "tier2_scene": True,
                    "scene_index": index + 1,
                    "start_sec": float(start),
                    "end_sec": float(end),
                },
                character_count=len(content),
                token_count=self.embeddings_service.calculate_token_count(content),
                status=SegmentStatus.INDEXING.value,
                enabled=False,
            )
            # 文本向量：让场景段落可被文本检索命中
            self.knowledge_vector_service.index_segment(segment, knowledge_base)
            self.update(
                segment,
                status=SegmentStatus.COMPLETED.value,
                enabled=True,
            )
            next_position += 1
            created += 1
        return created

    @staticmethod
    def _collect_scene_content(l1_timeline, start_sec: float, end_sec: float) -> str:
        """拼接落在 [start_sec, end_sec) 内的 L1 片段正文（按时间序）。

        判定用「时间重叠 > 0」而不是「完整包含」：跨场景边界的台词/画面
        描述必须归属到某个场景，用包含判定会让边界段落两个场景都不收，
        静默丢失。重叠即收，允许相邻场景各收录一次边界段落。
        """
        picked: list[tuple[float, str]] = []
        for segment in l1_timeline:
            metadata = getattr(segment, "metadata_", None) or {}
            seg_start = float(metadata.get("start_sec") or 0.0)
            seg_end = float(metadata.get("end_sec") or seg_start)
            if min(end_sec, seg_end) - max(start_sec, seg_start) <= 0:
                continue
            content = str(getattr(segment, "content", "") or "").strip()
            if content:
                picked.append((seg_start, content))
        picked.sort(key=lambda item: item[0])
        return "\n".join(content for _, content in picked)

    def _invoke_scene_boundaries(self, document: KnowledgeDocument) -> list[float]:
        """调用 Omni 识别场景切换点（独立方法便于测试替换）。

        送的是**音轨**而非整段视频：场景切换主要由画面驱动，但 Omni 的
        音视频联合输入能显著提升「同一画面内的对话换场」识别率；只送音轨
        可同时避免整段视频的上传体积与超长时长成本。
        """
        from internal.core.vision.omni_invoke import (
            build_scene_prompt,
            encode_audio_for_omni,
            invoke_omni_audio,
            parse_scene_boundaries,
        )
        from internal.core.vision.vision_invoke import extract_video_audio

        video_path = self._download_document_video(document)
        if not video_path:
            return []

        with tempfile.TemporaryDirectory(prefix="l2-scene-") as work:
            audio_path = os.path.join(work, "track.wav")
            extract_video_audio(video_path, audio_path)
            encoded = os.path.join(work, "track.mp3")
            encode_audio_for_omni(
                audio_path, encoded, duration_sec=self._resolve_document_duration(document)
            )
            text = invoke_omni_audio(encoded, build_scene_prompt())
        return parse_scene_boundaries(text)

    def _clear_previous_l2_scenes(self, segments) -> None:
        """删除上一轮场景片段。

        与 ``_clear_previous_l2_windows`` 同理：不清理会让重复触发累积重复片段。
        场景片段**不含帧对象**，故无需释放配额（与窗口片段的关键差别）。
        """
        stale = [
            s for s in segments if (getattr(s, "metadata_", None) or {}).get("tier2_scene")
        ]
        for segment in stale:
            self.db.session.delete(segment)
```

(c) 在文件顶部导入区补（`os`、`tempfile`、`re` 已存在，**不要重复导入**）：

```python
from internal.core.vision.scene_planning import plan_scene_ranges
```

`extract_video_audio` 采用**局部导入**（放在 `_invoke_scene_boundaries` 内），与同文件 `_invoke_l2_vision` 局部导入 `invoke_vision_model` 的既有风格一致——避免顶部导入拖慢模块加载，也避免与 `knowledge_media_extractor_service` 形成导入环。

- [ ] **Step 8: 运行测试确认通过**

```bash
docker exec llmops-api pytest test/internal/service/test_knowledge_indexing_l2_scenes.py test/internal/core/vision/test_scene_planning.py -v
```

Expected：11 passed（场景切分 6 + 场景区间规划 5）。

- [ ] **Step 9: 跑既有 L2 测试确认无回归**

```bash
docker exec llmops-api pytest test/internal/service/test_l2_range_sampling.py test/internal/service/test_l2_explicit_range.py test/internal/task/test_knowledge_l2_tasks.py -v
```

Expected：全部 passed。**已知的两点预期差异**，逐条确认不是故障：

1. `test_l2_range_sampling.py::test_no_hits_means_no_extraction` 断言 `result["window_frames"] == 0` 仍成立；该用例未 stub `_enhance_l2_scenes`，场景分支会走到「下载/抽音轨失败」→ 方法内 `try/except` 降级返回 0，只产生一条 warning 日志。**这不影响断言**。
2. 若有用例断言 `_enhance_l2` 返回字典的**精确键集合**，需同步补 `scenes` 键（本次新增返回字段，属预期变更）。

- [ ] **Step 10: 提交**

```bash
git add api/internal/core/vision/scene_planning.py api/internal/service/knowledge_indexing_service.py api/test/internal/core/vision/test_scene_planning.py api/test/internal/service/test_knowledge_indexing_l2_scenes.py
git commit -m "feat(kb): L2 视频场景切分（Omni 边界识别 + 连续区间）"
```

---

## Task 9: 架构文档同步与图谱更新

**Files:**
- Modify: `docs/prd/modules/02-knowledge-base.md`
- Modify: `docs/README.md`（仅当新增顶层文档时）

- [ ] **Step 1: 更新 `02-knowledge-base.md` 的三处「未实现」登记**

必须**实测后**再写，措辞与实际落地一致（不得留「待确认」）：

1. §「资料内容库需要支持」段落中，把
   `图片：…L1 视觉理解已落地，细粒度 OCR 区块坐标等 L2 增强未实现。`
   改为
   `图片：…L1 视觉理解已落地，OCR 区块坐标（归一化 bbox，metadata.ocr_blocks）已落地。`

2. 同段落中，把
   `音频：会议录音、访谈、播客、语音备忘等，L1 ASR 转写已落地，说话人切分等 L2 增强未实现。`
   改为
   `音频：…L1 ASR 转写 + 说话人切分（cue 级 speaker 标签，metadata.speakers）已落地；章节切分未实现。`

3. §11.11 档位表中，把「说话人切分、细粒度 OCR 坐标、场景切分仍未实现」改为
   `说话人切分（L1，cue 级 speaker）、细粒度 OCR 坐标（L1，归一化 bbox）、场景切分（L2，tier2_scene 片段）均已落地；音频章节切分未实现。`

4. 在 L2 小节补一段说明新增的 `tier2_scene` 标记与清理规则（对齐既有 `tier2_window` 的写法）。

- [ ] **Step 2: 核对导航**

本次改动都在既有文件内，**不新增顶层文档**，故 `docs/README.md` 无需改动。若改为新建文档则必须登记。

- [ ] **Step 3: 更新知识图谱**

```bash
python -m graphify update .
```

- [ ] **Step 4: 提交**

```bash
git add docs/prd/modules/02-knowledge-base.md graphify-out/
git commit -m "docs(prd): 知识库多模态 L2 三项缺口已落地（说话人/场景/OCR 坐标）"
```

---

## 验收清单（全部通过才算完成）

- [ ] `docker exec llmops-api pytest test/internal/core/vision/ test/internal/service/test_knowledge_media_extractor_service.py test/internal/service/test_knowledge_indexing_l2_scenes.py -v` 全绿
- [ ] `docker exec llmops-api pytest test/internal/service/test_knowledge_indexing_service.py -v` 无回归
- [ ] `/admin/public-ai-features` 列表出现 `media_omni_analyze`，可绑定 Omni 模型
- [ ] 上传一段多说话人音频：`metadata.transcript_segments` 每条带 `speaker`，`metadata.speakers` 为说话人清单
- [ ] 上传含文字图片：`metadata.ocr_blocks` 为 `[{"text","bbox":[x1,y1,x2,y2]}]`（0-1000 归一化）
- [ ] 对视频触发 `POST /space/knowledge-bases/<kb_id>/documents/<document_id>/l2`：返回体含 `tier2.scenes`，且新片段 `metadata.tier2_scene=True`
- [ ] 重复触发 L2：场景片段不累积（旧片段被清理）
- [ ] 未绑定 `media_omni_analyze` 模型时：素材解析仍成功，仅无 speaker/scenes（降级路径可用）
- [ ] `docs/prd/modules/02-knowledge-base.md` 三项登记已更新且与实测一致
- [ ] 已执行 `python -m graphify update .`

## 接线自检（AGENTS.md 强制项）

| 新增产物 | 入口 / 触发路径 |
| --- | --- |
| feature_key `media_omni_analyze` | `/admin/public-ai-features` 可绑定模型；运行时经 `LanguageModelService.get_feature_credentials` 读取 |
| `omni_invoke.encode_audio_for_omni` / `invoke_omni_audio` | `KnowledgeMediaExtractorService._invoke_diarization`（音频/视频 L1）与 `KnowledgeIndexingService._invoke_scene_boundaries`（视频 L2） |
| `KnowledgeMediaExtractorService._invoke_diarization` | `_extract_audio`（L1 音频）与 `_extract_video`（L1 视频） |
| `KnowledgeMediaExtractorService._invoke_ocr_blocks` | `_extract_image`（L1 图片） |
| `scene_planning.plan_scene_ranges` | `KnowledgeIndexingService._enhance_l2_scenes` |
| `KnowledgeIndexingService._enhance_l2_scenes` | `_enhance_l2`（视频分支）← Celery `internal.task.knowledge_l2_tasks.build_document_l2_task` ← 路由 `POST /space/knowledge-bases/<kb_id>/documents/<document_id>/l2` |
| `metadata.speakers` / `cue.speaker` | 消费方：`video_edit_service._load_stored_cues`（字幕生成）、`build_timeline_plan`（时间线锚点） |
| `metadata.ocr_blocks` | 消费方：片段 metadata 透传至检索结果；前端按显示尺寸换算像素（本次不做前端渲染） |
| `metadata.tier2_scene` | 消费方：检索结果区分场景片段；`_clear_previous_l2_scenes` 负责重复触发清理 |
