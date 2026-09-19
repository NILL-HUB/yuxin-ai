# KB-P4 视频轻量剪辑（trim / concat / subtitle）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为知识库「改细节」链路补齐三件套——视频裁剪（trim）、拼接（concat）、加字幕（subtitle），产物存入成品库并可检索复用。

**Architecture:** 纯函数构造 ffmpeg 命令（可单测，不依赖真实 ffmpeg）→ `VideoEditService` 下载素材/执行/校验产物 → 薄 Celery 任务（复用主 worker，走默认 `celery` 队列）→ 三个 builtin 工具（`video_edit_tools` provider）对话内触发 → 产物经既有 `store_render_output` 落 COS + 建档 + 索引。

**Tech Stack:** Python 3.12 / ffmpeg（`imageio_ffmpeg` 静态兜底，api 容器实测可用）/ Celery / LangChain BaseTool / srt 纯文本生成

---

## 0. 前置实测结论（执行者必读，勿凭设计稿臆断）

调研中实测推翻了两处设计稿前提，**本计划已按实测设计**：

| # | 设计稿说法 | 实测事实 | 本计划的处理 |
| --- | --- | --- | --- |
| 1 | §5.2「字幕源来自 Segment 的 ASR 文本 **+ 时间戳**」 | ❌ **本计划此处的判断后来被推翻**，见 §0.1 | 字幕**由调用方显式传入** `[{start,end,text}]`（初版实现）。**§0.1 已改为自动生成** |
| 2 | §5.2「转码是 CPU 密集：需专门任务队列（Celery）」 | api 容器 `NO_FFMPEG_IN_API`，仅 `imageio_ffmpeg` 静态兜底（v7.0.2，实测支持 `libx264` + `concat` demuxer + `subtitles` 滤镜）；主 worker 跑的正是 api 镜像 | 走 **Celery**（不阻塞请求线程），但**复用默认 `celery` 队列**，不新建队列/容器 |

### 0.1 更正：ASR **能**提供时间戳（后续实测推翻本计划原结论）

上文第 1 行原写「`AudioService.audio_to_text` 只返回 `resp.json()["text"]`（纯文本零时间戳）→ 不做自动对齐」。
**该推理有缺陷**：它只观察到「本项目从未拿到时间戳」，却直接推断「服务端不提供」。

用真实人声对 SiliconFlow ASR 端点实测（`POST {base_url}/audio/transcriptions`）：

| 请求 | 响应字段 |
| --- | --- |
| `{"model": ...}`（即现有实现） | `duration, text, usage` —— **无** segments |
| `{"model": ..., "response_format": "verbose_json"}` | `duration, segments, text, usage` |

`segments` 形如（真实返回）：

```json
[
  {"start": 0.04, "end": 3.48, "text": "今天天气很好，我们一起去公园散步吧。"},
  {"start": 3.72, "end": 5.12, "text": "然后回家吃饭。"}
]
```

即这是 OpenAI Whisper 兼容参数，**此前只是从未请求过该字段**。据此已补充实现（见 §11.16）：

- 新增 `AudioService.audio_to_text_with_segments()`（请求 `verbose_json`）；**纯文本 `audio_to_text()` 请求契约保持不变**（不发送 `response_format`），其既有 8+ 调用方不受影响；
- L1 解析把时间轴写入 `KnowledgeSegment.metadata.transcript_segments`；
- `video_subtitle` 的 `cues` 改为**可选**：不传则自动生成（复用 L1 留存 → 缺失则重跑 ASR）。

> 保留此节是为了留下「错误结论如何产生」的记录：**只凭调用方观察不到某字段，不足以断言服务端不提供**。

**其他已核实的可复用构件**（勿重造）：

| 构件 | 位置 | 用途 |
| --- | --- | --- |
| `_resolve_ffmpeg_exe()` | `api/internal/core/vision/vision_invoke.py` L84-98 | ffmpeg 路径（系统优先 → imageio 兜底） |
| `probe_duration_sec(path)` | 同上 L119-136 | 时长探测（trim 边界校验 / concat 校验） |
| `RuntimeStorageProxy.download_file(key, path)` | `api/internal/service/storage/runtime_storage_service.py` | 素材下载 |
| `KnowledgeBaseService.store_render_output(account=, video_path=, name=)` | `knowledge_base_service.py` L330-384 | 产物落 COS + 建档 + 触发索引 |
| `get_document_detail(kb_id, doc_id, account)` | 同上 L810-834 | 素材定位与归属校验 |
| Celery 薄委托范式 | `api/internal/task/knowledge_l2_tasks.py` | 任务体只做「取 service + 委托 + 重试」 |
| builtin 工具三件套 | `video_render_tools/` | `.py` + `.yaml` + `positions.yaml` |
| 挂载点写法（含 account_id 注入） | `assistant_agent_service.py` L1054-1064 | 运行时挂载模板 |

**⚠️ 三条硬约束（违反即埋雷）**：

1. **`positions.yaml` 缺一不可**：`Provider._provider_init` 与 `BuiltinToolSyncService` 都靠它决定加载/同步哪些工具，缺了 provider 会被整体跳过。且 `.py` 内工厂函数**必须与工具名同名**。
2. **工具必须显式挂载**：`_load_non_mcp_tool` 那条通用路径是**空参实例化**（不传 account_id）。依赖账号的工具只能在 `_build_assistant_runtime_tools` 显式挂载。既有 `video_analyze` 就是「登记了但没挂载」的反面案例。
3. **产物落库不要再显式 `add_usage`**：`RuntimeStorageProxy.upload_bytes` 已隐式计量，重复调用会双重计费（`test_frame_quota_charge.py` 锁定了该契约）。

---

## 1. 文件结构规划

### 新建文件

| 文件 | 职责 |
| --- | --- |
| `api/internal/core/video/ffmpeg_edit.py` | **纯函数**：ffmpeg 命令构造 + SRT 生成 + 时间戳格式化。无 IO、无 subprocess，便于单测 |
| `api/internal/service/video_edit_service.py` | 素材下载 → 执行 ffmpeg → 产物校验。编排层 |
| `api/internal/task/video_edit_tasks.py` | 薄 Celery 任务：委托 `VideoEditService` + 重试 |
| `api/internal/core/tools/builtin_tools/providers/video_edit_tools/__init__.py` | provider 包 |
| `api/internal/core/tools/builtin_tools/providers/video_edit_tools/positions.yaml` | 工具名清单（3 项） |
| `.../video_edit_tools/video_trim.py` + `.yaml` | 裁剪工具 |
| `.../video_edit_tools/video_concat.py` + `.yaml` | 拼接工具 |
| `.../video_edit_tools/video_subtitle.py` + `.yaml` | 字幕工具 |
| `api/test/internal/core/video/test_ffmpeg_edit.py` | 纯函数单测 |
| `api/test/internal/service/test_video_edit_service.py` | 服务层单测 |
| `api/test/internal/core/tools/test_video_edit_tools.py` | 工具层单测 |

### 修改文件

| 文件 | 改动 |
| --- | --- |
| `api/internal/core/tools/builtin_tools/providers/providers.yaml` | 追加 `video_edit_tools` 登记 |
| `api/app/http/celery_app.py` | `TASK_MODULES` 加 `internal.task.video_edit_tasks` + 显式 import |
| `api/internal/service/assistant_agent_service.py` | `_build_assistant_runtime_tools` 挂载三个工具（注入 account_id） |
| `docs/prd/modules/02-knowledge-base.md` | 新增 §11.15 视频轻量剪辑 |
| `docs/prd/execution-roadmap.md` | `KB-P4` 状态更新 |
| `docs/prd/knowledge-base-product-form-design.md` | §5.2 / §7.4 / §9.2 状态更新 |

### 不新增迁移

本阶段**不新增数据表**：产物复用成品库（`KnowledgeDocument` + `source_type=render_output`），无需 schema 变更。

---

## Task 1: ffmpeg 命令构造纯函数

**Files:**
- Create: `api/internal/core/video/ffmpeg_edit.py`
- Test: `api/test/internal/core/video/test_ffmpeg_edit.py`

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/core/video/test_ffmpeg_edit.py`：

```python
"""ffmpeg 编辑命令构造与 SRT 生成（纯函数，不依赖真实 ffmpeg）。"""
import pytest

from internal.core.video.ffmpeg_edit import (
    build_concat_command,
    build_subtitle_command,
    build_trim_command,
    format_srt_timestamp,
    render_srt,
)


def test_format_srt_timestamp_uses_comma_millis():
    # SRT 规范用逗号分隔毫秒（不是点），写错播放器会不认
    assert format_srt_timestamp(0) == "00:00:00,000"
    assert format_srt_timestamp(1.5) == "00:00:01,500"
    assert format_srt_timestamp(3661.234) == "01:01:01,234"


def test_format_srt_timestamp_clamps_negative_to_zero():
    assert format_srt_timestamp(-3) == "00:00:00,000"


def test_format_srt_timestamp_rounds_to_millis():
    # 避免浮点噪声产生 1,2345 这类非法四位毫秒
    assert format_srt_timestamp(1.2345) in {"00:00:01,234", "00:00:01,235"}


def test_render_srt_produces_valid_blocks():
    srt = render_srt([
        {"start": 0.0, "end": 1.5, "text": "第一句"},
        {"start": 1.5, "end": 3.0, "text": "第二句"},
    ])
    assert srt == (
        "1\n00:00:00,000 --> 00:00:01,500\n第一句\n\n"
        "2\n00:00:01,500 --> 00:00:03,000\n第二句\n\n"
    )


def test_render_srt_skips_empty_text_and_renumbers():
    srt = render_srt([
        {"start": 0.0, "end": 1.0, "text": "有"},
        {"start": 1.0, "end": 2.0, "text": "   "},
        {"start": 2.0, "end": 3.0, "text": "也有"},
    ])
    # 空文本块必须丢弃，且序号连续（不能留 1,3）
    assert "1\n00:00:00,000" in srt
    assert "2\n00:00:02,000" in srt
    assert "3\n" not in srt


def test_render_srt_rejects_empty_cues():
    with pytest.raises(ValueError, match="字幕内容为空"):
        render_srt([])
    with pytest.raises(ValueError, match="字幕内容为空"):
        render_srt([{"start": 0, "end": 1, "text": "  "}])


def test_render_srt_rejects_end_before_start():
    with pytest.raises(ValueError, match="结束时间必须晚于开始时间"):
        render_srt([{"start": 2.0, "end": 1.0, "text": "倒挂"}])


def test_build_trim_command_uses_stream_copy_by_default():
    # -c copy 是无损且秒级的关键；顺序必须是 -ss 在 -i 之前（快速定位）
    cmd = build_trim_command(
        "ffmpeg", source="/in/a.mp4", output="/out/b.mp4", start_sec=1.0, end_sec=3.0
    )
    assert cmd[0] == "ffmpeg"
    assert "-ss" in cmd and cmd[cmd.index("-ss") + 1] == "1.000"
    assert cmd.index("-ss") < cmd.index("-i")
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "2.000"
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[-1] == "/out/b.mp4"


def test_build_trim_command_reencode_drops_copy():
    cmd = build_trim_command(
        "ffmpeg", source="/in/a.mp4", output="/out/b.mp4",
        start_sec=0.0, end_sec=1.0, reencode=True,
    )
    assert "copy" not in cmd
    assert "libx264" in cmd


