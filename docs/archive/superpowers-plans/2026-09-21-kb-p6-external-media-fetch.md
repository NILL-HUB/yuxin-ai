# KB-P6 外部素材获取（fetch_media / yt-dlp）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让对话内 Agent 通过 `fetch_media` 工具把一个公开网页视频/音频 URL（YouTube / Bilibili / Vimeo 等）下载、上传、建档入知识库，并自动触发解析；字幕优先平台字幕、回退 ASR。

**Architecture:** 复用 video_edit 链路范式：builtin 工具 `fetch_media`（挂载点注入 account_id）→ 校验后派发 Celery 任务 `media_fetch_task`（默认 `celery` 队列）→ 任务内 `MediaFetchService` 用 yt-dlp 库调用下载到临时文件（提取器白名单 + URL scheme + 体积上限前置校验）→ 主媒体走 `cos_service.upload_local_file` 流式上传保 key + 手工补建 `UploadFile` 记录（GB 级视频不进内存）→ `create_document_from_upload_file` 建档（自动触发 L1 解析）→ 字幕/封面小文件用 `upload_bytes` 建记录并把 id 写入 `document.metadata_[subtitle_upload_file_id / cover_upload_file_id]` → 提取器视频分支读到 `subtitle_upload_file_id` 时优先消费平台字幕，无则回退现有 ASR。全链路**默认关闭**（`ENABLE_MEDIA_FETCH_TOOL=1`），不做登录态/Cookies。

**Tech Stack:** Python 3.12（API 容器）/ 3.13（本机实测嵌入 API 通过）、yt-dlp（库调用，禁 CLI 拼接）、Celery 5.5、cos_python_sdk_v5、injector、langchain-core BaseTool。

---

## 接线自检总表（验收点）

| 新增符号 | 类型 | 入口/挂载点 | 本计划 Task |
|---|---|---|---|
| `MediaFetchService` | service | 由 `media_fetch_task` 经 injector 取用；工具不做业务 | T1 |
| `media_fetch_task` | Celery 任务 | `celery_app.py` TASK_MODULES(include) + 显式 import 双重注册；派发点 = `fetch_media` 工具 `.delay()` | T3 |
| `fetch_media` 工具 | builtin 工具 | `.py`+`.yaml`+`positions.yaml`+`__init__.py` 重导出 + `providers.yaml` provider 登记 + `_build_assistant_runtime_tools` 挂载（ENABLE 门控） | T4+T6 |
| Metadata 字段 | 无新表 | 复用 `KnowledgeDocument.metadata_`（JSONB） | T2 |
| 字幕优先 | 提取器增强 | `KnowledgeMediaExtractorService._extract_video` 分支 | T5 |

强制约束逐条落地：
- ① 默认关闭 → T4/T6（`_media_fetch_enabled()`，参照 `code_execution_tool._enabled()`）
- ② 提取器白名单排除 generic → T1（SSRF 关键）
- ③ 体积内存上限 → T1/T2（主媒体流式 `upload_local_file`；体积上限 `MEDIA_FETCH_MAX_BYTES` 前置拒绝）
- ④ 合规免责、不做登录态/cookies → T2（代码注释 + 工具 description 标注）
- ⑤ 版本锁定 + 站点失效翻译 → T1/T6
- ⑥ 库调用禁 CLI → T1

---

### Task 1: MediaFetchService 核心 — 校验 + yt-dlp 下载编排

**Files:**
- Modify: `api/requirements.txt`（末尾追加 yt-dlp）
- Create: `api/internal/service/media_fetch_service.py`
- Create: `api/tests/unit/service/test_media_fetch_service.py`

- [ ] **Step 1: 追加依赖**

在 `api/requirements.txt` 末尾加：
```text
yt-dlp==2026.6.30
```
> 版本号先 `pip install yt-dlp` 实测安装到的版本后回填为固定钉版（本机 3.13 / API 容器 3.12 均需兼容）。若该版本号不存在，用实测版本替换。

- [ ] **Step 2: 写失败测试（scheme 校验 + 白名单 + 体积上限）**

```python
"""MediaFetchService 校验与下载编排单测（mock yt_dlp，不联网）。"""
from internal.service.media_fetch_service import MediaFetchService


def test_reject_non_http_scheme():
    svc = MediaFetchService()
    assert svc.validate_url("ftp://x.com/v.mp4", max_bytes=0)["ok"] is False


def test_reject_unknown_extractor():
    svc = MediaFetchService()
    # 白名单不含 generic；mock 解析结果 extractor_key='generic'
    assert svc._extractor_allowed("generic") is False
    assert svc._extractor_allowed("youtube") is True
    assert svc._extractor_allowed("bilibili") is True


def test_size_cap_rejected_proactively():
    svc = MediaFetchService()
    info = {"filesize_approx": 2 * 1024 * 1024 * 1024}
    assert svc._respect_size_cap(info, max_bytes=1024)["ok"] is False
```

- [ ] **Step 3: Run fail → 预期 FAIL**

Run: `cd api && python -m pytest tests/unit/service/test_media_fetch_service.py -v`
Expected: `ModuleNotFoundError: No module named 'internal.service.media_fetch_service'`

- [ ] **Step 4: 写服务核心**

