# KB-P5 收尾·素材预览（网格缩略图直出 + 成品库播放入口）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户端「我的知识库」素材网格直出视频帧缩略图（`frame_url`），并在素材详情抽屉直接播放视频成品（成品库播放入口），同时把分段的时间线元数据（`start_sec/end_sec/source/speech_text/frame_url`）透出到 API 供前端展示。

**Architecture:** 后端在 `KnowledgeBaseService` 注入预览字段（文档级 `frame_url` 缩略图 + `playback_url` 播放直链；分段级时间线字段），签名逻辑复用 COS `get_file_url`；schema 用 `getattr` 透出（既有 `segment_count` 注入同款模式）。前端 `MaterialGrid` 网格项改缩略图布局，`MaterialDetailDrawer` 顶部加 `<video>` 播放器、分段行加帧缩略图与时间标签。全部改动走 TDD，i18n 双侧同步并跑 parity。

**Tech Stack:** Python 3.12 / Quart / SQLAlchemy(PostgreSQL JSONB) / Vue3 + Arco Design / Vitest / vue-i18n

---

## 0. 前置结论与约束（执行者必读）

| # | 事实（已勘察） | 处理 |
| --- | --- | --- |
| 1 | `frame_url` 存在 `KnowledgeSegment.metadata_['frame_url']`，值是 **COS key 而非 URL** | 注入前必须 `cos_service.get_file_url(key)` 签名（`build_output_artifact` 同款） |
| 2 | 视频段落在 `knowledge_media_extractor_service` 写入，`metadata` 含 `source=vision_timeline` / `anchor_type` / `start_sec` / `end_sec` / `speech_text` / `frame_url` | 分段注入直接读 `metadata_` |
| 3 | 成品（渲染/剪辑产物）是 `media_type=video` 的 `KnowledgeDocument`，关联 `upload_file_id`，播放直链 = `upload_file.key` 签名 | 文档注入按 `media_type == DocumentMediaType.VIDEO.value` 且 `upload_file_id` 非空生成 `playback_url` |
| 4 | 文档列表/详情 schema（`GetKnowledgeDocumentsWithPageResp` / `GetKnowledgeDocumentResp`）已透出 `media_type/content_type/parse_profile`，无预览字段 | 追加 `frame_url` / `playback_url` |
| 5 | 分段 schema（`GetKnowledgeSegmentsWithPageResp`）未透出任何 metadata | 追加 `frame_url` / `start_sec` / `end_sec` / `source` / `speech_text` |
| 6 | 服务注入模式：`get_documents_with_page` / `get_document_detail` 已用 `setattr(document, "segment_count", ...)`；schema `pre_dump` 用 `getattr` 读取 | 预览注入走同一模式 |
| 7 | 服务层测试模式：`_SessionStub`（顺序弹查询）+ 链式 `_QueryStub`；前端组件测试：`vi.mock('@/services/knowledge-base')` + 内联 i18n 字典 | 新测试沿用 |
| 8 | 前端 i18n 强制规则：文案必须走 i18n，zh-CN/en-US 键集必须一致（parity spec 把关）；`space.datasets.detail.material.*` 为既有板块键 | 新增键双侧同步 |
| 9 | 既有组件测试内联 i18n 字典不含新键时 `t()` 会回退裸键——新增键后**必须同步补进组件测试的内联字典** | 见 Task 4/5 测试代码 |
| 10 | **本计划不含**「对话框内成片编辑器」（时间轴拖拽/逐段替换）——那是独立大子系统，Part 2 单独立项 | 不触碰；§11.16「未落地」行保留成片编辑器，改掉播放入口 |

**本计划不涉及**：新表/迁移、路由（复用既有 `GET /space/knowledge-bases/<id>/documents`、`GET .../documents/<id>`、`GET .../documents/<id>/segments`）、成片编辑器。

## 1. 文件结构规划

### 新建

| 文件 | 职责 |
| --- | --- |
| `api/test/internal/service/test_knowledge_preview_fields.py` | 预览注入与分段时间线注入的服务层单测 |

### 修改

