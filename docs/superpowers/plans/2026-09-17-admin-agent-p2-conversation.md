# 管理端 Agent 治理 P2（对话式入口 + 独立会话表 + 预置提示词）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理员能选一个管理端 Agent 与之多轮对话，由它在已授权板块内执行治理动作——补齐独立会话/消息表、对话编排链路（取模型 → 工具循环 → 落库 → SSE）、板块工具的 LLM 适配、系统提示词与预置 Agent、以及 admin Agent 的 feature 计费注册。

**Architecture:** 沿用 P1b「新建独立链路、不复用用户端 `chat()`」的决策（设计 §6.1）：本链路只装配**白名单式板块工具**（每个已登记板块一个 LangChain 工具，内部按 `action` 分支），身份是显式 `AdminAgentPrincipal`（三重交集实时重算）。会话/消息走**独立表** `admin_agent_conversation` / `admin_agent_message`，不与用户端 `conversation` / `message` 混表——因此**不扩展** `InvokeFrom` 枚举，也不需要用户端 `app`/`account` 上下文。预置 Agent 落 `admin_agent` 表（新增 `builtin_key` 幂等键），**不进 Agent 池**（池成员是用户端 `app_id`、无授权字段，语义与数据模型均不兼容）。

**Tech Stack:** Python 3.12 / Quart(ASGI) / SQLAlchemy / Alembic / LangChain(`BaseTool`/`bind_tools`) / pytest（`--no-cov` 快跑）

**依据规格：** [2026-09-15-admin-agent-governance-design.md](../specs/2026-09-15-admin-agent-governance-design.md) §5（L4 身份层）、§6.1（独立链路）、§6.2（计费）、§7.1（板块级聚合工具）、§10.1/§10.3（表与提示词）、§14（P2 分期）。

---

## 范围边界（已与用户确认，不得擅自扩张）

| 项 | 决定 |
|---|---|
| 前端 | **不做**。仅后端：API + 落库 + 编排 + 提示词 seed + feature 注册。管理端 Vue 对话页另立前端任务 |
| 预置 Agent 存储 | 落 `admin_agent` 表 + 新增 `builtin_key` 幂等键；**不进 Agent 池** |
| 预置 Agent 权限 | `granted_permissions=[]`（**不下放**——权限必须由管理员显式下放，符合 §4.3） |
| 定时任务入口（`schedule_task.agent_id`） | **不做**，属 P4 |
| 预算闸门实际执行 | **不做**，属 P4（`budget_config` 列已存在，P2 只读不写） |
| 记忆主体抽象 / 按 Agent 隔离记忆 | **不做**，属 P3 |
| MCP 动态身份注入 | **不做**，属 P5 |

---

## 本机实测事实（写计划前已核对，非推测）

| 事实 | 值 / 证据 |
| --- | --- |
| 迁移当前 **单 head** | `w1e2f3a4b5c6`（AST 遍历 154 个迁移，唯一 head）→ 新迁移 `down_revision` 必须指向它 |
| `admin_agent` 表列 | `id` / `owner_admin_user_id`(FK admin_user, CASCADE) / `name` / `description` / `prompt_key`(可空) / `granted_permissions`(JSONB) / `automation_policy`(JSONB) / `budget_config`(JSONB) / `enabled` / 时间戳（`api/internal/model/admin_agent.py`） |
| `AdminAgentPrincipal` | `admin_user_id` / `agent_id` / `agent_name` / `effective_permissions: frozenset[str]` / `automation_policy: Mapping[str, AutomationLevel]`；`has_permission(code)` / `automation_level_for(board)`（未配置 → `SUPERVISED`） |
| `AdminAgentService`（非 `@inject`，`__init__(self, db)`） | `get_principal(*, agent_id, admin_user_id, admin_permissions)` → principal 或 `None`；非属主/停用 → `PermissionError`；`get_agent(*, agent_id, admin_user_id)`；`list_agents(*, admin_user_id)` |
| **`admin_user_id` 必须是 `UUID`** | `admin["id"]` 由序列化层产出**字符串**，而 `owner_admin_user_id` 是 UUID 列、`get_agent` 做纯 Python 比较——路由必须 `UUID(str(admin["id"]))`（P1 已修，路由测试已锁定） |
| `BOARD_ACTIONS` 注册表 | `api/internal/core/admin_agent_boards.py`：`BOARD_ACTIONS` / `BOARD_IDS` / `board_ids_of(board)` / `resolve_action(board, action)`（未登记 → `ValueError`，fail closed）；当前仅登记 `builtin_tool` 的 `list`/`update_enabled`/`update_metadata` |
| `BoardToolExecutor`（无状态，直接 `BoardToolExecutor()`） | `assert_allowed(principal, *, board, action)` → `BoardAction`；`requires_draft(principal, board)`（静态）；`execute(principal, *, board, action, payload)` |
| `AdminAgentExecutionService.run(...)` | `run(principal, *, board, action, payload)` → `{"outcome": "executed"\|"drafted", "result": ..., "draft_id": ...}`；`(board, action)` 未登记 → `ValueError`；权限不足/熔断 → `PermissionError`，**且已写审计**（`admin_agent.<board>.<action>.denied`） |
| 取模型 | `LanguageModelService.get_feature_model(feature_key)`（`@classmethod`）→ `BaseLanguageModel`；feature 未启用 → `FailException`；未绑定模型 → 用 `fallback_tier` |
| feature 注册表 | `PublicAIFeatureService._BUILTIN_FEATURES`（list[dict]，字段 `feature_key`/`feature_name`/`feature_category`/`feature_description`/`model_type`/`fallback_tier`/`billable`）+ 启动时 `ensure_builtin_features()` 补齐 |
| 提示词 seed | `api/internal/core/prompts/index.yaml` 登记 `key`/`category`/`file`；YAML 结构 `prompt_key`/`name`/`category`/`description`/`variables`/`content`；`admin_agent/board_agent.yaml` 已存在 |
| 管理端路由 | 全在 `api/app/http/admin_routes_7.py`；`support._admin_route_permission` 对 `/admin/agents*` 通用映射：`GET → agent_pool:read`，`POST/PATCH/PUT/DELETE → agent_pool:manage`（**新路由无需改权限表**） |
| 管理员字典 | `await a._resolve_admin_permission(code)` → `(admin_dict, None)` 或 `(None, err)`；`admin_dict["id"]` 为**字符串** |
| SSE 写法参照 | `api/app/http/schedule_assistant_routes.py` 的 `POST /assistant-agent/chat`：`await _to_thread(service.chat, req, account)` → `_sse_response(gen)`；`support._sse_response` 包成 `text/event-stream` |
| **DI 构造（易致命）** | `support._get_service(cls)` = `injector.get(cls)`；只有 `@inject` 标注过的类可被构造，**仅写 `db: SQLAlchemy` 注解不够**。实测缺 `@inject` 的三个 admin-agent 服务全部 `CallError`（已修，提交 `0f24d29`），守卫测试 `test_admin_agent_di_construction.py` |
| 测试约定 | conftest autouse 把 `support._resolve_admin_permission` 替换为无条件放行，需显式覆盖才能测权限；路由测试用 `quart_app.test_client()` + `asyncio.run` |

---

## 文件结构

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `api/internal/model/admin_agent.py` | 修改 | 新增 `builtin_key` 列 + `(owner_admin_user_id, builtin_key)` 部分唯一索引 |
| `api/internal/model/admin_agent_conversation.py` | 新建 | `AdminAgentConversation` + `AdminAgentMessage` 两张独立表 |
| `api/internal/model/__init__.py` | 修改 | 导出新模型 |
| `api/internal/migration/versions/x1a2b3c4d5e7_add_admin_agent_conversation.py` | 新建 | 建会话/消息表 + `admin_agent.builtin_key` |
| `api/internal/entity/admin_agent_chat_entity.py` | 新建 | 会话状态/消息角色/SSE 事件枚举 |
| `api/internal/service/admin_agent_conversation_service.py` | 新建 | 会话与消息 CRUD + 归属隔离 |
| `api/internal/service/admin_agent_builtin_agents.py` | 新建 | 预置 Agent 清单 + `ensure_builtin_agents()` |
| `api/internal/service/admin_agent_chat_tools.py` | 新建 | 把 `BOARD_ACTIONS` 暴露为「每板块一个」LangChain 工具 |
| `api/internal/service/admin_agent_chat_service.py` | 新建 | 对话编排：principal → 会话 → 提示词 → 工具循环 → 落库 → SSE |
| `api/internal/schema/admin_agent_chat_schema.py` | 新建 | 对话请求 / 会话 / 消息响应 schema |
| `api/app/http/admin_routes_7.py` | 修改 | `POST /admin/agents/<id>/chat`（SSE）+ 会话列表 + 消息列表 |
| `api/internal/service/public_ai_feature_service.py` | 修改 | `_BUILTIN_FEATURES` 增 `admin_agent`（`billable=False`） |
| `api/internal/core/prompts/admin_agent/ops_agent.yaml` | 新建 | 预置「运维 Agent」人格提示词 |
| `api/internal/core/prompts/admin_agent/marketing_agent.yaml` | 新建 | 预置「运营 Agent」人格提示词 |
| `api/internal/core/prompts/index.yaml` | 修改 | 登记两个新 `prompt_key` |
| `docs/api/admin-agents-api.md` | 修改 | 补对话与会话接口契约 |
| `docs/prd/execution-roadmap.md` | 修改 | 追加 P2 小节 |
| `docs/prd/modules/01-agent-tool-pool.md` | 修改 | 说明管理端对话链路的独立装配点 |

---

## Task 1: 会话与消息表 + `builtin_key` 幂等键

**Files:**
- Modify: `api/internal/model/admin_agent.py`
- Create: `api/internal/model/admin_agent_conversation.py`
- Modify: `api/internal/model/__init__.py`
- Create: `api/internal/migration/versions/x1a2b3c4d5e7_add_admin_agent_conversation.py`
- Test: `api/test/internal/migration/test_admin_agent_conversation_migration.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/migration/test_admin_agent_conversation_migration.py`：

```python
"""P2 会话/消息表与 builtin_key 迁移守卫。

设计 §10.1：管理端 Agent 的会话与消息走**独立表**，不与用户端
conversation/message 混表；预置 Agent 需 builtin_key 作幂等键。
"""
import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[3]
VERSIONS = API_ROOT / "internal" / "migration" / "versions"
MIGRATION = VERSIONS / "x1a2b3c4d5e7_add_admin_agent_conversation.py"


def test_migration_declares_correct_down_revision():
    assert MIGRATION.is_file(), "缺少 P2 会话表迁移"
    source = MIGRATION.read_text(encoding="utf-8")
    down = re.search(r"^down_revision\s*=\s*[\"']([^\"']+)[\"']", source, re.M)
    assert down is not None
    assert down.group(1) == "w1e2f3a4b5c6", "down_revision 必须是当前单 head"


def test_migration_creates_both_tables_and_builtin_key():
    source = MIGRATION.read_text(encoding="utf-8")
    assert "admin_agent_conversation" in source
    assert "admin_agent_message" in source
    assert "builtin_key" in source
    assert "postgresql_where" in source, "builtin_key 幂等键必须是部分唯一索引"


def test_migration_is_reversible():
    source = MIGRATION.read_text(encoding="utf-8")
    assert "def downgrade" in source
    assert "drop_table" in source
    assert "drop_column" in source


def test_models_exported_and_declared():
    from internal.model import AdminAgentConversation, AdminAgentMessage

    assert AdminAgentConversation.__tablename__ == "admin_agent_conversation"
    assert AdminAgentMessage.__tablename__ == "admin_agent_message"
    assert hasattr(AdminAgentConversation, "admin_agent_id")
    assert hasattr(AdminAgentMessage, "tool_calls")
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/migration/test_admin_agent_conversation_migration.py -q --no-header --no-cov
```

