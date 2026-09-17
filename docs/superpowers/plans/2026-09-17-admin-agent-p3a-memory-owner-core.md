# 管理端 Agent 治理 P3a（记忆主体抽象内核 + 存量迁移）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给记忆系统引入「主体类型」维度（`owner_type` = user/admin + `owner_agent_id`），让归属从"硬编码 account"变为可表达管理员与 Agent；**本计划只做双写与存量迁移，读路径一律不变，行为零变化**。

**Architecture:** 对齐知识库已验证的三字段模式（`knowledge_base.owner_account_id` + `owner_admin_user_id` + `knowledge_scope`），为 `user_memory` 及向量分表补 `owner_type` / `owner_admin_user_id` / `owner_agent_id`，并派生一个**跨层统一的主体键字符串** `owner_key`（`user:{account_uuid}` / `admin:{admin_uuid}` / `admin:{admin_uuid}:{agent_uuid}`）供 Neo4j / Redis / 冷存储使用。写入侧**双写**（旧 `owner_account_id`/`user_id` 与新字段同时写），读取侧**暂不切换**——这样存量行为可逐字节验证不变，把风险锁在写入路径。

**Tech Stack:** Python 3.12 / SQLAlchemy(asyncpg) / Alembic / Pydantic v2 / Neo4j / Redis / pytest

**依据规格：** [admin-agent-governance-design.md](../specs/2026-09-15-admin-agent-governance-design.md) §8（记忆主体统一抽象）、§3 L1「记忆：按 admin_user_id + agent_id 隔离」、§14 P3、§10.2（表清单）。

---

## 范围边界（已与用户确认）

| 项 | 决定 |
|---|---|
| `agent_id` 落点 | **新增 `owner_agent_id` 列**（可空 FK `admin_agent.id`），主体键含 `admin:{admin_uuid}:{agent_uuid}` |
| 本计划做 | 主体键值对象、模型四字段、迁移、**写入双写**、存量迁移（全标 `owner_type='user'`） |
| 本计划**不做**（属 P3b） | 读路径切换为 `owner_key`、Neo4j/Redis/冷存储键改造、服务层签名统一、admin Agent 记忆**读取**接入 |
| 既有不一致 C1–C4 | 不在本计划修（P3b 单独处理，避免与"行为零变化"目标冲突） |
| 前端 / 预算闸门 / MCP | 不属 P3 |

> **为什么先双写不切读**：规格要求"存量全标 `owner_type='user'`，**行为零变化**"。只有读路径不动，才能用现有全量回归逐字节证明"零变化"；读切换与写改造混在一个计划里，一旦回归失败无法区分归因。

---

## 本机实测事实（写计划前已核对，非推测）

