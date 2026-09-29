# 用户文件中心（Plan 3 · Agent 工具）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Agent 通过 builtin 工具在**与用户同一个文件中心命名空间**上操作（list / mkdir / move / rename / delete / read / save_artifact）。

**Architecture:** 新增 builtin provider `file_center`，采用仓库既有范式：pydantic `Input` + `BaseTool` 子类 + 同名模块级工厂函数 + `.yaml` 元数据 + `positions.yaml` + `providers.yaml` 登记；运行时在 `assistant_agent_service._build_assistant_runtime_tools` **显式挂载并注入 `requester=account_id`**（`_load_non_mcp_tool` 的空参路径拿不到账号，故必须显式挂载）。同时给 `FileCenterService` 补 `read_file` / `save_artifact`。

**Tech Stack:** Python / langchain_core `BaseTool` / pydantic / injector / pytest。

**依赖与衔接**
- **前置**：Plan 1（后端核心，提供 `FileCenterEntry`/`FileCenterService`）；Plan 2（回收站原目录恢复，删除/恢复语义）。
- **后续**：Plan 4（产物收编，`save_artifact` 的写入点收编）、Plan 5（前端）。
- **规格**：`.../specs/2026-09-30-user-file-center-design.md` §4.5、§9（`save_artifact` 默认落点 `产物/`）。

**前置条件：** 只 `git add` 本任务列举的文件；测试在 `api/` 下运行。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `api/internal/service/file_center_service.py` | 修改：补 `read_file` / `save_artifact` |
| `api/internal/core/tools/builtin_tools/providers/file_center/file_center.py` | 新建：工具实现 |
| `api/internal/core/tools/builtin_tools/providers/file_center/file_center.yaml` | 新建：工具元数据 |
| `api/internal/core/tools/builtin_tools/providers/file_center/positions.yaml` | 新建：工具清单 |
| `api/internal/core/tools/builtin_tools/providers/file_center/__init__.py` | 新建：导出工厂 |
| `api/internal/core/tools/builtin_tools/providers/providers.yaml` | 修改：登记 provider |
| `api/internal/service/assistant_agent_service.py` | 修改：运行时挂载 |
| `api/test/internal/service/test_file_center_readsave.py` | 新建：service 单测 |
| `api/test/internal/core/tools/test_file_center_tool.py` | 新建：工具测试 |

---

## Task 1: `FileCenterService` 补 `read_file` / `save_artifact`

**Files:**
- Modify: `api/internal/service/file_center_service.py`
- Create: `api/test/internal/service/test_file_center_readsave.py`

- [ ] **Step 1: 先核对存储端口签名（侦察步）**

读 `api/internal/core/ports/storage_port.py` 与 `api/internal/service/storage/runtime_storage_service.py`，确认：
- 读取字节的可用方法（`download_file(key, target_file_path)` 或等价）；
- 写入字节的方法签名（`upload_bytes(*, filename, content, account_id, mime_type=None, folder="artifacts") -> UploadFile`）。
**按实际签名实现下一步**（若签名与下述代码不同，以真实签名为准并调整）。

- [ ] **Step 2: 写失败测试**

创建 `api/test/internal/service/test_file_center_readsave.py`：

```python
"""FileCenterService read_file / save_artifact 单测。"""
import uuid

from internal.service.file_center_service import FileCenterService


def test_save_artifact_creates_node_and_upload_file():
    svc = FileCenterService()
    acc = uuid.uuid4()
    res = svc.save_artifact(acc, name="note.txt", content="hello", parent_id=None)
    assert res["name"] == "note.txt"
    roots = svc.list_children(acc, parent_id=None)
    assert any(c.name == "note.txt" and not c.is_folder for c in roots)
```

- [ ] **Step 3: 运行确认失败**

Run: `python -m pytest test/internal/service/test_file_center_readsave.py -q`
Expected: FAIL（无 `save_artifact`）

- [ ] **Step 4: 实现 `read_file` / `save_artifact`**

在 `FileCenterService` 中，把 `@inject @dataclass` 字段区补上存储端口注入：

```python
    storage: ObjectStoragePort = field(default=None)
```

顶部 import 增加：

```python
from internal.core.ports.storage_port import ObjectStoragePort
from internal.model import UploadFile
```

追加方法：

```python
    def read_file(self, account_id, entry_id, *, limit: int = 0) -> dict:
        """读取文件节点对应的文本内容（UTF-8 尽力解码；超长按 limit 截断行数）。"""
        import os
        import tempfile

        entry = self._get_owned_entry(account_id, entry_id)
        if entry.is_folder or not entry.upload_file_id:
            raise ValidateErrorException("不是可读取的文件")
        upload_file = (
            db.session.query(UploadFile)
            .filter(UploadFile.id == entry.upload_file_id)
            .one_or_none()
        )
        if upload_file is None:
            raise NotFoundException("文件不存在")
        fd, tmp_path = tempfile.mkstemp()
        os.close(fd)
        try:
            self.storage.download_file(upload_file.key, tmp_path)
            with open(tmp_path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        if limit and limit > 0:
            text = "\n".join(text.splitlines()[:limit])
        return {"ok": True, "name": upload_file.name, "content": text}

    def save_artifact(
        self,
        account_id,
        *,
        name: str,
        content: str,
        parent_id=None,
        folder: str = "产物",
    ) -> dict:
        """把一段文本保存为文件中心的产物（默认落 `产物/` 目录，不存在则创建）。"""
        if parent_id is None:
            parent_id = ensure_path(account_id, [folder])
        upload_file = self.storage.upload_bytes(
            filename=self._validate_name(name),
            content=str(content).encode("utf-8"),
            account_id=account_id,
            folder="artifacts",
        )
        entry = self.import_upload_file(
            account_id,
            upload_file_id=upload_file.id,
            parent_id=parent_id,
            name=upload_file.name,
            source="artifact",
        )
        return {"ok": True, "entry_id": str(entry.id), "upload_file_id": str(upload_file.id), "name": entry.name}
```

