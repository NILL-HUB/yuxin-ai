# 用户侧文件中心（后端核心）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地用户侧文件中心的**后端核心**——`file_center_entry` 虚拟目录树 + `FileCenterService` + `/space/files/*` 路由，删除复用回收站；产出可用 HTTP API。

**Architecture:** 新增一张组织层表 `file_center_entry`（每账号一棵树，节点分 folder/file，file 1:1 指向 `UploadFile` 且**不加外键**）；`FileCenterService` 负责树操作，删除经 `RecycleBinService.delete_resource(resource_type="upload_file")`；不新建存储层、不改 `UploadFile`。

**Tech Stack:** Python / Quart / SQLAlchemy 2.0（`pkg.sqlalchemy.Base`）/ Alembic / marshmallow / injector / pytest。

**计划拆分（本特性分 5 份计划，本文件为第 1 份）**
1. **（本文件）后端核心**：模型 + 迁移 + `FileCenterService` + `/space/files/*` 路由。
2. 回收站原目录恢复：`snapshot_upload_file` / `restore_upload_file` / `purge_upload_file` 增 `file_center` 字段。
3. Agent 工具：builtin provider `file_center` + 挂载。
4. 产物收编：`image_persistence` 等改为建记录。
5. 前端：`/space/files` 页面 + i18n。

**前置条件（实施前必须满足）**
- 执行环境的迁移图为**单 head**；`alembic heads` 的当前值即新迁移的 `down_revision`。
- 本仓库工作区当前存在并行未提交改动（沙箱多后端等）。**本计划的每个 `git add` 只加本任务列举的文件**，不要 `git add -A`。
- 测试命令统一在 `api/` 目录下执行：`python -m pytest <path> -q`。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `api/internal/model/file_center_entry.py` | 新建：目录树节点模型 |
| `api/internal/model/__init__.py` | 修改：导出 `FileCenterEntry` |
| `api/internal/migration/versions/<rev>_create_file_center_entry.py` | 新建：建表迁移 |
| `api/internal/service/file_center_service.py` | 新建：树操作 + 删除编排 |
| `api/internal/schema/file_center_schema.py` | 新建：响应 schema |
| `api/app/http/file_center_routes.py` | 新建：`/space/files/*` 路由 |
| `api/app/http/asgi_app.py` | 修改：注册路由 |
| `api/app/http/module.py` | 修改：绑定 `FileCenterService` |
| `api/test/internal/service/test_file_center_service.py` | 新建：服务单测 |
| `api/test/app/http/test_file_center_routes.py` | 新建：路由契约测试 |
| `docs/prd/modules/06-file-storage.md` | 修改：增「文件中心」章节 |

---

## Task 1: 目录树模型 `FileCenterEntry`

**Files:**
- Create: `api/internal/model/file_center_entry.py`
- Modify: `api/internal/model/__init__.py`

- [ ] **Step 1: 写模型文件**

创建 `api/internal/model/file_center_entry.py`：

```python
"""用户文件中心条目（虚拟目录树）。

每个账号一棵目录树：节点分 folder / file 两类；file 节点 1:1 指向一个 UploadFile。
物理对象归 RuntimeStorageProxy、删除/恢复归 RecycleBinService——本表只做「组织层」。

`upload_file_id` **不加外键约束**：回收站删除 upload_file 后本节点需保留、恢复时再挂回；
若加外键，悬挂引用会阻塞 upload_file 的物理删除。
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    PrimaryKeyConstraint,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FileCenterEntry(Base):
    __tablename__ = "file_center_entry"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_file_center_entry_id"),
        Index("ix_file_center_entry_account_parent", "account_id", "parent_id"),
        Index("ix_file_center_entry_upload_file", "upload_file_id"),
        Index(
            "uq_file_center_entry_root_name",
            "account_id",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
        Index(
            "uq_file_center_entry_child_name",
            "account_id",
            "parent_id",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NOT NULL"),
        ),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, nullable=False)
    parent_id = Column(UUID, nullable=True)
    name = Column(String(512), nullable=False, server_default=text("''::character varying"))
    is_folder = Column(Boolean, nullable=False, server_default=text("false"))
    upload_file_id = Column(UUID, nullable=True)
    source = Column(String(32), nullable=False, server_default=text("'upload'::character varying"))
    origin = Column(String(32), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
```

- [ ] **Step 2: 注册到模型导出**

在 `api/internal/model/__init__.py` 中，紧邻 `from .storage_config import StorageConfig` 之后加一行：

```python
from .file_center_entry import FileCenterEntry
```

并在 `__all__` 列表中加入 `"FileCenterEntry"`（放在 `"StorageConfig"` 之前）。

- [ ] **Step 3: 验证可导入**

Run: `python -c "from internal.model import FileCenterEntry; print(FileCenterEntry.__tablename__)"`（在 `api/` 目录）
Expected: 输出 `file_center_entry`

