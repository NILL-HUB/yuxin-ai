# CLI 工具池来源（source_type=cli）Implementation Plan

> **已归档（2026-10-03）**：Task 1~9 已落地（`cli_provider`/`cli_tool` 表 + `CliService` + `/admin/cli` 五端点 + `_collect_cli_tools` 候选 + assistant 链路 runtime 装配 + SOURCE_TYPES 一致 + cli-hub 清理），33 例后端测试通过。§4.4 初稿声称的四个挂载点已按实测纠偏（实际仅 assistant 链路；其余三个面各有政策原因）。当前说明见 [01-agent-tool-pool.md](../../prd/modules/01-agent-tool-pool.md) 与 [CLI 工具池设计规格](../superpowers-specs/2026-09-24-cli-tool-pool-design.md)；本文档仅保留实施过程，**不代表当前实现**。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 CLI 成为与 builtin/api_tool/mcp/skill 并列的独立工具来源（`source_type="cli"`），其全部子命令全量进入工具池候选、经现有 `ToolSelectorService` 选择、经 `McpStdioClient` 执行；同时清理 cli-hub 并维护一致性。

**Architecture:** 新建 `cli_provider` / `cli_tool` 两表独立存储 CLI（不寄生 `mcp_provider`）。`cli_provider.tool_schema` 是"能力说明书"，注册时展开写入 `cli_tool`（候选唯一事实源）。`ToolInventoryService._collect_cli_tools` 把 `cli_tool` 输出为 `source_type="cli"` 候选，复用 `ToolSelectorService`（关键词快通道 + LLM 兜底，已覆盖全 source_type）。执行时把 `cli_provider` 行构造成 MCP 形状的 binding dict（`transport="cli"`）交给既有 `McpToolFactory`（内部走 `McpStdioClient` 的 `protocol=raw`），不重复实现执行器。

**Tech Stack:** Python 3.11 / Flask(Quart ASGI) / SQLAlchemy / Alembic / LangChain / PostgreSQL(JSONB+GIN)。

**Spec:** `docs/superpowers/specs/2026-09-24-cli-tool-pool-design.md`

---

## File Structure

**Create:**
- `api/internal/model/cli.py` — `CliProvider` / `CliTool` 模型
- `api/internal/migration/versions/<rev>_add_cli_provider_tables.py` — 建表迁移
- `api/internal/migration/versions/<rev>_cleanup_cli_hub_skill.py` — 清理 cli-hub DB 残留
- `api/internal/service/cli_service.py` — CLI CRUD + `tool_schema`→`cli_tool` 展开 + 运行时 binding 构造
- `api/test/internal/service/test_cli_service.py`
- `api/test/internal/migration/test_cli_provider_migration.py`

**Modify:**
- `api/internal/model/__init__.py` — 导出新模型
- `api/internal/service/tool_inventory_service.py` — 新增 `_collect_cli_tools` 并注册进 `collect()`
- `api/internal/schema/admin_tool_governance_schema.py:10` — `SOURCE_TYPES` 加 `"cli"`
- `api/internal/service/admin_tool_governance_service.py:15` — `SOURCE_TYPES` 加 `"cli"`
- `api/app/http/admin_routes_4.py` — 新增 `/admin/cli` CRUD（对齐 `/admin/mcp` 形态）
- `api/app/http/module.py` / DI 注册 `CliService`
- `docs/prd/modules/01-agent-tool-pool.md` — 7 类 → 8 类
- `docs/prd/extensibility-design.md` — CLI 从"MCP transport 别名"改写为独立来源

**Delete:**
- `api/internal/core/skills/catalog/cli-hub/manifest.yaml`
- `api/internal/core/skills/catalog/cli-hub/skill.md`（磁盘存在，被 `.gitignore` 忽略）
- `api/test/internal/core/skills/test_cli_hub_skill.py`

**Move:**
- `docs/research/cli-anything.md` → `docs/archive/research-completed/cli-anything.md`

> **范围说明**：本计划覆盖后端 + 清理 + 文档。**admin UI（Vue）建议另出前端计划**（见末尾「后续」），因为它是独立技术栈、可独立验证，且不影响后端 API 的端到端测试。

---

## Task 1: `cli_provider` / `cli_tool` 模型与建表迁移

**Files:**
- Create: `api/internal/model/cli.py`
- Create: `api/internal/migration/versions/c4e5f6a7b8d9_add_cli_provider_tables.py`
- Modify: `api/internal/model/__init__.py`
- Test: `api/test/internal/migration/test_cli_provider_migration.py`

- [ ] **Step 1: 写失败测试（迁移守卫）**