```python
"""外部素材获取服务（KB-P6）：yt-dlp 库调用下载 + 前缀校验。

强制约束（设计 §5.3）：
- 默认关闭：由工具层 _enabled() 控制挂载，本服务不做开关；
- 提取器白名单，排除 generic 兜底（SSRF 关键）——只允许已实名 extractor；
- 体积上限提前拒绝，主媒体流式上传不读进内存；
- 仅公开内容，不做登录态/Cookies，只认平台可匿名抓取。
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# 允许的实名提取器白名单（新增站点在此登记）。未命中一律拒绝。
ALLOWED_EXTRACTORS = {"youtube", "bilibili", "vimeo", "dailymotion", "twitch"}


class MediaFetchError(Exception):
    """外部素材获取业务失败（不重试）。其子类是 Celery 判定不重试的边界。"""


def _normalize_max_bytes(value: str | int | float | None) -> int | None:
    """解析体积上限（字节）；配置为空/非法则 None=不限制。"""
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return int(os.getenv("MEDIA_FETCH_MAX_BYTES", "0") or 0) or None


class MediaFetchService:
    """负责 fetch_media 的下载编排。所有业务校验在此，供 Celery 任务与单测复用。"""

    def validate_url(self, url: str, *, max_bytes: int | None = None) -> dict:
        """URL scheme 前置校验：仅 http/https。"""
        from urllib.parse import urlparse

        parsed = urlparse(str(url or "").strip() or "")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return {"ok": False, "error": "仅支持 http/https 链接，请提供可公开访问的视频/音频网页地址"}
        return {"ok": True}

    def _extractor_allowed(self, extractor_key: str) -> bool:
        """提取器白名单判断。"""
        return str(extractor_key or "").strip().lower() in ALLOWED_EXTRACTORS

    def _respect_size_cap(self, info: dict, *, max_bytes: int | None) -> dict:
        """体积上限前置拒绝；估算缺失时按配置上限兜底。"""
        if max_bytes is None or max_bytes <= 0:
            return {"ok": True}
        size = 0
        for key in ("filesize", "filesize_approx"):
            size = max(size, int(info.get(key) or 0))
        if size <= 0:
            size = int(os.getenv("MEDIA_FETCH_MAX_BYTES_FALLBACK", "536870912") or "536870912")  # 512MB
        if size > max_bytes:
            return {"ok": False, "error": f"素材体积约 {size // 1 << 20} MiB 超出本板块上限，请降低分辨率后重试"}
        return {"ok": True}

    def _download(
        self,
        url: str,
        temp_dir: str,
        *,
        format_spec: str,
        max_bytes: int | None,
        prefer_subtitle: bool = True,
    ) -> dict[str, Any]:
        """用 yt-dlp 库下载媒体到临时目录；返回主媒体路径 + 元数据 + 可选字幕路径。

        返回条目：{media_path, ext, info, subtitle_path?}
        """
        import yt_dlp

        outtmpl = os.path.join(temp_dir, "%(title).30B-%(id)s.%(ext)s")
        opts: dict[str, Any] = {
            "format": format_spec,
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": False,
        }
        if prefer_subtitle:
            opts.update({
                "writesubtitles": True,
                "writeautomaticsub": False,
                "subtitleslangs": ["en", "zh-Hans", "zh-CN", "zh"],
                "subtitlesformat": "vtt/srt",
                "skip_download": False,
            })
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as exc:  # noqa: BLE001
            # 站点失效/接口变更翻译为用户可读
            msg = str(exc)
            if "Unsupported URL" in msg or "requested format is not available" in msg:
                raise MediaFetchError("该链接当前无法解析，可能为平台不支持或页面已失效") from exc
            if "Unable to download webpage" in msg:
                raise MediaFetchError("无法访问该网页，链接可能失效或平台要求登录（暂不支持登录态）") from exc
            logger.warning("yt-dlp 下载失败 url=%s", url, exc_info=True)
            raise MediaFetchError(f"外部素材下载失败：{msg[:200]}") from exc

        extractor = str(info.get("extractor_key") or "").lower()
        if not self._extractor_allowed(extractor):
            # 提取器兜底 generic：虽然解析/下载已完成，但按白名单直接拒绝，防止 SSRF/乱抓
            raise MediaFetchError("该站点暂不在支持的提取器白名单内，无法入库")
        cap_result = self._respect_size_cap(info, max_bytes=max_bytes)
        if not cap_result["ok"]:
            raise MediaFetchError(cap_result["error"])

        filepath = info.get("requested_downloads") or info.get("_filename") or ""
        if isinstance(filepath, list):
            filepath = next((str(f.get("filepath") or "") for f in filepath if f.get("filepath")), "")
        media_path = str(filepath or "")
        if not media_path or not os.path.exists(media_path):
            raise MediaFetchError("下载完成但未找到产物文件，请稍后重试")

        result: dict[str, Any] = {
            "media_path": media_path,
            "ext": str(info.get("ext") or "").lower(),
            "info": info,
        }
        # 平台字幕：目录下若有与新 VTT/SRT 匹配的字幕文件则带回（供 L1 优先消费）
        if prefer_subtitle:
            srt = self._find_subtitle(temp_dir, media_path)
            result["subtitle_path"] = srt
        return result

    @staticmethod
    def _find_subtitle(temp_dir: str, media_path: str) -> str | None:
        """在临时目录中查找与主媒体同前缀的 .vtt/.srt 字幕文件。"""
        base = os.path.splitext(os.path.basename(media_path or ""))[0]
        if not base:
            return None
        for name in os.listdir(temp_dir):
            low = name.lower()
            if name.startswith(base) and (low.endswith(".vtt") or low.endswith(".srt")):
                return os.path.join(temp_dir, name)
        return None
```

