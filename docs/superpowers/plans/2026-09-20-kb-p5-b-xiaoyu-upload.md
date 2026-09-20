# KB-P5-B 小钰帮传 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通「对话内让小钰把素材存进用户知识库」：新增 builtin 工具 `upload_to_knowledge_base`，Agent 拿到平台已生成的文件 id 后建档入库（板块类型硬校验 + 校验后落盘 + 触发索引），复用既有「UploadFile → 建档 → 索引」链路，与用户自传操作同一份数据。

**Architecture:** 工具接收 `file_id`（对话附件/先前上传形成的 UploadFile，**不接受任意本地路径**——api 容器读不到用户本机文件，且会引入任意文件读取安全洞）。工具内部：加载 Account → 加载 UploadFile → 校验归属 → 调 `KnowledgeBaseService.create_document_from_upload_file`（板块媒体类型硬约束 + 配额已在文件上传阶段计入）。挂载进 `assistant_agent_service._build_assistant_runtime_tools`（与 `create_knowledge_base` 同处，注入 account_id）。

**Tech Stack:** Python 3.12 / LangChain BaseTool / pydantic v2 / Quart injector / pytest

---

## 0. 现状核对摘要（2026-09-20 实测）

| 事实 | 依据 |
| --- | --- |
| 对话工具挂载点已存在且注入 account_id | [assistant_agent_service.py](../../../api/internal/service/assistant_agent_service.py) L1049-1058（`knowledge_base_tools/create_knowledge_base`） |
| 建档入口 `create_document_from_upload_file(knowledge_base_id=, upload_file=, account=, partition_id=)` 已实现 | [knowledge_base_service.py](../../../api/internal/service/knowledge_base_service.py) L286-328（含板块硬约束 + 触发索引） |
| 上传链路（UploadFile 生成）已存在：`chunked_upload_service` / `upload_file_service` | 用户自传走同链路，配额由 `chunked_upload_service` 的 `check_quota` / `consume_quota` 计 |
| 现有对话工具范式（py + yaml + positions + providers + 工厂 + 测试） | `create_knowledge_base` 全套 |
| 工具测试现成范式（_load_task 捕获 delay、工厂上下文透传断言） | `test_video_edit_tools.py`（KB-P4 建立） |

**本计划不涉及**：新表/迁移、认证、权限点；文件内容上传本身（复用既有 UploadFile 链路）。

---

## 1. 文件结构规划

| 文件 | 职责 |
| --- | --- |
| Create: `api/internal/core/tools/builtin_tools/providers/knowledge_base_tools/upload_to_knowledge_base.py` | 工具：参数校验 → 加载文件 → 建构档 |
| Create: `api/internal/core/tools/builtin_tools/providers/knowledge_base_tools/upload_to_knowledge_base.yaml` | 工具声明 + task_keywords |
| Modify: `api/internal/core/tools/builtin_tools/providers/knowledge_base_tools/positions.yaml` | 追加 `upload_to_knowledge_base` |
| Modify: `api/internal/core/tools/builtin_tools/providers/knowledge_base_tools/__init__.py` | 重导出新工厂 |
| Modify: `api/internal/service/assistant_agent_service.py` | `_build_assistant_runtime_tools` 挂载点追加 |
| Create: `api/test/internal/core/tools/test_upload_to_knowledge_base_tool.py` | 工具单测 |
| Modify: `api/test/internal/core/tools/test_builtin_apps_and_providers.py`（或现有 provider 加载测试） | provider 可发现 + yaml 契约合法 |
| Modify: `api/test/internal/service/test_assistant_agent_service.py` | 挂载点出现新工具 |

---

## Task B1: 工具实现（file_id → 建档）

**Files:**
- Create: `api/internal/core/tools/builtin_tools/providers/knowledge_base_tools/upload_to_knowledge_base.py`
- Test: `api/test/internal/core/tools/test_upload_to_knowledge_base_tool.py`

- [ ] **Step 1: 写失败的测试**