| 文件 | 改动 |
| --- | --- |
| `api/internal/service/knowledge_base_service.py` | 新增 `_enrich_document_previews(documents)` / `_enrich_segment_previews(segments)`，并在 `get_documents_with_page` / `get_document_detail` / `get_segments_with_page` 末尾调用 |
| `api/internal/schema/knowledge_base_schema.py` | 文档列表/详情 schema 加 `frame_url/playback_url`；分段 schema 加 `frame_url/start_sec/end_sec/source/speech_text`（均 `getattr` 读取） |
| `ui/src/models/knowledge-base.ts` | 文档/分段 TS 类型补新字段 |
| `ui/src/views/space/datasets/detail/components/MaterialGrid.vue` | 网格项改缩略图布局（`frame_url` → `<img>`，无则回退图标 + video 角标） |
| `ui/src/views/space/datasets/detail/components/MaterialDetailDrawer.vue` | 顶部加 `<video controls>` 播放器；分段行加帧缩略图 + 时间标签 |
| `ui/src/views/space/datasets/detail/components/__tests__/MaterialGrid.spec.ts` | 新增缩略图用例 + 内联 i18n 补 `videoBadge` |
| `ui/src/views/space/datasets/detail/components/__tests__/MaterialDetailDrawer.spec.ts` | 新增播放器/分段缩略图用例 |
| `ui/src/i18n/messages/zh-CN/space.ts`、`ui/src/i18n/messages/en-US/space.ts` | `space.datasets.detail.material.videoBadge` |
| `docs/prd/modules/02-knowledge-base.md` | §11.17 未落地项更新；§11.16 播放入口落地 |
| `docs/prd/execution-roadmap.md` | KB-P5 未落地项更新 |
| `docs/README.md` | L14「KB-P5 未开始」漂移修正 |

**接线自检（完成后逐项核对）**：

| 新符号 | 入口 |
| --- | --- |
| `_enrich_document_previews` | 调用方 `get_documents_with_page`（路由 `GET /space/knowledge-bases/<id>/documents`）+ `get_document_detail`（`GET .../documents/<id>`） |
| `_enrich_segment_previews` | 调用方 `get_segments_with_page`（`GET .../documents/<id>/segments`） |
| schema `frame_url/playback_url/start_sec/...` | 同一批路由响应，前端 `MaterialGrid` / `MaterialDetailDrawer` 消费 |
| 无「写了没读」 | 后端注入字段 → 前端组件渲染 → 组件测试断言 |

---

## Task 1: 文档级预览字段注入（服务层 + schema）

**Files:**
- Create: `api/test/internal/service/test_knowledge_preview_fields.py`
- Modify: `api/internal/service/knowledge_base_service.py`
- Modify: `api/internal/schema/knowledge_base_schema.py`

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/service/test_knowledge_preview_fields.py`：

```python
"""知识库文档/分段预览字段注入单测（frame_url 缩略图 / playback_url 播放直链 / 时间线元数据）。"""
from types import SimpleNamespace
from uuid import uuid4

from internal.service.knowledge_base_service import KnowledgeBaseService


class _ChainStub:
    """支持 filter/order_by/distinct/all 链式调用的查询桩。"""

    def __init__(self, rows=None):
        self._rows = [] if rows is None else rows

    def filter(self, *_a, **_k):
        return self

    def order_by(self, *_a, **_k):
        return self

    def distinct(self, *_a, **_k):
        return self

    def all(self):
        return self._rows


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_a, **_k):
        if self._queries:
            return self._queries.pop(0)
        return _ChainStub()


class _CosStub:
    def get_file_url(self, key):
        return f"https://cos/{key}"


def _new_service(session=None, cos=None):
    service = KnowledgeBaseService(
        db=SimpleNamespace(session=session or _SessionStub()),
        retrieval_service=SimpleNamespace(),
        icon_generator_service=SimpleNamespace(),
    )
    service._get_cos_service = lambda: cos or _CosStub()
    return service


def _doc(**overrides):
    base = dict(id=uuid4(), name="clip.mp4", media_type="video", upload_file_id=uuid4())
    base.update(overrides)
    return SimpleNamespace(**base)


def test_enrich_documents_injects_frame_and_playback_urls():
    """视频文档：frame_url 来自首个带帧的分段（签名后），playback_url 来自 upload_file.key（签名后）。"""
    video_doc = _doc()
    frame_query = _ChainStub([(video_doc.id, "2026/09/13/frame-1.jpg")])
    upload_query = _ChainStub(
        [SimpleNamespace(id=video_doc.upload_file_id, key="2026/09/13/out.mp4")]
    )
    service = _new_service(_SessionStub([frame_query, upload_query]))

    service._enrich_document_previews([video_doc])

    assert getattr(video_doc, "frame_url") == "https://cos/2026/09/13/frame-1.jpg"
    assert getattr(video_doc, "playback_url") == "https://cos/2026/09/13/out.mp4"


