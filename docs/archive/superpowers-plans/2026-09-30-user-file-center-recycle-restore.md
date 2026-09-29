# 用户文件中心（Plan 2 · 回收站原目录恢复）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 文件中心删除的文件在回收站**恢复后回到原目录**（而非落到账号根）。

**Architecture:** 不改回收站机制本身，只扩展 `upload_file` 的三个处理器——`snapshot_upload_file` 快照时附带文件中心路径、`restore_upload_file` 恢复时逐级重建目录并挂回节点、`purge_upload_file` 物理销毁时清理残留节点。路径工具抽到独立模块 `file_center_paths.py`，避免 `handlers → service → handlers` 循环导入。

**Tech Stack:** Python / SQLAlchemy 2.0 / injector / pytest。

**依赖与衔接**
- **前置**：`docs/superpowers/plans/2026-09-30-user-file-center-backend.md`（Plan 1，提供 `FileCenterEntry` 与 `FileCenterService`）。
- **后续**：Plan 3（Agent 工具）、Plan 4（产物收编）、Plan 5（前端）。
- **规格**：`docs/superpowers/specs/2026-09-30-user-file-center-design.md` §4.3、§9。

**前置条件：** 工作区有并行未提交改动，**每个 `git add` 只加本任务列举的文件**；测试在 `api/` 下运行 `python -m pytest <path> -q`。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `api/internal/service/file_center_paths.py` | 新建：路径工具（供 service 与回收站处理器共用，规避循环导入） |
| `api/internal/service/recycle_bin_handlers.py` | 修改：`snapshot_upload_file` / `restore_upload_file` / `purge_upload_file` |
| `api/test/internal/service/test_file_center_recycle.py` | 新建：路径工具与三处理器单测 |

---

## Task 1: 路径工具模块 `file_center_paths.py`

**Files:**
- Create: `api/internal/service/file_center_paths.py`
- Create: `api/test/internal/service/test_file_center_recycle.py`

- [ ] **Step 1: 写失败测试**

创建 `api/test/internal/service/test_file_center_recycle.py`：

```python
"""文件中心 × 回收站：路径工具与处理器单测。"""
import uuid

from internal.model import FileCenterEntry
from internal.service.file_center_paths import (
    build_parent_path_names,
    delete_entries_by_upload_file,
    ensure_path,
)
from internal.service.file_center_service import FileCenterService


def test_build_parent_path_names_root_first():
    svc = FileCenterService()
    acc = uuid.uuid4()
    a = svc.mkdir(acc, parent_id=None, name="A")
    b = svc.mkdir(acc, parent_id=a.id, name="B")
    entry = svc.import_upload_file(acc, upload_file_id=uuid.uuid4(), parent_id=b.id, name="f.txt")
    assert build_parent_path_names(entry) == ["A", "B"]


def test_ensure_path_creates_and_reuses():
    acc = uuid.uuid4()
    pid = ensure_path(acc, ["A", "B"])
    assert pid is not None
    pid2 = ensure_path(acc, ["A", "B"])
    assert pid2 == pid
    assert build_parent_path_names(
        type("E", (), {"parent_id": pid})()
    ) == ["A", "B"]


def test_delete_entries_by_upload_file_removes_node():
    svc = FileCenterService()
    acc = uuid.uuid4()
    fid = uuid.uuid4()
    svc.import_upload_file(acc, upload_file_id=fid, parent_id=None, name="x.txt")
    delete_entries_by_upload_file(fid)
    assert svc.list_children(acc, parent_id=None) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_file_center_recycle.py -q`
Expected: FAIL（`ModuleNotFoundError: internal.service.file_center_paths`）

- [ ] **Step 3: 写实现**

创建 `api/internal/service/file_center_paths.py`：

```python
"""文件中心路径工具。

抽出为独立模块：回收站处理器（recycle_bin_handlers）与 FileCenterService 都要用它，
若放在 FileCenterService 内会造成 handlers → service → handlers 的循环导入。
"""
from internal.extension.database_extension import db
from internal.model import FileCenterEntry


def build_parent_path_names(entry) -> list[str]:
    """返回 entry 所在目录的路径名数组（root 在前，不含 entry 自身）。"""
    names: list[str] = []
    cursor = getattr(entry, "parent_id", None)
    while cursor is not None:
        parent = (
            db.session.query(FileCenterEntry)
            .filter(FileCenterEntry.id == cursor)
            .one_or_none()
        )
        if parent is None:
            break
        names.append(parent.name)
        cursor = parent.parent_id
    return list(reversed(names))


def ensure_path(account_id, path_names: list[str]):
    """逐级确保目录存在（存在则复用），返回最深目录 id；path_names 为空返回 None。"""
    parent_id = None
    for name in path_names:
        query = db.session.query(FileCenterEntry).filter(
            FileCenterEntry.account_id == account_id,
            FileCenterEntry.name == name,
            FileCenterEntry.is_folder.is_(True),
        )
        if parent_id is None:
            query = query.filter(FileCenterEntry.parent_id.is_(None))
        else:
            query = query.filter(FileCenterEntry.parent_id == parent_id)
        folder = query.one_or_none()
        if folder is None:
            folder = FileCenterEntry(
                account_id=account_id,
                parent_id=parent_id,
                name=name,
                is_folder=True,
                source="upload",
            )
            db.session.add(folder)
            db.session.flush()
        parent_id = folder.id
    return parent_id


def delete_entries_by_upload_file(upload_file_id) -> int:
    """删除所有指向该 upload_file 的节点（物理销毁时的残留清理）。"""
    return (
        db.session.query(FileCenterEntry)
        .filter(FileCenterEntry.upload_file_id == upload_file_id)
        .delete(synchronize_session=False)
    )
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/service/test_file_center_recycle.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/file_center_paths.py api/test/internal/service/test_file_center_recycle.py
git commit -m "feat(file-center): path helpers for recycle restore (build/ensure/cleanup)"
```