Expected: FAIL —— 「缺少 P2 会话表迁移」与 `ImportError: cannot import name 'AdminAgentConversation'`

- [ ] **Step 3: 给 `admin_agent` 加 `builtin_key`**

在 `api/internal/model/admin_agent.py` 的 `__table_args__` 末尾（`admin_agent_enabled_idx` 之后）追加：

```python
        # 预置 Agent 的幂等键：同一管理员下同一 builtin_key 至多一条。
        # 为什么是**部分**唯一索引：自建 Agent 的 builtin_key 为 NULL，
        # 全表唯一会让"多个 NULL"在 PostgreSQL 下虽可行、但语义含糊，
        # 且日后若改用其他方言会踩 NULL 唯一陷阱。
        Index(
            "admin_agent_owner_builtin_uniq",
            "owner_admin_user_id",
            "builtin_key",
            unique=True,
            postgresql_where=text("builtin_key IS NOT NULL"),
        ),
```

并在列定义区（`prompt_key` 之后）追加：

```python
    # 预置（内置）Agent 的稳定标识；自建 Agent 为 NULL
    builtin_key = Column(String(64), nullable=True)
```

- [ ] **Step 4: 建会话与消息模型**

新建 `api/internal/model/admin_agent_conversation.py`：

```python
"""管理端 Agent 的会话与消息（设计 §10.1）。

**独立表**：不与用户端 `conversation` / `message` 混表。理由（设计 §11）：
用户端表没有 admin 标识列，admin 侧只能靠 `invoke_from` 约定区分；
独立表让"管理端对话"拥有自己的主键域与归属列（`admin_user_id`），
审计与归属判断不再需要猜测。
"""
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UUID,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AdminAgentConversation(Base):
    __tablename__ = "admin_agent_conversation"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_admin_agent_conversation_id"),
        ForeignKeyConstraint(
            ["admin_agent_id"],
            ["admin_agent.id"],
            name="fk_admin_agent_conversation_agent_id_admin_agent",
            ondelete="CASCADE",
        ),
        Index("admin_agent_conversation_agent_idx", "admin_agent_id"),
        Index("admin_agent_conversation_admin_idx", "admin_user_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    admin_agent_id = Column(UUID, nullable=False)
    admin_user_id = Column(UUID, nullable=False)
    title = Column(String(255), nullable=False, server_default=text("''::character varying"))
    is_deleted = Column(Boolean, nullable=False, server_default=text("false"))
    updated_at = Column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )


class AdminAgentMessage(Base):
    __tablename__ = "admin_agent_message"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_admin_agent_message_id"),
        ForeignKeyConstraint(
            ["conversation_id"],
            ["admin_agent_conversation.id"],
            name="fk_admin_agent_message_conversation_id_admin_agent_conversation",
            ondelete="CASCADE",
        ),
        Index("admin_agent_message_conversation_idx", "conversation_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    conversation_id = Column(UUID, nullable=False)
    # user / assistant / tool（设计 §10.1 只规定 role + content + tool_calls）
    role = Column(String(32), nullable=False, server_default=text("'user'::character varying"))
    content = Column(Text, nullable=False, server_default=text("''::text"))
    # assistant：本次 LLM 产出的 tool_calls；tool：回灌结果（含 name/tool_call_id/result）
    tool_calls = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    updated_at = Column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
```

在 `api/internal/model/__init__.py` 中，紧随 `admin_agent` 的导出处追加（按该文件既有风格，保持字母序）：

```python
from .admin_agent_conversation import AdminAgentConversation, AdminAgentMessage
```

并在 `__all__`（若该文件维护）中登记 `"AdminAgentConversation"`、`"AdminAgentMessage"`。

- [ ] **Step 5: 写迁移**

新建 `api/internal/migration/versions/x1a2b3c4d5e7_add_admin_agent_conversation.py`：

```python
"""add admin agent conversation/message tables and builtin_key

设计依据：docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md
§10.1（独立会话表）与 §10.3（预置 Agent）。

为什么必须独立表：用户端 `conversation` / `message` 没有 admin 标识列，
admin 侧只能靠 `invoke_from ∈ {debugger, schedule}` 约定区分（设计 §11 盘点）。
独立表把归属列（`admin_user_id`）显式化，避免继续依赖约定。

`admin_agent.builtin_key` 用**部分唯一索引**兜底预置 Agent 的幂等：
同一管理员下同一 builtin_key 至多一条，自建 Agent 为 NULL 不受约束。

Revision ID: x1a2b3c4d5e7
Revises: w1e2f3a4b5c6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "x1a2b3c4d5e7"
down_revision = "w1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "admin_agent",
        sa.Column("builtin_key", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "admin_agent_owner_builtin_uniq",
        "admin_agent",
        ["owner_admin_user_id", "builtin_key"],
        unique=True,
        postgresql_where=sa.text("builtin_key IS NOT NULL"),
    )

    op.create_table(
        "admin_agent_conversation",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("admin_agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "title",
            sa.String(length=255),
            server_default=sa.text("''::character varying"),
            nullable=False,
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP(0)"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP(0)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["admin_agent_id"],
            ["admin_agent.id"],
            name="fk_admin_agent_conversation_agent_id_admin_agent",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_agent_conversation_id"),
    )
    op.create_index(
        "admin_agent_conversation_agent_idx", "admin_agent_conversation", ["admin_agent_id"]
    )
    op.create_index(
        "admin_agent_conversation_admin_idx", "admin_agent_conversation", ["admin_user_id"]
    )

    op.create_table(
        "admin_agent_message",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            sa.String(length=32),
            server_default=sa.text("'user'::character varying"),
            nullable=False,
        ),
        sa.Column(
            "content", sa.Text(), server_default=sa.text("''::text"), nullable=False
        ),
        sa.Column(
            "tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP(0)"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP(0)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["admin_agent_conversation.id"],
            name="fk_admin_agent_message_conversation_id_admin_agent_conversation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_agent_message_id"),
    )
    op.create_index(
        "admin_agent_message_conversation_idx", "admin_agent_message", ["conversation_id"]
    )


def downgrade():
    op.drop_index("admin_agent_message_conversation_idx", table_name="admin_agent_message")
    op.drop_table("admin_agent_message")
    op.drop_index("admin_agent_conversation_admin_idx", table_name="admin_agent_conversation")
    op.drop_index("admin_agent_conversation_agent_idx", table_name="admin_agent_conversation")
    op.drop_table("admin_agent_conversation")
    op.drop_index("admin_agent_owner_builtin_uniq", table_name="admin_agent")
    op.drop_column("admin_agent", "builtin_key")
```

- [ ] **Step 6: 运行测试确认通过**

```bash
cd api && python -m pytest test/internal/migration/test_admin_agent_conversation_migration.py -q --no-header --no-cov
```

Expected: PASS（4 个用例）

- [ ] **Step 7: 运行迁移图守卫（必须仍是单 head）**

```bash
cd api && python -m pytest test/internal/migration -q --no-header --no-cov
```

Expected: PASS（含单 head 与无悬空 `down_revision` 断言）

- [ ] **Step 8: 提交**

```bash
git add api/internal/model/admin_agent.py api/internal/model/admin_agent_conversation.py api/internal/model/__init__.py api/internal/migration/versions/x1a2b3c4d5e7_add_admin_agent_conversation.py api/test/internal/migration/test_admin_agent_conversation_migration.py
git commit -m "feat(admin-agent): add conversation/message tables and builtin_key"
```

---

## Task 2: 会话与消息服务（归属隔离）

**Files:**
- Create: `api/internal/entity/admin_agent_chat_entity.py`
- Create: `api/internal/service/admin_agent_conversation_service.py`
- Test: `api/test/internal/service/test_admin_agent_conversation_service.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/test_admin_agent_conversation_service.py`：

```python
"""管理端 Agent 会话服务测试：归属隔离 + 消息追加/读取顺序。

归属隔离是安全边界：非创建者**不可**读写他人 Agent 的会话
（与 `AdminAgentService.get_agent` 同口径，设计 §2「仅创建者可用」）。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ForbiddenException, NotFoundException
from internal.service.admin_agent_conversation_service import (
    AdminAgentConversationService,
)


class _Query:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter_by(self, **kwargs):
        self._kwargs = kwargs
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _Session:
    def __init__(self, rows):
        self._rows = rows
        self.added = []

    def query(self, model):
        return _Query(self._rows)

    def add(self, obj):
        self.added.append(obj)


class _AutoCommit:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def _service(rows):
    service = AdminAgentConversationService.__new__(AdminAgentConversationService)
    session = _Session(rows)
    service.db = SimpleNamespace(session=session, auto_commit=lambda: _AutoCommit())
    service.session = session
    return service


def test_get_conversation_rejects_foreign_admin():
    owner = uuid4()
    conv = SimpleNamespace(id=uuid4(), admin_agent_id=uuid4(), admin_user_id=owner)
    service = _service([conv])

    with pytest.raises(ForbiddenException):
        service.get_conversation(conv.id, admin_user_id=uuid4())

    assert service.get_conversation(conv.id, admin_user_id=owner) is conv


def test_missing_conversation_raises_not_found():
    service = _service([])

    with pytest.raises(NotFoundException):
        service.get_conversation(uuid4(), admin_user_id=uuid4())


def test_create_conversation_persists_owner_and_title():
    admin_id = uuid4()
    agent_id = uuid4()
    service = _service([])

    conversation = service.create_conversation(
        admin_agent_id=agent_id, admin_user_id=admin_id, title="看看现状"
    )

    assert conversation.admin_agent_id == agent_id
    assert conversation.admin_user_id == admin_id
    assert conversation.title == "看看现状"
    assert len(service.session.added) == 1, "必须落库"


def test_append_message_persists_role_and_tool_calls():
    service = _service([])

    message = service.append_message(
        conversation_id=uuid4(),
        role="assistant",
        content="好的",
        tool_calls=[{"name": "admin_builtin_tool", "args": {"action": "list"}}],
    )

    assert message.role == "assistant"
    assert message.content == "好的"
    assert message.tool_calls[0]["name"] == "admin_builtin_tool"
    assert len(service.session.added) == 1


def test_append_message_rejects_illegal_role():
    service = _service([])

    with pytest.raises(ValueError):
        service.append_message(conversation_id=uuid4(), role="robot", content="x")
```