- [ ] **Step 4: Commit**

```bash
git add api/internal/model/file_center_entry.py api/internal/model/__init__.py
git commit -m "feat(file-center): add file_center_entry model (virtual directory tree)"
```

---

## Task 2: 建表迁移

**Files:**
- Create: `api/internal/migration/versions/o9f0a1b2c3d4_create_file_center_entry.py`

- [ ] **Step 1: 确认当前 head**

Run: `python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; print(ScriptDirectory.from_config(Config('internal/migration/alembic.ini')).get_heads())"`
Expected: 输出单个 revision（实现时若与 `n8d9e0f1a2b3` 不同，以其为准填 `down_revision`）。

- [ ] **Step 2: 写迁移文件**

创建 `api/internal/migration/versions/o9f0a1b2c3d4_create_file_center_entry.py`（`down_revision` 用上一步实测的 head）：

```python
"""create file_center_entry table

Revision ID: o9f0a1b2c3d4
Revises: n8d9e0f1a2b3
Create Date: 2026-09-30 00:00:00.000000

用户文件中心：在既有存储抽象（RuntimeStorageProxy）与回收站（RecycleBinService）之上，
新增「组织层」虚拟目录树。物理对象与删除语义均复用既有链路，本迁移只建表 + 索引。
"""
from alembic import op
import sqlalchemy as sa


revision = "o9f0a1b2c3d4"
down_revision = "n8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "file_center_entry",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("account_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(512), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column("is_folder", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("upload_file_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default=sa.text("'upload'::character varying")),
        sa.Column("origin", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint("id", name="pk_file_center_entry_id"),
    )
    op.create_index("ix_file_center_entry_account_parent", "file_center_entry", ["account_id", "parent_id"])
    op.create_index("ix_file_center_entry_upload_file", "file_center_entry", ["upload_file_id"])
    op.create_index(
        "uq_file_center_entry_root_name",
        "file_center_entry",
        ["account_id", "name"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL"),
    )
    op.create_index(
        "uq_file_center_entry_child_name",
        "file_center_entry",
        ["account_id", "parent_id", "name"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_file_center_entry_child_name", table_name="file_center_entry")
    op.drop_index("uq_file_center_entry_root_name", table_name="file_center_entry")
    op.drop_index("ix_file_center_entry_upload_file", table_name="file_center_entry")
    op.drop_index("ix_file_center_entry_account_parent", table_name="file_center_entry")
    op.drop_table("file_center_entry")
```

- [ ] **Step 3: 校验单 head**

Run: `python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; print(ScriptDirectory.from_config(Config('internal/migration/alembic.ini')).get_heads())"`
Expected: 输出 `['o9f0a1b2c3d4']`（单 head）。

- [ ] **Step 4: 应用迁移（本地库）**

Run: `python -m alembic -c internal/migration/alembic.ini upgrade head`
Expected: `Running upgrade n8d9e0f1a2b3 -> o9f0a1b2c3d4, create file_center_entry table`

- [ ] **Step 5: Commit**

```bash
git add api/internal/migration/versions/o9f0a1b2c3d4_create_file_center_entry.py
git commit -m "feat(file-center): migration to create file_center_entry table"
```

---

## Task 3: `FileCenterService` —— 建目录 / 列目录

**Files:**
- Create: `api/internal/service/file_center_service.py`
- Create: `api/test/internal/service/test_file_center_service.py`

- [ ] **Step 1: 写失败测试**

创建 `api/test/internal/service/test_file_center_service.py`：

```python
"""FileCenterService 目录树操作单测。"""
import uuid

import pytest

from internal.exception import ValidateErrorException, NotFoundException
from internal.service.file_center_service import FileCenterService


def _svc() -> FileCenterService:
    return FileCenterService()


def test_mkdir_creates_folder():
    account_id = uuid.uuid4()
    svc = _svc()
    entry = svc.mkdir(account_id, parent_id=None, name="文档")
    assert entry.is_folder is True
    assert entry.name == "文档"
    assert entry.parent_id is None


def test_mkdir_rejects_duplicate_name_in_same_parent():
    account_id = uuid.uuid4()
    svc = _svc()
    parent = svc.mkdir(account_id, parent_id=None, name="A")
    svc.mkdir(account_id, parent_id=parent.id, name="B")
    with pytest.raises(ValidateErrorException):
        svc.mkdir(account_id, parent_id=parent.id, name="B")


def test_list_children_only_returns_own_account():
    svc = _svc()
    acc_a, acc_b = uuid.uuid4(), uuid.uuid4()
    svc.mkdir(acc_a, parent_id=None, name="a1")
    svc.mkdir(acc_b, parent_id=None, name="b1")
    names = [e.name for e in svc.list_children(acc_a, parent_id=None)]
    assert names == ["a1"]


def test_mkdir_under_foreign_parent_rejected():
    svc = _svc()
    acc_a, acc_b = uuid.uuid4(), uuid.uuid4()
    parent = svc.mkdir(acc_a, parent_id=None, name="A")
    with pytest.raises(NotFoundException):
        svc.mkdir(acc_b, parent_id=parent.id, name="x")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest test/internal/service/test_file_center_service.py -q`