顶部 import 增加 `from internal.service.file_center_paths import ensure_path`。

> 若 `upload_bytes` 的形参名/返回类型与实现不符，以 Step 1 核对的真实签名为准调整。

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest test/internal/service/test_file_center_readsave.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/file_center_service.py api/test/internal/service/test_file_center_readsave.py
git commit -m "feat(file-center): service read_file/save_artifact"
```

---

## Task 2: 工具文件 `file_center`

**Files:**
- Create: `api/internal/core/tools/builtin_tools/providers/file_center/file_center.py`
- Create: `.../file_center.yaml`
- Create: `.../positions.yaml`
- Create: `.../__init__.py`

- [ ] **Step 1: 写工具实现**

创建 `.../providers/file_center/file_center.py`：

```python
"""文件中心工具：让 Agent 在用户文件中心（虚拟目录树）上操作。"""
import json
from typing import Any, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


class FileCenterInput(BaseModel):
    """文件中心操作输入。"""

    op: Literal["list", "mkdir", "move", "rename", "delete", "read", "save_artifact"] = Field(
        ...,
        description=(
            "list=列目录；mkdir=建目录；move=移动；rename=重命名；"
            "delete=删除（进入回收站，可恢复）；read=读取文本文件；save_artifact=保存文本产物"
        ),
    )
    parent_id: str = Field("", description="目标目录节点 id；空表示账号根（list/mkdir/move/save_artifact）")
    entry_id: str = Field("", description="目标节点 id（rename/move/delete/read）")
    name: str = Field("", description="名称（mkdir/rename/save_artifact）")
    content: str = Field("", description="文本内容（save_artifact）")
    limit: int = Field(0, ge=0, description="read 时读取的最大行数；0 表示默认")
    requester: str = Field("", description="调用方账号 ID，由平台注入")


class FileCenterTool(BaseTool):
    """在用户文件中心上操作（与用户同一命名空间）。"""

    name: str = "file_center"
    description: str = (
        "在用户的文件中心（虚拟目录树）上操作：列目录 / 建目录 / 移动 / 重命名 / "
        "删除 / 读取 / 保存文本产物。删除会进入用户回收站可恢复。"
        "所有操作只作用于当前账号自己的文件中心。"
    )
    args_schema: type[BaseModel] = FileCenterInput
    requester: str = ""

    def _run(self, **kwargs: Any) -> str:
        from app.http.module import injector
        from internal.service.file_center_service import FileCenterService

        op = str(kwargs.get("op") or "list").strip().lower()
        account_id = str(kwargs.get("requester") or self.requester or "").strip()
        if not account_id:
            return json.dumps({"ok": False, "error": "缺少调用方账号"}, ensure_ascii=False)
        service = injector.get(FileCenterService)
        try:
            if op == "list":
                items = service.list_children(account_id, parent_id=kwargs.get("parent_id") or None)
                return json.dumps(
                    {"ok": True, "items": [
                        {
                            "id": str(e.id),
                            "name": e.name,
                            "is_folder": bool(e.is_folder),
                            "upload_file_id": str(e.upload_file_id) if e.upload_file_id else None,
                        }
                        for e in items
                    ]},
                    ensure_ascii=False,
                )
            if op == "mkdir":
                e = service.mkdir(
                    account_id,
                    parent_id=kwargs.get("parent_id") or None,
                    name=str(kwargs.get("name") or ""),
                )
                return json.dumps({"ok": True, "id": str(e.id), "name": e.name}, ensure_ascii=False)
            if op == "move":
                e = service.move(account_id, kwargs.get("entry_id"), kwargs.get("parent_id") or None)
                return json.dumps({"ok": True, "id": str(e.id)}, ensure_ascii=False)
            if op == "rename":
                e = service.rename(account_id, kwargs.get("entry_id"), str(kwargs.get("name") or ""))
                return json.dumps({"ok": True, "id": str(e.id), "name": e.name}, ensure_ascii=False)
            if op == "delete":
                service.delete_node(account_id, kwargs.get("entry_id"))
                return json.dumps({"ok": True, "message": "已移入回收站"}, ensure_ascii=False)
            if op == "read":
                result = service.read_file(
                    account_id, kwargs.get("entry_id"), limit=int(kwargs.get("limit") or 0)
                )
                return json.dumps(result, ensure_ascii=False, default=str)
            if op == "save_artifact":
                result = service.save_artifact(
                    account_id,
                    name=str(kwargs.get("name") or ""),
                    content=str(kwargs.get("content") or ""),
                    parent_id=kwargs.get("parent_id") or None,
                )
                return json.dumps(result, ensure_ascii=False, default=str)
            return json.dumps({"ok": False, "error": f"未知操作: {op}"}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 - 工具层统一转结构化错误
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)