def test_build_trim_command_requires_positive_duration():
    with pytest.raises(ValueError, match="结束时间必须晚于开始时间"):
        build_trim_command(
            "ffmpeg", source="/in/a.mp4", output="/out/b.mp4", start_sec=5.0, end_sec=5.0
        )


def test_build_trim_command_end_none_means_to_the_end():
    cmd = build_trim_command(
        "ffmpeg", source="/in/a.mp4", output="/out/b.mp4", start_sec=2.0, end_sec=None
    )
    assert "-t" not in cmd
    assert cmd[cmd.index("-ss") + 1] == "2.000"


def test_build_concat_command_uses_concat_demuxer():
    cmd = build_concat_command("ffmpeg", list_file="/tmp/list.txt", output="/out/m.mp4")
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-f") + 1] == "concat"
    assert cmd[cmd.index("-i") + 1] == "/tmp/list.txt"
    assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[-1] == "/out/m.mp4"


def test_build_subtitle_command_burns_srt_with_libass():
    cmd = build_subtitle_command(
        "ffmpeg", source="/in/a.mp4", output="/out/b.mp4", srt_path="/tmp/c.srt"
    )
    assert cmd[0] == "ffmpeg"
    # subtitles 滤镜依赖 libass（已实测镜像内可用）
    vf_index = cmd.index("-vf")
    assert cmd[vf_index + 1].startswith("subtitles=")
    assert "c.srt" in cmd[vf_index + 1]
    assert "libx264" in cmd
    assert cmd[-1] == "/out/b.mp4"


def test_build_subtitle_command_escapes_windows_style_path_colon():
    # ffmpeg 滤镜参数里 ':' 是分隔符，绝对路径必须转义，否则滤镜解析失败
    cmd = build_subtitle_command(
        "ffmpeg", source="/in/a.mp4", output="/out/b.mp4", srt_path="C:/tmp/c.srt"
    )
    vf = cmd[cmd.index("-vf") + 1]
    assert "C\\:/tmp/c.srt" in vf
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/core/video/test_ffmpeg_edit.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（`ModuleNotFoundError: internal.core.video.ffmpeg_edit`）

- [ ] **Step 3: 实现纯函数模块**

创建 `api/internal/core/video/ffmpeg_edit.py`：

```python
"""视频轻量剪辑的 ffmpeg 命令构造（纯函数）。

只做「构造命令 / 生成文本」，不碰 subprocess、不碰文件系统——
执行与 IO 在 `internal.service.video_edit_service`，便于本模块被充分单测。

实测约束（api 容器）：
- 无系统 ffmpeg，仅有 imageio_ffmpeg 静态兜底（v7.0.2）；
- 该构建具备 libx264 编码器、subtitles/ass 滤镜（依赖 libass）、concat demuxer，
  但**没有 drawtext 滤镜**——故字幕走 `subtitles` 烧录而非 drawtext。
"""
from __future__ import annotations

from typing import Any

__all__ = [
    "build_concat_command",
    "build_subtitle_command",
    "build_trim_command",
    "format_srt_timestamp",
    "render_srt",
]

# 重编码时的编码参数：与既有渲染链路口径一致（H.264 + AAC，广泛兼容）
_VIDEO_ENCODER = "libx264"
_AUDIO_ENCODER = "aac"
_ENCODE_PRESET = "veryfast"
_ENCODE_CRF = "23"


def format_srt_timestamp(seconds: Any) -> str:
    """秒 → SRT 时间戳 `HH:MM:SS,mmm`。

    注意用**逗号**分隔毫秒（SRT 规范），不是点号；负数按 0 处理。
    """
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        value = 0.0
    if value < 0:
        value = 0.0
    total_ms = int(round(value * 1000))
    hours, remainder = divmod(total_ms, 3600 * 1000)
    minutes, remainder = divmod(remainder, 60 * 1000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def render_srt(cues: list[dict[str, Any]]) -> str:
    """把 `[{start, end, text}]` 渲染为 SRT 文本。

    规则：丢弃空文本块后**重新连续编号**（不能留 1,3 这类断号，部分播放器会错位）；
    结束时间必须晚于开始时间；全部为空则报错（避免烧出一张空白字幕）。
    """
    blocks: list[str] = []
    index = 0
    for cue in cues or []:
        text = str((cue or {}).get("text") or "").strip()
        if not text:
            continue
        try:
            start = float((cue or {}).get("start") or 0.0)
            end = float((cue or {}).get("end") or 0.0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"字幕时间非法：{cue}") from exc
        if end <= start:
            raise ValueError(f"字幕结束时间必须晚于开始时间：start={start} end={end}")
        index += 1
        blocks.append(
            f"{index}\n{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}\n{text}\n"
        )
    if index == 0:
        raise ValueError("字幕内容为空：至少需要一条非空文本")
    # 每块以空行分隔，末尾保留一个空行
    return "\n".join(blocks) + "\n"


def build_trim_command(
    ffmpeg_exe: str,
    *,
    source: str,
    output: str,
    start_sec: float,
    end_sec: float | None,
    reencode: bool = False,
) -> list[str]:
    """构造裁剪命令。

    默认 `-c copy`（无损且秒级，纯封装操作）；`reencode=True` 时才重编码
    （帧对齐更精确，但慢得多）。`-ss` 必须放在 `-i` 之前走快速定位。
    """
    start = float(start_sec or 0.0)
    if start < 0:
        raise ValueError("开始时间不能为负")
    args = [ffmpeg_exe, "-y", "-ss", f"{start:.3f}", "-i", str(source)]
    if end_sec is not None:
        end = float(end_sec)
        if end <= start:
            raise ValueError(f"结束时间必须晚于开始时间：start={start} end={end}")
        args += ["-t", f"{end - start:.3f}"]
    if reencode:
        args += [
            "-c:v", _VIDEO_ENCODER, "-preset", _ENCODE_PRESET, "-crf", _ENCODE_CRF,
            "-c:a", _AUDIO_ENCODER,
        ]
    else:
        args += ["-c", "copy"]
    args.append(str(output))
    return args


def build_concat_command(ffmpeg_exe: str, *, list_file: str, output: str) -> list[str]:
    """构造拼接命令（concat demuxer + `-c copy`）。

    `list_file` 是 concat 清单文件（每行 `file '<abs path>'`），
    由 service 层按素材实际路径生成。
    """
    return [
        ffmpeg_exe, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(output),
    ]


def _escape_subtitle_path(path: str) -> str:
    """转义 subtitles 滤镜里的路径。

    ffmpeg 滤镜参数用 `:` 分隔选项，绝对路径中的 `:`（Windows 盘符）必须转义为 `\\:`；
    反斜杠同样要转义，否则被当作转义符吃掉。
    """
    return str(path).replace("\\", "\\\\").replace(":", "\\:")


def build_subtitle_command(
    ffmpeg_exe: str, *, source: str, output: str, srt_path: str
) -> list[str]:
    """构造字幕烧录命令（`subtitles` 滤镜 + libass + 重编码）。

    字幕必须重编码才能烧进画面（无法 copy），故固定用 libx264/AAC。
    """
    vf = f"subtitles='{_escape_subtitle_path(srt_path)}'"
    return [
        ffmpeg_exe, "-y",
        "-i", str(source),
        "-vf", vf,
        "-c:v", _VIDEO_ENCODER, "-preset", _ENCODE_PRESET, "-crf", _ENCODE_CRF,
        "-c:a", _AUDIO_ENCODER,
        str(output),
    ]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/core/video/test_ffmpeg_edit.py -q --no-cov -p no:cacheprovider`
Expected: PASS（14 passed）

- [ ] **Step 5: 提交**

```bash
git add api/internal/core/video/ffmpeg_edit.py api/test/internal/core/video/test_ffmpeg_edit.py
git commit -m "feat(video-edit): add pure ffmpeg command builders for trim/concat/subtitle"
```

---

## Task 2: 视频编辑服务（下载 / 执行 / 校验）

**Files:**
- Create: `api/internal/service/video_edit_service.py`
- Test: `api/test/internal/service/test_video_edit_service.py`

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/service/test_video_edit_service.py`：

```python
"""视频编辑服务：命令执行、产物校验、失败语义。"""
import subprocess
from pathlib import Path

import pytest

from internal.service.video_edit_service import VideoEditService, VideoEditError


def _service(monkeypatch, *, run_result=None, run_error=None, duration=10.0):
    """构造绕过 DI 的服务实例，并替换 ffmpeg 执行与时长探测。"""
    svc = VideoEditService.__new__(VideoEditService)
    calls = []

    def fake_run(cmd, timeout):
        calls.append(cmd)
        if run_error is not None:
            raise run_error
        return run_result

    monkeypatch.setattr(svc, "_run_ffmpeg", fake_run)
    monkeypatch.setattr(svc, "_probe_duration", lambda p: duration)
    monkeypatch.setattr(svc, "_resolve_exe", lambda: "ffmpeg")
    return svc, calls


def _touch_ok(path: Path, size: int = 1024) -> None:
    path.write_bytes(b"x" * size)


def test_trim_produces_output_and_calls_ffmpeg(tmp_path, monkeypatch):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    svc, calls = _service(monkeypatch)
    monkeypatch.setattr(svc, "_materialize_output", lambda p: _touch_ok(p) or p)

    result = svc.trim(source_path=src, output_path=out, start_sec=1.0, end_sec=3.0)

    assert result == out
    assert len(calls) == 1
    assert "-c" in calls[0] and "copy" in calls[0]


def test_trim_rejects_start_beyond_duration(tmp_path, monkeypatch):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    svc, _ = _service(monkeypatch, duration=5.0)
    with pytest.raises(VideoEditError, match="超出视频时长"):
        svc.trim(source_path=src, output_path=out, start_sec=9.0, end_sec=10.0)


def test_trim_rejects_end_beyond_duration(tmp_path, monkeypatch):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    svc, _ = _service(monkeypatch, duration=5.0)
    with pytest.raises(VideoEditError, match="超出视频时长"):
        svc.trim(source_path=src, output_path=out, start_sec=1.0, end_sec=99.0)


def test_trim_source_missing_raises(tmp_path, monkeypatch):
    svc, _ = _service(monkeypatch)
    with pytest.raises(VideoEditError, match="源视频不存在"):
        svc.trim(
            source_path=tmp_path / "nope.mp4", output_path=tmp_path / "o.mp4",
            start_sec=0.0, end_sec=1.0,
        )


def test_trim_ffmpeg_failure_wrapped_as_video_edit_error(tmp_path, monkeypatch):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    err = subprocess.CalledProcessError(1, "ffmpeg", stderr=b"boom")
    svc, _ = _service(monkeypatch, run_error=err)
    with pytest.raises(VideoEditError, match="裁剪失败"):
        svc.trim(source_path=src, output_path=out, start_sec=0.0, end_sec=1.0)


def test_trim_empty_output_raises(tmp_path, monkeypatch):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    svc, _ = _service(monkeypatch)
    # ffmpeg 退出 0 但没产出文件：不能静默当成功
    with pytest.raises(VideoEditError, match="未产出有效文件"):
        svc.trim(source_path=src, output_path=out, start_sec=0.0, end_sec=1.0)