```python
# api/test/internal/migration/test_cli_provider_migration.py
from __future__ import annotations

import importlib.util
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parents[3] / "internal/migration/versions"


def _load(module_name: str):
    path = VERSIONS_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_migration_links_to_known_head():
    mod = _load("c4e5f6a7b8d9_add_cli_provider_tables")
    assert mod.revision == "c4e5f6a7b8d9"
    # down_revision 必须指向已被 git 跟踪的迁移（避免全新 clone 上 upgrade head 崩溃）
    head_file = VERSIONS_DIR / f"{mod.down_revision}_drop_resource_vector_index.py"
    assert head_file.exists()


def test_model_declares_two_tables():
    from internal.model.cli import CliProvider, CliTool

    assert CliProvider.__tablename__ == "cli_provider"
    assert CliTool.__tablename__ == "cli_tool"
    assert hasattr(CliProvider, "tool_schema")
    assert hasattr(CliTool, "task_keywords")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/migration/test_cli_provider_migration.py -v`
Expected: FAIL（`cli.py` 不存在 / 迁移文件不存在）

- [ ] **Step 3: 写模型**

```python
# api/internal/model/cli.py
from datetime import UTC, datetime
import uuid

from sqlalchemy import (
    Column, UUID, String, Text, DateTime, Boolean, Integer, text,
    PrimaryKeyConstraint, Index, ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class CliProvider(Base):
    """CLI 工具提供者（本地进程 CLI，source_type=cli）。"""
    __tablename__ = "cli_provider"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_cli_provider_id"),
        Index("cli_provider_account_id_idx", "account_id"),
        Index("cli_provider_is_public_idx", "is_public"),
        Index("cli_provider_task_keywords_idx", "task_keywords", postgresql_using="gin"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    account_id = Column(UUID, ForeignKey("account.id"), nullable=True)
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    label = Column(String(255), nullable=False, server_default=text("''::character varying"))
    icon = Column(String(512), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=False, server_default=text("''::text"))
    category = Column(String(255), nullable=False, server_default=text("''::character varying"))
    command = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    args = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    env = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # 能力说明书：{tool_id: {"description": str, "parameters": {JSON Schema}}}
    tool_schema = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    task_keywords = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    timeout_seconds = Column(Integer, nullable=False, server_default=text("30"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    is_public = Column(Boolean, nullable=False, server_default=text("false"))
    source_type = Column(String(64), nullable=False, server_default=text("'cli'::character varying"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"),
                        server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    tools = relationship("CliTool", back_populates="provider", cascade="all, delete-orphan", lazy="selectin")


class CliTool(Base):
    """CLI 子命令元数据（工具粒度，`cli_tool` 是候选唯一事实源）。"""
    __tablename__ = "cli_tool"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_cli_tool_id"),
        Index("cli_tool_provider_id_idx", "provider_id"),
        Index("cli_tool_name_idx", "name"),
        Index("cli_tool_task_keywords_idx", "task_keywords", postgresql_using="gin"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    provider_id = Column(UUID, ForeignKey("cli_provider.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=False, server_default=text("''::text"))
    input_schema = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    task_keywords = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"),
                        server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    provider = relationship("CliProvider", back_populates="tools", lazy="joined")
```

- [ ] **Step 4: 导出模型**

在 `api/internal/model/__init__.py` 追加（与既有 import 同风格）：

```python
from .cli import CliProvider, CliTool
```

- [ ] **Step 5: 写建表迁移**

先确认 head：`Get-ChildItem api\internal\migration\versions\*.py | Sort-Object LastWriteTime -Descending | Select-Object -First 1`，当前为 `p2c3d4e5f6a8`（本计划据此设 `down_revision`）。

```python
# api/internal/migration/versions/c4e5f6a7b8d9_add_cli_provider_tables.py
"""add cli_provider / cli_tool tables

Revision ID: c4e5f6a7b8d9
Revises: p2c3d4e5f6a8
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c4e5f6a7b8d9"
down_revision = "p2c3d4e5f6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cli_provider",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(255), nullable=False, server_default=sa.text("''")),
        sa.Column("label", sa.String(255), nullable=False, server_default=sa.text("''")),
        sa.Column("icon", sa.String(512), nullable=False, server_default=sa.text("''")),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("category", sa.String(255), nullable=False, server_default=sa.text("''")),
        sa.Column("command", sa.String(1024), nullable=False, server_default=sa.text("''")),
        sa.Column("args", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("env", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("tool_schema", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("task_keywords", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source_type", sa.String(64), nullable=False, server_default=sa.text("'cli'")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"]),
        sa.PrimaryKeyConstraint("id", name="pk_cli_provider_id"),
    )
    op.create_index("cli_provider_account_id_idx", "cli_provider", ["account_id"])
    op.create_index("cli_provider_is_public_idx", "cli_provider", ["is_public"])
    op.create_index("cli_provider_task_keywords_idx", "cli_provider", ["task_keywords"], postgresql_using="gin")

    op.create_table(
        "cli_tool",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, server_default=sa.text("''")),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("input_schema", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("task_keywords", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.ForeignKeyConstraint(["provider_id"], ["cli_provider.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_cli_tool_id"),
    )
    op.create_index("cli_tool_provider_id_idx", "cli_tool", ["provider_id"])
    op.create_index("cli_tool_name_idx", "cli_tool", ["name"])
    op.create_index("cli_tool_task_keywords_idx", "cli_tool", ["task_keywords"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("cli_tool_task_keywords_idx", table_name="cli_tool")
    op.drop_index("cli_tool_name_idx", table_name="cli_tool")
    op.drop_index("cli_tool_provider_id_idx", table_name="cli_tool")
    op.drop_table("cli_tool")
    op.drop_index("cli_provider_task_keywords_idx", table_name="cli_provider")
    op.drop_index("cli_provider_is_public_idx", table_name="cli_provider")
    op.drop_index("cli_provider_account_id_idx", table_name="cli_provider")
    op.drop_table("cli_provider")
```