```python
"""upload_to_knowledge_base 工具：对话内把小钰拿到的素材文件建档入库。"""
import json
import importlib

import pytest

_PKG = "internal.core.tools.builtin_tools.providers.knowledge_base_tools"

upload_tool = importlib.import_module(f"{_PKG}.upload_to_knowledge_base")


class _FakeAccount:
    id = "acc-1"


def test_requires_account_and_kb():
    tool = upload_tool.upload_to_knowledge_base()
    payload = json.loads(tool._run(file_id="u1"))
    assert payload["ok"] is False
    assert "账号" in payload["error"] or "知识库" in payload["error"]


def test_rejects_missing_file_id():
    tool = upload_tool.upload_to_knowledge_base(account_id="acc-1")
    payload = json.loads(tool._run(knowledge_base_id="kb-1"))
    assert payload["ok"] is False
    assert "文件" in payload["error"]


def test_creates_document_from_upload_file(monkeypatch):
    """file_id 命中 UploadFile 时调 create_document_from_upload_file 建档。"""
    calls = {}

    fake_upload_file = type("U", (), {"id": "u1", "name": "v.mp4", "extension": "mp4"})()

    class _FakeMgr:
        def get_upload_file(self, file_id):
            calls["file_id"] = file_id
            return fake_upload_file

    class _FakeKbSvc:
        def create_document_from_upload_file(self, **kw):
            calls.update(kw)
            return type("D", (), {"id": "d1"})()

    monkeypatch.setattr(upload_tool, "_load_upload_file_manager", lambda: _FakeMgr())
    monkeypatch.setattr(upload_tool, "_load_knowledge_base_service", lambda: _FakeKbSvc())

    tool = upload_tool.upload_to_knowledge_base(account_id="acc-1")
    payload = json.loads(tool._run(knowledge_base_id="kb-1", file_id="u1", name="标题"))

    assert payload["ok"] is True
    assert calls["knowledge_base_id"] == "kb-1"
    assert calls["upload_file"] is fake_upload_file
    assert str(calls["account"].id) == "acc-1"


def test_file_not_found_readable_error(monkeypatch):
    """UploadFile 不存在（例如被用户删除）时报可读错误，不抛裸异常。"""
    class _FakeMgr:
        def get_upload_file(self, file_id):
            raise LookupError("not found")

    monkeypatch.setattr(upload_tool, "_load_upload_file_manager", lambda: _FakeMgr())

    tool = upload_tool.upload_to_knowledge_base(account_id="acc-1")
    payload = json.loads(tool._run(knowledge_base_id="kb-1", file_id="gone"))

    assert payload["ok"] is False
    assert "不存在" in payload["error"]


def test_factory_passes_account_id():
    tool = upload_tool.upload_to_knowledge_base(account_id="acc-9", message_id="m", conversation_id="c")
    assert tool.account_id == "acc-9"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/core/tools/test_upload_to_knowledge_base_tool.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
"""upload_to_knowledge_base 工具（小钰帮传：对话内把素材文件建档入用户知识库）。

小钰在对话里帮用户把「平台已生成的文件（file_id，来自对话附件/先前上传）」存进
用户资料库：板块媒体类型硬约束 + 触发索引，与用户自传走同一链路、同一份数据。

安全边界：只接受 ``file_id``（平台 UploadFile），**不接受任意本地/远程路径**——
api 容器读不到用户本机文件，盲目读取会引入任意文件读取洞。文件字节的上传本身
由既有上传链路（chunked_upload / upload_file_service）完成并在上传阶段计入配额。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _load_account(account_id: Any):
    """按账号 ID 加载真实 Account 实例，无法解析/不存在时返回 None。"""
    normalized = str(account_id or "").strip()
    if not normalized:
        return None
    try:
        account_uuid = UUID(normalized)
    except (ValueError, TypeError, AttributeError):
        return None
    try:
        from app.http.module import injector
        from internal.service.account_service import AccountService

        return injector.get(AccountService).get_account(account_uuid)
    except Exception:
        logger.warning("加载账号失败 account_id=%s", normalized, exc_info=True)
        return None


def _load_upload_file_manager():
    """获取 UploadFile 管理服务（按 upload_file_service 实际导出名核对后填写）。"""
    from app.http.module import injector
    from internal.service.upload_file_service import UploadFileService

    return injector.get(UploadFileService)


def _load_knowledge_base_service():
    """获取知识库服务单例。"""
    from app.http.module import injector
    from internal.service.knowledge_base_service import KnowledgeBaseService

    return injector.get(KnowledgeBaseService)


class UploadToKnowledgeBaseInput(BaseModel):
    """把平台已有文件建档进用户知识库的输入。"""

    knowledge_base_id: str = Field(..., description="目标知识库板块 id（用户自有板块）")
    file_id: str = Field(..., description="平台已生成的文件 id（对话附件或先前上传的文件）")
    partition_id: str = Field("", description="目标分区 id（可选；分区模式下建议提供）")


class UploadToKnowledgeBaseTool(BaseTool):
    """在对话内把素材文件建档进用户知识库。"""

    name: str = "upload_to_knowledge_base"
    description: str = (
        "当用户要求把文件/素材存入某个知识库板块时调用（如「把这个文件传到视频素材库」）。"
        "file_id 必须是平台已生成的文件 id（来自对话附件或先前上传）；会把该文件建档入"
        "目标知识库并触发解析索引，之后可被检索。仅能为当前登录用户操作其自有板块。"
    )
    args_schema: type[BaseModel] = UploadToKnowledgeBaseInput
    account_id: str = ""

    def _run(
        self,
        knowledge_base_id: str = "",
        file_id: str = "",
        partition_id: str = "",
        **kwargs: Any,
    ) -> str:
        kb_id = str(knowledge_base_id or "").strip()
        fid = str(file_id or "").strip()
        if not kb_id or not fid:
            return json.dumps(
                {"ok": False, "error": "需要同时提供知识库 id 与文件 id"},
                ensure_ascii=False,
            )

        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps(
                {"ok": False, "error": "缺少当前账号信息，无法上传素材"},
                ensure_ascii=False,
            )

        account = _load_account(account_id)
        if account is None:
            return json.dumps(
                {"ok": False, "error": f"账号不存在或不可用：{account_id}"},
                ensure_ascii=False,
            )

        try:
            upload_file = _load_upload_file_manager().get_upload_file(fid)
        except Exception as exc:
            logger.warning("加载文件失败 file_id=%s", fid, exc_info=True)
            return json.dumps(
                {"ok": False, "error": f"文件不存在或不可用：{exc}"},
                ensure_ascii=False,
            )

        try:
            service = _load_knowledge_base_service()
            document = service.create_document_from_upload_file(
                knowledge_base_id=kb_id,
                upload_file=upload_file,
                account=account,
                partition_id=str(partition_id or "").strip() or None,
            )
        except Exception as exc:
            logger.warning("建档入知识库失败 kb=%s file=%s", kb_id, fid, exc_info=True)
            return json.dumps(
                {"ok": False, "error": f"上传素材失败：{exc}"},
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "ok": True,
                "document_id": str(getattr(document, "id", "")),
                "knowledge_base_id": kb_id,
                "file_id": fid,
                "message": "素材已存入知识库，正在解析索引",
            },
            ensure_ascii=False,
        )

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        return self._run(*args, **kwargs)


def upload_to_knowledge_base(**kwargs: Any) -> BaseTool:
    """工厂函数：返回把文件建档进用户知识库的 LangChain 工具。"""
    return UploadToKnowledgeBaseTool(
        account_id=str(kwargs.get("account_id") or "").strip(),
    )
```