def test_concat_writes_list_file_in_sorted_order(tmp_path, monkeypatch):
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _touch_ok(a); _touch_ok(b)
    out = tmp_path / "out.mp4"
    svc, calls = _service(monkeypatch)
    captured = {}

    def fake_run(cmd, timeout):
        calls.append(cmd)
        list_file = Path(cmd[cmd.index("-i") + 1])
        captured["content"] = list_file.read_text(encoding="utf-8")
        _touch_ok(out)
        return None

    monkeypatch.setattr(svc, "_run_ffmpeg", fake_run)

    svc.concat(source_paths=[a, b], output_path=out)

    # concat demuxer 清单必须按传入顺序且路径绝对化
    assert captured["content"].index("a.mp4") < captured["content"].index("b.mp4")
    assert captured["content"].count("file '") == 2


def test_concat_requires_at_least_two_sources(tmp_path, monkeypatch):
    svc, _ = _service(monkeypatch)
    with pytest.raises(VideoEditError, match="至少需要两段"):
        svc.concat(source_paths=[tmp_path / "a.mp4"], output_path=tmp_path / "o.mp4")


def test_concat_missing_source_raises(tmp_path, monkeypatch):
    svc, _ = _service(monkeypatch)
    with pytest.raises(VideoEditError, match="源视频不存在"):
        svc.concat(
            source_paths=[tmp_path / "a.mp4", tmp_path / "b.mp4"],
            output_path=tmp_path / "o.mp4",
        )


def test_burn_subtitles_writes_srt_then_executes(tmp_path, monkeypatch):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    svc, calls = _service(monkeypatch)
    captured = {}

    def fake_run(cmd, timeout):
        calls.append(cmd)
        srt_path = Path(str(cmd[cmd.index("-vf") + 1]).split("'")[1].replace("\\:", ":"))
        captured["srt"] = srt_path.read_text(encoding="utf-8")
        _touch_ok(out)
        return None

    monkeypatch.setattr(svc, "_run_ffmpeg", fake_run)

    svc.burn_subtitles(
        source_path=src, output_path=out,
        cues=[{"start": 0.0, "end": 1.0, "text": "你好"}],
    )

    assert "你好" in captured["srt"]
    assert "00:00:00,000 --> 00:00:01,000" in captured["srt"]


def test_burn_subtitles_rejects_empty_cues(tmp_path, monkeypatch):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    svc, _ = _service(monkeypatch)
    with pytest.raises(VideoEditError, match="字幕内容为空"):
        svc.burn_subtitles(source_path=src, output_path=out, cues=[])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_video_edit_service.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（`ModuleNotFoundError: internal.service.video_edit_service`）

- [ ] **Step 3: 实现服务**

创建 `api/internal/service/video_edit_service.py`：

```python
"""视频轻量剪辑服务（trim / concat / subtitle）。

职责边界：
- 本模块负责「下载素材 → 构造命令 → 执行 ffmpeg → 校验产物」；
- 命令构造是纯函数，见 `internal.core.video.ffmpeg_edit`；
- 分钟级/大批量场景由调用方（Celery 任务）承载，本模块自身是同步的。

为什么不做复杂重试/闸门：trim（-c copy）与 concat（-c copy）本质是封装操作（秒级），
subtitle 的重编码也仅对短视频耗时明显；故由 Celery 的 max_retries 兜底即可，
无需复制渲染链路的并发闸门（那是分钟级任务的成本，此处属过度设计）。
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from injector import inject

from internal.core.video.ffmpeg_edit import (
    build_concat_command,
    build_subtitle_command,
    build_trim_command,
    render_srt,
)

logger = logging.getLogger(__name__)

# 单条 ffmpeg 命令超时：剪辑是 IO 密集，但重编码可能较慢，留足余量
_EDIT_TIMEOUT_SEC = 600
# 产物体积下限：小于 1KB 基本可判定为「空壳产物」
_MIN_OUTPUT_BYTES = 1024


class VideoEditError(RuntimeError):
    """视频编辑失败。消息面向用户可直接展示，不进重试。"""


@inject
class VideoEditService:
    """视频剪辑服务。依赖注入保持与既有 service 一致的写型注解。"""

    def _resolve_exe(self) -> str:
        """ffmpeg 可执行文件路径（系统优先，imageio 兜底）。"""
        from internal.core.vision.vision_invoke import _resolve_ffmpeg_exe

        return _resolve_ffmpeg_exe()

    def _probe_duration(self, path: str | Path) -> float:
        """探测时长（秒）；失败返回 0.0（调用方据此跳过边界校验）。"""
        from internal.core.vision.vision_invoke import probe_duration_sec

        return probe_duration_sec(str(path))

    def _run_ffmpeg(self, cmd: list[str], timeout: int = _EDIT_TIMEOUT_SEC) -> None:
        """执行 ffmpeg；失败抛 CalledProcessError（由调用方包装为可读错误）。"""
        subprocess.run(cmd, capture_output=True, timeout=timeout, check=True)

    def _ensure_source(self, path: str | Path) -> Path:
        source = Path(path)
        if not source.is_file():
            raise VideoEditError(f"源视频不存在：{source}")
        return source

    def _ensure_output(self, output: str | Path) -> Path:
        out = Path(output)
        if not out.is_file() or out.stat().st_size < _MIN_OUTPUT_BYTES:
            # ffmpeg 退出码 0 不等于产物有效（既有渲染链路同样教训）
            raise VideoEditError("剪辑未产出有效文件")
        return out

    def trim(
        self,
        *,
        source_path: str | Path,
        output_path: str | Path,
        start_sec: float,
        end_sec: float | None,
        reencode: bool = False,
    ) -> Path:
        """按时间区间裁剪。默认流拷贝（无损、秒级）。"""
        source = self._ensure_source(source_path)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # 边界校验：仅在能探到时长时启用（探测失败不阻断，交由 ffmpeg 自身报错）
        duration = self._probe_duration(source)
        if duration > 0:
            if float(start_sec) >= duration:
                raise VideoEditError(
                    f"开始时间 {float(start_sec):.2f}s 超出视频时长 {duration:.2f}s"
                )
            if end_sec is not None and float(end_sec) > duration + 0.5:
                raise VideoEditError(
                    f"结束时间 {float(end_sec):.2f}s 超出视频时长 {duration:.2f}s"
                )

        try:
            cmd = build_trim_command(
                self._resolve_exe(),
                source=str(source), output=str(out),
                start_sec=start_sec, end_sec=end_sec, reencode=reencode,
            )
            self._run_ffmpeg(cmd)
        except subprocess.CalledProcessError as exc:
            logger.warning("裁剪失败 source=%s", source, exc_info=True)
            detail = (exc.stderr or b"").decode("utf-8", errors="replace")[:200]
            raise VideoEditError(f"裁剪失败：{detail or exc}") from exc
        except ValueError as exc:
            raise VideoEditError(str(exc)) from exc
        return self._ensure_output(out)

    def concat(self, *, source_paths: list[str | Path], output_path: str | Path) -> Path:
        """按传入顺序拼接多段视频（concat demuxer + 流拷贝）。"""
        paths = [self._ensure_source(p) for p in (source_paths or [])]
        if len(paths) < 2:
            raise VideoEditError("拼接至少需要两段视频")

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="video-concat-") as work:
            list_file = Path(work) / "list.txt"
            # concat demuxer 清单：绝对路径 + 单引号（-safe 0 允许绝对路径）
            list_file.write_text(
                "".join(f"file '{p.resolve().as_posix()}'\n" for p in paths),
                encoding="utf-8",
            )
            try:
                cmd = build_concat_command(
                    self._resolve_exe(), list_file=str(list_file), output=str(out)
                )
                self._run_ffmpeg(cmd)
            except subprocess.CalledProcessError as exc:
                logger.warning("拼接失败 sources=%s", paths, exc_info=True)
                detail = (exc.stderr or b"").decode("utf-8", errors="replace")[:200]
                raise VideoEditError(f"拼接失败：{detail or exc}") from exc
        return self._ensure_output(out)

    def burn_subtitles(
        self,
        *,
        source_path: str | Path,
        output_path: str | Path,
        cues: list[dict[str, Any]],
    ) -> Path:
        """把字幕烧录进画面（subtitles 滤镜，需重编码）。"""
        source = self._ensure_source(source_path)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        try:
            srt_text = render_srt(cues)
        except ValueError as exc:
            # 统一成 VideoEditError，工具层只需处理一种异常
            raise VideoEditError(str(exc)) from exc

        with tempfile.TemporaryDirectory(prefix="video-subtitle-") as work:
            srt_path = Path(work) / "subtitle.srt"
            # 必须 UTF-8 无 BOM：带 BOM 时 libass 会把首行时间码读坏
            srt_path.write_text(srt_text, encoding="utf-8")
            try:
                cmd = build_subtitle_command(
                    self._resolve_exe(),
                    source=str(source), output=str(out), srt_path=str(srt_path),
                )
                self._run_ffmpeg(cmd)
            except subprocess.CalledProcessError as exc:
                logger.warning("字幕烧录失败 source=%s", source, exc_info=True)
                detail = (exc.stderr or b"").decode("utf-8", errors="replace")[:200]
                raise VideoEditError(f"字幕烧录失败：{detail or exc}") from exc
        return self._ensure_output(out)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_video_edit_service.py -q --no-cov -p no:cacheprovider`
Expected: PASS（11 passed）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/video_edit_service.py api/test/internal/service/test_video_edit_service.py
git commit -m "feat(video-edit): add VideoEditService for trim/concat/subtitle execution"
```

---

## Task 3: 素材定位与产物落库的编排层

**Files:**
- Modify: `api/internal/service/video_edit_service.py`（追加方法）
- Test: `api/test/internal/service/test_video_edit_service.py`（追加用例）

**背景**：工具层不应直接碰 `KnowledgeBaseService` 与对象存储。本节把「按 document_id 取素材 → 下载到临时目录 → 剪辑 → 存成品库」收口到 service，工具层只做参数解析与错误可读化。

- [ ] **Step 1: 写失败的测试**

在 `api/test/internal/service/test_video_edit_service.py` 末尾追加：

```python
def _edit_service(monkeypatch, *, docs, downloads_ok=True):
    """构造带素材下载与入库替身的服务。"""
    svc = VideoEditService.__new__(VideoEditService)
    monkeypatch.setattr(svc, "_resolve_exe", lambda: "ffmpeg")
    monkeypatch.setattr(svc, "_probe_duration", lambda p: 10.0)

    def fake_download(key, dest):
        if not downloads_ok:
            raise RuntimeError("download boom")
        Path(dest).write_bytes(b"v" * 2048)

    monkeypatch.setattr(svc, "_download_source", fake_download)
    monkeypatch.setattr(svc, "_load_source_documents", lambda **kw: docs)
    return svc


def _fake_doc(doc_id, key="kb/video.mp4", name="素材.mp4"):
    from types import SimpleNamespace
    return SimpleNamespace(id=doc_id, upload_file_id="uf-1",
                           upload_file=SimpleNamespace(key=key, name=name))