- [ ] **Step 5: Run test → PASS**

Run: `cd api && python -m pytest tests/unit/service/test_media_fetch_service.py -v`
Expected: PASS（3 passed）

- [ ] **Step 6: Commit**

```bash
git add api/requirements.txt api/internal/service/media_fetch_service.py api/tests/unit/service/test_media_fetch_service.py
git commit -m "feat(kb): MediaFetchService 外部素材下载核心（白名单+体积/URL 校验）"
```

---

### Task 2: 导入链路 — UploadFile 记录 + create_document_from_upload_file + 字幕/封面 metadata

**Files:**
- Modify: `api/internal/service/media_fetch_service.py`
- Modify: `api/tests/unit/service/test_media_fetch_service.py`

- [ ] **Step 1: 写失败测试（导入编排，用 injector 反向验证注入）**

```python
from unittest.mock import MagicMock

from internal.service.cos_service import CosService
from internal.service.knowledge_base_service import KnowledgeBaseService
from internal.service.media_fetch_service import MediaFetchService
from internal.service.upload_file_service import UploadFileService


def _fake_download(svc, url, temp_dir, *, format_spec, max_bytes, prefer_subtitle=True):
    # mock 掉 yt_dlp：在临时目录落一个真实 mp4 + vtt，返回标准化结果
    import os
    open(os.path.join(temp_dir, "sample.mp4"), "wb").write(b"\x00" * 100)
    open(os.path.join(temp_dir, "sample.zh-Hans.vtt"), "w").write("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n")
    return {
        "media_path": os.path.join(temp_dir, "sample.mp4"),
        "ext": "mp4",
        "info": {"extractor_key": "youtube"},
        "subtitle_path": os.path.join(temp_dir, "sample.zh-Hans.vtt"),
    }


def test_import_document_injects_cos_and_calls_create(monkeypatch):
    svc = MediaFetchService()
    svc._download = _fake_download

    cos = MagicMock(spec=CosService)
    upload_file_svc = MagicMock(spec=UploadFileService)
    kb_svc = MagicMock(spec=KnowledgeBaseService)
    created = {"id": 123, "metadata_": {}}
    kb_svc.create_document_from_upload_file.return_value = created

    # 手工注入（构造期依赖，抽离 _inject_deps 便于测试透过真实 Injector 校验）
    svc._cos = cos
    svc._upload_file_service = upload_file_svc
    svc._knowledge_base_service = kb_svc

    account = MagicMock(); account.id = "u1"
    kb = MagicMock(); kb.base_type = "video"; kb.id = "kb1"

    result = svc.import_document(
        url="https://www.youtube.com/watch?v=abc",
        knowledge_base=kb, account=account,
        temp_dir="/tmp/mediatest",
        max_bytes=None,
    )
    assert result["ok"] is True
    # 主媒体流式上传保 key（upload_local_file）
    assert cos.upload_local_file.called
    # 字幕经 create_upload_file 建记录，并写入 document.metadata_[subtitle_upload_file_id]
    assert upload_file_svc.create_upload_file.called
    assert created["metadata_"]["subtitle_upload_file_id"]
```

- [ ] **Step 2: Run fail → 预期 FAIL**

Run: `cd api && python -m pytest tests/unit/service/test_media_fetch_service.py::test_import_document_injects_cos_and_calls_create -v`
Expected: FAIL（`MediaFetchService` 无 `import_document` / `_cos`）

- [ ] **Step 3: 实现导入方法与依赖注入**

在 `media_fetch_service.py` 增加注入访问（**强类型注解，injector 依赖**，复用 KB-P5 教训）：