> **为什么替身要带 `auto_commit`/`session.add`**：服务实现用
> `with self.db.auto_commit(): self.db.session.add(...)`（与 `BaseService.create` 同形），
> 因此替身必须提供可用的上下文管理器与 `add`，否则测试会以 `AttributeError` 假失败。

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_conversation_service.py -q --no-header --no-cov
```

Expected: FAIL —— `ModuleNotFoundError: internal.service.admin_agent_conversation_service`

- [ ] **Step 3: 写枚举**

新建 `api/internal/entity/admin_agent_chat_entity.py`：

```python
"""管理端 Agent 对话链路的枚举（设计 §10.1）。"""
from enum import Enum


class AdminAgentMessageRole(str, Enum):
    """管理端会话消息角色。"""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AdminAgentChatEvent(str, Enum):
    """管理端对话 SSE 事件名。

    与用户端 `QueueEvent` 分开：两条链路的前端契约不同，共用枚举会让
    一侧新增事件意外改变另一侧契约。
    """

    MESSAGE = "message"   # 会话/消息 id 已建立
    TOOL = "tool"         # 一次板块工具调用及其结果
    ANSWER = "answer"     # 最终答复
    ERROR = "error"       # 链路异常（已可读化）
    END = "end"           # 流结束
```

- [ ] **Step 4: 写服务**

新建 `api/internal/service/admin_agent_conversation_service.py`：

```python
"""管理端 Agent 的会话与消息服务（设计 §10.1）。

只做会话/消息的持久化与归属校验，不感知 LLM 与板块工具。

**归属契约（勿弱化）**：归属校验**只**由 `get_conversation` / `list_conversations`
提供；`append_message` / `list_messages` 只收 `conversation_id`，**依赖调用方先调
`get_conversation`**。新增调用方跳过该前置，隔离即失效。

**类型契约**：`conversation_id` / `admin_user_id` / `admin_agent_id` 均为 `UUID`。
`admin["id"]` 由序列化层产出为**字符串**，**路由层负责 `UUID(str(...))` 归一化**
——传字符串会让属主比较恒不相等而误判 403（P1 已踩过的坑）。
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.entity.admin_agent_chat_entity import AdminAgentMessageRole
from internal.exception import ForbiddenException, NotFoundException
from internal.model import AdminAgentConversation, AdminAgentMessage
from pkg.sqlalchemy import SQLAlchemy


# 必须带 @inject：`support._get_service` 实为 `injector.get`，而 injector 只对
# `@inject` 标注过的类做构造注入——仅写 `db: SQLAlchemy` 注解**不够**。
# 历史事故：AdminAgentService / AdminChangeDraftService / 本服务曾漏 @inject，
# 使 /admin/agents/* 全部路由在生产上抛 CallError（测试因替换了 _get_service 而全绿）。
@inject
@dataclass
class AdminAgentConversationService:
    db: SQLAlchemy

    def list_conversations(self, *, admin_agent_id, admin_user_id) -> list[AdminAgentConversation]:
        return (
            self.db.session.query(AdminAgentConversation)
            .filter_by(admin_agent_id=admin_agent_id, admin_user_id=admin_user_id, is_deleted=False)
            .order_by(AdminAgentConversation.updated_at.desc())
            .all()
        )

    def get_conversation(self, conversation_id, *, admin_user_id) -> AdminAgentConversation:
        conversation = (
            self.db.session.query(AdminAgentConversation)
            .filter_by(id=conversation_id)
            .one_or_none()
        )
        if conversation is None:
            raise NotFoundException("会话不存在")
        if conversation.admin_user_id != admin_user_id:
            # 与 AdminAgentService.get_agent 同口径：非属主一律视为不存在，
            # 避免通过"报错差异"探测他人 Agent 的会话是否存在。
            raise ForbiddenException("无权访问该会话")
        return conversation

    def create_conversation(self, *, admin_agent_id, admin_user_id, title: str = "") -> AdminAgentConversation:
        with self.db.auto_commit():
            conversation = AdminAgentConversation(
                admin_agent_id=admin_agent_id,
                admin_user_id=admin_user_id,
                title=(title or "")[:255],
            )
            self.db.session.add(conversation)
        return conversation

    def append_message(
        self,
        *,
        conversation_id,
        role: str,
        content: str = "",
        tool_calls=None,
    ) -> AdminAgentMessage:
        AdminAgentMessageRole(role)  # 非法 role 直接报错，不落库
        with self.db.auto_commit():
            message = AdminAgentMessage(
                conversation_id=conversation_id,
                role=role,
                content=content or "",
                tool_calls=list(tool_calls or []),
            )
            self.db.session.add(message)
        return message

    def list_messages(self, *, conversation_id) -> list[AdminAgentMessage]:
        return (
            self.db.session.query(AdminAgentMessage)
            .filter_by(conversation_id=conversation_id)
            .order_by(AdminAgentMessage.created_at.asc())
            .all()
        )
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_conversation_service.py -q --no-header --no-cov
```

Expected: PASS（5 个用例）

- [ ] **Step 6: 提交**

```bash
git add api/internal/entity/admin_agent_chat_entity.py api/internal/service/admin_agent_conversation_service.py api/test/internal/service/test_admin_agent_conversation_service.py
git commit -m "feat(admin-agent): add conversation and message service with ownership isolation"
```

---

## Task 3: 板块工具的 LLM 适配（每板块一个工具）

**Files:**
- Create: `api/internal/service/admin_agent_chat_tools.py`
- Test: `api/test/internal/service/test_admin_agent_chat_tools.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/test_admin_agent_chat_tools.py`：

```python
"""板块工具的 LLM 适配测试（设计 §7.1）。

不变量：
- 工具数 == 已登记板块数（板块级聚合，不做端点级）；
- 工具名与 `BOARD_IDS` 一一对应，未登记板块不会出现；
- 权限/未登记拒绝**不抛给 LLM**，而是返回可读 JSON（让模型据实回报管理员）。
"""
from types import SimpleNamespace
from uuid import uuid4

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.service.admin_agent_chat_tools import build_board_tools


def _principal():
    return AdminAgentPrincipal(
        admin_user_id=uuid4(),
        agent_id=uuid4(),
        agent_name="运维 Agent",
        effective_permissions=frozenset({"builtin_tool:read", "builtin_tool:update"}),
        automation_policy={"builtin_tool": AutomationLevel.SUPERVISED},
    )


class _StubExecution:
    def __init__(self, error=None):
        self.calls = []
        self._error = error

    def run(self, principal, *, board, action, payload=None):
        self.calls.append({"board": board, "action": action, "payload": payload})
        if self._error is not None:
            raise self._error
        return {"outcome": "executed", "result": {"ok": True}, "draft_id": None}


def test_one_tool_per_registered_board():
    from internal.core.admin_agent_boards import BOARD_IDS

    tools = build_board_tools(_StubExecution(), _principal())

    assert [t.name for t in tools] == [f"admin_{b}" for b in BOARD_IDS]


def test_tool_forwards_board_action_and_payload():
    exec_svc = _StubExecution()
    tools = {t.name: t for t in build_board_tools(exec_svc, _principal())}
    tool = tools["admin_builtin_tool"]

    tool.invoke({"action": "list", "payload": {}})

    assert exec_svc.calls[0]["board"] == "builtin_tool"
    assert exec_svc.calls[0]["action"] == "list"


def test_permission_denial_is_returned_as_readable_json():
    import json

    exec_svc = _StubExecution(error=PermissionError("Agent 无权限执行 builtin_tool.list（需要 builtin_tool:read）"))
    tools = {t.name: t for t in build_board_tools(exec_svc, _principal())}

    payload = json.loads(tools["admin_builtin_tool"].invoke({"action": "list", "payload": {}}))

    assert payload["ok"] is False
    assert "无权限" in payload["error"]


def test_undeclared_action_is_returned_as_readable_json():
    import json

    exec_svc = _StubExecution(error=ValueError("板块 builtin_tool 未登记动作 nope（已登记: list, update_enabled, update_metadata）"))
    tools = {t.name: t for t in build_board_tools(exec_svc, _principal())}

    payload = json.loads(tools["admin_builtin_tool"].invoke({"action": "nope", "payload": {}}))

    assert payload["ok"] is False
    assert "未登记" in payload["error"]
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_chat_tools.py -q --no-header --no-cov
```

Expected: FAIL —— `ModuleNotFoundError: internal.service.admin_agent_chat_tools`

- [ ] **Step 3: 写实现**

新建 `api/internal/service/admin_agent_chat_tools.py`：

```python
"""把板块动作注册表暴露为「每板块一个」LangChain 工具（设计 §7.1）。

为什么不复用 `AssistantAgentService._build_assistant_runtime_tools`：
那是用户域工具的条件装配点（逐个 try + 功能开关），复用它只能靠黑名单
排除用户域工具，而黑名单对动态集合不完备——漏一个就是越权（设计 §6.1）。
本模块**只**为已登记板块生成工具，白名单式，边界可自证。

为什么拒绝不抛异常：工具的调用方是 LLM。抛异常会中断整轮对话，而
`PermissionError` / `ValueError` 都是"该动作不能做"的正常业务结论——
应作为**可读结果**回给模型，让它如实向管理员汇报（审计已由执行层写好）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, create_model

from internal.core.admin_agent_boards import boards as _boards
from internal.entity.admin_agent_entity import AdminAgentPrincipal

logger = logging.getLogger(__name__)

__all__ = ["build_board_tools", "tool_name_for_board"]


def tool_name_for_board(board: str) -> str:
    """板块 → LLM 工具名（LLM 工具名只允许字母/数字/下划线/连字符）。"""
    return f"admin_{board}"


def _make_args_schema(board: str, actions: list[str]):
    description = (
        f"要执行的动作，必须取自：{', '.join(actions)}。"
        "未登记的动作会被拒绝（fail closed）。"
    )
    return create_model(
        f"Admin{board.title().replace('_', '')}Args",
        action=(str, Field(..., description=description)),
        payload=(dict, Field(default_factory=dict, description="动作入参（按动作语义传）")),
    )


def _make_tool_class(board: str, actions: list[str]):
    schema = _make_args_schema(board, actions)
    tool_name = tool_name_for_board(board)

    class _BoardTool(BaseTool):
        name: str = tool_name
        description: str = (
            f"执行管理端「{board}」板块的治理动作。可选动作：{', '.join(actions)}。"
            "只读动作可直接执行；写动作按该板块的自动化级别可能转为待批准草稿。"
        )
        args_schema: type[BaseModel] = schema
        execution_service: Any = None
        principal: Any = None

        def _run(self, action: str = "", payload: dict | None = None, **kwargs: Any) -> str:
            try:
                result = self.execution_service.run(
                    self.principal, board=board, action=action, payload=payload or {}
                )
            except (PermissionError, ValueError) as exc:
                # 拒绝是正常业务结论：回可读结果，不中断对话（审计已由执行层记录）
                return json.dumps(
                    {"ok": False, "board": board, "action": action, "error": str(exc)},
                    ensure_ascii=False,
                )
            return json.dumps(
                {"ok": True, "board": board, **result}, ensure_ascii=False
            )

        async def _arun(self, action: str = "", payload: dict | None = None, **kwargs: Any) -> str:
            return self._run(action=action, payload=payload, **kwargs)

    return _BoardTool


