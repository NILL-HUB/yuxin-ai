# 知识库产品形态 P2A · 多模态素材入库 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让图片/音频/视频素材上传后自动解析为可检索文本片段并写入向量库，实现「上传视频 → 能被语义检索命中」。

**Architecture:** 新增 `KnowledgeMediaExtractorService` 负责把非文档素材转为文本片段（`MediaSegment`），复用平台既有的视觉模型调用与 ASR 能力（先抽取为共享模块）。`KnowledgeIndexingService` 按 `document.media_type` 分支：文档走原 `parsing→splitting→indexing`，多媒体走「解析产物即片段」的直达入库路径。`upload_document` 增加媒体类型识别与板块类型硬约束校验。

**Tech Stack:** Python 3.11+ / Quart / SQLAlchemy 2.0 / injector DI / ffmpeg（或 imageio-ffmpeg）/ SiliconFlow ASR / LangChain

**上游设计:** [knowledge-base-product-form-design.md](../../prd/knowledge-base-product-form-design.md) §三、§五
**前置依赖:** P1 数据基座已完成（`media_type`/`parse_profile` 字段、`KnowledgeBaseType` 枚举、音视频白名单、配额收口）
**显式不含:** 大文件分片上传（另立 P2B）、视频 ASR 音轨提取（L2 深度解析，见 P3）、关键帧视觉向量（P3）

---

## 文件结构

### 新增文件

| 文件 | 职责 |
|---|---|
| `api/internal/core/vision/__init__.py` | 视觉能力共享包（空） |
| `api/internal/core/vision/vision_invoke.py` | 共享视觉能力：data URI 构造、视觉模型调用、视频抽帧 |
| `api/internal/service/knowledge_media_extractor_service.py` | 多模态素材 → 文本片段（图片/音频/视频三分支） |
| `api/test/internal/core/vision/test_vision_invoke.py` | 共享视觉能力单测 |
| `api/test/internal/service/test_knowledge_media_extractor_service.py` | 多模态抽取服务单测 |
| `api/test/internal/service/test_knowledge_media_ingest.py` | 索引链路多媒体分支单测 |

### 修改文件

| 文件 | 改动 |
|---|---|
| `api/internal/core/tools/builtin_tools/providers/vision_tools/vision_analyze.py` | 改为复用共享模块（删除本地 `_invoke_vision_model` 等重复实现） |
| `api/internal/core/tools/builtin_tools/providers/vision_tools/video_analyze.py` | 改为复用共享模块（删除本地抽帧与视觉调用实现） |
| `api/internal/service/knowledge_indexing_service.py` | 注入 `media_extractor`；`build_document` 按 `media_type` 分支；抽 `_finalize_segments` 供两条路径复用 |
| `api/internal/service/knowledge_base_service.py` | `upload_document` 识别 `media_type`、板块类型硬约束校验、写入 `parse_profile` |

---

## Task 1: 抽取共享视觉能力模块

**Files:**
- Create: `api/internal/core/vision/__init__.py`
- Create: `api/internal/core/vision/vision_invoke.py`
- Test: `api/test/internal/core/vision/test_vision_invoke.py`

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/core/vision/test_vision_invoke.py
import base64
import os
import tempfile

import pytest

from internal.core.vision.vision_invoke import path_to_data_uri


def test_path_to_data_uri_encodes_file_bytes():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "sample.jpg")
        with open(path, "wb") as fh:
            fh.write(b"\xff\xd8\xff\xe0hello")

        data_uri = path_to_data_uri(path)

    assert data_uri.startswith("data:image/jpeg;base64,")
    encoded = data_uri.split(",", 1)[1]
    assert base64.b64decode(encoded) == b"\xff\xd8\xff\xe0hello"


def test_path_to_data_uri_rejects_oversized_file(monkeypatch):
    import internal.core.vision.vision_invoke as module

    monkeypatch.setattr(module, "_MAX_IMAGE_BYTES", 4)
    with tempfile.TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "big.jpg")
        with open(path, "wb") as fh:
            fh.write(b"12345")

        with pytest.raises(ValueError):
            path_to_data_uri(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/core/vision/test_vision_invoke.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'internal.core.vision'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/internal/core/vision/__init__.py
"""视觉能力共享包。"""
```

```python
# api/internal/core/vision/vision_invoke.py
"""共享视觉能力：图片/视频帧的视觉模型调用与视频抽帧。

从 vision_tools 内置工具中抽取，供「内置工具」与「知识库多模态解析」复用，
避免两处重复维护模型调用与帧抽取逻辑。
"""
from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)

# 单张图片编码上限（base64 前）
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
# 默认抽帧数量
_DEFAULT_FRAME_COUNT = 3
# ffmpeg 单次命令超时（秒）
_FRAME_TIMEOUT = 60


def path_to_data_uri(path: str) -> str:
    """把本地图片文件转为 data URI（带大小上限）。"""
    if not os.path.isfile(path):
        raise ValueError(f"图片文件不存在：{path}")
    with open(path, "rb") as fh:
        raw = fh.read(_MAX_IMAGE_BYTES + 1)
    if len(raw) > _MAX_IMAGE_BYTES:
        raise ValueError(f"图片超过大小限制：{path}")
    return f"data:image/jpeg;base64,{base64.b64encode(raw).decode('ascii')}"


def invoke_vision_model(data_uri: str, prompt: str) -> str:
    """调用平台视觉模型分析单张图片（入参为 data URI）。"""
    from langchain_core.messages import HumanMessage

    from internal.service.language_model_service import LanguageModelService

    llm = LanguageModelService.get_feature_model("vision_analyze")
    if llm is None:
        raise RuntimeError("未配置视觉分析模型")
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": data_uri}},
    ]
    response = llm.invoke([HumanMessage(content=content)])
    text = getattr(response, "content", "")
    if isinstance(text, list):
        text = "\n".join(
            str(item.get("text", ""))
            for item in text
            if isinstance(item, dict) and item.get("text")
        )
    return str(text or "").strip()


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _duration_to_ms(duration: str) -> int:
    parts = str(duration).split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = (float(part) for part in parts)
            return int((hours * 3600 + minutes * 60 + seconds) * 1000)
    except ValueError:
        return 0
    return 0


