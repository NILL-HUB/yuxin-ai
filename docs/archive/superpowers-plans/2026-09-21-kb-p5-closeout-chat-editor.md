# KB-P5 收尾·成片编辑器（时间线编排：拖拽重排 / 删除 / 逐段替换）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户把一段成片/视频按时间线重新编排（拖拽调整段落顺序、删除段落、用其他素材的段落替换某段），提交后生成新成片存入成品库（对话内由 `video_reassemble` 工具覆盖同一链路并回填预览）。

**Architecture:** 后端新增 `VideoEditService.reassemble_document`（对主文档/替换素材的源文件逐项本地 `trim`（流拷贝秒级）→ `concat`（仅 1 段时跳过）→ 单次 `_store_output`，中间产物只存在于工作目录、不污染成品库），`clips` 协议为 `[{"document_id": str, "segment_index": int}]`（`segment_index` 1-based 段落，0/缺省取整段）。触发面两个：**REST 路由** `POST /space/knowledge-bases/<kb_id>/documents/<document_id>/reassemble`（前端编辑器提交入口）与 **builtin 工具** `video_reassemble`（Agent 对话内触发，`clips` 用 JSON 字符串参数以绕开 yaml `type` 枚举限制），二者都派发同一 Celery 任务 `video_reassemble_task`（薄委托 + `_notify_artifact` 单次回填）。前端在素材详情抽屉加「重新编排」入口，弹 `TimelineEditorModal.vue`（HTML5 拖拽排序，无新依赖），复用 Part 1 已透出的分段时间线字段（`frame_url/start_sec/end_sec/source/speech_text`）。

**Tech Stack:** Python 3.12 / Quart / Celery / ffmpeg(imageio_ffmpeg) / Vue3 + Arco Design / Vitest / vue-i18n

---

## 0. 前置结论与约束（执行者必读）

| # | 事实（已勘察） | 处理 |
| --- | --- | --- |
| 1 | 编排对象是成品/素材自身的 `source=vision_timeline` 分段（KB-P4.5），Part 1 已让 `GET .../segments` 透出 `frame_url/start_sec/end_sec/source/speech_text` | 前端编辑器直接消费该接口 |
| 2 | `VideoEditService` 已有 `_load_source_documents`（归属校验复用 `get_document_detail`）、`_prepare_source_file`（COS 下载）、`_resolve_trim_range`（`segment_index` 越界抛错）、`trim`/`concat`（流拷贝）、`_store_output`（存成品库 + 可播放 artifact） | `reassemble_document` 全部复用，不自造新能力 |
| 3 | `clips` 由前端编辑器 / Agent 提交，含嵌套结构；工具 yaml 参数 `type` 枚举仅 `string/number/boolean/select` | 工具参数 `clips` 用 `type: string` 收 JSON 字符串，工具内 `json.loads` 校验 |
| 4 | 任务薄委托范式 + `_notify_artifact` 已定型（`video_edit_tasks.py`），`VideoEditError` 不重试 | 新任务 `video_reassemble_task` 全盘沿用；`internal.task.video_edit_tasks` 已在 `celery_app.py` `TASK_MODULES`（L85）+ 显式 import（L105），**无需改 celery_app.py**，只需加 `__all__` 与新函数 |
| 5 | builtin 工具四件套：`.py` + `.yaml` + `positions.yaml` + `providers.yaml`（`video_edit_tools` provider 已存在）+ 运行时挂载点（`assistant_agent_service.py` L1095 元组）+ 包 `__init__.py` 重导出工厂 | 新工具 `video_reassemble` 需补齐 py/yaml/positions 一行/挂载元组一项/`__init__.py` 一行；providers.yaml 不用动 |
| 6 | 路由错误响应函数是 `_err(code, message, status=400)`（`app.http.support`），当前 `knowledge_mcp_routes.py` import 行未引入 `_err` | 路由 Task 需在 import 行补 `_err` |
| 7 | 路由测试模式：`register_routes(asgi_app.quart_app)` + monkeypatch `knowledge_mcp_routes._resolve_account` + `asyncio.run` + `test_client`（见 `test_knowledge_mcp_routes.py` `_setup`） | 新路由测试沿用 |
| 8 | 工具/任务测试模式：`test_video_edit_tools.py`（`_capture_delay` 锁 `captured["kwargs"]`、`test_tool_yamls_declare_expected_shape`/`test_positions_yaml_lists_all_three_tools`/`test_tools_are_mounted_at_runtime_with_account_id`/`test_package_init_reexports_factories`/`test_provider_loader_discovers_all_tools` 均在遍历工具名）与 `test_video_edit_tasks.py`（`_invoke` 取底层函数 + `_FakeSelf` + `_install_service`） | 新工具/任务测试**追加到既有文件**，且**同步更新既有遍历元组/集合**（漏改会直接红） |
| 9 | 服务测试模式：`VideoEditService.__new__(VideoEditService)` + monkeypatch 替换依赖方法（见 `test_video_edit_service.py`）；`_resolve_trim_range` 依赖 `_load_timeline_segments` | 服务测试新建 `test_video_reassemble.py`，stub `_load_source_documents/_prepare_source_file/trim/concat/_store_output/_load_timeline_segments`，`_resolve_trim_range` 走真实逻辑 |
| 10 | 前端 `useGetKnowledgeSegmentsWithPage` hook 是「单实例单缓存」——**主文档分段与替换素材分段必须用两个 hook 实例**，共用一个会把主文档时间线冲掉 | `TimelineEditorModal` 用 `useGetKnowledgeSegmentsWithPage()` × 2（main/source） |
| 11 | 前端组件测试模式：`vi.mock('@/services/knowledge-base')` + `vi.mock('@arco-design/web-vue')` + 内联 i18n 字典 + `stubs`；i18n parity 会扫 `t('...')` 字面量 | 新组件测试沿用；内联字典必须含新键 |
| 12 | **形态决策**：编辑器 UI 落在素材中心（素材详情抽屉入口），而非对话消息内——素材中心有完整上下文（kb_id + document_id + 同库素材供替换选择）；「对话框内」能力由 `video_reassemble` 工具覆盖（Agent 对话内触发同一链路）。`ChatVideoGallery` 的 artifact 载荷不含 `document_id`，对话内直接挂编辑器需额外改造 artifact，**不纳入本计划**（文档同步时如实标注） | 按此设计实现 |

**本计划不涉及**：新表/迁移、新 provider、ChatVideoGallery 改造、Part 1 范围（素材预览字段透出——已完成）。

---

## 1. 文件结构规划

### 新建

| 文件 | 职责 |
| --- | --- |
| `api/test/internal/service/test_video_reassemble.py` | `reassemble_document` 服务层单测（8 用例） |
| `api/internal/core/tools/builtin_tools/providers/video_edit_tools/video_reassemble.py` | 成片编排工具（`clips` JSON 字符串解析 + Celery 派发 + 会话上下文透传） |
| `api/internal/core/tools/builtin_tools/providers/video_edit_tools/video_reassemble.yaml` | 工具声明（params `clips` type=string） |
| `ui/src/views/space/datasets/detail/components/TimelineEditorModal.vue` | 时间线编排弹窗（拖拽重排 / 删除 / 替换 + 提交） |
| `ui/src/views/space/datasets/detail/components/__tests__/TimelineEditorModal.spec.ts` | 编辑器组件测试（4 用例） |

### 修改

| 文件 | 改动 |
| --- | --- |
| `api/internal/service/video_edit_service.py` | 新增 `reassemble_document`（编排解析 + 逐段 trim + concat + 单次落库） |
| `api/internal/task/video_edit_tasks.py` | 新增 `video_reassemble_task` + `__all__` 补名 |
| `api/internal/core/tools/builtin_tools/providers/video_edit_tools/positions.yaml` | 追加 `- video_reassemble` |
| `api/internal/core/tools/builtin_tools/providers/video_edit_tools/__init__.py` | 重导出 `video_reassemble` 工厂 |
| `api/internal/service/assistant_agent_service.py` | L1095 挂载元组补 `"video_reassemble"` |
| `api/app/http/knowledge_mcp_routes.py` | import 行补 `_err`；新增 `POST .../documents/<document_id>/reassemble` 路由 |
| `api/test/internal/task/test_video_edit_tasks.py` | `_install_service._Svc` 加 `reassemble_document`；追加任务用例 + 任务名稳定用例 |
| `api/test/internal/core/tools/test_video_edit_tools.py` | 追加工具用例；**更新既有遍历元组/集合**（chat context / yaml shape / positions / 挂载点 / 包重导出 / provider 发现） |
| `api/test/app/http/test_knowledge_mcp_routes.py` | 追加 reassemble 路由用例（校验 + 派发） |
| `ui/src/services/knowledge-base.ts` | 新增 `reassembleKnowledgeDocument` + `ReassembleClip` 类型 |
| `ui/src/models/knowledge-base.ts` | `ReassembleClip` / `ReassembleRequest` 类型 |
| `ui/src/views/space/datasets/detail/components/MaterialDetailDrawer.vue` | 视频素材显示「重新编排」按钮 + 挂载 `TimelineEditorModal` |
| `ui/src/views/space/datasets/detail/components/__tests__/MaterialDetailDrawer.spec.ts` | 新增按钮/弹窗用例 |
| `ui/src/i18n/messages/zh-CN/space.ts`、`en-US/space.ts` | `space.datasets.detail.material.reassemble*` 键组 |
| `docs/prd/modules/02-knowledge-base.md` | §11.16/§11.17 成片编辑器落地状态更新 |
| `docs/prd/execution-roadmap.md` | KB-P5 未落地项更新 |