def file_center(**kwargs: Any) -> BaseTool:
    """工厂函数：返回文件中心工具实例（注入 requester=账号 ID）。"""
    return FileCenterTool(requester=str(kwargs.get("requester") or ""))
```

- [ ] **Step 2: 写 yaml / positions / __init__**

`.../file_center.yaml`：

```yaml
name: file_center
label: 文件中心
description: 在用户文件中心（虚拟目录树）上列目录/建目录/移动/重命名/删除/读取/保存文本产物，删除进回收站可恢复。
params:
  - name: requester
    type: string
    label: 调用方账号ID
    description: 由平台注入，无需手动填写
task_keywords:
  - 文件中心
  - 我的文件
  - 新建文件夹
  - 保存文件
  - 移动文件
  - 重命名文件
  - 删除文件
```

`.../positions.yaml`：

```yaml
- file_center
```

`.../__init__.py`：

```python
from .file_center import file_center

__all__ = ["file_center"]
```

- [ ] **Step 3: 验证可加载**

Run: `python -c "from internal.core.tools.builtin_tools.providers.file_center import file_center; t=file_center(requester='x'); print(t.name)"`
Expected: `file_center`

- [ ] **Step 4: Commit**

```bash
git add api/internal/core/tools/builtin_tools/providers/file_center/
git commit -m "feat(file-center): builtin tool provider 'file_center'"
```

---

## Task 3: `providers.yaml` 登记 + 运行时挂载

**Files:**
- Modify: `api/internal/core/tools/builtin_tools/providers/providers.yaml`
- Modify: `api/internal/service/assistant_agent_service.py`

- [ ] **Step 1: 登记 provider**

在 `providers.yaml` 末尾（与既有 `- name: host_os` 记录同级）追加：

```yaml
- name: file_center
  label: 文件中心
  description: 用户文件中心（虚拟目录树）的文件管理能力，与用户侧同一命名空间。
  icon: ""
  background: "#F3EEFF"
  category: productivity
  created_at: 1790700000
```

- [ ] **Step 2: 运行时挂载**

在 `assistant_agent_service.py` 的 `_build_assistant_runtime_tools` 中，紧邻 host_os 挂载块（`for tool_name in ("os_file_task", "os_recycle_bin", "os_snapshot"):`）之后插入：

```python
        # 文件中心工具：与用户同一命名空间，注入当前账号
        if self.app_config_service is not None:
            try:
                fc_tool_factory = (
                    self.app_config_service.builtin_provider_manager.get_tool(
                        "file_center", "file_center"
                    )
                )
                if fc_tool_factory is not None:
                    tools.append(fc_tool_factory(requester=str(account_id)))
            except Exception:
                logger.warning("构建文件中心工具失败，不影响其他工具", exc_info=True)
```

- [ ] **Step 3: 写工具测试（注入替身服务）**

创建 `api/test/internal/core/tools/test_file_center_tool.py`：

```python
"""file_center 工具测试。"""
import json
import uuid

import pytest

from internal.core.tools.builtin_tools.providers.file_center import file_center


class _FakeEntry:
    def __init__(self, name="A", is_folder=True):
        self.id = uuid.uuid4()
        self.name = name
        self.is_folder = is_folder
        self.upload_file_id = None


class _FakeService:
    def list_children(self, account_id, parent_id=None):
        return [_FakeEntry("Docs")]


def test_list_returns_items(monkeypatch):
    import app.http.module as module

    monkeypatch.setattr(module.injector, "get", lambda cls: _FakeService())
    tool = file_center(requester=str(uuid.uuid4()))
    out = json.loads(tool._run(op="list"))
    assert out["ok"] is True
    assert out["items"][0]["name"] == "Docs"


def test_missing_requester_returns_error():
    tool = file_center()
    out = json.loads(tool._run(op="list"))
    assert out["ok"] is False
```

- [ ] **Step 4: 运行测试**

Run: `python -m pytest test/internal/core/tools/test_file_center_tool.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/internal/core/tools/builtin_tools/providers/providers.yaml api/internal/service/assistant_agent_service.py api/test/internal/core/tools/test_file_center_tool.py
git commit -m "feat(file-center): register provider + mount file_center tool with requester"
```

---

## 接线自检（写进回复）
- 工具唯一入口：`file_center`（provider `file_center`），挂载点 `assistant_agent_service._build_assistant_runtime_tools`，注入 `requester=account_id`。
- 工具 → 服务 → 存储/回收站，均复用既有链路，无平行机制。

## 下一份计划
- Plan 4 `2026-09-30-user-file-center-artifact-collection.md`
- Plan 5 `2026-09-30-user-file-center-frontend.md`