def extract_video_frames(video_path: str, frame_count: int = _DEFAULT_FRAME_COUNT) -> list[str]:
    """抽取视频关键帧，返回 data URI 列表；无可用后端时抛错。"""
    requested = _DEFAULT_FRAME_COUNT if frame_count is None else int(frame_count)
    normalized_count = max(1, requested)
    if _ffmpeg_available():
        return _extract_frames_ffmpeg(video_path, normalized_count)
    try:
        import imageio_ffmpeg  # type: ignore
    except ImportError:
        raise RuntimeError(
            "视频抽帧不可用：容器未安装 ffmpeg，也未安装 imageio-ffmpeg。"
            "请安装 imageio-ffmpeg（pip install imageio-ffmpeg）后重试。"
        )
    return _extract_frames_imageio(video_path, normalized_count)


def _extract_frames_ffmpeg(video_path: str, frame_count: int) -> list[str]:
    out_dir = tempfile.mkdtemp(prefix="video_frames_")
    try:
        pattern = os.path.join(out_dir, "frame_%03d.jpg")
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", "select='not(mod(n\\,100))'",
            "-frames:v", str(frame_count),
            "-q:v", "4", pattern,
        ]
        try:
            probe = subprocess.run(
                ["ffmpeg", "-i", video_path],
                capture_output=True, timeout=_FRAME_TIMEOUT,
            )
            stderr = probe.stderr.decode("utf-8", errors="replace")
            duration = None
            for line in stderr.splitlines():
                if "Duration:" in line:
                    duration = line.split("Duration:")[1].split(",")[0].strip()
                    break
            if duration:
                total_ms = _duration_to_ms(duration)
                if total_ms > 0:
                    step = max(1, int(total_ms / frame_count / 40))
                    cmd = [
                        "ffmpeg", "-y", "-i", video_path,
                        "-vf", f"select='not(mod(n\\,{step}))'",
                        "-frames:v", str(frame_count),
                        "-q:v", "4", pattern,
                    ]
        except Exception:
            pass

        subprocess.run(cmd, capture_output=True, timeout=_FRAME_TIMEOUT * 3, check=True)
        frames = sorted(
            os.path.join(out_dir, name)
            for name in os.listdir(out_dir)
            if name.startswith("frame_")
        )
        if not frames:
            return _last_resort_first_frame(video_path)
        return [path_to_data_uri(path) for path in frames[:frame_count]]
    except subprocess.CalledProcessError as exc:
        logger.warning("ffmpeg 抽帧失败: %s", getattr(exc, "stderr", b"")[:200])
        return _last_resort_first_frame(video_path)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def _last_resort_first_frame(video_path: str) -> list[str]:
    """抽帧失败时尝试取首帧，再失败则抛错。

    必须校验产出的首帧可被解码，否则损坏/空帧会被当作成功，
    让下游视觉模型收到空图并静默失败。
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
            out = handle.name
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", video_path, "-frames:v", "1", "-q:v", "4", out],
                capture_output=True, timeout=_FRAME_TIMEOUT, check=True,
            )
            from PIL import Image

            Image.open(out).load()
            return [path_to_data_uri(out)]
        finally:
            try:
                os.remove(out)
            except OSError:
                pass
    except Exception as exc:
        raise RuntimeError(f"视频帧提取失败: {exc}")


def _extract_frames_imageio(video_path: str, frame_count: int) -> list[str]:
    import imageio_ffmpeg  # type: ignore

    exe = imageio_ffmpeg.get_ffmpeg_exe()
    out_dir = tempfile.mkdtemp(prefix="video_frames_")
    try:
        pattern = os.path.join(out_dir, "frame_%03d.jpg")
        cmd = [exe, "-y", "-i", video_path, "-frames:v", str(frame_count), "-q:v", "4", pattern]
        subprocess.run(cmd, capture_output=True, timeout=_FRAME_TIMEOUT * 3, check=True)
        frames = sorted(
            os.path.join(out_dir, name)
            for name in os.listdir(out_dir)
            if name.startswith("frame_")
        )
        if not frames:
            raise RuntimeError("imageio_ffmpeg 未产出帧")
        return [path_to_data_uri(path) for path in frames[:frame_count]]
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/core/vision/test_vision_invoke.py -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/core/vision/__init__.py api/internal/core/vision/vision_invoke.py api/test/internal/core/vision/test_vision_invoke.py
git commit -m "feat(vision): extract shared vision invoke and frame extraction module"
```

---

## Task 2: 内置视觉工具改为复用共享模块

**Files:**
- Modify: `api/internal/core/tools/builtin_tools/providers/vision_tools/vision_analyze.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/vision_tools/video_analyze.py`
- Test: `api/test/internal/core/tools/test_vision_tools_shared.py` (create)

**目的**：消除重复实现（DRY），保证工具与知识库解析使用同一套视觉调用逻辑。**工具对外行为必须完全不变**。

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/core/tools/test_vision_tools_shared.py
"""确认内置视觉工具已复用共享模块（无本地重复实现）。