def test_enrich_documents_leaves_empty_when_no_frame_or_not_video():
    """无帧分段 / 非视频文档：frame_url 与 playback_url 均为空串，不抛错。"""
    video_doc = _doc()
    image_doc = _doc(media_type="image", upload_file_id=None)
    service = _new_service(
        _SessionStub([_ChainStub(), _ChainStub()]),  # 帧查询空 + 上传文件查询空
    )

    service._enrich_document_previews([video_doc, image_doc])

    assert getattr(video_doc, "frame_url") == ""
    assert getattr(image_doc, "frame_url") == ""
    assert getattr(video_doc, "playback_url") == ""
    assert getattr(image_doc, "playback_url") == ""


def test_enrich_documents_noop_for_empty_list():
    """空列表直接返回，不发起任何查询。"""
    service = _new_service(_SessionStub([]))
    service._enrich_document_previews([])


def test_enrich_segments_exposes_timeline_metadata():
    """时间线段落：frame_url 签名后注入，start/end/source/speech_text 从 metadata 透出。"""
    segment = SimpleNamespace(
        id=uuid4(),
        metadata_={
            "source": "vision_timeline",
            "start_sec": 3.2,
            "end_sec": 8.7,
            "frame_url": "2026/09/13/rep.jpg",
            "speech_text": "第一句台词。",
        },
    )
    service = _new_service(_SessionStub([]))

    service._enrich_segment_previews([segment])

    assert getattr(segment, "frame_url") == "https://cos/2026/09/13/rep.jpg"
    assert getattr(segment, "start_sec") == 3.2
    assert getattr(segment, "end_sec") == 8.7
    assert getattr(segment, "source") == "vision_timeline"
    assert getattr(segment, "speech_text") == "第一句台词。"


def test_enrich_segments_defaults_when_metadata_missing():
    """无 metadata 的分段：所有预览字段回退默认值，不抛错。"""
    segment = SimpleNamespace(id=uuid4(), metadata_={})
    service = _new_service(_SessionStub([]))

    service._enrich_segment_previews([segment])

    assert getattr(segment, "frame_url") == ""
    assert getattr(segment, "start_sec") == 0.0
    assert getattr(segment, "end_sec") == 0.0
    assert getattr(segment, "source") == ""
    assert getattr(segment, "speech_text") == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_preview_fields.py -v`
Expected: FAIL — `AttributeError: 'KnowledgeBaseService' object has no attribute '_enrich_document_previews'`

- [ ] **Step 3: 实现注入方法**

在 `api/internal/service/knowledge_base_service.py` 的 `get_documents_with_page` 之后追加：

```python
    def _enrich_document_previews(self, documents: list[KnowledgeDocument]) -> None:
        """给文档注入预览字段（frame_url 缩略图 / playback_url 视频播放地址）。

        数据源：分段的 `metadata->>'frame_url'`（COS key，需签名）与文档关联的
        `upload_file.key`（成品播放直链）。注入发生在 schema 序列化之前，schema 用
        getattr 读取，与既有 segment_count 注入同款模式。
        """
        if not documents:
            return
        cos_service = self._get_cos_service()
        doc_ids = [document.id for document in documents]

        frame_rows = (
            self.db.session.query(
                KnowledgeSegment.knowledge_document_id,
                KnowledgeSegment.metadata_["frame_url"].astext,
            )
            .filter(
                KnowledgeSegment.knowledge_document_id.in_(doc_ids),
                KnowledgeSegment.metadata_["frame_url"].astext != "",
            )
            .order_by(KnowledgeSegment.knowledge_document_id, KnowledgeSegment.position)
            .distinct(KnowledgeSegment.knowledge_document_id)
            .all()
        )
        frame_urls: dict[str, str] = {}
        for doc_id, key in frame_rows:
            url = cos_service.get_file_url(str(key))
            if url:
                frame_urls[str(doc_id)] = url

        upload_ids = [
            document.upload_file_id
            for document in documents
            if document.media_type == DocumentMediaType.VIDEO.value
            and document.upload_file_id
        ]
        uploads: dict[str, UploadFile] = {}
        if upload_ids:
            upload_rows = (
                self.db.session.query(UploadFile)
                .filter(UploadFile.id.in_(upload_ids))
                .all()
            )
            uploads = {str(row.id): row for row in upload_rows}

        for document in documents:
            setattr(document, "frame_url", frame_urls.get(str(document.id), ""))
            playback_url = ""
            upload = uploads.get(str(document.upload_file_id or ""))
            if upload is not None:
                key = str(getattr(upload, "key", "") or "")
                if key:
                    playback_url = cos_service.get_file_url(key) or ""
            setattr(document, "playback_url", playback_url)