| 事实 | 值 / 证据 |
| --- | --- |
| 迁移当前 **单 head** | `x1a2b3c4d5e7`（AST 遍历 155 个迁移，唯一 head，已 git 跟踪） |
| `user_memory` 字段 | `id` / **`owner_account_id`(UUID, FK account.id, NOT NULL)** / `memory_type` / `content` / `confidence` / `status` / `created_from` / `metadata_`(列名 `metadata`, JSONB) / `embedding_node_id` / `embedding`(Vector(1536)) / `scope`(server_default `'global'`) / `source_conversation_ids` / `last_used_at` / `updated_at` / `created_at`（[knowledge.py:132-155](../../api/internal/model/knowledge.py#L132-L155)） |
| `user_memory` 索引 | `pk_user_memory_id`、`user_memory_owner_type_idx(owner_account_id, memory_type)`、`user_memory_status_idx(status)`（[knowledge.py:134-138](../../api/internal/model/knowledge.py#L134-L138)） |
| 向量分表 | `user_memory_embedding_{dim}`，字段 `id` / `memory_id`(FK user_memory CASCADE) / **`owner_account_id`(UUID NOT NULL FK account)** / `embedding` / `embedding_node_id` / `created_at` / `updated_at`；索引 `{t}_owner_idx` / `{t}_memory_idx` / `{t}_memory_id_uidx`(UNIQUE) / `{t}_embedding_hnsw_idx`（[embedding_table_router.py:146-174](../../api/internal/service/embedding_table_router.py#L146-L174)） |
| 向量分表建表入口 | `EmbeddingTableRouter.ensure_tables_for_dimension()`（[embedding_table_router.py:114-217](../../api/internal/service/embedding_table_router.py#L114-L217)）；维度 1–2000，兜底 1536 |
| 写入落库点 | `LedgerWriter._upsert_vector` 新建 `UserMemory(...)`（[ledger_writer.py:950-962](../../api/internal/service/memory/ledger_writer.py#L950-L962)）；`owner_account_id` 来自 `UUID(str(payload["user_id"]))`，**解析失败即跳过写入**（[ledger_writer.py:839-860](../../api/internal/service/memory/ledger_writer.py#L839-L860)） |
| 向量列双写现状 | 基表 `user_memory.embedding` 与分表并存：写分表（[ledger_writer.py:970-985](../../api/internal/service/memory/ledger_writer.py#L970-L985)），三处读基表列（`representation_repulsion.py:182-199`、`entity_resolution.py:241-243`、`consolidation_engine.py:790-793`） |
| `MemoryEvent.user_id` | `str` 字段（Pydantic），语义即 `str(account.id)`（[memory_models.py:244](../../api/internal/model/memory_models.py#L244)） |
| `admin_agent` 表 | 已存在，主键 `id` UUID（P1a 落地），可作 FK 目标 |
| `scope` 字段现状 | 只写不读：仅 `ledger_writer.py:956` 硬编码 `"user_memory"`，默认 `'global'`；**全仓检索链路零过滤** |
| 迁移 head 校验测试 | `test/internal/migration/test_migration_graph_integrity.py`（单 head + 无悬空 `down_revision`） |

---

## 文件结构

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `api/internal/entity/memory_owner_entity.py` | 新建 | `MemoryOwnerType` 枚举 + `MemoryOwnerKey` 值对象（构造/解析/`to_key`/`pg_kwargs`） |
| `api/internal/model/knowledge.py` | 修改 | `UserMemory` 增 `owner_type` / `owner_admin_user_id` / `owner_agent_id` 列 + 索引 |
| `api/internal/service/embedding_table_router.py` | 修改 | 分表 DDL 增三列（新建表用；已存在的表由迁移补列） |
| `api/internal/migration/versions/y2b3c4d5e6f8_add_memory_owner_type.py` | 新建 | 补三列（`user_memory`）+ 存量回填 + 分表补列 + 索引；可逆 |
| `api/internal/service/memory/ledger_writer.py` | 修改 | 写入双写：解析主体键并写三新列（**读路径不动**） |
| `api/internal/config/memory_settings.py` | 修改 | 增 `owner_key` 前缀常量（供 P3b 用，本计划仅落常量与测试） |
| `docs/prd/memory-system/*.md` | 修改 | 记录主体抽象（见 Task 7） |

---

## Task 1: 主体键值对象 `MemoryOwnerKey`

**Files:**
- Create: `api/internal/entity/memory_owner_entity.py`
- Test: `api/test/internal/entity/test_memory_owner_entity.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/entity/test_memory_owner_entity.py`：

```python
"""记忆主体键值对象测试（纯函数，无 IO）。

主体键是跨层（PG/Neo4j/Redis/冷存储）的唯一归属表达，必须可逆、
对非法输入 fail closed，且**用户主体产出与旧行为逐字节一致**
（`user:<account_uuid>` == 旧 `str(account.id)` 的语义对齐）。
"""
from uuid import UUID, uuid4

import pytest

from internal.entity.memory_owner_entity import (
    MemoryOwnerKey,
    MemoryOwnerType,
    MemoryOwnerKeyError,
)


def test_for_user_produces_account_scoped_key():
    account_id = uuid4()
    key = MemoryOwnerKey.for_user(account_id)

    assert key.owner_type is MemoryOwnerType.USER
    assert key.owner_account_id == account_id
    assert key.owner_admin_user_id is None
    assert key.owner_agent_id is None
    assert key.to_key() == f"user:{account_id}"


def test_for_admin_without_agent():
    admin_id = uuid4()
    key = MemoryOwnerKey.for_admin(admin_id)

    assert key.owner_type is MemoryOwnerType.ADMIN
    assert key.owner_account_id is None
    assert key.owner_admin_user_id == admin_id
    assert key.to_key() == f"admin:{admin_id}"


def test_for_admin_with_agent_is_two_level():
    admin_id, agent_id = uuid4(), uuid4()
    key = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id)

    assert key.owner_agent_id == agent_id
    assert key.to_key() == f"admin:{admin_id}:{agent_id}"


def test_to_key_is_stable_for_same_identity():
    account_id = uuid4()
    assert MemoryOwnerKey.for_user(account_id).to_key() == MemoryOwnerKey.for_user(account_id).to_key()


def test_parses_user_key_roundtrip():
    account_id = uuid4()
    key = MemoryOwnerKey.parse(f"user:{account_id}")

    assert key.owner_type is MemoryOwnerType.USER
    assert key.owner_account_id == account_id


def test_parses_admin_key_with_agent_roundtrip():
    admin_id, agent_id = uuid4(), uuid4()
    key = MemoryOwnerKey.parse(f"admin:{admin_id}:{agent_id}")

    assert key.owner_admin_user_id == admin_id
    assert key.owner_agent_id == agent_id


def test_pg_kwargs_matches_model_columns():
    """PG 列名必须与模型字段一一对应（写库时直接 **kwargs 展开）。"""
    account_id = uuid4()
    kwargs = MemoryOwnerKey.for_user(account_id).pg_kwargs()

    assert kwargs == {
        "owner_type": "user",
        "owner_account_id": account_id,
        "owner_admin_user_id": None,
        "owner_agent_id": None,
    }


def test_user_requires_account_id():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.for_user(None)


def test_admin_requires_admin_user_id():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.for_admin(None)


def test_admin_type_without_admin_user_id_rejected():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey(
            owner_type=MemoryOwnerType.ADMIN,
            owner_account_id=uuid4(),
            owner_admin_user_id=None,
            owner_agent_id=None,
        )


def test_user_type_must_not_carry_admin_fields():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey(
            owner_type=MemoryOwnerType.USER,
            owner_account_id=uuid4(),
            owner_admin_user_id=uuid4(),
            owner_agent_id=None,
        )


def test_parse_rejects_unknown_prefix():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.parse("robot:1234")


def test_parse_rejects_malformed_uuid():
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.parse("user:not-a-uuid")


def test_from_legacy_user_id_treats_non_uuid_as_user_key():
    """旧数据里 `user_id` 未必是 UUID（历史写入，如 'platform'）。

    **行为必须与既有 `_upsert_vector` 一致**（[ledger_writer.py:846-860](../../api/internal/service/memory/ledger_writer.py#L846-L860)）：
    既有实现是 `UUID(str(...))` 失败 → 记 warning → **跳过写入**（不抛错）。
    故此处解析失败必须抛错，由调用方捕获后跳过——不得静默降级成
    "account 为空的 user 键"（那会让后续归属判定拿到坏 key）。
    """
    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.from_legacy_user_id("not-a-uuid")
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/entity/test_memory_owner_entity.py -q --no-header --no-cov
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'internal.entity.memory_owner_entity'`

- [ ] **Step 3: 写实现**

新建 `api/internal/entity/memory_owner_entity.py`：

```python
"""记忆主体抽象：把「记忆属于谁」从硬编码 account 提升为可表达的主体类型。

背景（设计 §8）：记忆系统此前把主体**硬编码为 Account**——`user_memory.owner_account_id`
是 NOT NULL FK、Neo4j 用 `user_id = str(account.id)`、Redis 键拼 `str(account.id)`。
引入管理员与 Agent 主体后，需要一个**跨层统一、可逆、fail closed** 的键表达。

四层映射（对齐知识库三字段模式 + 新增 agent 维度）：

| 层 | 表达 |
| --- | --- |
| PG | `owner_type` + `owner_account_id` / `owner_admin_user_id` / `owner_agent_id` |
| Neo4j / Redis / 冷存储 | 字符串 `owner_key` |

`owner_key` 形态（确定性、可解析、无歧义分隔）：
- 用户主体：`user:{account_uuid}`（与旧 `str(account.id)` **同值**，保证存量零变化）
- 管理员主体：`admin:{admin_uuid}`
- 管理员 + Agent（两级隔离，设计 §3 L1）：`admin:{admin_uuid}:{agent_uuid}`

**为什么不用 JSON / 不用长度前缀**：这些键要作为 Redis key 与 S3 路径片段，
必须是短、可读、URL/路径安全、且人类可直接看懂归属的形态。UUID 本身无冒号，
故 `:` 作为分隔符无歧义。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

__all__ = [
    "MemoryOwnerType",
    "MemoryOwnerKey",
    "MemoryOwnerKeyError",
]

_USER_PREFIX = "user"
_ADMIN_PREFIX = "admin"


class MemoryOwnerKeyError(ValueError):
    """主体键非法（类型与字段不匹配、UUID 不合法、前缀未知）。"""


class MemoryOwnerType(str, Enum):
    """记忆主体类型。"""

    USER = "user"
    ADMIN = "admin"


@dataclass(frozen=True)
class MemoryOwnerKey:
    """记忆主体键（不可变值对象）。

    不变量（构造即校验，fail closed）：
    - `user` 类型：必须有 `owner_account_id`，且不得携带 admin/agent 字段；
    - `admin` 类型：必须有 `owner_admin_user_id`，且不得携带 `owner_account_id`；
    - `owner_agent_id` 仅 `admin` 类型允许（user 主体没有 Agent 概念）。
    """

    owner_type: MemoryOwnerType
    owner_account_id: UUID | None = None
    owner_admin_user_id: UUID | None = None
    owner_agent_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.owner_type, MemoryOwnerType):
            raise MemoryOwnerKeyError(f"未知主体类型：{self.owner_type!r}")

        if self.owner_type is MemoryOwnerType.USER:
            if self.owner_account_id is None:
                raise MemoryOwnerKeyError("user 主体必须提供 owner_account_id")
            if self.owner_admin_user_id is not None or self.owner_agent_id is not None:
                raise MemoryOwnerKeyError(
                    "user 主体不得携带 owner_admin_user_id / owner_agent_id"
                )
            return

        if self.owner_admin_user_id is None:
            raise MemoryOwnerKeyError("admin 主体必须提供 owner_admin_user_id")
        if self.owner_account_id is not None:
            raise MemoryOwnerKeyError("admin 主体不得携带 owner_account_id")

    # ------------------------------------------------------------------
    # 构造
    # ------------------------------------------------------------------

    @classmethod
    def for_user(cls, account_id: UUID | None) -> "MemoryOwnerKey":
        """用户主体（等价旧的 `str(account.id)` 语义）。"""
        if account_id is None:
            raise MemoryOwnerKeyError("user 主体必须提供 account_id")
        return cls(owner_type=MemoryOwnerType.USER, owner_account_id=_as_uuid(account_id))

    @classmethod
    def for_admin(
        cls, admin_user_id: UUID | None, *, agent_id: UUID | None = None
    ) -> "MemoryOwnerKey":
        """管理员主体；传 `agent_id` 即「每 Agent 一份记忆」的两级隔离。"""
        if admin_user_id is None:
            raise MemoryOwnerKeyError("admin 主体必须提供 admin_user_id")
        return cls(
            owner_type=MemoryOwnerType.ADMIN,
            owner_admin_user_id=_as_uuid(admin_user_id),
            owner_agent_id=_as_uuid(agent_id) if agent_id is not None else None,
        )

    # ------------------------------------------------------------------
    # 序列化 / 解析
    # ------------------------------------------------------------------

    def to_key(self) -> str:
        """跨层主体键字符串（Neo4j 属性 / Redis key 片段 / 冷存储路径片段）。"""
        if self.owner_type is MemoryOwnerType.USER:
            return f"{_USER_PREFIX}:{self.owner_account_id}"
        if self.owner_agent_id is None:
            return f"{_ADMIN_PREFIX}:{self.owner_admin_user_id}"
        return f"{_ADMIN_PREFIX}:{self.owner_admin_user_id}:{self.owner_agent_id}"

    def pg_kwargs(self) -> dict:
        """可直接 `**` 展开给 `UserMemory(...)` / 向量表的列字典。"""
        return {
            "owner_type": self.owner_type.value,
            "owner_account_id": self.owner_account_id,
            "owner_admin_user_id": self.owner_admin_user_id,
            "owner_agent_id": self.owner_agent_id,
        }

    @classmethod
    def parse(cls, key: str) -> "MemoryOwnerKey":
        """解析 `to_key()` 产物；非法输入抛 `MemoryOwnerKeyError`。"""
        if not isinstance(key, str) or not key:
            raise MemoryOwnerKeyError("主体键必须是非空字符串")
        parts = key.split(":")
        prefix = parts[0]

        if prefix == _USER_PREFIX:
            if len(parts) != 2:
                raise MemoryOwnerKeyError(f"user 主体键格式应为 user:<uuid>，实际：{key}")
            return cls.for_user(_parse_uuid(parts[1], key))

        if prefix == _ADMIN_PREFIX:
            if len(parts) == 2:
                return cls.for_admin(_parse_uuid(parts[1], key))
            if len(parts) == 3:
                return cls.for_admin(
                    _parse_uuid(parts[1], key), agent_id=_parse_uuid(parts[2], key)
                )
            raise MemoryOwnerKeyError(
                f"admin 主体键格式应为 admin:<uuid> 或 admin:<uuid>:<uuid>，实际：{key}"
            )

        raise MemoryOwnerKeyError(f"未知主体键前缀：{prefix!r}（期望 user/admin）")

    @classmethod
    def from_legacy_user_id(cls, user_id: str) -> "MemoryOwnerKey":
        """把历史 `user_id` 字符串（= `str(account.id)`）转为主体键。

        历史 `user_id` 只可能是用户主体；非 UUID 一律抛错而不是降级
        （降级会造出 account 为空的坏键，污染归属判定）。
        """
        return cls.for_user(_parse_uuid(user_id, str(user_id)))


def _as_uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    return _parse_uuid(str(value), str(value))


def _parse_uuid(raw: str, context: str) -> UUID:
    try:
        return UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise MemoryOwnerKeyError(f"主体键含非法 UUID：{context}") from exc
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd api && python -m pytest test/internal/entity/test_memory_owner_entity.py -q --no-header --no-cov
```

Expected: PASS（14 个用例）

- [ ] **Step 5: 提交**

```bash
git add api/internal/entity/memory_owner_entity.py api/test/internal/entity/test_memory_owner_entity.py
git commit -m "feat(memory): add memory owner key value object"
```

---

## Task 2: `user_memory` 与向量分表增列 + 迁移

**Files:**
- Modify: `api/internal/model/knowledge.py`（`UserMemory`）
- Modify: `api/internal/service/embedding_table_router.py`（分表 DDL）
- Create: `api/internal/migration/versions/y2b3c4d5e6f8_add_memory_owner_type.py`
- Test: `api/test/internal/migration/test_memory_owner_type_migration.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/migration/test_memory_owner_type_migration.py`：

```python
"""记忆主体三列迁移守卫。

设计 §8：`user_memory` 与向量分表补 `owner_type` / `owner_admin_user_id` /
`owner_agent_id`；存量全标 `owner_type='user'`，**行为零变化**。
"""
import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3]
VERSIONS = API_ROOT / "internal" / "migration" / "versions"
MIGRATION = VERSIONS / "y2b3c4d5e6f8_add_memory_owner_type.py"


def _source() -> str:
    assert MIGRATION.is_file(), "缺少记忆主体迁移"
    return MIGRATION.read_text(encoding="utf-8")


def test_down_revision_points_to_current_single_head():
    down = re.search(r"^down_revision\s*=\s*[\"']([^\"']+)[\"']", _source(), re.M)
    assert down is not None, "迁移必须声明 down_revision"
    assert down.group(1) == "x1a2b3c4d5e7", (
        "down_revision 必须指向当前单 head（x1a2b3c4d5e7）"
    )


def test_migration_adds_three_columns_to_user_memory():
    source = _source()
    for column in ("owner_type", "owner_admin_user_id", "owner_agent_id"):
        assert column in source, f"迁移必须补 {column} 列"


def test_migration_backfills_existing_rows_as_user():
    """存量必须回填 owner_type='user'，否则新列非空约束会炸或语义错误。"""
    source = _source()
    assert "owner_type" in source
    assert re.search(r"UPDATE\s+user_memory", source, re.I), "必须回填存量行"
    assert "'user'" in source


def test_migration_creates_owner_agent_fk_and_index():
    source = _source()
    assert "admin_agent" in source, "owner_agent_id 必须 FK 到 admin_agent"
    assert "create_index" in source
    assert "owner_agent" in source


def test_migration_is_reversible():
    source = _source()
    assert "def downgrade" in source
    assert "drop_column" in source or "op.drop_column" in source


def test_model_declares_the_three_columns():
    from internal.model import UserMemory

    for column in ("owner_type", "owner_admin_user_id", "owner_agent_id"):
        assert column in UserMemory.__table__.c, f"模型缺列 {column}"
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/migration/test_memory_owner_type_migration.py -q --no-header --no-cov
```

Expected: FAIL（迁移文件不存在、模型缺列）

- [ ] **Step 3: 改模型**

在 `api/internal/model/knowledge.py` 的 `UserMemory`（`owner_account_id` 之后）插入：

```python
    # 主体类型（设计 §8）：'user' | 'admin'；存量全为 'user'
    owner_type = Column(
        String(16), nullable=False, server_default=text("'user'::character varying")
    )
    # 管理员主体（owner_type='admin' 时非空；与知识库 owner_admin_user_id 同义）
    owner_admin_user_id = Column(UUID, ForeignKey("admin_user.id"), nullable=True)
    # Agent 主体（设计 §3 L1：admin_user_id + agent_id 两级隔离）
    owner_agent_id = Column(UUID, ForeignKey("admin_agent.id"), nullable=True)
```

并把 `__table_args__` 的索引区扩充（保留既有两个索引不动）：

```python
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_user_memory_id"),
        Index("user_memory_owner_type_idx", "owner_account_id", "memory_type"),
        Index("user_memory_status_idx", "status"),
        # 按主体类型 + 管理员 + Agent 检索（P3b 读路径切换后使用）
        Index("user_memory_owner_admin_idx", "owner_admin_user_id"),
        Index("user_memory_owner_agent_idx", "owner_agent_id"),
    )
```

> **注意**：既有索引名 `user_memory_owner_type_idx` 指的是 `(owner_account_id, memory_type)`
> 复合索引，**与新增的 `owner_type` 列无关**（命名历史残留）。本计划**不改它**——
> 改名会牵动既有迁移与 `alembic autogenerate` 对比；如需改名，属 P3b 的清理项。

- [ ] **Step 4: 分表 DDL 增列**

在 `api/internal/service/embedding_table_router.py` 的 `user_memory_embedding_{dim}` 建表语句（`owner_account_id` 之后）插入三列：

```python
                            owner_account_id UUID NOT NULL REFERENCES account(id),
                            owner_type VARCHAR(16) NOT NULL DEFAULT 'user',
                            owner_admin_user_id UUID REFERENCES admin_user(id),
                            owner_agent_id UUID REFERENCES admin_agent(id),
```

并在该表索引区追加：

```python
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS {um_table}_owner_agent_idx "
                        f"ON {um_table} (owner_agent_id)"
                    ))
```

- [ ] **Step 5: 写迁移**

新建 `api/internal/migration/versions/y2b3c4d5e6f8_add_memory_owner_type.py`：

```python
"""add memory owner type columns for subject abstraction

设计依据：docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md §8。

记忆主体此前硬编码为 Account（`owner_account_id` NOT NULL FK）。本迁移引入
`owner_type`(+`owner_admin_user_id`/`owner_agent_id`)，使记忆可归属管理员与 Agent。

**存量回填 `owner_type='user'`**：规格要求"存量全标 owner_type='user'，行为零变化"。
回填后 `owner_account_id` 原值不变、为非空，故既有读路径（按 owner_account_id 过滤）
逐字节不受影响。

向量分表 `user_memory_embedding_{dim}` 是**按维度动态建表**的（维度 1–2000），
无法在迁移里枚举全部表名，故此处对"已存在的分表"做一次 information_schema 扫描补列；
新建分表由 `EmbeddingTableRouter.ensure_tables_for_dimension()` 的 DDL 直接带上新列。

Revision ID: y2b3c4d5e6f8
Revises: x1a2b3c4d5e7
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "y2b3c4d5e6f8"
down_revision = "x1a2b3c4d5e7"
branch_labels = None
depends_on = None

_USER_MEMORY_EMBEDDING_PREFIX = "user_memory_embedding_"


def upgrade():
    # 1) 主表补三列（owner_type 先可空，回填后再收紧为 NOT NULL，避免锁表时报"已有非空行")
    op.add_column(
        "user_memory",
        sa.Column("owner_type", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "user_memory",
        sa.Column(
            "owner_admin_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "user_memory",
        sa.Column("owner_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # 2) 存量回填：全部标 user（原 owner_account_id 不变 → 行为零变化）
    op.execute("UPDATE user_memory SET owner_type = 'user' WHERE owner_type IS NULL")

    # 3) 回填后再收紧非空 + 默认值
    op.alter_column(
        "user_memory",
        "owner_type",
        nullable=False,
        server_default=sa.text("'user'::character varying"),
    )

    # 4) 外键（与模型声明一致；FK 名遵循本仓 fk_<table>_<col>_<target> 约定）
    op.create_foreign_key(
        "fk_user_memory_owner_admin_user_id_admin_user",
        "user_memory",
        "admin_user",
        ["owner_admin_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_user_memory_owner_agent_id_admin_agent",
        "user_memory",
        "admin_agent",
        ["owner_agent_id"],
        ["id"],
    )

    # 5) 索引
    op.create_index("user_memory_owner_admin_idx", "user_memory", ["owner_admin_user_id"])
    op.create_index("user_memory_owner_agent_idx", "user_memory", ["owner_agent_id"])

    # 6) 已存在的向量分表补列（动态表名，故用扫描而非枚举）
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE :prefix"
        ),
        {"prefix": f"{_USER_MEMORY_EMBEDDING_PREFIX}%"},
    ).fetchall()
    for (table_name,) in rows:
        op.execute(
            f"ALTER TABLE {table_name} "
            "ADD COLUMN IF NOT EXISTS owner_type VARCHAR(16) NOT NULL DEFAULT 'user'"
        )
        op.execute(
            f"ALTER TABLE {table_name} "
            "ADD COLUMN IF NOT EXISTS owner_admin_user_id UUID REFERENCES admin_user(id)"
        )
        op.execute(
            f"ALTER TABLE {table_name} "
            "ADD COLUMN IF NOT EXISTS owner_agent_id UUID REFERENCES admin_agent(id)"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {table_name}_owner_agent_idx "
            f"ON {table_name} (owner_agent_id)"
        )


def downgrade():
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE :prefix"
        ),
        {"prefix": f"{_USER_MEMORY_EMBEDDING_PREFIX}%"},
    ).fetchall()
    for (table_name,) in rows:
        op.execute(f"DROP INDEX IF EXISTS {table_name}_owner_agent_idx")
        op.execute(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS owner_agent_id")
        op.execute(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS owner_admin_user_id")
        op.execute(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS owner_type")

    op.drop_index("user_memory_owner_agent_idx", table_name="user_memory")
    op.drop_index("user_memory_owner_admin_idx", table_name="user_memory")
    op.drop_constraint(
        "fk_user_memory_owner_agent_id_admin_agent", "user_memory", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_user_memory_owner_admin_user_id_admin_user", "user_memory", type_="foreignkey"
    )
    op.drop_column("user_memory", "owner_agent_id")
    op.drop_column("user_memory", "owner_admin_user_id")
    op.drop_column("user_memory", "owner_type")
```

- [ ] **Step 6: 运行测试确认通过**

```bash
cd api && python -m pytest test/internal/migration/test_memory_owner_type_migration.py -q --no-header --no-cov
```

Expected: PASS（6 个用例）

- [ ] **Step 7: 跑迁移图守卫（必须仍是单 head）**

```bash
cd api && python -m pytest test/internal/migration -q --no-header --no-cov
```

Expected: PASS（含单 head 与无悬空 `down_revision`）

- [ ] **Step 8: 在真实 PostgreSQL 上验证迁移可升可降**

```bash
cd api && python -m alembic -c internal/migration/alembic.ini upgrade head
cd api && python -m alembic -c internal/migration/alembic.ini downgrade -1
cd api && python -m alembic -c internal/migration/alembic.ini upgrade head
```

Expected: 三个命令均成功（第二次 upgrade 证明 downgrade 干净可重入）

- [ ] **Step 9: 提交**

```bash
git add api/internal/model/knowledge.py api/internal/service/embedding_table_router.py api/internal/migration/versions/y2b3c4d5e6f8_add_memory_owner_type.py api/test/internal/migration/test_memory_owner_type_migration.py
git commit -m "feat(memory): add owner type columns to memory tables"
```

---

## Task 3: 写入侧双写（读路径不动）

**Files:**
- Modify: `api/internal/service/memory/ledger_writer.py`
- Test: `api/test/internal/service/memory/test_ledger_writer_owner.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/memory/test_ledger_writer_owner.py`：

```python
"""写入侧主体双写测试（设计 §8：先双写，读路径不变）。

不变量：
1. 用户主体路径写入的三新列必须与旧 `owner_account_id` **一致**（owner_type='user'）；
2. 旧列仍照写（读路径零变化的前提）；
3. 无法解析主体时**不写**且不抛（与既有 `UUID(str(...))` 失败即跳过的行为一致）。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.memory_owner_entity import MemoryOwnerKey


def test_user_owner_writes_matching_new_columns():
    account_id = uuid4()
    key = MemoryOwnerKey.for_user(account_id)

    kwargs = key.pg_kwargs()

    assert kwargs["owner_type"] == "user"
    assert kwargs["owner_account_id"] == account_id
    assert kwargs["owner_admin_user_id"] is None
    assert kwargs["owner_agent_id"] is None


def test_admin_owner_keeps_account_column_empty():
    admin_id, agent_id = uuid4(), uuid4()
    key = MemoryOwnerKey.for_admin(admin_id, agent_id=agent_id)

    kwargs = key.pg_kwargs()

    assert kwargs["owner_type"] == "admin"
    assert kwargs["owner_account_id"] is None
    assert kwargs["owner_admin_user_id"] == admin_id
    assert kwargs["owner_agent_id"] == agent_id


def test_resolve_owner_key_from_legacy_user_id():
    """系统路径从 `event.user_id`（str）还原主体键。"""
    account_id = uuid4()

    key = MemoryOwnerKey.from_legacy_user_id(str(account_id))

    assert key.owner_account_id == account_id
    assert key.to_key() == f"user:{account_id}"


def test_resolve_owner_key_rejects_non_uuid():
    from internal.entity.memory_owner_entity import MemoryOwnerKeyError

    with pytest.raises(MemoryOwnerKeyError):
        MemoryOwnerKey.from_legacy_user_id("platform")
```

> **说明**：本任务的测试只锁「主体键 → 列值」的映射契约（纯函数级）。
> 真实写库路径的行为由 Task 4 的存量迁移校验 + 全量回归共同证明。

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/service/memory/test_ledger_writer_owner.py -q --no-header --no-cov
```

Expected: PASS（4 个用例）—— 这是**纯函数契约测试**，Task 1 落地后即可通过；
若失败，说明 `MemoryOwnerKey` 的接口与这里的调用不一致，先修接口。

- [ ] **Step 3: 在写入点接上双写**

在 `api/internal/service/memory/ledger_writer.py` 的 `_upsert_vector` 中，找到解析 `owner_account_id` 的位置（当前 `user_id_raw = payload.get("user_id")` 附近，L839-860），把主体解析改为走值对象，并把三新列写进 `UserMemory(...)`：

```python
        # 主体解析：统一走 MemoryOwnerKey，解析失败即跳过写入（与既有行为一致）
        from internal.entity.memory_owner_entity import (
            MemoryOwnerKey,
            MemoryOwnerKeyError,
        )

        user_id_raw = payload.get("user_id")
        try:
            owner_key_obj = MemoryOwnerKey.from_legacy_user_id(str(user_id_raw))
        except MemoryOwnerKeyError:
            logger.warning("记忆主体无法解析，跳过向量写入：user_id=%r", user_id_raw)
            return None
        owner_account_id = owner_key_obj.owner_account_id
```

并在新建 `UserMemory(...)` 处（当前 L950-962）把三新列并入：

```python
            memory = UserMemory(
                owner_account_id=owner_account_id,
                **{
                    k: v
                    for k, v in owner_key_obj.pg_kwargs().items()
                    if k != "owner_account_id"  # 已在上一行显式传入，避免重复
                },
                memory_type=payload.get("event_type", "episode"),
                content=payload.get("content", ""),
                embedding_node_id=point_id,
                scope="user_memory",
                created_from=payload.get("source", "conversation_memory"),
                metadata_=payload,
            )
```

> **重要（勿改）**：`owner_account_id` 仍必须显式传入（它是 NOT NULL 旧列，读路径依赖）。
> 新列是**附加**信息，不替换旧列——这正是"双写"的含义。
>
> 同时，Agent 策展写入路径 `write_agent_curated(account_id: UUID, ...)` 也要一并双写：
> 该路径主体是用户（`owner_type='user'`），用 `MemoryOwnerKey.for_user(account_id)` 取列值，
> 保持与系统路径同一套映射（避免两条写入路径的归属语义再次分叉）。

- [ ] **Step 4: 跑记忆写入相关回归**

```bash
cd api && python -m pytest test/internal/service/memory -q --no-header --no-cov
```

Expected: PASS（既有记忆测试全绿——双写不应改变任何既有行为）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/memory/ledger_writer.py api/test/internal/service/memory/test_ledger_writer_owner.py
git commit -m "feat(memory): dual-write owner type columns in ledger writer"
```

---

## Task 4: 存量数据一致性校验

**Files:**
- Test: `api/test/internal/migration/test_memory_owner_backfill_consistency.py`

- [ ] **Step 1: 写校验测试**

新建 `api/test/internal/migration/test_memory_owner_backfill_consistency.py`：

```python
"""存量回填一致性守卫（设计 §8：存量全标 owner_type='user'，行为零变化）。

在**真实数据库**上校验（无 DB 时自动跳过，不制造假绿）：
1. `user_memory` 无 `owner_type IS NULL` 行；
2. 所有存量行 `owner_type='user'` 且 `owner_account_id IS NOT NULL`；
3. `owner_type='admin'` 的行数为 0（本计划不写 admin 记忆）。
"""
import pytest


def _engine():
    from sqlalchemy import create_engine

    from config import Config

    uri = getattr(Config(), "SQLALCHEMY_DATABASE_URI", "") or ""
    if not uri.startswith("postgresql"):
        return None
    try:
        engine = create_engine(uri)
        engine.connect().close()
        return engine
    except Exception:
        return None


@pytest.fixture()
def engine():
    engine = _engine()
    if engine is None:
        pytest.skip("无可用 PostgreSQL，跳过存量一致性校验")
    return engine


def test_no_null_owner_type_rows(engine):
    from sqlalchemy import text

    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM user_memory WHERE owner_type IS NULL")
        ).scalar()
    assert count == 0, "存量回填后不应存在 owner_type 为空的行"


def test_existing_rows_are_user_scoped(engine):
    from sqlalchemy import text

    with engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM user_memory "
                "WHERE owner_type = 'user' AND owner_account_id IS NOT NULL"
            )
        ).scalar()
        total = conn.execute(text("SELECT count(*) FROM user_memory")).scalar()
    assert count == total, "所有存量行都应是 user 主体且保留 owner_account_id"


def test_no_admin_scoped_memory_yet(engine):
    from sqlalchemy import text

    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM user_memory WHERE owner_type <> 'user'")
        ).scalar()
    assert count == 0, "本计划不写入 admin 记忆，出现即说明双写逻辑越界"
```

- [ ] **Step 2: 运行测试**

```bash
cd api && python -m pytest test/internal/migration/test_memory_owner_backfill_consistency.py -q --no-header --no-cov
```

Expected: PASS 或 SKIP（无 PG 环境时跳过；有 PG 时必须 PASS）

- [ ] **Step 3: 提交**

```bash
git add api/test/internal/migration/test_memory_owner_backfill_consistency.py
git commit -m "test(memory): guard owner type backfill consistency"
```

---

## Task 5: 全量回归（证明"行为零变化"）

**Files:** 无（验证任务）

- [ ] **Step 1: 全量回归**

```bash
cd api && python -m pytest test -q --no-header --no-cov
```

Expected: 全绿；用例数应 ≥ 基线（原 4767 passed + 本计划新增用例），**无 failed**

- [ ] **Step 2: 确认读路径未改（零变化自证）**

```bash
cd api && git diff --stat <baseline_sha> HEAD -- internal/service/memory/retriever.py internal/service/memory/digest_manager.py internal/service/memory/memory_governor.py internal/service/memory/consolidation_engine.py
```

Expected: **空输出**（本计划承诺不触碰这些读路径文件；有输出即为越界，必须回退）

- [ ] **Step 3: 提交（如无代码改动则跳过）**

若无改动，本任务不产生提交。

---

## Task 6: 主体键常量落位（供 P3b 使用）

**Files:**
- Modify: `api/internal/config/memory_settings.py`
- Test: `api/test/internal/config/test_memory_owner_settings.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/config/test_memory_owner_settings.py`：

```python
"""主体键跨层前缀常量（供 P3b 的 Neo4j/Redis/冷存储统一使用）。"""


def test_owner_key_prefixes_defined():
    from internal.config import memory_settings

    assert memory_settings.OWNER_KEY_USER_PREFIX == "user"
    assert memory_settings.OWNER_KEY_ADMIN_PREFIX == "admin"


def test_owner_key_separator_is_colon():
    from internal.config import memory_settings

    assert memory_settings.OWNER_KEY_SEPARATOR == ":"
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/config/test_memory_owner_settings.py -q --no-header --no-cov
```

Expected: FAIL —— `AttributeError: module ... has no attribute 'OWNER_KEY_USER_PREFIX'`

- [ ] **Step 3: 加常量**

在 `api/internal/config/memory_settings.py` 模块级常量区追加：

```python
# ============================================================
# 记忆主体键（设计 §8，P3a 落常量，P3b 起被 Neo4j/Redis/冷存储使用）
# ============================================================
# 跨层主体键的形态由 MemoryOwnerKey.to_key() 唯一决定，此处常量只提供给
# 需要"按前缀拼键/扫描"的存储层（Redis scan / 冷存储路径），避免各处自行
# 硬编码 'user'/'admin' 造成漂移。
OWNER_KEY_USER_PREFIX = "user"
OWNER_KEY_ADMIN_PREFIX = "admin"
OWNER_KEY_SEPARATOR = ":"
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd api && python -m pytest test/internal/config/test_memory_owner_settings.py -q --no-header --no-cov
```

Expected: PASS（2 个用例）

- [ ] **Step 5: 提交**

```bash
git add api/internal/config/memory_settings.py api/test/internal/config/test_memory_owner_settings.py
git commit -m "feat(memory): add owner key prefix constants"
```

---

## Task 7: 文档同步

**Files:**
- Modify: `docs/prd/memory-system/`（主体抽象章节）
- Modify: `docs/prd/execution-roadmap.md`（P3a 小节 + Phase 表）

- [ ] **Step 1: 在记忆系统文档登记主体抽象**

在 `docs/prd/memory-system/` 下已有文档中挑选「数据模型 / 归属」相关一篇，追加一节，内容须与代码同源（**逐条核对后再写**）：

```markdown
### 记忆主体抽象（P3a 已落地）

记忆归属从"硬编码 `Account`"升级为**主体类型**维度（设计 §8），使记忆可归属管理员与 Agent。

| 层 | 归属表达 |
| --- | --- |
| PG `user_memory` | `owner_type`('user'\|'admin') + `owner_account_id` + `owner_admin_user_id` + `owner_agent_id` |
| PG `user_memory_embedding_{dim}` | 同上四列（新建分表由 `EmbeddingTableRouter` DDL 带上；已存在的分表由迁移 `y2b3c4d5e6f8` 补列） |
| 跨层主体键 | `MemoryOwnerKey.to_key()`：`user:{account_uuid}` / `admin:{admin_uuid}` / `admin:{admin_uuid}:{agent_uuid}` |

**两级隔离**：管理员 + Agent（`admin:{admin_uuid}:{agent_uuid}`），同一管理员的多个 Agent 互不干扰。

**本阶段（P3a）范围**：写侧双写新列 + 存量回填 `owner_type='user'`；**读路径未切换**（仍按 `owner_account_id` / `user_id` 过滤），故行为零变化。
Neo4j / Redis / 冷存储的键统一与读路径切换属 **P3b**（尚未落地）。
```

- [ ] **Step 2: roadmap 追加 P3a 小节**

在 `docs/prd/execution-roadmap.md` 的 P2 小节之后追加：

```markdown
### 管理端 Agent 治理（P3a 记忆主体抽象内核，2026-09-17 完成）

| 交付物 | 位置 |
| --- | --- |
| 主体键值对象 | `api/internal/entity/memory_owner_entity.py`（`MemoryOwnerKey` / `MemoryOwnerType`） |
| 主体列与迁移 | `user_memory` + 向量分表补 `owner_type`/`owner_admin_user_id`/`owner_agent_id`；迁移 `y2b3c4d5e6f8` |
| 写入双写 | `api/internal/service/memory/ledger_writer.py`（系统路径 + Agent 策展路径） |
| 存量一致性守卫 | `test_memory_owner_backfill_consistency.py`（真库校验） |
| 键前缀常量 | `api/internal/config/memory_settings.py` |

> **未落地（P3b）**：读路径切 `owner_key`、Neo4j/Redis/冷存储键统一、服务层签名统一、admin Agent 记忆**读取**接入；
> 以及既有不一致 C1（Neo4j `Skill` 节点写入键与统计合并键不符）、C2（`DigestConfig` 配置双源）、
> C3（GDPR 清 Redis 白名单键与真实键不符 → 清理无效）、C4（冷存储 `list_user_archives()` 空实现）。
```

- [ ] **Step 3: 刷新知识图谱 + 提交**

```bash
python -m graphify update .
git add docs/prd/memory-system docs/prd/execution-roadmap.md
git commit -m "docs(memory): document owner abstraction core (P3a)"
```

---

## 自检清单（实施者收尾前逐项确认）

- [ ] **每个新符号点名入口**：
  - `MemoryOwnerKey` / `MemoryOwnerType` → 由 `LedgerWriter` 写入路径构造（Task 3）；P3b 起被读路径与各存储层使用
  - `owner_type` / `owner_admin_user_id` / `owner_agent_id` → 写入侧 `ledger_writer.py`（Task 3）；**读取侧本计划不接入**（P3b）
  - `OWNER_KEY_USER_PREFIX` 等常量 → 本计划仅落常量与测试，**尚无生产消费方**；须在文档与回复中标注「已提供、未接入（P3b 使用）」
- [ ] **新列读写核验**：本计划是**刻意只写不读**（双写阶段）；已在 roadmap 与记忆文档如实标注，未宣称"读路径已支持主体抽象"
- [ ] **迁移** `down_revision = x1a2b3c4d5e7`（当前单 head）；`test/internal/migration` 通过；真库 upgrade/downgrade/upgrade 三连通过
- [ ] **读路径零改动**：`retriever.py` / `digest_manager.py` / `memory_governor.py` / `consolidation_engine.py` **无 diff**
- [ ] **存量零变化**：全量回归无 failed；存量行 `owner_type='user'` 且有测试守卫
- [ ] **无硬编码主体前缀**：`'user'` / `'admin'` 仅在 `MemoryOwnerKey` 与 `memory_settings` 常量处出现
- [ ] 全量回归：`cd api && python -m pytest test -q --no-header --no-cov`

---

## 后续（P3b，本计划不实施）

1. 读路径切 `owner_key`：`retriever._vector_recall` / `_tkg_recall` / `_community_recall`、`digest_manager` 各 `_fetch_*`、`consolidation_engine`、`memory_governor`
2. Neo4j 节点属性 `user_id` → `owner_key`（含全部标签与关系、全文索引过滤、`SpreadActivation` 补归属谓词）
3. Redis 键 `{prefix}:{user_id}` → `{prefix}:{owner_key}`；修 C3（GDPR 清理白名单键不符）
4. 冷存储路径 `cold-memories/{user_id}/...` → `{owner_key}`；修 C4（`list_user_archives` 空实现）
5. 服务层签名统一（60+ 处 `user_id: str` → 主体键入参）
6. admin Agent 记忆**读写**接入（`AdminAgentPrincipal` → `MemoryOwnerKey.for_admin(admin_user_id, agent_id=...)`）
7. 既有不一致 C1 / C2 收敛