注意：vision_tools 包的 __init__.py 会 `from .vision_analyze import vision_analyze`
把同名函数挂到包属性上，遮蔽子模块；因此必须用 importlib.import_module 取真实模块对象，
否则 `import ... as m` 拿到的是函数而非模块，断言会失真。
"""
import importlib

vision_tool_module = importlib.import_module(
    "internal.core.tools.builtin_tools.providers.vision_tools.vision_analyze"
)
video_tool_module = importlib.import_module(
    "internal.core.tools.builtin_tools.providers.vision_tools.video_analyze"
)


def test_vision_analyze_reuses_shared_invoker():
    """视觉分析工具不应再定义本地 _invoke_vision_model。"""
    assert not hasattr(vision_tool_module, "_invoke_vision_model")


def test_video_analyze_reuses_shared_frame_extractor():
    """视频工具不应再定义本地抽帧实现。"""
    assert not hasattr(video_tool_module, "_extract_frames_ffmpeg")
    assert not hasattr(video_tool_module, "_extract_frames_imageio")
    assert not hasattr(video_tool_module, "_image_to_data_uri")
    assert not hasattr(video_tool_module, "_invoke_vision_model")


def test_video_analyze_keeps_ssrf_guard_and_download():
    """工具特有的 SSRF 防护与下载逻辑必须保留。"""
    assert hasattr(video_tool_module, "_is_safe_video_url")
    assert hasattr(video_tool_module, "_download_video")


def test_vision_analyze_keeps_ssrf_guard():
    assert hasattr(vision_tool_module, "_is_safe_image_url")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/core/tools/test_vision_tools_shared.py -v --no-cov`
Expected: FAIL（当前两个模块仍定义本地 `_invoke_vision_model` / `_extract_frames_ffmpeg`）

- [ ] **Step 3: Refactor 两个工具文件**

**`vision_analyze.py`** —— 删除本地 `_invoke_vision_model`（第 68-88 行），改为从共享模块导入；保留 SSRF 校验与 URL→data URI 转换（这是工具特有的网络安全逻辑）：

```python
from internal.core.vision.vision_invoke import invoke_vision_model
```

并将 `_run` 中的调用改为 `invoke_vision_model(data_uri, normalized_prompt)`。文件顶部 import 区删除不再使用的 `from langchain_core.messages import HumanMessage`（若仅此处使用）。

**`video_analyze.py`** —— 删除本地 `_invoke_vision_model`（第 214-234 行）、`_ffmpeg_available`、`_extract_frames`、`_extract_frames_ffmpeg`、`_duration_to_ms`、`_last_resort_first_frame`、`_extract_frames_imageio`、`_image_to_data_uri`（第 77-211 行），改为：

```python
from internal.core.vision.vision_invoke import extract_video_frames, invoke_vision_model
```

并将 `_run` 中 `frames = _extract_frames(video_path)` 改为 `frames = extract_video_frames(video_path)`、`_invoke_vision_model(frame, normalized_prompt)` 改为 `invoke_vision_model(frame, normalized_prompt)`。**保留** `_is_safe_video_url`、`_download_video`、`VideoAnalyzeTool` 与常量 `_MAX_VIDEO_BYTES`（工具特有的 SSRF/下载逻辑）。

- [ ] **Step 4: Run tests to verify tools still work**

Run: `cd api && python -m pytest test/internal/core/tools/test_vision_tools_shared.py test/internal/core/tools/ -v --no-cov`
Expected: PASS（新测试 3 passed，既有工具测试无回归）

- [ ] **Step 5: Commit**

```bash
git add api/internal/core/tools/builtin_tools/providers/vision_tools/vision_analyze.py api/internal/core/tools/builtin_tools/providers/vision_tools/video_analyze.py api/test/internal/core/tools/test_vision_tools_shared.py
git commit -m "refactor(vision): reuse shared vision module in builtin tools"
```

---

## Task 3: KnowledgeMediaExtractorService 骨架与图片解析

**Files:**
- Create: `api/internal/service/knowledge_media_extractor_service.py`
- Test: `api/test/internal/service/test_knowledge_media_extractor_service.py`

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/service/test_knowledge_media_extractor_service.py
import os
import tempfile
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.service.knowledge_media_extractor_service import (
    KnowledgeMediaExtractorService,
    MediaSegment,
)


class _FakeStorage:
    """把预置字节写入目标路径，模拟对象存储下载。"""

    def __init__(self, payload: bytes):
        self.payload = payload

    def download_file(self, key, target_path):
        with open(target_path, "wb") as fh:
            fh.write(self.payload)


def _new_service(payload=b"img-bytes", vision_text="一张产品截图"):
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(payload),
        audio_service=SimpleNamespace(),
    )
    service._invoke_vision = lambda data_uri, prompt: vision_text  # type: ignore[assignment]
    return service


def _document(media_type: str):
    return SimpleNamespace(
        id=uuid4(),
        media_type=media_type,
        knowledge_base_id=uuid4(),
        owner_account_id=uuid4(),
    )


def _upload_file(extension: str = "jpg"):
    return SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.{extension}",
        name=f"sample.{extension}", extension=extension, mime_type="image/jpeg",
    )


def test_image_extraction_returns_single_segment_with_summary():
    service = _new_service(vision_text="画面为新品海报，含文字「限时五折」")

    segments = service.extract(_document("image"), _upload_file("jpg"))

    assert len(segments) == 1
    assert isinstance(segments[0], MediaSegment)
    assert "限时五折" in segments[0].content
    assert segments[0].metadata["media_type"] == "image"
    assert segments[0].metadata["vision_summary"] == segments[0].content


def test_document_media_type_returns_no_segments():
    service = _new_service()
    assert service.extract(_document("document"), _upload_file("pdf")) == []


def test_unknown_media_type_returns_no_segments():
    service = _new_service()
    assert service.extract(_document("unknown"), _upload_file("bin")) == []


def test_image_extraction_propagates_vision_failure():
    service = _new_service()
    service._invoke_vision = lambda data_uri, prompt: (_ for _ in ()).throw(RuntimeError("no model"))
    with pytest.raises(RuntimeError):
        service.extract(_document("image"), _upload_file("png"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_media_extractor_service.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'internal.service.knowledge_media_extractor_service'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/internal/service/knowledge_media_extractor_service.py
"""多模态素材解析服务（L1 基础解析）。

把图片 / 音频 / 视频素材转为可入库的文本片段：
- 图片：视觉模型 OCR + 摘要
- 音频：ASR 全文转写
- 视频：关键帧视觉描述