---

## Task 2: `snapshot_upload_file` 记录文件中心路径

**Files:**
- Modify: `api/internal/service/recycle_bin_handlers.py`（`snapshot_upload_file`，约 L620-629）

- [ ] **Step 1: 写失败测试**

在 `test_file_center_recycle.py` 追加：

```python
def test_snapshot_upload_file_captures_file_center_path():
    from internal.model import UploadFile
    from internal.service.recycle_bin_handlers import snapshot_upload_file
    from internal.extension.database_extension import db

    svc = FileCenterService()
    acc = uuid.uuid4()
    folder = svc.mkdir(acc, parent_id=None, name="Docs")
    uf = UploadFile(id=uuid.uuid4(), account_id=acc, name="a.txt", key="k", size=1,
                    extension="txt", mime_type="text/plain", hash="h", storage_backend="local")
    db.session.add(uf)
    db.session.flush()
    svc.import_upload_file(acc, upload_file_id=uf.id, parent_id=folder.id, name="a.txt")
    snap = snapshot_upload_file(uf.id)
    assert snap["file_center"]["parent_path"] == ["Docs"]
    assert snap["file_center"]["name"] == "a.txt"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_file_center_recycle.py::test_snapshot_upload_file_captures_file_center_path -q`
Expected: FAIL（`KeyError: 'file_center'`）

- [ ] **Step 3: 实现**

把 `recycle_bin_handlers.py` 的 `snapshot_upload_file` 替换为：

```python
def snapshot_upload_file(resource_id) -> dict[str, Any] | None:
    """快照单个上传文件记录（底层对象在留存期内保留），并记录文件中心路径。"""
    upload_file = (
        db.session.query(UploadFile)
        .filter(UploadFile.id == resource_id)
        .one_or_none()
    )
    if upload_file is None:
        return None
    snapshot: dict[str, Any] = {"main": _row_to_dict(upload_file)}
    entry = (
        db.session.query(FileCenterEntry)
        .filter(FileCenterEntry.upload_file_id == resource_id)
        .one_or_none()
    )
    if entry is not None:
        snapshot["file_center"] = {
            "account_id": str(entry.account_id),
            "parent_path": _build_parent_path_names(entry),
            "name": entry.name,
            "source": entry.source,
            "origin": entry.origin,
        }
    return snapshot
```

在该文件顶部 import 区加入：

```python
from internal.model import FileCenterEntry
from internal.service.file_center_paths import build_parent_path_names as _build_parent_path_names
```