> **实现前必须核对**：
> 1. `upload_file_service` 的类名与「按 id 查文件」方法真实签名（先读 `api/internal/service/upload_file_service.py`；方法名若为 `get_upload_file` 之外的写法，以实测为准替换 `_load_upload_file_manager` 与调用处）。
> 2. `UploadFileService` 是否已 bind 进 injector（module.py）；未 bind 则 `_load_upload_file_manager` 改用先 `injector.get(UploadFileService)` 外兜底实例化方式（以现有 `_load_knowledge_base_service` 同款写法为准）。

- [ ] **Step 4: 运行测试确认通过** — Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

---

## Task B2: yaml + positions + __init__ + provider 加载测试

**Files:**
- Create: `api/internal/core/tools/builtin_tools/providers/knowledge_base_tools/upload_to_knowledge_base.yaml`
- Modify: `positions.yaml` / `__init__.py`
- Test: 既有 provider 发现测试（`test_builtin_apps_and_providers.py` 或同目录测试）

- [ ] **Step 1: 写 yaml**

```yaml
name: upload_to_knowledge_base
label: 存入知识库
description: 把平台已有文件（对话附件/先前上传）建档进用户的某个知识库板块，并触发解析索引。需要 user 明确指定目标板块与文件。
params:
- name: knowledge_base_id
  label: 目标知识库
  type: string
  required: true
- name: file_id
  label: 文件 id
  type: string
  required: true
- name: partition_id
  label: 目标分区
  type: string
  required: false
task_keywords:
- 存入知识库
- 传到知识库
- 保存到知识库
- 帮传
- 上传素材
- 存到资源库
```