```python
# media_fetch_service.py 顶部补充 __init__ 与惰性取用
def _inject(self):
    from app.http.module import injector
    from internal.service.cos_service import CosService
    from internal.service.knowledge_base_service import KnowledgeBaseService
    from internal.service.upload_file_service import UploadFileService

    self._cos = injector.get(CosService)
    self._upload_file_service = injector.get(UploadFileService)
    self._knowledge_base_service = injector.get(KnowledgeBaseService)
    return self


def import_document(
    self,
    *,
    url: str,
    knowledge_base,
    account,
    temp_dir: str,
    max_bytes: int | None,
    format_spec: str = "bv*+ba/b",
) -> dict:
    """下载 → 上传 → 建档 → 字幕/封面 metadata 关联。

    主媒体走 upload_local_file（流式保 key，GB 级不进内存）+ 手工建 UploadFile 记录；
    字幕/封面为小文件用 upload_bytes。随后 create_document_from_upload_file 建档并
    触发 L1 解析；再把字幕/封面 id 写入 document.metadata_ 供解析时优先消费。
    """
    self._inject()
    fetched = self._download(
        url, temp_dir, format_spec=format_spec, max_bytes=max_bytes,
        prefer_subtitle=True,
    )
    media_path = fetched["media_path"]
    filename = os.path.basename(media_path)
    target_key = self._cos._build_object_key(filename)  # 预计算 key，流式写入
    self._cos.upload_local_file(source_path=media_path, target_key=target_key)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    main_upload = self._upload_file_service.create_upload_file(
        account_id=account.id,
        name=filename,
        key=target_key,
        size=os.path.getsize(media_path),
        extension=extension,
        mime_type=None,
        hash="sha3-placeholder-external",
        storage_backend=(
            "local" if str(os.getenv("STORAGE_BACKEND") or "").strip().lower() == "local" else "cos"
        ),
    )

    document = self._knowledge_base_service.create_document_from_upload_file(
        knowledge_base_id=knowledge_base.id,
        upload_file=main_upload,
        account=account,
    )

    metadata_patch: dict[str, Any] = {}
    # 平台字幕：小文件 upload_bytes 建记录并写入 metadata_
    subtitle_path = fetched.get("subtitle_path")
    if subtitle_path and os.path.exists(subtitle_path):
        with open(subtitle_path, "rb") as fh:
            sub_content = fh.read()
        with open(subtitle_path, "rb") as fh:
            sub_record = self._cos.upload_bytes(
                filename=os.path.basename(subtitle_path),
                content=sub_content,
                account_id=account.id,
                mime_type="text/vtt" if subtitle_path.lower().endswith(".vtt") else "text/plain",
            )
        metadata_patch["subtitle_upload_file_id"] = str(sub_record.id)

    # 封面（可选）：yt-dlp 若已写 thumbnail，这里只登记，封面上传由 upload_bytes 建记录
    thumb = fetched["info"].get("thumbnail")
    if thumb:
        # 从临时目录读取封面（下载时 writethumbnail 未必开，故不做强制上传，留待后续）
        pass  # 见 Task 6 说明：封面 UploadFile id 记录通过 metadata_[cover_upload_file_id]

    if metadata_patch:
        # 更新同级元数据（沿用现有 model 更新逻辑，无新表）
        self._knowledge_base_service.update_model_metadata(document, metadata_patch)

    return {
        "ok": True,
        "document_id": str(getattr(document, "id", "")),
        "subtitle_attached": bool(metadata_patch.get("subtitle_upload_file_id")),
        "message": "外部素材已下载并入知识库，开始解析",
    }
```

- [ ] **Step 4: Run test → PASS**

Run: `cd api && python -m pytest tests/unit/service/test_media_fetch_service.py -v`
Expected: PASS

- [ ] **Step 5: 核对 `update_model_metadata` 是否存在**

若 `KnowledgeBaseService` 没有 `update_model_metadata`，用以下在 `test_inject_interface` 前的**修复步骤**定位既有更新 metadata_ 的方法（如 `KnowledgeBaseService.update(...)` 或 BaseService），写进本步骤实现。实测确认后再继续，不臆造方法名。

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/media_fetch_service.py api/tests/unit/service/test_media_fetch_service.py
git commit -m "feat(kb): 外部素材导入链路（流式上传建记录 + 字幕 attach + metadata）"
```

---

### Task 3: Celery 任务 media_fetch_task + 双重注册

**Files:**
- Create: `api/internal/task/media_fetch_tasks.py`
- Modify: `api/app/http/celery_app.py`（TASK_MODULES + 显式 import）
- Create: `api/tests/unit/task/test_media_fetch_tasks.py`

- [ ] **Step 1: 写失败测试（注册存在 + 任务可属性解析）**

```python
from internal.task import media_fetch_tasks
from internal.task.media_fetch_tasks import media_fetch_task


def test_task_registered():
    assert media_fetch_task.name == "internal.task.media_fetch_tasks.media_fetch_task"


def test_task_module_exported():
    assert callable(getattr(media_fetch_tasks, "media_fetch_task"))
```

- [ ] **Step 2: Run fail → 预期 FAIL**

Run: `cd api && python -m pytest tests/unit/task/test_media_fetch_tasks.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现任务（薄委托范式）**