- [ ] **Step 6: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/migration/test_cli_provider_migration.py -v`
Expected: PASS（2 passed）

- [ ] **Step 7: 校验单 head**

Run: `cd api && python -m pytest test/internal/migration/ -v`（或使用仓库既有的 head 收敛校验脚本）
Expected: 无 "multiple heads" 报错

- [ ] **Step 8: Commit**

```bash
git add api/internal/model/cli.py api/internal/model/__init__.py \
        api/internal/migration/versions/c4e5f6a7b8d9_add_cli_provider_tables.py \
        api/test/internal/migration/test_cli_provider_migration.py
git commit -m "feat(cli): add cli_provider/cli_tool tables and migration"
```

---

## Task 2: `CliService`（CRUD + `tool_schema`→`cli_tool` 展开）

**Files:**
- Create: `api/internal/service/cli_service.py`
- Test: `api/test/internal/service/test_cli_service.py`

- [ ] **Step 1: 写失败测试**

```python
# api/test/internal/service/test_cli_service.py
from __future__ import annotations

from internal.service.cli_service import CliService


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_expand_tool_schema_creates_tool_rows():
    schema = {
        "caption": {"description": "一站式生成字幕并烧录", "parameters": {"type": "object", "properties": {"video": {"type": "string"}}}},
        "translate": {"description": "翻译字幕", "parameters": {"type": "object", "properties": {}}},
    }
    rows = CliService.expand_tool_schema(schema)
    names = sorted(r["name"] for r in rows)
    assert names == ["caption", "translate"]
    caption = next(r for r in rows if r["name"] == "caption")
    assert caption["description"] == "一站式生成字幕并烧录"
    assert caption["input_schema"]["type"] == "object"