> 说明：`snapshot_upload_file` 在 `delete_resource` 内**早于** `physical_delete_resource` 调用，此刻节点仍存在，故能取到路径。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/service/test_file_center_recycle.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/recycle_bin_handlers.py api/test/internal/service/test_file_center_recycle.py
git commit -m "feat(file-center): capture file_center path in upload_file recycle snapshot"
```

---

## Task 3: `restore_upload_file` 恢复回原目录

**Files:**
- Modify: `api/internal/service/recycle_bin_handlers.py`（`restore_upload_file`，约 L639-652）

- [ ] **Step 1: 写失败测试**

```python
def test_restore_upload_file_recreates_node_at_path():
    from internal.service.recycle_bin_handlers import restore_upload_file
    svc = FileCenterService()
    acc = uuid.uuid4()
    snap = {
        "main": {
            "id": uuid.uuid4(), "account_id": acc, "name": "a.txt", "key": "k",
            "size": 1, "extension": "txt", "mime_type": "text/plain",
            "hash": "h", "storage_backend": "local",
        },
        "file_center": {"account_id": str(acc), "parent_path": ["Docs"], "name": "a.txt",
                        "source": "upload", "origin": None},
    }
    assert restore_upload_file(snap) is True
    roots = svc.list_children(acc, parent_id=None)
    docs = [e for e in roots if e.is_folder and e.name == "Docs"]
    assert len(docs) == 1
    children = svc.list_children(acc, parent_id=docs[0].id)
    assert [c.name for c in children] == ["a.txt"]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_file_center_recycle.py::test_restore_upload_file_recreates_node_at_path -q`
Expected: FAIL（节点未重建）

- [ ] **Step 3: 实现**

把 `restore_upload_file` 替换为：

```python
def restore_upload_file(snapshot: dict[str, Any]) -> bool:
    """按快照重建上传文件记录，并按记录的文件中心路径重建节点。"""
    main_data = snapshot.get("main") or {}
    if not main_data.get("id"):
        return False
    if db.session.query(UploadFile).filter(
        UploadFile.id == main_data["id"],
    ).one_or_none() is not None:
        return False
    upload_file = UploadFile()
    for col_name, value in main_data.items():
        _apply_column_value(UploadFile, upload_file, col_name, value)
    db.session.add(upload_file)
    db.session.flush()

    fc = snapshot.get("file_center")
    if isinstance(fc, dict) and fc.get("account_id"):
        parent_id = ensure_path(fc["account_id"], list(fc.get("parent_path") or []))
        db.session.add(
            FileCenterEntry(
                account_id=fc["account_id"],
                parent_id=parent_id,
                name=fc.get("name") or main_data.get("name") or "未命名",
                is_folder=False,
                upload_file_id=main_data["id"],
                source=fc.get("source") or "upload",
                origin=fc.get("origin"),
            )
        )
    return True
```

顶部 import 追加：

```python
from internal.service.file_center_paths import ensure_path as _ensure_path
```

并在实现里用 `_ensure_path(...)`（保持与既有 `_` 前缀内部工具的命名一致）。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/service/test_file_center_recycle.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/recycle_bin_handlers.py api/test/internal/service/test_file_center_recycle.py
git commit -m "feat(file-center): restore upload_file re-creates node at original path"
```

---

## Task 4: `purge_upload_file` 清理残留节点

**Files:**
- Modify: `api/internal/service/recycle_bin_handlers.py`（`purge_upload_file`，约 L655-665）

- [ ] **Step 1: 写失败测试**

```python
def test_purge_upload_file_cleans_leftover_node(monkeypatch):
    import internal.service.storage.storage_migration_service as sms
    from internal.service.recycle_bin_handlers import purge_upload_file
    from internal.model import UploadFile
    from internal.extension.database_extension import db

    monkeypatch.setattr(sms, "_delete_object", lambda *_a, **_k: None)
    svc = FileCenterService()
    acc = uuid.uuid4()
    fid = uuid.uuid4()
    svc.import_upload_file(acc, upload_file_id=fid, parent_id=None, name="gone.txt")
    purge_upload_file({"main": {"id": fid, "key": "k", "storage_backend": "local",
                                "account_id": acc, "size": 1}})
    db.session.commit()
    assert svc.list_children(acc, parent_id=None) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_file_center_recycle.py::test_purge_upload_file_cleans_leftover_node -q`
Expected: FAIL（节点未清理）

- [ ] **Step 3: 实现**

把 `purge_upload_file` 替换为：

```python
def purge_upload_file(snapshot: dict[str, Any]) -> None:
    """留存期结束彻底销毁底层对象，并清理文件中心残留节点。"""
    main_data = snapshot.get("main") or {}
    key = main_data.get("key")
    if key:
        backend = (main_data.get("storage_backend") or "local").strip() or "local"
        from internal.service.storage.storage_migration_service import _delete_object
        _delete_object(backend, key)
        _release_storage_quota(main_data)
        logger.info("回收站销毁上传文件 key=%s backend=%s", key, backend)
    if main_data.get("id"):
        _delete_entries_by_upload_file(main_data["id"])
```

顶部 import 追加：

```python
from internal.service.file_center_paths import (
    delete_entries_by_upload_file as _delete_entries_by_upload_file,
)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/service/test_file_center_recycle.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: 回归（确保未破坏既有回收站用例）**

Run: `python -m pytest test/internal/service/ -q -k recycle`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/recycle_bin_handlers.py api/test/internal/service/test_file_center_recycle.py
git commit -m "feat(file-center): purge cleans leftover file_center nodes"
```

---

## Self-Review
**规格覆盖**：§4.3 删除/恢复语义（Task 2/3/4）、§9 快照 `file_center` 字段（Task 2）✅。
**占位符扫描**：无 TBD/TODO。
**类型一致性**：`file_center_paths` 导出 `build_parent_path_names/ensure_path/delete_entries_by_upload_file`，在 Task 2/3/4 以别名导入使用，名称一致。

## 下一份计划
- Plan 3 `2026-09-30-user-file-center-agent-tools.md`（Agent 工具，依赖 Plan 1 + 本计划）
- Plan 4 `2026-09-30-user-file-center-artifact-collection.md`
- Plan 5 `2026-09-30-user-file-center-frontend.md`