**接线自检（完成后逐项核对）**：

| 新符号 | 入口 |
| --- | --- |
| `reassemble_document`（service 方法） | `video_reassemble_task`（`_delegate` 内） |
| `video_reassemble_task`（Celery 任务） | 派发点 ×2：工具 `video_reassemble._run` 的 `delay`；路由 `POST .../reassemble` 的 `delay`；模块已在 `celery_app.TASK_MODULES` |
| `video_reassemble`（builtin 工具） | `positions.yaml` + 包 `__init__.py` 重导出 + `assistant_agent_service` 挂载元组（Provider 动态导入发现） |
| `POST .../documents/<document_id>/reassemble`（路由） | 前端 `reassembleKnowledgeDocument`（`TimelineEditorModal.handleSubmit`） |
| `TimelineEditorModal`（前端组件） | `MaterialDetailDrawer`「重新编排」按钮 → 弹窗 |
| 无「写了没读」 | 服务 → 任务 → 工具/路由 → 前端弹窗，每层均有测试锁定 |

---

## Task 1: 服务层 `reassemble_document`（编排解析 + 逐段合成）

**Files:**
- Create: `api/test/internal/service/test_video_reassemble.py`
- Modify: `api/internal/service/video_edit_service.py`

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/service/test_video_reassemble.py`：

```python
"""成片编辑器服务层：reassemble_document 的编排解析、逐段合成与落库。"""
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.service.video_edit_service import VideoEditError, VideoEditService


def _svc(monkeypatch):
    """构造绕过 DI 的服务实例，替换编排依赖的方法，`_resolve_trim_range` 走真实逻辑。"""
    svc = VideoEditService.__new__(VideoEditService)
    calls = {"trim": [], "concat": [], "store": None}
    docs = {}
    timeline = [
        {"start_sec": 0.0, "end_sec": 5.0, "anchor_type": "speech_sentence",
         "anchor_text": "第一句", "speech_text": "第一句台词"},
        {"start_sec": 5.0, "end_sec": 10.0, "anchor_type": "speech_sentence",
         "anchor_text": "第二句", "speech_text": "第二句台词"},
    ]

    def fake_load(*, account, knowledge_base_id, document_ids):
        return [docs[d] for d in document_ids if d in docs]

    def fake_prepare(doc, work_dir):
        path = Path(work_dir) / f"{doc.id}.mp4"
        path.write_bytes(b"x" * 1024)
        return path

    def fake_trim(*, source_path, output_path, start_sec, end_sec, reencode=False):
        Path(output_path).write_bytes(b"x" * 1024)
        calls["trim"].append((float(start_sec), None if end_sec is None else float(end_sec)))
        return Path(output_path)

    def fake_concat(*, source_paths, output_path):
        Path(output_path).write_bytes(b"x" * 1024)
        calls["concat"].append(len(source_paths))
        return Path(output_path)

    def fake_store(*, account, video_path, name):
        calls["store"] = (video_path, name)
        return {"document_id": str(uuid4()), "artifact": {"name": name, "url": "https://cos/x.mp4"}}

    monkeypatch.setattr(svc, "_load_source_documents", fake_load)
    monkeypatch.setattr(svc, "_prepare_source_file", fake_prepare)
    monkeypatch.setattr(svc, "trim", fake_trim)
    monkeypatch.setattr(svc, "concat", fake_concat)
    monkeypatch.setattr(svc, "_store_output", fake_store)
    monkeypatch.setattr(svc, "_load_timeline_segments", lambda document: list(timeline))
    return svc, calls, docs, timeline


def _doc(doc_id=None):
    return SimpleNamespace(id=doc_id or uuid4(), upload_file=SimpleNamespace(key="cos/key.mp4"))


def test_reassemble_single_clip_trims_and_skips_concat(monkeypatch):
    svc, calls, docs, _ = _svc(monkeypatch)
    main_id = uuid4()
    docs[str(main_id)] = _doc(main_id)

    result = svc.reassemble_document(
        account="acc", knowledge_base_id="kb", document_id=str(main_id),
        clips=[{"document_id": str(main_id), "segment_index": 1}], name="单段成片",
    )

    assert result["document_id"]
    assert calls["trim"] == [(0.0, 5.0)], "第 1 段应取 0~5s"
    assert calls["concat"] == [], "单段编排不应触发 concat"
    assert calls["store"][1] == "单段成片"


def test_reassemble_multi_clips_reorders_and_concats(monkeypatch):
    svc, calls, docs, _ = _svc(monkeypatch)
    main_id = uuid4()
    docs[str(main_id)] = _doc(main_id)

    svc.reassemble_document(
        account="acc", knowledge_base_id="kb", document_id=str(main_id),
        clips=[
            {"document_id": str(main_id), "segment_index": 2},
            {"document_id": str(main_id), "segment_index": 1},
        ],
        name="重排",
    )

    assert calls["trim"] == [(5.0, 10.0), (0.0, 5.0)], "应严格按 clips 顺序逐段裁剪"
    assert calls["concat"] == [2], "多段编排应触发一次 concat（2 段）"


def test_reassemble_whole_clip_uses_full_range(monkeypatch):
    svc, calls, docs, _ = _svc(monkeypatch)
    main_id = uuid4()
    docs[str(main_id)] = _doc(main_id)

    svc.reassemble_document(
        account="acc", knowledge_base_id="kb", document_id=str(main_id),
        clips=[{"document_id": str(main_id), "segment_index": 0}], name="整段",
    )

    assert calls["trim"] == [(0.0, None)], "segment_index=0 表示取整段（首尾全量）"


def test_reassemble_requires_at_least_one_clip(monkeypatch):
    svc, _, _, _ = _svc(monkeypatch)
    with pytest.raises(VideoEditError, match="至少需要一个片段"):
        svc.reassemble_document(
            account="acc", knowledge_base_id="kb", document_id=str(uuid4()),
            clips=[], name="",
        )


def test_reassemble_rejects_clip_without_document_id(monkeypatch):
    svc, _, _, _ = _svc(monkeypatch)
    with pytest.raises(VideoEditError, match="document_id"):
        svc.reassemble_document(
            account="acc", knowledge_base_id="kb", document_id=str(uuid4()),
            clips=[{"segment_index": 1}], name="",
        )


def test_reassemble_rejects_negative_segment_index(monkeypatch):
    svc, _, _, _ = _svc(monkeypatch)
    with pytest.raises(VideoEditError, match="不能为负"):
        svc.reassemble_document(
            account="acc", knowledge_base_id="kb", document_id=str(uuid4()),
            clips=[{"document_id": str(uuid4()), "segment_index": -1}], name="",
        )


def test_reassemble_rejects_segment_index_out_of_range(monkeypatch):
    svc, _, docs, _ = _svc(monkeypatch)
    main_id = uuid4()
    docs[str(main_id)] = _doc(main_id)

    with pytest.raises(VideoEditError, match="越界"):
        svc.reassemble_document(
            account="acc", knowledge_base_id="kb", document_id=str(main_id),
            clips=[{"document_id": str(main_id), "segment_index": 5}], name="",
        )


def test_reassemble_supports_cross_document_replacement(monkeypatch):
    """替换段落：不同素材的时间线段落也能进入编排，归属校验随 _load_source_documents。"""
    svc, calls, docs, _ = _svc(monkeypatch)
    main_id, repl_id = uuid4(), uuid4()
    docs[str(main_id)] = _doc(main_id)
    docs[str(repl_id)] = _doc(repl_id)

    svc.reassemble_document(
        account="acc", knowledge_base_id="kb", document_id=str(main_id),
        clips=[
            {"document_id": str(main_id), "segment_index": 1},
            {"document_id": str(repl_id), "segment_index": 2},
        ],
        name="替换成片",
    )

    assert calls["trim"] == [(0.0, 5.0), (5.0, 10.0)]
    assert calls["concat"] == [2]