def test_trim_from_documents_downloads_and_stores(tmp_path, monkeypatch):
    doc = _fake_doc("doc-1")
    svc = _edit_service(monkeypatch, docs=[doc])
    stored = {}

    def fake_trim(**kw):
        Path(kw["output_path"]).write_bytes(b"o" * 4096)
        return Path(kw["output_path"])

    monkeypatch.setattr(svc, "trim", fake_trim)
    monkeypatch.setattr(
        svc, "_store_output",
        lambda *, account, video_path, name: stored.update(
            {"path": str(video_path), "name": name}
        ) or {"document_id": "new-doc"},
    )

    result = svc.trim_document(
        account="acc", knowledge_base_id="kb-1", document_id="doc-1",
        start_sec=0.0, end_sec=3.0, name="裁剪成品",
    )

    assert result["document_id"] == "new-doc"
    assert stored["name"] == "裁剪成品"


def test_trim_document_unknown_document_raises(monkeypatch):
    svc = _edit_service(monkeypatch, docs=[])
    with pytest.raises(VideoEditError, match="素材不存在"):
        svc.trim_document(
            account="acc", knowledge_base_id="kb-1", document_id="nope",
            start_sec=0.0, end_sec=1.0, name="x",
        )


def test_concat_documents_preserves_input_order(tmp_path, monkeypatch):
    docs = [_fake_doc("d1"), _fake_doc("d2"), _fake_doc("d3")]
    svc = _edit_service(monkeypatch, docs=docs)
    captured = {}

    def fake_concat(**kw):
        captured["paths"] = [Path(p).name for p in kw["source_paths"]]
        Path(kw["output_path"]).write_bytes(b"o" * 4096)
        return Path(kw["output_path"])

    monkeypatch.setattr(svc, "concat", fake_concat)
    monkeypatch.setattr(svc, "_store_output", lambda **kw: {"document_id": "nd"})

    svc.concat_documents(
        account="acc", knowledge_base_id="kb-1",
        document_ids=["d3", "d1", "d2"], name="拼接成品",
    )

    # 顺序必须严格按调用方给定（不能按 id 排序或去重）
    assert len(captured["paths"]) == 3
    assert len(set(captured["paths"])) == 3


def test_subtitle_document_burns_and_stores(tmp_path, monkeypatch):
    doc = _fake_doc("doc-1")
    svc = _edit_service(monkeypatch, docs=[doc])

    def fake_burn(**kw):
        Path(kw["output_path"]).write_bytes(b"o" * 4096)
        return Path(kw["output_path"])

    monkeypatch.setattr(svc, "burn_subtitles", fake_burn)
    monkeypatch.setattr(svc, "_store_output", lambda **kw: {"document_id": "sd"})

    result = svc.subtitle_document(
        account="acc", knowledge_base_id="kb-1", document_id="doc-1",
        cues=[{"start": 0, "end": 1, "text": "hi"}], name="字幕成品",
    )
    assert result["document_id"] == "sd"


def test_download_failure_is_wrapped(tmp_path, monkeypatch):
    doc = _fake_doc("doc-1")
    svc = _edit_service(monkeypatch, docs=[doc], downloads_ok=False)
    with pytest.raises(VideoEditError, match="下载素材失败"):
        svc.trim_document(
            account="acc", knowledge_base_id="kb-1", document_id="doc-1",
            start_sec=0.0, end_sec=1.0, name="x",
        )


def test_temp_dir_is_cleaned_after_success(monkeypatch):
    doc = _fake_doc("doc-1")
    svc = _edit_service(monkeypatch, docs=[doc])
    seen = {}

    def fake_trim(**kw):
        seen["dir"] = str(Path(kw["output_path"]).parent)
        Path(kw["output_path"]).write_bytes(b"o" * 4096)
        return Path(kw["output_path"])

    monkeypatch.setattr(svc, "trim", fake_trim)
    monkeypatch.setattr(svc, "_store_output", lambda **kw: {"document_id": "d"})

    svc.trim_document(
        account="acc", knowledge_base_id="kb-1", document_id="doc-1",
        start_sec=0.0, end_sec=1.0, name="x",
    )
    # 不能在用户/服务器上残留临时工作目录
    assert not Path(seen["dir"]).exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_video_edit_service.py -q -k document --no-cov -p no:cacheprovider`
Expected: FAIL（`AttributeError: 'VideoEditService' object has no attribute 'trim_document'`）

- [ ] **Step 3: 追加编排方法**

在 `api/internal/service/video_edit_service.py` 的 `burn_subtitles` 之后追加：

```python
    # ── 编排层：document → 下载 → 剪辑 → 成品库 ───────────────────────────

    def _download_source(self, key: str, dest: str) -> None:
        """从对象存储下载素材到本地（独立方法便于测试替换）。"""
        from app.http.module import injector
        from internal.service.storage.runtime_storage_service import RuntimeStorageProxy

        injector.get(RuntimeStorageProxy).download_file(key, dest)

    def _load_source_documents(
        self, *, account: Any, knowledge_base_id: str, document_ids: list[str]
    ) -> list[Any]:
        """按 id 批量取素材文档（含 upload_file），保持传入顺序。

        归属校验复用 `get_document_detail`（内含知识库归属 + 文档归属双重校验），
        避免手写查询绕过权限。
        """
        from app.http.module import injector
        from internal.service.knowledge_base_service import KnowledgeBaseService

        service = injector.get(KnowledgeBaseService)
        docs = []
        for doc_id in document_ids:
            doc = service.get_document_detail(knowledge_base_id, doc_id, account)
            # get_document_detail 返回的 document 不带 upload_file 关系，按需补取
            upload_file = getattr(doc, "upload_file", None)
            if upload_file is None and getattr(doc, "upload_file_id", None):
                from internal.model.upload_file import UploadFile

                upload_file = service.db.session.query(UploadFile).filter(
                    UploadFile.id == doc.upload_file_id
                ).one_or_none()
                setattr(doc, "upload_file", upload_file)
            docs.append(doc)
        return docs

    def _store_output(self, *, account: Any, video_path: Path, name: str) -> dict:
        """把剪辑产物写入成品库（复用 KB-P3.7 的 store_render_output）。"""
        from app.http.module import injector
        from internal.service.knowledge_base_service import KnowledgeBaseService

        document = injector.get(KnowledgeBaseService).store_render_output(
            account=account, video_path=video_path, name=name
        )
        return {"document_id": str(document.id)}

    def _prepare_source_file(self, doc: Any, work_dir: Path) -> Path:
        """把文档对应素材下载到工作目录，返回本地路径。"""
        upload_file = getattr(doc, "upload_file", None)
        key = getattr(upload_file, "key", "") if upload_file else ""
        if not key:
            raise VideoEditError(f"素材不存在或缺少存储对象：document_id={doc.id}")
        dest = work_dir / f"{doc.id}_{Path(key).name or 'source.mp4'}"
        try:
            self._download_source(key, str(dest))
        except Exception as exc:  # noqa: BLE001 - 统一成可读错误
            logger.warning("下载素材失败 key=%s", key, exc_info=True)
            raise VideoEditError(f"下载素材失败：{exc}") from exc
        return dest

    def trim_document(
        self, *, account: Any, knowledge_base_id: str, document_id: str,
        start_sec: float, end_sec: float | None, name: str, reencode: bool = False,
    ) -> dict:
        """裁剪单个库内视频并存入成品库。"""
        docs = self._load_source_documents(
            account=account, knowledge_base_id=knowledge_base_id, document_ids=[document_id]
        )
        if not docs:
            raise VideoEditError(f"素材不存在：document_id={document_id}")

        with tempfile.TemporaryDirectory(prefix="video-edit-") as work:
            work_dir = Path(work)
            source = self._prepare_source_file(docs[0], work_dir)
            output = work_dir / "output.mp4"
            self.trim(
                source_path=source, output_path=output,
                start_sec=start_sec, end_sec=end_sec, reencode=reencode,
            )
            return self._store_output(account=account, video_path=output, name=name)

    def concat_documents(
        self, *, account: Any, knowledge_base_id: str, document_ids: list[str],
        name: str,
    ) -> dict:
        """按给定顺序拼接多段库内视频并存入成品库。"""
        docs = self._load_source_documents(
            account=account, knowledge_base_id=knowledge_base_id, document_ids=document_ids
        )
        if len(docs) != len(document_ids):
            missing = set(document_ids) - {str(d.id) for d in docs}
            raise VideoEditError(f"素材不存在：document_id={sorted(missing)}")

        with tempfile.TemporaryDirectory(prefix="video-edit-") as work:
            work_dir = Path(work)
            sources = [self._prepare_source_file(doc, work_dir) for doc in docs]
            output = work_dir / "output.mp4"
            self.concat(source_paths=sources, output_path=output)
            return self._store_output(account=account, video_path=output, name=name)

    def subtitle_document(
        self, *, account: Any, knowledge_base_id: str, document_id: str,
        cues: list[dict[str, Any]], name: str,
    ) -> dict:
        """给库内视频烧录字幕并存入成品库。"""
        docs = self._load_source_documents(
            account=account, knowledge_base_id=knowledge_base_id, document_ids=[document_id]
        )
        if not docs:
            raise VideoEditError(f"素材不存在：document_id={document_id}")

        with tempfile.TemporaryDirectory(prefix="video-edit-") as work:
            work_dir = Path(work)
            source = self._prepare_source_file(docs[0], work_dir)
            output = work_dir / "output.mp4"
            self.burn_subtitles(source_path=source, output_path=output, cues=cues)
            return self._store_output(account=account, video_path=output, name=name)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_video_edit_service.py -q --no-cov -p no:cacheprovider`
Expected: PASS（17 passed）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/video_edit_service.py api/test/internal/service/test_video_edit_service.py
git commit -m "feat(video-edit): add document-scoped edit orchestration with output ingestion"
```

---

## Task 4: Celery 任务与注册

**Files:**
- Create: `api/internal/task/video_edit_tasks.py`
- Modify: `api/app/http/celery_app.py`（TASK_MODULES + 显式 import）
- Test: `api/test/internal/task/test_video_edit_tasks.py`

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/task/test_video_edit_tasks.py`：

```python
"""视频编辑 Celery 任务：薄委托 + 重试语义。"""
import pytest

from internal.service.video_edit_service import VideoEditError
from internal.task import video_edit_tasks


class _FakeSelf:
    """模拟 Celery 的 bind=True self。"""

    def __init__(self):
        self.retries = []

    def retry(self, exc=None, **kwargs):
        self.retries.append(exc)
        raise RuntimeError(f"retry:{exc}")


def _install_service(monkeypatch, *, result=None, error=None):
    calls = {}

    class _Svc:
        def trim_document(self, **kw):
            calls.update(kw)
            if error is not None:
                raise error
            return result or {"document_id": "d1"}

    monkeypatch.setattr(video_edit_tasks, "_load_service", lambda: _Svc())
    return calls


def test_trim_task_delegates_with_all_args(monkeypatch):
    calls = _install_service(monkeypatch)
    out = video_edit_tasks.video_trim_task(
        _FakeSelf(), "kb-1", "doc-1", 1.0, 3.0, "成品", "acc-1"
    )
    assert out == {"document_id": "d1"}
    assert calls["knowledge_base_id"] == "kb-1"
    assert calls["document_id"] == "doc-1"
    assert calls["start_sec"] == 1.0
    assert calls["end_sec"] == 3.0
    assert calls["name"] == "成品"