产物 MediaSegment 直接映射 KnowledgeSegment 的 content 与 metadata，
由 KnowledgeIndexingService 写入并向量化，从而让多媒体素材可被语义检索。
"""
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

from injector import inject

from internal.core.ports.storage_port import ObjectStoragePort
from internal.core.vision.vision_invoke import invoke_vision_model, path_to_data_uri
from internal.entity.knowledge_entity import DocumentMediaType
from internal.model import KnowledgeDocument, UploadFile
from pkg.sqlalchemy import SQLAlchemy
from .audio_service import AudioService
from .base_service import BaseService

logger = logging.getLogger(__name__)

_IMAGE_PROMPT = (
    "请详细描述这张图片的内容，包括画面主体、场景、风格、配色，"
    "并完整识别其中的文字（OCR）。用简洁的中文段落输出。"
)

_VIDEO_FRAME_PROMPT = (
    "这是视频的一个关键帧。请描述画面主体、场景、动作与镜头类型，"
    "并识别画面中的字幕或文字（OCR）。用简洁的中文段落输出。"
)


@dataclass
class MediaSegment:
    """多模态解析产物，映射为一个 KnowledgeSegment。"""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@inject
@dataclass
class KnowledgeMediaExtractorService(BaseService):
    """图片/音频/视频 → 文本片段。

    依赖字段必须用具体类型标注：injector 依据类型注解做依赖解析，
    写 Any 会导致无法注入。
    """

    db: SQLAlchemy
    cos_service: ObjectStoragePort
    audio_service: AudioService

    def extract(
        self,
        document: KnowledgeDocument,
        upload_file: UploadFile,
    ) -> list[MediaSegment]:
        """按 media_type 分派解析；文档类型返回空（由既有文本链路处理）。"""
        media_type = getattr(document, "media_type", None) or DocumentMediaType.DOCUMENT.value
        if media_type == DocumentMediaType.IMAGE.value:
            return self._extract_image(upload_file)
        if media_type == DocumentMediaType.AUDIO.value:
            return self._extract_audio(upload_file)
        if media_type == DocumentMediaType.VIDEO.value:
            return self._extract_video(upload_file)
        return []

    def _download_to(self, upload_file: UploadFile, temp_dir: str) -> str:
        """从对象存储下载素材到临时目录，返回本地路径。"""
        file_path = os.path.join(temp_dir, os.path.basename(upload_file.key) or "material.bin")
        self.cos_service.download_file(upload_file.key, file_path)
        return file_path

    def _invoke_vision(self, data_uri: str, prompt: str) -> str:
        """视觉模型调用（独立方法便于测试替换）。"""
        return invoke_vision_model(data_uri, prompt)

    def _extract_image(self, upload_file: UploadFile) -> list[MediaSegment]:
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = self._download_to(upload_file, temp_dir)
            data_uri = path_to_data_uri(file_path)
            summary = self._invoke_vision(data_uri, _IMAGE_PROMPT)
        return [
            MediaSegment(
                content=summary,
                metadata={"media_type": DocumentMediaType.IMAGE.value, "vision_summary": summary},
            )
        ]

    def _extract_audio(self, upload_file: UploadFile) -> list[MediaSegment]:
        raise NotImplementedError("音频解析将在 Task 4 实现")

    def _extract_video(self, upload_file: UploadFile) -> list[MediaSegment]:
        raise NotImplementedError("视频解析将在 Task 5 实现")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_media_extractor_service.py -v --no-cov`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/knowledge_media_extractor_service.py api/test/internal/service/test_knowledge_media_extractor_service.py
git commit -m "feat(knowledge): add media extractor service with image parsing"
```

---

## Task 4: 音频 ASR 解析

**Files:**
- Modify: `api/internal/service/knowledge_media_extractor_service.py`
- Test: `api/test/internal/service/test_knowledge_media_extractor_service.py` (append)

- [ ] **Step 1: Write the failing test**

在测试文件末尾追加：

```python
class _FakeAudioService:
    def __init__(self, text="这是一段会议录音的转写内容。", error=None):
        self.text = text
        self.error = error
        self.received_filename = None

    def audio_to_text(self, audio, language="", provider="", model=""):
        self.received_filename = getattr(audio, "filename", None)
        if self.error:
            raise self.error
        return self.text


def test_audio_extraction_returns_transcript_segment():
    audio_service = _FakeAudioService()
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"audio-bytes"),
        audio_service=audio_service,
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp3", name="meeting.mp3",
        extension="mp3", mime_type="audio/mpeg",
    )

    segments = service.extract(_document("audio"), upload)

    assert len(segments) == 1
    assert "会议录音" in segments[0].content
    assert segments[0].metadata["media_type"] == "audio"
    assert audio_service.received_filename == "meeting.mp3"


def test_audio_extraction_raises_when_asr_unavailable():
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"audio-bytes"),
        audio_service=_FakeAudioService(error=RuntimeError("asr down")),
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.wav", name="a.wav",
        extension="wav", mime_type="audio/wav",
    )

    with pytest.raises(RuntimeError):
        service.extract(_document("audio"), upload)


def test_audio_extraction_returns_empty_when_transcript_blank():
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"audio-bytes"),
        audio_service=_FakeAudioService(text="   "),
    )
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.m4a", name="silent.m4a",
        extension="m4a", mime_type="audio/mp4",
    )

    assert service.extract(_document("audio"), upload) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_media_extractor_service.py -v --no-cov`
Expected: FAIL with `NotImplementedError: 音频解析将在 Task 4 实现`

- [ ] **Step 3: Implement `_extract_audio`**

将 `_extract_audio` 方法体替换为：

```python
    def _extract_audio(self, upload_file: UploadFile) -> list[MediaSegment]:
        """音频：下载后经 ASR 转写为文本片段；转写为空则不产出片段。"""
        from io import BytesIO

        from werkzeug.datastructures import FileStorage

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = self._download_to(upload_file, temp_dir)
            with open(file_path, "rb") as fh:
                content = fh.read()

        file_storage = FileStorage(
            stream=BytesIO(content),
            filename=upload_file.name or os.path.basename(upload_file.key),
            content_type=getattr(upload_file, "mime_type", None) or "audio/mpeg",
        )
        transcript = str(self.audio_service.audio_to_text(file_storage) or "").strip()
        if not transcript:
            return []
        return [
            MediaSegment(
                content=transcript,
                metadata={"media_type": DocumentMediaType.AUDIO.value},
            )
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_media_extractor_service.py -v --no-cov`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/knowledge_media_extractor_service.py api/test/internal/service/test_knowledge_media_extractor_service.py
git commit -m "feat(knowledge): parse audio materials via ASR"
```

---

## Task 5: 视频关键帧视觉解析

**Files:**
- Modify: `api/internal/service/knowledge_media_extractor_service.py`
- Test: `api/test/internal/service/test_knowledge_media_extractor_service.py` (append)

- [ ] **Step 1: Write the failing test**

在测试文件末尾追加：

```python
def test_video_extraction_returns_segment_per_frame():
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames = lambda path: ["data:frame-1", "data:frame-2"]
    seen_prompts = []

    def _vision(data_uri, prompt):
        seen_prompts.append((data_uri, prompt))
        return f"画面描述-{data_uri}"

    service._invoke_vision = _vision

    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mp4", name="promo.mp4",
        extension="mp4", mime_type="video/mp4",
    )

    segments = service.extract(_document("video"), upload)

    assert len(segments) == 2
    assert segments[0].content == "画面描述-data:frame-1"
    assert segments[0].metadata["media_type"] == "video"
    assert segments[0].metadata["scene_index"] == 1
    assert segments[0].metadata["frame_count"] == 2
    assert segments[1].metadata["scene_index"] == 2
    assert len(seen_prompts) == 2


def test_video_extraction_skips_frames_that_fail_analysis():
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames = lambda path: ["data:ok", "data:bad"]

    def _vision(data_uri, prompt):
        if data_uri == "data:bad":
            raise RuntimeError("vision failed")
        return "可用画面描述"

    service._invoke_vision = _vision
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mov", name="clip.mov",
        extension="mov", mime_type="video/quicktime",
    )

    segments = service.extract(_document("video"), upload)

    assert len(segments) == 1
    assert segments[0].content == "可用画面描述"
    assert segments[0].metadata["scene_index"] == 1


def test_video_extraction_raises_when_no_frames_extracted():
    service = KnowledgeMediaExtractorService(
        db=SimpleNamespace(),
        cos_service=_FakeStorage(b"video-bytes"),
        audio_service=SimpleNamespace(),
    )
    service._extract_frames = lambda path: []
    upload = SimpleNamespace(
        id=uuid4(), key=f"2026/09/13/{uuid4()}.mkv", name="broken.mkv",
        extension="mkv", mime_type="video/x-matroska",
    )

    with pytest.raises(RuntimeError):
        service.extract(_document("video"), upload)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_media_extractor_service.py -v --no-cov`
Expected: FAIL with `NotImplementedError: 视频解析将在 Task 5 实现`

- [ ] **Step 3: Implement `_extract_video` and `_extract_frames`**

将 `_extract_video` 替换为（并在类中新增 `_extract_frames` 便于测试替换）：

```python
    def _extract_frames(self, video_path: str) -> list[str]:
        """视频抽帧（独立方法便于测试替换）。"""
        from internal.core.vision.vision_invoke import extract_video_frames

        return extract_video_frames(video_path)

    def _extract_video(self, upload_file: UploadFile) -> list[MediaSegment]:
        """视频：抽关键帧 → 逐帧视觉描述；单帧失败跳过，全部失败则抛错。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = self._download_to(upload_file, temp_dir)
            frames = self._extract_frames(file_path)

        if not frames:
            raise RuntimeError("视频抽帧结果为空，无法解析")

        segments: list[MediaSegment] = []
        for index, frame in enumerate(frames, start=1):
            try:
                description = self._invoke_vision(frame, _VIDEO_FRAME_PROMPT)
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
                    },
                )
            )

        if not segments:
            raise RuntimeError("视频解析未产出任何可用内容")
        return segments