Expected: FAIL（`ModuleNotFoundError: internal.service.file_center_service`）

- [ ] **Step 3: 写最小实现**

创建 `api/internal/service/file_center_service.py`：

```python
"""用户文件中心服务：虚拟目录树的读取与组织操作。

只做「组织层」：物理对象归 RuntimeStorageProxy，删除/恢复归 RecycleBinService。
"""
from dataclasses import dataclass

from injector import inject

from internal.exception import NotFoundException, ValidateErrorException
from internal.extension.database_extension import db
from internal.model import FileCenterEntry
from internal.service.recycle_bin_service import RecycleBinService

_MAX_NAME_LEN = 512


@inject
@dataclass
class FileCenterService:
    """文件中心虚拟目录树服务。"""

    recycle_bin_service: RecycleBinService

    # ------------------------------------------------------------------ #
    #  读取
    # ------------------------------------------------------------------ #
    def list_children(self, account_id, parent_id=None) -> list[FileCenterEntry]:
        """列出某目录下的直接子节点；parent_id 为 None 时列账号根。"""
        query = db.session.query(FileCenterEntry).filter(FileCenterEntry.account_id == account_id)
        if parent_id is None:
            query = query.filter(FileCenterEntry.parent_id.is_(None))
        else:
            query = query.filter(FileCenterEntry.parent_id == parent_id)
        return query.order_by(FileCenterEntry.is_folder.desc(), FileCenterEntry.name.asc()).all()

    # ------------------------------------------------------------------ #
    #  组织操作
    # ------------------------------------------------------------------ #
    def mkdir(self, account_id, *, parent_id=None, name: str) -> FileCenterEntry:
        """在 parent_id 下新建目录。"""
        name = self._validate_name(name)
        if parent_id is not None:
            self._get_owned_entry(account_id, parent_id, expect_folder=True)
        self._assert_no_conflict(account_id, parent_id, name)
        entry = FileCenterEntry(
            account_id=account_id,
            parent_id=parent_id,
            name=name,
            is_folder=True,
            source="upload",
        )
        db.session.add(entry)
        db.session.commit()
        return entry

    # ------------------------------------------------------------------ #
    #  内部工具
    # ------------------------------------------------------------------ #
    @staticmethod
    def _validate_name(name: str) -> str:
        text = str(name or "").strip()
        if not text:
            raise ValidateErrorException("名称不能为空")
        if len(text) > _MAX_NAME_LEN:
            raise ValidateErrorException("名称过长")
        if "/" in text or "\\" in text:
            raise ValidateErrorException("名称不能包含路径分隔符")
        return text

    def _get_owned_entry(self, account_id, entry_id, *, expect_folder: bool = False) -> FileCenterEntry:
        entry = (
            db.session.query(FileCenterEntry)
            .filter(FileCenterEntry.id == entry_id, FileCenterEntry.account_id == account_id)
            .one_or_none()
        )
        if entry is None:
            raise NotFoundException("目标不存在")
        if expect_folder and not entry.is_folder:
            raise ValidateErrorException("目标不是目录")
        return entry

    def _assert_no_conflict(self, account_id, parent_id, name: str, *, exclude_id=None) -> None:
        query = db.session.query(FileCenterEntry).filter(
            FileCenterEntry.account_id == account_id,
            FileCenterEntry.name == name,
        )
        if parent_id is None:
            query = query.filter(FileCenterEntry.parent_id.is_(None))
        else:
            query = query.filter(FileCenterEntry.parent_id == parent_id)
        if exclude_id is not None:
            query = query.filter(FileCenterEntry.id != exclude_id)
        if query.one_or_none() is not None:
            raise ValidateErrorException("同级已存在同名节点")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest test/internal/service/test_file_center_service.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/file_center_service.py api/test/internal/service/test_file_center_service.py
git commit -m "feat(file-center): FileCenterService mkdir/list_children with account isolation"
```

---

## Task 4: 重命名 / 移动（含成环校验）

**Files:**
- Modify: `api/internal/service/file_center_service.py`
- Modify: `api/test/internal/service/test_file_center_service.py`

- [ ] **Step 1: 追加失败测试**

在 `api/test/internal/service/test_file_center_service.py` 末尾追加：