```

在 `get_documents_with_page` 末尾（segment_count 循环之后）追加：

```python
        # 6.为每个文档注入预览字段（缩略图 / 播放直链）
        self._enrich_document_previews(documents)
```

在 `get_document_detail` 末尾（segment_count setattr 之后）追加：

```python
        # 4.补充预览字段（缩略图 / 播放直链）
        self._enrich_document_previews([document])
```

> 核对既有 import：`KnowledgeSegment` / `UploadFile` / `DocumentMediaType` 本文件已导入（`store_render_output` / `build_output_artifact` 在用），无需新增。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_preview_fields.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 更新 schema 透出字段**

`api/internal/schema/knowledge_base_schema.py`：

在 `GetKnowledgeDocumentsWithPageResp`（L176）字段区追加：

```python
    frame_url = fields.String(dump_default="")
    playback_url = fields.String(dump_default="")
```

在其 `process_data` 返回 dict 追加：

```python
            "frame_url": getattr(data, "frame_url", "") or "",
            "playback_url": getattr(data, "playback_url", "") or "",
```

在 `GetKnowledgeDocumentResp`（L211）字段区追加同样两个字段，`process_data` 同样追加两行。

- [ ] **Step 6: 补 schema 契约测试（追加到测试文件末尾）**

```python
def test_documents_schema_dumps_preview_fields():
    """文档列表 schema 应透出 frame_url / playback_url。"""
    from datetime import datetime, timezone

    from internal.schema.knowledge_base_schema import GetKnowledgeDocumentsWithPageResp

    doc = SimpleNamespace(
        id=uuid4(),
        name="clip.mp4",
        media_type="video",
        content_type="video/mp4",
        parse_profile={},
        character_count=0,
        segment_count=1,
        status="completed",
        error="",
        updated_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        frame_url="https://cos/rep.jpg",
        playback_url="https://cos/out.mp4",
    )

    payload = GetKnowledgeDocumentsWithPageResp().dump(doc)

    assert payload["frame_url"] == "https://cos/rep.jpg"
    assert payload["playback_url"] == "https://cos/out.mp4"
```

Run: `cd api && python -m pytest test/internal/service/test_knowledge_preview_fields.py -v`
Expected: PASS（7 passed）

- [ ] **Step 7: Commit**

```bash
git add api/internal/service/knowledge_base_service.py api/internal/schema/knowledge_base_schema.py api/test/internal/service/test_knowledge_preview_fields.py
git commit -m "feat(kb): 文档列表/详情透出 frame_url 缩略图与 playback_url 播放直链（素材预览后端）"
```

---

## Task 2: 分段时间线元数据透出

**Files:**
- Modify: `api/internal/service/knowledge_base_service.py`
- Modify: `api/internal/schema/knowledge_base_schema.py`
- Test: `api/test/internal/service/test_knowledge_preview_fields.py`

- [ ] **Step 1: 写失败的测试（已在上文写入 `test_enrich_segments_*`，直接跑确认失败）**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_preview_fields.py -k "segment" -v`
Expected: FAIL — `AttributeError: 'KnowledgeBaseService' object has no attribute '_enrich_segment_previews'`

- [ ] **Step 2: 实现分段注入方法**

在 `api/internal/service/knowledge_base_service.py` 的 `_enrich_document_previews` 之后追加：

```python
    def _enrich_segment_previews(self, segments: list[KnowledgeSegment]) -> None:
        """把分段的时间线元数据注入分段对象：帧缩略图（签名）+ start/end/source/speech_text。

        字段来自 `metadata_`（`source=vision_timeline` 段落结构，见 KB-P4.5），
        帧 key 是 COS key，需签名后才可被前端 <img> 直出。
        """
        if not segments:
            return
        cos_service = self._get_cos_service()
        for segment in segments:
            metadata = segment.metadata_ or {}
            frame_key = str(metadata.get("frame_url") or "")
            setattr(
                segment, "frame_url", cos_service.get_file_url(frame_key) if frame_key else ""
            )
            setattr(segment, "start_sec", float(metadata.get("start_sec") or 0))
            setattr(segment, "end_sec", float(metadata.get("end_sec") or 0))
            setattr(segment, "source", str(metadata.get("source") or ""))
            setattr(segment, "speech_text", str(metadata.get("speech_text") or ""))
```