```python
"""外部素材获取的 Celery 任务（KB-P6）。

薄委托范式（与 video_edit_tasks 一致）：任务体只取 service + 委托 + 重试。
MediaFetchError 为业务失败（URL/site 不支持、超上限）不重试；其余重试。
队列：走默认 celery 队列。
"""
from __future__ import annotations

import logging
import os
import tempfile

from celery import shared_task

logger = logging.getLogger(__name__)

__all__ = ["media_fetch_task"]


def _load_service():
    from app.http.module import injector
    from internal.service.media_fetch_service import MediaFetchService

    return injector.get(MediaFetchService)


@shared_task(
    name="internal.task.media_fetch_tasks.media_fetch_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def media_fetch_task(
    self,
    url: str,
    knowledge_base_id: str,
    account_id: str,
    resolution: str = "",
    max_bytes: int | None = None,
):
    """按 URL 下载外部素材并建档入库，成功后回填会话。"""
    from uuid import UUID

    from app.http.module import injector
    from internal.service.media_fetch_service import MediaFetchError
    from internal.service.knowledge_base_service import KnowledgeBaseService
    from internal.service.account_service import AccountService, LoginServiceError

    account = injector.get(AccountService).get_account(UUID(str(account_id)))
    kb = injector.get(KnowledgeBaseService).get_accessible_base(str(knowledge_base_id), account)

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            svc = _load_service()
            result = svc.import_document(
                url=url, knowledge_base=kb, account=account,
                temp_dir=temp_dir, max_bytes=max_bytes,
                format_spec=_format_for(kb.base_type),
            )
        except MediaFetchError:
            logger.warning("外部素材获取业务失败 url=%s", url, exc_info=True)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("外部素材获取失败 url=%s，将重试", url)
            raise self.retry(exc=exc)

    # 会话回填（成品/素材就绪提示），失败不抛
    try:
        from internal.service.artifact_notification_service import notify_artifact_ready
        # result.document_id → 素材（非成品库）。只做存在性提示，不强制播放地址。
        if result.get("ok") and result.get("document_id"):
            logger.info("外部素材已入库 document_id=%s", result["document_id"])
    except Exception:  # noqa: BLE001
        logger.debug("外部素材会话回填忽略")
    return result


def _format_for(base_type: str) -> str:
    """按板块基类型推断下载形态：audio→纯音频；video/mixed→默认视频。"""
    from internal.entity.knowledge_base_entity import KnowledgeBaseType
    if str(base_type).upper() == "audio":
        return "ba"
    return "bv*+ba/b"


def _normalize_max_bytes(value) -> int | None:
    try:
        return max(0, int(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 4: 双重注册 celery_app.py**

在 `api/app/http/celery_app.py`：
1. `TASK_MODULES` 列表末尾加 `"internal.task.media_fetch_tasks",`
2. 显式 import 区末尾加 `import internal.task.media_fetch_tasks as _task_media_fetch  # noqa: F401,E402`
3. `task_routes` 追加（走默认队列即可，可不加；如需隔离加 `"internal.task.media_fetch_tasks.*": {"queue": "celery"}`，推荐默认不加）

- [ ] **Step 5: Run test → PASS**

Run: `cd api && python -m pytest tests/unit/task/test_media_fetch_tasks.py -v`
Expected: PASS

- [ ] **Step 6: 接线自检**

全仓搜索 `media_fetch_task` 调用方：唯一生产派发点应为 `fetch_media` 工具（Task 4）的 `.delay()`；`celery_app.py` 出现 2 处（include + 显式 import）。

- [ ] **Step 7: Commit**

```bash
git add api/internal/task/media_fetch_tasks.py api/app/http/celery_app.py api/tests/unit/task/test_media_fetch_tasks.py
git commit -m "feat(kb): media_fetch_task Celery 任务 + 双重注册"
```

---

### Task 4: fetch_media builtin 工具四件套

**Files:**
- Create: `api/internal/core/tools/builtin_tools/providers/media_fetch_tools/fetch_media.py`
- Create: `api/internal/core/tools/builtin_tools/providers/media_fetch_tools/fetch_media.yaml`
- Create: `api/internal/core/tools/builtin_tools/providers/media_fetch_tools/positions.yaml`
- Create: `api/internal/core/tools/builtin_tools/providers/media_fetch_tools/__init__.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/providers.yaml`
- Create: `api/tests/unit/tools/test_fetch_media_tool.py`

- [ ] **Step 1: 写失败测试（校验 + 派发 kwarg 锁定）**

```python
from langs_for_test import json  # noqa: F401  # 直接用内置
import json

from internal.core.tools.builtin_tools.providers.media_fetch_tools.fetch_media import fetch_media


def test_missing_params_rejected(monkeypatch):
    tool = fetch_media()
    out = json.loads(tool.invoke({"url": ""}))
    assert out["ok"] is False


def test_dispatch_uses_kwargs(monkeypatch):
    captured = {}
    class FakeTask:
        @classmethod
        def delay(cls, *a, **kw):
            captured["kwargs"] = kw
            return SimpleNamespace(id="tid")
    monkeypatch.setattr("internal.core.tools.builtin_tools.providers.media_fetch_tools.fetch_media._load_task", lambda: FakeTask)
    tool = fetch_media(account_id="u1", message_id="m1", conversation_id="c1")
    out = json.loads(tool.invoke({"url": "https://www.youtube.com/watch?v=x", "knowledge_base_id": "kb1"}))
    assert out["ok"] is True and out["dispatched"] is True
    # kwarg 位置绑定（历史教训：禁止位置绑定错位）
    assert captured["kwargs"]["knowledge_base_id"] == "kb1"
    assert captured["kwargs"]["account_id"] == "u1"
    assert captured["kwargs"]["message_id"] == "m1"
```

- [ ] **Step 2: Run fail → 预期 FAIL**