```python
def test_rename_changes_name():
    svc = _svc()
    acc = uuid.uuid4()
    entry = svc.mkdir(acc, parent_id=None, name="旧名")
    renamed = svc.rename(acc, entry.id, "新名")
    assert renamed.name == "新名"


def test_rename_rejects_duplicate():
    svc = _svc()
    acc = uuid.uuid4()
    svc.mkdir(acc, parent_id=None, name="A")
    b = svc.mkdir(acc, parent_id=None, name="B")
    with pytest.raises(ValidateErrorException):
        svc.rename(acc, b.id, "A")


def test_move_into_own_descendant_rejected():
    svc = _svc()
    acc = uuid.uuid4()
    root = svc.mkdir(acc, parent_id=None, name="R")
    child = svc.mkdir(acc, parent_id=root.id, name="C")
    with pytest.raises(ValidateErrorException):
        svc.move(acc, root.id, child.id)


def test_move_reparents_entry():
    svc = _svc()
    acc = uuid.uuid4()
    a = svc.mkdir(acc, parent_id=None, name="A")
    b = svc.mkdir(acc, parent_id=None, name="B")
    moved = svc.move(acc, a.id, b.id)
    assert moved.parent_id == b.id
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_file_center_service.py -q`
Expected: FAIL（`AttributeError: 'FileCenterService' object has no attribute 'rename'`）

- [ ] **Step 3: 实现 rename / move**

在 `FileCenterService` 的「组织操作」区追加：

```python
    def rename(self, account_id, entry_id, new_name: str) -> FileCenterEntry:
        """重命名节点（只改展示名，不动物理对象）。"""
        entry = self._get_owned_entry(account_id, entry_id)
        new_name = self._validate_name(new_name)
        if new_name == entry.name:
            return entry
        self._assert_no_conflict(account_id, entry.parent_id, new_name, exclude_id=entry.id)
        entry.name = new_name
        db.session.commit()
        return entry

    def move(self, account_id, entry_id, new_parent_id) -> FileCenterEntry:
        """把节点移动到 new_parent_id 目录下（禁止移动到自身子孙）。"""
        entry = self._get_owned_entry(account_id, entry_id)
        target_parent_id = None if new_parent_id in (None, "") else new_parent_id
        if target_parent_id is not None:
            self._get_owned_entry(account_id, target_parent_id, expect_folder=True)
            self._assert_not_cycle(entry, target_parent_id)
        self._assert_no_conflict(account_id, target_parent_id, entry.name, exclude_id=entry.id)
        entry.parent_id = target_parent_id
        db.session.commit()
        return entry

    def _assert_not_cycle(self, entry: FileCenterEntry, new_parent_id) -> None:
        """沿 new_parent_id 向上回溯，若遇到 entry 自身即为成环。"""
        cursor = new_parent_id
        seen = set()
        while cursor is not None:
            if str(cursor) == str(entry.id):
                raise ValidateErrorException("不能移动到自身或其子目录下")
            if cursor in seen:
                raise ValidateErrorException("目录结构异常（存在环）")
            seen.add(cursor)
            parent = (
                db.session.query(FileCenterEntry.parent_id)
                .filter(
                    FileCenterEntry.id == cursor,
                    FileCenterEntry.account_id == entry.account_id,
                )
                .one_or_none()
            )
            cursor = parent[0] if parent is not None else None
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/service/test_file_center_service.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/file_center_service.py api/test/internal/service/test_file_center_service.py
git commit -m "feat(file-center): rename/move with cycle and conflict guards"
```

---

## Task 5: 删除（文件入回收站、目录递归）

**Files:**
- Modify: `api/internal/service/file_center_service.py`
- Modify: `api/test/internal/service/test_file_center_service.py`

- [ ] **Step 1: 追加失败测试**

在测试文件末尾追加（用替身捕获回收站调用，避免依赖真实回收站）：

```python
class _FakeRecycleBin:
    def __init__(self):
        self.calls = []

    def delete_resource(self, **kwargs):
        self.calls.append(kwargs)
        return True


def _svc_with_fake_recycle():
    svc = FileCenterService()
    fake = _FakeRecycleBin()
    svc.recycle_bin_service = fake
    return svc, fake


def test_delete_file_node_sends_upload_file_to_recycle():
    svc, fake = _svc_with_fake_recycle()
    acc = uuid.uuid4()
    fid = uuid.uuid4()
    entry = svc.import_upload_file(acc, upload_file_id=fid, parent_id=None, name="a.txt")
    svc.delete_node(acc, entry.id)
    assert [c["resource_id"] for c in fake.calls] == [fid]
    assert fake.calls[0]["resource_type"] == "upload_file"
    assert svc.list_children(acc, parent_id=None) == []


def test_delete_folder_recursively_recycles_files():
    svc, fake = _svc_with_fake_recycle()
    acc = uuid.uuid4()
    folder = svc.mkdir(acc, parent_id=None, name="F")
    f1 = uuid.uuid4()
    f2 = uuid.uuid4()
    svc.import_upload_file(acc, upload_file_id=f1, parent_id=folder.id, name="1.txt")
    svc.import_upload_file(acc, upload_file_id=f2, parent_id=folder.id, name="2.txt")
    svc.delete_node(acc, folder.id)
    assert sorted(c["resource_id"] for c in fake.calls) == sorted([f1, f2])
    assert svc.list_children(acc, parent_id=None) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_file_center_service.py -q`