def build_board_tools(execution_service, principal: AdminAgentPrincipal) -> list[BaseTool]:
    """为每个已登记板块构造一个绑定到该 principal 的工具。

    工具实例持有 principal，因此**不能**跨 Agent 复用或缓存。
    """
    from internal.core.admin_agent_boards import board_ids_of

    tools: list[BaseTool] = []
    for board in _boards():
        cls = _make_tool_class(board, board_ids_of(board))
        tools.append(cls(execution_service=execution_service, principal=principal))
    return tools
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_chat_tools.py -q --no-header --no-cov
```

Expected: PASS（4 个用例）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/admin_agent_chat_tools.py api/test/internal/service/test_admin_agent_chat_tools.py
git commit -m "feat(admin-agent): expose board actions as one LLM tool per board"
```

---

## Task 4: 系统提示词解析（prompt_key → 渲染）

**Files:**
- Create: `api/internal/service/admin_agent_prompt_service.py`
- Test: `api/test/internal/service/test_admin_agent_prompt_service.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/test_admin_agent_prompt_service.py`：

```python
"""管理端 Agent 系统提示词构造测试（AGENTS.md 强制规则）。

提示词内容必须来自 YAML seed / DB `prompt_template`，**不得**硬编码在 .py；
Agent 的 prompt_key 为空时回退到内置默认 `admin_agent_board_agent`。
"""
from types import SimpleNamespace
from uuid import uuid4

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.service.admin_agent_prompt_service import (
    DEFAULT_ADMIN_AGENT_PROMPT_KEY,
    AdminAgentPromptService,
)


def _principal():
    return AdminAgentPrincipal(
        admin_user_id=uuid4(),
        agent_id=uuid4(),
        agent_name="运维 Agent",
        effective_permissions=frozenset({"builtin_tool:read"}),
        automation_policy={"builtin_tool": AutomationLevel.SUPERVISED},
    )


def test_uses_agent_prompt_key_when_present():
    captured = {}

    def _get(content_key, variables):
        captured["key"] = content_key
        captured["variables"] = variables
        return "渲染后的提示词"

    service = AdminAgentPromptService()
    service._render_template = _get

    result = service.build_system_prompt(_principal(), prompt_key="ops_agent")

    assert result == "渲染后的提示词"
    assert captured["key"] == "ops_agent"
    assert captured["variables"]["agent_name"] == "运维 Agent"
    assert "builtin_tool:read" in captured["variables"]["granted_permissions"]


def test_falls_back_to_default_key_when_agent_has_none():
    captured = {}

    service = AdminAgentPromptService()
    service._render_template = lambda key, variables: captured.setdefault("key", key) or "x"

    service.build_system_prompt(_principal(), prompt_key=None)

    assert captured["key"] == DEFAULT_ADMIN_AGENT_PROMPT_KEY
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_prompt_service.py -q --no-header --no-cov
```

Expected: FAIL —— `ModuleNotFoundError: internal.service.admin_agent_prompt_service`

- [ ] **Step 3: 写实现**

新建 `api/internal/service/admin_agent_prompt_service.py`：

```python
"""管理端 Agent 的系统提示词构造（AGENTS.md 强制规则）。

提示词内容**只**从 `prompt_template` 表（由 YAML seed 同步）读取，
本模块只负责：
1. 解析 Agent 的 `prompt_key`（为空 → 内置默认）；
2. 用 `AdminAgentPrincipal` 填充变量（agent_name / granted_permissions / automation_policy）。

运行时读取顺序遵循 AGENTS.md：DB（admin 编辑过的 `source=custom`）> YAML seed。
该优先级与变量填充**已由** `PromptSyncService.get_prompt`（`@staticmethod`，
读全局 `db.session`）实现，故此处直接复用，不再自行解析。
"""
from __future__ import annotations

import logging

from internal.entity.admin_agent_entity import AdminAgentPrincipal

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_ADMIN_AGENT_PROMPT_KEY", "AdminAgentPromptService"]

# 兜底提示词 key（YAML: api/internal/core/prompts/admin_agent/board_agent.yaml）
DEFAULT_ADMIN_AGENT_PROMPT_KEY = "admin_agent_board_agent"


class AdminAgentPromptService:
    """无状态服务：提示词读取走 `PromptSyncService.get_prompt`（用全局 db）。

    不持有 db，因此可无参构造；`_render_template` 是测试替换点。
    """

    def build_system_prompt(self, principal: AdminAgentPrincipal, *, prompt_key: str | None) -> str:
        key = str(prompt_key or "").strip() or DEFAULT_ADMIN_AGENT_PROMPT_KEY
        variables = {
            "agent_name": principal.agent_name,
            "granted_permissions": self._format_permissions(principal),
            "automation_policy": self._format_policy(principal),
        }
        return self._render_template(key, variables)

    # ------------------------------------------------------------------
    # 可替换点（测试替换，避免依赖 DB）
    # ------------------------------------------------------------------

    def _render_template(self, key: str, variables: dict) -> str:
        """按 key 取提示词并填充变量；取不到内容时抛错，**不**返回空串。

        静默空串会让 Agent 失去全部行为约束（等于没有系统提示词），
        属于"看起来能跑、实际无边界"的隐患，必须显式失败。

        `PromptSyncService.get_prompt` 已实现「custom > catalog」优先级与
        `content.format(**variables)` 变量填充，故此处不再自行 replace。
        """
        from internal.service.prompt_sync_service import PromptSyncService

        content = PromptSyncService.get_prompt(key, **variables)
        if not content:
            raise RuntimeError(
                f"管理端 Agent 提示词缺失：{key}（检查 prompts/index.yaml 登记与启动同步）"
            )
        return content

    @staticmethod
    def _format_permissions(principal: AdminAgentPrincipal) -> str:
        codes = sorted(principal.effective_permissions)
        return "、".join(codes) if codes else "（无：管理员尚未下放任何权限）"

    @staticmethod
    def _format_policy(principal: AdminAgentPrincipal) -> str:
        if not principal.automation_policy:
            return "（未配置：全部板块按 supervised 处理）"
        return "、".join(
            f"{board}={level.value}" for board, level in sorted(principal.automation_policy.items())
        )
```

> **已核实（勿再改）**：`PromptSyncService.get_prompt(prompt_key, **variables)`
> 是 **`@staticmethod`**，读全局 `db.session`，内建「custom > catalog」优先级与
> `content.format(**variables)` 填充（`api/internal/service/prompt_sync_service.py`）。
> `PromptSyncService` **构造无参**——`PromptSyncService(self.db)` 是错的。
> 变量填充失败（KeyError）时它返回**原始内容**并记 warning，故提示词里
> 不得出现除 `agent_name` / `granted_permissions` / `automation_policy`
> 以外的 `{...}` 占位符。

- [ ] **Step 4: 运行测试确认通过**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_prompt_service.py -q --no-header --no-cov
```

Expected: PASS（2 个用例）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/admin_agent_prompt_service.py api/test/internal/service/test_admin_agent_prompt_service.py
git commit -m "feat(admin-agent): build system prompt from prompt_template with principal variables"
```

---

## Task 5: 预置 Agent 与幂等补建

**Files:**
- Create: `api/internal/core/prompts/admin_agent/ops_agent.yaml`
- Create: `api/internal/core/prompts/admin_agent/marketing_agent.yaml`
- Modify: `api/internal/core/prompts/index.yaml`
- Create: `api/internal/service/admin_agent_builtin_agents.py`
- Test: `api/test/internal/service/test_admin_agent_builtin_agents.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/test_admin_agent_builtin_agents.py`：

```python
"""预置 Agent 幂等补建测试（设计 §10.3）。

关键不变量：
1. 幂等：重复调用不产生重复记录（靠 builtin_key 唯一索引兜底）；
2. **不下放权限**：预置 Agent 的 granted_permissions 必须为空——
   权限只能由管理员显式下放（设计 §4.3），系统预置不得绕过；
3. 未配置 automation_policy → 运行时按 supervised 处理（fail closed）。
"""
from types import SimpleNamespace
from uuid import uuid4

from internal.service.admin_agent_builtin_agents import (
    BUILTIN_ADMIN_AGENTS,
    AdminAgentBuiltinService,
)


class _Query:
    def __init__(self, rows):
        self._rows = list(rows)
        self._created = None

    def filter_by(self, **kwargs):
        self._kwargs = kwargs
        return self

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


def _service(existing=None):
    service = AdminAgentBuiltinService.__new__(AdminAgentBuiltinService)
    rows = list(existing or [])
    created = []

    class _Session:
        def query(self, model):
            return _Query(rows)

        def add(self, obj):
            created.append(obj)

    class _AutoCommit:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    service.db = SimpleNamespace(session=_Session(), auto_commit=lambda: _AutoCommit())
    service.created = created
    return service


def test_builtin_list_is_non_empty_and_keys_unique():
    keys = [item["builtin_key"] for item in BUILTIN_ADMIN_AGENTS]
    assert keys, "至少要有运维/运营两个预置 Agent"
    assert len(keys) == len(set(keys))


def test_ensure_creates_missing_agents_without_granting_permissions():
    admin_id = uuid4()
    service = _service(existing=[])

    service.ensure_builtin_agents(admin_id)

    assert len(service.created) == len(BUILTIN_ADMIN_AGENTS)
    for agent in service.created:
        assert agent.owner_admin_user_id == admin_id
        assert agent.granted_permissions == [], "预置 Agent 不得预置权限"
        assert agent.automation_policy == {}
        assert agent.enabled is True
        assert agent.builtin_key


def test_ensure_is_idempotent_when_all_exist():
    admin_id = uuid4()
    existing = [
        SimpleNamespace(builtin_key=item["builtin_key"], owner_admin_user_id=admin_id)
        for item in BUILTIN_ADMIN_AGENTS
    ]
    service = _service(existing=existing)

    service.ensure_builtin_agents(admin_id)

    assert service.created == [], "已存在时必须零写入"
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_builtin_agents.py -q --no-header --no-cov
```

Expected: FAIL —— `ModuleNotFoundError: internal.service.admin_agent_builtin_agents`

- [ ] **Step 3: 写两个预置人格提示词**

新建 `api/internal/core/prompts/admin_agent/ops_agent.yaml`：