```

（`_VIDEO_FRAME_PROMPT` 常量已在 Task 3 的文件骨架中定义，此处直接使用，勿重复定义。）

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_media_extractor_service.py -v --no-cov`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/knowledge_media_extractor_service.py api/test/internal/service/test_knowledge_media_extractor_service.py
git commit -m "feat(knowledge): parse video materials via keyframe vision analysis"
```

---

## Task 6: upload_document 接入媒体类型识别与板块类型硬约束

**Files:**
- Modify: `api/internal/service/knowledge_base_service.py:196-236`
- Test: `api/test/internal/service/test_knowledge_upload_media_type.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/service/test_knowledge_upload_media_type.py
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ValidateErrorException
from internal.service.knowledge_base_service import KnowledgeBaseService


def _service():
    return KnowledgeBaseService(
        db=SimpleNamespace(),
        retrieval_service=SimpleNamespace(),
        icon_generator_service=SimpleNamespace(),
    )


def test_media_type_allowed_for_matching_base_type():
    service = _service()
    base = SimpleNamespace(base_type="video")
    # 不应抛异常
    service._assert_media_type_allowed(base, "mp4")


def test_media_type_rejected_for_mismatched_base_type():
    service = _service()
    base = SimpleNamespace(base_type="video")
    with pytest.raises(ValidateErrorException):
        service._assert_media_type_allowed(base, "pdf")


def test_mixed_base_type_allows_any_media_type():
    service = _service()
    base = SimpleNamespace(base_type="mixed")
    service._assert_media_type_allowed(base, "mp4")
    service._assert_media_type_allowed(base, "pdf")


def test_missing_base_type_falls_back_to_mixed():
    service = _service()
    base = SimpleNamespace(base_type=None)
    service._assert_media_type_allowed(base, "mp3")