Expected: FAIL（`AttributeError: ... 'delete_node'` / `'import_upload_file'`）

- [ ] **Step 3: 实现 import_upload_file 与 delete_node**

在 `FileCenterService` 追加：

```python
    def import_upload_file(
        self,
        account_id,
        *,
        upload_file_id,
        parent_id=None,
        name: str,
        source: str = "upload",
        origin: str | None = None,
    ) -> FileCenterEntry:
        """把一个 UploadFile 挂到指定目录下（不存在则新建文件节点）。"""
        if parent_id is not None:
            self._get_owned_entry(account_id, parent_id, expect_folder=True)
        existing = (
            db.session.query(FileCenterEntry)
            .filter(
                FileCenterEntry.account_id == account_id,
                FileCenterEntry.upload_file_id == upload_file_id,
            )
            .one_or_none()
        )
        if existing is not None:
            return existing
        name = self._validate_name(name)
        self._assert_no_conflict(account_id, parent_id, name)
        entry = FileCenterEntry(
            account_id=account_id,
            parent_id=parent_id,
            name=name,
            is_folder=False,
            upload_file_id=upload_file_id,
            source=source,
            origin=origin,
        )
        db.session.add(entry)
        db.session.commit()
        return entry

    def delete_node(
        self,
        account_id,
        entry_id,
        *,
        deleted_by_type: str = "user",
        retention_days: int | None = None,
    ) -> None:
        """删除节点：文件节点 → 底层 upload_file 入回收站；目录节点 → 递归。"""
        entry = self._get_owned_entry(account_id, entry_id)
        if entry.is_folder:
            file_entries = self._collect_descendant_file_entries(account_id, entry.id)
            folder_ids = [entry.id] + [e.id for e in self._collect_descendant_folder_entries(account_id, entry.id)]
            for file_entry in file_entries:
                self._recycle_file(account_id, file_entry, deleted_by_type, retention_days)
            db.session.query(FileCenterEntry).filter(FileCenterEntry.id.in_(folder_ids)).delete(
                synchronize_session=False
            )
            db.session.commit()
        else:
            self._recycle_file(account_id, entry, deleted_by_type, retention_days)
            db.session.query(FileCenterEntry).filter(FileCenterEntry.id == entry.id).delete(
                synchronize_session=False
            )
            db.session.commit()

    def _recycle_file(self, account_id, entry: FileCenterEntry, deleted_by_type: str, retention_days) -> None:
        if entry.upload_file_id:
            self.recycle_bin_service.delete_resource(
                resource_type="upload_file",
                resource_id=entry.upload_file_id,
                resource_name=entry.name,
                deleted_by=account_id,
                deleted_by_type=deleted_by_type,
                retention_days=retention_days,
            )

    def _collect_descendant_folder_entries(self, account_id, root_id) -> list[FileCenterEntry]:
        result: list[FileCenterEntry] = []
        frontier = [root_id]
        while frontier:
            rows = (
                db.session.query(FileCenterEntry)
                .filter(
                    FileCenterEntry.account_id == account_id,
                    FileCenterEntry.parent_id.in_(frontier),
                    FileCenterEntry.is_folder.is_(True),
                )
                .all()
            )
            result.extend(rows)
            frontier = [r.id for r in rows]
        return result

    def _collect_descendant_file_entries(self, account_id, root_id) -> list[FileCenterEntry]:
        folder_ids = [root_id] + [e.id for e in self._collect_descendant_folder_entries(account_id, root_id)]
        return (
            db.session.query(FileCenterEntry)
            .filter(
                FileCenterEntry.account_id == account_id,
                FileCenterEntry.parent_id.in_(folder_ids),
                FileCenterEntry.is_folder.is_(False),
            )
            .all()
        )
```

> 注：`FileCenterService()` 无参构造用于单测（`recycle_bin_service` 由测试注入替身；运行时由 injector 注入真实服务）。为支持无参构造，**把 `recycle_bin_service` 字段声明为 `field(default=None)`**：文件顶部改为
> `from dataclasses import dataclass, field` 且字段写成 `recycle_bin_service: RecycleBinService = field(default=None)`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/service/test_file_center_service.py -q`
Expected: PASS（10 passed）

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/file_center_service.py api/test/internal/service/test_file_center_service.py
git commit -m "feat(file-center): delete_node (file to recycle bin, folder recursive)"
```

---

## Task 6: 「全部文件」视图（`list_all_files`）

**Files:**
- Modify: `api/internal/service/file_center_service.py`
- Modify: `api/test/internal/service/test_file_center_service.py`

- [ ] **Step 1: 追加失败测试**