def test_expand_tool_schema_ignores_malformed_entries():
    schema = {"ok": {"description": "d"}, "bad": "not-a-dict"}
    rows = CliService.expand_tool_schema(schema)
    assert [r["name"] for r in rows] == ["ok"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_cli_service.py -v`
Expected: FAIL（`cli_service` 不存在）

- [ ] **Step 3: 写服务**

```python
# api/internal/service/cli_service.py
"""CLI 工具来源服务：CRUD + tool_schema→cli_tool 展开 + 运行时 binding 构造。"""
from __future__ import annotations

import logging
from typing import Any

from injector import inject

from internal.model.cli import CliProvider, CliTool

logger = logging.getLogger(__name__)


@inject
class CliService:
    def __init__(self, db=None):
        self.db = db

    @staticmethod
    def expand_tool_schema(tool_schema: dict[str, Any] | None) -> list[dict[str, Any]]:
        """把能力说明书展开为 cli_tool 行数据（唯一事实源写入点）。"""
        if not isinstance(tool_schema, dict):
            return []
        rows: list[dict[str, Any]] = []
        for name, spec in tool_schema.items():
            if not isinstance(name, str) or not name.strip():
                continue
            if not isinstance(spec, dict):
                continue
            params = spec.get("parameters") if isinstance(spec.get("parameters"), dict) else {}
            rows.append({
                "name": name.strip(),
                "description": str(spec.get("description") or "").strip(),
                "input_schema": params,
                "task_keywords": [name.strip()],
            })
        return rows

    def create_provider(self, *, account_id, name: str, label: str, description: str,
                        category: str, command: str, args: list, env: dict,
                        tool_schema: dict, task_keywords: list, timeout_seconds: int,
                        enabled: bool = True) -> CliProvider:
        encrypted_env = self._encrypt_env(env or {})
        provider = CliProvider(
            account_id=account_id, name=name, label=label or name, description=description,
            category=category, command=command, args=list(args or []), env=encrypted_env,
            tool_schema=dict(tool_schema or {}), task_keywords=list(task_keywords or []),
            timeout_seconds=int(timeout_seconds or 30), enabled=bool(enabled), source_type="cli",
        )
        with self.db.auto_commit():
            self.db.session.add(provider)
            self.db.session.flush()
            self._sync_tools(provider)
        return provider

    def _sync_tools(self, provider: CliProvider) -> None:
        """以 tool_schema 为准重建 cli_tool（cli_tool 是候选唯一事实源）。"""
        self.db.session.query(CliTool).filter(CliTool.provider_id == provider.id).delete()
        for row in self.expand_tool_schema(provider.tool_schema):
            self.db.session.add(CliTool(provider_id=provider.id, **row))

    def build_mcp_shaped_bindings(self, providers: list[CliProvider],
                                  tool_names: list[str] | None = None) -> list[dict[str, Any]]:
        """把 cli_provider 行构造成 MCP 形状 binding，供 McpToolFactory 复用执行。"""
        bindings = []
        for p in providers:
            bindings.append({
                "name": p.name, "label": p.label, "description": p.description,
                "transport": "cli",
                "command": p.command, "args": list(p.args or []),
                "env": dict(p.env or {}), "timeout_seconds": p.timeout_seconds,
                "tool_schema": dict(p.tool_schema or {}),
                "tool_names": list(tool_names or []),
                "enabled": bool(p.enabled),
            })
        return bindings

    @staticmethod
    def _encrypt_env(env: dict) -> dict:
        try:
            from internal.service.tool_credential_encryptor import ensure_encrypted_env
            return ensure_encrypted_env(env)
        except Exception:
            logger.warning("CLI env 加密失败，按空处理", exc_info=True)
            return {}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_cli_service.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add api/internal/service/cli_service.py api/test/internal/service/test_cli_service.py
git commit -m "feat(cli): add CliService with tool_schema expansion and binding builder"
```

---

## Task 3: admin `/admin/cli` CRUD 路由 + DI 注册

**Files:**
- Modify: `api/app/http/admin_routes_4.py`（在 `/admin/mcp` 路由群之后追加）
- Modify: `api/app/http/module.py`（绑定 `CliService`）
- Test: `api/test/app/http/test_admin_routes_cli.py`

- [ ] **Step 1: 写失败测试**

仿既有 `test_admin_routes_8.py` 的 `_setup(monkeypatch, {Service: fake})` + `asyncio.run` + `quart_app.test_client()` 风格：

```python
# api/test/app/http/test_admin_routes_cli.py
from __future__ import annotations

import asyncio
from types import SimpleNamespace


class _FakeCliService:
    def create_provider(self, **kwargs):
        return SimpleNamespace(id="00000000-0000-0000-0000-000000000001")


def test_create_cli_provider_requires_name(quart_app, monkeypatch):
    from app.http import asgi_app
    from internal.service.cli_service import CliService

    # 复用仓库既有 _setup 助手：注入 fake 服务 + admin 身份
    from test.app.http._helpers import setup_admin, _setup  # 若仓库无此助手，按 test_admin_routes_8.py 内联实现
    _setup(monkeypatch, {CliService: _FakeCliService()})

    client = quart_app.test_client()
    resp = asyncio.run(client.post("/admin/cli", json={"name": "", "description": "d"}))
    assert resp.status_code == 400
    body = asyncio.run(resp.get_json())
    assert body["code"] == "validate_error"
```

> 说明：`_setup`/`setup_admin` 的具体形态以 `api/test/app/http/test_admin_routes_8.py` 中 `TestAdminGlobalControlConfig` 的实现为准（内联复制其用法，勿新造）。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/app/http/test_admin_routes_cli.py -v`
Expected: FAIL（404，路由未注册）

- [ ] **Step 3: 加路由（对齐 `/admin/mcp` 形态）**

在 `api/app/http/admin_routes_4.py` 的 MCP 路由群后追加：

```python
    @quart_app.post("/admin/cli")
    async def admin_create_cli_provider():
        from app.http import asgi_app as a
        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err
        from internal.service.cli_service import CliService

        data = await request.get_json(force=True, silent=True) or {}
        name = str(data.get("name") or "").strip()
        description = str(data.get("description") or "").strip()
        command = str(data.get("command") or "").strip()
        if not name:
            return a._json_resp(code="validate_error", message="CLI 名称不能为空",
                                data={"name": ["CLI 名称不能为空"]}, status=400)
        if not command:
            return a._json_resp(code="validate_error", message="CLI 命令不能为空",
                                data={"command": ["CLI 命令不能为空"]}, status=400)
        provider = await a._to_thread(
            a._get_service(CliService).create_provider,
            account_id=account.id, name=name, label=str(data.get("label") or ""),
            description=description, category=str(data.get("category") or "other"),
            command=command, args=list(data.get("args") or []),
            env=dict(data.get("env") or {}), tool_schema=dict(data.get("tool_schema") or {}),
            task_keywords=list(data.get("task_keywords") or []),
            timeout_seconds=int(data.get("timeout_seconds") or 30),
            enabled=bool(data.get("enabled", True)),
        )
        await _record_mutation_audit(action="cli.create", resource_type="cli",
                                     resource_id=str(provider.id), after_data={"name": name})
        return a._ok({"id": str(provider.id)})

    @quart_app.get("/admin/cli")
    async def admin_list_cli_providers():
        from app.http import asgi_app as a
        account, err = await a._resolve_admin_operator()
        if err is not None:
            return err
        from internal.service.cli_service import CliService
        items = await a._to_thread(a._get_service(CliService).list_providers, account_id=account.id)
        return a._ok({"items": items})
```

> **注意**：`_record_mutation_audit` / `a._resolve_admin_operator` / `a._get_service` / `a._json_resp` / `a._to_thread` 均以同文件既有用法为准。列表/详情/更新/删除路由按 `create` 同款补齐（update 需调用 `CliService.update_provider`，内部重建 `cli_tool`）。

- [ ] **Step 4: DI 注册**

在 `api/app/http/module.py` 的绑定列表中加入 `CliService`（与 `McpService` 同风格），并确保 `CliService` 的 `db` 依赖可注入（参照既有 service 的 `db` 注入方式）。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd api && python -m pytest test/app/http/test_admin_routes_cli.py -v`
Expected: PASS

- [ ] **Step 6: 补 `update_provider` / `list_providers` / `get_provider` / `delete_provider` 单测并跑通**

Run: `cd api && python -m pytest test/internal/service/test_cli_service.py test/app/http/test_admin_routes_cli.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add api/app/http/admin_routes_4.py api/app/http/module.py \
        api/internal/service/cli_service.py api/test/app/http/test_admin_routes_cli.py
git commit -m "feat(cli): add /admin/cli CRUD routes and DI wiring"
```

---

## Task 4: 候选收集 `_collect_cli_tools`（补断链，核心）

**Files:**
- Modify: `api/internal/service/tool_inventory_service.py:157-167`（`collect()`）+ 新增方法
- Test: `api/test/internal/service/test_tool_inventory_cli.py`

- [ ] **Step 1: 写失败测试**

```python
# api/test/internal/service/test_tool_inventory_cli.py
from __future__ import annotations

from types import SimpleNamespace

from internal.service.tool_inventory_service import ToolInventoryService


class _Query:
    def __init__(self, rows):
        self._rows = rows
    def filter(self, *a, **k):
        return self
    def all(self):
        return self._rows


class _Session:
    def __init__(self, providers):
        self._providers = providers
    def query(self, model):
        return _Query(self._providers)


def test_collect_cli_tools_uses_tool_level_description():
    provider = SimpleNamespace(
        id="p1", name="videocaptioner", label="VideoCaptioner", description="provider-desc",
        is_public=False, task_keywords=["字幕"],
        tools=[
            SimpleNamespace(name="caption", description="一站式生成字幕并烧录", input_schema={},
                            task_keywords=["caption"], enabled=True),
        ],
    )
    svc = ToolInventoryService(session=_Session([provider]))
    cands = svc._collect_cli_tools("acct")
    assert len(cands) == 1
    c = cands[0]
    assert c["source_type"] == "cli"
    assert c["name"] == "caption"
    assert c["description"] == "一站式生成字幕并烧录"   # 工具级，非 provider 级
    assert "caption" in c["task_keywords"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_tool_inventory_cli.py -v`
Expected: FAIL（`_collect_cli_tools` 不存在）

- [ ] **Step 3: 实现收集器并注册**

在 `ToolInventoryService.collect()` 的 `candidates.extend(...)` 列表中加入：

```python
        candidates.extend(self._collect_cli_tools(account_id))
```

新增方法（沿用 `_collect_mcp_tools` 的 metadata/available 约定）：

```python
    def _collect_cli_tools(self, account_id) -> list[dict[str, object]]:
        from internal.model.cli import CliProvider

        providers = (
            self.session.query(CliProvider)
            .filter((CliProvider.account_id == account_id) | (CliProvider.is_public == True))  # noqa: E712
            .all()
        )
        cli_pool = self.inventory.normalize_pool_name("cli")
        result: list[dict[str, object]] = []
        for provider in providers:
            if not bool(provider.enabled):
                continue
            provider_keywords = list(provider.task_keywords or [])
            for tool in provider.tools or []:
                if not bool(getattr(tool, "enabled", True)):
                    continue
                metadata = normalize_tool_metadata({
                    "tool_pool": cli_pool,
                    "capabilities": [tool.name],
                    "permission_scope": "public" if provider.is_public else "user",
                })
                if not self._is_available(metadata):
                    continue
                tool_keywords = list(tool.task_keywords or [])
                if tool.name and tool.name not in tool_keywords:
                    tool_keywords.append(tool.name)
                result.append({
                    "id": build_tool_id("cli", str(provider.id), tool.name),
                    "name": tool.name,
                    "description": tool.description,            # 工具级描述（核心修复）
                    "source_type": "cli",
                    "provider_id": str(provider.id),
                    "provider_name": provider.label or provider.name,
                    "inputs": [],
                    "metadata": metadata,
                    "visibility": "public" if provider.is_public else "private",
                    "enabled": True,
                    "task_keywords": provider_keywords + tool_keywords,
                })
        return result
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_tool_inventory_cli.py -v`
Expected: PASS

- [ ] **Step 5: 验证 cli 候选可被选择器选中**

在 `api/test/internal/service/test_tool_inventory_cli.py` 追加：

```python
def test_selector_can_pick_cli_candidate_by_keyword():
    from internal.service.tool_selector_service import ToolSelectorService

    candidates = [{
        "source_type": "cli", "provider_id": "p1", "provider_name": "VC",
        "name": "caption", "description": "一站式生成字幕并烧录",
        "task_keywords": ["caption", "字幕"],
    }]
    selector = ToolSelectorService(builtin_tool_service=None, language_model_service=None)
    hits = selector._fast_keyword_match("请帮我做字幕 caption", candidates, max_tools=5)
    assert len(hits) == 1
    assert hits[0]["source_type"] == "cli"
    assert hits[0]["tool_name"] == "caption"
    assert hits[0]["match_type"] == "keyword"
```

Run: `cd api && python -m pytest test/internal/service/test_tool_inventory_cli.py -v`
Expected: PASS（2 passed）

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/tool_inventory_service.py api/test/internal/service/test_tool_inventory_cli.py
git commit -m "feat(cli): collect cli_tool candidates into tool pool (fix断链)"
```

---

## Task 5: 运行时工具装配（选中 cli 工具 → LangChain tool）

**Files:**
- Modify: `api/internal/service/cli_service.py`（新增 `build_selected_tools`）
- Test: `api/test/internal/service/test_cli_runtime_tools.py`

- [ ] **Step 1: 写失败测试**

```python
# api/test/internal/service/test_cli_runtime_tools.py
from __future__ import annotations

from types import SimpleNamespace
from internal.service.cli_service import CliService


class _Svc(CliService):
    def __init__(self):
        self.db = None


def test_build_selected_tools_forwards_to_mcp_factory(monkeypatch):
    captured = {}

    class _FakeFactory:
        def get_tools(self, bindings, mcp_tool_snapshots=None):
            captured["bindings"] = bindings
            captured["snapshots"] = mcp_tool_snapshots
            return ["tool-obj"]

    import internal.service.cli_service as mod
    monkeypatch.setattr(mod, "McpToolFactory", _FakeFactory, raising=False)

    provider = SimpleNamespace(
        id="p1", name="vc", label="VC", description="d", command="cli-anything-vc",
        args=["--json"], env={"K": "v"}, timeout_seconds=30,
        tool_schema={"caption": {"description": "x", "parameters": {}}}, enabled=True,
    )
    tools = _Svc().build_selected_tools([provider], tool_names=["caption"])
    assert tools == ["tool-obj"]
    b = captured["bindings"][0]
    assert b["transport"] == "cli"
    assert b["tool_names"] == ["caption"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_cli_runtime_tools.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

在 `cli_service.py` 顶部 import `from internal.core.tools.mcp_tools.providers.mcp_tool_factory import McpToolFactory`，并新增：

```python
    def build_selected_tools(self, providers: list[CliProvider],
                             tool_names: list[str] | None = None):
        """把 cli_provider 构造成 MCP 形状 binding，复用 McpToolFactory 装配（内部走 protocol=raw）。"""
        bindings = self.build_mcp_shaped_bindings(providers, tool_names=tool_names)
        if not bindings:
            return []
        return McpToolFactory().get_tools(bindings, mcp_tool_snapshots=None)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_cli_runtime_tools.py -v`
Expected: PASS

- [ ] **Step 5: 接入运行时装配挂载点**

在 `app_runtime_service` / `assistant_agent_service` 的工具装配处，对 `source_type="cli"` 的选中工具调用 `CliService.build_selected_tools([provider], tool_names=[selected])`，与 MCP 工具并列加入 tools 列表。**必须实际接线**（否则重演断链）：新增的每个调用点都要在测试中以「选中 cli 工具后 tools 列表包含该项」断言。

- [ ] **Step 6: Commit**

```bash
git add api/internal/service/cli_service.py api/test/internal/service/test_cli_runtime_tools.py \
        api/internal/service/app_runtime_service.py api/internal/service/assistant_agent_service.py
git commit -m "feat(cli): wire selected cli tools into runtime tool assembly"
```

---

## Task 6: 一致性 —— `SOURCE_TYPES` 加 `cli`

**Files:**
- Modify: `api/internal/schema/admin_tool_governance_schema.py:10`
- Modify: `api/internal/service/admin_tool_governance_service.py:15`
- Test: `api/test/internal/service/test_tool_governance_source_types.py`

- [ ] **Step 1: 写失败测试**

```python
# api/test/internal/service/test_tool_governance_source_types.py
def test_source_types_include_cli_and_stay_in_sync():
    from internal.schema.admin_tool_governance_schema import SOURCE_TYPES as S1
    from internal.service.admin_tool_governance_service import SOURCE_TYPES as S2

    assert "cli" in S1
    assert S1 == S2        # 两处必须一致，防漂移
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/service/test_tool_governance_source_types.py -v`
Expected: FAIL

- [ ] **Step 3: 改两处**

两处均改为：

```python
SOURCE_TYPES = ["api_tool", "mcp", "skill", "cli", "builtin", "knowledge", "workflow", "agent_binding"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/service/test_tool_governance_source_types.py -v`
Expected: PASS

- [ ] **Step 5: 回归工具治理既有测试**

Run: `cd api && python -m pytest test/internal/service/ -k "governance" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/internal/schema/admin_tool_governance_schema.py \
        api/internal/service/admin_tool_governance_service.py \
        api/test/internal/service/test_tool_governance_source_types.py
git commit -m "chore(cli): add cli to SOURCE_TYPES (consistency)"
```

---

## Task 7: cli-hub 清理（文件 + 测试 + DB + 归档）

**Files:**
- Delete: `api/internal/core/skills/catalog/cli-hub/manifest.yaml`
- Delete: `api/internal/core/skills/catalog/cli-hub/skill.md`
- Delete: `api/test/internal/core/skills/test_cli_hub_skill.py`
- Create: `api/internal/migration/versions/d5f6a7b8c9e0_cleanup_cli_hub_skill.py`
- Move: `docs/research/cli-anything.md` → `docs/archive/research-completed/cli-anything.md`

- [ ] **Step 1: 写失败测试（迁移清理守卫）**

```python
# api/test/internal/migration/test_cleanup_cli_hub_skill.py
from __future__ import annotations

import importlib.util
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parents[3] / "internal/migration/versions"


def test_cleanup_migration_links_and_targets_cli_hub():
    path = VERSIONS_DIR / "d5f6a7b8c9e0_cleanup_cli_hub_skill.py"
    spec = importlib.util.spec_from_file_location("d5f6a7b8c9e0_cleanup_cli_hub_skill", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    assert mod.down_revision == "c4e5f6a7b8d9"


def test_cli_hub_files_removed():
    root = Path(__file__).resolve().parents[4]
    assert not (root / "internal/core/skills/catalog/cli-hub/manifest.yaml").exists()
    assert not (root / "internal/core/skills/catalog/cli-hub").exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/migration/test_cleanup_cli_hub_skill.py -v`
Expected: FAIL

- [ ] **Step 3: 删除文件**

```bash
git rm api/internal/core/skills/catalog/cli-hub/manifest.yaml
git rm api/test/internal/core/skills/test_cli_hub_skill.py
```
`skill.md` 被 `.gitignore` 忽略（`**/*.md`），用文件删除：
```bash
Remove-Item api/internal/core/skills/catalog/cli-hub/skill.md
Remove-Item api/internal/core/skills/catalog/cli-hub -Force   # 移除空目录
```

- [ ] **Step 4: 写 DB 清理迁移**

catalog 同步只增不删，需显式清理 `skill_package` 残留：

```python
# api/internal/migration/versions/d5f6a7b8c9e0_cleanup_cli_hub_skill.py
"""cleanup cli-hub skill_package rows

Revision ID: d5f6a7b8c9e0
Revises: c4e5f6a7b8d9
"""
from alembic import op
import sqlalchemy as sa

revision = "d5f6a7b8c9e0"
down_revision = "c4e5f6a7b8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM skill_package_version WHERE skill_package_id IN "
            "(SELECT id FROM skill_package WHERE source_key = 'cli-hub')"
        )
    )
    op.execute(sa.text("DELETE FROM skill_package WHERE source_key = 'cli-hub'"))


def downgrade() -> None:
    # 数据删除不可逆；catalog 文件已删除，重新同步也不会恢复
    pass
```

- [ ] **Step 5: 归档调研文档**

```bash
git mv docs/research/cli-anything.md docs/archive/research-completed/cli-anything.md
```
并在该文档首行追加一行状态标注：
```markdown
> **方案作废（2026-09-24）**：本文建议的 cli-hub 工具目录 + 执行器方案已被否决；系统采用「CLI 作为受管工具池来源（source_type=cli）」方案，见 `docs/superpowers/specs/2026-09-24-cli-tool-pool-design.md`。发现/安装生态不做。
```

- [ ] **Step 6: 运行测试确认通过 + 全仓零残留**

```bash
cd api && python -m pytest test/internal/migration/test_cleanup_cli_hub_skill.py -v
```
Expected: PASS
```bash
Select-String -Path "api/**/*.py","docs/**/*.md" -Pattern "cli-hub|cli_hub|cli-anything" | Select-Object -First 5
```
Expected: 仅 `docs/archive/research-completed/cli-anything.md` 命中

- [ ] **Step 7: Commit**

```bash
git add -A api/internal/core/skills/catalog/cli-hub \
        api/test/internal/core/skills/test_cli_hub_skill.py \
        api/internal/migration/versions/d5f6a7b8c9e0_cleanup_cli_hub_skill.py \
        api/test/internal/migration/test_cleanup_cli_hub_skill.py \
        docs/research/cli-anything.md docs/archive/research-completed/cli-anything.md
git commit -m "chore(cli): remove cli-hub skill, tests, DB rows; archive research doc"
```

---

## Task 8: 文档一致性维护

**Files:**
- Modify: `docs/prd/modules/01-agent-tool-pool.md`（§10.1.1 等多处 7 类 → 8 类）
- Modify: `docs/prd/extensibility-design.md`（§3.2 / §3.2.1）

- [ ] **Step 1: 更新工具池来源类型**

在 `docs/prd/modules/01-agent-tool-pool.md` §10.1.1「工具来源类型（完整版）」表格新增 `cli` 行，并把文中所有「7 类」「7 种」表述改为「8 类」：

```markdown
| cli | CliProvider + CliTool（本地进程，`tool_schema` 为能力说明书） | 纳入 ToolSourceType | 纯 CLI 工具（一条龙打包能力） |
```

- [ ] **Step 2: 改写 extensibility-design**

把 `docs/prd/extensibility-design.md` §3.2 / §3.2.1 中"CLI 走 MCP 工厂的 `transport=cli`"表述改为：

```markdown
CLI 是**独立的工具来源**（`source_type=cli`）：数据/服务/路由/UI 独立（`cli_provider`/`cli_tool`），
执行复用本地进程原语（`McpStdioClient` 的 `protocol=raw`）。其子命令全量进入工具池候选，
经 `ToolSelectorService`（关键词快通道 + LLM 兜底）选择，与 builtin/mcp/skill 同池竞争。
```

- [ ] **Step 3: 校验文档无悬空引用**

Run: `Select-String -Path "docs/prd/**/*.md" -Pattern "transport=cli" | Select-Object -First 10`
Expected: 无"寄生在 MCP 板块"的旧表述残留

- [ ] **Step 4: Commit**

```bash
git add docs/prd/modules/01-agent-tool-pool.md docs/prd/extensibility-design.md
git commit -m "docs(cli): document cli as independent tool source (8 source types)"
```

---

## Task 9: 端到端验收

**Files:**
- Test: `api/test/integration/test_cli_agent_select.py`

- [ ] **Step 1: 构造纯 CLI 型 provider 并入库**

示例 CLI（无 GUI 依赖，用于验收）：

```python
# 假设环境存在 python；command 直接执行内联脚本
provider_payload = {
    "name": "demo-cli", "description": "演示 CLI",
    "command": "python",
    "args": ["-c", "print('hello-cli')"],
    "tool_schema": {"echo": {"description": "输出 hello-cli", "parameters": {"type": "object", "properties": {}}}},
    "task_keywords": ["演示"],
}
```

- [ ] **Step 2: 断言候选池可见**

`ToolInventoryService.collect(account_id)` 结果含 `source_type="cli"`、`name="echo"` 的候选。

- [ ] **Step 3: 断言选择器可选中**

```python
selected = ToolSelectorService(...).select_tools("演示 echo", candidates=cands, max_tools=5)
assert any(s["source_type"] == "cli" and s["tool_name"] == "echo" for s in selected)
```

- [ ] **Step 4: 断言执行返回 stdout**

```python
tools = CliService(...).build_selected_tools([provider], tool_names=["echo"])
out = tools[0].invoke({})
assert "hello-cli" in str(out)
```

- [ ] **Step 5: 全量回归**

Run: `cd api && python -m pytest test/ -v`
Expected: 无新增失败（既有 memory 真库用例的已知失败除外）

- [ ] **Step 6: Commit**

```bash
git add api/test/integration/test_cli_agent_select.py
git commit -m "test(cli): end-to-end acceptance for cli tool selection and execution"
```

---

## Self-Review（对 spec 覆盖核对）

| Spec 章节 | 覆盖任务 |
|---|---|
| §4.1 数据模型（两表） | Task 1 |
| §4.2 候选收集（补断链） | Task 4 |
| §4.3 选择逻辑（零新增） | Task 4 Step 5 / Task 9 |
| §4.4 执行链路（复用） | Task 5 |
| §4.5 治理（SOURCE_TYPES） | Task 6 |
| §4.6 一条龙 vs 精细 | Task 4（工具级描述）+ Task 8（文档） |
| §4.7 管理入口与迁移 | Task 1 / 3 / 5 / 7 |
| §5 cli-hub 清理 | Task 7 |
| §6 一致性与死代码 | Task 6 / 7 / 8 |
| §8 验收标准 | Task 9 |
| §9 测试策略 | 各 Task 内 |

**遗留（另出计划）**：
- **admin UI（Vue）**：CLI 管理页（对齐 `AdminMcpView.vue` + `CreateOrUpdateMcpModal.vue` 模式），含 `tool_schema` 能力说明书编辑器 + i18n（zh/en 镜像 + parity 测试）。
- **`.gitignore` `**/*.md` 导致所有 `catalog/*/skill.md` 未入库**：既有缺陷，需单独评估与修复（不阻塞本计划）。