def test_empty_extension_is_allowed():
    """无扩展名（历史数据）不拦截，交由后续流程处理。"""
    service = _service()
    base = SimpleNamespace(base_type="video")
    service._assert_media_type_allowed(base, "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_upload_media_type.py -v --no-cov`
Expected: FAIL with `AttributeError: 'KnowledgeBaseService' object has no attribute '_assert_media_type_allowed'`

- [ ] **Step 3: Implement**

1. 在 `knowledge_base_service.py` 顶部 import 区补：

```python
from internal.entity.knowledge_entity import KnowledgeBaseType
from internal.entity.upload_file_entity import allowed_extensions_for_base_type, media_type_for_extension
```

（若 `knowledge_entity` 已导入 `KnowledgeBaseType`/`PartitionMode`，仅在既有 import 中确认存在，勿重复。）

2. 将 `upload_document` 改为：

```python
    def upload_document(
            self,
            knowledge_base_id,
            file: FileStorage,
            account: Account,
    ) -> KnowledgeDocument:
        """上传素材到知识库并触发索引构建。

        会按扩展名识别 media_type，并按知识库板块类型做硬约束校验。
        """
        knowledge_base = self.get_accessible_base(knowledge_base_id, account)

        cos_service = self._get_cos_service()
        upload_file = cos_service.upload_file(file=file, only_image=False, account=account)

        extension = (upload_file.extension or "").lower()
        media_type = media_type_for_extension(extension)
        self._assert_media_type_allowed(knowledge_base, extension)

        document = self.create(
            KnowledgeDocument,
            knowledge_base_id=knowledge_base.id,
            owner_account_id=account.id,
            name=upload_file.name,
            content_type="document",
            source_type=KnowledgeCreatedFrom.MANUAL_UPLOAD.value,
            source_id=str(upload_file.id),
            upload_file_id=upload_file.id,
            media_type=media_type,
            parse_profile={},
            metadata_={
                "upload_file_id": str(upload_file.id),
                "operation_context": OperationContext.USER.value,
            },
            character_count=0,
            status=DocumentStatus.WAITING.value,
        )

        indexing_service = self._get_knowledge_indexing_service()
        indexing_service.build_document(document.id, account)

        return document

    @staticmethod
    def _assert_media_type_allowed(knowledge_base: KnowledgeBase, extension: str) -> None:
        """板块类型硬约束：扩展名必须属于该板块允许的媒体类型。

        板块 base_type 为空时视为 mixed（兼容存量库）；扩展名为空时不拦截。
        """
        normalized = (extension or "").strip().lower()
        if not normalized:
            return
        base_type = getattr(knowledge_base, "base_type", None) or KnowledgeBaseType.MIXED.value
        allowed = allowed_extensions_for_base_type(base_type)
        if normalized not in allowed:
            raise ValidateErrorException(
                f"当前知识库不允许上传 .{normalized} 文件",
                {"file": [f"板块类型 {base_type} 允许的扩展名：{'/'.join(allowed)}"]},
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_upload_media_type.py test/internal/service/test_knowledge_base_service.py test/internal/service/test_knowledge_base_type.py -v --no-cov`
Expected: PASS（新测试 5 passed，既有测试无回归）

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/knowledge_base_service.py api/test/internal/service/test_knowledge_upload_media_type.py
git commit -m "feat(knowledge): enforce base type constraint on document upload"
```

---

## Task 7: 索引链路按 media_type 分支（多媒体直达入库）

**Files:**
- Modify: `api/internal/service/knowledge_indexing_service.py`
- Test: `api/test/internal/service/test_knowledge_media_ingest.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# api/test/internal/service/test_knowledge_media_ingest.py
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.service.knowledge_indexing_service import KnowledgeIndexingService
from internal.service.knowledge_media_extractor_service import MediaSegment


@contextmanager
def _auto_commit():
    yield


class _QueryStub:
    """支持 filter/update/one_or_none 的查询桩。"""

    def __init__(self, one_or_none_result=None):
        self._one_or_none = one_or_none_result

    def filter(self, *_a, **_kw):
        return self

    def update(self, *_a, **_kw):
        return 1

    def one_or_none(self):
        return self._one_or_none


class _SessionStub:
    """按调用顺序返回查询桩；队列耗尽返回默认桩。"""

    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_a, **_kw):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()


class _FakeMediaExtractor:
    def __init__(self, segments):
        self.segments = segments
        self.calls = []

    def extract(self, document, upload_file):
        self.calls.append((document, upload_file))
        return self.segments


class _FakeVectorService:
    def __init__(self):
        self.indexed = []

    def index_segment(self, segment, knowledge_base):
        self.indexed.append(segment.content)
        return str(segment.id)


def _build_service(media_segments):
    """构造索引服务；upload_file 查询由 session 队列首个桩返回。"""
    updates = []
    created_segments = []
    extractor = _FakeMediaExtractor(media_segments)
    vector_service = _FakeVectorService()
    upload_file = SimpleNamespace(id=uuid4(), key="2026/09/14/a.mp4", name="a.mp4")
    session = _SessionStub([_QueryStub(one_or_none_result=upload_file)])

    service = KnowledgeIndexingService(
        db=SimpleNamespace(session=session, auto_commit=lambda: _auto_commit()),
        file_extractor=SimpleNamespace(),
        embeddings_service=SimpleNamespace(calculate_token_count=lambda text: len(text)),
        jieba_service=SimpleNamespace(extract_keywords=lambda text, n: ["kw"]),
        knowledge_vector_service=vector_service,
        media_extractor=extractor,
    )
    service.update = lambda instance, **kwargs: updates.append(kwargs) or instance  # type: ignore[assignment]
    service.create = lambda model, **kwargs: created_segments.append(kwargs) or SimpleNamespace(id=uuid4(), **kwargs)  # type: ignore[assignment]
    return service, extractor, vector_service, created_segments, updates


def _document(media_type="video"):
    return SimpleNamespace(
        id=uuid4(),
        media_type=media_type,
        knowledge_base_id=uuid4(),
        owner_account_id=uuid4(),
        upload_file_id=uuid4(),
        knowledge_base=SimpleNamespace(id=uuid4()),
    )


def test_media_document_creates_one_segment_per_media_segment():
    service, extractor, vector_service, created, updates = _build_service([
        MediaSegment(content="场景一：产品特写", metadata={"media_type": "video", "scene_index": 1}),
        MediaSegment(content="场景二：用户使用", metadata={"media_type": "video", "scene_index": 2}),
    ])

    service._build_media_document(_document("video"))

    assert len(created) == 2
    assert created[0]["content"] == "场景一：产品特写"
    assert created[0]["metadata_"] == {"media_type": "video", "scene_index": 1}
    assert created[0]["position"] == 1
    assert created[1]["position"] == 2
    assert vector_service.indexed == ["场景一：产品特写", "场景二：用户使用"]


def test_media_document_records_parse_profile_tier1():
    service, _extractor, _vector, _created, updates = _build_service([
        MediaSegment(content="唯一片段", metadata={}),
    ])

    service._build_media_document(_document("image"))

    profiles = [u["parse_profile"] for u in updates if "parse_profile" in u]
    assert profiles, "应写入 parse_profile"
    assert profiles[-1]["tier1"]["status"] == "completed"
    assert profiles[-1]["tier1"]["media_type"] == "image"
    assert profiles[-1]["tier1"]["segment_count"] == 1