在 `get_segments_with_page` 末尾（paginate 之后）追加：

```python
        # 6.注入时间线预览字段（帧缩略图 / start/end/source/speech_text）
        self._enrich_segment_previews(segments)
```

- [ ] **Step 3: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_preview_fields.py -k "segment" -v`
Expected: PASS（2 passed）

- [ ] **Step 4: 更新 schema 透出字段**

`api/internal/schema/knowledge_base_schema.py` 的 `GetKnowledgeSegmentsWithPageResp`（L251）字段区追加：

```python
    frame_url = fields.String(dump_default="")
    start_sec = fields.Float(dump_default=0.0)
    end_sec = fields.Float(dump_default=0.0)
    source = fields.String(dump_default="")
    speech_text = fields.String(dump_default="")
```

其 `process_data` 返回 dict 追加：

```python
            "frame_url": getattr(data, "frame_url", "") or "",
            "start_sec": getattr(data, "start_sec", 0.0) or 0.0,
            "end_sec": getattr(data, "end_sec", 0.0) or 0.0,
            "source": getattr(data, "source", "") or "",
            "speech_text": getattr(data, "speech_text", "") or "",
```

- [ ] **Step 5: 补 schema 契约测试（追加到测试文件末尾）**

```python
def test_segments_schema_dumps_timeline_fields():
    """分段 schema 应透出时间线元数据字段。"""
    from datetime import datetime, timezone

    from internal.schema.knowledge_base_schema import GetKnowledgeSegmentsWithPageResp

    segment = SimpleNamespace(
        id=uuid4(),
        knowledge_base_id=uuid4(),
        knowledge_document_id=uuid4(),
        position=1,
        content="画面A",
        keywords=[],
        character_count=3,
        token_count=0,
        hit_count=0,
        enabled=True,
        status="completed",
        updated_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        frame_url="https://cos/rep.jpg",
        start_sec=3.2,
        end_sec=8.7,
        source="vision_timeline",
        speech_text="第一句台词。",
    )

    payload = GetKnowledgeSegmentsWithPageResp().dump(segment)

    assert payload["frame_url"] == "https://cos/rep.jpg"
    assert payload["start_sec"] == 3.2
    assert payload["end_sec"] == 8.7
    assert payload["source"] == "vision_timeline"
    assert payload["speech_text"] == "第一句台词。"
```

Run: `cd api && python -m pytest test/internal/service/test_knowledge_preview_fields.py -v`
Expected: PASS（9 passed）

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/knowledge_base_service.py api/internal/schema/knowledge_base_schema.py api/test/internal/service/test_knowledge_preview_fields.py
git commit -m "feat(kb): 分段 API 透出时间线元数据（frame_url/start_sec/end_sec/source/speech_text）"
```

---

## Task 3: 后端回归

**Files:** 无新增

- [ ] **Step 1: 跑知识库相关既有测试**

Run: `cd api && python -m pytest test/internal/service/test_knowledge_base_service.py test/internal/service/test_knowledge_output_artifact.py test/app/http/test_knowledge_mcp_routes.py -q`
Expected: PASS（既有用例不受影响；若出现因 schema 字段新增导致的断言失败，修正断言）

- [ ] **Step 2: 跑全量单测确认无回归**

Run: `cd api && python -m pytest -q`
Expected: PASS（与基线一致：既有 1 个环境性失败 `test_resend_login_challenge_should_reuse_pending_challenge` 不修）

- [ ] **Step 3: Commit（如有修正）**

```bash
git add -u api/
git commit -m "test(kb): 素材预览字段透出后回归修正"
```

---

## Task 4: 前端类型 + 素材网格缩略图直出

**Files:**
- Modify: `ui/src/models/knowledge-base.ts`
- Modify: `ui/src/views/space/datasets/detail/components/MaterialGrid.vue`
- Test: `ui/src/views/space/datasets/detail/components/__tests__/MaterialGrid.spec.ts`

- [ ] **Step 1: 更新 TS 类型**

`ui/src/models/knowledge-base.ts`：

- `GetKnowledgeDocumentsWithPageResponse` 列表项与 `GetKnowledgeDocumentResponse` 对象各追加：