```yaml
# 预置「运维 Agent」人格提示词。
# 由 prompt_sync_service 启动时同步到 DB prompt_template（source=catalog）。
# admin 可创建 source=custom 副本覆盖，不会被 YAML 同步覆盖。

prompt_key: admin_agent_ops_agent
name: 管理端运维 Agent
category: admin_agent
description: 预置人格：面向系统运维与工具治理，先查现状再动手，写操作尊重自动化级别
variables:
  agent_name: Agent 名称（运行时填充）
  granted_permissions: 该 Agent 生效权限清单（运行时填充）
  automation_policy: 各板块自动化级别（运行时填充）
content: |
  你是「{agent_name}」，管理后台的**运维治理** Agent，服务于系统稳定性与工具治理。

  # 职责边界
  1. 只处理运维与工具治理相关板块（内置工具、模型池、编排开关、公共能力配置等）；
  2. 你**不能**接触任何用户端（C 端）内容，也**不能**修改管理员账号、角色、权限点；
  3. 你**只能**操作被显式授权的板块与动作——授权清单如下。

  # 当前生效权限
  {granted_permissions}

  # 各板块自动化级别
  {automation_policy}

  级别含义：
  - `supervised`：变更先成为**待批准草稿**，管理员点「应用」后才生效；
  - `autonomous`：变更**直接生效**（删除类进回收站，写操作有快照可回滚）；
  - `blocked`：该板块熔断，即使有权限也不执行。

  # 工作方式
  1. 动配置前**先读现状**（`list` 类动作），不要凭猜测改；
  2. 一次只做一个明确变更，说明**为什么**改、改前改后是什么；
  3. 被拒绝时如实回报原因，不要反复重试同一动作；
  4. 收尾汇报：改了哪个板块的哪个对象、结果、如何回滚。

  # 硬约束
  1. 不臆造板块或动作名——只使用授权清单内的板块与动作；
  2. 不在未读现状时执行删除或启停；
  3. 管理员已否决的变更不再提第二次（除非情况变化并说明）。
```

新建 `api/internal/core/prompts/admin_agent/marketing_agent.yaml`：

```yaml
# 预置「运营 Agent」人格提示词。
# 由 prompt_sync_service 启动时同步到 DB prompt_template（source=catalog）。

prompt_key: admin_agent_marketing_agent
name: 管理端运营 Agent
category: admin_agent
description: 预置人格：面向套餐/兑换码/分销/公告等运营配置，改前先查、改后必报
variables:
  agent_name: Agent 名称（运行时填充）
  granted_permissions: 该 Agent 生效权限清单（运行时填充）
  automation_policy: 各板块自动化级别（运行时填充）
content: |
  你是「{agent_name}」，管理后台的**运营配置** Agent，服务于套餐、兑换码、
  分销与对外公告等运营侧配置的维护。

  # 职责边界
  1. 只处理运营相关板块（套餐与权益、兑换码、分销与返佣、公共能力开关等）；
  2. 你**不能**接触用户端内容，也**不能**修改管理员账号、角色、权限点；
  3. 涉及**计费与资金**的字段（价格、返佣比例、额度）默认按最高谨慎级别处理：
     即使板块为 `autonomous`，也要先说明影响面再动手。

  # 当前生效权限
  {granted_permissions}

  # 各板块自动化级别
  {automation_policy}

  级别含义同运维 Agent：`supervised` 产待批准草稿、`autonomous` 直接生效、
  `blocked` 熔断。

  # 工作方式
  1. 改价格/额度前**先读现状**，并明确说出"改前 → 改后"的差异；
  2. 一次只改一个对象；批量改动拆成多次并逐次汇报；
  3. 被拒绝时如实回报，不重试同一动作；
  4. 收尾汇报：对象、前后值、影响面、回滚方式。

  # 硬约束
  1. 不臆造板块或动作名；
  2. 不在未读现状时改价格、额度或返佣；
  3. 不向外部泄露任何成本、返佣与结算口径。
```

在 `api/internal/core/prompts/index.yaml` 末尾追加：

```yaml

- key: admin_agent_ops_agent
  category: admin_agent
  file: admin_agent/ops_agent.yaml

- key: admin_agent_marketing_agent
  category: admin_agent
  file: admin_agent/marketing_agent.yaml
```

- [ ] **Step 4: 写预置服务**

新建 `api/internal/service/admin_agent_builtin_agents.py`：

```python
"""预置（内置）管理端 Agent 的幂等补建（设计 §10.3）。

为什么不复用 Agent 池：池成员是用户端 `app`（`agent_pool_config.app_id`
NOT NULL）+ 启停/健康元数据，**没有任何授权字段**；而治理 Agent 的授权
（`granted_permissions` / `automation_policy`）挂在 `admin_agent` 表。
把治理 Agent 塞进池要么伪造 `app` 行（正好落进用户端候选收集域 = 污染），
要么改池的数据模型。故预置 Agent 落 `admin_agent`，池继续只做用户端路由。

权限策略：预置**不下放任何权限**（`granted_permissions=[]`）。权限必须由
管理员显式下放（设计 §4.3「显式下放」）；`automation_policy={}` 由
`automation_level_for` 兜底为 `supervised`（fail closed）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from injector import inject

from internal.model import AdminAgent
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

# 预置清单。新增项只需在此追加 + 在 prompts/index.yaml 登记对应 prompt_key。
BUILTIN_ADMIN_AGENTS: list[dict[str, str]] = [
    {
        "builtin_key": "ops_agent",
        "name": "运维 Agent",
        "description": "系统运维与工具治理：先查现状再动手，写操作按自动化级别分流",
        "prompt_key": "admin_agent_ops_agent",
    },
    {
        "builtin_key": "marketing_agent",
        "name": "运营 Agent",
        "description": "运营配置维护：套餐/兑换码/分销等，涉及计费字段最高谨慎",
        "prompt_key": "admin_agent_marketing_agent",
    },
]


# 必须带 @inject（否则 `a._get_service(AdminAgentBuiltinService)` 运行时 CallError）
@inject
@dataclass
class AdminAgentBuiltinService:
    db: SQLAlchemy

    def ensure_builtin_agents(self, admin_user_id) -> int:
        """为该管理员补齐缺失的预置 Agent，返回新建条数（幂等）。

        并发安全：靠 `admin_agent_owner_builtin_uniq`（部分唯一索引）兜底；
        冲突时忽略该条（另一个请求已建），不抛错。
        """
        existing = {
            row.builtin_key
            for row in self.db.session.query(AdminAgent)
            .filter_by(owner_admin_user_id=admin_user_id)
            .all()
            if getattr(row, "builtin_key", None)
        }
        created = 0
        for item in BUILTIN_ADMIN_AGENTS:
            if item["builtin_key"] in existing:
                continue
            try:
                with self.db.auto_commit():
                    self.db.session.add(
                        AdminAgent(
                            owner_admin_user_id=admin_user_id,
                            name=item["name"],
                            description=item["description"],
                            prompt_key=item["prompt_key"],
                            granted_permissions=[],
                            automation_policy={},
                            budget_config={},
                            builtin_key=item["builtin_key"],
                            enabled=True,
                        )
                    )
                created += 1
            except Exception:
                # 并发下已被另一请求建成：回滚该条并继续
                logger.info(
                    "预置 Agent 已存在（并发），跳过 builtin_key=%s", item["builtin_key"]
                )
                self.db.session.rollback()
        return created
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_builtin_agents.py -q --no-header --no-cov
```

Expected: PASS（3 个用例）

- [ ] **Step 6: 校验提示词 YAML 能被解析器读懂**

```bash
cd api && python -c "import yaml,pathlib; [print(p.name, yaml.safe_load(p.read_text(encoding='utf-8'))['prompt_key']) for p in pathlib.Path('internal/core/prompts/admin_agent').glob('*.yaml')]"
```

Expected: 打印三个文件的 `prompt_key`（含新增两个），无异常

- [ ] **Step 7: 提交**

```bash
git add api/internal/core/prompts/admin_agent/ops_agent.yaml api/internal/core/prompts/admin_agent/marketing_agent.yaml api/internal/core/prompts/index.yaml api/internal/service/admin_agent_builtin_agents.py api/test/internal/service/test_admin_agent_builtin_agents.py
git commit -m "feat(admin-agent): seed preset agent personas and idempotent builtin agents"
```

---

## Task 6: 对话编排服务（取模型 → 工具循环 → 落库 → SSE）

**Files:**
- Create: `api/internal/service/admin_agent_chat_service.py`
- Test: `api/test/internal/service/test_admin_agent_chat_service.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/test_admin_agent_chat_service.py`：

```python
"""管理端对话编排测试（设计 §6.1）。

用替身隔离真实 LLM 与 DB，只验证编排契约：
1. 身份：非属主/停用 Agent 直接拒绝（不进模型）；
2. 工具循环：LLM 请求工具 → 执行 → 回灌 → 产出最终答复；
3. 落库：user / assistant(tool_calls) / tool 三类消息都要落；
4. 上限保护：LLM 反复请求工具时中止，不无限循环。
"""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.exception import FailException
from internal.service.admin_agent_chat_service import AdminAgentChatService


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def invoke(self, args):
        self.calls.append(args)
        return json.dumps({"ok": True, "board": "builtin_tool", "outcome": "executed"})


class _FakeLLM:
    """按脚本产出若干轮 AI 消息，最后一轮不带 tool_calls。"""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.bound_tools = []

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def invoke(self, messages):
        return self._scripted.pop(0)


def _principal():
    return AdminAgentPrincipal(
        admin_user_id=uuid4(),
        agent_id=uuid4(),
        agent_name="运维 Agent",
        effective_permissions=frozenset({"builtin_tool:read"}),
        automation_policy={"builtin_tool": AutomationLevel.AUTONOMOUS},
    )


def _service(principal, llm, tools):
    service = AdminAgentChatService.__new__(AdminAgentChatService)
    service.get_principal = lambda **kwargs: principal
    service._build_model = lambda: llm
    service._build_tools = lambda p: tools
    service._build_system_prompt = lambda p, prompt_key: "系统提示词"
    service._persist = []
    service.append_message = lambda **kwargs: service._persist.append(kwargs) or SimpleNamespace(id=uuid4())
    service._history_for = lambda conversation_id: []
    service._resolve_conversation = lambda **kwargs: SimpleNamespace(id=uuid4())
    # 必须一并替换 `_load_agent`：真实实现会经 AdminAgentService 触库
    service._load_agent = lambda agent_id, admin_user_id: SimpleNamespace(prompt_key=None)
    return service


def test_tool_loop_executes_tool_and_returns_answer():
    llm = _FakeLLM(
        [
            SimpleNamespace(content="", tool_calls=[{"name": "admin_builtin_tool", "args": {"action": "list"}, "id": "c1"}]),
            SimpleNamespace(content="已查看现状：1 个工具处于启用状态。", tool_calls=[]),
        ]
    )
    tool = _FakeTool("admin_builtin_tool")
    service = _service(_principal(), llm, [tool])

    frames = list(
        service.chat(
            agent_id=uuid4(),
            admin_user_id=uuid4(),
            admin_permissions=["builtin_tool:read"],
            query="看看内置工具现状",
        )
    )

    assert tool.calls == [{"action": "list"}]
    body = "".join(frames)
    assert "已查看现状" in body
    # 三类消息都要落库
    roles = [item["role"] for item in service._persist]
    assert roles == ["user", "tool", "assistant"]


def test_unknown_agent_raises_without_calling_model():
    service = _service(None, _FakeLLM([]), [])
    service.get_principal = lambda **kwargs: None

    with pytest.raises(FailException):
        list(
            service.chat(
                agent_id=uuid4(),
                admin_user_id=uuid4(),
                admin_permissions=[],
                query="hi",
            )
        )


def test_tool_loop_aborts_on_excessive_iterations():
    looping = [
        SimpleNamespace(content="", tool_calls=[{"name": "admin_builtin_tool", "args": {}, "id": f"c{i}"}])
        for i in range(20)
    ]
    service = _service(_principal(), _FakeLLM(looping), [_FakeTool("admin_builtin_tool")])

    with pytest.raises(FailException):
        list(
            service.chat(
                agent_id=uuid4(),
                admin_user_id=uuid4(),
                admin_permissions=["builtin_tool:read"],
                query="循环",
            )
        )
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_chat_service.py -q --no-header --no-cov
```