def test_reassemble_requires_main_document_exists(monkeypatch):
    svc, _, docs, _ = _svc(monkeypatch)
    main_id, other_id = uuid4(), uuid4()
    docs[str(other_id)] = _doc(other_id)

    with pytest.raises(VideoEditError, match="素材不存在"):
        svc.reassemble_document(
            account="acc", knowledge_base_id="kb", document_id=str(main_id),
            clips=[{"document_id": str(other_id), "segment_index": 1}], name="",
        )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_video_reassemble.py -v`
Expected: FAIL — `AttributeError: 'VideoEditService' object has no attribute 'reassemble_document'`

- [ ] **Step 3: 实现 `reassemble_document`**

在 `api/internal/service/video_edit_service.py` 的 `concat_documents` 之后追加：

```python
    def reassemble_document(
        self, *, account: Any, knowledge_base_id: str, document_id: str,
        clips: list[dict[str, Any]], name: str,
    ) -> dict:
        """按时间线编排重建视频并存入成品库（成片编辑器后端）。

        `clips` 是有序编排片段，每项 `{"document_id": str, "segment_index": int}`：
        - `segment_index` > 0：取该素材第 N 个时间线段落（1-based，越界抛错，
          复用 `_resolve_trim_range` 的既有校验与日志）；
        - `segment_index` 为 0 / 缺省：取该素材完整视频（首尾全量）。
        同一文档可多次引用（重排/复用段落）；替换段落则引用其他素材——
        归属校验统一走 `_load_source_documents`（复用 get_document_detail 双重校验）。

        执行：下载涉及的素材 → 逐项本地 trim（流拷贝秒级）→ concat（仅 1 项
        跳过）→ 单次 `_store_output`。中间产物只存在于工作目录，不污染成品库。
        """
        if not clips:
            raise VideoEditError("编排至少需要一个片段")

        normalized: list[dict[str, Any]] = []
        for clip in clips:
            clip_doc_id = str((clip or {}).get("document_id") or "").strip()
            if not clip_doc_id:
                raise VideoEditError("编排片段缺少 document_id")
            try:
                seg_index = int((clip or {}).get("segment_index") or 0)
            except (TypeError, ValueError):
                raise VideoEditError("编排片段的段落序号必须是整数（0 表示整段）")
            if seg_index < 0:
                raise VideoEditError("编排片段的段落序号不能为负")
            normalized.append({"document_id": clip_doc_id, "segment_index": seg_index})

        # 去重加载涉及的素材（保持首见顺序），并确认主文档确实存在
        unique_ids: list[str] = []
        for clip in normalized:
            if clip["document_id"] not in unique_ids:
                unique_ids.append(clip["document_id"])
        docs = self._load_source_documents(
            account=account, knowledge_base_id=knowledge_base_id,
            document_ids=unique_ids,
        )
        docs_by_id = {str(doc.id): doc for doc in docs}
        if str(document_id) not in docs_by_id:
            raise VideoEditError(f"素材不存在：document_id={document_id}")

        with tempfile.TemporaryDirectory(prefix="video-reassemble-") as work:
            work_dir = Path(work)
            pieces: list[Path] = []
            for index, clip in enumerate(normalized, start=1):
                doc = docs_by_id.get(clip["document_id"])
                if doc is None:
                    raise VideoEditError(f"素材不存在：document_id={clip['document_id']}")
                start, end = self._resolve_trim_range(
                    document=doc, segment_index=clip["segment_index"] or None,
                    start_sec=0.0, end_sec=None,
                )
                source = self._prepare_source_file(doc, work_dir)
                piece = work_dir / f"piece_{index}.mp4"
                self.trim(
                    source_path=source, output_path=piece,
                    start_sec=start, end_sec=end,
                )
                pieces.append(piece)

            if len(pieces) == 1:
                output = pieces[0]
            else:
                output = work_dir / "output.mp4"
                self.concat(source_paths=pieces, output_path=output)
            return self._store_output(account=account, video_path=output, name=name)
```

> 既有 import 核对：`VideoEditError` / `tempfile` / `Path` / `Any` 本文件已导入，无需新增。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_video_reassemble.py -v`
Expected: PASS（9 passed）

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/video_edit_service.py api/test/internal/service/test_video_reassemble.py
git commit -m "feat(kb): VideoEditService.reassemble_document 时间线编排合成（拖拽重排/删除/逐段替换后端）"
```

---

## Task 2: Celery 任务 `video_reassemble_task`

**Files:**
- Modify: `api/internal/task/video_edit_tasks.py`
- Test: `api/test/internal/task/test_video_edit_tasks.py`

- [ ] **Step 1: 更新任务模块 `__all__` 并新增任务**

`api/internal/task/video_edit_tasks.py`：

1. `__all__` 改为：

```python
__all__ = ["video_concat_task", "video_subtitle_task", "video_trim_task", "video_reassemble_task"]
```

2. 在 `video_trim_task` 之前（或文件末尾，`__all__` 之下列任意位置）追加：

```python
@shared_task(
    name="internal.task.video_edit_tasks.video_reassemble_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def video_reassemble_task(
    self, knowledge_base_id: str, document_id: str, clips,
    name: str, account_id: str,
    message_id: str = "", conversation_id: str = "",
):
    """按时间线编排重建库内视频并存入成品库，完成后回填到原对话消息。

    `clips` 为有序编排片段（每项含 document_id / segment_index），
    由工具或前端编辑器提交；业务校验全在
    `VideoEditService.reassemble_document`（素材归属/序号越界/参数非法）。
    """
    service = _load_service()
    account = _load_account(account_id)

    def _run():
        return service.reassemble_document(
            account=account, knowledge_base_id=knowledge_base_id,
            document_id=document_id, clips=list(clips or []), name=name,
        )

    result = _delegate(self, "reassemble", _run)
    _notify_artifact(
        account_id=account_id, message_id=message_id, conversation_id=conversation_id,
        result=result, tool="video_reassemble",
    )
    return result
```

- [ ] **Step 2: 写失败的测试（追加到 `test_video_edit_tasks.py`）**

1. 修改 `_install_service` 里的 `_Svc`，加一个方法：

```python
        def reassemble_document(self, **kw):
            calls.update(kw)
            if error is not None:
                raise error
            return result or {"document_id": "d1"}
```

2. 文件末尾追加：

```python
def test_reassemble_task_delegates_with_clips(monkeypatch):
    calls = _install_service(monkeypatch)
    clips = [{"document_id": "doc-1", "segment_index": 1}]
    out = _invoke(
        video_edit_tasks.video_reassemble_task, _FakeSelf(),
        "kb-1", "doc-1", clips, "新成片", "acc-1",
    )
    assert out == {"document_id": "d1"}
    assert calls["knowledge_base_id"] == "kb-1"
    assert calls["document_id"] == "doc-1"
    assert calls["clips"] == clips
    assert calls["name"] == "新成片"


def test_reassemble_task_does_not_retry_business_error(monkeypatch):
    _install_service(monkeypatch, error=VideoEditError("编排至少需要一个片段"))
    self_obj = _FakeSelf()
    with pytest.raises(VideoEditError, match="至少需要一个片段"):
        _invoke(video_edit_tasks.video_reassemble_task, self_obj, "kb", "doc", [], "n", "acc")
    assert self_obj.retries == []


def test_reassemble_task_retries_on_transient_error(monkeypatch):
    _install_service(monkeypatch, error=RuntimeError("io boom"))
    self_obj = _FakeSelf()
    with pytest.raises(RuntimeError, match="retry:"):
        _invoke(video_edit_tasks.video_reassemble_task, self_obj, "kb", "doc", [{"document_id": "d", "segment_index": 1}], "n", "acc")
    assert len(self_obj.retries) == 1


def test_reassemble_task_name_is_stable():
    # 派发端（工具/路由）按名字路由，改名即断链
    assert video_edit_tasks.video_reassemble_task.name == (
        "internal.task.video_edit_tasks.video_reassemble_task"
    )
