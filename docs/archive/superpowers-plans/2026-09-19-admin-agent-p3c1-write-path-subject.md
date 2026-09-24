# ADMIN-P3c-1 写入侧主体化（数据层解阻塞 + 写路径主体化）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 解除 PG `owner_account_id NOT NULL` 对 admin/Agent 主体的写入阻塞，并让 Neo4j / PG 写入路径按主体键（`MemoryOwnerKey`）落归属，使 admin 记忆「写得进、归属对」。

**Architecture:** 三层改造——(1) **DB**：把「列级非空」升级为「按主体类型非空」（CHECK），主表 + 动态向量分表同步；(2) **模型/DDL**：`UserMemory.owner_account_id` 改可空，运行时建表 DDL 同步；(3) **写入侧**：`LedgerWriter._upsert_vector` 去掉「account 为空即跳过」，Neo4j 节点写入改走 `neo4j_props()`（用户态逐字节等价、admin 态写 `admin_user_id` [+ `agent_id` 哨兵]）。

**Tech Stack:** Python 3.12 / Alembic / SQLAlchemy / PostgreSQL（pgvector）/ Neo4j / pytest

---

## 0. 前置实测结论（执行者必读，勿凭旧文档臆断）

| # | 旧文档说法 | 实测事实 | 本计划的处理 |
| --- | --- | --- | --- |
| 1 | 「admin 写路径阻塞在 `owner_account_id` NOT NULL」 | ✅ 成立。主表 [knowledge.py L144](file:///d:/DEMO/openagent-main/api/internal/model/knowledge.py#L144) 与分表 [embedding_table_router.py L150](file:///d:/DEMO/openagent-main/api/internal/service/embedding_table_router.py#L150) 均为 `NOT NULL`；[_upsert_vector L866-872](file:///d:/DEMO/openagent-main/api/internal/service/memory/ledger_writer.py#L866-L872) 在 account 为空时**主动 return None 跳过**（图节点已建、投影缺失） | Task 1~3 解除 |
| 2 | 写路径「Neo4j 侧仅 user_id」 | ✅ 成立。`user_id` 硬编码出现在 7 个 MATCH/CREATE 段（episode/entity/access/cooccur/agent_curated×2） | Task 4~5 主体化 |
| 3 | 分表按维度**动态建表** | ✅ 成立。`EmbeddingTableRouter.ensure_tables_for_dimension()` 用 `CREATE TABLE IF NOT EXISTS`；迁移只能靠 `information_schema` 扫描 | Task 1/2 双改（迁移补存量 + DDL 覆盖新建） |

**关键不变量（违反即回归）**：

1. **用户态零变化**：对用户主体，`neo4j_props()` 必须产出与今日硬编码**逐字节一致**的属性（`user_id` = 原始字符串）；且**不得要求 `event.user_id` 可解析为 UUID**（历史可能存在非 UUID 值，如 `platform`）。
2. **单 head**：新迁移 `down_revision` 必须指向当前唯一 head `y2b3c4d5e6f8`（[test_migration_graph_integrity.py](file:///d:/DEMO/openagent-main/api/test/internal/migration/test_migration_graph_integrity.py) 强制）。
3. **键值互补不变式**：图节点与 PG 投影行同生同灭；admin 主体必须能同时写两边（这正是本阶段要修的）。

---

## 1. 文件结构规划

### 新建文件

| 文件 | 职责 |
| --- | --- |
| `api/internal/migration/versions/z3c4d5e6f7a8_memory_owner_nullable_account.py` | 解 NOT NULL + 补 CHECK（主表 + 扫描分表） |
| `api/test/internal/migration/test_memory_owner_nullable_migration.py` | 迁移静态守卫（源文本 + 单 head） |
| `api/test/internal/service/memory/test_ledger_writer_admin_subject.py` | 写入侧 admin 主体判别性用例（真替身 db/driver） |

### 修改文件

| 文件 | 改动 |
| --- | --- |
| `api/internal/model/knowledge.py` | `UserMemory.owner_account_id` → `nullable=True` |
| `api/internal/service/embedding_table_router.py` | 分表 DDL：`owner_account_id` 去 `NOT NULL` + 补 CHECK |
| `api/internal/service/memory/ledger_writer.py` | `_upsert_vector` 解阻塞；写路径主体化（7 段 Cypher） |
| `api/test/internal/migration/test_memory_owner_backfill_consistency.py` | 断言 owner_account_id 可空 + CHECK 存在（真库） |
| `docs/prd/memory-system/02-storage-and-retrieval.md` | 关闭「缺口二」+ 更新「缺口十六」 |
| `docs/prd/execution-roadmap.md` | 更新 P3b 已知缺口条数与措辞 |

### 不新增数据表

复用既有 `user_memory` 与 `user_memory_embedding_{dim}`，仅改列可空性 + 加约束。

---

## Task 1: DB 迁移 —— 解 NOT NULL + 按主体类型 CHECK

**Files:**
- Create: `api/internal/migration/versions/z3c4d5e6f7a8_memory_owner_nullable_account.py`
- Test: `api/test/internal/migration/test_memory_owner_nullable_migration.py`

**背景**：约束语义从「`owner_account_id` 恒非空」升级为「`owner_type='user'` ⇒ account 非空 / `owner_type='admin'` ⇒ admin_user 非空」。主表与**已存在**的分表都要改；新建分表由 Task 2 的 DDL 覆盖。

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/migration/test_memory_owner_nullable_migration.py`：

```python
"""记忆主体解阻塞迁移守卫（ADMIN-P3c-1）。

不变量：
1. 新迁移必须是当前单 head（down_revision == 'y2b3c4d5e6f8'）；
2. 必须把 owner_account_id 改为可空（DROP NOT NULL）；
3. 必须补「按主体类型非空」的 CHECK，而非仅去掉非空（否则约束语义丢失）；
4. 必须扫描动态向量分表（与 P3b 的 y2b3c4d5e6f8 同法）；
5. 必须可逆（downgrade 存在）。
"""
import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3]
VERSIONS = API_ROOT / "internal" / "migration" / "versions"
MIGRATION = VERSIONS / "z3c4d5e6f7a8_memory_owner_nullable_account.py"


def _source() -> str:
    assert MIGRATION.is_file(), "缺少解阻塞迁移"
    return MIGRATION.read_text(encoding="utf-8")


def test_down_revision_points_to_previous_head():
    down = re.search(r"^down_revision\s*=\s*[\"']([^\"']+)[\"']", _source(), re.M)
    assert down is not None, "迁移必须声明 down_revision"
    assert down.group(1) == "y2b3c4d5e6f8", "down_revision 必须指向 y2b3c4d5e6f8"


def test_revision_id_is_declared():
    rev = re.search(r"^revision\s*=\s*[\"']([^\"']+)[\"']", _source(), re.M)
    assert rev is not None
    assert rev.group(1) == "z3c4d5e6f7a8"


def test_drops_not_null_on_account_column():
    source = _source()
    assert "DROP NOT NULL" in source, "必须解除 owner_account_id 的非空约束"
    assert "owner_account_id" in source


def test_adds_subject_type_check_constraint():
    """仅去掉 NOT NULL 会让主体类型与归属列失去一致性保证。"""
    source = _source()
    assert "CHECK" in source.upper()
    assert "owner_type = 'user'" in source
    assert "owner_type = 'admin'" in source
    assert "owner_admin_user_id IS NOT NULL" in source


def test_scans_dynamic_embedding_tables():
    source = _source()
    assert "information_schema.tables" in source
    assert "user_memory_embedding_" in source


def test_migration_is_reversible():
    source = _source()
    assert "def downgrade" in source
    # 回退时若存在 admin 主体行必须拒绝（否则 SET NOT NULL 会炸且丢语义）
    assert "owner_type = 'admin'" in source
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/migration/test_memory_owner_nullable_migration.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（`AssertionError: 缺少解阻塞迁移`）

- [ ] **Step 3: 实现迁移**

创建 `api/internal/migration/versions/z3c4d5e6f7a8_memory_owner_nullable_account.py`：

```python
"""make memory owner account column nullable for admin/agent subjects

设计依据：docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md §8。

P3b（y2b3c4d5e6f8）已补 owner_type/owner_admin_user_id/owner_agent_id，读路径按主体过滤；
但写入侧仍被 ``owner_account_id NOT NULL`` 阻塞——admin / Agent 主体该列恒为 NULL，
``LedgerWriter._upsert_vector`` 因此在 account 为空时主动跳过 pgvector 写入，
形成「图节点已建、投影行缺失」的键值互补破坏。

本迁移解除该阻塞，并把约束语义从「列级非空」升级为「按主体类型非空」：

    owner_type='user'  ⇒ owner_account_id      IS NOT NULL
    owner_type='admin' ⇒ owner_admin_user_id   IS NOT NULL

向量分表 ``user_memory_embedding_{dim}`` 按维度动态建表，故同样用 information_schema 扫描；
新建分表由 EmbeddingTableRouter 的 DDL 直接带 CHECK（P3c-1 Task 2）。

Revision ID: z3c4d5e6f7a8
Revises: y2b3c4d5e6f8
"""
from alembic import op
import sqlalchemy as sa

revision = "z3c4d5e6f7a8"
down_revision = "y2b3c4d5e6f8"
branch_labels = None
depends_on = None

_USER_MEMORY_EMBEDDING_PREFIX = "user_memory_embedding_"


def _check_name(table: str) -> str:
    return f"ck_{table}_owner_subject"


def _add_subject_check(table: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {_check_name(table)} CHECK ("
        "    (owner_type = 'user' AND owner_account_id IS NOT NULL)"
        " OR (owner_type = 'admin' AND owner_admin_user_id IS NOT NULL)"
        ")"
    )


def _drop_subject_check(table: str) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {_check_name(table)}")


def _embedding_tables(bind) -> list[str]:
    rows = bind.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE :prefix"
        ),
        {"prefix": f"{_USER_MEMORY_EMBEDDING_PREFIX}%"},
    ).fetchall()
    return [name for (name,) in rows]


def upgrade():
    # 1) 主表：解非空 + 补按主体类型非空
    op.execute("ALTER TABLE user_memory ALTER COLUMN owner_account_id DROP NOT NULL")
    _drop_subject_check("user_memory")
    _add_subject_check("user_memory")

    # 2) 已存在的向量分表同法（动态表名，故用扫描）
    bind = op.get_bind()
    for table_name in _embedding_tables(bind):
        op.execute(f"ALTER TABLE {table_name} ALTER COLUMN owner_account_id DROP NOT NULL")
        _drop_subject_check(table_name)
        _add_subject_check(table_name)


def downgrade():
    # 回退到「列级非空」前必须先确认不存在 admin/Agent 主体行——
    # 否则 SET NOT NULL 会失败，且即便强删也会丢归属语义；此处显式拒绝而非静默删数据。
    bind = op.get_bind()
    admin_rows = bind.execute(
        sa.text("SELECT count(*) FROM user_memory WHERE owner_type = 'admin'")
    ).scalar()
    if admin_rows:
        raise RuntimeError(
            f"存在 {admin_rows} 行 owner_type='admin' 的记忆，无法回退 owner_account_id NOT NULL"
        )

    for table_name in _embedding_tables(bind):
        _drop_subject_check(table_name)
        op.execute(f"ALTER TABLE {table_name} ALTER COLUMN owner_account_id SET NOT NULL")

    _drop_subject_check("user_memory")
    op.execute("ALTER TABLE user_memory ALTER COLUMN owner_account_id SET NOT NULL")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/migration/test_memory_owner_nullable_migration.py test/internal/migration/test_migration_graph_integrity.py -q --no-cov -p no:cacheprovider`
Expected: PASS（含既有单 head 守卫——证明未引入第二个 head）

- [ ] **Step 5: 提交**

```bash
git add api/internal/migration/versions/z3c4d5e6f7a8_memory_owner_nullable_account.py api/test/internal/migration/test_memory_owner_nullable_migration.py
git commit -m "feat(memory): allow null owner_account_id with subject-type check"
```

---

## Task 2: 模型与运行时建表 DDL 同步

**Files:**
- Modify: `api/internal/model/knowledge.py:144`
- Modify: `api/internal/service/embedding_table_router.py:146-181`
- Test: `api/test/internal/migration/test_memory_owner_nullable_migration.py`（追加）

**背景**：迁移只改「已存在」的表。新维度分表由运行时 DDL 创建，必须同样可空 + CHECK，否则新维度下 admin 记忆再次被阻塞（迁移覆盖不到）。

- [ ] **Step 1: 写失败的测试**

在 `api/test/internal/migration/test_memory_owner_nullable_migration.py` 末尾追加：

```python
def test_model_declares_account_column_nullable():
    from internal.model import UserMemory

    assert UserMemory.__table__.c.owner_account_id.nullable is True, (
        "owner_account_id 必须可空（admin 主体该列为 NULL）"
    )


def test_router_ddl_matches_nullable_and_check():
    """新建维度分表的 DDL 必须与迁移同口径，否则新维度重复踩坑。"""
    from pathlib import Path

    router_src = (
        Path(__file__).resolve().parents[3]
        / "internal" / "service" / "embedding_table_router.py"
    ).read_text(encoding="utf-8")

    assert "owner_account_id UUID NOT NULL REFERENCES account(id)" not in router_src, (
        "分表 DDL 仍把 owner_account_id 写死 NOT NULL"
    )
    assert "owner_account_id UUID REFERENCES account(id)" in router_src
    assert "ck_" in router_src and "owner_subject" in router_src, "分表 DDL 必须带主体 CHECK"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/migration/test_memory_owner_nullable_migration.py -q -k "nullable or router" --no-cov -p no:cacheprovider`
Expected: FAIL（模型 `nullable is False`；DDL 仍含 `NOT NULL`）

- [ ] **Step 3: 改模型**

修改 `api/internal/model/knowledge.py` 第 144 行：

```python
    # 归属账号（owner_type='user' 时非空；admin 主体为 NULL，见 P3c-1 迁移 z3c4d5e6f7a8）
    owner_account_id = Column(UUID, ForeignKey("account.id"), nullable=True)
```

- [ ] **Step 4: 改运行时 DDL**

修改 `api/internal/service/embedding_table_router.py` 中 `user_memory_embedding_{dim}` 的建表语句（第 146-159 行）：把 `owner_account_id UUID NOT NULL REFERENCES account(id),` 改为：

```sql
                            owner_account_id UUID REFERENCES account(id),
```

并在 `updated_at TIMESTAMP(0) ...` 之后追加表级 CHECK（注意逗号）：

```sql
                            updated_at TIMESTAMP(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
                            CONSTRAINT ck_{um_table}_owner_subject CHECK (
                                (owner_type = 'user' AND owner_account_id IS NOT NULL)
                                OR (owner_type = 'admin' AND owner_admin_user_id IS NOT NULL)
                            )
```

> 注：该 DDL 是 f-string，`{um_table}` 会被正常插值；`ck_{um_table}_owner_subject` 与迁移 `_check_name()` 同名，保证存量/新建两路约束名一致。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/migration/ -q --no-cov -p no:cacheprovider`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add api/internal/model/knowledge.py api/internal/service/embedding_table_router.py api/test/internal/migration/test_memory_owner_nullable_migration.py
git commit -m "feat(memory): make owner_account_id nullable in model and runtime ddl"
```

---

## Task 3: `_upsert_vector` 解除 admin 跳过

**Files:**
- Modify: `api/internal/service/memory/ledger_writer.py:861-872`（跳过分支）与 `:1011`（owner_id 绑定）
- Test: `api/test/internal/service/memory/test_ledger_writer_admin_subject.py`

**背景**：`_upsert_vector` 现在把「`owner_account_id is None`」等同于「主体非法」而跳过。解阻塞后必须改为：**主体无法解析**才跳过；`owner_type='admin'` 是合法主体，应正常写入（`owner_account_id` 列置 NULL）。

- [ ] **Step 1: 写失败的测试**

创建 `api/test/internal/service/memory/test_ledger_writer_admin_subject.py`：

```python
"""写入侧 admin 主体判别性用例（ADMIN-P3c-1）。

不变量：
1. admin 主体必须能写入 PG 投影行（owner_account_id 为 NULL，admin_user 列有值）；
2. admin 主体写入的 Neo4j 归属属性必须是 admin_user_id（+ agent_id），**不含 user_id**；
3. 用户主体行为与改造前逐字节等价（owner_account_id 有值、user_id 属性）；
4. 主体无法解析（非 UUID 的 user_id）仍跳过，不抛错。
"""
from uuid import UUID, uuid4

import pytest

from internal.entity.memory_owner_entity import (
    NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
    MemoryOwnerKey,
)
from internal.service.memory.ledger_writer import LedgerWriter


class _FakeResult:
    def __init__(self, rows, rowcount=1):
        self._rows = rows
        # UPDATE/DELETE 路径读 rowcount（invalidate_agent_curated 依赖它判断是否有权限）
        self.rowcount = rowcount

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    def __init__(self):
        self.added = []
        self.executed = []
        self.committed = 0
        self.rolled_back = 0
        self.flushed = 0
        self.select_results = {}

    def execute(self, sql, params=None):
        sql_str = str(sql)
        self.executed.append((sql_str, params))
        for frag, rows in self.select_results.items():
            if frag in sql_str:
                return _FakeResult(rows)
        return _FakeResult([])

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushed += 1

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


class _FakeDB:
    def __init__(self):
        self.session = _FakeSession()


class _StubRouter:
    def resolve_system_default_dimension(self):
        return 1536

    def ensure_tables_for_dimension(self, dimension):
        return True

    def get_user_memory_table_name(self, dimension):
        return f"user_memory_embedding_{dimension}"


def _wire(monkeypatch):
    from internal.service.embedding_table_router import EmbeddingTableRouter

    monkeypatch.setattr(
        EmbeddingTableRouter, "get_instance", staticmethod(lambda db=None: _StubRouter())
    )
    db = _FakeDB()
    db.session.select_results["SELECT id FROM user_memory"] = []
    db.session.select_results["SELECT tablename FROM pg_tables"] = []
    return db


def test_admin_owner_writes_projection_row(monkeypatch):
    """admin 主体：投影行必须落库（此前会被跳过）。"""
    db = _wire(monkeypatch)
    writer = LedgerWriter(db=db)
    admin_id, agent_id = uuid4(), uuid4()
    node_id = str(uuid4())

    memory_id = writer._upsert_vector(
        point_id=node_id,
        vector=[0.1] * 8,
        payload={"content": "管理员记忆", "event_type": "episode"},
        owner_key=MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id),
    )

    assert memory_id is not None, "admin 主体不得被跳过"
    assert len(db.session.added) == 1
    added = db.session.added[0]
    assert added.owner_type == "admin"
    assert added.owner_account_id is None
    assert added.owner_admin_user_id == admin_id
    assert added.owner_agent_id == agent_id

    insert_execs = [
        (sql, params)
        for sql, params in db.session.executed
        if "INSERT INTO user_memory_embedding_" in sql
    ]
    assert len(insert_execs) == 1
    insert_params = insert_execs[0][1]
    assert insert_params["owner_id"] is None, "admin 主体的 owner_account_id 绑定必须为 None"
    assert insert_params["owner_type"] == "admin"
    assert insert_params["owner_admin_user_id"] == admin_id
    assert insert_params["owner_agent_id"] == agent_id


def test_admin_level_owner_writes_sentinel_agent(monkeypatch):
    """管理员级（无 agent）：agent_id 列仍为 NULL，Neo4j 侧才写哨兵。"""
    db = _wire(monkeypatch)
    writer = LedgerWriter(db=db)
    admin_id = uuid4()

    memory_id = writer._upsert_vector(
        point_id=str(uuid4()),
        vector=[0.1] * 8,
        payload={"content": "管理员级", "event_type": "episode"},
        owner_key=MemoryOwnerKey.for_admin(admin_id),
    )

    assert memory_id is not None
    added = db.session.added[0]
    assert added.owner_admin_user_id == admin_id
    assert added.owner_agent_id is None


def test_user_owner_still_writes_account_column(monkeypatch):
    db = _wire(monkeypatch)
    writer = LedgerWriter(db=db)
    account_id = uuid4()

    memory_id = writer._upsert_vector(
        point_id=str(uuid4()),
        vector=[0.1] * 8,
        payload={"content": "用户记忆", "user_id": str(account_id), "event_type": "episode"},
    )

    assert memory_id is not None
    added = db.session.added[0]
    assert added.owner_type == "user"
    assert added.owner_account_id == account_id
    assert isinstance(added.owner_account_id, UUID)


def test_unparsable_user_id_still_skipped(monkeypatch):
    """非 UUID 的 user_id（历史脏值）无法解析主体 → 跳过不抛。"""
    db = _wire(monkeypatch)
    writer = LedgerWriter(db=db)

    memory_id = writer._upsert_vector(
        point_id=str(uuid4()),
        vector=[0.1] * 8,
        payload={"content": "x", "user_id": "platform", "event_type": "episode"},
    )

    assert memory_id is None
    assert db.session.added == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/memory/test_ledger_writer_admin_subject.py -q --no-cov -p no:cacheprovider`
Expected: FAIL（`test_admin_owner_writes_projection_row` 断言 `memory_id is not None` 失败——当前被跳过）

- [ ] **Step 3: 改 `_upsert_vector` 主体校验分支**

修改 `api/internal/service/memory/ledger_writer.py`：把第 861-872 行

```python
        # 旧列 owner_account_id 仍是 NOT NULL 外键，读路径依赖它
        owner_account_id: Optional[UUID] = (
            owner_key_obj.owner_account_id if owner_key_obj is not None else None
        )

        if owner_account_id is None:
            # 外键约束要求非空，无法写入，降级跳过
            logger.warning(
                "_upsert_vector: owner_account_id 为空，跳过 pgvector 写入 point_id=%s",
                point_id,
            )
            return None
```

替换为：

```python
        # 主体必须可解析；未解析即跳过（与既有「非 UUID user_id → 跳过」行为一致）。
        # 注意：admin 主体 owner_account_id 为 None 是**合法**的（P3c-1 起
        # owner_account_id 改可空，由 ck_*_owner_subject 保证按主体类型非空）。
        if owner_key_obj is None:
            logger.warning(
                "_upsert_vector: 主体无法解析，跳过 pgvector 写入 point_id=%s",
                point_id,
            )
            return None

        owner_account_id: Optional[UUID] = owner_key_obj.owner_account_id
```

- [ ] **Step 4: 改 INSERT 的 owner_id 绑定**

同文件第 1011 行 `"owner_id": str(owner_account_id),` 改为：

```python
                    "owner_id": str(owner_account_id) if owner_account_id is not None else None,
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/memory/test_ledger_writer_admin_subject.py test/internal/service/memory/test_ledger_writer_owner.py -q --no-cov -p no:cacheprovider`
Expected: PASS（新增 admin 用例 + 既有用户用例均绿）

- [ ] **Step 6: 提交**

```bash
git add api/internal/service/memory/ledger_writer.py api/test/internal/service/memory/test_ledger_writer_admin_subject.py
git commit -m "feat(memory): stop skipping pgvector write for admin subjects"
```

---

## Task 4: Neo4j 写路径主体化（episode / entity / access / cooccur）

**Files:**
- Modify: `api/internal/service/memory/ledger_writer.py`（公开方法签名 + 4 段 Cypher + 2 处补建实体调用）
- Test: `api/test/internal/service/memory/test_ledger_writer_admin_subject.py`（追加）

**背景**：写路径把 `event.user_id` 当属性值硬编码。主体化后：用户态产出 `{"user_id": <原字符串>}`（**逐字节等价，且不要求可解析为 UUID**）；admin 态产出 `{"admin_user_id": ..., "agent_id": ...}`（管理员级写哨兵）。

**设计（零变化安全）**：新增两个模块级纯函数，用户/历史脏值走 fallback，绝不因解析失败而改变行为：

```python
def _owner_props(owner: Optional[MemoryOwnerKey], fallback_user_id: str) -> dict:
    """归属属性字典：有主体键走访问器，否则回落到历史 user_id 字面量。"""
    if owner is not None:
        return owner.neo4j_props()
    return {"user_id": fallback_user_id}


def _owner_pattern(props: dict) -> str:
    """把归属属性拼成 Cypher 模式片段（`a: $a, b: $b`）。"""
    return ", ".join(f"{name}: ${name}" for name in props)
```

- [ ] **Step 1: 写失败的测试**

在 `api/test/internal/service/memory/test_ledger_writer_admin_subject.py` 末尾追加：

```python
class _CapturingSession:
    def __init__(self, sink):
        self._sink = sink

    def run(self, cypher, params=None, **kwargs):
        self._sink.append((cypher, params if params is not None else kwargs))
        return self

    def single(self):
        return None


class _CapturingDriver:
    def __init__(self):
        self.calls = []

    def session(self):
        return _CapturingSession(self.calls)


def _writer_with_driver(monkeypatch, driver=None):
    db = _wire(monkeypatch)
    writer = LedgerWriter(db=db)
    monkeypatch.setattr(writer, "_get_driver", lambda: driver or _CapturingDriver())
    return writer


def test_episode_node_user_owner_keeps_user_id_prop(monkeypatch):
    """用户态逐字节等价：属性名仍是 user_id，值仍是原始字符串。"""
    from datetime import UTC, datetime
    from internal.model.memory_models import EventSource, MemoryEvent

    writer = _writer_with_driver(monkeypatch)
    driver = writer._get_driver()
    event = MemoryEvent(content="内容", source=EventSource.USER_MESSAGE, user_id="acc-raw")
    writer._create_episode_node(driver, event, datetime.now(UTC))

    cypher, params = driver.calls[0]
    assert "user_id" in params["owner_props"]
    assert params["owner_props"]["user_id"] == "acc-raw"
    assert "user_id: $user_id" not in cypher, "归属改由 owner_props 注入"


def test_episode_node_admin_owner_writes_admin_props(monkeypatch):
    from datetime import UTC, datetime
    from internal.model.memory_models import EventSource, MemoryEvent

    writer = _writer_with_driver(monkeypatch)
    driver = writer._get_driver()
    admin_id, agent_id = uuid4(), uuid4()
    event = MemoryEvent(content="内容", source=EventSource.USER_MESSAGE, user_id="ignored")
    writer._create_episode_node(
        driver, event, datetime.now(UTC),
        owner=MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id),
    )

    _cypher, params = driver.calls[0]
    props = params["owner_props"]
    assert props["admin_user_id"] == str(admin_id)
    assert props["agent_id"] == str(agent_id)
    assert "user_id" not in props, "admin 节点不得带 user_id（属性分离）"


def test_merge_entity_pattern_includes_owner(monkeypatch):
    """MERGE 键必须含归属，否则不同主体同名实体被合并（跨主体污染）。"""
    from datetime import UTC, datetime

    writer = _writer_with_driver(monkeypatch)
    driver = writer._get_driver()
    admin_id = uuid4()
    writer._merge_entity_node(
        driver, {"name": "实体", "type": "t", "summary": ""}, datetime.now(UTC),
        owner=MemoryOwnerKey.for_admin(admin_id),
    )

    cypher, params = driver.calls[0]
    assert "MERGE (e:Entity:MemoryNode {name: $name" in cypher
    assert "admin_user_id: $admin_user_id" in cypher
    assert "agent_id: $agent_id" in cypher
    assert params["admin_user_id"] == str(admin_id)
    assert params["agent_id"] == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL
    assert "user_id" not in params


def test_merge_entity_user_owner_keeps_user_pattern(monkeypatch):
    from datetime import UTC, datetime

    writer = _writer_with_driver(monkeypatch)
    driver = writer._get_driver()
    writer._merge_entity_node(
        driver, {"name": "实体", "type": "t", "summary": ""}, datetime.now(UTC),
        fallback_user_id="acc-raw",
    )

    cypher, params = driver.calls[0]
    assert "user_id: $user_id" in cypher
    assert params["user_id"] == "acc-raw"


def test_increment_entity_access_admin_owner(monkeypatch):
    from datetime import UTC, datetime

    writer = _writer_with_driver(monkeypatch)
    driver = writer._get_driver()
    admin_id = uuid4()
    writer._increment_entity_access(
        driver, "实体", datetime.now(UTC),
        owner=MemoryOwnerKey.for_admin(admin_id),
    )

    cypher, params = driver.calls[0]
    assert "MATCH (e:Entity {name: $name" in cypher
    assert "admin_user_id: $admin_user_id" in cypher
    assert params["admin_user_id"] == str(admin_id)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/memory/test_ledger_writer_admin_subject.py -q -k "episode or merge or access" --no-cov -p no:cacheprovider`
Expected: FAIL（`TypeError: _create_episode_node() got an unexpected keyword argument 'owner'`）

- [ ] **Step 3: 加模块级纯函数**

在 `api/internal/service/memory/ledger_writer.py` 顶部（`logger = logging.getLogger(__name__)` 之后）加入 `_owner_props` / `_owner_pattern`（代码见本节「设计」）。

- [ ] **Step 4: 改 `_create_episode_node`**

签名改为：

```python
    def _create_episode_node(
        self,
        driver,
        event: MemoryEvent,
        now: datetime,
        owner: Optional[MemoryOwnerKey] = None,
        content_override: Optional[str] = None,
        explicit_detection: Optional[ExplicitDetectionResult] = None,
    ) -> str:
```

Cypher 去掉 `user_id: $user_id,` 一行，并在 `})` 之后、`RETURN` 之前加 `SET e += $owner_props`：

```cypher
        CREATE (e:Episode:MemoryNode {
            node_id: $node_id,
            id: $node_id,
            content: $content,
            summary: $summary,
            source: $source,
            tier: 'hot',
            storage_tier: 'hot',
            memory_type: 'episode',
            created_at: $now,
            updated_at: $now,
            last_accessed: $now,
            access_count: 0,
            is_active: true,
            session_id: $session_id,
            explicit_category: $explicit_category,
            explicit_polarity: $explicit_polarity,
            explicit_subject: $explicit_subject
        })
        SET e += $owner_props
        RETURN e.node_id AS node_id
```

params 去掉 `"user_id": event.user_id`，加 `"owner_props": _owner_props(owner, event.user_id)`。

- [ ] **Step 5: 改 `_merge_entity_node`**

签名第 4 参由 `user_id: str` 改为：

```python
        owner: Optional[MemoryOwnerKey] = None,
        fallback_user_id: str = "",
    ) -> str:
```

方法体开头计算 `props = _owner_props(owner, fallback_user_id)`，Cypher 改为：

```python
        cypher = f"""
        MERGE (e:Entity:MemoryNode {{name: $name, {_owner_pattern(props)}}})
        ON CREATE SET e.node_id = $node_id,
                      e.id = $node_id,
                      e.type = $type,
                      e.summary = $summary,
                      e.tier = 'hot',
                      e.storage_tier = 'hot',
                      e.memory_type = 'entity',
                      e.created_at = $now,
                      e.updated_at = $now,
                      e.last_accessed = $now,
                      e.access_count = 0,
                      e.is_active = true
        ON MATCH SET e.last_accessed = $now,
                     e.access_count = e.access_count + 1
        RETURN e.node_id AS node_id
        """
```

params：删 `"user_id": user_id`，改为 `**props`（`props` 的键即绑定名，与模式片段一致）。

- [ ] **Step 6: 改 `_increment_entity_access` 与 `_increment_cooccurrence`**

两者签名同法改为 `owner: Optional[MemoryOwnerKey] = None, fallback_user_id: str = ""`，Cypher 中的 `user_id: $user_id` 换成 `{_owner_pattern(props)}`，params 用 `**props`。`_increment_cooccurrence` 的两个 MATCH 都要替换。

- [ ] **Step 7: 改调用点（`_write_full_path_impl` / `_write_summary_path_impl` / `_write_stats_path_impl`）**

三个公开方法与其 `_impl` 均加参数 `owner_key: Optional[MemoryOwnerKey] = None`；`_impl` 内开头：

```python
        owner = owner_key
```

随后把现有调用改为传 `owner=` 与 `fallback_user_id=`：
- `_create_episode_node(driver, event, now, owner=owner, explicit_detection=...)`
- `_merge_entity_node(driver, ent, now, owner=owner, fallback_user_id=event.user_id)`
- 补建主体/客体实体两处（原第 208-213 / 225-230 行）同法
- `_increment_entity_access(... owner=owner, fallback_user_id=event.user_id)`（原第 518 行）
- `_increment_cooccurrence(... owner=owner, fallback_user_id=event.user_id)`（原第 530-536 行）

- [ ] **Step 8: 更新受影响的既有断言**

Run: `cd api && python -m pytest test/internal/service/memory/ test/internal/service/test_ledger_writer*.py -q --no-cov -p no:cacheprovider`

若既有用例断言 Cypher **文本**含 `user_id: $user_id`，改为断言**有效参数**（`params["owner_props"]["user_id"] == <原值>` 或 `params["user_id"] == <原值>`）。不得删除判别力——只换断言目标。

- [ ] **Step 9: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/memory/ -q --no-cov -p no:cacheprovider`
Expected: PASS

- [ ] **Step 10: 提交**

```bash
git add api/internal/service/memory/ledger_writer.py api/test/
git commit -m "feat(memory): subjectize neo4j write path for episode/entity/access"
```

---

## Task 5: `agent_curated` 路径主体化

**Files:**
- Modify: `api/internal/service/memory/ledger_writer.py:1095-1230` 起（`write_agent_curated` / `invalidate_agent_curated`）
- Test: `api/test/internal/service/memory/test_ledger_writer_admin_subject.py`（追加）

**背景**：`write_agent_curated(account_id: UUID, ...)` 在 Neo4j 侧硬编码 `user_id: str(account_id)`（PG 侧已走 `for_user`）——两条路径主体语义分叉。主体化后统一走 `owner_key`，并新增 admin 入口（供 P3c-2 接线）。

- [ ] **Step 1: 写失败的测试**

在 `api/test/internal/service/memory/test_ledger_writer_admin_subject.py` 末尾追加：

```python
def test_write_agent_curated_user_owner_uses_user_id_prop(monkeypatch):
    """用户态：Neo4j 属性仍是 user_id（逐字节等价）。"""
    driver = _CapturingDriver()
    writer = _writer_with_driver(monkeypatch, driver)
    # 抽出的可替换向量入口：避免单测依赖真实 embedding 服务/网络
    monkeypatch.setattr(writer, "_embed_content", lambda content: [0.1] * 8)
    monkeypatch.setattr(writer, "_upsert_vector", lambda **kw: str(kw["forced_memory_id"]))

    account_id = uuid4()
    result = writer.write_agent_curated(
        owner_key=MemoryOwnerKey.for_user(account_id), content="内容"
    )

    assert result is not None
    cypher, params = driver.calls[0]
    assert "user_id: $user_id" in cypher
    assert params["user_id"] == str(account_id)
    assert "admin_user_id" not in params


def test_write_agent_curated_admin_owner_writes_admin_props(monkeypatch):
    driver = _CapturingDriver()
    writer = _writer_with_driver(monkeypatch, driver)
    monkeypatch.setattr(writer, "_embed_content", lambda content: [0.1] * 8)
    monkeypatch.setattr(writer, "_upsert_vector", lambda **kw: str(kw["forced_memory_id"]))

    admin_id = uuid4()
    result = writer.write_agent_curated(
        owner_key=MemoryOwnerKey.for_admin(admin_id), content="管理员记忆"
    )

    assert result is not None
    cypher, params = driver.calls[0]
    assert "admin_user_id: $admin_user_id" in cypher
    assert "user_id: $user_id" not in cypher
    assert params["admin_user_id"] == str(admin_id)
    assert "user_id" not in params


def test_write_agent_curated_no_embedding_returns_none(monkeypatch):
    """向量生成失败/为空：不写投影（不变量：不得造纯 DB 孤儿行）。"""
    driver = _CapturingDriver()
    writer = _writer_with_driver(monkeypatch, driver)
    monkeypatch.setattr(writer, "_embed_content", lambda content: [])

    assert writer.write_agent_curated(
        owner_key=MemoryOwnerKey.for_user(uuid4()), content="内容"
    ) is None


def test_invalidate_agent_curated_admin_owner(monkeypatch):
    driver = _CapturingDriver()
    writer = _writer_with_driver(monkeypatch, driver)

    admin_id = uuid4()
    writer.invalidate_agent_curated(
        owner_key=MemoryOwnerKey.for_admin(admin_id), memory_id="m-1"
    )

    cypher, params = driver.calls[0]
    assert "admin_user_id: $admin_user_id" in cypher
    assert "user_id: $user_id" not in cypher
    assert params["admin_user_id"] == str(admin_id)
```

> **关于 embedding 获取**：`write_agent_curated` 现内部直接 `injector.get(EmbeddingsService)`（第 1189-1193 行）。实施时把它抽为可替换的私有方法：

```python
    def _embed_content(self, content: str) -> list[float]:
        """内容向量（抽为独立方法便于测试替换；失败返回空列表）。"""
        try:
            from internal.service.embeddings_service import EmbeddingsService
            from app.http.app import injector

            return injector.get(EmbeddingsService).embeddings.embed_query(content) or []
        except Exception:
            logger.warning("write_agent_curated: 向量生成失败", exc_info=True)
            return []
```

原内联 try/except 块替换为 `embedding = self._embed_content(content)`，后续 `if not embedding:` 分支保留。**这样单测可替换 `_embed_content`，不依赖真实模型。**

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/memory/test_ledger_writer_admin_subject.py -q -k "agent_curated" --no-cov -p no:cacheprovider`
Expected: FAIL（`write_agent_curated` 无 `owner_key` 参数）

- [ ] **Step 3: 改 `write_agent_curated`**

签名改为：

```python
    def write_agent_curated(
        self,
        *,
        owner_key: MemoryOwnerKey,
        content: str,
        memory_type: str = "preference",
        metadata: Optional[dict] = None,
    ) -> Optional[str]:
```

Neo4j Cypher 改为（去 `user_id: $user_id`，用 `_owner_pattern`）：

```python
                props = owner_key.neo4j_props()
                cypher = f"""
                CREATE (e:Episode:MemoryNode {{
                    node_id: $node_id,
                    {_owner_pattern(props)},
                    content: $content,
                    summary: $content,
                    created_at: datetime(),
                    storage_tier: 'hot',
                    source: 'agent_curated',
                    memory_type: $memory_type
                }})
                RETURN e.node_id AS node_id
                """
                with driver.session() as session:
                    session.run(cypher, {
                        "node_id": str(memory_id),
                        "content": content,
                        "memory_type": memory_type,
                        **props,
                    })
```

PG 侧 `owner_key=MemoryOwnerKey.for_user(account_id)` 改为 `owner_key=owner_key`；`curated_metadata["user_id"]` 改为按主体写入（user 写 `str(owner_key.owner_account_id)`，admin 不写 `user_id` 键）。

- [ ] **Step 4: 改 `invalidate_agent_curated`**

签名同法改为 `*, owner_key: MemoryOwnerKey, memory_id: str, action: str = "remove"`；Neo4j `MATCH (e:Episode {node_id: $node_id, user_id: $user_id})` 改为 `MATCH (e:Episode {{node_id: $node_id, {_owner_pattern(owner_key.neo4j_props())}}})` + `**owner_key.neo4j_props()`；PG `UPDATE ... WHERE owner_account_id = :account_id` 改为用 `owner_key.pg_sql_predicate("user_memory")` 产出的谓词（user 态含 `owner_type='user' AND owner_account_id=...`；admin 态含 admin 列）。

- [ ] **Step 5: 更新既有调用方与测试**

Run: `cd api && python -m pytest test/internal/service/memory/ test/internal/core/tools/ -q --no-cov -p no:cacheprovider`

`write_agent_curated` / `invalidate_agent_curated` 的既有调用方（`agent_memory_tool.py`）需改为传 `owner_key=MemoryOwnerKey.for_user(account_id)`。**这是签名变更的必然连带改动**，一并修好，不得留下调用点报错。

- [ ] **Step 6: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/memory/ test/internal/core/tools/ -q --no-cov -p no:cacheprovider`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add api/internal/service/memory/ledger_writer.py api/internal/service/memory/agent_memory_tool.py api/test/
git commit -m "feat(memory): subjectize agent-curated write path"
```

---

## Task 6: 真库 / 真图守卫 + 全量回归

**Files:**
- Modify: `api/test/internal/migration/test_memory_owner_backfill_consistency.py`（补可空/CHECK 断言）
- Test: 复用后台真库 PG + 真图 Neo4j

**背景**：单测用替身，绕过了「约束是否真解除」这一层。必须有真库断言，否则「迁移写了但没生效」无从发现。

- [ ] **Step 1: 写真库守卫**

在 `api/test/internal/migration/test_memory_owner_backfill_consistency.py` 追加。**必须复用该文件既有的 `engine` fixture**（`_engine()` + `pytest.skip`），不要自造连接助手：

```python
def test_owner_account_id_is_nullable_with_subject_check(engine):
    """真库：owner_account_id 必须可空，且存在按主体类型的 CHECK。"""
    from sqlalchemy import text

    with engine.connect() as conn:
        nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'user_memory' AND column_name = 'owner_account_id'"
            )
        ).scalar()
        assert nullable == "YES", "owner_account_id 在真库仍为 NOT NULL"

        check = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_user_memory_owner_subject'"
            )
        ).scalar()
        assert check is not None, "缺少 ck_user_memory_owner_subject 约束"
        assert "owner_admin_user_id" in check


def test_embedding_shards_have_subject_check(engine):
    """分表同样必须有 CHECK（动态表名，最易漏）。"""
    from sqlalchemy import text

    with engine.connect() as conn:
        with engine.begin() as tx:
            shards = _shard_tables(tx)
        assert shards, "未发现任何向量分表"
        with engine.connect() as conn2:
            for table in shards:
                check = conn2.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname = :name"
                    ),
                    {"name": f"ck_{table}_owner_subject"},
                ).scalar()
                assert check is not None, f"{table} 缺少主体 CHECK"


def test_admin_subject_row_is_insertable(engine):
    """端到端：admin 主体行必须能真正落库（CHECK 不误伤 admin）。

    注意 owner_admin_user_id 有 FK → admin_user(id)，探针必须用**真实存在**的
    admin_user id；无管理员数据时跳过（不制造假绿）。
    """
    from uuid import uuid4

    from sqlalchemy import text

    with engine.begin() as conn:
        admin_id = conn.execute(
            text("SELECT id FROM admin_user ORDER BY created_at LIMIT 1")
        ).scalar()
        if admin_id is None:
            pytest.skip("无 admin_user 数据，跳过 admin 落库探针")

        probe_id = uuid4()
        conn.execute(
            text(
                "INSERT INTO user_memory (id, owner_type, owner_account_id, "
                "owner_admin_user_id, memory_type, content, status, scope) "
                "VALUES (:id, 'admin', NULL, :admin_id, 'preference', 'probe', "
                "'active', 'user_memory')"
            ),
            {"id": str(probe_id), "admin_id": str(admin_id)},
        )
        stored = conn.execute(
            text("SELECT owner_account_id FROM user_memory WHERE id = :id"),
            {"id": str(probe_id)},
        ).scalar()
        assert stored is None, "admin 行的 owner_account_id 必须为 NULL"
        conn.execute(
            text("DELETE FROM user_memory WHERE id = :id"), {"id": str(probe_id)}
        )


def test_user_row_requires_account_column(engine):
    """CHECK 反向：owner_type='user' 但 account 为 NULL 必须被拒绝。"""
    from uuid import uuid4

    from sqlalchemy import text

    with engine.begin() as conn:
        try:
            conn.execute(
                text(
                    "INSERT INTO user_memory (id, owner_type, owner_account_id, "
                    "memory_type, content, status, scope) "
                    "VALUES (:id, 'user', NULL, 'preference', 'bad', 'active', 'user_memory')"
                ),
                {"id": str(uuid4())},
            )
            raised = False
        except Exception:
            raised = True
        assert raised, "user 主体缺 account 应被 CHECK 拒绝"
```

> **注意**：该文件既有的 `test_only_user_scoped_memory_exists` 断言「无 `owner_type <> 'user'` 行」——本阶段仍成立（admin 无生产调用方）。探针在 `engine.begin()` 事务内**先插后删**，不留残留；若断言失败需查明是否真有残留行。

- [ ] **Step 2: 运行真库守卫**

Run: `cd api && python -m pytest test/internal/migration/test_memory_owner_backfill_consistency.py -q --no-cov -p no:cacheprovider`
Expected: PASS（0 skipped，或明确输出 skip 原因）

- [ ] **Step 3: 真 Neo4j 验证 admin 写入属性**

```bash
docker exec llmops-neo4j cypher-shell -u neo4j -p openagent123 \
  "CREATE (e:Episode:MemoryNode {node_id: 'P3C1_PROBE', admin_user_id: 'probe-admin', agent_id: '__admin_level__'}) RETURN e.node_id;"
docker exec llmops-neo4j cypher-shell -u neo4j -p openagent123 \
  "MATCH (e:Episode {node_id: 'P3C1_PROBE'}) RETURN e.admin_user_id AS admin, e.agent_id AS agent, e.user_id AS user_id;"
docker exec llmops-neo4j cypher-shell -u neo4j -p openagent123 \
  "MATCH (e:Episode {node_id: 'P3C1_PROBE'}) DELETE e RETURN count(*) AS deleted;"
```
Expected: `user_id` 为 `null`（属性分离）；`agent` = `__admin_level__`；删除返回 1；随后 `MATCH ... RETURN count(e)` = 0。

- [ ] **Step 4: 全量回归**

Run: `cd api && python -m pytest -q --no-header --no-cov 2>&1 | Select-String -Pattern "passed|failed|error" | Select-Object -Last 5`
Expected: 全部通过（既有环境性失败需逐条确认与本改动无关）

- [ ] **Step 5: 提交**

```bash
git add api/test/internal/migration/test_memory_owner_backfill_consistency.py
git commit -m "test(memory): guard nullable owner column against live pg"
```

---

## Task 7: 文档同步

**Files:**
- Modify: `docs/prd/memory-system/02-storage-and-retrieval.md`
- Modify: `docs/prd/execution-roadmap.md`

- [ ] **Step 1: 关闭「缺口二」**

在 `02-storage-and-retrieval.md` 的「缺口二：PG 侧 `owner_account_id` NOT NULL 阻塞 admin 记忆落库」改为「缺口二（已修复，2026-09-19）」，写明：迁移 `z3c4d5e6f7a8` 将主表与全部分表 `owner_account_id` 改可空，并以 `ck_<table>_owner_subject` 保证按主体类型非空；`_upsert_vector` 不再对 admin 主体跳过。

- [ ] **Step 2: 更新「缺口十六」**

`_delete_all_pgvector_rows` 条目补注：解阻塞后 admin 行可存在，该方法**仅按 `owner_account_id` 过滤会漏删 admin 行**——标记为 P3c-2（治理主体化）待修，不得沿用「无 admin 写入路径所以无影响」的旧措辞。

- [ ] **Step 3: 更新 roadmap**

把 `execution-roadmap.md` 的「已知缺口」条数与清单同步（移除已修复的缺口二，补「写入侧已主体化但调用方未接线」的状态说明）。并补一节记录本阶段（`ADMIN-P3c-1`）交付物与验证结果。

- [ ] **Step 4: 提交**

```bash
git add docs/prd/memory-system/02-storage-and-retrieval.md docs/prd/execution-roadmap.md
git commit -m "docs(memory): record p3c-1 write-path subjectization"
```

---

## 自检清单（执行者收尾逐项打勾）

- [ ] 新迁移是**唯一 head**（`down_revision='y2b3c4d5e6f8'`），未产生第二 head
- [ ] 主表 + **全部**已存在分表都改了可空并加了 CHECK；运行时 DDL 也同步（新建维度不再踩坑）
- [ ] CHECK 语义正确：`user ⇒ account 非空` / `admin ⇒ admin_user 非空`
- [ ] `_upsert_vector` 的跳过条件已从「account 为空」改为「主体无法解析」
- [ ] admin 主体的 `owner_id` 绑定为 `None`（不是字符串 `"None"`）
- [ ] 用户态 Neo4j 属性**逐字节等价**（`user_id` = 原始字符串），且**不要求可解析为 UUID**
- [ ] admin 节点**不含** `user_id` 属性（属性分离）；管理员级 `agent_id` 写哨兵
- [ ] `MERGE`/`MATCH` 的归属属性都在**模式内**（防跨主体合并）
- [ ] `write_agent_curated` / `invalidate_agent_curated` 签名变更后的**所有调用方**已同步（无残留报错）
- [ ] 真库守卫证明「约束真解除且 admin 行可插入」；探针清理干净（leftover=0）
- [ ] 全量回归通过
- [ ] 文档缺口二已关闭、缺口十六措辞已更正
- [ ] 运行 `python -m graphify update .` 保持知识图谱最新

---

## 附：本阶段与后续阶段的边界（勿越界）

| 阶段 | 范围 | 本阶段是否覆盖 |
| --- | --- | --- |
| **P3c-1（本计划）** | DB 解阻塞 + 写入侧（PG/Neo4j）主体化 | ✅ |
| P3c-2 | **调用方接线**：`AdminAgentChatService` 召回/写入（镜像用户端）、`MemoryWriteService` 增 `owner_key` 入口、治理层 `MemoryGovernor` 主体化（缺口十六/九）、admin 巩固任务 | ❌ 另写 |
| P3c-3 | 配置与存储：`DigestConfig` 死副本（C2）、`ColdStorageManager.list_user_archives`（C4）、冷存储主体化、Redis 键分隔约定 | ❌ 另写 |

> **诚实披露**：本阶段完成后，admin 写入**能力**已具备（`_upsert_vector` / Neo4j 写路径接受 `MemoryOwnerKey.for_admin(...)`），但**仍无生产调用方**（admin 链路对记忆零接线）——按仓库「接线审查」规则，这属于「已提供能力、未接入」，**不得表述为「admin 记忆已可用」**。真正的端到端可达由 P3c-2 完成。