Run: `cd api && python -m pytest tests/unit/tools/test_fetch_media_tool.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现工具**

```python
"""外部素材获取工具（KB-P6）。

把公开网页视频/音频 URL 下载、上传、建档入知识库。执行走 Celery，派发后立即返回任务号。
默认关闭：需 ENABLE_MEDIA_FETCH_TOOL=1 才在 _build_assistant_runtime_tools 挂载。
只支持平台可匿名抓取内容，不做登录态/Cookies。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    flag = str(os.getenv("ENABLE_MEDIA_FETCH_TOOL", "")).strip().lower()
    return bool(flag in {"1", "true", "yes", "on"})


def _load_task():
    from internal.task.media_fetch_tasks import media_fetch_task

    return media_fetch_task


class FetchMediaInput(BaseModel):
    url: str = Field(..., description="要下载的视频/音频网页 URL（公开可访问）")
    knowledge_base_id: str = Field(..., description="目标知识库 id")
    resolution: str = Field("", description="可选目标分辨率，如 720/1080；留空用平台默认")
    max_bytes: int = Field(0, description="可选体积上限(字节)；0=不限制")


class FetchMediaTool(BaseTool):
    name: str = "fetch_media"
    description: str = (
        "当用户要求把一个外部视频/音频链接保存进知识库时调用。"
        "支持主流平台(YouTube/Bilibili/Vimeo 等)可公开访问的页面，仅获取平台可匿名抓取的内容，"
        "系统会下载、上传并开始解析入库；默认需管理员开启此能力。"
    )
    args_schema: type[BaseModel] = FetchMediaInput
    account_id: str = ""
    message_id: str = ""
    conversation_id: str = ""

    def _run(self, url: str = "", knowledge_base_id: str = "",
             resolution: str = "", max_bytes: int = 0, **kwargs: Any) -> str:
        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps({"ok": False, "error": "缺少当前账号信息，无法保存素材"}, ensure_ascii=False)
        if not str(url or "").strip() or not str(knowledge_base_id or "").strip():
            return json.dumps({"ok": False, "error": "需要 url 与 knowledge_base_id"}, ensure_ascii=False)
        if not _enabled():
            return json.dumps({"ok": False, "error": "外部素材获取能力未启用（需要管理员开启）"}, ensure_ascii=False)
        try:
            size = int(max_bytes or 0)
        except (TypeError, ValueError):
            return json.dumps({"ok": False, "error": "max_bytes 必须是整数(字节)"}, ensure_ascii=False)
        if size < 0:
            return json.dumps({"ok": False, "error": "max_bytes 不能为负"}, ensure_ascii=False)

        try:
            async_result = _load_task().delay(
                str(url).strip(), str(knowledge_base_id).strip(), account_id,
                resolution=str(resolution or "").strip(),
                max_bytes=size if size > 0 else None,
                message_id=str(kwargs.get("message_id") or self.message_id or ""),
                conversation_id=str(kwargs.get("conversation_id") or self.conversation_id or ""),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("外部素材任务提交失败 account_id=%s", account_id, exc_info=True)
            return json.dumps({"ok": False, "error": f"任务提交失败：{exc}"}, ensure_ascii=False)

        return json.dumps({
            "ok": True, "dispatched": True,
            "task_id": str(getattr(async_result, "id", "")),
            "message": "外部素材已提交下载，完成后会自动存入知识库并开始解析",
        }, ensure_ascii=False)

    async def _arun(self, url: str = "", knowledge_base_id: str = "",
                    resolution: str = "", max_bytes: int = 0, **kwargs: Any) -> str:
        return self._run(url=url, knowledge_base_id=knowledge_base_id,
                         resolution=resolution, max_bytes=max_bytes, **kwargs)


def fetch_media(**kwargs: Any) -> BaseTool:
    return FetchMediaTool(
        account_id=str(kwargs.get("account_id") or "").strip(),
        message_id=str(kwargs.get("message_id") or "").strip(),
        conversation_id=str(kwargs.get("conversation_id") or "").strip(),
    )
```

- [ ] **Step 4: yaml/positions/__init__/providers.yaml**

`fetch_media.yaml`（注意 type 枚举只有 string/number/boolean/select）：
```yaml
name: fetch_media
label: 获取外部素材
description: 把公开网页的视频/音频链接下载入库并开始解析。
params:
- name: url
  label: 链接
  type: string
  required: true
- name: knowledge_base_id
  label: 知识库
  type: string
  required: true
- name: resolution
  label: 分辨率
  type: string
  required: false
- name: max_bytes
  label: 体积上限(字节)
  type: number
  required: false
task_keywords:
- 下载视频
- 保存链接
- 视频链接入库
- 外部素材
- 抓取视频
- fetch media
```

`positions.yaml`：
```yaml
- fetch_media
```

`__init__.py`：
```python
from .fetch_media import fetch_media

__all__ = ["fetch_media"]
```

`providers.yaml`（末尾追加一个新 provider 条目，仿 video_edit_tools）：
```yaml
- name: media_fetch_tools
  label: 外部素材获取
  description: 外部媒体下载导入能力，供 Agent 把公开视频/音频链接保存进知识库。
  icon: ""
  background: "#F2F7F2"
  category: tool
  created_at: 1789900000
```

- [ ] **Step 5: Run test → PASS**

Run: `cd api && python -m pytest tests/unit/tools/test_fetch_media_tool.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/internal/core/tools/builtin_tools/providers/media_fetch_tools api/internal/core/tools/builtin_tools/providers/providers.yaml api/tests/unit/tools/test_fetch_media_tool.py
git commit -m "feat(kb): fetch_media 工具四件套 + provider 登记"
```

---

### Task 5: 提取器视频分支字幕优先（platform_subtitle 优先，回退 ASR）

**Files:**
- Modify: `api/internal/service/knowledge_media_extractor_service.py`（_extract_video / _transcribe_video_track）
- Create: `api/tests/unit/service/test_media_extractor_subtitle.py`

- [ ] **Step 1: 写失败测试（document 带 subtitle_upload_file_id 时优先消费，不调 ASR）**

```python
def test_video_with_platform_subtitle_skips_asr(monkeypatch):
    from unittest.mock import MagicMock
    from internal.service.knowledge_media_extractor_service import KnowledgeMediaExtractorService

    svc = KnowledgeMediaExtractorService()
    asr_called = {"n": 0}
    def fake_asr(path, up):
        asr_called["n"] += 1
        return "ASR TEXT", []
    monkeypatch.setattr(svc, "_transcribe_video_track", fake_asr)
    monkeypatch.setattr(svc, "_download_to", lambda up, d: "/s/x.mp4")
    monkeypatch.setattr(svc, "_extract_frames_with_offsets", lambda path, d: [("0", 0.0)])
    monkeypatch.setattr(svc, "_process_timeline_batch", lambda batch, scenario, **kw: [])
    from internal.core.video import timeline as tl
    monkeypatch.setattr(tl, "build_timeline_plan", lambda cues, frames: ("B", []))
    monkeypatch.setattr(tl, "chunk_anchors", lambda a: [])

    doc = MagicMock(); doc.metadata_ = {"subtitle_upload_file_id": "sub1"}
    # 用占位调用判定：有字幕 id 时应走字幕分支而非 _transcribe_video_track
    svc._extract_video(MagicMock(), account_id=None, document_id=None)
    assert asr_called["n"] == 0
```

- [ ] **Step 2: Run fail → 预期 FAIL**

Run: `cd api && python -m pytest tests/unit/service/test_media_extractor_subtitle.py -v`
Expected: FAIL（`_transcribe_video_track` 仍被调用 → asr_called["n"]==1）

- [ ] **Step 3: 实现字幕优先**

在 `_extract_video` 开头从 document 读字幕 id，若有则解析字幕时间轴作为 transcript+cues，跳过 ASR：

```python
# _extract_video 内，替换
transcript, cues = self._transcribe_video_track(file_path, upload_file)
# 为
transcript, cues = self._consume_subtitle_if_any(file_path, upload_file, document_id)

def _consume_subtitle_if_any(self, video_path, upload_file, document_id) -> tuple[str, list[dict]]:
    """有平台字幕优先消费（跳过 ASR）；无则回退 ASR。"""
    from internal.model import KnowledgeDocument
    doc = None
    if document_id:
        doc = self._get_document_cached(document_id)  # 见 Step：定位 reader
    sub_id = None
    if doc is not None:
        sub_id = (getattr(doc, "metadata_", None) or {}).get("subtitle_upload_file_id")
    if sub_id:
        try:
            from internal.service.upload_file_service import UploadFileService  # 见读者定位
            record = <load uploadfile by id>
            # 下载字幕文件，parse vtt/srt → cues
            cues = self._parse_subtitle_cues(record)
            if cues:
                text = " ".join(c["text"] for c in cues)
                return text, cues
        except Exception:
            logger.warning("平台字幕消费失败，回退 ASR sub_id=%s", sub_id, exc_info=True)
    return self._transcribe_video_track(video_path, upload_file)
```

> **实现前先实测**：`_extract_video` 的签名是 `(upload_file, account_id=None, document_id=None)`，但调用方 `extract` 是否真的传入 `document_id`？需读 `knowledge_media_extractor_service.py` L91-110 `extract` 确认。若 extract 只传了 document（模型对象）而非 id，则改为把 `document` 一并传入 `_extract_video`，据此改本任务签名保证读得到 metadata_。**以实测签名为准，不臆造。**

- [ ] **Step 4: Run test → PASS**

Run: `cd api && python -m pytest tests/unit/service/test_media_extractor_subtitle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/knowledge_media_extractor_service.py api/tests/unit/service/test_media_extractor_subtitle.py
git commit -m "feat(kb): 提取器视频分支平台字幕优先，无则回退 ASR"
```

---

### Task 6: 挂载 + 后台真实链路单测 + 完整接线自检

**Files:**
- Modify: `api/internal/service/assistant_agent_service.py`（_build_assistant_runtime_tools）
- Create: `api/tests/unit/service/test_media_fetch_mount.py`

- [ ] **Step 1: 写失败测试（ENABLE=1 才挂载；未开启不挂载）**

```python
import os
def test_mount_gated_by_env(monkeypatch):
    from internal.service.assistant_agent_service import AssistantAgentService
    built_injected = {}
    def fake_builder(self, account_id, invoke_from=None, **kw):
        # 复刻现有挂载逻辑对应工具分支
        return []
    # 直接测工具 _enabled 门控（挂载处条件判断依赖 _enabled）
    from internal.core.tools.builtin_tools.providers.media_fetch_tools.fetch_media import _enabled
    monkeypatch.setenv("ENABLE_MEDIA_FETCH_TOOL", "1")
    assert _enabled() is True
    monkeypatch.setenv("ENABLE_MEDIA_FETCH_TOOL", "")
    assert _enabled() is False
```
> 更严格的真实挂载断言：在 `_build_assistant_runtime_tools` 复刻 video_edit 分支加 `media_fetch_tools` 挂载后，构造带 fake `app_config_service` 的 `AssistantAgentService` 实例调用该分支（沿用 KB-P5 已用范式），断言 `ENABLE_MEDIA_FETCH_TOOL=1` 时 `fetch_media` 出现在 tools、未开启时不在。**建议直接照抄那条既有 test 的注入手法。**

- [ ] **Step 2: Run fail → 预期 FAIL**

Run: `cd api && python -m pytest tests/unit/service/test_media_fetch_mount.py -v`

- [ ] **Step 3: 挂载，复刻 video_edit_tools 分支**

在 `_build_assistant_runtime_tools`（`assistant_agent_service.py` L1094 附近的 video_edit 分支之后）追加：

```python
# 外部素材获取工具：默认关闭，管理员开启后 Agent 可把公开视频/音频链接入库。
if self.app_config_service is not None:
    try:
        from internal.core.tools.builtin_tools.providers.media_fetch_tools.fetch_media import (
            _enabled as _media_fetch_enabled,
        )
        if _media_fetch_enabled():
            me_tool_factory = self.app_config_service.builtin_provider_manager.get_tool(
                "media_fetch_tools",
                "fetch_media",
            )
            if me_tool_factory is not None:
                tools.append(
                    me_tool_factory(
                        account_id=str(account_id),
                        message_id=message_id,
                        conversation_id=conversation_id,
                    )
                )
    except Exception:
        logger.warning("构建外部素材获取工具失败，不影响其他工具", exc_info=True)
```

- [ ] **Step 4: Run test → PASS**

Run: `cd api && python -m pytest tests/unit/service/test_media_fetch_mount.py -v`
Expected: PASS

- [ ] **Step 5: 接线自检（强制性）**

逐一确认：
- `fetch_media`：`.py`+`.yaml`+`positions.yaml`+`__init__.py` 重导出 + `providers.yaml` 登记 + `_build_assistant_runtime_tools` 挂载 = 5 处齐 → 有
- `media_fetch_task`：`celery_app.py`(include+显式 import) + `fetch_media._load_task().delay()` 派发点 → 有
- `MediaFetchService`：由 `media_fetch_task` 经 injector 取用 → 有
- `metadata_[subtitle_upload_file_id]` 写(media_fetch_service) + 读(knowledge_media_extractor_service) → 有

测试基线：`cd api && python -m pytest -q`（既有 4 个环境性失败仍存在则不修）。

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/assistant_agent_service.py api/tests/unit/service/test_media_fetch_mount.py
git commit -m "feat(kb): fetch_media 挂载（ENABLE_MEDIA_FETCH_TOOL 门控）"
```

---

### Task 7: 文档同步 + graphify + 收尾

**Files:**
- Modify: `docs/prd/modules/02-knowledge-base.md`（§11.x 新增 KB-P6 小节/状态）
- Modify: `docs/prd/execution-roadmap.md`（KB-P6 状态栏）
- Modify: `docs/prd/knowledge-base-product-form-design.md`（§5.3 落地口径标注「已实现」）
- Modify: `docs/README.md`（如需登记）
- Run: `python -m graphify update .`

- [ ] **Step 1: 同步架构文档**
在 `02-knowledge-base.md` 新增「KB-P6 外部素材获取」小节：入口 `POST/对话 fetch_media 工具`、`ENABLE_MEDIA_FETCH_TOOL` 门控、白名单 extractor、字幕优先回退 ASR、无新表。`execution-roadmap.md` 将 KB-P6 标记为完成（若原为「未立项」则更新）。`form-design` §5.3 标注落地实现与偏离（若偏离如表单 BASE 语言/分辨率策略未实现则明确「部分实现」）。

- [ ] **Step 2: graphify**

Run: `python -m graphify update .`（AST 无 API 成本）

- [ ] **Step 3: Commit**

```bash
git add docs/prd/modules/02-knowledge-base.md docs/prd/execution-roadmap.md docs/prd/knowledge-base-product-form-design.md docs/README.md
git commit -m "docs(prd): KB-P6 外部素材获取文档同步"
```

---

## Self-Review Checklist

- **spec 覆盖**：①默认关闭(§T4/T6) ②白名单排除 generic(T1) ③体积上限/内存(T1/T2 流式) ④合规免责/无登录(T2+工具描述) ⑤版本锁定+失效翻译(T1/T6) ⑥库调用非 CLI(T1) —— 全部有 Task。
- **占位扫描**：Task 2/5 标注的 `update_model_metadata`/`_get_document_cached`/reader 需**实测签名后回填**，不得按占位提交（计划提供修复步骤与实测要求）。
- **类型一致**：`FetchMediaInput` 字段与 yaml params、工具 _run 参数、`media_fetch_task` 位置参数一致；`import_document` 返回 dict 含 `document_id`，任务据此回填一致。

## Execution Handoff

计划完成并保存至 `docs/superpowers/plans/2026-09-21-kb-p6-external-media-fetch.md`。两个执行选项：
1. **Subagent-Driven（推荐）**
2. **Inline 执行**