```

- [ ] **Step 3: 运行测试确认失败→通过**

Run: `cd api && python -m pytest test/internal/task/test_video_edit_tasks.py -v`
Expected: 新增 4 用例先 FAIL（`AttributeError` / 任务不存在）→ Step 1 实现后 PASS（既有 9 个 + 新增 4 个 = 13 个）

- [ ] **Step 4: Commit**

```bash
git add api/internal/task/video_edit_tasks.py api/test/internal/task/test_video_edit_tasks.py
git commit -m "feat(kb): video_reassemble_task Celery 任务（薄委托 + 单次回填）"
```

---

## Task 3: builtin 工具 `video_reassemble`（四件套 + 挂载点）

**Files:**
- Create: `api/internal/core/tools/builtin_tools/providers/video_edit_tools/video_reassemble.py`
- Create: `api/internal/core/tools/builtin_tools/providers/video_edit_tools/video_reassemble.yaml`
- Modify: `api/internal/core/tools/builtin_tools/providers/video_edit_tools/positions.yaml`
- Modify: `api/internal/core/tools/builtin_tools/providers/video_edit_tools/__init__.py`
- Modify: `api/internal/service/assistant_agent_service.py`
- Test: `api/test/internal/core/tools/test_video_edit_tools.py`

- [ ] **Step 1: 创建工具实现**

创建 `video_reassemble.py`：

```python
"""视频成片编排工具（对话内改细节）。

把库内一个成片/视频按时间线段落重新编排（调整顺序 / 删除 / 用其他素材段落
替换），产物存入成品库（可检索复用）。执行走 Celery（不阻塞对话），派发后
立即返回任务号。

clips 以 **JSON 字符串** 传入（工具参数 type 枚举限制，见 video_reassemble.yaml）：
  [{"document_id": "...", "segment_index": 3}, ...]
`segment_index` 为 1-based 段落序号；0 / 缺省表示取该素材完整视频。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _load_task():
    from internal.task.video_edit_tasks import video_reassemble_task

    return video_reassemble_task


class VideoReassembleInput(BaseModel):
    """成片编排输入。"""

    knowledge_base_id: str = Field(..., description="素材所在知识库 id")
    document_id: str = Field(..., description="主视频（成片）素材 id")
    clips: str = Field(
        ...,
        description="编排片段 JSON 数组字符串，如 [{\"document_id\":\"..\",\"segment_index\":3}]；"
        "segment_index 为 1-based 段落序号，0/缺省取整段",
    )
    name: str = Field("", description="成品名称，可选")


class VideoReassembleTool(BaseTool):
    """把视频按时间线编排重排/删段/替换并存入成品库。"""

    name: str = "video_reassemble"
    description: str = (
        "当用户要求把一段成片/视频的时间线段落重新编排（调整顺序、删除某段、"
        "用其他素材的段落替换某段）时调用。clips 传 JSON 字符串数组，"
        "每项含 document_id 与 segment_index（1-based 段落序号，0/缺省取整段）。"
    )
    args_schema: type[BaseModel] = VideoReassembleInput
    account_id: str = ""
    # 会话上下文：任务完成后据此把成品回填到原消息（对话内成片预览）。
    message_id: str = ""
    conversation_id: str = ""

    def _run(
        self, knowledge_base_id: str = "", document_id: str = "",
        clips: str = "", name: str = "", **kwargs: Any,
    ) -> str:
        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps({"ok": False, "error": "缺少当前账号信息，无法编排"}, ensure_ascii=False)
        if not str(knowledge_base_id or "").strip() or not str(document_id or "").strip():
            return json.dumps(
                {"ok": False, "error": "缺少知识库或素材信息：需要 knowledge_base_id 与 document_id"},
                ensure_ascii=False,
            )

        try:
            parsed = json.loads(str(clips or "").strip() or "[]")
        except json.JSONDecodeError:
            return json.dumps({"ok": False, "error": "编排片段必须是合法 JSON 数组"}, ensure_ascii=False)
        if not isinstance(parsed, list) or not parsed:
            return json.dumps({"ok": False, "error": "编排至少需要一个片段"}, ensure_ascii=False)
        for clip in parsed:
            if not isinstance(clip, dict) or not str(clip.get("document_id") or "").strip():
                return json.dumps({"ok": False, "error": "编排片段缺少 document_id"}, ensure_ascii=False)
            try:
                seg = int(clip.get("segment_index") or 0)
            except (TypeError, ValueError):
                return json.dumps({"ok": False, "error": "段落序号必须是整数（1-based）"}, ensure_ascii=False)
            if seg < 0:
                return json.dumps({"ok": False, "error": "段落序号不能为负"}, ensure_ascii=False)

        try:
            async_result = _load_task().delay(
                str(knowledge_base_id), str(document_id), parsed,
                str(name or "").strip(), account_id,
                message_id=str(kwargs.get("message_id") or self.message_id or ""),
                conversation_id=str(kwargs.get("conversation_id") or self.conversation_id or ""),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("编排任务提交失败 account_id=%s", account_id, exc_info=True)
            return json.dumps({"ok": False, "error": f"编排任务提交失败：{exc}"}, ensure_ascii=False)

        return json.dumps(
            {
                "ok": True,
                "dispatched": True,
                "task_id": str(getattr(async_result, "id", "")),
                "message": "成片编排已提交后台处理，完成后会自动存入成品库并在对话中展示",
            },
            ensure_ascii=False,
        )

    async def _arun(
        self, knowledge_base_id: str = "", document_id: str = "",
        clips: str = "", name: str = "", **kwargs: Any,
    ) -> str:
        return self._run(
            knowledge_base_id=knowledge_base_id, document_id=document_id,
            clips=clips, name=name, **kwargs,
        )


def video_reassemble(**kwargs: Any) -> BaseTool:
    """工厂函数（函数名必须与工具名一致，Provider 按此动态导入）。

    message_id / conversation_id 必须一并透传：任务完成后要据此把成品
    回填到原对话消息（遗漏则「对话内成片预览」静默失效）。
    """
    return VideoReassembleTool(
        account_id=str(kwargs.get("account_id") or "").strip(),
        message_id=str(kwargs.get("message_id") or "").strip(),
        conversation_id=str(kwargs.get("conversation_id") or "").strip(),
    )
```

创建 `video_reassemble.yaml`：

```yaml
name: video_reassemble
label: 成片编排
description: 把知识库里的成片/视频按时间线段落重新编排（调整顺序/删除/用其他素材段落替换），并自动存入成品库。
params:
- name: knowledge_base_id
  label: 知识库
  type: string
  required: true
- name: document_id
  label: 主视频素材
  type: string
  required: true
- name: clips
  label: 编排片段
  description: JSON 数组字符串，每项 {"document_id": "素材id", "segment_index": 段落序号}；segment_index 为 1-based，0/缺省取整段
  type: string
  required: true
- name: name
  label: 成品名称
  type: string
  required: false
task_keywords:
- 重新编排
- 调整顺序
- 重排
- 删掉某段
- 删除段落
- 替换段落
- 换一段
- 时间线编排
- 编排成片
- reassemble
```

- [ ] **Step 2: 登记与挂载（三处）**

1. `positions.yaml`（`api/internal/core/tools/builtin_tools/providers/video_edit_tools/positions.yaml`）追加：

```yaml
- video_reassemble
```

2. `__init__.py`（同目录）改为：

```python
"""视频编辑工具包（裁剪 / 拼接 / 加字幕 / 成片编排）。