Expected: FAIL —— `ModuleNotFoundError: internal.service.admin_agent_chat_service`

- [ ] **Step 3: 写实现**

新建 `api/internal/service/admin_agent_chat_service.py`：

```python
"""管理端 Agent 对话编排（设计 §6.1：新建独立链路）。

链路：解析 principal（三重交集实时重算）→ 取/建会话 → 落 user 消息 →
构造系统提示词 → 装配板块工具 → 工具循环 → 落库 → SSE 帧。

为什么手写循环而不用用户端 `FunctionCallAgent`：后者依赖用户域
`AgentConfig` + `app/account` 上下文与 LangGraph 状态机（含知识库、记忆、
确认流等用户域节点）。复用会把用户域语义带进管理端链路，而设计 §6.1 的
前提正是"两条链路不交叉"。此处只需要「LLM ⇄ 板块工具」两节点，故显式实现
并有轮次上限保护。

SSE 帧格式与用户端一致（`event: <name>\ndata:<json>\n\n`），便于复用
`support._sse_response`。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Generator

from injector import inject

from internal.entity.admin_agent_chat_entity import (
    AdminAgentChatEvent,
    AdminAgentMessageRole,
)
from internal.entity.admin_agent_entity import AdminAgentPrincipal
from internal.exception import FailException
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

# 工具循环上限：防 LLM 陷入"反复调同一工具"烧钱（预算闸门属 P4）
MAX_TOOL_ITERATIONS = 6

FEATURE_KEY = "admin_agent"


# 必须带 @inject（否则 `a._get_service(AdminAgentChatService)` 运行时 CallError）
@inject
@dataclass
class AdminAgentChatService:
    db: SQLAlchemy

    # ------------------------------------------------------------------
    # 主链路
    # ------------------------------------------------------------------

    def chat(
        self,
        *,
        agent_id,
        admin_user_id,
        admin_permissions,
        query: str,
        conversation_id=None,
    ) -> Generator[str, None, None]:
        """执行一轮对话，逐帧 yield SSE 字符串。"""
        text = str(query or "").strip()
        if not text:
            yield self._frame(AdminAgentChatEvent.ERROR, {"error": "消息不能为空"})
            return

        principal = self.get_principal(
            agent_id=agent_id,
            admin_user_id=admin_user_id,
            admin_permissions=admin_permissions,
        )
        if principal is None:
            raise FailException("Agent 不存在或不可用")

        conversation = self._resolve_conversation(
            admin_agent_id=principal.agent_id,
            admin_user_id=admin_user_id,
            conversation_id=conversation_id,
            title=text[:50],
        )
        yield self._frame(
            AdminAgentChatEvent.MESSAGE, {"conversation_id": str(conversation.id)}
        )

        self.append_message(
            conversation_id=conversation.id, role=AdminAgentMessageRole.USER.value, content=text
        )

        agent = self._load_agent(principal.agent_id, admin_user_id)
        tools = self._build_tools(principal)
        system_prompt = self._build_system_prompt(principal, getattr(agent, "prompt_key", None))
        llm = self._build_model()

        try:
            answer, tool_events = self._run_tool_loop(
                llm=llm,
                system_prompt=system_prompt,
                history=self._history_for(conversation.id),
                tools=tools,
                on_tool=lambda event: self.append_message(
                    conversation_id=conversation.id,
                    role=AdminAgentMessageRole.TOOL.value,
                    content=json.dumps(event, ensure_ascii=False),
                    tool_calls=[event],
                ),
            )
        except FailException as exc:
            yield self._frame(AdminAgentChatEvent.ERROR, {"error": str(exc)})
            raise
        except Exception as exc:
            logger.exception("管理端 Agent 对话失败 agent_id=%s", principal.agent_id)
            yield self._frame(AdminAgentChatEvent.ERROR, {"error": f"对话失败：{exc}"})
            return

        for event in tool_events:
            yield self._frame(AdminAgentChatEvent.TOOL, event)

        self.append_message(
            conversation_id=conversation.id,
            role=AdminAgentMessageRole.ASSISTANT.value,
            content=answer,
            tool_calls=[e["call"] for e in tool_events],
        )
        yield self._frame(AdminAgentChatEvent.ANSWER, {"answer": answer})
        yield self._frame(AdminAgentChatEvent.END, {})

    # ------------------------------------------------------------------
    # 工具循环
    # ------------------------------------------------------------------

    def _run_tool_loop(self, *, llm, system_prompt: str, history, tools, on_tool) -> tuple[str, list[dict]]:
        from langchain_core.messages import SystemMessage, ToolMessage

        messages: list[Any] = [SystemMessage(content=system_prompt), *history]
        tools_by_name = {tool.name: tool for tool in tools}
        bound = llm.bind_tools(tools) if tools else llm
        tool_events: list[dict] = []

        for _ in range(MAX_TOOL_ITERATIONS):
            ai = bound.invoke(messages)
            messages.append(ai)
            calls = list(getattr(ai, "tool_calls", None) or [])
            if not calls:
                return str(getattr(ai, "content", "") or ""), tool_events

            for call in calls:
                name = str(call.get("name") or "")
                tool = tools_by_name.get(name)
                if tool is None:
                    result = json.dumps({"ok": False, "error": f"未知工具：{name}"}, ensure_ascii=False)
                else:
                    result = tool.invoke(call.get("args") or {})
                event = {
                    "call": {"name": name, "args": call.get("args") or {}, "id": call.get("id") or ""},
                    "result": result,
                }
                tool_events.append(event)
                on_tool(event)
                messages.append(
                    ToolMessage(
                        content=result,
                        tool_call_id=call.get("id") or "",
                        name=name,
                    )
                )
        raise FailException(
            f"Agent 工具调用超过 {MAX_TOOL_ITERATIONS} 轮仍未收敛，已中止（疑似循环）"
        )

    # ------------------------------------------------------------------
    # 可替换点（测试替换，避免真实 LLM / DB / 提示词）
    # ------------------------------------------------------------------

    def _build_model(self):
        from internal.service.language_model_service import LanguageModelService

        return LanguageModelService.get_feature_model(FEATURE_KEY)

    def _build_tools(self, principal: AdminAgentPrincipal):
        from internal.service.admin_agent_board_tools import BoardToolExecutor
        from internal.service.admin_agent_chat_tools import build_board_tools

        return build_board_tools(BoardToolExecutor(), principal)

    def _build_system_prompt(self, principal: AdminAgentPrincipal, prompt_key) -> str:
        from internal.service.admin_agent_prompt_service import AdminAgentPromptService

        return AdminAgentPromptService().build_system_prompt(
            principal, prompt_key=prompt_key
        )

    def get_principal(self, *, agent_id, admin_user_id, admin_permissions):
        from internal.service.admin_agent_service import AdminAgentService

        return AdminAgentService(db=self.db).get_principal(
            agent_id=agent_id,
            admin_user_id=admin_user_id,
            admin_permissions=admin_permissions,
        )

    def append_message(self, *, conversation_id, role, content="", tool_calls=None):
        from internal.service.admin_agent_conversation_service import (
            AdminAgentConversationService,
        )

        return AdminAgentConversationService(self.db).append_message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
        )

    def _resolve_conversation(self, *, admin_agent_id, admin_user_id, conversation_id, title):
        """取既有会话（校验归属）或新建会话。"""
        from internal.service.admin_agent_conversation_service import (
            AdminAgentConversationService,
        )

        conversations = AdminAgentConversationService(self.db)
        if conversation_id:
            return conversations.get_conversation(
                conversation_id, admin_user_id=admin_user_id
            )
        return conversations.create_conversation(
            admin_agent_id=admin_agent_id, admin_user_id=admin_user_id, title=title
        )

    def _load_agent(self, agent_id, admin_user_id):
        from internal.service.admin_agent_service import AdminAgentService

        return AdminAgentService(db=self.db).get_agent(
            agent_id=agent_id, admin_user_id=admin_user_id
        )

    def _history_for(self, conversation_id):
        """把已落库的消息还原为 LangChain 消息序列（供多轮上下文）。"""
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from internal.service.admin_agent_conversation_service import (
            AdminAgentConversationService,
        )

        rows = AdminAgentConversationService(self.db).list_messages(
            conversation_id=conversation_id
        )
        history: list[Any] = []
        for row in rows:
            if row.role == AdminAgentMessageRole.USER.value:
                history.append(HumanMessage(content=row.content or ""))
            elif row.role == AdminAgentMessageRole.ASSISTANT.value:
                history.append(AIMessage(content=row.content or ""))
            elif row.role == AdminAgentMessageRole.TOOL.value and row.tool_calls:
                first = row.tool_calls[0]
                call = first.get("call") or {}
                history.append(
                    ToolMessage(
                        content=first.get("result") or "",
                        tool_call_id=call.get("id") or "",
                        name=call.get("name") or "",
                    )
                )
        return history

    @staticmethod
    def _frame(event: AdminAgentChatEvent, payload: dict) -> str:
        return f"event: {event.value}\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_chat_service.py -q --no-header --no-cov
```

Expected: PASS（3 个用例）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/admin_agent_chat_service.py api/test/internal/service/test_admin_agent_chat_service.py
git commit -m "feat(admin-agent): add conversation orchestration with tool loop and SSE"
```

---

## Task 7: `admin_agent` feature 计费注册

**Files:**
- Modify: `api/internal/service/public_ai_feature_service.py`
- Test: `api/test/internal/service/test_admin_agent_feature_registration.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/internal/service/test_admin_agent_feature_registration.py`：

```python
"""admin_agent feature 注册守卫（AGENTS.md：公共 AI 配置必须走 admin 板块）。

管理端 Agent 的成本由系统承担（设计 §6.2：billable=False → system_borne），
但**必须**经 `_BUILTIN_FEATURES` 注册，让管理员能在
`/admin/public-ai-features` 为其绑定模型与档位——不得在业务代码里硬编码模型。
"""
from internal.service.public_ai_feature_service import PublicAIFeatureService


def _feature(feature_key):
    for item in PublicAIFeatureService._BUILTIN_FEATURES:
        if item["feature_key"] == feature_key:
            return item
    return None


def test_admin_agent_feature_registered():
    feature = _feature("admin_agent")

    assert feature is not None, "必须在 _BUILTIN_FEATURES 注册 admin_agent"
    assert feature["billable"] is False, "管理端 Agent 成本由系统承担（设计 §6.2）"
    assert feature["model_type"] == "chat"
    assert feature["fallback_tier"], "必须给 fallback_tier，避免未绑定时无法降级"