```typescript
  frame_url?: string
  playback_url?: string
```

- `GetKnowledgeSegmentsWithPageResponse` 列表项追加：

```typescript
  frame_url?: string
  start_sec?: number
  end_sec?: number
  source?: string
  speech_text?: string
```

- [ ] **Step 2: 写失败的组件测试（先追加用例与 i18n 字典）**

`ui/src/views/space/datasets/detail/components/__tests__/MaterialGrid.spec.ts`：

1. 内联 i18n 字典的 `material` 对象补键（zh-CN 与 en-US 各一处）：

```typescript
              videoBadge: '视频',
```
与
```typescript
              videoBadge: 'Video',
```

2. 文件末尾追加用例：

```typescript
  it('视频素材带 frame_url 时渲染帧缩略图而非图标', async () => {
    mocks.getKnowledgeDocumentsWithPage.mockResolvedValue({
      data: {
        list: [
          {
            id: 'd1',
            name: 'demo.mp4',
            media_type: 'video',
            frame_url: 'https://cos/frame.jpg',
            status: 'completed',
            character_count: 120,
            created_at: 1700000000,
          },
        ],
        paginator: { current_page: 1, page_size: 20, total_page: 1, total_record: 1 },
      },
    })
    const wrapper = mount(MaterialGrid, {
      props: { knowledgeBaseId: 'kb-1', partitionId: '' },
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    expect(wrapper.find('img').attributes('src')).toBe('https://cos/frame.jpg')
  })
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd ui && npx vitest run src/views/space/datasets/detail/components/__tests__/MaterialGrid.spec.ts`
Expected: FAIL — 新增用例 `wrapper.find('img')` 不存在（当前模板无 `<img>`）

- [ ] **Step 4: 实现网格缩略图布局**

`MaterialGrid.vue` 的网格项模板（L70-93）改为：

```vue
        <a-grid-item v-for="doc in documents" :key="doc.id">
          <div
            class="cursor-pointer rounded-xl border border-border-c bg-surface p-2 transition hover:border-brand"
            @click="emit('open', String(doc.id))"
          >
            <div class="relative h-[92px] w-full overflow-hidden rounded-lg bg-surface-2">
              <img
                v-if="doc.frame_url"
                :src="doc.frame_url"
                :alt="doc.name"
                class="h-full w-full object-cover"
              />
              <div v-else class="flex h-full w-full items-center justify-center bg-brand-soft">
                <icon-font :type="mediaIcon(doc.media_type)" />
              </div>
              <span
                v-if="doc.media_type === 'video'"
                class="absolute right-1 top-1 rounded bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white"
              >
                {{ t('space.datasets.detail.material.videoBadge') }}
              </span>
            </div>
            <div class="mt-2 flex items-center justify-between">
              <a-tag
                class="rounded-full text-xs"
                :class="doc.status === 'completed' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'"
              >
                {{ statusText(doc.status) }}
              </a-tag>
            </div>
            <p class="mt-1 line-clamp-1 break-all text-sm font-medium text-text">{{ doc.name }}</p>
            <p class="mt-1 text-xs text-muted">
              {{ doc.character_count }} · {{ new Date(Number(doc.created_at) * 1000).toLocaleDateString() }}
            </p>
          </div>
        </a-grid-item>
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd ui && npx vitest run src/views/space/datasets/detail/components/__tests__/MaterialGrid.spec.ts`
Expected: PASS（3 passed：既有 2 个 + 新增缩略图用例）

- [ ] **Step 6: Commit**

```bash
git add ui/src/models/knowledge-base.ts ui/src/views/space/datasets/detail/components/MaterialGrid.vue ui/src/views/space/datasets/detail/components/__tests__/MaterialGrid.spec.ts
git commit -m "feat(ui): 素材网格视频帧缩略图直出（frame_url）与 video 角标"
```

---

## Task 5: 素材详情抽屉播放入口 + 分段缩略图

**Files:**
- Modify: `ui/src/views/space/datasets/detail/components/MaterialDetailDrawer.vue`
- Test: `ui/src/views/space/datasets/detail/components/__tests__/MaterialDetailDrawer.spec.ts`

- [ ] **Step 1: 写失败的组件测试（追加到既有 spec）**

`MaterialDetailDrawer.spec.ts` 末尾追加两个用例：