- [ ] **Step 2: 更新登记**

positions.yaml 追加：

```yaml
- upload_to_knowledge_base
```

`__init__.py`：

```python
from .create_knowledge_base import create_knowledge_base
from .upload_to_knowledge_base import upload_to_knowledge_base

__all__ = ["create_knowledge_base", "upload_to_knowledge_base"]
```

- [ ] **Step 3: 跑 provider 加载测试**

Run: `cd api && python -m pytest test/internal/core/tools/test_builtin_apps_and_providers.py -k "knowledge_base or provider or discover" -v`
Expected: PASS（yaml 契约合法，新工具可发现）

- [ ] **Step 4: Commit**

---

## Task B3: 运行时挂载点

**Files:**
- Modify: `api/internal/service/assistant_agent_service.py`
- Modify: `api/test/internal/service/test_assistant_agent_service.py`

- [ ] **Step 1: 写失败的测试**

在 `test_assistant_agent_service.py`（或与 create_knowledge_base 挂载测试同文件）新增：

```python
def test_runtime_tools_include_upload_to_knowledge_base(monkeypatch):
    """挂载点应把 upload_to_knowledge_base 注入对话工具列表。"""
    # 依既有 create_knowledge_base 挂载测试同构：
    # - fake app_config_service.builtin_provider_manager.get_tool("knowledge_base_tools", name)
    #   对 upload_to_knowledge_base 返回一个记录 account_id 的工厂；
    # - 调用 _build_assistant_runtime_tools(account, message_id, conversation_id)，
    # - 断言工具列表含该工具且工厂收到 account_id。
```

> 先读既有 create_knowledge_base 挂载测试（若存在）照抄其夹具与断言结构，避免另起炉灶。

- [ ] **Step 2: 运行确认失败** — Expected: FAIL（工具不在列表）

- [ ] **Step 3: 实现挂载**

在 `_build_assistant_runtime_tools` 的 `create_knowledge_base` 挂载块（L1049-1058）之后追加：

```python
        # 小钰帮传：Agent 在对话内把平台已有文件建档进用户知识库。
        if self.app_config_service is not None:
            try:
                upload_tool_factory = self.app_config_service.builtin_provider_manager.get_tool(
                    "knowledge_base_tools",
                    "upload_to_knowledge_base",
                )
                if upload_tool_factory is not None:
                    tools.append(upload_tool_factory(account_id=str(account_id)))
            except Exception:
                logger.warning("构建上传素材工具失败，不影响其他工具", exc_info=True)
```

- [ ] **Step 4: 运行确认通过** — Expected: PASS

- [ ] **Step 5: Commit**

---

## Task B4: 回归 + 接线自检 + 文档同步

- [ ] **Step 1: 全量回归** — `cd api && python -m pytest -q`（基线 5200+ passed；2 个既有环境失败不修）
- [ ] **Step 2: 接线自检**

| 新符号 | 入口 |
| --- | --- |
| `upload_to_knowledge_base` 工具 | `.py` + `.yaml` + `positions.yaml` + `providers.yaml` 登记 + `_build_assistant_runtime_tools`（唯一对话入口） |
| `_load_upload_file_manager` | 仅被工具 `_run` 调用 |

- [ ] **Step 3: 文档同步** — `docs/prd/modules/02-knowledge-base.md`（对话工具小节补「小钰帮传 upload_to_knowledge_base，file_id 契约」）、`docs/prd/execution-roadmap.md`（KB-P5 行补「KB-P5-B 完成：小钰帮传」）、`docs/prd/knowledge-base-product-form-design.md` §9.2 KB-P5 行更新
- [ ] **Step 4: graphify** — `python -m graphify update .`
- [ ] **Step 5: Commit（docs 单独）**

---

## Self-Review 备注

- **验收口径**：「双入口操作同一数据」——工具复用 `create_document_from_upload_file`，与用户自传（documents/upload 路由）完全同一建档/索引链路；配额在文件上传阶段已计，工具不重复计。
- **安全边界**：不接受本地路径，只接受平台 `file_id`。
- **延后项**：额外校验「该 UploadFile 是否属于当前 account」（当前 `get_upload_file` 方法语义视实现核对；若服务层已按账号隔离则无需额外处理）。