必须重导出工厂函数：`Provider._provider_init` 通过
`dynamic_import("...providers.video_edit_tools", "<tool_name>")`（即
`getattr(importlib.import_module(pkg), tool_name)`）取工厂函数，
故包的顶层必须能直接取到与工具同名的可调用对象。
这与同层其它 33 个 provider 的约定一致（见 video_render_tools/__init__.py）。
"""
from .video_concat import video_concat
from .video_reassemble import video_reassemble
from .video_subtitle import video_subtitle
from .video_trim import video_trim

__all__ = ["video_concat", "video_reassemble", "video_subtitle", "video_trim"]
```

3. `api/internal/service/assistant_agent_service.py` L1095 挂载元组改为：

```python
            for edit_tool_name in ("video_trim", "video_concat", "video_subtitle", "video_reassemble"):
```

- [ ] **Step 3: 写失败的测试（追加到 `test_video_edit_tools.py`）**

1. 文件头部导入区追加：

```python
video_reassemble = importlib.import_module(f"{_PKG}.video_reassemble")
```

2. 文件末尾追加新用例：

```python
# ── 成片编排工具（video_reassemble） ──────────────────────────────────────


def test_reassemble_tool_requires_account():
    tool = video_reassemble.video_reassemble()
    payload = json.loads(
        tool._run(knowledge_base_id="kb", document_id="d",
                  clips='[{"document_id": "d", "segment_index": 1}]')
    )
    assert payload["ok"] is False
    assert "账号" in payload["error"]


def test_reassemble_tool_requires_kb_and_document():
    tool = video_reassemble.video_reassemble(account_id="acc")
    payload = json.loads(tool._run(clips='[{"document_id": "d", "segment_index": 1}]'))
    assert payload["ok"] is False
    assert "知识库" in payload["error"] or "素材" in payload["error"]


def test_reassemble_tool_rejects_non_json_clips():
    tool = video_reassemble.video_reassemble(account_id="acc")
    payload = json.loads(tool._run(knowledge_base_id="kb", document_id="d", clips="not-json"))
    assert payload["ok"] is False
    assert "JSON" in payload["error"]


def test_reassemble_tool_rejects_empty_clips():
    tool = video_reassemble.video_reassemble(account_id="acc")
    payload = json.loads(tool._run(knowledge_base_id="kb", document_id="d", clips="[]"))
    assert payload["ok"] is False
    assert "至少" in payload["error"]


def test_reassemble_tool_rejects_clip_without_document_id():
    tool = video_reassemble.video_reassemble(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb", document_id="d",
                  clips='[{"segment_index": 1}]')
    )
    assert payload["ok"] is False
    assert "document_id" in payload["error"]


def test_reassemble_tool_dispatches_parsed_clips(monkeypatch):
    captured = _capture_delay(monkeypatch, video_reassemble)
    tool = video_reassemble.video_reassemble(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb-1", document_id="doc-1",
                  clips='[{"document_id": "doc-2", "segment_index": 2}]',
                  name="重排")
    )
    assert payload["ok"] is True
    assert payload["task_id"] == "task-1"
    assert captured["args"][2] == [{"document_id": "doc-2", "segment_index": 2}], "clips 应解析为列表透传"
    assert captured["args"][3] == "重排"


def test_reassemble_tool_forwards_chat_context_to_celery(monkeypatch):
    captured = _capture_delay(monkeypatch, video_reassemble)
    tool = video_reassemble.video_reassemble(
        account_id="acc", message_id="msg-1", conversation_id="conv-1",
    )
    json.loads(
        tool._run(knowledge_base_id="kb", document_id="d",
                  clips='[{"document_id": "d", "segment_index": 1}]')
    )
    assert captured["kwargs"]["message_id"] == "msg-1"
    assert captured["kwargs"]["conversation_id"] == "conv-1"
```

3. **更新既有遍历元组/集合**（这是本 Task 的隐藏红线——漏改直接红）：

| 既有用例 | 现状 | 改为 |
| --- | --- | --- |
| `test_edit_tool_factories_pass_chat_context` | `for module, tool_name in ((video_trim, "video_trim"), (video_concat, "video_concat"), (video_subtitle, "video_subtitle")):` | 追加 `, (video_reassemble, "video_reassemble")` |
| `test_tool_yamls_declare_expected_shape` | `for stem in ("video_trim", "video_concat", "video_subtitle"):` | 追加 `, "video_reassemble"` |
| `test_positions_yaml_lists_all_three_tools` | 函数名与 `assert set(names) == {"video_trim", "video_concat", "video_subtitle"}` | 改名 `test_positions_yaml_lists_all_four_tools`，断言集合加 `"video_reassemble"` |
| `test_tools_are_mounted_at_runtime_with_account_id` | `for tool_name in ("video_trim", "video_concat", "video_subtitle"):` | 追加 `, "video_reassemble"` |
| `test_package_init_reexports_factories` | `for name in ("video_trim", "video_concat", "video_subtitle"):` | 追加 `, "video_reassemble"` |
| `test_provider_loader_discovers_all_tools` | `assert set(provider.tool_func_map) == {"video_trim", "video_concat", "video_subtitle"}` 与 `for name in (...):` | 集合与元组均加 `"video_reassemble"` |

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/core/tools/test_video_edit_tools.py -v`
Expected: PASS（既有 22 个 + 新增 7 个 = 29 个；若既有遍历用例未同步更新会红，回到 Step 3.3）

- [ ] **Step 5: Commit**

```bash
git add api/internal/core/tools/builtin_tools/providers/video_edit_tools/ api/internal/service/assistant_agent_service.py api/test/internal/core/tools/test_video_edit_tools.py
git commit -m "feat(kb): video_reassemble builtin 工具（clips JSON 参数 + 挂载点 + 四件套登记）"
```

---

## Task 4: REST 路由 `POST .../documents/<document_id>/reassemble`

**Files:**
- Modify: `api/app/http/knowledge_mcp_routes.py`
- Test: `api/test/app/http/test_knowledge_mcp_routes.py`

- [ ] **Step 1: 补 `_err` import 并新增路由**

`api/app/http/knowledge_mcp_routes.py`：

1. import 行（L9-17）改为：

```python
from app.http.support import (
    _err,
    _field,
    _int_arg,
    _json_resp,
    _ok,
    _ok_msg,
    _resolve_account,
    _to_thread,
)
```

2. 在 `async_update_segment` 路由（`POST .../segments/<segment_id>`）之后、`async_knowledge_base_regenerate_icon` 之前插入：

```python
    @quart_app.post("/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>/reassemble")
    async def async_reassemble_document(knowledge_base_id, document_id) -> Response:
        """async 按时间线编排重建视频（成片编辑器提交入口）。

        请求体：`{"clips": [{"document_id": "...", "segment_index": 3}, ...], "name": ""}`
        `segment_index` 为 1-based 段落序号，0/缺省取整段。结构性校验在前
        （片段非空 / 必含 document_id / 序号非负整数），业务校验（素材归属、
        序号越界、文件下载）留在 `VideoEditService.reassemble_document`。
        """
        account, err = await _resolve_account()
        if err is not None:
            return err

        payload = await request.get_json(force=True, silent=True) or {}
        clips = payload.get("clips")
        if not isinstance(clips, list) or not clips:
            return _err("invalid_param", "编排至少需要一个片段")
        for clip in clips:
            if not isinstance(clip, dict) or not str(clip.get("document_id") or "").strip():
                return _err("invalid_param", "编排片段缺少 document_id")
            try:
                segment_index = int(clip.get("segment_index") or 0)
            except (TypeError, ValueError):
                return _err("invalid_param", "编排片段的段落序号必须是整数（0 表示整段）")
            if segment_index < 0:
                return _err("invalid_param", "编排片段的段落序号不能为负")

        from internal.task.video_edit_tasks import video_reassemble_task

        async_result = await _to_thread(
            video_reassemble_task.delay,
            str(knowledge_base_id), str(document_id), clips,
            str(payload.get("name") or "").strip(), str(account.id),
        )
        return _ok({"task_id": str(getattr(async_result, "id", ""))})
```

- [ ] **Step 2: 写失败的测试（追加到 `test_knowledge_mcp_routes.py`）**

```python
class TestReassembleDocumentRoute:
    def test_route_registered(self):
        rules = [r.rule for r in asgi_app.quart_app.url_map.iter_rules()]
        assert "/space/knowledge-bases/<uuid:knowledge_base_id>/documents/<uuid:document_id>/reassemble" in rules

    def test_reassemble_dispatches_task_with_clips(self, monkeypatch):
        """合法 clips 应派发 video_reassemble_task（同步 delay 在 _to_thread 内）。"""
        from internal.task import video_edit_tasks as tasks_module

        captured = {}

        class _Task:
            @staticmethod
            def delay(*args, **kwargs):
                captured["args"] = args
                return SimpleNamespace(id="task-re")

        account = _setup(monkeypatch)
        monkeypatch.setattr(tasks_module, "video_reassemble_task", _Task)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{uuid4()}/documents/{uuid4()}/reassemble",
                    json={"clips": [{"document_id": str(uuid4()), "segment_index": 2}], "name": "重排"},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 200
        assert payload["code"] == "success"
        assert payload["data"]["task_id"] == "task-re"
        assert captured["args"][1] == "重排" or captured["args"][3] == "重排"

    def test_reassemble_rejects_empty_clips(self, monkeypatch):
        account = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{uuid4()}/documents/{uuid4()}/reassemble",
                    json={"clips": []},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert "至少需要一个片段" in payload["message"]

    def test_reassemble_rejects_clip_without_document_id(self, monkeypatch):
        account = _setup(monkeypatch)

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    f"/space/knowledge-bases/{uuid4()}/documents/{uuid4()}/reassemble",
                    json={"clips": [{"segment_index": 1}]},
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())

        assert resp.status_code == 400
        assert "document_id" in payload["message"]
```

> 说明：`from internal.task.video_edit_tasks import video_reassemble_task` 在路由函数体内每次执行都会重新取模块属性，故 `monkeypatch.setattr(tasks_module, "video_reassemble_task", _Task)` 即可生效；`_setup` 已在文件顶部定义，直接复用。

- [ ] **Step 3: 运行测试确认通过**

Run: `cd api && python -m pytest test/app/http/test_knowledge_mcp_routes.py -v`
Expected: PASS（既有用例 + 新增 4 个）

- [ ] **Step 4: Commit**

```bash
git add api/app/http/knowledge_mcp_routes.py api/test/app/http/test_knowledge_mcp_routes.py
git commit -m "feat(kb): POST /space/knowledge-bases/<kb>/documents/<doc>/reassemble 编排提交路由"
```

---

## Task 5: 后端全量回归

**Files:** 无新增

- [ ] **Step 1: 跑视频编辑相关既有测试**

Run: `cd api && python -m pytest test/internal/service/test_video_edit_service.py test/internal/service/test_video_reassemble.py test/internal/task/test_video_edit_tasks.py test/internal/core/tools/test_video_edit_tools.py test/app/http/test_knowledge_mcp_routes.py -q`
Expected: PASS

- [ ] **Step 2: 跑全量单测确认无回归**

Run: `cd api && python -m pytest -q`
Expected: PASS（与基线一致：既有 1 个环境性失败 `test_resend_login_challenge_should_reuse_pending_challenge` 不修）

- [ ] **Step 3: Commit（如有修正）**

```bash
git add -u api/
git commit -m "test(kb): 成片编辑器后端回归修正"
```

---

## Task 6: 前端 service + 类型 + `TimelineEditorModal.vue`

**Files:**
- Modify: `ui/src/services/knowledge-base.ts`
- Modify: `ui/src/models/knowledge-base.ts`
- Create: `ui/src/views/space/datasets/detail/components/TimelineEditorModal.vue`
- Create: `ui/src/views/space/datasets/detail/components/__tests__/TimelineEditorModal.spec.ts`

- [ ] **Step 1: 新增 service 与类型**

`ui/src/models/knowledge-base.ts` 末尾追加：

```typescript
export type ReassembleClip = {
  document_id: string
  segment_index: number
}

export type ReassembleRequest = {
  clips: ReassembleClip[]
  name?: string
}
```

`ui/src/services/knowledge-base.ts` 末尾（`getKnowledgeSegmentsWithPage` 之后）追加：

```typescript
// 按时间线编排重建视频（成片编辑器提交）
export const reassembleKnowledgeDocument = (
  knowledge_base_id: string,
  document_id: string,
  req: ReassembleRequest,
) => {
  return post<BaseResponse<{ task_id: string }>>(
    `/space/knowledge-bases/${knowledge_base_id}/documents/${document_id}/reassemble`,
    { body: req },
  )
}
```

在 service 文件顶部 import 区补 `ReassembleRequest`（从 `@/models/knowledge-base` 导入）。

- [ ] **Step 2: 写失败的组件测试**

创建 `__tests__/TimelineEditorModal.spec.ts`：

```typescript
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createI18n } from 'vue-i18n'

import TimelineEditorModal from '../TimelineEditorModal.vue'
import * as services from '@/services/knowledge-base'
import * as arco from '@arco-design/web-vue'

vi.mock('@/services/knowledge-base')
vi.mock('@arco-design/web-vue', () => ({
  Message: { success: vi.fn(), error: vi.fn() },
  Modal: { warning: vi.fn() },
  Drawer: { install: vi.fn() },
  Button: { install: vi.fn() },
  Empty: { install: vi.fn() },
  Input: { install: vi.fn() },
  Skeleton: { install: vi.fn() },
}))

const mocks = vi.mocked(services)

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      space: {
        datasets: {
          detail: {
            material: {
              reassembleTitle: '时间线编排',
              reassembleHint: '拖拽调整顺序',
              reassembleDelete: '删除',
              reassembleReplace: '替换',
              reassembleReplaceTitle: '选择替换素材',
              reassemblePickDoc: '选择素材',
              reassemblePickSegment: '选择段落',
              reassembleSubmit: '生成成片',
              reassembleCancel: '取消',
              reassembleBack: '返回',
              reassembleSubmitted: '已提交后台处理',
              reassembleFailed: '编排提交失败',
              reassembleEmpty: '暂无时间线段落',
              reassembleNamePlaceholder: '成品名称（可选）',
            },
          },
        },
      },
    },
  },
})

const props = { knowledgeBaseId: 'kb-1', documentId: 'doc-1', visible: true }

const stubs = {
  'a-modal': {
    template: '<div><slot name="title" /><slot /></div>',
    props: ['visible'],
  },
  'a-input': { template: '<input :value="modelValue" />', props: ['modelValue'] },
  'a-button': { template: '<button @click="$emit(\'click\')"><slot /></button>' },
  'a-empty': { template: '<div><slot name="description" /></div>' },
  'a-skeleton': { template: '<div />' },
}

const timelineSegments = [
  { id: 's1', position: 1, content: '第一段', source: 'vision_timeline', start_sec: 0, end_sec: 5, frame_url: 'https://cos/f1.jpg', speech_text: '台词一' },
  { id: 's2', position: 2, content: '第二段', source: 'vision_timeline', start_sec: 5, end_sec: 10, frame_url: 'https://cos/f2.jpg', speech_text: '台词二' },
  { id: 's3', position: 3, content: '第三段', source: 'vision_timeline', start_sec: 10, end_sec: 15, frame_url: 'https://cos/f3.jpg', speech_text: '台词三' },
]

const paginator = { current_page: 1, page_size: 20, total_page: 1, total_record: 1 }

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getKnowledgeSegmentsWithPage.mockResolvedValue({ data: { list: timelineSegments, paginator } })
  mocks.getKnowledgeDocumentsWithPage.mockResolvedValue({ data: { list: [], paginator } })
  mocks.reassembleKnowledgeDocument.mockResolvedValue({ data: { task_id: 't1' }, message: '', code: 'success' })
})

describe('TimelineEditorModal', () => {
  it('挂载后渲染主文档全部时间线段落', async () => {
    const wrapper = mount(TimelineEditorModal, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    expect(mocks.getKnowledgeSegmentsWithPage).toHaveBeenCalledWith('kb-1', 'doc-1', expect.anything())
    expect(wrapper.text()).toContain('第一段')
    expect(wrapper.text()).toContain('第二段')
    expect(wrapper.text()).toContain('第三段')
  })

  it('点击删除后段落减少，删光后提交按钮禁用', async () => {
    const wrapper = mount(TimelineEditorModal, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    const deleteButtons = wrapper.findAll('button[data-test="remove-clip"]')
    await deleteButtons[0].trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('第一段')
  })

  it('提交时携带 clips 与名称', async () => {
    const wrapper = mount(TimelineEditorModal, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    await wrapper.find('button[data-test="submit"]').trigger('click')
    await flushPromises()
    expect(mocks.reassembleKnowledgeDocument).toHaveBeenCalledWith('kb-1', 'doc-1', {
      clips: [
        { document_id: 'doc-1', segment_index: 1 },
        { document_id: 'doc-1', segment_index: 2 },
        { document_id: 'doc-1', segment_index: 3 },
      ],
      name: '',
    })
  })

  it('替换流程：选择素材 → 选择段落 → clip 更新为替换素材', async () => {
    mocks.getKnowledgeDocumentsWithPage.mockResolvedValue({
      data: {
        list: [
          { id: 'repl-1', name: '替换源.mp4', media_type: 'video', status: 'completed', character_count: 0 },
        ],
        paginator,
      },
    })
    mocks.getKnowledgeSegmentsWithPage.mockResolvedValueOnce({ data: { list: timelineSegments, paginator } }) // 主文档
      .mockResolvedValueOnce({
        data: {
          list: [
            { id: 'r1', position: 1, content: '替换段', source: 'vision_timeline', start_sec: 2, end_sec: 7, frame_url: '', speech_text: '替换台词' },
          ],
          paginator,
        },
      })
    const wrapper = mount(TimelineEditorModal, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()

    await wrapper.find('button[data-test="replace-clip-0"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('替换源.mp4')

    await wrapper.find('button[data-test="pick-doc-repl-1"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('替换段')

    await wrapper.find('button[data-test="pick-segment-0"]').trigger('click')
    await flushPromises()

    await wrapper.find('button[data-test="submit"]').trigger('click')
    await flushPromises()
    expect(mocks.reassembleKnowledgeDocument).toHaveBeenCalledWith('kb-1', 'doc-1', {
      clips: [
        { document_id: 'repl-1', segment_index: 1 },
        { document_id: 'doc-1', segment_index: 2 },
        { document_id: 'doc-1', segment_index: 3 },
      ],
      name: '',
    })
  })
})
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd ui && npx vitest run src/views/space/datasets/detail/components/__tests__/TimelineEditorModal.spec.ts`
Expected: FAIL — 组件文件不存在（`Cannot find module '../TimelineEditorModal.vue'`）

- [ ] **Step 4: 实现 `TimelineEditorModal.vue`**

创建组件：

```vue
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Message } from '@arco-design/web-vue'
import {
  useGetKnowledgeDocumentsWithPage,
  useGetKnowledgeSegmentsWithPage,
} from '@/hooks/use-knowledge-base'
import { reassembleKnowledgeDocument } from '@/services/knowledge-base'
import { getErrorMessage } from '@/utils/error'

type TimelineClip = {
  document_id: string
  segment_index: number
  frame_url?: string
  start_sec?: number
  end_sec?: number
  speech_text?: string
  content?: string
}

const props = defineProps<{
  knowledgeBaseId: string
  documentId: string
  visible: boolean
}>()
const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
}>()
const { t } = useI18n()

// 主文档分段与替换素材分段必须用两个 hook 实例：单实例单缓存，
// 共用一个会把主文档时间线冲掉（替换素材分段加载会覆盖缓存）。
const { loading: segLoading, segments: mainSegments, loadSegments: loadMainSegments } = useGetKnowledgeSegmentsWithPage()
const { segments: sourceSegments, loadSegments: loadSourceSegments } = useGetKnowledgeSegmentsWithPage()
const { loading: docLoading, documents, loadDocuments } = useGetKnowledgeDocumentsWithPage()

const clips = ref<TimelineClip[]>([])
const name = ref('')
const submitting = ref(false)
const replaceIndex = ref<number | null>(null)
const replaceDocId = ref('')
const replaceSegments = ref<TimelineClip[]>([])
const dragIndex = ref<number | null>(null)

const mainTimeline = computed(() =>
  mainSegments.value.filter(
    seg => seg.source === 'vision_timeline' && Number(seg.start_sec) >= 0,
  ),
)

const replaceableVideos = computed(() =>
  documents.value.filter(doc => doc.media_type === 'video'),
)

const canSubmit = computed(() => clips.value.length > 0 && !submitting.value)

watch(
  () => [props.visible, props.documentId] as const,
  async ([visible, docId]) => {
    if (!visible || !docId || !props.knowledgeBaseId) return
    clips.value = []
    name.value = ''
    replaceIndex.value = null
    replaceDocId.value = ''
    replaceSegments.value = []
    dragIndex.value = null
    await loadMainSegments(props.knowledgeBaseId, docId, true)
    // 初始编排 = 主文档全部时间线段落（按 position 顺序）
    clips.value = mainTimeline.value.map((seg, index) => ({
      document_id: docId,
      segment_index: index + 1,
      frame_url: seg.frame_url,
      start_sec: seg.start_sec,
      end_sec: seg.end_sec,
      speech_text: seg.speech_text,
      content: seg.content,
    }))
  },
  { immediate: true },
)

const handleDragStart = (index: number) => {
  dragIndex.value = index
}

const handleDragOver = (event: DragEvent) => {
  event.preventDefault()
}

const handleDrop = (index: number) => {
  if (dragIndex.value === null || dragIndex.value === index) return
  const list = [...clips.value]
  const [moved] = list.splice(dragIndex.value, 1)
  list.splice(index, 0, moved)
  clips.value = list
  dragIndex.value = null
}

const handleRemove = (index: number) => {
  clips.value = clips.value.filter((_, i) => i !== index)
}

const openReplacer = async (index: number) => {
  replaceIndex.value = index
  replaceDocId.value = ''
  replaceSegments.value = []
  await loadDocuments(props.knowledgeBaseId, {
    current_page: 1,
    page_size: 50,
    search_word: '',
  })
}

const pickReplaceDoc = async (docId: string) => {
  replaceDocId.value = docId
  replaceSegments.value = []
  await loadSourceSegments(props.knowledgeBaseId, docId, true)
  replaceSegments.value = sourceSegments.value
    .filter(seg => seg.source === 'vision_timeline' && Number(seg.start_sec) >= 0)
    .map((seg, index) => ({
      document_id: docId,
      segment_index: index + 1,
      frame_url: seg.frame_url,
      start_sec: seg.start_sec,
      end_sec: seg.end_sec,
      speech_text: seg.speech_text,
      content: seg.content,
    }))
}

const applyReplace = (seg: TimelineClip) => {
  if (replaceIndex.value === null) return
  const next = [...clips.value]
  next[replaceIndex.value] = seg
  clips.value = next
  replaceIndex.value = null
  replaceDocId.value = ''
  replaceSegments.value = []
}

const handleSubmit = async () => {
  if (clips.value.length === 0) return
  submitting.value = true
  try {
    await reassembleKnowledgeDocument(props.knowledgeBaseId, props.documentId, {
      clips: clips.value.map(clip => ({
        document_id: clip.document_id,
        segment_index: clip.segment_index,
      })),
      name: name.value,
    })
    Message.success(t('space.datasets.detail.material.reassembleSubmitted'))
    emit('update:visible', false)
  } catch (error) {
    Message.error(getErrorMessage(error, t('space.datasets.detail.material.reassembleFailed')))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <a-modal
    :visible="visible"
    :width="720"
    :footer="false"
    @cancel="emit('update:visible', false)"
  >
    <template #title>
      <span class="text-base font-semibold text-text">
        {{ t('space.datasets.detail.material.reassembleTitle') }}
      </span>
    </template>

    <div class="space-y-3">
      <p class="text-xs text-muted">
        {{ t('space.datasets.detail.material.reassembleHint') }}
      </p>

      <a-input
        v-model="name"
        :placeholder="t('space.datasets.detail.material.reassembleNamePlaceholder')"
      />

      <a-skeleton v-if="segLoading" :animation="true" />
      <a-empty v-else-if="mainTimeline.length === 0">
        <template #description>{{ t('space.datasets.detail.material.reassembleEmpty') }}</template>
      </a-empty>

      <div v-else class="space-y-2">
        <div
          v-for="(clip, index) in clips"
          :key="`${clip.document_id}-${clip.segment_index}-${index}`"
          class="flex items-center gap-3 rounded-lg border border-border-c bg-surface p-3"
          draggable="true"
          @dragstart="handleDragStart(index)"
          @dragover="handleDragOver"
          @drop="handleDrop(index)"
        >
          <img
            v-if="clip.frame_url"
            :src="clip.frame_url"
            class="h-14 w-20 shrink-0 rounded object-cover"
            alt=""
          />
          <div class="min-w-0 flex-1">
            <p class="line-clamp-1 text-sm font-medium text-text">
              {{ clip.speech_text || clip.content || `#${index + 1}` }}
            </p>
            <p class="mt-0.5 text-xs text-muted">
              {{ formatTime(clip.start_sec) }} ~ {{ formatTime(clip.end_sec) }}
            </p>
          </div>
          <button
            type="button"
            class="shrink-0 text-xs text-brand"
            :data-test="`replace-clip-${index}`"
            @click="openReplacer(index)"
          >
            {{ t('space.datasets.detail.material.reassembleReplace') }}
          </button>
          <button
            type="button"
            class="shrink-0 text-xs text-red-500"
            data-test="remove-clip"
            @click="handleRemove(index)"
          >
            {{ t('space.datasets.detail.material.reassembleDelete') }}
          </button>
        </div>
      </div>

      <!-- 替换素材选择区 -->
      <div
        v-if="replaceIndex !== null"
        class="rounded-lg border border-border-c bg-surface-2 p-3"
      >
        <p class="mb-2 text-xs font-medium text-text-2">
          {{ t('space.datasets.detail.material.reassembleReplaceTitle') }}
        </p>
        <div v-if="replaceDocId === ''" class="space-y-1">
          <a-skeleton v-if="docLoading" :animation="true" />
          <button
            v-for="doc in replaceableVideos"
            :key="doc.id"
            type="button"
            class="block w-full rounded px-2 py-1.5 text-left text-sm text-text hover:bg-surface"
            :data-test="`pick-doc-${doc.id}`"
            @click="pickReplaceDoc(String(doc.id))"
          >
            {{ doc.name }}
          </button>
        </div>
        <div v-else class="space-y-1">
          <button
            type="button"
            class="mb-1 text-xs text-muted"
            :data-test="'back-to-docs'"
            @click="replaceDocId = ''; replaceSegments = []"
          >
            {{ t('space.datasets.detail.material.reassembleBack') }}
          </button>
          <a-skeleton v-if="segLoading" :animation="true" />
          <button
            v-for="(seg, segIndex) in replaceSegments"
            :key="segIndex"
            type="button"
            class="block w-full rounded px-2 py-1.5 text-left text-sm text-text hover:bg-surface"
            :data-test="`pick-segment-${segIndex}`"
            @click="applyReplace(seg)"
          >
            {{ seg.speech_text || seg.content || `#${segIndex + 1}` }}
            <span class="ml-1 text-xs text-muted">
              {{ formatTime(seg.start_sec) }} ~ {{ formatTime(seg.end_sec) }}
            </span>
          </button>
        </div>
      </div>

      <div class="flex justify-end gap-2 pt-1">
        <a-button @click="emit('update:visible', false)">
          {{ t('space.datasets.detail.material.reassembleCancel') }}
        </a-button>
        <a-button
          type="primary"
          data-test="submit"
          :disabled="!canSubmit"
          :loading="submitting"
          @click="handleSubmit"
        >
          {{ t('space.datasets.detail.material.reassembleSubmit') }}
        </a-button>
      </div>
    </div>
  </a-modal>
</template>

<script lang="ts">
const formatTime = (sec?: number) => {
  const total = Math.max(0, Math.floor(Number(sec) || 0))
  const m = Math.floor(total / 60).toString().padStart(2, '0')
  const s = (total % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}
</script>
```

> 注意：`formatTime` 放在第二个 `<script lang="ts">` 普通脚本块里导出为顶层函数，`<script setup>` 内可直接调用（同一 SFC 的两个 script 块共享作用域）。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd ui && npx vitest run src/views/space/datasets/detail/components/__tests__/TimelineEditorModal.spec.ts`
Expected: PASS（4 passed）

- [ ] **Step 6: Commit**

```bash
git add ui/src/services/knowledge-base.ts ui/src/models/knowledge-base.ts ui/src/views/space/datasets/detail/components/TimelineEditorModal.vue ui/src/views/space/datasets/detail/components/__tests__/TimelineEditorModal.spec.ts
git commit -m "feat(ui): 时间线编排弹窗 TimelineEditorModal（拖拽重排/删除/逐段替换 + 提交）"
```

---

## Task 7: 抽屉入口按钮 + i18n 双侧同步

**Files:**
- Modify: `ui/src/views/space/datasets/detail/components/MaterialDetailDrawer.vue`
- Modify: `ui/src/views/space/datasets/detail/components/__tests__/MaterialDetailDrawer.spec.ts`
- Modify: `ui/src/i18n/messages/zh-CN/space.ts`
- Modify: `ui/src/i18n/messages/en-US/space.ts`

- [ ] **Step 1: 补 i18n 键**

`zh-CN/space.ts` 的 `datasets.detail.material` 块内补：

```typescript
      reassemble: '重新编排',
      reassembleTitle: '时间线编排',
      reassembleHint: '拖拽调整顺序，可删除段落或用其他素材的段落替换',
      reassembleDelete: '删除',
      reassembleReplace: '替换',
      reassembleReplaceTitle: '选择替换素材',
      reassemblePickDoc: '选择素材',
      reassemblePickSegment: '选择段落',
      reassembleSubmit: '生成成片',
      reassembleCancel: '取消',
      reassembleBack: '返回',
      reassembleSubmitted: '已提交后台处理，完成后会自动存入成品库',
      reassembleFailed: '编排提交失败，请稍后重试',
      reassembleEmpty: '暂无时间线段落，无法编排',
      reassembleNamePlaceholder: '成品名称（可选）',
```

`en-US/space.ts` 的对应位置补：

```typescript
      reassemble: 'Reassemble',
      reassembleTitle: 'Timeline Editor',
      reassembleHint: 'Drag to reorder; delete clips or replace with a segment from another asset',
      reassembleDelete: 'Delete',
      reassembleReplace: 'Replace',
      reassembleReplaceTitle: 'Choose replacement asset',
      reassemblePickDoc: 'Pick asset',
      reassemblePickSegment: 'Pick segment',
      reassembleSubmit: 'Generate video',
      reassembleCancel: 'Cancel',
      reassembleBack: 'Back',
      reassembleSubmitted: 'Submitted; the finished video will be saved to the output library',
      reassembleFailed: 'Failed to submit, please try again later',
      reassembleEmpty: 'No timeline segments to edit',
      reassembleNamePlaceholder: 'Output name (optional)',
```

- [ ] **Step 2: 写失败的组件测试（追加到 `MaterialDetailDrawer.spec.ts`）**

```typescript
  it('视频素材显示重新编排按钮，点击后打开编排弹窗', async () => {
    mocks.getKnowledgeDocument.mockResolvedValue({
      data: {
        id: 'd1',
        name: 'demo.mp4',
        media_type: 'video',
        segment_count: 3,
        character_count: 0,
        status: 'completed',
      },
    })
    mocks.getKnowledgeSegmentsWithPage.mockResolvedValue({
      data: {
        list: [
          { id: 's1', position: 1, content: '段1', source: 'vision_timeline', start_sec: 0, end_sec: 5 },
        ],
        paginator: { current_page: 1, page_size: 20, total_page: 1, total_record: 1 },
      },
    })
    const wrapper = mount(MaterialDetailDrawer, {
      props,
      global: { plugins: [i18n], stubs },
    })
    await flushPromises()
    const button = wrapper.find('[data-test="open-reassemble"]')
    expect(button.exists()).toBe(true)
    await button.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-test="reassemble-modal"]').exists()).toBe(true)
  })
```

> 既有 `beforeEach` 会重置 `getKnowledgeDocument` / `getKnowledgeSegmentsWithPage`；内联 i18n 字典需补本用例引用的键（`reassemble` 与弹窗内文案），缺键时 `t()` 回退裸键导致 `data-test="open-reassemble"` 仍可断言（按钮文案无关断言），但弹窗内文案会显示裸键——**为稳妥，把 Task 6 测试里的内联字典键组复制进本 spec 的内联字典**。

- [ ] **Step 3: 运行测试确认失败**

Run: `cd ui && npx vitest run src/views/space/datasets/detail/components/__tests__/MaterialDetailDrawer.spec.ts`
Expected: FAIL — 找不到 `[data-test="open-reassemble"]`

- [ ] **Step 4: 实现抽屉入口**

`MaterialDetailDrawer.vue`：

1. script 区新增状态与导入：

```typescript
import { ref, watch } from 'vue'
import TimelineEditorModal from './TimelineEditorModal.vue'
```

（script 区追加）:

```typescript
const editorVisible = ref(false)
const canReassemble = computed(() =>
  document.value.media_type === 'video',
)
```

> 需要把 `computed` 加入现有 `import { ref, watch } from 'vue'` 行：`import { computed, ref, watch } from 'vue'`。

2. 模板按钮区（L86-93 的按钮组）在「删除」按钮前插入：

```vue
        <a-button
          v-if="canReassemble"
          size="small"
          data-test="open-reassemble"
          @click="editorVisible = true"
        >
          {{ t('space.datasets.detail.material.reassemble') }}
        </a-button>
```

3. 抽屉内（`</a-drawer>` 之前）挂载编辑器：

```vue
      <timeline-editor-modal
        v-model:visible="editorVisible"
        :knowledge-base-id="knowledgeBaseId"
        :document-id="String(document.id || '')"
      />
```

> 由于组件使用 `<script setup>`，`TimelineEditorModal` 导入后模板里自动可用（`<timeline-editor-modal>`）。若既有测试的 `stubs` 不含该组件，需在 `MaterialDetailDrawer.spec.ts` 的 `stubs` 里加 `'timeline-editor-modal': { template: '<div data-test="reassemble-modal" />', props: ['visible'] }`（见 Step 2 说明）。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd ui && npx vitest run src/views/space/datasets/detail/components/__tests__/MaterialDetailDrawer.spec.ts`
Expected: PASS（既有 3 个 + 新增 1 个 = 4 个）

- [ ] **Step 6: Commit**

```bash
git add ui/src/views/space/datasets/detail/components/MaterialDetailDrawer.vue ui/src/views/space/datasets/detail/components/__tests__/MaterialDetailDrawer.spec.ts ui/src/i18n/messages/zh-CN/space.ts ui/src/i18n/messages/en-US/space.ts
git commit -m "feat(ui): 素材详情抽屉重新编排入口 + 编排弹窗 i18n 双侧同步"
```

---

## Task 8: i18n parity + 前端全量

**Files:** 无新增

- [ ] **Step 1: 跑 i18n parity**

Run: `cd ui && npx vitest run src/i18n/__tests__/parity.spec.ts`
Expected: PASS（zh/en 键集一致、`t('...')` 引用的键均存在于字典；若报 `(引用位置: ...)` 按提示修键路径）

- [ ] **Step 2: 跑前端全量**

Run: `cd ui && npx vitest run`
Expected: PASS（既有 133 文件 607 tests + 本计划新增用例）

- [ ] **Step 3: Commit（如有修正）**

```bash
git add -u ui/
git commit -m "test(ui): 成片编辑器前端回归修正"
```

---

## Task 9: 文档同步 + 接线自检

**Files:**
- Modify: `docs/prd/modules/02-knowledge-base.md`
- Modify: `docs/prd/execution-roadmap.md`

- [ ] **Step 1: 更新 `docs/prd/modules/02-knowledge-base.md`**

§11.16（L928）「未落地」行改为：

```markdown
**已落地（KB-P5 收尾·成片编辑器）**：时间线编排——对成片/素材的时间线段落拖拽重排、删除段落、用其他素材的段落替换某段（素材详情抽屉「重新编排」入口，`TimelineEditorModal`）；提交走 `POST /space/knowledge-bases/<kb_id>/documents/<document_id>/reassemble` 派发 `video_reassemble_task`，产物入成品库；对话内由 `video_reassemble` builtin 工具覆盖同一链路（`clips` 传 JSON 字符串，`segment_index` 1-based），完成后回填对话内成片预览。对话消息卡片内的直编入口未落地（artifact 载荷不含 document_id）。
```

§11.17（L967）「未落地」行改为：

```markdown
**已落地（KB-P5 收尾）**：网格缩略图直出（`frame_url`）与成品库播放入口（素材详情抽屉内联播放）；时间线编排编辑器见 §11.16。
```

- [ ] **Step 2: 更新 `docs/prd/execution-roadmap.md`**

KB-P5 行（L416）的「未落地项」括号更新为：

```markdown
未落地项：对话消息卡片内直编入口（artifact 载荷不含 document_id，见 modules/02-knowledge-base.md §11.16）
```

- [ ] **Step 3: 接线自检（AGENTS.md 强制，逐项核对）**

| 检查项 | 结果 |
| --- | --- |
| `reassemble_document` 入口 | `video_reassemble_task`（`_delegate` 内调用），任务模块已在 `celery_app.TASK_MODULES`（L85）+ 显式 import（L105） |
| `video_reassemble_task` 派发点 | ① 工具 `video_reassemble._run` 的 `delay`（工具已挂载：positions.yaml + `__init__.py` 重导出 + `assistant_agent_service` 挂载元组）；② 路由 `POST .../reassemble` 的 `delay` |
| `video_reassemble` 工具挂载 | `providers.yaml` 的 `video_edit_tools` provider 已存在（不动）；`get_tool("video_edit_tools", "video_reassemble")` 由 Provider 按 positions.yaml 动态导入发现 |
| REST 路由 | `register_routes` 内 `@quart_app.post`（同文件注册）；前端 `reassembleKnowledgeDocument` 调用 |
| `TimelineEditorModal` | `MaterialDetailDrawer`「重新编排」按钮（`media_type === 'video'` 显示）→ 弹窗 |
| 无「写了没读」 | 每层均有测试锁定：服务 9 用例 / 任务 4 用例 / 工具 7 用例 + 既有遍历更新 / 路由 4 用例 / 组件 4+1 用例 |
| 无新表/迁移 | 不适用 |

- [ ] **Step 4: 更新知识图谱**

```bash
python -m graphify update .
```

- [ ] **Step 5: Commit**

```bash
git add docs/prd/modules/02-knowledge-base.md docs/prd/execution-roadmap.md
git commit -m "docs(kb): 成片编辑器（时间线编排）落地 + roadmap 状态同步"
```

---

## 验收清单（两份计划全部完成后统一核对）

- [ ] 后端：`cd api && python -m pytest -q`（基线 5282 passed / 1 环境性失败不修）
- [ ] 前端：`cd ui && npx vitest run`（含 parity.spec.ts）
- [ ] 接线：§Task 9 Step 3 自检表逐项为「可复核」
- [ ] 文档：02-knowledge-base.md / execution-roadmap.md 无「未落地/待确认」过期标记
- [ ] 交付入口自证：编辑器入口 = 素材详情抽屉「重新编排」按钮；对话内 = `video_reassemble` 工具；任务派发 = `POST /space/knowledge-bases/<kb_id>/documents/<document_id>/reassemble`