```typescript
  it('视频成品带 playback_url 时渲染内联播放器', async () => {
    mocks.getKnowledgeDocument.mockResolvedValue({
      data: {
        id: 'd1',
        name: 'demo.mp4',
        media_type: 'video',
        playback_url: 'https://cos/out.mp4',
        segment_count: 0,
        character_count: 0,
        status: 'completed',
      },
    })
    const wrapper = mount(MaterialDetailDrawer, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    expect(wrapper.find('video').attributes('src')).toBe('https://cos/out.mp4')
  })

  it('分段带 frame_url 时渲染帧缩略图与时间标签', async () => {
    mocks.getKnowledgeSegmentsWithPage.mockResolvedValue({
      data: {
        list: [
          {
            id: 's1',
            position: 1,
            content: 'some segment content',
            frame_url: 'https://cos/f.jpg',
            start_sec: 3.2,
            end_sec: 8.7,
          },
        ],
        paginator: { current_page: 1, page_size: 20, total_page: 1, total_record: 1 },
      },
    })
    const wrapper = mount(MaterialDetailDrawer, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    expect(wrapper.find('img').attributes('src')).toBe('https://cos/f.jpg')
    expect(wrapper.text()).toContain('00:03')
  })
```

> 既有 beforeEach 会把 `getKnowledgeDocument` / `getKnowledgeSegmentsWithPage` 重置为默认值，新用例内再次 `mockResolvedValue` 覆盖即可。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd ui && npx vitest run src/views/space/datasets/detail/components/__tests__/MaterialDetailDrawer.spec.ts`
Expected: FAIL — 新增用例找不到 `<video>` / `<img>`

- [ ] **Step 3: 实现抽屉播放器与分段缩略图**

`MaterialDetailDrawer.vue`：

1. script 区新增时间格式化辅助（放在 `handleDelete` 之后）：

```typescript
const formatTime = (sec: number) => {
  const total = Math.max(0, Math.floor(Number(sec) || 0))
  const m = Math.floor(total / 60)
    .toString()
    .padStart(2, '0')
  const s = (total % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}
```

2. 模板基本信息卡片之前插入播放器块：

```vue
      <div
        v-if="document.media_type === 'video' && document.playback_url"
        class="overflow-hidden rounded-xl border border-border-c bg-black"
      >
        <video :src="document.playback_url" controls playsinline class="aspect-video w-full" />
      </div>
```

3. 分段列表项（L98-101）改为缩略图 + 时间标签布局：

```vue
          <div
            v-for="seg in segments"
            :key="seg.id"
            class="flex gap-3 rounded-lg border border-border-c bg-surface p-3"
          >
            <img
              v-if="seg.frame_url"
              :src="seg.frame_url"
              class="h-16 w-24 shrink-0 rounded object-cover"
              alt=""
            />
            <div class="min-w-0 flex-1">
              <p v-if="seg.start_sec && seg.start_sec > 0" class="text-xs text-muted">
                {{ formatTime(seg.start_sec) }} ~ {{ formatTime(seg.end_sec) }}
              </p>
              <p class="line-clamp-3 text-sm text-text-2">{{ seg.content }}</p>
              <p class="mt-1 text-xs text-muted">#{{ seg.position }}</p>
            </div>
          </div>
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd ui && npx vitest run src/views/space/datasets/detail/components/__tests__/MaterialDetailDrawer.spec.ts`
Expected: PASS（5 passed：既有 3 个 + 新增 2 个）

- [ ] **Step 5: Commit**

```bash
git add ui/src/views/space/datasets/detail/components/MaterialDetailDrawer.vue ui/src/views/space/datasets/detail/components/__tests__/MaterialDetailDrawer.spec.ts
git commit -m "feat(ui): 素材详情抽屉视频成品播放入口 + 分段帧缩略图与时间标签"
```

---

## Task 6: i18n 双侧同步 + 前端回归

**Files:**
- Modify: `ui/src/i18n/messages/zh-CN/space.ts`
- Modify: `ui/src/i18n/messages/en-US/space.ts`

- [ ] **Step 1: 补 i18n 键**

`zh-CN/space.ts` 的 `datasets.detail.material` 块内补：

```typescript
      videoBadge: '视频',
```

`en-US/space.ts` 的对应位置补：

```typescript
      videoBadge: 'Video',
```

> 位置以实际文件内 `detail.material` 对象为准；`videoBadge` 为唯一新增展示文案（播放器控件与时间格式属原生/格式化，不新增文案键）。

- [ ] **Step 2: 跑 i18n parity**

Run: `cd ui && npx vitest run src/i18n/__tests__/parity.spec.ts`
Expected: PASS（zh/en 键集一致、代码引用键均存在）

- [ ] **Step 3: 跑前端全量**

Run: `cd ui && npx vitest run`
Expected: PASS（既有 133 文件 607 tests + 本计划新增用例）

- [ ] **Step 4: Commit**

```bash
git add ui/src/i18n/messages/zh-CN/space.ts ui/src/i18n/messages/en-US/space.ts
git commit -m "feat(ui): 素材预览 videoBadge 文案 i18n 双侧同步"
```

---

## Task 7: 文档同步 + 接线自检

**Files:**
- Modify: `docs/prd/modules/02-knowledge-base.md`
- Modify: `docs/prd/execution-roadmap.md`
- Modify: `docs/README.md`

- [ ] **Step 1: 更新 `docs/prd/modules/02-knowledge-base.md`**

§11.17（L930 起）表格「素材网格 / 表格」行数据源描述不变，但在「未落地」行（L967）更新为：

```markdown
**已落地（KB-P5 收尾）**：网格缩略图直出——文档列表/详情 API 透出 `frame_url`（视频首个带帧分段的代表帧，COS 签名后直出）与 `playback_url`（视频成品播放直链）；分段 API 透出时间线元数据（`frame_url` / `start_sec` / `end_sec` / `source` / `speech_text`）。详情抽屉对视频成品直接内联播放，分段行展示帧缩略图与时间标签。

**未落地**：对话框内成片编辑器（时间轴拖拽 / 逐段替换，见 §11.16，独立立项）。
```

§11.16（L928）「未落地」行更新为：

```markdown
**未落地**：对话框内的成片编辑器（时间轴拖拽 / 逐段替换）。成品库页面的播放入口已随 KB-P5 收尾落地（素材详情抽屉内联播放）。
```

- [ ] **Step 2: 更新 `docs/prd/execution-roadmap.md`**

KB-P5 行（L416）的「未落地项」括号更新为：

```markdown
未落地项：对话框内成片编辑器（独立立项，见 modules/02-knowledge-base.md §11.16））
```

- [ ] **Step 3: 修正 `docs/README.md` 漂移**

L14 的「KB-P5 未开始」改为「KB-P5 已完成」：

```markdown
- [知识库产品形态设计](prd/knowledge-base-product-form-design.md)：素材中心 / 分级解析 / 容量商业化（KB-P1、KB-P2A、KB-P2B、KB-P3 已落地；KB-P3.5–P3.8 为增量；KB-P4、KB-P5 已完成）
```

- [ ] **Step 4: 接线自检（AGENTS.md 强制，逐项核对）**

| 检查项 | 结果 |
| --- | --- |
| `_enrich_document_previews` 入口 | `get_documents_with_page`（`GET /space/knowledge-bases/<id>/documents`）+ `get_document_detail`（`GET .../documents/<id>`），调用方在服务内，随路由天然可达 |
| `_enrich_segment_previews` 入口 | `get_segments_with_page`（`GET .../documents/<id>/segments`） |
| schema 新字段消费方 | 前端 `MaterialGrid`（`frame_url` 缩略图）、`MaterialDetailDrawer`（`playback_url` 播放器 + 分段缩略图/时间），均有组件测试锁定 |
| 无「写了没读」字段 | 后端注入 → 前端渲染 → 测试断言，闭环 |
| 无新迁移/新路由/新工具 | 不适用 |

- [ ] **Step 5: 更新知识图谱**

```bash
python -m graphify update .
```

- [ ] **Step 6: Commit**

```bash
git add docs/prd/modules/02-knowledge-base.md docs/prd/execution-roadmap.md docs/README.md
git commit -m "docs(kb): KB-P5 素材预览收尾落地 + roadmap/README 状态同步"
```

---

## Part 2（不在本计划实现，单独立项）

「对话框内成片编辑器（时间轴拖拽 / 逐段替换）」为独立大子系统：前端时间线组件 + 重排/替换合成链路（复用 `video_trim` 的 `segment_index` 与 `video_concat`），需要先定编辑对象（成品文档自身的 `source=vision_timeline` 分段）与替换素材来源，再出独立 Implementation Plan。本计划完成后，若用户确认继续，再写 `docs/superpowers/plans/2026-09-21-kb-p5-closeout-chat-editor.md`。