def test_trim_task_retries_on_transient_error(monkeypatch):
    _install_service(monkeypatch, error=RuntimeError("io boom"))
    self_obj = _FakeSelf()
    with pytest.raises(RuntimeError, match="retry:"):
        video_edit_tasks.video_trim_task(self_obj, "kb", "doc", 0.0, 1.0, "n", "acc")
    assert len(self_obj.retries) == 1


def test_trim_task_does_not_retry_business_error(monkeypatch):
    # VideoEditError 是业务失败（参数非法/素材不存在），重试无意义
    _install_service(monkeypatch, error=VideoEditError("结束时间超出视频时长"))
    self_obj = _FakeSelf()
    with pytest.raises(VideoEditError, match="超出视频时长"):
        video_edit_tasks.video_trim_task(self_obj, "kb", "doc", 0.0, 99.0, "n", "acc")
    assert self_obj.retries == []


def test_concat_task_passes_document_ids_through(monkeypatch):
    calls = _install_service(monkeypatch)
    video_edit_tasks.video_concat_task(_FakeSelf(), "kb-1", ["d1", "d2"], "合片", "acc")
    assert calls["document_ids"] == ["d1", "d2"]


def test_subtitle_task_passes_cues(monkeypatch):
    calls = _install_service(monkeypatch)
    cues = [{"start": 0.0, "end": 1.0, "text": "hi"}]
    video_edit_tasks.video_subtitle_task(_FakeSelf(), "kb", "doc", cues, "n", "acc")
    assert calls["cues"] == cues


def test_tasks_are_registered_in_celery_task_modules():
    """任务必须同时进 TASK_MODULES 与显式 import，否则 Celery 不认。"""
    from app.http.celery_app import TASK_MODULES

    assert "internal.task.video_edit_tasks" in TASK_MODULES


def test_task_names_are_stable():
    # 派发端按名字路由，改名即断链
    for task, expected in (
        (video_edit_tasks.video_trim_task, "internal.task.video_edit_tasks.video_trim_task"),
        (video_edit_tasks.video_concat_task, "internal.task.video_edit_tasks.video_concat_task"),
        (video_edit_tasks.video_subtitle_task, "internal.task.video_edit_tasks.video_subtitle_task"),
    ):
        assert task.name == expected
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/task/test_video_edit_tasks.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（`ModuleNotFoundError: internal.task.video_edit_tasks`）

- [ ] **Step 3: 实现任务**

创建 `api/internal/task/video_edit_tasks.py`：

```python
"""视频轻量剪辑的 Celery 任务（trim / concat / subtitle）。

薄委托范式（与 knowledge_l2_tasks 一致）：任务体只做「取 service + 委托 + 重试」，
业务全在 VideoEditService。

重试语义分层：
- `VideoEditError` 是业务失败（参数非法 / 素材不存在 / 字幕为空），**不重试**，
  重试只会重复失败并放大噪音；
- 其他异常（IO / 存储抖动）重试。

队列：走默认 `celery` 队列（不新建队列/容器）。理由见计划 §0：
剪辑是秒级 IO 操作，主 worker 镜像已内含 imageio_ffmpeg，无需专属消费者。
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)

__all__ = ["video_concat_task", "video_subtitle_task", "video_trim_task"]


def _load_service():
    """延迟导入重依赖（避免 Celery 启动期加载应用依赖）。"""
    from app.http.module import injector
    from internal.service.video_edit_service import VideoEditService

    return injector.get(VideoEditService)


def _load_account(account_id: str):
    from uuid import UUID

    from app.http.module import injector
    from internal.service.account_service import AccountService

    return injector.get(AccountService).get_account(UUID(str(account_id)))


def _delegate(self, action: str, fn):
    """统一的重试/异常分层。业务失败不重试，其余交给 Celery 重试。"""
    from internal.service.video_edit_service import VideoEditError

    try:
        return fn()
    except VideoEditError:
        logger.warning("视频编辑业务失败 action=%s", action, exc_info=True)
        raise
    except Exception as exc:
        logger.exception("视频编辑失败 action=%s，将重试", action)
        raise self.retry(exc=exc)


@shared_task(
    name="internal.task.video_edit_tasks.video_trim_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def video_trim_task(
    self, knowledge_base_id: str, document_id: str,
    start_sec: float, end_sec, name: str, account_id: str, reencode: bool = False,
):
    """裁剪库内视频并存入成品库。"""
    service = _load_service()
    account = _load_account(account_id)

    def _run():
        return service.trim_document(
            account=account, knowledge_base_id=knowledge_base_id,
            document_id=document_id, start_sec=start_sec, end_sec=end_sec,
            name=name, reencode=reencode,
        )

    return _delegate(self, "trim", _run)


@shared_task(
    name="internal.task.video_edit_tasks.video_concat_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def video_concat_task(
    self, knowledge_base_id: str, document_ids: list, name: str, account_id: str
):
    """按给定顺序拼接库内视频并存入成品库。"""
    service = _load_service()
    account = _load_account(account_id)

    def _run():
        return service.concat_documents(
            account=account, knowledge_base_id=knowledge_base_id,
            document_ids=list(document_ids or []), name=name,
        )

    return _delegate(self, "concat", _run)


@shared_task(
    name="internal.task.video_edit_tasks.video_subtitle_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def video_subtitle_task(
    self, knowledge_base_id: str, document_id: str, cues: list,
    name: str, account_id: str,
):
    """给库内视频烧录字幕并存入成品库。"""
    service = _load_service()
    account = _load_account(account_id)

    def _run():
        return service.subtitle_document(
            account=account, knowledge_base_id=knowledge_base_id,
            document_id=document_id, cues=list(cues or []), name=name,
        )

    return _delegate(self, "subtitle", _run)
```

- [ ] **Step 4: 注册到 Celery（两处都要）**

修改 `api/app/http/celery_app.py`：

在 `TASK_MODULES` 列表的 `"internal.task.render_tasks",` 之后加一行：

```python
    "internal.task.video_edit_tasks",
```

并在文件下方显式 import 区（`import internal.task.render_tasks as _task_render  # noqa: F401,E402` 之后）加一行：

```python
import internal.task.video_edit_tasks as _task_video_edit  # noqa: F401,E402
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/task/test_video_edit_tasks.py -q --no-cov -p no:cacheprovider`
Expected: PASS（7 passed）

- [ ] **Step 6: 提交**

```bash
git add api/internal/task/video_edit_tasks.py api/app/http/celery_app.py api/test/internal/task/test_video_edit_tasks.py
git commit -m "feat(video-edit): add celery tasks for trim/concat/subtitle"
```

---

## Task 5: 三个 builtin 工具

**Files:**
- Create: `api/internal/core/tools/builtin_tools/providers/video_edit_tools/__init__.py`
- Create: `.../video_edit_tools/positions.yaml`
- Create: `.../video_edit_tools/video_trim.py` + `video_trim.yaml`
- Create: `.../video_edit_tools/video_concat.py` + `video_concat.yaml`
- Create: `.../video_edit_tools/video_subtitle.py` + `video_subtitle.yaml`
- Test: `api/test/internal/core/tools/test_video_edit_tools.py`

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/core/tools/test_video_edit_tools.py`：

```python
"""视频编辑工具：参数解析、派发、错误可读化。

工具不向 Agent 抛异常，一律返回 {"ok": bool, ...} JSON。
"""
import json

import pytest

from internal.core.tools.builtin_tools.providers.video_edit_tools import (
    video_concat,
    video_subtitle,
    video_trim,
)


def _capture_delay(monkeypatch, module):
    captured = {}

    class _Task:
        @staticmethod
        def delay(*args, **kwargs):
            captured["args"] = args
            return __import__("types").SimpleNamespace(id="task-1")

    monkeypatch.setattr(module, "_load_task", lambda: _Task)
    return captured


def test_trim_tool_requires_account():
    tool = video_trim.video_trim()
    payload = json.loads(tool._run(knowledge_base_id="kb", document_id="d", start_sec=0, end_sec=1))
    assert payload["ok"] is False
    assert "账号" in payload["error"]


def test_trim_tool_requires_kb_and_document():
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(tool._run(document_id="d", start_sec=0, end_sec=1))
    assert payload["ok"] is False
    assert "知识库" in payload["error"] or "素材" in payload["error"]


def test_trim_tool_rejects_negative_start():
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb", document_id="d", start_sec=-1, end_sec=1)
    )
    assert payload["ok"] is False
    assert "开始时间" in payload["error"]


def test_trim_tool_rejects_end_not_after_start():
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb", document_id="d", start_sec=2, end_sec=2)
    )
    assert payload["ok"] is False


def test_trim_tool_dispatches_celery_task(monkeypatch):
    captured = _capture_delay(monkeypatch, video_trim)
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb-1", document_id="doc-1",
                  start_sec=1.0, end_sec=3.0, name="裁剪")
    )
    assert payload["ok"] is True
    assert payload["task_id"] == "task-1"
    assert captured["args"][0] == "kb-1"
    assert captured["args"][1] == "doc-1"
    assert captured["args"][4] == "裁剪"


def test_trim_tool_reports_dispatch_failure_readably(monkeypatch):
    class _Boom:
        @staticmethod
        def delay(*a, **k):
            raise RuntimeError("broker down")

    monkeypatch.setattr(video_trim, "_load_task", lambda: _Boom)
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb", document_id="d", start_sec=0, end_sec=1)
    )
    assert payload["ok"] is False
    assert "提交" in payload["error"]


def test_concat_tool_requires_two_documents():
    tool = video_concat.video_concat(account_id="acc")
    payload = json.loads(tool._run(knowledge_base_id="kb", document_ids=["d1"]))
    assert payload["ok"] is False
    assert "两段" in payload["error"]


def test_concat_tool_dispatches_in_order(monkeypatch):
    captured = _capture_delay(monkeypatch, video_concat)
    tool = video_concat.video_concat(account_id="acc")
    json.loads(tool._run(knowledge_base_id="kb", document_ids=["d3", "d1"], name="合片"))
    assert captured["args"][1] == ["d3", "d1"]


def test_subtitle_tool_requires_cues():
    tool = video_subtitle.video_subtitle(account_id="acc")
    payload = json.loads(tool._run(knowledge_base_id="kb", document_id="d", cues=[]))
    assert payload["ok"] is False
    assert "字幕" in payload["error"]


def test_subtitle_tool_rejects_malformed_cue():
    tool = video_subtitle.video_subtitle(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb", document_id="d",
                  cues=[{"start": "abc", "end": 2, "text": "x"}])
    )
    assert payload["ok"] is False
    assert "时间" in payload["error"]


def test_subtitle_tool_dispatches_cues(monkeypatch):
    captured = _capture_delay(monkeypatch, video_subtitle)
    tool = video_subtitle.video_subtitle(account_id="acc")
    cues = [{"start": 0.0, "end": 1.0, "text": "hi"}]
    json.loads(
        tool._run(knowledge_base_id="kb", document_id="d", cues=cues, name="字幕")
    )
    assert captured["args"][2] == cues


def test_tool_yamls_declare_expected_shape():
    from pathlib import Path

    import yaml

    base = Path(video_trim.__file__).parent
    for stem in ("video_trim", "video_concat", "video_subtitle"):
        data = yaml.safe_load((base / f"{stem}.yaml").read_text(encoding="utf-8"))
        assert data["name"] == stem
        assert data["label"]
        assert isinstance(data["params"], list) and data["params"]
        assert isinstance(data["task_keywords"], list) and data["task_keywords"]