```python
def test_list_all_files_paginates_and_flags_organized():
    svc, _ = _svc_with_fake_recycle()
    acc = uuid.uuid4()
    f1, f2 = uuid.uuid4(), uuid.uuid4()
    svc.import_upload_file(acc, upload_file_id=f1, parent_id=None, name="1.txt")
    result = svc.list_all_files(acc, page=1, page_size=10, extra_upload_file_ids=[f1, f2])
    assert result["total"] == 2
    by_id = {item["upload_file_id"]: item for item in result["items"]}
    assert by_id[str(f1)]["organized"] is True
    assert by_id[str(f2)]["organized"] is False
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest test/internal/service/test_file_center_service.py::test_list_all_files_paginates_and_flags_organized -q`
Expected: FAIL（无 `list_all_files`）

- [ ] **Step 3: 实现 `list_all_files`**

```python
    def list_all_files(
        self,
        account_id,
        *,
        page: int = 1,
        page_size: int = 20,
        extra_upload_file_ids=None,
    ) -> dict:
        """「全部文件」视图：账号全部已入树的文件节点（并标注是否已入树本身即 True）。

        入参 extra_upload_file_ids 供上层把「未入树的 upload_file」一并合入展示，
        此处只负责已入树节点；合并与来源标注由路由/上层完成（保持服务职责单一）。
        """
        import math

        page = max(int(page or 1), 1)
        page_size = max(min(int(page_size or 20), 100), 1)
        query = db.session.query(FileCenterEntry).filter(
            FileCenterEntry.account_id == account_id,
            FileCenterEntry.is_folder.is_(False),
        )
        total = query.count()
        rows = (
            query.order_by(FileCenterEntry.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [
            {
                "entry_id": str(row.id),
                "upload_file_id": str(row.upload_file_id) if row.upload_file_id else None,
                "name": row.name,
                "source": row.source,
                "origin": row.origin,
                "organized": True,
            }
            for row in rows
        ]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total else 0,
            "total_record": total,
        }
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest test/internal/service/test_file_center_service.py -q`
Expected: PASS（11 passed）

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/file_center_service.py api/test/internal/service/test_file_center_service.py
git commit -m "feat(file-center): list_all_files view with pagination"
```

---

## Task 7: Schema + `/space/files/*` 路由 + DI 绑定 + 注册

**Files:**
- Create: `api/internal/schema/file_center_schema.py`
- Create: `api/app/http/file_center_routes.py`
- Modify: `api/app/http/asgi_app.py`
- Modify: `api/app/http/module.py`
- Create: `api/test/app/http/test_file_center_routes.py`

- [ ] **Step 1: 写 schema**

创建 `api/internal/schema/file_center_schema.py`：

```python
"""用户文件中心响应 schema。"""
from marshmallow import Schema, fields, pre_dump


class FileCenterEntrySchema(Schema):
    id = fields.String()
    parent_id = fields.String(allow_none=True)
    name = fields.String()
    is_folder = fields.Boolean()
    upload_file_id = fields.String(allow_none=True)
    source = fields.String()
    origin = fields.String(allow_none=True)

    @pre_dump
    def process_data(self, data, **kwargs):
        return {
            "id": str(data.id),
            "parent_id": str(data.parent_id) if data.parent_id else None,
            "name": data.name,
            "is_folder": bool(data.is_folder),
            "upload_file_id": str(data.upload_file_id) if data.upload_file_id else None,
            "source": data.source,
            "origin": data.origin,
        }


class FileCenterChildrenSchema(Schema):
    items = fields.List(fields.Nested(FileCenterEntrySchema))
    parent_id = fields.String(allow_none=True)
```

- [ ] **Step 2: 写路由模块**

创建 `api/app/http/file_center_routes.py`：

```python
"""用户侧文件中心路由（/space/files/*）。"""
from uuid import UUID

_registered = False


def _uuid_arg(value):
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def register_routes(quart_app):
    global _registered
    if _registered:
        return
    _registered = True

    @quart_app.get("/space/files")
    async def file_center_list():
        from quart import request

        from app.http import asgi_app as a
        from internal.schema.file_center_schema import FileCenterChildrenSchema
        from internal.service.file_center_service import FileCenterService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        parent_id = _uuid_arg(request.args.get("parent_id"))
        items = await a._to_thread(
            lambda: a._get_service(FileCenterService).list_children(account.id, parent_id=parent_id)
        )
        return a._ok(FileCenterChildrenSchema().dump({"items": items, "parent_id": str(parent_id) if parent_id else None}))

    @quart_app.get("/space/files/all")
    async def file_center_list_all():
        from quart import request

        from app.http import asgi_app as a
        from internal.service.file_center_service import FileCenterService

        account, err = await a._resolve_account()
        if err is not None:
            return err

        def _int_arg(name, default):
            raw = request.args.get(name)
            try:
                return int(raw) if raw is not None else default
            except (TypeError, ValueError):
                return default

        result = await a._to_thread(
            lambda: a._get_service(FileCenterService).list_all_files(
                account.id,
                page=_int_arg("page", 1),
                page_size=_int_arg("page_size", 20),
            )
        )
        return a._ok(result)

    @quart_app.post("/space/files/folders")
    async def file_center_mkdir():
        from quart import request

        from app.http import asgi_app as a
        from internal.exception import NotFoundException, ValidateErrorException
        from internal.schema.file_center_schema import FileCenterEntrySchema
        from internal.service.file_center_service import FileCenterService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        payload = {}
        raw_body = await request.get_json(silent=True)
        if isinstance(raw_body, dict):
            payload = raw_body
        try:
            entry = await a._to_thread(
                lambda: a._get_service(FileCenterService).mkdir(
                    account.id,
                    parent_id=_uuid_arg(payload.get("parent_id")),
                    name=str(payload.get("name") or ""),
                )
            )
        except NotFoundException as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        except ValidateErrorException as exc:
            return a._json_resp(code="validate_error", message=str(exc), status=400)
        return a._ok(FileCenterEntrySchema().dump(entry))

    @quart_app.patch("/space/files/<string:entry_id>")
    async def file_center_update(entry_id):
        from quart import request

        from app.http import asgi_app as a
        from internal.exception import NotFoundException, ValidateErrorException
        from internal.schema.file_center_schema import FileCenterEntrySchema
        from internal.service.file_center_service import FileCenterService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        payload = {}
        raw_body = await request.get_json(silent=True)
        if isinstance(raw_body, dict):
            payload = raw_body
        service = a._get_service(FileCenterService)
        try:
            if "parent_id" in payload:
                entry = await a._to_thread(
                    lambda: service.move(account.id, UUID(entry_id), _uuid_arg(payload.get("parent_id")))
                )
            else:
                entry = await a._to_thread(
                    lambda: service.rename(account.id, UUID(entry_id), str(payload.get("name") or ""))
                )
        except NotFoundException as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        except ValidateErrorException as exc:
            return a._json_resp(code="validate_error", message=str(exc), status=400)
        return a._ok(FileCenterEntrySchema().dump(entry))

    @quart_app.delete("/space/files/<string:entry_id>")
    async def file_center_delete(entry_id):
        from app.http import asgi_app as a
        from internal.exception import NotFoundException
        from internal.service.file_center_service import FileCenterService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        try:
            await a._to_thread(
                lambda: a._get_service(FileCenterService).delete_node(account.id, UUID(entry_id))
            )
        except NotFoundException as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        return a._ok_msg("已移入回收站")

    @quart_app.post("/space/files/import")
    async def file_center_import():
        from quart import request

        from app.http import asgi_app as a
        from internal.exception import NotFoundException, ValidateErrorException
        from internal.schema.file_center_schema import FileCenterEntrySchema
        from internal.service.file_center_service import FileCenterService

        account, err = await a._resolve_account()
        if err is not None:
            return err
        payload = {}
        raw_body = await request.get_json(silent=True)
        if isinstance(raw_body, dict):
            payload = raw_body
        upload_file_id = _uuid_arg(payload.get("upload_file_id"))
        if upload_file_id is None:
            return a._json_resp(code="validate_error", message="upload_file_id 无效", status=400)
        try:
            entry = await a._to_thread(
                lambda: a._get_service(FileCenterService).import_upload_file(
                    account.id,
                    upload_file_id=upload_file_id,
                    parent_id=_uuid_arg(payload.get("parent_id")),
                    name=str(payload.get("name") or ""),
                )
            )
        except NotFoundException as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        except ValidateErrorException as exc:
            return a._json_resp(code="validate_error", message=str(exc), status=400)
        return a._ok(FileCenterEntrySchema().dump(entry))
```

- [ ] **Step 3: 注册路由**

在 `api/app/http/asgi_app.py` 的 import 区（紧邻 `from app.http.user_recycle_bin_routes import register_routes as _register_user_recycle_bin_routes`）加：

```python
from app.http.file_center_routes import register_routes as _register_file_center_routes
```

并在底部注册调用区（紧邻 `_register_user_recycle_bin_routes(quart_app)`）加：

```python
_register_file_center_routes(quart_app)
```

- [ ] **Step 4: 绑定服务**

在 `api/app/http/module.py` 的 `binder.bind(RecycleBinService, to=RecycleBinService)` 之后加：

```python
binder.bind(FileCenterService, to=FileCenterService)
```

并在该文件顶部 import 区加 `from internal.service.file_center_service import FileCenterService`。

- [ ] **Step 5: 写路由契约测试**

创建 `api/test/app/http/test_file_center_routes.py`（用既有路由测试范式：替换 `_resolve_account` 与 `_get_service`）：

```python
"""文件中心路由契约测试。"""
import uuid

import pytest

from app.http import asgi_app as a


class _FakeAccount:
    id = uuid.uuid4()


class _FakeEntry:
    def __init__(self):
        self.id = uuid.uuid4()
        self.parent_id = None
        self.name = "文档"
        self.is_folder = True
        self.upload_file_id = None
        self.source = "upload"
        self.origin = None


class _FakeFileCenterService:
    def mkdir(self, account_id, *, parent_id=None, name=""):
        e = _FakeEntry()
        e.name = name
        return e


@pytest.fixture
def client(monkeypatch):
    from app.http.app import create_app  # 沿用仓库既有 app 工厂
    app = create_app()
    test_client = app.test_client()

    async def _resolve_account():
        return _FakeAccount(), None

    monkeypatch.setattr(a, "_resolve_account", _resolve_account)
    monkeypatch.setitem(a._service_cache, _FakeFileCenterService, _FakeFileCenterService())
    return test_client


@pytest.mark.asyncio
async def test_mkdir_returns_entry(client):
    resp = await client.post("/space/files/folders", json={"name": "文档"})
    assert resp.status_code == 200
    body = await resp.get_json()
    assert body["code"] == "success"
    assert body["data"]["name"] == "文档"
    assert body["data"]["is_folder"] is True
```

> 若仓库既有路由测试用的是别的 app 构造/夹具方式（见 `api/test/app/http/test_admin_sandbox_routes.py` 等），**沿用它们的夹具与 monkeypatch 方式**，不要另造一套。

- [ ] **Step 6: 运行测试**

Run: `python -m pytest test/app/http/test_file_center_routes.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add api/internal/schema/file_center_schema.py api/app/http/file_center_routes.py api/app/http/asgi_app.py api/app/http/module.py api/test/app/http/test_file_center_routes.py
git commit -m "feat(file-center): /space/files routes + schema + DI binding"
```

---

## Task 8: 文档同步

**Files:**
- Modify: `docs/prd/modules/06-file-storage.md`

- [ ] **Step 1: 增章节**

在 `docs/prd/modules/06-file-storage.md` 末尾新增一节「## 18. 用户文件中心（虚拟目录树）」，写明：
- 定位：组织层，物理对象仍归 `RuntimeStorageProxy`，删除/恢复归 `RecycleBinService`，配额归 `StorageQuotaService`；
- 表 `file_center_entry`（含 partial unique 索引与「`upload_file_id` 不加外键」的原因）；
- 路由 `/space/files/*` 六端点；
- 与知识库的关系（只读来源 + 引用保护）。

- [ ] **Step 2: 校验链接可达**

Run: `python -c "import pathlib; p=pathlib.Path('docs/prd/modules/06-file-storage.md'); print('file_center_entry' in p.read_text(encoding='utf-8'))"`
Expected: `True`

- [ ] **Step 3: Commit**

```bash
git add docs/prd/modules/06-file-storage.md
git commit -m "docs(file-storage): document user file center (virtual directory tree)"
```

---

## Self-Review

**1. Spec 覆盖（本计划范围）**：模型（spec §4.2）✅、迁移 ✅、树操作 mkdir/rename/move/delete（§4.4）✅、全部文件视图（§4.1 D1）✅、路由（§4.4）✅、文档（§5#8）✅。
**未覆盖（拆到后续计划）**：回收站原目录恢复（§4.3/§9）、Agent 工具（§4.5）、产物收编（§4.6）、前端（§4.7）。
**2. 占位符扫描**：无 TBD/TODO；每个代码步骤均给出完整代码。
**3. 类型一致性**：`import_upload_file` 在 Task 5 定义、Task 5/6 测试引用；`list_children` 在 Task 3 定义、Task 5 测试引用；`list_all_files` 返回结构在 Task 6 定义、Task 7 路由透传——名称一致。

## 后续计划（衔接链路，各自独立文档，按序实施）

> 依赖方向：Plan 1 →（Plan 2 与 Plan 3/4/5 均可并行）→ Plan 3 依赖 Plan 1+2 的删除/恢复语义 → Plan 4 依赖 Plan 1+3 → Plan 5 依赖 Plan 1。

- **Plan 2** `2026-09-30-user-file-center-recycle-restore.md`：回收站原目录恢复（快照记录 `file_center` 路径；恢复逐级重建父目录并挂回节点；销毁清理残留节点）。
- **Plan 3** `2026-09-30-user-file-center-agent-tools.md`：Agent 工具——builtin provider `file_center`（`list/mkdir/move/rename/delete/read/save_artifact`）+ `assistant_agent_service` 挂载（注入 `requester=account_id`）。
- **Plan 4** `2026-09-30-user-file-center-artifact-collection.md`：产物收编——生成图片建记录并入树、Agent 文本产物入树。
- **Plan 5** `2026-09-30-user-file-center-frontend.md`：前端 `/space/files` 页面 + i18n（zh/en parity）。