def test_feature_key_matches_chat_service_constant():
    from internal.service.admin_agent_chat_service import FEATURE_KEY

    assert FEATURE_KEY == "admin_agent"
    assert _feature(FEATURE_KEY) is not None
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_feature_registration.py -q --no-header --no-cov
```

Expected: FAIL —— `assert None is not None`

- [ ] **Step 3: 注册 feature**

在 `api/internal/service/public_ai_feature_service.py` 的 `_BUILTIN_FEATURES` 列表末尾追加：

```python
    {
        "feature_key": "admin_agent",
        "feature_name": "管理端 Agent 对话",
        "feature_category": "admin",
        "feature_description": "管理端 Agent 的对话与板块动作执行（受管理员监督的后台自动化）",
        "model_type": "chat",
        "fallback_tier": "3",  # 治理动作需要较强的工具调用能力
        "billable": False,     # 系统治理功能：system_borne，系统承担成本（设计 §6.2）
    },
```

> 若 `feature_category` 有枚举约束（实读 `public_ai_feature_service.py` 与
> `admin_public_ai_feature_schema.py` 确认），按既有取值选择（如 `routing`）；
> **不要**新增未登记的 category 值——前端分组与校验可能依赖它。

- [ ] **Step 4: 运行测试确认通过**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_feature_registration.py -q --no-header --no-cov
```

Expected: PASS（2 个用例）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/public_ai_feature_service.py api/test/internal/service/test_admin_agent_feature_registration.py
git commit -m "feat(admin-agent): register admin_agent public ai feature (system-borne)"
```

---

## Task 8: HTTP 入口（对话 SSE + 会话列表 + 消息列表）

**Files:**
- Create: `api/internal/schema/admin_agent_chat_schema.py`
- Modify: `api/app/http/admin_routes_7.py`
- Modify: `api/test/app/http/test_admin_agent_crud_routes.py`（补 `ensure_builtin_agents` 替身与断言）
- Test: `api/test/app/http/test_admin_agent_chat_routes.py`
- Test: `api/test/internal/service/test_admin_agent_builtin_agents.py`

- [ ] **Step 1: 写失败测试**

新建 `api/test/app/http/test_admin_agent_chat_routes.py`：

```python
"""管理端 Agent 对话路由测试。

只验证接线：
- 权限映射（chat POST → agent_pool:manage；会话/消息 GET → agent_pool:read）；
- `admin["id"]` 必须转 UUID 后交给服务（与 P1 的 invoke/drafts 同口径）；
- 服务层 `FailException` → 404/400 可读错误。
"""
import asyncio
from uuid import UUID, uuid4

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_7 import register_routes

register_routes(asgi_app.quart_app)


def _admin_ctx(admin_id, permissions):
    async def _fake(permission_code=None):
        return {"id": str(admin_id), "roles": ["operator"], "permissions": list(permissions)}, None

    return _fake


class _StubChatService:
    def __init__(self, frames=None, error=None):
        self.calls = []
        self._frames = frames or ['event: end\ndata:{}\n\n']
        self._error = error

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        for frame in self._frames:
            yield frame

    def list_conversations(self, **kwargs):
        self.calls.append(kwargs)
        return []

    def list_messages(self, **kwargs):
        self.calls.append(kwargs)
        return []


def _wire(monkeypatch, admin_id, permissions, svc):
    monkeypatch.setattr(support, "_resolve_admin_permission", _admin_ctx(admin_id, permissions))
    monkeypatch.setattr(support, "_get_service", lambda cls: svc)
    return svc


def _run(coro):
    return asyncio.run(coro)


class TestPermissionMapping:
    def test_chat_maps_to_manage(self):
        assert (
            support._admin_route_permission(
                "POST", f"/admin/agents/{uuid4()}/chat"
            )
            == "agent_pool:manage"
        )

    def test_conversations_maps_to_read(self):
        assert (
            support._admin_route_permission(
                "GET", f"/admin/agents/{uuid4()}/conversations"
            )
            == "agent_pool:read"
        )


class TestChatEndpoint:
    def test_chat_passes_uuid_admin_user_id(self, monkeypatch):
        admin_id = uuid4()
        svc = _wire(monkeypatch, admin_id, ["agent_pool:manage"], _StubChatService())

        async def _go():
            client = asgi_app.quart_app.test_client()
            return await client.post(
                f"/admin/agents/{uuid4()}/chat", json={"query": "看看现状"}
            )

        resp = _run(_go())

        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert isinstance(svc.calls[0]["admin_user_id"], UUID)
        assert svc.calls[0]["admin_user_id"] == admin_id
        assert svc.calls[0]["query"] == "看看现状"
```

- [ ] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/app/http/test_admin_agent_chat_routes.py -q --no-header --no-cov
```

Expected: FAIL —— 404（路由不存在）

- [ ] **Step 3: 写 schema**

新建 `api/internal/schema/admin_agent_chat_schema.py`：

```python
"""管理端 Agent 对话/会话/消息 schema。"""
from marshmallow import Schema, fields


class AdminAgentChatReq(Schema):
    query = fields.String(required=True)
    conversation_id = fields.String(load_default=None, allow_none=True)


class AdminAgentConversationResp(Schema):
    id = fields.String()
    admin_agent_id = fields.String()
    title = fields.String()
    created_at = fields.Integer(allow_none=True)
    updated_at = fields.Integer(allow_none=True)


class AdminAgentConversationListResp(Schema):
    items = fields.List(fields.Nested(AdminAgentConversationResp), dump_default=[])


class AdminAgentChatMessageResp(Schema):
    id = fields.String()
    role = fields.String()
    content = fields.String()
    tool_calls = fields.List(fields.Dict(), dump_default=[])
    created_at = fields.Integer(allow_none=True)


class AdminAgentChatMessageListResp(Schema):
    items = fields.List(fields.Nested(AdminAgentChatMessageResp), dump_default=[])
```

- [ ] **Step 4: 写路由**

在 `api/app/http/admin_routes_7.py` 的 `admin_agent_delete` 之后、`admin_customer_user_handler` 注释块之前插入：

```python
    @quart_app.post("/admin/agents/<uuid:agent_id>/chat")
    async def admin_agent_chat(agent_id):
        """与某个管理端 Agent 对话（SSE 流式）。

        路由只做接线：把当前管理员的**实时权限**与查询交给
        `AdminAgentChatService.chat`，由它完成 principal → 会话 → 提示词
        → 工具循环 → 落库，并逐帧 yield SSE。
        """
        from app.http import asgi_app as a

        admin, err = await a._resolve_admin_permission("agent_pool:manage")
        if err is not None:
            return err

        from internal.schema.admin_agent_chat_schema import AdminAgentChatReq
        from internal.service.admin_agent_chat_service import AdminAgentChatService
        from uuid import UUID

        body = await request.get_json(force=True, silent=True) or {}
        form = AdminAgentChatReq()
        try:
            req = form.load(body)
        except Exception as exc:
            return a._json_resp(
                code="validate_error", message=f"参数错误: {exc}", status=400
            )

        # 同 invoke/drafts：服务契约是 UUID，传字符串会让属主比较恒不相等
        admin_user_id = UUID(str(admin.get("id")))
        admin_permissions = list(admin.get("permissions") or [])
        conversation_id = req.get("conversation_id") or None

        generator = a._get_service(AdminAgentChatService).chat(
            agent_id=agent_id,
            admin_user_id=admin_user_id,
            admin_permissions=admin_permissions,
            query=req["query"],
            conversation_id=conversation_id,
        )
        return a._sse_response(generator)

    @quart_app.get("/admin/agents/<uuid:agent_id>/conversations")
    async def admin_agent_conversations(agent_id):
        """列出某 Agent 的会话（仅创建者可见）。"""
        from app.http import asgi_app as a

        admin, err = await a._resolve_admin_permission("agent_pool:read")
        if err is not None:
            return err

        from internal.schema.admin_agent_chat_schema import (
            AdminAgentConversationListResp,
        )
        from internal.service.admin_agent_service import AdminAgentService
        from internal.service.admin_agent_conversation_service import (
            AdminAgentConversationService,
        )
        from uuid import UUID

        admin_user_id = UUID(str(admin.get("id")))

        def _run():
            # 先校验 Agent 归属（非属主 → PermissionError）
            a._get_service(AdminAgentService).get_agent(
                agent_id=agent_id, admin_user_id=admin_user_id
            )
            return a._get_service(AdminAgentConversationService).list_conversations(
                admin_agent_id=agent_id, admin_user_id=admin_user_id
            )

        try:
            rows = await a._to_thread(_run)
        except PermissionError as exc:
            return a._json_resp(code="forbidden", message=str(exc), status=403)
        resp = AdminAgentConversationListResp()
        return a._ok(
            resp.dump(
                {
                    "items": [
                        {
                            "id": str(row.id),
                            "admin_agent_id": str(row.admin_agent_id),
                            "title": row.title,
                            "created_at": _timestamp(row.created_at),
                            "updated_at": _timestamp(row.updated_at),
                        }
                        for row in rows
                    ]
                }
            )
        )

    @quart_app.get("/admin/agents/conversations/<uuid:conversation_id>/messages")
    async def admin_agent_conversation_messages(conversation_id):
        """列出某会话的消息（仅会话归属管理员可见）。"""
        from app.http import asgi_app as a

        admin, err = await a._resolve_admin_permission("agent_pool:read")
        if err is not None:
            return err

        from internal.exception import ForbiddenException, NotFoundException
        from internal.schema.admin_agent_chat_schema import (
            AdminAgentChatMessageListResp,
        )
        from internal.service.admin_agent_conversation_service import (
            AdminAgentConversationService,
        )
        from uuid import UUID

        admin_user_id = UUID(str(admin.get("id")))

        def _run():
            service = a._get_service(AdminAgentConversationService)
            service.get_conversation(conversation_id, admin_user_id=admin_user_id)
            return service.list_messages(conversation_id=conversation_id)

        try:
            rows = await a._to_thread(_run)
        except ForbiddenException as exc:
            return a._json_resp(code="forbidden", message=str(exc), status=403)
        except NotFoundException as exc:
            return a._json_resp(code="not_found", message=str(exc), status=404)
        resp = AdminAgentChatMessageListResp()
        return a._ok(
            resp.dump(
                {
                    "items": [
                        {
                            "id": str(row.id),
                            "role": row.role,
                            "content": row.content,
                            "tool_calls": list(row.tool_calls or []),
                            "created_at": _timestamp(row.created_at),
                        }
                        for row in rows
                    ]
                }
            )
        )
```

并在文件的模块级辅助函数区（紧邻 `_dump_agent`）追加：

```python
def _timestamp(value):
    from internal.lib.helper import datetime_to_timestamp

    return datetime_to_timestamp(value)
```

**同时修改既有 `admin_agent_list`（`GET /admin/agents`）以接线 `ensure_builtin_agents`**
——否则 `ensure_builtin_agents` 全仓无调用方（正是 AGENTS.md 禁止的"无派发点"断链）。
把该路由的 `_run` 改为"先补建、再列出"：