def test_positions_yaml_lists_all_three_tools():
    from pathlib import Path

    import yaml

    base = Path(video_trim.__file__).parent
    names = yaml.safe_load((base / "positions.yaml").read_text(encoding="utf-8"))
    assert set(names) == {"video_trim", "video_concat", "video_subtitle"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/core/tools/test_video_edit_tools.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（`ModuleNotFoundError: ...providers.video_edit_tools`）

- [ ] **Step 3: 实现 provider 包与工具**

创建 `api/internal/core/tools/builtin_tools/providers/video_edit_tools/__init__.py`（空文件）：

```python
```

创建 `api/internal/core/tools/builtin_tools/providers/video_edit_tools/positions.yaml`：

```yaml
- video_trim
- video_concat
- video_subtitle
```

创建 `api/internal/core/tools/builtin_tools/providers/video_edit_tools/video_trim.py`：

```python
"""视频裁剪工具（对话内改细节）。

把库内某个视频按时间区间裁出一段，产物存入成品库（可检索复用）。
执行走 Celery（不阻塞对话），派发后立即返回任务号。

注意：本工具**不自造剪辑能力**，ffmpeg 命令构造与执行见
`internal.core.video.ffmpeg_edit` / `internal.service.video_edit_service`。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _load_task():
    from internal.task.video_edit_tasks import video_trim_task

    return video_trim_task


class VideoTrimInput(BaseModel):
    """裁剪输入。"""

    knowledge_base_id: str = Field(..., description="素材所在知识库 id")
    document_id: str = Field(..., description="要裁剪的视频素材 id")
    start_sec: float = Field(..., description="开始时间（秒）")
    end_sec: float = Field(0, description="结束时间（秒）；不传或 0 表示裁到末尾")
    name: str = Field("", description="成品名称，可选")


class VideoTrimTool(BaseTool):
    """把视频按时间区间裁剪并存入成品库。"""

    name: str = "video_trim"
    description: str = (
        "当用户要求裁剪/截取/剪出一段视频时调用。"
        "传入素材所在知识库与视频 id、起止秒数，系统会裁剪并存入成品库。"
    )
    args_schema: type[BaseModel] = VideoTrimInput
    account_id: str = ""

    def _run(
        self,
        knowledge_base_id: str = "",
        document_id: str = "",
        start_sec: float = 0,
        end_sec: float = 0,
        name: str = "",
        **kwargs: Any,
    ) -> str:
        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps({"ok": False, "error": "缺少当前账号信息，无法裁剪"}, ensure_ascii=False)
        if not str(knowledge_base_id or "").strip() or not str(document_id or "").strip():
            return json.dumps(
                {"ok": False, "error": "缺少知识库或素材信息：需要 knowledge_base_id 与 document_id"},
                ensure_ascii=False,
            )

        try:
            start = float(start_sec or 0)
            end_raw = float(end_sec or 0)
        except (TypeError, ValueError):
            return json.dumps({"ok": False, "error": "起止时间必须是数字（秒）"}, ensure_ascii=False)
        if start < 0:
            return json.dumps({"ok": False, "error": "开始时间不能为负"}, ensure_ascii=False)
        # end=0 视为「裁到末尾」，交由 service 与时长比对
        end = end_raw if end_raw > 0 else None
        if end is not None and end <= start:
            return json.dumps(
                {"ok": False, "error": "结束时间必须晚于开始时间"}, ensure_ascii=False
            )

        try:
            async_result = _load_task().delay(
                str(knowledge_base_id), str(document_id), start, end,
                str(name or "").strip(), account_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("裁剪任务提交失败 account_id=%s", account_id, exc_info=True)
            return json.dumps(
                {"ok": False, "error": f"裁剪任务提交失败：{exc}"}, ensure_ascii=False
            )

        return json.dumps(
            {
                "ok": True,
                "dispatched": True,
                "task_id": str(getattr(async_result, "id", "")),
                "message": "视频裁剪已提交后台处理，完成后会自动存入成品库",
            },
            ensure_ascii=False,
        )

    async def _arun(
        self, knowledge_base_id: str = "", document_id: str = "",
        start_sec: float = 0, end_sec: float = 0, name: str = "", **kwargs: Any
    ) -> str:
        return self._run(
            knowledge_base_id=knowledge_base_id, document_id=document_id,
            start_sec=start_sec, end_sec=end_sec, name=name, **kwargs,
        )


def video_trim(**kwargs: Any) -> BaseTool:
    """工厂函数（函数名必须与工具名一致，Provider 按此动态导入）。"""
    return VideoTrimTool(account_id=str(kwargs.get("account_id") or "").strip())
```

创建 `api/internal/core/tools/builtin_tools/providers/video_edit_tools/video_trim.yaml`：

```yaml
name: video_trim
label: 裁剪视频
description: 把知识库里的视频按时间区间裁出一段，并自动存入成品库。
params:
- name: knowledge_base_id
  label: 知识库
  type: string
  required: true
- name: document_id
  label: 视频素材
  type: string
  required: true
- name: start_sec
  label: 开始时间（秒）
  type: number
  required: true
- name: end_sec
  label: 结束时间（秒）
  type: number
  required: false
- name: name
  label: 成品名称
  type: string
  required: false
task_keywords:
- 裁剪视频
- 剪切视频
- 截取视频
- 剪一段
- 掐头去尾
- 裁剪
- trim
```

创建 `.../video_edit_tools/video_concat.py`：

```python
"""视频拼接工具（对话内改细节）。

把库内多段视频按给定顺序拼成一段，产物存入成品库。
要求各段编码参数一致（concat demuxer + 流拷贝），否则应改用重编码路径。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _load_task():
    from internal.task.video_edit_tasks import video_concat_task

    return video_concat_task


class VideoConcatInput(BaseModel):
    """拼接输入。"""

    knowledge_base_id: str = Field(..., description="素材所在知识库 id")
    document_ids: list[str] = Field(..., description="要拼接的视频素材 id 列表，按拼接顺序给出")
    name: str = Field("", description="成品名称，可选")


class VideoConcatTool(BaseTool):
    """把多段视频按顺序拼接并存入成品库。"""

    name: str = "video_concat"
    description: str = (
        "当用户要求把多段视频拼成一段/合并视频/串起来时调用。"
        "按传入的素材顺序拼接，产物存入成品库。"
    )
    args_schema: type[BaseModel] = VideoConcatInput
    account_id: str = ""

    def _run(
        self,
        knowledge_base_id: str = "",
        document_ids: list[str] | None = None,
        name: str = "",
        **kwargs: Any,
    ) -> str:
        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps({"ok": False, "error": "缺少当前账号信息，无法拼接"}, ensure_ascii=False)
        if not str(knowledge_base_id or "").strip():
            return json.dumps(
                {"ok": False, "error": "缺少知识库信息：需要 knowledge_base_id"}, ensure_ascii=False
            )

        ids = [str(i).strip() for i in (document_ids or []) if str(i).strip()]
        if len(ids) < 2:
            return json.dumps(
                {"ok": False, "error": "拼接至少需要两段视频素材"}, ensure_ascii=False
            )
        if len(set(ids)) != len(ids):
            return json.dumps(
                {"ok": False, "error": "拼接素材不能重复：请检查 document_ids"}, ensure_ascii=False
            )

        try:
            async_result = _load_task().delay(
                str(knowledge_base_id), ids, str(name or "").strip(), account_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("拼接任务提交失败 account_id=%s", account_id, exc_info=True)
            return json.dumps(
                {"ok": False, "error": f"拼接任务提交失败：{exc}"}, ensure_ascii=False
            )

        return json.dumps(
            {
                "ok": True,
                "dispatched": True,
                "task_id": str(getattr(async_result, "id", "")),
                "message": "视频拼接已提交后台处理，完成后会自动存入成品库",
            },
            ensure_ascii=False,
        )

    async def _arun(
        self, knowledge_base_id: str = "", document_ids: list[str] | None = None,
        name: str = "", **kwargs: Any
    ) -> str:
        return self._run(
            knowledge_base_id=knowledge_base_id, document_ids=document_ids, name=name, **kwargs
        )


def video_concat(**kwargs: Any) -> BaseTool:
    """工厂函数（函数名必须与工具名一致）。"""
    return VideoConcatTool(account_id=str(kwargs.get("account_id") or "").strip())
```

创建 `.../video_edit_tools/video_concat.yaml`：

```yaml
name: video_concat
label: 拼接视频
description: 把知识库里的多段视频按指定顺序拼成一段，并自动存入成品库。
params:
- name: knowledge_base_id
  label: 知识库
  type: string
  required: true
- name: document_ids
  label: 视频素材（按拼接顺序）
  type: string
  required: true
- name: name
  label: 成品名称
  type: string
  required: false
task_keywords:
- 拼接视频
- 合并视频
- 视频拼起来
- 串视频
- 合成一段
- concat
```

创建 `.../video_edit_tools/video_subtitle.py`：

```python
"""视频加字幕工具（对话内改细节）。

将字幕烧录进画面并存入成品库。

**字幕时间轴由调用方显式提供**（`cues=[{start,end,text}]`）——这是经实测的
刻意设计：现有 ASR（`AudioService.audio_to_text`）只返回纯文本、零时间戳，
无法自动生成时间轴。需要自动对齐时，应由上层（LLM 读 ASR 文本 + 视频时长）
先分配时间轴再传入，而非在本工具内猜测。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _load_task():
    from internal.task.video_edit_tasks import video_subtitle_task

    return video_subtitle_task


class VideoSubtitleInput(BaseModel):
    """字幕输入。"""

    knowledge_base_id: str = Field(..., description="素材所在知识库 id")
    document_id: str = Field(..., description="要加字幕的视频素材 id")
    cues: list[dict] = Field(
        ...,
        description=(
            "字幕条目列表，每项形如 {start: 0.0, end: 1.5, text: '字幕文本'}，"
            "start/end 为秒。**必须由调用方给出时间轴**（系统不做自动对齐）。"
        ),
    )
    name: str = Field("", description="成品名称，可选")


class VideoSubtitleTool(BaseTool):
    """给视频烧录字幕并存入成品库。"""

    name: str = "video_subtitle"
    description: str = (
        "当用户要求给视频加字幕/烧字幕/配字幕时调用。"
        "须提供带时间轴的字幕条目（start/end 秒 + 文本），系统会烧录进画面并存入成品库。"
    )
    args_schema: type[BaseModel] = VideoSubtitleInput
    account_id: str = ""

    def _run(
        self,
        knowledge_base_id: str = "",
        document_id: str = "",
        cues: list[dict] | None = None,
        name: str = "",
        **kwargs: Any,
    ) -> str:
        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps({"ok": False, "error": "缺少当前账号信息，无法加字幕"}, ensure_ascii=False)
        if not str(knowledge_base_id or "").strip() or not str(document_id or "").strip():
            return json.dumps(
                {"ok": False, "error": "缺少知识库或素材信息：需要 knowledge_base_id 与 document_id"},
                ensure_ascii=False,
            )

        normalized = self._normalize_cues(cues)
        if isinstance(normalized, str):
            return json.dumps({"ok": False, "error": normalized}, ensure_ascii=False)

        try:
            async_result = _load_task().delay(
                str(knowledge_base_id), str(document_id), normalized,
                str(name or "").strip(), account_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("字幕任务提交失败 account_id=%s", account_id, exc_info=True)
            return json.dumps(
                {"ok": False, "error": f"字幕任务提交失败：{exc}"}, ensure_ascii=False
            )

        return json.dumps(
            {
                "ok": True,
                "dispatched": True,
                "task_id": str(getattr(async_result, "id", "")),
                "message": "字幕已提交后台烧录，完成后会自动存入成品库",
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _normalize_cues(cues: list[dict] | None) -> list[dict] | str:
        """校验并归一化字幕条目；不合法时返回错误消息字符串。

        在工具层拦下非法时间（早于 service，避免把明显错误的输入丢进 Celery）。
        """
        if not cues:
            return "字幕内容为空：需要至少一条 {start, end, text}"
        normalized: list[dict] = []
        for index, cue in enumerate(cues, start=1):
            if not isinstance(cue, dict):
                return f"第 {index} 条字幕格式错误：应为 {{start, end, text}} 对象"
            text = str(cue.get("text") or "").strip()
            if not text:
                continue
            try:
                start = float(cue.get("start"))
                end = float(cue.get("end"))
            except (TypeError, ValueError):
                return f"第 {index} 条字幕时间非法：start/end 必须是数字（秒）"
            if start < 0:
                return f"第 {index} 条字幕开始时间不能为负"
            if end <= start:
                return f"第 {index} 条字幕结束时间必须晚于开始时间"
            normalized.append({"start": start, "end": end, "text": text})
        if not normalized:
            return "字幕内容为空：至少需要一条非空文本"
        return normalized

    async def _arun(
        self, knowledge_base_id: str = "", document_id: str = "",
        cues: list[dict] | None = None, name: str = "", **kwargs: Any
    ) -> str:
        return self._run(
            knowledge_base_id=knowledge_base_id, document_id=document_id,
            cues=cues, name=name, **kwargs,
        )


def video_subtitle(**kwargs: Any) -> BaseTool:
    """工厂函数（函数名必须与工具名一致）。"""
    return VideoSubtitleTool(account_id=str(kwargs.get("account_id") or "").strip())
```

创建 `.../video_edit_tools/video_subtitle.yaml`：

```yaml
name: video_subtitle
label: 视频加字幕
description: 给知识库里的视频烧录字幕（需提供带时间轴的字幕条目），并自动存入成品库。
params:
- name: knowledge_base_id
  label: 知识库
  type: string
  required: true
- name: document_id
  label: 视频素材
  type: string
  required: true
- name: cues
  label: 字幕条目（含时间轴）
  type: string
  required: true
- name: name
  label: 成品名称
  type: string
  required: false
task_keywords:
- 加字幕
- 烧字幕
- 配字幕
- 字幕
- subtitle
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/core/tools/test_video_edit_tools.py -q --no-cov -p no:cacheprovider`
Expected: PASS（13 passed）

- [ ] **Step 5: 提交**

```bash
git add api/internal/core/tools/builtin_tools/providers/video_edit_tools api/test/internal/core/tools/test_video_edit_tools.py
git commit -m "feat(video-edit): add video_trim/video_concat/video_subtitle tools"
```

---

## Task 6: 登记 provider 与运行时挂载

**Files:**
- Modify: `api/internal/core/tools/builtin_tools/providers/providers.yaml`
- Modify: `api/internal/service/assistant_agent_service.py`
- Test: `api/test/internal/core/tools/test_video_edit_tools.py`（追加）

**背景**：这是本次最关键的「接线」环节——仓库历史上多次出现「工具写好了但没挂载点」的断链（`create_knowledge_base`、`video_analyze`）。本节两处缺一不可。

- [ ] **Step 1: 写失败的测试**

在 `api/test/internal/core/tools/test_video_edit_tools.py` 末尾追加：

```python
def test_provider_registered_in_providers_yaml():
    from pathlib import Path

    import yaml

    providers_yaml = Path(video_trim.__file__).parents[1] / "providers.yaml"
    data = yaml.safe_load(providers_yaml.read_text(encoding="utf-8"))
    names = [p["name"] for p in data]
    assert "video_edit_tools" in names, "video_edit_tools 未登记进 providers.yaml"
    entry = next(p for p in data if p["name"] == "video_edit_tools")
    # 字段完整性：ProviderEntity 要求这些键存在
    for key in ("label", "description", "icon", "background", "category", "created_at"):
        assert key in entry, f"providers.yaml 缺字段：{key}"


def test_tools_are_mounted_at_runtime_with_account_id():
    """挂载点回归：缺挂载则对话内不可达（历史断链）。"""
    from pathlib import Path

    src = Path(video_trim.__file__).parents[4] / "service" / "assistant_agent_service.py"
    text = src.read_text(encoding="utf-8")
    assert "video_edit_tools" in text, "assistant_agent_service 未挂载 video_edit_tools"
    for tool_name in ("video_trim", "video_concat", "video_subtitle"):
        assert f'"{tool_name}"' in text, f"未挂载 {tool_name}"
    # 依赖账号的工具必须注入 account_id，否则会返回「缺少账号」
    assert "account_id=str(account_id)" in text


def test_provider_loader_discovers_all_tools():
    """Provider 按 positions.yaml 动态导入，工具必须能被真实发现。"""
    from internal.core.tools.builtin_tools.providers.builtin_provider_manager import (
        BuiltinProviderManager,
    )
    from internal.core.tools.builtin_tools.providers.provider_entity import Provider

    manager = BuiltinProviderManager()
    provider_entity = manager.get_provider("video_edit_tools")
    assert provider_entity is not None, "provider 未被管理器发现"
    provider = Provider(provider_entity=provider_entity)
    assert set(provider.tool_entity_map) == {"video_trim", "video_concat", "video_subtitle"}
    for name in ("video_trim", "video_concat", "video_subtitle"):
        assert callable(provider.tool_func_map[name]), f"{name} 工厂函数不可调用"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/core/tools/test_video_edit_tools.py -q -k "provider or mounted" --no-cov -p no:cacheprovider`
Expected: FAIL（`video_edit_tools 未登记进 providers.yaml`）

- [ ] **Step 3: 登记 provider**

在 `api/internal/core/tools/builtin_tools/providers/providers.yaml` 末尾追加：

```yaml
- name: video_edit_tools
  label: 视频编辑工具
  description: 视频轻量剪辑能力，支持 Agent 在对话内裁剪、拼接、加字幕并存入成品库。
  icon: ""
  background: "#EEF2FF"
  category: video
  created_at: 1789800000
```

- [ ] **Step 4: 挂载到运行时**

在 `api/internal/service/assistant_agent_service.py` 的 `_build_assistant_runtime_tools` 中，找到 video_render_tools 的挂载块（约 L1054-1064），在其**之后**追加：

```python
        # 视频编辑工具（裁剪/拼接/加字幕）：Agent 可在对话内改细节并存入成品库。
        # 依赖当前账号（素材归属校验 + 成品库归属），故必须在此显式挂载并注入 account_id
        # ——`_load_non_mcp_tool` 那条通用路径是空参实例化，拿不到账号。
        if self.app_config_service is not None:
            for edit_tool_name in ("video_trim", "video_concat", "video_subtitle"):
                try:
                    edit_tool_factory = self.app_config_service.builtin_provider_manager.get_tool(
                        "video_edit_tools",
                        edit_tool_name,
                    )
                    if edit_tool_factory is not None:
                        tools.append(edit_tool_factory(account_id=str(account_id)))
                except Exception:
                    logger.warning(
                        "构建视频编辑工具失败 name=%s，不影响其他工具",
                        edit_tool_name,
                        exc_info=True,
                    )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/core/tools/test_video_edit_tools.py -q --no-cov -p no:cacheprovider`
Expected: PASS（16 passed）

- [ ] **Step 6: 提交**

```bash
git add api/internal/core/tools/builtin_tools/providers/providers.yaml api/internal/service/assistant_agent_service.py api/test/internal/core/tools/test_video_edit_tools.py
git commit -m "feat(video-edit): register provider and mount edit tools at runtime"
```

---

## Task 7: 真机端到端验证

**Files:**（无代码改动，仅验证）

**背景**：本任务的剪辑命令此前从未真实跑过。必须用真 ffmpeg 验证三种命令都能产出有效 MP4——单测替换了 subprocess，恰好绕过了这一层。

- [ ] **Step 1: 生成测试素材并验证 trim**

在仓库根运行（用与生产同源的 imageio_ffmpeg）：

```bash
cd api && python - <<'PY'
import subprocess, tempfile, os
from pathlib import Path
from internal.core.vision.vision_invoke import _resolve_ffmpeg_exe

exe = _resolve_ffmpeg_exe()
work = Path(tempfile.mkdtemp(prefix="kb-p4-e2e-"))
src = work / "src.mp4"
# 造 5 秒测试视频（含音轨，覆盖 -c copy 的音频处理）
subprocess.run([exe, "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25",
                "-f", "lavfi", "-i", "sine=frequency=440", "-t", "5",
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                str(src)], check=True, capture_output=True)
print("source:", src, src.stat().st_size, "bytes")

from internal.service.video_edit_service import VideoEditService
svc = VideoEditService.__new__(VideoEditService)
out = work / "trim.mp4"
svc.trim(source_path=src, output_path=out, start_sec=1.0, end_sec=3.0)
print("TRIM OK:", out.stat().st_size, "bytes")
PY
```

Expected: 输出 `source: ...` 与 `TRIM OK: <正数字节>`；无异常。

- [ ] **Step 2: 验证 concat 与 subtitle**

```bash
cd api && python - <<'PY'
import subprocess, tempfile
from pathlib import Path
from internal.core.vision.vision_invoke import _resolve_ffmpeg_exe
from internal.service.video_edit_service import VideoEditService

exe = _resolve_ffmpeg_exe()
work = Path(tempfile.mkdtemp(prefix="kb-p4-e2e2-"))
parts = []
for i in range(2):
    p = work / f"p{i}.mp4"
    subprocess.run([exe, "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25",
                    "-t", "2", "-c:v", "libx264", "-preset", "ultrafast",
                    str(p)], check=True, capture_output=True)
    parts.append(p)

svc = VideoEditService.__new__(VideoEditService)

merged = work / "merged.mp4"
svc.concat(source_paths=parts, output_path=merged)
print("CONCAT OK:", merged.stat().st_size, "bytes")

sub = work / "sub.mp4"
svc.burn_subtitles(source_path=parts[0], output_path=sub,
                   cues=[{"start": 0.0, "end": 1.0, "text": "Hello"},
                         {"start": 1.0, "end": 2.0, "text": "World"}])
print("SUBTITLE OK:", sub.stat().st_size, "bytes")
PY
```

Expected: 输出 `CONCAT OK: <正数>` 与 `SUBTITLE OK: <正数>`。

- [ ] **Step 3: 用 ffprobe 复核产物有效性**

```bash
cd api && python - <<'PY'
import glob, subprocess, os
from internal.core.vision.vision_invoke import _resolve_ffmpeg_exe
exe = _resolve_ffmpeg_exe()
# 复用最近一次 e2e 目录
dirs = sorted(glob.glob(os.path.join(os.environ.get("TEMP", "/tmp"), "kb-p4-e2e*")))
for d in dirs:
    for f in sorted(glob.glob(os.path.join(d, "*.mp4"))):
        r = subprocess.run([exe, "-i", f], capture_output=True)
        err = (r.stderr or b"").decode("utf-8", "replace")
        dur = [l for l in err.splitlines() if "Duration:" in l]
        print(os.path.basename(f), "->", (dur[0].split("Duration:")[1].split(",")[0].strip() if dur else "NO_DURATION"))
PY
```

Expected: 每个产物都能读出 `Duration: 00:00:0x.xx`（**读不出即产物无效，必须排查**）。

- [ ] **Step 4: 记录验证结论**

将实测通过的版本信息记入 `docs/deployment-single-node.md` 的渲染段（与 KB-P3.7 同口径），说明剪辑依赖 `imageio_ffmpeg`（api 容器内已有，无需额外安装）。

- [ ] **Step 5: 提交**

```bash
git add docs/deployment-single-node.md
git commit -m "docs(video-edit): record verified ffmpeg edit capabilities on api container"
```

---

## Task 8: 文档同步

**Files:**
- Modify: `docs/prd/modules/02-knowledge-base.md`
- Modify: `docs/prd/execution-roadmap.md`
- Modify: `docs/prd/knowledge-base-product-form-design.md`

- [ ] **Step 1: 更新 02-knowledge-base.md**

在 §11.14 之后新增：

```markdown
### 11.15 视频轻量剪辑（KB-P4 已落地）

「改细节」链路的剪辑三件套：裁剪 / 拼接 / 加字幕，产物存入成品库（与出片共用 `store_render_output`）。

| 能力 | 工具 | 实现 | 说明 |
| --- | --- | --- | --- |
| 裁剪 | `video_trim` | ffmpeg `-ss/-t -c copy` | 默认流拷贝（无损、秒级）；`reencode=True` 可重编码换取帧精度 |
| 拼接 | `video_concat` | ffmpeg `concat demuxer -c copy` | 按传入顺序拼接，要求各段编码参数一致 |
| 加字幕 | `video_subtitle` | ffmpeg `subtitles` 滤镜（libass）+ 重编码 | **字幕时间轴由调用方显式提供**（见下） |

**执行环境**：api 容器内**无系统 ffmpeg**，依赖 `imageio_ffmpeg` 静态二进制（实测 v7.0.2，具备 libx264 / concat demuxer / subtitles 滤镜；**无 drawtext**，故字幕走 subtitles 烧录）。
剪辑经 Celery 任务（`internal.task.video_edit_tasks.*`，走默认 `celery` 队列）异步执行，避免阻塞对话请求线程。

**⚠️ 字幕时间轴：三级解析（**本段原写「ASR 只返回纯文本、必须显式传 cues」，已被 §0.1 推翻**）**：
L1 解析时经 `AudioService.audio_to_text_with_segments()`（请求 `response_format=verbose_json`）取得
`segments[{start,end,text}]` 并写入 `KnowledgeSegment.metadata.transcript_segments`。
`video_subtitle` 的 `cues` 因此为**可选**：不传即自动生成（① 复用 L1 留存时间轴 → ② 缺失则重跑 ASR）；
仅在人工修订文案 / 精确对齐时才需显式传入。

**工具挂载点**：`assistant_agent_service._build_assistant_runtime_tools`（与 `render_video` 同处，注入 `account_id` 用于素材归属校验与成品库归属）。
```

- [ ] **Step 2: 更新 execution-roadmap.md**

把 `KB-P4` 行改为：

```markdown
| KB-P4 | 视频轻量编辑（trim / concat / subtitle） | ✅ 完成：渲染出片由 KB-P3.7 落地；trim/concat/subtitle 三工具由本阶段落地（见 [02-knowledge-base.md §11.15](./modules/02-knowledge-base.md)） |
```

并在 KB-P4 小节（若已建）或 KB-P3.8 之后补一节 `### KB-P4：视频轻量剪辑（已完成）`，列出三个工具、执行环境、字幕时间轴三级解析（见 §0.1）。

- [ ] **Step 3: 更新 knowledge-base-product-form-design.md**

- §5.2 表格「加字幕」行的「说明」列改为：`字幕源可为**调用方显式提供**（含时间轴），也可**自动生成**（实测 ASR 请求 response_format=verbose_json 即返回 segments`（**注**：原计划此处写「实测现有 ASR 只返回纯文本，无法自动对齐」，已被 §0.1 推翻）
- §7.4 表格末行状态改为：三工具**已落地**
- §9.2 的 KB-P4 行状态改为 `✅ 已完成`

- [ ] **Step 4: 提交**

```bash
git add docs/prd/modules/02-knowledge-base.md docs/prd/execution-roadmap.md docs/prd/knowledge-base-product-form-design.md
git commit -m "docs(video-edit): document KB-P4 trim/concat/subtitle with subtitle timeline reality"
```

---

## Task 9: 接线审查与全量回归

**Files:**（无代码改动，仅验证）

- [ ] **Step 1: 逐个新符号点名入口**

| 新符号 | 必须存在的入口 | 复核方式 |
| --- | --- | --- |
| `video_edit_tools` provider | `providers.yaml` 登记 | `test_provider_registered_in_providers_yaml` |
| `video_trim` / `video_concat` / `video_subtitle` | `positions.yaml` + 同名工厂函数 | `test_provider_loader_discovers_all_tools` |
| 三个工具类 | `assistant_agent_service` 挂载点（注入 account_id） | `test_tools_are_mounted_at_runtime_with_account_id` |
| `video_trim_task` 等 | `TASK_MODULES` + 显式 import + 工具层 `delay()` 派发点 | `test_tasks_are_registered_in_celery_task_modules` |
| `VideoEditService.trim/concat/burn_subtitles` | `*_document` 编排方法 → 工具 → Celery | 服务层单测 + Task 7 真机验证 |
| `build_*_command` | `VideoEditService` 调用 | `test_ffmpeg_edit.py` |
| `store_render_output` 复用 | 无需改动（KB-P3.7 已有） | 既有测试 |

- [ ] **Step 2: 全仓搜索新符号的调用方（排除测试与文档）**

```bash
cd d:/DEMO/openagent-main
grep -rn "video_trim\|video_concat\|video_subtitle\|VideoEditService\|video_edit_tools" --include=*.py api/ | grep -v "/test/" | grep -v "\.pyc"
```

Expected: 每个符号都能在**非测试**代码中找到「定义处 + 调用处」。若某符号只命中定义处，即为断链，必须补接线。

- [ ] **Step 3: 运行相关测试**

Run: `cd api && python -m pytest test/internal/core/video/test_ffmpeg_edit.py test/internal/service/test_video_edit_service.py test/internal/task/test_video_edit_tasks.py test/internal/core/tools/test_video_edit_tools.py -q --no-cov -p no:cacheprovider`
Expected: PASS（全部）

- [ ] **Step 4: 全量回归**

Run: `cd api && python -m pytest test/ -q --no-cov -p no:cacheprovider 2>&1 | tail -20`
Expected: 全部通过（允许既有环境失败，需逐条确认与本改动无关）

- [ ] **Step 5: 工具同步与加载冒烟**

```bash
cd api && python - <<'PY'
from internal.core.tools.builtin_tools.providers.builtin_provider_manager import BuiltinProviderManager
m = BuiltinProviderManager()
p = m.get_provider("video_edit_tools")
assert p is not None, "provider 缺失"
from internal.core.tools.builtin_tools.providers.provider_entity import Provider
prov = Provider(provider_entity=p)
for name in ("video_trim", "video_concat", "video_subtitle"):
    tool = prov.tool_func_map[name](account_id="smoke-account")
    print(name, "OK ->", tool.name)
PY
```

Expected: 三行 `... OK -> video_trim` / `video_concat` / `video_subtitle`

- [ ] **Step 6: 提交验证记录（若有文档更新）**

```bash
git add api/ docs/
git commit -m "test(video-edit): verify KB-P4 wiring end to end"
```

---

## 自检清单（执行者收尾逐项打勾）

- [ ] `ffmpeg_edit.py` 是纯函数（无 subprocess / 无 IO），单测不依赖真实 ffmpeg
- [ ] SRT 时间戳用**逗号**分隔毫秒（`.` 是常见错误，播放器不认）
- [ ] SRT 空文本块被丢弃且**重新连续编号**
- [ ] `trim` 默认 `-c copy`，且 `-ss` 在 `-i` 之前
- [ ] `subtitle` 用的 `subtitles` 滤镜（**不是 drawtext**——实测镜像无 drawtext）
- [ ] `subtitle` 路径中的 `:` 已转义（Windows 盘符场景）
- [ ] 产物校验：退出码 0 但文件缺失/<1KB 必须报错，**不静默当成功**
- [ ] `TASK_MODULES` **与**显式 import 都加了 `video_edit_tasks`
- [ ] `positions.yaml` 三项齐全，且工厂函数名 == 工具名
- [ ] `providers.yaml` 已登记 `video_edit_tools`（字段齐全）
- [ ] 三个工具已挂载到 `_build_assistant_runtime_tools` 并注入 `account_id`
- [ ] 产物落库走 `store_render_output`，**未额外 `add_usage`**（避免双重计费）
- [ ] 临时工作目录用 `TemporaryDirectory`，成功/失败都不残留
- [ ] 字幕时间轴策略已在代码注释与文档双处说明（初版策略为「必须显式传入」，**已由 §0.1 更正为三级自动解析**）
- [ ] 全量回归通过，既有失败已逐条确认为环境问题
- [ ] 文档三处已同步（02-knowledge-base §11.15 / roadmap KB-P4 / form-design §5.2·§7.4·§9.2）
- [ ] 运行 `python -m graphify update .` 保持知识图谱最新

---

## 附：本计划对设计稿的两处偏离（已获实测支撑，供复核）

| # | 设计稿 | 本计划 | 依据 |
| --- | --- | --- | --- |
| 1 | §5.2 字幕「ASR 产物直接复用（ASR 文本 + 时间戳）」 | **已按设计稿实现**（§0.1 更正）：`audio_to_text_with_segments()` 请求 `verbose_json` 取得 `segments`，L1 落库后自动复用；调用方仍可显式覆盖 | 实测：不传 `response_format` 无 segments，传 `verbose_json` 则返回 `[{start,end,text}]`。**原判断「ASR 零时间戳」是错的**——它把「本项目没请求」误读为「服务端不提供」 |
| 2 | §5.2「转码是 CPU 密集：需专门任务队列（Celery）+ 独立配额计量」 | 用 Celery，但**复用默认 `celery` 队列**，不新建队列/容器/闸门 | api 容器无系统 ffmpeg 但有 `imageio_ffmpeg`；主 worker 即 api 镜像；剪辑为秒级操作，专用队列属过度设计 |

> 另：设计稿说「产物默认不入知识库，用户显式要求才存档」。本计划选择**入成品库**（与 `render_video` 同口径，零额外机制）。
> 若要严格照设计稿，需改为临时产物 + 过期清理，成本更高——**执行前请确认这一取向**。