def test_media_document_does_not_call_text_splitting():
    """多媒体不走文本切分：file_extractor 不应被调用。"""
    file_extractor_calls = []
    service, _extractor, _vector, _created, _updates = _build_service([
        MediaSegment(content="唯一片段", metadata={}),
    ])
    service.file_extractor = SimpleNamespace(
        load=lambda *a, **k: file_extractor_calls.append("load")
    )

    service._build_media_document(_document("image"))

    assert file_extractor_calls == []


def test_media_document_with_no_segments_raises():
    service, _extractor, _vector, _created, _updates = _build_service([])

    with pytest.raises(Exception):
        service._build_media_document(_document("video"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_media_ingest.py -v --no-cov`
Expected: FAIL（`KnowledgeIndexingService` 无 `media_extractor` 参数、无 `_build_media_document`）

- [ ] **Step 3: Implement**

在 `knowledge_indexing_service.py` 中：

1. import 区补：

```python
from internal.entity.knowledge_entity import DocumentMediaType
from internal.model import UploadFile
from internal.service.knowledge_media_extractor_service import KnowledgeMediaExtractorService, MediaSegment
```

（`UploadFile` 若已导入则确认，勿重复。）

2. 类字段增加：

```python
@inject
@dataclass
class KnowledgeIndexingService(BaseService):
    db: SQLAlchemy
    file_extractor: FileExtractor
    embeddings_service: EmbeddingsService
    jieba_service: JiebaService
    knowledge_vector_service: KnowledgeVectorService
    media_extractor: KnowledgeMediaExtractorService
```

3. `build_document` 改为按 `media_type` 分支：

```python
    def build_document(self, document_id: UUID, account) -> None:
        document = self.get(KnowledgeDocument, document_id)
        if document is None:
            raise NotFoundException("知识库文档不存在")

        try:
            self.update(
                document,
                status=DocumentStatus.PARSING.value,
            )

            media_type = getattr(document, "media_type", None) or DocumentMediaType.DOCUMENT.value
            if media_type != DocumentMediaType.DOCUMENT.value:
                logger.info("开始解析多模态素材 document_id=%s media_type=%s", document_id, media_type)
                self._build_media_document(document)
            else:
                logger.info("开始解析知识库文档 document_id=%s", document_id)
                lc_documents = self._parsing(document)

                logger.info("开始分割知识库文档 document_id=%s", document_id)
                lc_segments = self._splitting(document, lc_documents)

                logger.info("开始构建知识库索引 document_id=%s", document_id)
                self._indexing(document, lc_segments)

                logger.info("开始完成知识库文档索引 document_id=%s", document_id)
                self._completed(document, lc_segments)
            logger.info("知识库文档处理完成 document_id=%s", document_id)

        except Exception as e:
            logger.exception("构建知识库文档发生错误 document_id=%s 错误信息:%s", document_id, str(e))
            self.update(
                document,
                status=DocumentStatus.ERROR.value,
                error=str(e),
            )
```

4. 新增多媒体入库与共享收尾方法：

```python
    def _get_upload_file(self, document: KnowledgeDocument) -> UploadFile:
        """取文档关联的上传文件，缺失时抛错。"""
        if not document.upload_file_id:
            raise NotFoundException("当前文档未关联上传文件，无法解析")
        upload_file = self.db.session.query(UploadFile).filter(
            UploadFile.id == document.upload_file_id,
        ).one_or_none()
        if upload_file is None:
            raise NotFoundException("上传文件不存在")
        return upload_file

    def _build_media_document(self, document: KnowledgeDocument) -> None:
        """多模态素材：解析产物即片段，跳过文本切分。"""
        upload_file = self._get_upload_file(document)
        media_segments = self.media_extractor.extract(document, upload_file)
        if not media_segments:
            raise NotFoundException("素材解析未产出可用内容")

        knowledge_base = document.knowledge_base
        if knowledge_base is None:
            raise NotFoundException("知识库不存在")

        segment_ids = []
        for index, item in enumerate(media_segments, start=1):
            segment = self.create(
                KnowledgeSegment,
                knowledge_base_id=document.knowledge_base_id,
                knowledge_document_id=document.id,
                owner_account_id=document.owner_account_id,
                position=index,
                content=item.content,
                keywords=self.jieba_service.extract_keywords(item.content, 10),
                metadata_=item.metadata,
                character_count=len(item.content),
                token_count=self.embeddings_service.calculate_token_count(item.content),
                status=SegmentStatus.INDEXING.value,
                enabled=False,
            )
            self.knowledge_vector_service.index_segment(segment, knowledge_base)
            segment_ids.append(segment.id)

        self.update(document, status=DocumentStatus.INDEXING.value)
        self._finalize_segments(
            document,
            segment_ids,
            parse_profile={
                "tier1": {
                    "status": "completed",
                    "media_type": getattr(document, "media_type", None),
                    "segment_count": len(segment_ids),
                }
            },
        )

    def _finalize_segments(self, document, segment_ids, parse_profile=None) -> None:
        """统一收尾：片段置为完成并启用，文档置为完成。"""
        if segment_ids:
            with self.db.auto_commit():
                self.db.session.query(KnowledgeSegment).filter(
                    KnowledgeSegment.id.in_(segment_ids),
                ).update({
                    "status": SegmentStatus.COMPLETED.value,
                    "enabled": True,
                })

        update_fields = {"status": DocumentStatus.COMPLETED.value}
        if parse_profile is not None:
            update_fields["parse_profile"] = parse_profile
        self.update(document, **update_fields)
```

5. 将既有 `_parsing` 改为复用 `_get_upload_file`（消除重复查询）：

```python
    def _parsing(self, document: KnowledgeDocument) -> list[LCDocument]:
        upload_file = self._get_upload_file(document)

        lc_documents = self.file_extractor.load(upload_file, False, True)

        for lc_document in lc_documents:
            lc_document.page_content = self._clean_extra_text(lc_document.page_content)

        self.update(
            document,
            character_count=sum([len(lc_document.page_content) for lc_document in lc_documents]),
            status=DocumentStatus.SPLITTING.value,
        )

        return lc_documents
```

6. 将既有 `_completed` 改为复用 `_finalize_segments`：

```python
    def _completed(self, document: KnowledgeDocument, lc_segments: list[LCDocument]) -> None:
        segment_ids = [lc_segment.metadata["segment_id"] for lc_segment in lc_segments]

        self.update(
            document,
            character_count=sum([len(seg.page_content) for seg in lc_segments]),
        )
        self._finalize_segments(document, segment_ids)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_media_ingest.py -v --no-cov`
Expected: PASS (3 passed)

- [ ] **Step 5: 修既有测试的构造参数**

`KnowledgeIndexingService` 新增了必填 dataclass 字段 `media_extractor`。**已确认 `api/test/internal/service/test_knowledge_indexing_service.py:79-90` 的 `_build_service` 直接构造该服务**，必须同步补字段，否则该文件全部测试报 `TypeError: missing required positional argument: 'media_extractor'`。

将该文件的 `_build_service` 改为：

```python
def _build_service(db=None, file_extractor=None,
                   embeddings_service=None, jieba_service=None,
                   knowledge_vector_service=None, media_extractor=None):
    return KnowledgeIndexingService(
        db=db or SimpleNamespace(session=SimpleNamespace()),
        file_extractor=file_extractor or SimpleNamespace(),
        embeddings_service=embeddings_service or SimpleNamespace(calculate_token_count=lambda _t: 1),
        jieba_service=jieba_service or SimpleNamespace(extract_keywords=lambda _t, _k: ["kw"]),
        knowledge_vector_service=knowledge_vector_service or SimpleNamespace(
            index_segment=lambda _seg, _kb: str(_seg.id)
        ),
        media_extractor=media_extractor or SimpleNamespace(
            extract=lambda _doc, _file: []
        ),
    )
```

然后运行：

Run: `cd api && python -m pytest test/internal/service/test_knowledge_indexing_service.py test/internal/service/test_knowledge_media_ingest.py -v --no-cov`
Expected: PASS（既有测试无回归）

再全目录排查其他构造点：

Run: `cd api && python -m pytest test/internal/service -q --no-cov 2>&1 | Select-Object -Last 20`
Expected: 无新增失败（对照修改前基线；已知 `test_home_integration.py` 的 3 个 error 属工作区其他在途改动）

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/knowledge_indexing_service.py api/test/internal/service/test_knowledge_media_ingest.py
git commit -m "feat(knowledge): route media documents to direct segment ingestion"
```

---

## Task 8: 回归验证与文档同步

**Files:**
- Modify: `docs/prd/modules/02-knowledge-base.md`
- Modify: `docs/prd/knowledge-base-product-form-design.md`

- [ ] **Step 1: 跑全量后端测试**

Run: `cd api && python -m pytest -q --no-cov 2>&1 | Select-Object -Last 20`
Expected: 无**新增**失败（对照改动前的失败集合；已知 `test_home_integration.py` 等失败属工作区其他在途改动，与本期无关）

- [ ] **Step 2: 验证 DI 可解析**

Run: `cd api && python -c "import sys; sys.path.insert(0,'.'); from pkg.env_loader import load_project_env; load_project_env(); from app.http.app import app; from internal.service.knowledge_indexing_service import KnowledgeIndexingService; from internal.service.knowledge_media_extractor_service import KnowledgeMediaExtractorService; i=app.injector; print('indexing ok:', i.get(KnowledgeIndexingService) is not None); print('extractor ok:', i.get(KnowledgeMediaExtractorService) is not None)"`
Expected: 两行 `ok: True`

- [ ] **Step 3: 更新架构文档**

在 `docs/prd/modules/02-knowledge-base.md` 的 §11.7（P1 新增节）之后新增一节「11.8 多模态素材解析（P2A 已落地）」，说明：

- `KnowledgeMediaExtractorService` 的职责与三个分支（图片视觉摘要 / 音频 ASR / 视频关键帧视觉描述）
- 解析产物 `MediaSegment` 直接映射 `KnowledgeSegment`（content + metadata）
- 索引链路按 `media_type` 分支：文档走 parsing→splitting→indexing；多媒体直达入库
- `upload_document` 的媒体类型识别与板块类型硬约束
- `parse_profile.tier1` 记录 L1 解析状态
- **明确标注 L2 深度解析（视频 ASR 音轨、说话人切分、关键帧视觉向量）未实现，属 P3**

同时把 `docs/prd/knowledge-base-product-form-design.md` §9.2 表中 P2 标记为「部分完成（P2A 多模态入库已完成；P2B 分片上传待做）」。

- [ ] **Step 4: 更新知识图谱**

Run: `cd d:\DEMO\openagent-main && python -m graphify update .`
Expected: 成功更新 `graphify-out/`

- [ ] **Step 5: Commit**

```bash
git add docs/prd/modules/02-knowledge-base.md docs/prd/knowledge-base-product-form-design.md
git commit -m "docs(knowledge): sync P2A multimodal ingest architecture"
```

---

## 验收清单

| # | 验收项 | 验证方式 |
|---|---|---|
| 1 | 共享视觉模块可独立单测 | `test_vision_invoke.py` 通过 |
| 2 | 内置视觉工具复用共享模块且行为不变 | `test_vision_tools_shared.py` + 既有工具测试通过 |
| 3 | 图片可解析为 1 个含视觉摘要的片段 | `test_knowledge_media_extractor_service.py` 图片用例 |
| 4 | 音频可经 ASR 转写为片段；空转写不产出片段 | 音频用例 |
| 5 | 视频按帧产出多个片段，含 scene_index/frame_count | 视频用例 |
| 6 | 单帧视觉失败被跳过，不整体失败 | 视频容错用例 |
| 7 | 板块类型硬约束生效（video 板块拒 pdf） | `test_knowledge_upload_media_type.py` |
| 8 | 多媒体不入文本切分链路 | `test_knowledge_media_ingest.py` |
| 9 | 多媒体片段写入向量库 | 同上（断言 vector_service.indexed） |
| 10 | `parse_profile.tier1` 被记录 | 同上（断言 update 收到 parse_profile） |
| 11 | DI 全链路可解析 | Task 8 Step 2 |
| 12 | 无新增回归 | Task 8 Step 1 |