```python
        def _run():
            # 预置 Agent 幂等补建：首次打开列表即补齐缺失的内置 Agent
            a._get_service(AdminAgentBuiltinService).ensure_builtin_agents(admin_user_id)
            return a._get_service(AdminAgentService).list_agents(admin_user_id=admin_user_id)
```

并在该路由的局部 import 区加入：

```python
        from internal.service.admin_agent_builtin_agents import AdminAgentBuiltinService
```

**同步更新既有测试 `api/test/app/http/test_admin_agent_crud_routes.py`**：其 `_StubAgentService` 需要新增
`ensure_builtin_agents(self, admin_user_id)` 记录器（否则路由调用会 `AttributeError`），
并新增一条断言：

```python
    def test_list_ensures_builtin_agents_before_listing(self, monkeypatch):
        admin_id = uuid4()
        svc = _wire(
            monkeypatch,
            admin_id,
            ["agent_pool:read"],
            _StubAgentService(agents=[]),
        )

        resp, _ = _req("GET", "/admin/agents")

        assert resp.status_code == 200
        assert ("ensure_builtin_agents", {"admin_user_id": admin_id}) in svc.calls
        # 补建必须发生在列出之前
        assert [name for name, _ in svc.calls] == ["ensure_builtin_agents", "list_agents"]
```

> **已实测（勿改）**：`support._get_service(cls)` 实为 `injector.get(cls)`，而 injector
> **只对 `@inject` 标注过的类**做构造注入——仅写 `db: SQLAlchemy` 注解**不够**。
> 实测：`injector.get(AdminAgentService)` / `AdminChangeDraftService` /
> `AdminAgentConversationService` 在补 `@inject` **之前**全部抛 `CallError`，
> 导致 `/admin/agents/*` 全部路由生产上 500（测试替换了 `_get_service` 故全绿）。
> 因此：**本计划涉及的服务一律 `@inject` + `@dataclass` + `db: SQLAlchemy`**，
> 并且路由测试**至少有一条不替换 `_get_service`**（见
> `api/test/internal/service/test_admin_agent_di_construction.py`），否则断链会再次隐身。
> `_build_draft_service` 的 try/except 回退分支与「不是 @inject」注释现已过时（死代码），
> 本任务顺手清理为直接 `a._get_service(AdminChangeDraftService)`。

- [ ] **Step 5: 运行测试确认通过**

```bash
cd api && python -m pytest test/app/http/test_admin_agent_chat_routes.py -q --no-header --no-cov
```

Expected: PASS（3 个用例）

- [ ] **Step 6: 跑权限守卫（新路由必须已被登记）**

```bash
cd api && python -m pytest test/app/http/test_admin_rbac_guard.py -q --no-header --no-cov
```

Expected: PASS（`/admin/agents*` 前缀规则已覆盖 chat/conversations/messages）

- [ ] **Step 7: 提交**

```bash
git add api/internal/schema/admin_agent_chat_schema.py api/app/http/admin_routes_7.py api/test/app/http/test_admin_agent_chat_routes.py
git commit -m "feat(admin-agent): add chat SSE, conversation and message endpoints"
```

---

## Task 9: 文档同步

**Files:**
- Modify: `docs/api/admin-agents-api.md`
- Modify: `docs/prd/execution-roadmap.md`
- Modify: `docs/prd/modules/01-agent-tool-pool.md`

- [ ] **Step 1: `docs/api/admin-agents-api.md` 增对话与会话契约**

在「## 5. 待应用变更草稿」之后插入新章节：

```markdown
## 6. 对话与会话

### `POST /admin/agents/<agent_id>/chat`

权限：`agent_pool:manage`（发起对话 = 让 Agent 动起来，不接受只读权限触发）

**请求体**：`{"query": "看看内置工具现状", "conversation_id": "<可选，续聊时传>"}`

**响应**：`text/event-stream`，逐帧格式 `event: <name>\ndata:<json>\n\n`：

| `event` | `data` | 说明 |
| --- | --- | --- |
| `message` | `{"conversation_id": "..."}` | 会话已建立/复用 |
| `tool` | `{"call": {"name","args","id"}, "result": "<JSON 字符串>"}` | 一次板块工具调用及结果 |
| `answer` | `{"answer": "..."}` | 最终答复 |
| `error` | `{"error": "..."}` | 可读错误 |
| `end` | `{}` | 流结束 |

链路：解析 `AdminAgentPrincipal`（三重交集实时重算）→ 取/建会话 → 系统提示词
（Agent 的 `prompt_key`，缺省 `admin_agent_board_agent`）→ 装配板块工具（每板块一个）
→ 工具循环（上限 6 轮）→ 落库 → SSE。写动作仍按 `automation_policy` 分流
（`supervised` 产待批准草稿）。

**错误**：`403 forbidden`（权限不足 / 非属主 / Agent 已停用）、`400 validate_error`
（`query` 为空）。

### `GET /admin/agents/<agent_id>/conversations`

权限：`agent_pool:read` — 列出该 Agent 的会话（仅创建者可见；非属主 403）。

**响应 `data`**：`{"items": [{"id","admin_agent_id","title","created_at","updated_at"}]}`

### `GET /admin/agents/conversations/<conversation_id>/messages`

权限：`agent_pool:read` — 列出会话内消息。

**响应 `data`**：`{"items": [{"id","role","content","tool_calls","created_at"}]}`，
`role ∈ {user, assistant, tool}`；`tool` 角色消息的 `tool_calls` 承载
`{"call": {...}, "result": "..."}`。

**错误**：`403 forbidden`（非会话归属管理员）、`404 not_found`（会话不存在）。
```

- [ ] **Step 2: `docs/prd/execution-roadmap.md` 追加 P2 小节**

在 P1b 小节之后追加：

```markdown
### 管理端 Agent 治理 P2：对话式入口（已完成）

| 任务 | 文件 | 状态 |
| --- | --- | --- |
| **独立会话/消息表** | `model/admin_agent_conversation.py` + 迁移 `x1a2b3c4d5e7` | ✅ 已落地；不与用户端 `conversation`/`message` 混表，故**不扩展** `InvokeFrom` |
| **预置 Agent 幂等键** | `admin_agent.builtin_key` + 部分唯一索引 `admin_agent_owner_builtin_uniq` | ✅ 已落地 |
| **会话/消息服务** | `service/admin_agent_conversation_service.py` | ✅ 已落地；归属隔离（非属主 403） |
| **板块工具的 LLM 适配** | `service/admin_agent_chat_tools.py` | ✅ 已落地；每板块一个工具，权限/未登记拒绝回可读 JSON（不中断对话） |
| **系统提示词构造** | `service/admin_agent_prompt_service.py` | ✅ 已落地；只读 `prompt_template`（DB `source=custom` > YAML seed），无硬编码 |
| **预置 Agent 与人格** | `service/admin_agent_builtin_agents.py` + `prompts/admin_agent/{ops,marketing}_agent.yaml` | ✅ 已落地；**不下放权限**（`granted_permissions=[]`），`automation_policy={}` → supervised |
| **对话编排** | `service/admin_agent_chat_service.py` | ✅ 已落地；工具循环上限 6 轮 |
| **feature 注册** | `public_ai_feature_service.py`（`admin_agent`，`billable=False`） | ✅ 已落地；管理员在 `/admin/public-ai-features` 绑模型 |
| **HTTP 入口** | `admin_routes_7.py`（chat SSE / conversations / messages） | ✅ 已落地；权限走 `/admin/agents*` 前缀映射 |

> **未落地**：管理端前端对话页（另立前端任务）；定时任务 `agent_id` 通道与预算闸门（P4）；记忆主体抽象（P3）；MCP 动态身份注入（P5）。
```

- [ ] **Step 3: `docs/prd/modules/01-agent-tool-pool.md` 补对话链路说明**

在 `internal_admin` 池的消费方说明（§「`internal_admin` 池的消费方（2026-09 已接线）」段）末尾追加一句：

```markdown
> **P2 起的新调用方**：管理端 Agent 的**对话链路**（`api/internal/service/admin_agent_chat_service.py`）
> 同样装配白名单式板块工具（`admin_agent_chat_tools.build_board_tools`，每板块一个），
> 仍属管理端链路，**不进入**用户端候选收集（`AgentCandidateCollector`）。
```

- [ ] **Step 4: 提交**

```bash
git add docs/api/admin-agents-api.md docs/prd/execution-roadmap.md docs/prd/modules/01-agent-tool-pool.md
git commit -m "docs(admin-agent): document P2 conversation entry and sessions"
```

- [ ] **Step 5: 刷新知识图谱并跑全量回归**

```bash
python -m graphify update .
cd api && python -m pytest test -q --no-header --no-cov
```

Expected: 全绿（无 failed）

---

## 自检清单（实施者收尾前逐项确认）

- [ ] **每个新符号都点名入口**：
  - `AdminAgentChatService.chat` → 路由 `POST /admin/agents/<id>/chat`
  - `AdminAgentConversationService.list_conversations` / `list_messages` → 两条 GET 路由
  - `build_board_tools` → `AdminAgentChatService._build_tools`
  - `AdminAgentPromptService.build_system_prompt` → `AdminAgentChatService._build_system_prompt`
  - `AdminAgentBuiltinService.ensure_builtin_agents` → **调用方**：`GET /admin/agents` 路由（Task 8 Step 4，先补建再列出），并有测试锁定调用顺序
  - `admin_agent` feature_key → `LanguageModelService.get_feature_model("admin_agent")`（`AdminAgentChatService.FEATURE_KEY`）
- [ ] **新表读写俱全**：`admin_agent_conversation`/`admin_agent_message` 有写入（编排）与读取（两条 GET 路由）
- [ ] **新路由**均在 `admin_routes_7.py` 的 `register_routes` 内，且 `test_admin_rbac_guard.py` 通过（前缀映射已覆盖，无需改 `support.py`）
- [ ] **DI 构造守卫**：每个新服务都带 `@inject` + `@dataclass`（否则 `_get_service` 运行时 `CallError` → 500）；`test_admin_agent_di_construction.py` 覆盖每个新服务的 `injector.get` 可构造性，且**至少一条路由测试不替换 `_get_service`**（保护真实构造路径）
- [ ] **提示词无硬编码**：`ops_agent` / `marketing_agent` / 系统提示词全部来自 `prompts/**/*.yaml` + `prompt_template`
- [ ] **预置 Agent 不下放权限**：`granted_permissions=[]` 有测试锁定
- [ ] **`admin_user_id` 一律 UUID**：三条新路由均 `UUID(str(admin["id"]))`，有测试锁定
- [ ] **迁移** `down_revision = w1e2f3a4b5c6` 且 `test/internal/migration` 断言单 head
- [ ] **不扩展 `InvokeFrom`**（独立表已解决混表问题）
- [ ] 用调用方搜索验证无断链：对每个新符号全仓搜引用（排除 `test/`）
- [ ] 全量回归：`cd api && python -m pytest test -q --no-header --no-cov`
