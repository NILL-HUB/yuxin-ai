# 管理端 Agent 治理 P1b：板块工具与执行链路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理端 Agent 从「只有授权」变成「能真正执行一个板块动作」——补齐板块级聚合工具框架、审计 `actor_type` 身份、变更草稿泛化、回收站 `admin_agent` 来源扩展，并以 `builtin_tool` 作为端到端样板板块打通全链路。

**Architecture:** 本计划是设计文档 `docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md` §5.2（草稿泛化）、§7.1（板块级聚合工具 + 回收站扩展）、§9（审计身份）、§10.2 中 `audit_log` / `policy_change_draft` 部分 的落地。P1a 已交付授权内核与身份对象；P1b 在其上装配**能力层（L2）与执行层（L1）**：`AdminAgentPrincipal` 作为显式入参全链路传递，板块工具内部按 `action` 分支、每 action 显式声明所需权限点（未声明即拒绝），写操作按 `automation_policy` 分流（`supervised` → 变更草稿 / `autonomous` → 直接执行 / `blocked` → 熔断）。

**边界（本计划不做）**：对话式入口与会话表（P2）、记忆主体抽象（P3）、预算闸门实际执行与 `schedule_task.agent_id`（P4）、MCP 动态身份注入（P5）。

**Tech Stack:** Python 3.12 / Quart(ASGI) / SQLAlchemy / Alembic / pytest（`--no-cov` 快跑）

**前置状态（已完成）**：
- P0 地基修复（`collect_raw`、`_ADMIN_USER_ID`、orchestrator fail closed）。
- P1a 授权内核：`api/internal/core/admin_agent_authorization.py`（`ASSIGNABLE_PERMISSIONS` / `compute_effective_permissions` / `assert_grantable`）、`api/internal/entity/admin_agent_entity.py`（`AdminAgentPrincipal` / `AutomationLevel`）、`api/internal/model/admin_agent.py`、`api/internal/service/admin_agent_service.py`、`GET /admin/agents/assignable-permissions`。
- 迁移链单 head：**`s5f6a7b8c9d0`**（已实测确认，全仓 150 个迁移、唯一 head、无悬空 `down_revision`）。

---

## 关键事实（实现者必读，已实测核实）

| 项 | 事实 | 来源 |
| --- | --- | --- |
| 迁移 head | `s5f6a7b8c9d0`（唯一 head） | 已实测（AST 遍历全仓 150 个迁移） |
| `AdminAgentPrincipal` 字段 | `admin_user_id` / `agent_id` / `agent_name` / `effective_permissions: frozenset[str]` / `automation_policy: Mapping[str, AutomationLevel]`；`has_permission()`、`automation_level_for()`（未配置 → `SUPERVISED`，fail closed） | 已实测 |
| 授权计算入口 | `compute_effective_permissions(admin_permissions=..., granted_permissions=...)` 返回 `frozenset[str]` | 已实测 |
| `AdminAgentService` | 非 `@inject`；`__init__(self, db: SQLAlchemy)` 只用 `db.session` + `db.auto_commit()`，可传 `SimpleNamespace` 适配器 | 已实测 |
| `AdminUserService` 取权限 | `get_current_admin_from_token(token)` → `dict`，含 `id` / `roles` / `permissions`（`_serialize_current_admin_user`） | 已实测 |
| super_admin 权限 | `_get_permission_codes` 对 `super_admin` 返回 `all_permission_codes()` 全量 | 已实测 |
| 测试期 RBAC 替身 | `test/conftest.py` autouse fixture 把 `support._resolve_admin_permission` 替换为无条件放行（`permissions=["*"]`），需显式覆盖才能测"展示即受限" | 已实测 |
| `AuditLog` 列 | `id`/`admin_user_id`/`account_id`/`action`/`resource_type`/`resource_id`/`ip`/`user_agent`/`before_data`/`after_data`/`created_at`；**无 `actor_type`、无 `agent_id`** | 已实测 |
| 审计写入方法 | `record(*, admin_user_id, ..., commit=True)`；`record_for_write(...)` → `record(commit=False)`，`admin_user_id` 空则返回 `None`；`record_for_tool_invocation(*, account_id, ..., commit=True)` | 已实测 |
| 审计写入契约 | `record_for_write` 是 `commit=False`，**必须由调用方事务提交** | 已实测 |
| `policy_change_draft` 列 | `id`/`suggestion_id`(**NOT NULL**, 普通索引**非 FK**)/`policy_type`/`target_id`/`before_config`/`after_config`/`diff`/`impact`/`status`/`applied_by`/`applied_at`/`rolled_back_at`/`rollback_reason`/`created_at`/`updated_at`；**零外键** | 已实测 |
| 草稿服务 | `RoutingPolicyChangeService`：`generate_preview` / `apply_draft(suggestion_id, admin_user_id, preview_data)` / `rollback_draft(draft_id, admin_user_id, reason)` / `list_drafts(status)` | 已实测 |
| 草稿路由 | 4 条挂在 `admin_routes_6.py` L511-579；权限 `routing_quality:read/apply/rollback`（`support.py` L646-662）；仅 `operator` 角色默认持有写权限 | 已实测 |
| `recycle_bin` 常量 | `RESOURCE_TYPES` 14 项；`USER_VISIBLE_RESOURCE_TYPES` 7 项；`ADMIN_ONLY_RESOURCE_TYPES` 为**派生只读常量、无任何调用点** | 已实测 |
| `delete_resource` 签名 | `(self, *, resource_type, resource_id, resource_key="", resource_name="", deleted_by=None, deleted_by_type="admin", retention_days=None, agent_id=None) -> bool`（**全 keyword-only**） | 已实测 |
| `deleted_by_type` 校验 | 不在 `("admin","user","agent")` → **静默归一为 `admin`**；`user`/`agent` 且资源非用户可见 → **抛 `ValidateErrorException`**；`agent` → 强制 `retention_days = AGENT_RETENTION_DAYS = 7` | 已实测 |
| `_agent_id` 写入 | 仅当 `deleted_by_type == "agent"` 且 `agent_id is not None` 时写 `snapshot["_agent_id"]`；**全仓零读取点** | 已实测 |
| admin 回收站路由 | 5 条在 `admin_routes_8.py` L966-1073，`deleted_by_type` 默认 `"admin"`；权限 `recycle_bin:read` / `recycle_bin:write` | 已实测 |
| 回收站列表过滤 | `list_items(deleted_by_type=...)` 用 `==` 精确匹配；`list_user_items` 用 `in_(("user","agent"))` | 已实测 |
| builtin 工具同步 | `BuiltinToolSyncService.sync_yaml_to_db()` 启动时执行（`app.py` L84-92），**只增不删**；`_upsert_tool` 只在新建立写 `source="catalog"` / `enabled=True`，更新分支**不碰 `enabled` 也不重写 `source`** | 已实测 |
| builtin 编辑白名单 | `admin_routes_8._builtin_tool_update` 的 `allowed_fields = {"label","description","task_keywords","icon"}`；**`enabled` / `source` 不在白名单**，全仓没有任何写 `builtin_tool.enabled` / `source` 的代码 | 已实测 |
| builtin `enabled` 读侧 | `BuiltinProviderManager._load_from_db`（L106-108）、`BuiltinToolService._get_builtin_tools_from_db`（L72-74）、`ResourceVectorIndexService.index_all_builtin_tools`（L232）均已尊重 `enabled=False` | 已实测 |
| `builtin_tool:update` 权限 | 已存在（`rbac.py` L95，说明即"启停内置工具"），且 `builtin_tool` 已在 `ASSIGNABLE_RESOURCES` 中 → **可下放给 Agent** | 已实测 |
| 编排开关服务 | `OrchestrationFeatureFlagService.update_flag(*, code: str, enabled: bool, operator_id: UUID) -> dict`（code 未知抛 `ValueError`；`operator_id` 必须是 `UUID` 实例）；`list_flags() -> list[dict]` | 已实测 |
| 系统提示词服务 | `SystemPromptLibraryService.update_managed_prompt(prompt_key, *, content=None, description=None, enabled=None) -> dict | None`（key 不在 YAML 中返回 `None`）；删除走 `delete_managed_prompt(...)` → `RecycleBinService.delete_resource(resource_type="system_prompt", ...)` | 已实测 |
| 板块工具已登记 resource | `ASSIGNABLE_RESOURCES` 已含 `builtin_tool` / `prompt_template` / `orchestration_flag` / `recycle_bin` 等 | 已实测 |
| 审计静默丢失缺陷 | 4 类（见 Task 1） | 已实测 |

---

## 关于测试的重要约定

1. 跑测试一律加 `--no-cov -p no:cacheprovider`（默认 `addopts` 带覆盖率，很慢）。
2. **每个边界规则必须有反向验证**：临时把实现改成违规版本 → 测试**必须失败** → 恢复。这是设计文档 §12 的教训（曾有回归测试假通过）。
3. **不要重写被测逻辑**：测试替身不得重新实现 service 的判断逻辑，否则测的是替身而非实现（P1a 已两次踩中：`test_fail_closed_for_unknown_resource` 用真实权限点导致走不到 resource 分支、`_stub_service` 重写 `list_assignable_permissions`）。替身只做 I/O 隔离，逻辑必须走真实实现。
4. **断言不要放在会被吞掉的位置**：`OrchestratorService.decide()` 外层有 `except Exception` 会把断言异常转成 fallback，导致假通过。断言写在调用返回之后。
5. 不要在测试里断言"数量恰为 N"这类易漂移值，除非同时说明由某个常量派生。

---

## 文件结构

**新建**

| 文件 | 职责 |
| --- | --- |
| `api/internal/core/admin_agent_boards.py` | 板块动作注册表：`BoardAction` 声明（板块 + action + 所需权限点 + 是否写/删）+ `resolve_action()`（未声明即拒绝） |
| `api/internal/entity/admin_change_draft_entity.py` | 通用变更草稿的值对象与状态/板块枚举 |
| `api/internal/service/admin_change_draft_service.py` | 通用变更草稿服务（创建 / 列出 / 应用 / 回滚），供所有板块的 `supervised` 档复用 |
| `api/internal/service/admin_agent_board_tools.py` | 板块级聚合工具的实现体：`admin_builtin_tools` 等，按 `action` 分发到既有 service |
| `api/internal/service/admin_agent_execution_service.py` | 执行层：装配 `AdminAgentPrincipal`（实时重算三重交集）、按 `automation_policy` 分流、写审计 |
| `api/internal/migration/versions/<rev>_add_audit_log_actor_fields.py` | `audit_log` 新增 `actor_type` / `agent_id` |
| `api/internal/migration/versions/<rev>_generalize_policy_change_draft.py` | `policy_change_draft.suggestion_id` 改可空 + 建通用索引 |
| `api/internal/migration/versions/<rev>_extend_recycle_bin_admin_agent.py` | 回收站支持 `deleted_by_type='admin_agent'`（含来源回填与索引） |
| `api/internal/core/prompts/admin_agent/board_agent.yaml` | 板块 Agent 系统提示词（YAML seed） |
| `api/test/internal/core/test_admin_agent_boards.py` | 板块动作注册表测试（含反向验证） |
| `api/test/internal/service/test_admin_change_draft_service.py` | 通用草稿服务测试 |
| `api/test/internal/service/test_admin_agent_board_tools.py` | 板块工具测试（含反向验证） |
| `api/test/internal/service/test_admin_agent_execution_service.py` | 执行层测试（含反向验证） |
| `api/test/internal/model/test_audit_log_actor_fields.py` | `audit_log` 新列结构测试 |
| `api/test/app/http/test_admin_agent_invoke_routes.py` | 执行入口路由测试 |

**修改**

| 文件 | 变更 |
| --- | --- |
| `api/internal/model/admin.py` | `AuditLog` 新增 `actor_type` / `agent_id` 列 |
| `api/internal/model/routing_quality.py` | `PolicyChangeDraftModel.suggestion_id` 改 `nullable=True` |
| `api/internal/service/audit_log_service.py` | `record` / `record_for_write` 增加 `actor_type` / `agent_id` 透传；序列化输出两字段 |
| `api/internal/schema/admin_audit_log_schema.py` | `AuditLogResp` 新增 `actor_type` / `agent_name` |
| `api/internal/service/admin_agent_service.py` | 新增 `get_principal()`（组装 `AdminAgentPrincipal`） |
| `api/internal/service/recycle_bin_service.py` | 支持 `admin_agent` 来源（校验 / 留存 / 名称解析 / 列表过滤） |
| `api/internal/service/routing_policy_change_service.py` | 泛化：`suggestion_id` 可空 + 板块标识；保留路由既有行为 |
| `api/internal/service/builtin_tool_service.py` | 新增 `set_tool_enabled()`（补 `builtin_tool.enabled` 写路径） |
| `api/app/http/admin_routes_8.py` | `_builtin_tool_update` 白名单放开 `enabled` 并置 `source="custom"` |
| `api/app/http/admin_routes_7.py` | 追加 `/admin/agents/<id>/invoke` 与 `/admin/agents/<id>/drafts` 端点 |
| `api/app/http/support.py` | `_admin_route_permission` 登记新路径 |
| `api/internal/core/prompts/index.yaml` | 登记 `admin_agent/board_agent.yaml` |
| `docs/rbac.md` | 板块工具与审计身份机制 |
| `docs/prd/modules/01-agent-tool-pool.md` | `internal_admin` 池消费方接线状态 |
| `docs/prd/modules/03-orchestration-infra.md` | 变更草稿泛化 |
| `docs/prd/execution-roadmap.md` | P1b 完成记录 |

**为什么新建 `admin_agent_boards.py` 而非把 action 表写进工具文件**：板块动作注册表是**授权边界**（未声明即拒绝），必须能被独立测试与静态核对；写进工具实现体会让它与"执行"耦合，无法单独审计"哪个 action 需要哪个权限点"。

---

## Task 1: 修复审计写入静默丢失（P1b 的前置）

**为什么先做这个**：P1b 要为 Agent 写 `actor_type=agent` 的审计。若审计写入本身存在"写完不提交 → 被 `session.remove()` 回滚"的缺陷，新链路会继承同样的静默丢失，且无法验证。必须先让审计写入可信。

**Files:**
- Modify: `api/internal/service/admin_user_service.py:696-707`
- Modify: `api/internal/service/admin_redeem_code_service.py:162-176`
- Modify: `api/internal/service/scoped_knowledge_service.py:25-57, 160-230`
- Modify: `api/app/http/admin_commerce_routes.py:26-40`
- Test: `api/test/internal/service/test_audit_write_commit_guard.py`（新建）

- [x] **Step 1: 写失败测试（静态扫描守卫）**

创建 `api/test/internal/service/test_audit_write_commit_guard.py`：

```python
"""审计写入提交守卫。

背景：`AuditLogService.record_for_write` 的契约是 `commit=False`，必须由调用方
事务提交。历史上有 3 处调用点在其后**再无 commit**，而请求/工作线程退出时
`runtime_context._exit_scope()` 会 `db.session.remove()`，`Session.close()`
回滚未提交事务 → 审计行永久丢失。另有 1 处路由层直接 `db.session.add(AuditLog)`
且永不提交。

本守卫用 AST 静态扫描：凡调用 `record_for_write(` 或 `db.session.add(AuditLog(`
的函数，其函数体内必须出现 `commit(`，否则视为违规。

为什么不用运行时测试：这类"写入后丢失"只在真实 session 生命周期结束时才显现，
单测里 session 是替身、不会 close，测不出；必须用静态扫描把契约固化。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[3]
SCAN_DIRS = (API_ROOT / "internal" / "service", API_ROOT / "app" / "http")

# 允许豁免的文件（每个都必须写清理由，且**不得为空**）
ALLOWLIST: dict[str, str] = {}


def _iter_source_files():
    for base in SCAN_DIRS:
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def _writes_audit(node: ast.AST) -> tuple[bool, str]:
    """判断函数体内是否有审计写入；返回 (是否命中, 命中说明)。"""
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            # 形式一：self.audit_log_service.record_for_write(...) / xxx.record_for_write(...)
            if isinstance(func, ast.Attribute) and func.attr == "record_for_write":
                return True, "record_for_write"
            # 形式二：db.session.add(AuditLog(...))
            if isinstance(func, ast.Attribute) and func.attr == "add" and child.args:
                arg = child.args[0]
                if isinstance(arg, ast.Call):
                    name = getattr(arg.func, "id", None) or getattr(arg.func, "attr", None)
                    if name == "AuditLog":
                        return True, "session.add(AuditLog)"
    return False, ""


def _has_commit(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr in {"commit", "auto_commit"}:
                return True
            if isinstance(func, ast.Name) and func.id == "commit":
                return True
    return False


def _collect_violations() -> list[str]:
    violations: list[str] = []
    for path in _iter_source_files():
        rel = path.relative_to(API_ROOT).as_posix()
        if rel in ALLOWLIST:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            hit, how = _writes_audit(node)
            if not hit:
                continue
            if not _has_commit(node):
                violations.append(f"{rel}::{node.name} 通过 {how} 写审计但函数体内无 commit")
    return violations


def test_audit_writes_must_be_committed():
    """每个写审计的函数必须在同一函数体内提交。"""
    violations = _collect_violations()
    assert violations == [], (
        "以下位置写审计后未提交，事务回滚会导致审计静默丢失：\n  "
        + "\n  ".join(violations)
    )


class TestDetectorSelfCheck:
    """守卫自检：正则/AST 失效会让守卫恒真，必须证明它真的能命中违规。"""

    def test_detects_missing_commit(self):
        tree = ast.parse(
            "def f(self):\n"
            "    self.audit_log_service.record_for_write(admin_user_id=1)\n"
        )
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        assert _writes_audit(fn)[0] is True
        assert _has_commit(fn) is False

    def test_direct_auditlog_add_detected(self, tmp_path):
        tree = ast.parse(
            "def f():\n"
            "    db.session.add(AuditLog(admin_user_id=1))\n"
        )
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        hit, how = _writes_audit(fn)
        assert hit is True
        assert how == "session.add(AuditLog)"
        assert _has_commit(fn) is False

    def test_commit_detected(self):
        tree = ast.parse(
            "def f():\n"
            "    self.audit_log_service.record_for_write(admin_user_id=1)\n"
            "    self.session.commit()\n"
        )
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        assert _writes_audit(fn)[0] is True
        assert _has_commit(fn) is True
```

> ⚠️ 上面 `test_detects_missing_commit` 已按上表形式写好（不要引入 `import api_guard_helpers` 之类的占位行）；三个自检用例都直接对 `ast.parse` 出来的函数做断言。

- [x] **Step 2: 运行测试，确认失败并列出全部违规点**

```bash
cd api && python -m pytest test/internal/service/test_audit_write_commit_guard.py --no-cov -p no:cacheprovider -q
```

预期：FAIL，`test_audit_writes_must_be_committed` 报出 4 个文件内的违规函数（`revoke_admin_sessions`、`view_plain_code`、`create_system_knowledge` / `update_system_knowledge` / `delete_system_knowledge`、`_write_audit`）。

把实际报出的清单**照抄进终端记录**，后续按清单逐条修。

- [x] **Step 3: 修 `admin_user_service.revoke_admin_sessions`**

`api/internal/service/admin_user_service.py`：把 `self.session.commit()` 移到 `_emit_audit` 之后。

```python
        now = self._now()
        # 撤销该管理员的所有活跃 AdminSession
        sessions = self.session.query(AdminSession).filter(AdminSession.admin_user_id == admin_user_id).all()
        revoked_count = 0
        for session in sessions:
            if session.revoked_at is None and (session.expires_at is None or session.expires_at >= now):
                session.revoked_at = now
                revoked_count += 1
        # 审计日志：记录踢下线操作及撤销会话数量
        # 必须在 commit 之前写入：record_for_write 是 commit=False，
        # 事务由本次 commit 一并提交；顺序颠倒会让审计在 commit 之后写入，
        # 而 session 归还时的 close() 会回滚它，导致审计静默丢失。
        self._emit_audit(
            operator_id=operator_id,
            action="revoke_admin_sessions",
            resource_type="admin_user",
            resource_id=str(admin_user.id),
            ip=ip,
            user_agent=user_agent,
            after_data={"revoked_count": revoked_count},
        )
        self.session.commit()
        return {"revoked_sessions": revoked_count}
```

- [x] **Step 4: 修 `admin_redeem_code_service.view_plain_code`**

先 `Read` 该方法的完整实现（约 L150-180），确认它当前**没有任何 commit**。在其 `_emit_audit(...)` 之后补 `self.session.commit()`：

```python
        self._emit_audit(
            operator_id=operator_id,
            action="view_plain",
            resource_type="redeem_code",
            resource_id=str(code_id),
            ip=ip,
            user_agent=user_agent,
            after_data={"batch_id": str(batch_id)},
        )
        # record_for_write 是 commit=False；明文查看是只读操作、业务上无其它写，
        # 因此这里必须显式提交，否则审计会随 session 归还被回滚丢弃。
        self.session.commit()
        return {...}   # 保持既有返回值不变
```

> 实现者注意：`view_plain_code` 的既有返回值结构不要改动，只在 `_emit_audit` 后插入 commit。

- [x] **Step 5: 修 `scoped_knowledge_service` 三处**

`api/internal/service/scoped_knowledge_service.py`。三处 `_emit_audit` 都在 `BaseService.auto_commit()` / `RecycleBinService.delete_resource()`（二者各自已 `commit()` + `remove()`）**之后**调用，因此审计写入的是一个已被归还的 session，必须自行提交。

**推荐做法（更稳）**：不逐处补 commit，而是让 `SystemKnowledgeService._emit_audit` 自己提交——它的语义是"审计是独立于业务事务的旁路记录"，与 `record_for_write` 的"随调用方事务"契约本就不同。

修改 `_emit_audit`（L490-515）：

```python
    def _emit_audit(
        self,
        *,
        admin_user_id,
        action: str,
        resource_id: str = "",
        before_data: dict | None = None,
        after_data: dict | None = None,
    ) -> None:
        """记录系统级知识库操作审计日志，失败不影响主流程。

        此处用 `record(commit=True)` 而非 `record_for_write(commit=False)`：
        三个调用点（create/update/delete）的业务写分别经由
        ``BaseService.auto_commit()`` 与 ``RecycleBinService.delete_resource()``
        提交，二者都会 `session.remove()` 归还 session；若审计再走
        "随调用方事务"，它写入的将是已归还的 session，退出时被 close() 回滚，
        导致 system_knowledge 的审计**全部**丢失。
        """
        if not admin_user_id:
            return
        try:
            self._get_audit_log_service().record(
                admin_user_id=admin_user_id,
                action=action,
                resource_type="system_knowledge",
                resource_id=resource_id,
                before_data=before_data,
                after_data=after_data,
                commit=True,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "系统知识库审计日志记录失败，不影响主流程", exc_info=True
            )
```

- [x] **Step 6: 修 `admin_commerce_routes._write_audit`**

`api/app/http/admin_commerce_routes.py`。该 helper 在**事件循环线程**里 `db.session.add(...)`，而业务写发生在线程池 worker 的另一个 thread-scoped session 上，`teardown_request` 只 `remove()` 不 commit → 4 类审计（关单 / 提现 / 退款 / 支付配置）全部丢失。

改为走 `AuditLogService.record(commit=True)`：

```python
def _write_audit(admin_id, action, resource_type, resource_id, before_data, after_data, note=None):
    """写入管理员操作审计。note 仅作过程说明（AuditLog 无独立备注列）。

    必须用 `commit=True`（而非直接 db.session.add 后不管）：本函数运行在事件
    循环线程，与线程池 worker 的 session 不是同一个；且 asgi teardown 只
    `remove()` 不提交，业务事务提交不会捎带这条审计。历史上此处的 4 类
    审计（关单/提现/退款/支付配置）因此全部丢失。
    """
    from internal.service.audit_log_service import AuditLogService

    merged_after = dict(after_data or {})
    if note:
        # AuditLog 无独立备注列，note 归入 after_data 以免丢失过程说明
        merged_after.setdefault("_note", note)
    AuditLogService().record(
        admin_user_id=admin_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else "",
        before_data=before_data,
        after_data=merged_after,
        commit=True,
    )
```

> 实现者注意：`_write_audit` 目前是**同步函数**，被 async 路由直接调用。`AuditLogService.record` 也是同步的，保持同步调用即可（与相邻既有代码一致）；不要改成 `await a._to_thread(...)`，否则会引入本任务范围外的线程/事务语义变化。若静态守卫报出"异步函数内调用同步 DB"，按 Step 2 的实际报错处理。

- [x] **Step 7: 运行守卫测试，确认通过**

```bash
cd api && python -m pytest test/internal/service/test_audit_write_commit_guard.py --no-cov -p no:cacheprovider -q
```

预期：PASS（4 个用例：主扫描 + 3 个自检）。

- [x] **Step 8: 反向验证**

临时把 `admin_user_service.revoke_admin_sessions` 里的 commit 移回 `_emit_audit` **之前**，重跑守卫：

```bash
cd api && python -m pytest test/internal/service/test_audit_write_commit_guard.py --no-cov -p no:cacheprovider -q
```

预期：**必须 FAIL**（报出 `admin_user_service.py::revoke_admin_sessions`）。

> 注意：本守卫是"函数体内无 commit"级别，把 commit 移到 `_emit_audit` 之前仍然"函数体内有 commit"，因此**不会**被这条守卫捕获——这正是本守卫的已知局限。反向验证请改为**临时删除**该 commit，预期 FAIL，然后恢复。

- [x] **Step 9: 跑既有审计相关测试**

```bash
cd api && python -m pytest test/internal/service/test_audit_log_service.py test/internal/service/test_admin_user_service.py test/internal/service/test_admin_customer_user_service.py --no-cov -p no:cacheprovider -q
```

预期：全部 PASS。

- [x] **Step 10: 提交**

```bash
cd api && git add internal/service/admin_user_service.py internal/service/admin_redeem_code_service.py internal/service/scoped_knowledge_service.py app/http/admin_commerce_routes.py test/internal/service/test_audit_write_commit_guard.py
git commit -m "fix(audit): commit audit writes that were silently rolled back

record_for_write 是 commit=False，必须由调用方事务提交；有 3 处调用点其后
再无 commit，而线程退出时 session.remove() 会 rollback 未提交事务，导致
审计行永久丢失：admin_user.revoke_admin_sessions、redeem_code.view_plain、
system_knowledge 的 create/update/delete（后者三个调用点的业务写分别经
auto_commit() 与 delete_resource() 提交并 remove，审计写入的是已归还的
session）。

另有 admin_commerce_routes._write_audit 在事件循环线程直接
db.session.add(AuditLog) 且永不提交（业务写在线程池 worker 的另一个
session 上，teardown 只 remove 不 commit），关单/提现/退款/支付配置 4 类
审计全部丢失；改为走 AuditLogService.record(commit=True)。

新增 AST 静态守卫 test_audit_write_commit_guard.py：写审计的函数必须在
同一函数体内 commit，并含 3 个检测器自检防止守卫退化为恒真。"
```

---

## Task 2: `audit_log` 新增 `actor_type` / `agent_id`

**Files:**
- Modify: `api/internal/model/admin.py:209-233`
- Create: `api/internal/migration/versions/<new_rev>_add_audit_log_actor_fields.py`
- Modify: `api/internal/service/audit_log_service.py`（`record` / `record_for_write` / `_serialize_audit_log`）
- Modify: `api/internal/schema/admin_audit_log_schema.py`
- Test: `api/test/internal/model/test_audit_log_actor_fields.py`（新建）

- [x] **Step 1: 写失败测试（列结构）**

创建 `api/test/internal/model/test_audit_log_actor_fields.py`：

```python
"""audit_log.actor_type / agent_id 列结构测试（设计 §9）。"""
from internal.model.admin import AuditLog


def test_audit_log_has_actor_type_defaulting_to_human():
    """actor_type 必须 NOT NULL 且默认 human——存量记录语义为人工操作。"""
    col = AuditLog.__table__.c.actor_type
    assert col.nullable is False
    assert "human" in str(col.server_default.arg)


def test_audit_log_has_nullable_agent_id():
    """agent_id 可空：人工操作没有 agent。"""
    col = AuditLog.__table__.c.agent_id
    assert col.nullable is True


def test_agent_id_has_no_hard_fk_constraint():
    """agent_id 不加 FK 约束。

    理由：admin_agent 行可被删除（P1a 的 delete_agent 是物理删除），若加
    ON DELETE 约束，删除 Agent 会连带影响历史审计；审计的价值恰在于
    "即使主体被删也要留住痕迹"。因此保留为逻辑引用（与 policy_change_draft
    的零外键设计一致）。
    """
    fks = {
        fk.target_fullname
        for fk in AuditLog.__table__.c.agent_id.foreign_keys
    }
    assert fks == set()
```

- [x] **Step 2: 运行测试，确认失败**

```bash
cd api && python -m pytest test/internal/model/test_audit_log_actor_fields.py --no-cov -p no:cacheprovider -q
```

预期：FAIL，`AttributeError`（`actor_type` 不存在）。

- [x] **Step 3: 修改模型**

`api/internal/model/admin.py` 的 `AuditLog` 类，在 `account_id` 之后插入两列：

```python
    admin_user_id = Column(UUID, ForeignKey("admin_user.id"), nullable=True)
    account_id = Column(UUID, ForeignKey("account.id"), nullable=True)
    # 操作者类型：human=管理员本人操作 / agent=管理端 Agent 代操作（设计 §9）。
    # admin_user_id 始终保持为**人类责任人**，因此能精确区分
    # "A 自己改的" 与 "A 让 AI 改的"。
    actor_type = Column(
        String(16),
        nullable=False,
        server_default=text("'human'::character varying"),
    )
    # 执行该操作的 Agent（仅 actor_type=agent 时有值）。
    # 刻意**不加 FK 约束**：Agent 行可被物理删除，而审计必须留住痕迹
    # （与 policy_change_draft 的零外键设计一致）。
    agent_id = Column(UUID, nullable=True)
```

并在 `__table_args__` 追加索引：

```python
        Index("audit_log_actor_type_idx", "actor_type"),
        Index("audit_log_agent_id_idx", "agent_id"),
```

- [x] **Step 4: 运行模型测试，确认通过**

```bash
cd api && python -m pytest test/internal/model/test_audit_log_actor_fields.py --no-cov -p no:cacheprovider -q
```

预期：PASS（3 个用例）。

- [x] **Step 5: 写迁移**

先确认当前 head：

```bash
cd api && python -c "
import ast, os
d='internal/migration/versions'
revs={}; downs=set()
for f in os.listdir(d):
    if not f.endswith('.py'): continue
    t=ast.parse(open(os.path.join(d,f),encoding='utf-8').read())
    r=x=None
    for n in t.body:
        if isinstance(n, ast.Assign):
            for tg in n.targets:
                if isinstance(tg, ast.Name) and tg.id=='revision': r=ast.literal_eval(n.value)
                if isinstance(tg, ast.Name) and tg.id=='down_revision': x=ast.literal_eval(n.value)
    if r: revs[r]=f
    if x:
        for i in (x if isinstance(x,(tuple,list)) else [x]): downs.add(i)
print('HEADS:', [k for k in revs if k not in downs])
"
```

预期输出：`HEADS: ['s5f6a7b8c9d0']`

创建 `api/internal/migration/versions/t8b9c0d1e2f3_add_audit_log_actor_fields.py`：

```python
"""add audit_log.actor_type / agent_id

设计依据：docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md §9。
用于区分"管理员本人操作"与"管理员让 Agent 代操作"。

Revision ID: t8b9c0d1e2f3
Revises: s5f6a7b8c9d0
"""
from alembic import op
import sqlalchemy as sa

revision = "t8b9c0d1e2f3"
down_revision = "s5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "audit_log",
        sa.Column(
            "actor_type",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'human'::character varying"),
        ),
    )
    op.add_column("audit_log", sa.Column("agent_id", sa.UUID(), nullable=True))
    op.create_index("audit_log_actor_type_idx", "audit_log", ["actor_type"])
    op.create_index("audit_log_agent_id_idx", "audit_log", ["agent_id"])


def downgrade():
    op.drop_index("audit_log_agent_id_idx", table_name="audit_log")
    op.drop_index("audit_log_actor_type_idx", table_name="audit_log")
    op.drop_column("audit_log", "agent_id")
    op.drop_column("audit_log", "actor_type")
```

> `server_default` 让存量行自动填 `human`，无需数据回填语句——这是"行为零变化"的关键。

- [x] **Step 6: 应用迁移并核对 DB**

```bash
cd api && alembic upgrade head
```

然后核对（用项目既有的连库方式，如 `python -c` + `db.engine`）：

```bash
cd api && python -c "
from app.http import asgi_app  # noqa
from internal.extension.database_extension import db
from sqlalchemy import text
with db.engine.connect() as c:
    rows = c.execute(text(\"SELECT column_name, is_nullable, column_default FROM information_schema.columns WHERE table_name='audit_log' AND column_name IN ('actor_type','agent_id') ORDER BY column_name\")).fetchall()
    for r in rows: print(r)
    idx = c.execute(text(\"SELECT indexname FROM pg_indexes WHERE tablename='audit_log' AND indexname LIKE '%actor%' OR indexname LIKE '%agent_id%'\")).fetchall()
    print('IDX', idx)
    ver = c.execute(text('SELECT version_num FROM alembic_version')).fetchall()
    print('ALEMBIC', ver)
"
```

预期：`actor_type` 非空且默认含 `human`；`agent_id` 可空；两个索引存在；`alembic_version` = `t8b9c0d1e2f3`。

- [x] **Step 7: 写失败测试（service 透传）**

追加到 `api/test/internal/model/test_audit_log_actor_fields.py`：

```python
def test_record_passes_actor_fields():
    """record() 必须把 actor_type / agent_id 写进 AuditLog 实例。

    否则 Agent 代操作的审计会退化成 actor_type=human，审计页无法区分。
    """
    from uuid import uuid4

    from internal.service.audit_log_service import AuditLogService

    captured = {}

    class _SessionStub:
        def add(self, obj):
            captured["obj"] = obj

        def commit(self):
            captured["committed"] = True

    agent_id = uuid4()
    svc = AuditLogService(session=_SessionStub())
    svc.record(
        admin_user_id=uuid4(),
        action="update",
        resource_type="builtin_tool",
        actor_type="agent",
        agent_id=agent_id,
    )
    obj = captured["obj"]
    assert obj.actor_type == "agent"
    assert obj.agent_id == agent_id
    assert captured["committed"] is True


def test_record_defaults_to_human_without_agent():
    from uuid import uuid4

    from internal.service.audit_log_service import AuditLogService

    captured = {}

    class _SessionStub:
        def add(self, obj):
            captured["obj"] = obj

        def commit(self):
            pass

    svc = AuditLogService(session=_SessionStub())
    svc.record(
        admin_user_id=uuid4(), action="update", resource_type="x",
    )
    assert captured["obj"].actor_type == "human"
    assert captured["obj"].agent_id is None
```

- [x] **Step 8: 运行测试，确认失败**

```bash
cd api && python -m pytest test/internal/model/test_audit_log_actor_fields.py --no-cov -p no:cacheprovider -q
```

预期：FAIL（`record()` 不接受 `actor_type` 关键字参数）。

- [x] **Step 9: 实现 service 透传**

`api/internal/service/audit_log_service.py`。`record` 增加两参数：

```python
    def record(
        self,
        *,
        admin_user_id,
        action: str,
        resource_type: str,
        resource_id: str = "",
        ip: str = "",
        user_agent: str = "",
        before_data: dict | None = None,
        after_data: dict | None = None,
        actor_type: str = "human",
        agent_id=None,
        commit: bool = True,
    ) -> AuditLog:
        audit_log = AuditLog(
            admin_user_id=admin_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip=ip,
            user_agent=user_agent,
            before_data=before_data or {},
            after_data=after_data or {},
            actor_type=actor_type,
            agent_id=agent_id,
        )
        self.session.add(audit_log)
        if commit:
            self.session.commit()
        return audit_log
```

`record_for_write` 增加同样的两参数并透传：

```python
    def record_for_write(
        self,
        *,
        admin_user_id,
        action: str,
        resource_type: str,
        resource_id: str = "",
        ip: str = "",
        user_agent: str = "",
        before_data: dict | None = None,
        after_data: dict | None = None,
        actor_type: str = "human",
        agent_id=None,
    ) -> AuditLog | None:
        if not admin_user_id:
            return None
        return self.record(
            admin_user_id=admin_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip=ip,
            user_agent=user_agent,
            before_data=before_data,
            after_data=after_data,
            actor_type=actor_type,
            agent_id=agent_id,
            commit=False,
        )
```

`_serialize_audit_log` 输出两字段（在 `"resource_name":` 之后追加）：

```python
            "actor_type": getattr(audit_log, "actor_type", "human") or "human",
            "agent_id": str(audit_log.agent_id) if audit_log.agent_id else None,
```

> `getattr(..., "human")` 兜底：审计序列化会处理历史对象/替身，缺列时不应 500。

- [x] **Step 10: 运行测试，确认通过**

```bash
cd api && python -m pytest test/internal/model/test_audit_log_actor_fields.py test/internal/service/test_audit_log_service.py --no-cov -p no:cacheprovider -q
```

预期：PASS。

- [x] **Step 11: 补 schema 字段**

`api/internal/schema/admin_audit_log_schema.py` 的 `AuditLogResp`：

```python
    resource_name = fields.String()
    actor_type = fields.String(dump_default="human")
    agent_id = fields.String(allow_none=True)
    agent_name = fields.String(dump_default="")
    ip = fields.String()
```

> `agent_name` 为派生字段，由 Task 9 的批量回源填充（与 `admin_user_name` 同模式）；本步先声明，保证契约完整。

- [x] **Step 12: 反向验证**

临时把 `record()` 里的 `actor_type=actor_type, agent_id=agent_id,` 删掉，重跑 Step 10：

```bash
cd api && python -m pytest test/internal/model/test_audit_log_actor_fields.py --no-cov -p no:cacheprovider -q
```

预期：**必须 FAIL**（`record` 写入的实例 `actor_type` 为 `None`）。恢复。

- [x] **Step 13: 提交**

```bash
cd api && git add internal/model/admin.py internal/migration/versions/t8b9c0d1e2f3_add_audit_log_actor_fields.py internal/service/audit_log_service.py internal/schema/admin_audit_log_schema.py test/internal/model/test_audit_log_actor_fields.py
git commit -m "feat(audit): distinguish human vs agent operations (P1b)

audit_log 新增 actor_type（human|agent，NOT NULL，server_default='human'）
与 agent_id（可空，刻意不加 FK——Agent 可被物理删除，审计必须留住痕迹）。

admin_user_id 始终保持为人类责任人，因此可精确区分「A 自己改的」与
「A 让 AI 改的」；审计页可据此加「只看 AI 操作」筛选。

record / record_for_write 增加两参数透传，_serialize_audit_log 输出
actor_type / agent_id，AuditLogResp 同步声明 agent_name（派生字段）。"
```

---

## Task 3: 板块动作注册表（fail closed）

**Files:**
- Create: `api/internal/core/admin_agent_boards.py`
- Test: `api/test/internal/core/test_admin_agent_boards.py`（新建）

- [x] **Step 1: 写失败测试**

创建 `api/test/internal/core/test_admin_agent_boards.py`：

```python
"""板块动作注册表测试（设计 §7.1 执行四步的第 1 步）。

核心不变式：**未声明的 action 必须被拒绝**（fail closed）。
工具内部按 action 分支，若校验漏了某个 action 就会越权，因此
"未声明即拒绝"是本设计的硬约束。
"""
import pytest

from internal.core.admin_agent_boards import (
    BOARD_ACTIONS,
    BOARD_IDS,
    BoardAction,
    board_ids_of,
    resolve_action,
)


class TestBoardActionRegistry:
    def test_registry_is_not_empty(self):
        """守卫：注册表为空会让所有测试恒真。"""
        assert len(BOARD_ACTIONS) > 0
        assert len(BOARD_IDS) > 0

    def test_builtin_tool_board_is_registered(self):
        """P1b 的样板板块必须已登记。"""
        assert "builtin_tool" in BOARD_IDS

    def test_every_action_declares_a_permission_code(self):
        """每个 action 必须显式声明所需权限点，且必须是真实存在的 code。"""
        from internal.core.rbac import PERMISSION_BY_CODE

        for action in BOARD_ACTIONS:
            assert action.permission_code, f"{action} 未声明 permission_code"
            assert action.permission_code in PERMISSION_BY_CODE, (
                f"{action} 声明的 {action.permission_code} 不在权限目录中"
            )

    def test_resolve_action_returns_declared_action(self):
        action = resolve_action("builtin_tool", "update_enabled")
        assert action.permission_code == "builtin_tool:update"
        assert action.is_write is True

    def test_unknown_action_is_rejected(self):
        """未声明的 action 必须抛错（fail closed）。"""
        with pytest.raises(ValueError):
            resolve_action("builtin_tool", "drop_everything")

    def test_unknown_board_is_rejected(self):
        with pytest.raises(ValueError):
            resolve_action("not_a_board", "list")

    def test_board_ids_are_derived_from_actions(self):
        """BOARD_IDS 必须由 BOARD_ACTIONS 派生，不允许手工维护两个清单。"""
        assert set(BOARD_IDS) == {a.board for a in BOARD_ACTIONS}

    def test_board_ids_of_lists_actions_of_one_board(self):
        ids = board_ids_of("builtin_tool")
        assert "update_enabled" in ids
        assert set(ids) == {
            a.action for a in BOARD_ACTIONS if a.board == "builtin_tool"
        }

    def test_read_actions_are_marked_not_write(self):
        action = resolve_action("builtin_tool", "list")
        assert action.is_write is False


class TestReverseValidationNote:
    """反向验证记录（人工执行，见计划 Step 6）。

    把 `resolve_action` 的「未声明即拒绝」改成返回一个默认 BoardAction
    （fail open）时，`test_unknown_action_is_rejected` 与
    `test_unknown_board_is_rejected` 必须失败。已人工验证。
    """
```

- [x] **Step 2: 运行测试，确认失败**

```bash
cd api && python -m pytest test/internal/core/test_admin_agent_boards.py --no-cov -p no:cacheprovider -q
```

预期：FAIL（`ModuleNotFoundError: internal.core.admin_agent_boards`）。

- [x] **Step 3: 实现注册表**

创建 `api/internal/core/admin_agent_boards.py`：

```python
"""管理端 Agent 板块动作注册表（设计 §7.1）。

为什么单独成文件：板块动作 → 所需权限点 的映射是**授权边界**，必须能被
独立测试与静态核对。若把它写进工具实现体，就会与"执行"耦合，无法单独
审计"哪个 action 需要哪个权限点"。

核心不变式：**未声明的 (board, action) 一律拒绝**（fail closed）。
工具内部按 action 分支，若校验漏了某个 action 就会越权；显式登记制使
"新增 action 忘记声明"表现为明确报错，而不是静默放行。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ActionKind = Literal["read", "write", "delete"]


@dataclass(frozen=True)
class BoardAction:
    """一个板块动作的声明。

    Attributes:
        board: 板块标识（同时作为 automation_policy 的键）。
        action: 动作标识。
        kind: 动作类别。``delete`` 类必须走回收站（设计 §5.1）。
        permission_code: 执行该动作所需的权限点（必须在 PERMISSION_CATALOG 中）。
        description: 人类可读说明，用于工具 schema 文档与审计。
    """

    board: str
    action: str
    kind: ActionKind
    permission_code: str
    description: str = ""

    @property
    def is_write(self) -> bool:
        """是否需要按 automation_policy 分流。

        只读动作不进草稿、不需要自动化级别判定——否则「只读也要人工批准」
        会让 supervised 档的 Agent 连列表都查不了。
        """
        return self.kind in ("write", "delete")


def _a(board, action, kind, permission_code, description="") -> BoardAction:
    return BoardAction(
        board=board,
        action=action,
        kind=kind,
        permission_code=permission_code,
        description=description,
    )


# 板块动作登记表。
# 约定：每个板块至少登记一个只读 action（否则 Agent 无法了解现状再动手）。
BOARD_ACTIONS: tuple[BoardAction, ...] = (
    # -------- 内置工具（P1b 端到端样板板块）--------
    _a("builtin_tool", "list", "read", "builtin_tool:read", "列出内置工具及其启停状态"),
    _a("builtin_tool", "update_enabled", "write", "builtin_tool:update", "启用/停用某个内置工具"),
    _a("builtin_tool", "update_metadata", "write", "builtin_tool:update", "更新内置工具的标签/描述/关键词"),
)

BOARD_IDS: tuple[str, ...] = tuple(sorted({a.board for a in BOARD_ACTIONS}))

_INDEX: dict[tuple[str, str], BoardAction] = {
    (a.board, a.action): a for a in BOARD_ACTIONS
}


def resolve_action(board: str, action: str) -> BoardAction:
    """解析 (board, action) 声明；未声明则抛 ValueError（fail closed）。

    Raises:
        ValueError: 板块或动作未登记。
    """
    board = str(board or "").strip()
    action = str(action or "").strip()
    if not board or not action:
        raise ValueError("board 与 action 不能为空")
    declared = _INDEX.get((board, action))
    if declared is None:
        known = sorted(a for (b, a) in _INDEX if b == board)
        if not known:
            raise ValueError(
                f"未登记的板块: {board}（已登记板块: {', '.join(BOARD_IDS)}）"
            )
        raise ValueError(
            f"板块 {board} 未登记动作 {action}（已登记: {', '.join(known)}）"
        )
    return declared


def board_ids_of(board: str) -> list[str]:
    """列出某板块已登记的全部 action（用于工具 schema 与报错提示）。"""
    board = str(board or "").strip()
    return sorted(a.action for (b, a) in _INDEX if b == board)


def boards() -> tuple[str, ...]:
    """全部已登记板块。"""
    return BOARD_IDS
```

- [x] **Step 4: 运行测试，确认通过**

```bash
cd api && python -m pytest test/internal/core/test_admin_agent_boards.py --no-cov -p no:cacheprovider -q
```

预期：PASS。

- [x] **Step 5: 反向验证（fail open）**

临时把 `resolve_action` 末尾改为：

```python
    declared = _INDEX.get((board, action))
    if declared is None:
        # 反向验证：故意 fail open
        return BoardAction(board=board, action=action, kind="read", permission_code="builtin_tool:read")
```

重跑：

```bash
cd api && python -m pytest test/internal/core/test_admin_agent_boards.py --no-cov -p no:cacheprovider -q
```

预期：**必须 FAIL**（`test_unknown_action_is_rejected` 与 `test_unknown_board_is_rejected`）。恢复实现。

- [x] **Step 6: 提交**

```bash
cd api && git add internal/core/admin_agent_boards.py test/internal/core/test_admin_agent_boards.py
git commit -m "feat(admin-agent): add board action registry with fail-closed resolution

按设计 §7.1 建立「板块动作 → 所需权限点」的显式登记表。未声明的
(board, action) 一律抛 ValueError——工具内部按 action 分支，漏声明必须
表现为明确报错而非静默放行（fail closed）。

BoARD_IDS 由 BOARD_ACTIONS 派生，避免两个清单手工同步。is_write 区分
只读/写/删：只读动作不进变更草稿，否则 supervised 档的 Agent 连列表都
查不了。

首个登记板块为 builtin_tool（P1b 端到端样板）。"
```

---

## Task 4: 通用变更草稿（`policy_change_draft` 泛化）

**Files:**
- Modify: `api/internal/model/routing_quality.py:89-122`
- Create: `api/internal/migration/versions/<new_rev>_generalize_policy_change_draft.py`
- Create: `api/internal/service/admin_change_draft_service.py`
- Test: `api/test/internal/service/test_admin_change_draft_service.py`（新建）
- Test: `api/test/internal/model/test_policy_change_draft_generalization.py`（新建）

- [x] **Step 1: 写失败测试（模型泛化）**

创建 `api/test/internal/model/test_policy_change_draft_generalization.py`：

```python
"""policy_change_draft 泛化测试（设计 §5.2）。

泛化内容：suggestion_id 由 NOT NULL 改为可空——通用草稿可不来自路由建议。
路由既有取值保持兼容。
"""
from internal.model.routing_quality import PolicyChangeDraftModel


def test_suggestion_id_is_now_nullable():
    """通用草稿不需要来源建议，因此必须可空。

    若仍 NOT NULL，supervised 档的板块草稿写入会直接 IntegrityError。
    """
    col = PolicyChangeDraftModel.__table__.c.suggestion_id
    assert col.nullable is True


def test_policy_type_semantics_is_board_identifier():
    """policy_type 语义扩展为「板块标识」，长度必须放得下最长板块名。"""
    col = PolicyChangeDraftModel.__table__.c.policy_type
    assert col.type.length >= 64


def test_status_still_covers_three_states():
    """路由既有状态机不变（pending / applied / rolled_back）。"""
    col = PolicyChangeDraftModel.__table__.c.status
    assert col.nullable is False


def test_has_created_at_index_for_global_listing():
    """通用草稿需要「列出全部待应用草稿」，因此需要 status/created_at 维度索引。"""
    names = {idx.name for idx in PolicyChangeDraftModel.__table__.indexes}
    assert "policy_change_draft_status_created_idx" in names
```

- [x] **Step 2: 运行测试，确认失败**

```bash
cd api && python -m pytest test/internal/model/test_policy_change_draft_generalization.py --no-cov -p no:cacheprovider -q
```

预期：FAIL（`suggestion_id` 仍是 `nullable=False`；索引不存在）。

- [x] **Step 3: 修改模型**

`api/internal/model/routing_quality.py` 的 `PolicyChangeDraftModel`：

```python
class PolicyChangeDraftModel(Base):
    """策略变更草稿（已泛化为**通用 admin 变更草稿**，设计 §5.2）。

    泛化说明：
    - ``suggestion_id`` 可空——通用草稿（如 builtin_tool 的启停建议）不来自
      路由调优建议。路由路径仍会写入它，既有取值保持兼容。
    - ``policy_type`` 语义扩展为**板块标识**（承载任意 admin 板块，如
      ``builtin_tool`` / ``prompt_template``）；路由三个既有取值
      （``model_routing`` / ``tool_policy`` / ``agent_policy``）保持不变。
    - 无任何外键（与原设计一致）：草稿是台账，主体被删也要留住痕迹。
    """

    __tablename__ = "policy_change_draft"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_policy_change_draft_id"),
        Index("policy_change_draft_suggestion_id_idx", "suggestion_id"),
        Index("policy_change_draft_status_idx", "status"),
        # 通用草稿需要「列出全部板块的待应用草稿」这条查询
        Index(
            "policy_change_draft_status_created_idx",
            "status",
            "created_at",
        ),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    # 来源调优建议；通用草稿为 NULL（路由路径仍写入，保持兼容）
    suggestion_id = Column(UUID, nullable=True)
```

> 其余列保持不变。**注意**：`suggestion_id` 的类型注解不要加 `| None`（SQLAlchemy `Column` 不做 Python 类型检查），只改 `nullable`。

- [x] **Step 4: 写迁移**

创建 `api/internal/migration/versions/u9c0d1e2f3a4_generalize_policy_change_draft.py`（`down_revision = "t8b9c0d1e2f3"`，即 Task 2 新建的迁移）：

```python
"""generalize policy_change_draft into a generic admin change draft

设计依据：docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md §5.2。

`suggestion_id` 由 NOT NULL 改为可空（通用草稿可不来自路由建议），
并补一条 (status, created_at) 索引支撑「列出全部待应用草稿」。
路由既有行为与三个 policy_type 取值保持兼容，存量数据零迁移。

Revision ID: u9c0d1e2f3a4
Revises: t8b9c0d1e2f3
"""
from alembic import op
import sqlalchemy as sa

revision = "u9c0d1e2f3a4"
down_revision = "t8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "policy_change_draft",
        "suggestion_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.create_index(
        "policy_change_draft_status_created_idx",
        "policy_change_draft",
        ["status", "created_at"],
    )


def downgrade():
    # 回退前先清掉无法回填的通用草稿（suggestion_id IS NULL 的行在
    # NOT NULL 约束下无法存在），否则 alter 会直接失败。
    op.execute("DELETE FROM policy_change_draft WHERE suggestion_id IS NULL")
    op.drop_index(
        "policy_change_draft_status_created_idx",
        table_name="policy_change_draft",
    )
    op.alter_column(
        "policy_change_draft",
        "suggestion_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
```

- [x] **Step 5: 应用迁移并核对**

```bash
cd api && alembic upgrade head
cd api && python -c "
from app.http import asgi_app  # noqa
from internal.extension.database_extension import db
from sqlalchemy import text
with db.engine.connect() as c:
    r = c.execute(text(\"SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name='policy_change_draft' AND column_name='suggestion_id'\")).fetchall()
    print('COL', r)
    i = c.execute(text(\"SELECT indexname FROM pg_indexes WHERE tablename='policy_change_draft'\")).fetchall()
    print('IDX', i)
    print('ALEMBIC', c.execute(text('SELECT version_num FROM alembic_version')).fetchall())
"
```

预期：`suggestion_id` 的 `is_nullable` = `YES`；存在 `policy_change_draft_status_created_idx`；alembic = `u9c0d1e2f3a4`。

- [x] **Step 6: 运行模型测试，确认通过**

```bash
cd api && python -m pytest test/internal/model/test_policy_change_draft_generalization.py test/internal/service/test_routing_policy_change_service.py --no-cov -p no:cacheprovider -q
```

预期：PASS（含路由既有 17 个用例，证明泛化未破坏原有行为）。

- [x] **Step 7: 写失败测试（通用草稿服务）**

创建 `api/test/internal/service/test_admin_change_draft_service.py`：

```python
"""通用 admin 变更草稿服务测试（设计 §5.2）。

本服务是 supervised 档的载体：板块工具产出草稿 → 人工点「应用」才落库。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.sql import operators

from internal.service.admin_change_draft_service import (
    AdminChangeDraftService,
    DraftStatus,
)


class _QueryStub:
    """会按相等 / IN 条件真实过滤行的 query 替身。

    为什么不用空壳替身：草稿的「只能应用 pending」「只能回滚 applied」是
    **状态机安全边界**；若替身忽略 filter，测试会在"能重复应用"的实现下
    依然通过。
    """

    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *criteria, **kw):
        for crit in criteria:
            self._rows = [r for r in self._rows if _matches(r, crit)]
        return self

    def filter_by(self, **kw):
        self._rows = [
            r for r in self._rows if all(getattr(r, k, None) == v for k, v in kw.items())
        ]
        return self

    def order_by(self, *a, **kw):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


def _matches(row, crit) -> bool:
    left = getattr(crit, "left", None)
    key = getattr(left, "key", None)
    if key is None:
        return True
    op = getattr(crit, "operator", None)
    right = crit.right
    if op is operators.eq:
        return getattr(row, key, None) == getattr(right, "value", right)
    if op is operators.in_op:
        values = getattr(right, "value", right)
        return getattr(row, key, None) in set(values)
    return True


class _SessionStub:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.added = []
        self.commits = 0

    def query(self, *a, **kw):
        return _QueryStub(self.rows)

    def add(self, obj):
        self.added.append(obj)
        if obj not in self.rows:
            self.rows.append(obj)

    def flush(self):
        for i, obj in enumerate(self.added):
            if getattr(obj, "id", None) is None:
                obj.id = uuid4()

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _service(rows=None):
    session = _SessionStub(rows)
    db = SimpleNamespace(session=session)
    return AdminChangeDraftService(db=db), session


def _draft(status="pending", policy_type="builtin_tool", **kw):
    return SimpleNamespace(
        id=uuid4(),
        suggestion_id=None,
        policy_type=policy_type,
        target_id=kw.get("target_id", "tool-1"),
        before_config=kw.get("before_config", {}),
        after_config=kw.get("after_config", {}),
        diff=kw.get("diff", {}),
        impact=kw.get("impact", {}),
        status=status,
        applied_by=None,
        applied_at=None,
        rolled_back_at=None,
        rollback_reason="",
    )


class TestAdminChangeDraftService:
    def test_create_draft_persists_board_and_payload(self):
        svc, session = _service()
        draft = svc.create_draft(
            policy_type="builtin_tool",
            target_id="tool-1",
            before_config={"enabled": True},
            after_config={"enabled": False},
            diff={"changes": [{"field": "enabled", "before": True, "after": False}]},
            impact={"scope": "builtin_tool"},
            created_by=uuid4(),
            agent_id=uuid4(),
        )
        assert draft.policy_type == "builtin_tool"
        assert draft.status == DraftStatus.PENDING.value
        assert session.commits == 1

    def test_create_draft_records_agent_id_in_impact(self):
        """agent_id 必须留在草稿里，否则「哪个 Agent 提的建议」无法追溯。

        policy_change_draft 无 agent_id 列，因此写入 impact（JSONB）而非改表
        ——避免为单一用途扩列，且 impact 本就是"变更影响面"的载体。
        """
        agent_id = uuid4()
        svc, _ = _service()
        draft = svc.create_draft(
            policy_type="builtin_tool",
            target_id="tool-1",
            before_config={},
            after_config={},
            diff={},
            impact={},
            created_by=uuid4(),
            agent_id=agent_id,
        )
        assert draft.impact.get("agent_id") == str(agent_id)

    def test_apply_rejects_non_pending_draft(self):
        """已应用/已回滚的草稿不能重复应用（状态机边界）。"""
        draft = _draft(status="applied")
        svc, _ = _service([draft])
        with pytest.raises(ValueError, match="仅 pending 状态可应用"):
            svc.apply_draft(draft_id=draft.id, applied_by=uuid4())

    def test_apply_marks_applied_with_operator(self):
        draft = _draft(status="pending")
        svc, session = _service([draft])
        operator = uuid4()
        svc.apply_draft(draft_id=draft.id, applied_by=operator)
        assert draft.status == DraftStatus.APPLIED.value
        assert draft.applied_by == operator
        assert draft.applied_at is not None

    def test_rollback_rejects_non_applied_draft(self):
        draft = _draft(status="pending")
        svc, _ = _service([draft])
        with pytest.raises(ValueError, match="仅 applied 状态可回滚"):
            svc.rollback_draft(draft_id=draft.id, rolled_back_by=uuid4(), reason="x")

    def test_rollback_marks_rolled_back_with_reason(self):
        draft = _draft(status="applied")
        svc, _ = _service([draft])
        svc.rollback_draft(draft_id=draft.id, rolled_back_by=uuid4(), reason="误操作")
        assert draft.status == DraftStatus.ROLLED_BACK.value
        assert draft.rollback_reason == "误操作"
        assert draft.rolled_back_at is not None

    def test_list_pending_filters_by_status_and_board(self):
        d1 = _draft(status="pending", policy_type="builtin_tool")
        d2 = _draft(status="applied", policy_type="builtin_tool")
        d3 = _draft(status="pending", policy_type="prompt_template")
        svc, _ = _service([d1, d2, d3])
        rows = svc.list_drafts(status="pending", policy_type="builtin_tool")
        assert rows == [d1]

    def test_list_pending_without_board_filter_returns_all_boards(self):
        d1 = _draft(status="pending", policy_type="builtin_tool")
        d2 = _draft(status="pending", policy_type="prompt_template")
        svc, _ = _service([d1, d2])
        rows = svc.list_drafts(status="pending")
        assert set(r.policy_type for r in rows) == {"builtin_tool", "prompt_template"}
```

- [x] **Step 8: 运行测试，确认失败**

```bash
cd api && python -m pytest test/internal/service/test_admin_change_draft_service.py --no-cov -p no:cacheprovider -q
```

预期：FAIL（`ModuleNotFoundError`）。

- [x] **Step 9: 实现服务**

创建 `api/internal/service/admin_change_draft_service.py`：

```python
"""通用 admin 变更草稿服务（设计 §5.2）。

定位：``supervised`` 档自动化级别的载体——板块工具产出草稿（before/after/
diff/impact），管理员在后台点「应用」才真正落库，并提供回滚。

与 ``RoutingPolicyChangeService`` 的关系：后者是**路由板块**的专用编排
（含 suggestion 状态联动与特性开关写入），本服务是**通用台账**（只管草稿
本身的状态机）。路由板继续用自己的服务，其它板块用本服务，二者共用同一张
``policy_change_draft`` 表——避免 admin 侧并存两套草稿表。
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID

from internal.exception import NotFoundException
from internal.model.routing_quality import PolicyChangeDraftModel
from pkg.sqlalchemy import SQLAlchemy


class DraftStatus(str, Enum):
    """草稿状态机（与路由既有取值保持一致）。"""

    PENDING = "pending"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AdminChangeDraftService:
    """通用 admin 变更草稿的创建 / 列出 / 应用 / 回滚。"""

    def __init__(self, db: SQLAlchemy):
        self.db = db

    def create_draft(
        self,
        *,
        policy_type: str,
        target_id: str,
        before_config: dict,
        after_config: dict,
        diff: dict,
        impact: dict,
        created_by: UUID | None = None,
        agent_id: UUID | None = None,
    ) -> PolicyChangeDraftModel:
        """创建一个待应用的变更草稿。

        Args:
            policy_type: **板块标识**（如 ``builtin_tool``）；路由板沿用
                ``model_routing`` / ``tool_policy`` / ``agent_policy``。
            agent_id: 提议该变更的 Agent；写入 ``impact``（本表无 agent_id 列，
                不为单一用途扩列，且 impact 本就是"变更影响面"的载体）。

        Returns:
            已落库的草稿（status=pending）。
        """
        merged_impact = dict(impact or {})
        if agent_id is not None:
            merged_impact["agent_id"] = str(agent_id)
        if created_by is not None:
            merged_impact.setdefault("created_by", str(created_by))

        draft = PolicyChangeDraftModel(
            suggestion_id=None,
            policy_type=str(policy_type),
            target_id=str(target_id or ""),
            before_config=before_config or {},
            after_config=after_config or {},
            diff=diff or {},
            impact=merged_impact,
            status=DraftStatus.PENDING.value,
            rollback_reason="",
        )
        with self.db.auto_commit():
            self.db.session.add(draft)
        return draft

    def list_drafts(
        self,
        *,
        status: str = "",
        policy_type: str = "",
    ) -> list[PolicyChangeDraftModel]:
        """按状态与板块列出草稿（板块为空表示全部板块）。"""
        query = self.db.session.query(PolicyChangeDraftModel)
        if status:
            query = query.filter(PolicyChangeDraftModel.status == status)
        if policy_type:
            query = query.filter(PolicyChangeDraftModel.policy_type == policy_type)
        return query.order_by(PolicyChangeDraftModel.created_at.desc()).all()

    def get_draft(self, draft_id: UUID) -> PolicyChangeDraftModel:
        draft = (
            self.db.session.query(PolicyChangeDraftModel)
            .filter(PolicyChangeDraftModel.id == draft_id)
            .first()
        )
        if draft is None:
            raise NotFoundException("变更草稿不存在")
        return draft

    def apply_draft(self, *, draft_id: UUID, applied_by: UUID) -> PolicyChangeDraftModel:
        """把 pending 草稿标记为 applied。

        注意：本方法**只改变台账状态**，不执行板块动作——动作由调用方
        （板块工具/路由）在此之后执行，保证"先记账再执行"的审计顺序。

        Raises:
            ValueError: 草稿不是 pending。
        """
        draft = self.get_draft(draft_id)
        if draft.status != DraftStatus.PENDING.value:
            raise ValueError(f"仅 pending 状态可应用，当前为 {draft.status}")
        draft.status = DraftStatus.APPLIED.value
        draft.applied_by = applied_by
        draft.applied_at = _utcnow_naive()
        with self.db.auto_commit():
            self.db.session.add(draft)
        return draft

    def rollback_draft(
        self,
        *,
        draft_id: UUID,
        rolled_back_by: UUID,
        reason: str = "",
    ) -> PolicyChangeDraftModel:
        """把 applied 草稿标记为 rolled_back。

        Raises:
            ValueError: 草稿不是 applied。
        """
        draft = self.get_draft(draft_id)
        if draft.status != DraftStatus.APPLIED.value:
            raise ValueError(f"仅 applied 状态可回滚，当前为 {draft.status}")
        draft.status = DraftStatus.ROLLED_BACK.value
        draft.rolled_back_at = _utcnow_naive()
        draft.rollback_reason = reason or ""
        with self.db.auto_commit():
            self.db.session.add(draft)
        return draft
```

- [x] **Step 10: 运行测试，确认通过**

```bash
cd api && python -m pytest test/internal/service/test_admin_change_draft_service.py --no-cov -p no:cacheprovider -q
```

预期：PASS（8 个用例）。

- [x] **Step 11: 反向验证**

临时删掉 `apply_draft` 中的状态检查：

```python
        if draft.status != DraftStatus.PENDING.value:
            raise ValueError(...)
```

重跑：

```bash
cd api && python -m pytest test/internal/service/test_admin_change_draft_service.py --no-cov -p no:cacheprovider -q
```

预期：**必须 FAIL**（`test_apply_rejects_non_pending_draft`）。同样对 `rollback_draft` 做一次。恢复实现。

- [x] **Step 12: 提交**

```bash
cd api && git add internal/model/routing_quality.py internal/migration/versions/u9c0d1e2f3a4_generalize_policy_change_draft.py internal/service/admin_change_draft_service.py test/internal/model/test_policy_change_draft_generalization.py test/internal/service/test_admin_change_draft_service.py
git commit -m "feat(admin-agent): generalize policy_change_draft into a shared admin change draft

按设计 §5.2 把 policy_change_draft 提升为**通用 admin 变更草稿**，承载
supervised 档的「Agent 提议 → 人工批准」：

- suggestion_id 由 NOT NULL 改为可空（通用草稿不来自路由建议），
  迁移 down 时先清理无法回填的通用草稿再收紧约束；
- policy_type 语义扩展为板块标识，路由三个既有取值保持兼容；
- 新增 (status, created_at) 索引支撑跨板块列待应用草稿。

新增 AdminChangeDraftService 作为通用台账（创建/列出/应用/回滚 + 状态机
守卫），与 RoutingPolicyChangeService（路由专用编排）共用同一张表，
避免 admin 侧并存两套草稿表。agent_id 写入 impact JSONB 以支持追溯。"
```

---

## Task 5: 回收站 `admin_agent` 来源扩展

**Files:**
- Modify: `api/internal/service/recycle_bin_service.py`（常量 / `delete_resource` / `_attach_deleted_by_names` / `_owner_account_context` / `list_items` / `restore_item`）
- Create: `api/internal/migration/versions/<new_rev>_extend_recycle_bin_admin_agent.py`
- Test: `api/test/internal/service/test_recycle_bin_admin_agent.py`（新建）

**背景（实测）**：既有 `deleted_by_type="agent"` 只允许 7 类用户可见资源，且固定留存 7 天。admin 板块资源（`app` / `workflow` / `skill` / `mcp` / `api_tool` / `system_prompt` / `upload_file`）以该来源入站会**直接抛 `ValidateErrorException`**。因此需要独立的 `admin_agent` 来源。

- [x] **Step 1: 写失败测试**

创建 `api/test/internal/service/test_recycle_bin_admin_agent.py`：

```python
"""回收站 admin_agent 来源测试（设计 §7.1）。

要覆盖的组合是「admin 专属资源 + Agent 来源」——该组合在当前代码下会抛
ValidateErrorException，是设计文档明确要求补测的缺口。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ValidateErrorException
from internal.service.recycle_bin_service import RecycleBinService


def _service(monkeypatch, snapshot=None):
    """构造只测校验逻辑的服务实例：替换掉快照/物理删除/提交三处 I/O。"""
    svc = RecycleBinService()
    monkeypatch.setattr(
        "internal.service.recycle_bin_service.snapshot_resource",
        lambda resource_type, resource_id, resource_key: (
            {"main": {"id": str(resource_id)}} if snapshot is None else snapshot
        ),
    )
    monkeypatch.setattr(
        "internal.service.recycle_bin_service.physical_delete_resource",
        lambda *a, **kw: None,
    )
    added = []
    session = SimpleNamespace(
        add=lambda obj: added.append(obj),
        flush=lambda: None,
        commit=lambda: None,
    )
    monkeypatch.setattr(
        "internal.service.recycle_bin_service.db",
        SimpleNamespace(session=session),
    )
    return svc, added


class TestAdminAgentSource:
    def test_admin_only_resource_can_be_deleted_by_admin_agent(self, monkeypatch):
        """核心缺口：admin 专属资源 + admin_agent 来源必须可入站。

        历史行为：以 deleted_by_type='agent' 传 admin 专属资源会抛
        ValidateErrorException，导致 Agent 代删系统资源在运行时不可达。
        """
        svc, added = _service(monkeypatch)
        agent_id = uuid4()
        ok = svc.delete_resource(
            resource_type="builtin_tool",
            resource_id=uuid4(),
            deleted_by=uuid4(),
            deleted_by_type="admin_agent",
            agent_id=agent_id,
        )
        assert ok is True
        assert len(added) == 1
        item = added[0]
        assert item.deleted_by_type == "admin_agent"
        assert item.snapshot.get("_agent_id") == str(agent_id)

    def test_admin_agent_retention_defaults_to_30_days(self, monkeypatch):
        """admin_agent 来源留存默认 30 天（不是用户侧 agent 的 7 天）。"""
        svc, added = _service(monkeypatch)
        svc.delete_resource(
            resource_type="workflow",
            deleted_by=uuid4(),
            resource_id=uuid4(),
            deleted_by_type="admin_agent",
        )
        assert added[0].retention_days == 30

    def test_admin_agent_retention_respects_choices(self, monkeypatch):
        svc, added = _service(monkeypatch)
        svc.delete_resource(
            resource_type="workflow",
            resource_id=uuid4(),
            deleted_by=uuid4(),
            deleted_by_type="admin_agent",
            retention_days=90,
        )
        assert added[0].retention_days == 90

    def test_user_visible_resource_can_still_use_agent_source(self, monkeypatch):
        """既有 agent（用户侧）语义不受影响。"""
        svc, added = _service(monkeypatch)
        svc.delete_resource(
            resource_type="os_file",
            resource_id=uuid4(),
            deleted_by=uuid4(),
            deleted_by_type="agent",
            agent_id=uuid4(),
        )
        assert added[0].deleted_by_type == "agent"
        assert added[0].retention_days == 7

    def test_admin_agent_source_rejects_user_invisible_typo(self, monkeypatch):
        """不存在的资源类型仍被拒绝（守卫：新分支没有绕过白名单）。"""
        svc, _ = _service(monkeypatch)
        with pytest.raises(ValidateErrorException):
            svc.delete_resource(
                resource_type="not_a_resource",
                resource_id=uuid4(),
                deleted_by_type="admin_agent",
            )

    def test_unknown_source_still_normalizes_to_admin(self, monkeypatch):
        """既有语义：未知来源静默归一为 admin（不破坏兼容）。"""
        svc, added = _service(monkeypatch)
        svc.delete_resource(
            resource_type="workflow",
            resource_id=uuid4(),
            deleted_by=uuid4(),
            deleted_by_type="who_knows",
        )
        assert added[0].deleted_by_type == "admin"


class TestAdminAgentListingFilter:
    def test_admin_agent_is_included_when_listing_admin_sources(self, monkeypatch):
        """admin 回收站列表需能覆盖 admin_agent 条目。

        list_items 用 `==` 精确匹配 deleted_by_type；若列表仍只传 'admin'，
        Agent 代删的系统资源在后台回收站里**看不见**，用户将无法恢复。
        这里编译真实的 filter 表达式断言 SQL 文本同时含 admin 与 admin_agent。
        """
        import internal.service.recycle_bin_service as mod
        from internal.service.recycle_bin_service import RecycleBinService

        captured = {}

        class _Q:
            def filter(self, crit):
                captured.setdefault("crits", []).append(crit)
                return self

            def count(self):
                return 0

            def order_by(self, *a):
                return self

            def offset(self, *a):
                return self

            def limit(self, *a):
                return self

            def all(self):
                return []

        class _S:
            def query(self, *a, **kw):
                return _Q()

        monkeypatch.setattr(mod, "db", SimpleNamespace(session=_S()))
        RecycleBinService().list_items(deleted_by_type="admin")

        compiled = " ".join(
            str(c.compile(compile_kwargs={"literal_binds": True}))
            for c in captured.get("crits", [])
        )
        assert "admin_agent" in compiled, (
            "admin 来源的列表查询必须同时覆盖 admin_agent，否则 Agent 代删条目在后台不可见"
        )

- [x] **Step 2: 运行测试，确认失败**

```bash
cd api && python -m pytest test/internal/service/test_recycle_bin_admin_agent.py --no-cov -p no:cacheprovider -q
```

预期：FAIL（`admin_agent` 来源被校验抛错 / 归一为 `admin` / 列表过滤不含 `admin_agent`）。

- [x] **Step 3: 修改常量与 `delete_resource`**

`api/internal/service/recycle_bin_service.py`。

在 `USER_VISIBLE_RESOURCE_TYPES` 之后新增常量：

```python
    # admin 专属资源类型（由 RESOURCE_TYPES 派生，勿手工维护）。
    # admin Agent 代删这些资源时必须用 admin_agent 来源——既有 "agent" 来源
    # 被硬约束为仅 7 类用户可见资源（见 delete_resource 的校验），
    # 用于 admin 板块资源会直接抛 ValidateErrorException。
    ADMIN_ONLY_RESOURCE_TYPES = tuple(
        rt for rt in RESOURCE_TYPES if rt not in USER_VISIBLE_RESOURCE_TYPES
    )
    # admin Agent 代删的默认留存天数：比用户侧 agent（7 天）长，
    # 与 admin 手动删除（30 天）一致。
    ADMIN_AGENT_RETENTION_DAYS = 30
```

> ⚠️ 该常量原先在**模块末尾**通过 `RecycleBinService.ADMIN_ONLY_RESOURCE_TYPES = ...` 后挂派生。本步把它移进类体（更直观），**并删除模块末尾那段后挂代码**，避免两处定义。模块末尾那段已被实测确认全仓零调用点，删除是安全的。

`delete_resource` 的来源校验与留存逻辑改为：

```python
        if resource_type not in self.RESOURCE_TYPES:
            raise ValidateErrorException(f"不支持的资源类型: {resource_type}")
        deleted_by_type = (deleted_by_type or "admin").strip().lower()
        if deleted_by_type not in ("admin", "user", "agent", "admin_agent"):
            deleted_by_type = "admin"
        if (
            deleted_by_type in ("user", "agent")
            and resource_type not in self.USER_VISIBLE_RESOURCE_TYPES
        ):
            raise ValidateErrorException(
                f"资源类型 {resource_type} 仅支持管理员删除，不能进入用户回收站"
            )
        if deleted_by_type == "admin_agent":
            # admin Agent 代删：留存按 admin 口径（可配），默认 30 天。
            # 与用户侧 agent 的固定 7 天区分——admin 板块资源更需要可追溯期。
            retention_days = int(retention_days or self.ADMIN_AGENT_RETENTION_DAYS)
            if retention_days not in self.RETENTION_CHOICES:
                retention_days = self.ADMIN_AGENT_RETENTION_DAYS
        elif deleted_by_type == "agent":
            retention_days = self.AGENT_RETENTION_DAYS
        else:
            retention_days = int(retention_days or self.DEFAULT_RETENTION_DAYS)
            if retention_days not in self.RETENTION_CHOICES:
                retention_days = self.DEFAULT_RETENTION_DAYS

        snapshot = snapshot_resource(resource_type, resource_id, resource_key)
        if snapshot is None:
            return False
        if deleted_by_type in ("agent", "admin_agent") and agent_id is not None:
            snapshot["_agent_id"] = str(agent_id)
```

同时更新方法 docstring 的 `deleted_by_type` 说明，补一行：

```python
                - ``admin_agent``：管理端 Agent 代删（设计 §7.1）。
                  admin 专属资源（app/workflow/skill/mcp/api_tool/system_prompt/
                  upload_file）只能走该来源；留存默认 30 天。
```

- [x] **Step 4: 修改列表过滤（admin 来源需含 admin_agent）**

`list_items` 与 `overview` 中：

```python
        if deleted_by_type:
            if deleted_by_type == "admin":
                # admin 回收站视图需同时覆盖管理员手动删除与 Agent 代删，
                # 否则 Agent 代删的系统资源在后台回收站里看不见、无法恢复。
                query = query.filter(
                    RecycleBin.deleted_by_type.in_(("admin", "admin_agent"))
                )
            else:
                query = query.filter(RecycleBin.deleted_by_type == deleted_by_type)
```

`overview` 里除主查询的同样改动外，`pending_count` 的那段（L238-241）用同样写法。

- [x] **Step 5: 修改名称解析与归属账号**

`_attach_deleted_by_names`：`admin_agent` 的 `deleted_by` 记的是**管理员 ID**（人类责任人），因此走 admin 分支：

```python
        admin_ids = {
            str(item.deleted_by)
            for item in items
            if item.deleted_by_type in ("admin", "admin_agent")
            and item.deleted_by
            and _valid_uuid(str(item.deleted_by))
        }
```

与结尾分支：

```python
            if item.deleted_by_type in ("admin", "admin_agent"):
                item.deleted_by_name = admin_names.get(str(item.deleted_by))
            elif item.deleted_by_type in ("user", "agent"):
                item.deleted_by_name = user_names.get(str(item.deleted_by))
            else:
                item.deleted_by_name = None
```

`_owner_account_context`：`admin_agent` 的 `deleted_by` 是管理员 ID，**不能当账号用**：

```python
        if item.deleted_by_type not in ("user", "agent"):
            return None
        return str(item.deleted_by) if item.deleted_by else None
```

> 本方法**无需改动**——`admin_agent` 已被 `not in ("user", "agent")` 覆盖为返回 `None`。请在实现时**确认这一点并保留原样**，不要顺手加 `admin_agent`（那会让恢复去解析管理员 ID 对应的"账号"，是错误的设备归属）。

`_check_user_owned`：同样无需改动（`admin_agent` 会被 `not in ("user","agent")` 拒绝），保持原样。

- [x] **Step 6: 写迁移**

创建 `api/internal/migration/versions/v0d1e2f3a4b5_extend_recycle_bin_admin_agent.py`（`down_revision = "u9c0d1e2f3a4"`）：

```python
"""extend recycle_bin to support admin_agent deletion source

设计依据：docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md §7.1。

背景：既有 deleted_by_type='agent' 被硬约束为仅 7 类用户可见资源
（USER_VISIBLE_RESOURCE_TYPES），admin 专属资源（app/workflow/skill/mcp/
api_tool/system_prompt/upload_file）以该来源入站会抛 ValidateErrorException。
新增 'admin_agent' 来源表达"管理端 Agent 代删"，与 'agent'（用户侧）区分。

本迁移只做两件与 DB 相关的事：
1. 为 deleted_by_type 建索引（跨来源查询变多）；
2. 兜底修正历史误标——把「admin 专属资源 + agent 来源」的行归位为 admin_agent
   （这类行在当前代码下本就无法产生，属防御性清理，预期影响 0 行）。
无列变更（deleted_by_type 已是 VARCHAR(16)，长度足够）。

Revision ID: v0d1e2f3a4b5
Revises: u9c0d1e2f3a4
"""
from alembic import op
import sqlalchemy as sa

revision = "v0d1e2f3a4b5"
down_revision = "u9c0d1e2f3a4"
branch_labels = None
depends_on = None

# 与 RecycleBinService.USER_VISIBLE_RESOURCE_TYPES 同源（此处硬编码是刻意的：
# 迁移必须固化"当时的事实"，不能随代码常量漂移）。
_USER_VISIBLE = (
    "knowledge_base", "knowledge_document", "os_file", "schedule_task",
    "external_data_source", "conversation", "memory",
)


def upgrade():
    op.create_index(
        "recycle_bin_deleted_by_type_idx2", "recycle_bin", ["deleted_by_type"]
    )
    visible = ", ".join(f"'{t}'" for t in _USER_VISIBLE)
    op.execute(
        "UPDATE recycle_bin "
        "SET deleted_by_type = 'admin_agent' "
        f"WHERE deleted_by_type = 'agent' AND resource_type NOT IN ({visible})"
    )


def downgrade():
    # 归位回 agent 会让这些行重新落回"用户侧来源 + admin 专属资源"的非法组合，
    # 因此降级时一并改回 admin（保守且不产生非法状态）。
    op.execute(
        "UPDATE recycle_bin SET deleted_by_type = 'admin' "
        "WHERE deleted_by_type = 'admin_agent'"
    )
    op.drop_index("recycle_bin_deleted_by_type_idx2", table_name="recycle_bin")
```

> 注意：既有索引名是 `recycle_bin_deleted_by_type_idx`（由迁移 `b6c7d8e9f0a1` 创建）。本迁移新建的是 `..._idx2`，避免重名。

- [x] **Step 7: 应用迁移并核对**

```bash
cd api && alembic upgrade head
cd api && python -c "
from app.http import asgi_app  # noqa
from internal.extension.database_extension import db
from sqlalchemy import text
with db.engine.connect() as c:
    print('IDX', c.execute(text(\"SELECT indexname FROM pg_indexes WHERE tablename='recycle_bin'\")).fetchall())
    print('COUNT admin_agent', c.execute(text(\"SELECT count(*) FROM recycle_bin WHERE deleted_by_type='admin_agent'\")).scalar())
    print('ALEMBIC', c.execute(text('SELECT version_num FROM alembic_version')).fetchall())
"
```

预期：出现 `recycle_bin_deleted_by_type_idx2`；alembic = `v0d1e2f3a4b5`。

- [x] **Step 8: 运行测试，确认通过**

```bash
cd api && python -m pytest test/internal/service/test_recycle_bin_admin_agent.py test/internal/service/test_recycle_bin_service.py test/internal/service/test_recycle_bin_handlers.py --no-cov -p no:cacheprovider -q
```

预期：PASS。

- [x] **Step 9: 反向验证**

临时把 `delete_resource` 中 `admin_agent` 分支的 `retention_days` 改为 `self.AGENT_RETENTION_DAYS`（7 天），重跑：

```bash
cd api && python -m pytest test/internal/service/test_recycle_bin_admin_agent.py --no-cov -p no:cacheprovider -q
```

预期：**必须 FAIL**（`test_admin_agent_retention_defaults_to_30_days`）。恢复。

- [x] **Step 10: 提交**

```bash
cd api && git add internal/service/recycle_bin_service.py internal/migration/versions/v0d1e2f3a4b5_extend_recycle_bin_admin_agent.py test/internal/service/test_recycle_bin_admin_agent.py
git commit -m "feat(recycle): add admin_agent deletion source for admin-only resources

既有 deleted_by_type='agent' 被硬约束为仅 7 类用户可见资源，admin 专属
资源（app/workflow/skill/mcp/api_tool/system_prompt/upload_file）以该来源
入站直接抛 ValidateErrorException——即设计 §7.1 记录的「Agent 代删系统资源
在运行时不可达」。

新增 'admin_agent' 来源：
- 放行 admin 专属资源；留存按 admin 口径（默认 30 天、可配），区别于用户侧
  agent 的固定 7 天；
- _agent_id 写入快照，支持追溯「哪个 Agent 删的」；
- admin 回收站列表/概览改为 in_(('admin','admin_agent'))，否则 Agent 代删
  条目在后台不可见、无法恢复；
- deleted_by 记人类责任人（管理员 ID），名称解析走 admin 分支；
  _owner_account_context / _check_user_owned 保持原样（admin_agent 必须
  不被当作账号或用户端归属）。

ADMIN_ONLY_RESOURCE_TYPES 由模块末尾后挂改为类体内派生（原定义全仓零调用点）。
迁移补 deleted_by_type 索引并防御性归位历史误标行（预期 0 行）。"
```

---

## Task 6: `builtin_tool` 板块写路径补齐

**背景（实测）**：`builtin_tool.enabled` 的**读侧已齐**（`BuiltinProviderManager._load_from_db`、`BuiltinToolService._get_builtin_tools_from_db`、`ResourceVectorIndexService` 都尊重 `enabled=False`），但**写侧完全缺失**——全仓没有任何写 `builtin_tool.enabled` / `source` 的代码，`_builtin_tool_update` 的 `allowed_fields` 也不含 `enabled`。而 `rbac.py` 里 `builtin_tool:update` 的说明恰恰是"启停内置工具"。授权了却无路径可走。

同理 `source="custom"` 的双源保护在 builtin 域是**失效的**：没有任何代码把 `source` 置为 `custom`（对照 prompt 域：`PromptSyncService.update_prompt` 明确 `source = "custom"`）。后果是管理员 PATCH 改了 `task_keywords`，该行 `source` 仍是 `catalog`，**下次进程重启 `sync_yaml_to_db()` 会用 YAML 值无条件覆盖回去**，编辑静默丢失。

**Files:**
- Modify: `api/internal/service/builtin_tool_service.py`
- Modify: `api/app/http/admin_routes_8.py:92-139`
- Test: `api/test/internal/service/test_builtin_tool_write_paths.py`（新建）

- [x] **Step 1: 写失败测试**

创建 `api/test/internal/service/test_builtin_tool_write_paths.py`：

```python
"""builtin_tool 写路径测试（P1b 的板块样板前置）。

两条不变式：
1. 启停内置工具必须有写路径（此前缺失，而权限点已存在且描述就是"启停"）；
2. admin 编辑后必须置 source='custom'，否则下次启动 YAML 同步会覆盖掉编辑。

测试通过真实构造 `BuiltinToolService(builtin_provider_manager=..., 
builtin_category_manager=...)` 得到实例，只 monkeypatch 模块内 `db`
（与 `_get_builtin_tools_from_db` 内部局部 import `db` 的方式一致），
不重写被测逻辑。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest


class _QueryStub:
    def __init__(self, row):
        self._row = row

    def filter_by(self, **kw):
        return self

    def filter(self, *a, **kw):
        return self

    def first(self):
        return self._row


class _SessionStub:
    def __init__(self, row):
        self._row = row
        self.commits = 0

    def query(self, *a, **kw):
        return _QueryStub(self._row)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass


class _AutoCommit:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._session.commit()
        return False


def _tool(enabled=True, source="catalog"):
    return SimpleNamespace(
        id=uuid4(), enabled=enabled, source=source, name="host_os_tool"
    )


def _service(monkeypatch, tool):
    """真实构造 BuiltinToolService，仅替换其内部使用的 db。"""
    import internal.service.builtin_tool_service as mod
    from internal.service.builtin_tool_service import BuiltinToolService

    session = _SessionStub(tool)
    monkeypatch.setattr(
        mod,
        "db",
        SimpleNamespace(session=session, auto_commit=lambda: _AutoCommit(session)),
    )
    svc = BuiltinToolService(
        builtin_provider_manager=SimpleNamespace(),
        builtin_category_manager=SimpleNamespace(),
    )
    return svc, session


class TestBuiltinToolWritePaths:
    def test_set_tool_enabled_updates_row_and_marks_custom(self, monkeypatch):
        tool = _tool(enabled=True, source="catalog")
        svc, session = _service(monkeypatch, tool)

        result = svc.set_tool_enabled(tool.id, False, set_custom_source=True)

        assert tool.enabled is False
        assert tool.source == "custom", (
            "编辑后必须置 custom，否则下次启动 YAML 同步会覆盖该行"
        )
        assert result is tool
        assert session.commits == 1

    def test_set_tool_enabled_keeps_catalog_when_not_requested(self, monkeypatch):
        tool = _tool(enabled=True, source="catalog")
        svc, _ = _service(monkeypatch, tool)

        svc.set_tool_enabled(tool.id, False, set_custom_source=False)

        assert tool.enabled is False
        assert tool.source == "catalog"

    def test_set_tool_enabled_raises_for_missing_tool(self, monkeypatch):
        from internal.exception import NotFoundException

        svc, _ = _service(monkeypatch, None)
        with pytest.raises(NotFoundException):
            svc.set_tool_enabled(uuid4(), False)
```

- [x] **Step 2: 运行测试，确认失败**

```bash
cd api && python -m pytest test/internal/service/test_builtin_tool_write_paths.py --no-cov -p no:cacheprovider -q
```

预期：FAIL（`AttributeError: set_tool_enabled`）。

- [x] **Step 3: 实现服务方法**

`api/internal/service/builtin_tool_service.py`，在 `get_builtin_tools` 之后新增：

```python
    def set_tool_enabled(
        self,
        tool_id,
        enabled: bool,
        *,
        set_custom_source: bool = True,
    ):
        """启用/停用某个内置工具（此前**没有**写路径，而权限点已存在）。

        为什么必须同时置 ``source="custom"``：
        ``BuiltinToolSyncService`` 启动时会用 YAML 无条件覆盖 ``source="catalog"``
        的行；若只改 ``enabled`` 不置 custom，管理员在后台的启停会在下次
        进程重启时被 YAML 覆写回 true（实测确认 builtin 域此前从未写过
        custom，即这层双源保护一直是失效的）。

        Args:
            set_custom_source: 由"管理员显式编辑"触发时传 True（默认）；
                若在数据迁移/回滚场景需要保持 catalog，可传 False。

        Raises:
            NotFoundException: 工具不存在。
        """
        from internal.exception import NotFoundException
        from internal.extension.database_extension import db as _db
        from internal.model.builtin_tool import BuiltinTool

        tool = _db.session.query(BuiltinTool).filter_by(id=tool_id).first()
        if tool is None:
            raise NotFoundException(f"builtin 工具 {tool_id} 不存在")
        with _db.auto_commit():
            tool.enabled = bool(enabled)
            if set_custom_source:
                tool.source = "custom"
        return tool
```

> 实现者注意：本仓库 service 有两种风格——`@inject @dataclass`（用 `self.db`）与直接 `from ... import db`。`BuiltinToolService` 是前者但只在 `_get_builtin_tools_from_db` 里**局部 import** `db`。为与该文件既有风格一致（且便于 `__new__` 构造的测试注入），此处沿用**模块内局部 import `db`** 的写法。若你改为 `self.db`，必须同步修改上面的测试（`BuiltinToolService` 需经 `db=` 参数构造）。

- [x] **Step 4: 运行测试，确认通过**

```bash
cd api && python -m pytest test/internal/service/test_builtin_tool_write_paths.py --no-cov -p no:cacheprovider -q
```

预期：PASS。

- [x] **Step 5: 让 admin 编辑端点置 custom 并放开 enabled**

`api/app/http/admin_routes_8.py` 的 `_builtin_tool_update`：

```python
        allowed_fields = {"label", "description", "task_keywords", "icon", "enabled"}
        provided_fields = set(data.keys()) & allowed_fields
        if not provided_fields:
            return {
                "_errors": {"form": ["至少提供 label/description/task_keywords/icon/enabled 中的一个字段"]}
            }
```

校验段追加：

```python
        if "enabled" in data and not isinstance(data["enabled"], bool):
            return {"_errors": {"enabled": ["enabled 必须是布尔值"]}}
```

写入段改为：

```python
        if "label" in data:
            tool.label = data["label"]
        if "description" in data:
            tool.description = data["description"]
        if "task_keywords" in data:
            tool.task_keywords = data["task_keywords"]
        if "enabled" in data:
            tool.enabled = bool(data["enabled"])
        if "icon" in data:
            provider = db.session.get(BuiltinToolProvider, tool.provider_id)
            if provider is None:
                raise NotFoundException("工具对应的 provider 不存在")
            provider.icon = data["icon"]

        # 管理员一旦编辑，即置 source="custom"：否则下次进程启动时
        # BuiltinToolSyncService 会用 YAML 值无条件覆盖这次编辑（静默丢失）。
        # 对照 prompt 域 PromptSyncService.update_prompt 的同一做法。
        tool.source = "custom"
```

- [x] **Step 6: 补测试（admin 编辑端点置 custom）**

追加到 `api/test/internal/service/test_builtin_tool_write_paths.py`：

```python
class TestAdminEditMarksCustom:
    def test_update_helper_marks_tool_custom(self, monkeypatch):
        """PATCH 编辑后必须落 source='custom'（否则重启被 YAML 覆盖）。

        直接调 `_builtin_tool_update` 的真实实现，不重写其逻辑。
        """
        from app.http import admin_routes_8

        tool = _tool(enabled=True, source="catalog")
        provider = SimpleNamespace(id=uuid4(), icon="")
        session = _SessionStub2(tool, provider)

        class _ACM:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        import contextlib

        monkeypatch.setattr(
            admin_routes_8,
            "app_session_scope",
            lambda: contextlib.nullcontext(),
            raising=False,
        )

        import internal.extension.database_extension as dbext

        monkeypatch.setattr(dbext, "db", SimpleNamespace(session=session))
        result = admin_routes_8._builtin_tool_update(tool.id, {"task_keywords": ["x"]})
        assert tool.source == "custom"
        assert tool.task_keywords == ["x"]


class _SessionStub2:
    def __init__(self, tool, provider):
        self._tool = tool
        self._provider = provider
        self.commits = 0

    def get(self, model, pk):
        name = getattr(model, "__name__", "")
        if name == "BuiltinTool":
            return self._tool
        return self._provider

    def query(self, *a, **kw):
        return _QueryStub(self._tool)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass
```

> 该用例依赖 `_builtin_tool_update` 内部 `from internal.extension.database_extension import db` 这个**函数内 import**。实现者若把该 import 提到模块顶层，需相应调整 monkeypatch 目标——以实际代码为准。

- [x] **Step 7: 运行测试**

```bash
cd api && python -m pytest test/internal/service/test_builtin_tool_write_paths.py test/app/http/test_admin_routes_8.py --no-cov -p no:cacheprovider -q
```

预期：PASS。

- [x] **Step 8: 反向验证**

临时删掉 `_builtin_tool_update` 里的 `tool.source = "custom"`，重跑 Step 7：

```bash
cd api && python -m pytest test/internal/service/test_builtin_tool_write_paths.py --no-cov -p no:cacheprovider -q
```

预期：**必须 FAIL**（`test_update_helper_marks_tool_custom`）。恢复。

- [x] **Step 9: 提交**

```bash
cd api && git add internal/service/builtin_tool_service.py app/http/admin_routes_8.py test/internal/service/test_builtin_tool_write_paths.py
git commit -m "fix(builtin-tool): add the missing enabled/source write paths

读侧早已齐备（BuiltinProviderManager / BuiltinToolService / 向量索引都尊重
enabled=False），但写侧完全缺失：全仓没有任何写 builtin_tool.enabled 或
source 的代码，而 rbac 里 builtin_tool:update 的说明正是「启停内置工具」
——授权了却无路径可走。

- BuiltinToolService.set_tool_enabled()：置 enabled + source='custom'；
- _builtin_tool_update 的 allowed_fields 放开 enabled，并在编辑后置
  source='custom'（对照 prompt 域 PromptSyncService.update_prompt）。

第二条修的是实际缺陷：builtin 域此前从未写过 source='custom'，
即双源保护一直失效——管理员 PATCH 改了 task_keywords 之后，下次进程启动
sync_yaml_to_db() 会用 YAML 值无条件覆盖，编辑静默丢失；而 task_keywords
直接决定 ToolSelectorService 的关键词快通道，该丢失有功能影响。"
```

---

## Task 7: 板块工具实现体与 `AdminAgentPrincipal` 装配

**Files:**
- Create: `api/internal/service/admin_agent_board_tools.py`
- Modify: `api/internal/service/admin_agent_service.py`（新增 `get_principal`）
- Test: `api/test/internal/service/test_admin_agent_board_tools.py`（新建）

- [x] **Step 1: 写失败测试（principal 装配）**

创建 `api/test/internal/service/test_admin_agent_board_tools.py`：

```python
"""板块工具与 principal 装配测试（设计 §4.1 运行时实时重算）。"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.service.admin_agent_service import AdminAgentService


class _QueryStub:
    def __init__(self, row):
        self._row = row

    def filter(self, *a, **kw):
        return self

    def first(self):
        return self._row


class _SessionStub:
    def __init__(self, row):
        self._row = row

    def query(self, *a, **kw):
        return _QueryStub(self._row)


def _agent(owner, granted, policy=None, enabled=True):
    return SimpleNamespace(
        id=uuid4(),
        owner_admin_user_id=owner,
        name="运维 Agent",
        granted_permissions=list(granted),
        automation_policy=policy or {},
        enabled=enabled,
    )


class TestGetPrincipal:
    def test_effective_is_intersection_of_three_sets(self):
        """运行时必须实时重算三重交集，不读静态快照。"""
        owner = uuid4()
        agent = _agent(owner, ["builtin_tool:read", "builtin_tool:update", "role:read"])
        svc = AdminAgentService(db=SimpleNamespace(session=_SessionStub(agent)))

        principal = svc.get_principal(
            agent_id=agent.id,
            admin_user_id=owner,
            admin_permissions=["builtin_tool:read", "builtin_tool:update", "model_pool:read"],
        )

        # role:read 被封禁、model_pool:read 未下放，都应被剔除
        assert principal.effective_permissions == frozenset(
            {"builtin_tool:read", "builtin_tool:update"}
        )
        assert principal.admin_user_id == owner
        assert principal.agent_id == agent.id

    def test_admin_losing_permission_shrinks_agent_immediately(self):
        """管理员失权后，即使 granted 里还有，effective 也必须立即收紧。"""
        owner = uuid4()
        agent = _agent(owner, ["builtin_tool:read", "builtin_tool:update"])
        svc = AdminAgentService(db=SimpleNamespace(session=_SessionStub(agent)))

        principal = svc.get_principal(
            agent_id=agent.id,
            admin_user_id=owner,
            admin_permissions=["builtin_tool:read"],
        )
        assert principal.effective_permissions == frozenset({"builtin_tool:read"})

    def test_automation_policy_is_parsed_to_enum(self):
        owner = uuid4()
        agent = _agent(
            owner, ["builtin_tool:update"], policy={"builtin_tool": "autonomous"}
        )
        svc = AdminAgentService(db=SimpleNamespace(session=_SessionStub(agent)))
        principal = svc.get_principal(
            agent_id=agent.id,
            admin_user_id=owner,
            admin_permissions=["builtin_tool:update"],
        )
        assert principal.automation_level_for("builtin_tool") is AutomationLevel.AUTONOMOUS
        # 未配置的板块 fail closed 到 supervised
        assert principal.automation_level_for("prompt_template") is AutomationLevel.SUPERVISED

    def test_disabled_agent_is_rejected(self):
        owner = uuid4()
        agent = _agent(owner, ["builtin_tool:read"], enabled=False)
        svc = AdminAgentService(db=SimpleNamespace(session=_SessionStub(agent)))
        with pytest.raises(PermissionError, match="已停用"):
            svc.get_principal(
                agent_id=agent.id,
                admin_user_id=owner,
                admin_permissions=["builtin_tool:read"],
            )

    def test_non_owner_is_rejected(self):
        owner = uuid4()
        agent = _agent(owner, ["builtin_tool:read"])
        svc = AdminAgentService(db=SimpleNamespace(session=_SessionStub(agent)))
        with pytest.raises(PermissionError, match="仅创建者"):
            svc.get_principal(
                agent_id=agent.id,
                admin_user_id=uuid4(),
                admin_permissions=["builtin_tool:read"],
            )

    def test_missing_agent_returns_none(self):
        svc = AdminAgentService(db=SimpleNamespace(session=_SessionStub(None)))
        assert svc.get_principal(
            agent_id=uuid4(), admin_user_id=uuid4(), admin_permissions=[]
        ) is None


class TestBoardToolPermissionGate:
    def test_action_without_permission_is_refused(self):
        """板块工具执行前必须校验 effective_permissions 含该 action 所需权限点。"""
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        principal = AdminAgentPrincipal(
            admin_user_id=uuid4(),
            agent_id=uuid4(),
            agent_name="运维 Agent",
            effective_permissions=frozenset({"builtin_tool:read"}),
        )
        executor = BoardToolExecutor()
        with pytest.raises(PermissionError, match="无权限"):
            executor.assert_allowed(principal, board="builtin_tool", action="update_enabled")

    def test_read_action_allowed_with_read_permission(self):
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        principal = AdminAgentPrincipal(
            admin_user_id=uuid4(),
            agent_id=uuid4(),
            agent_name="运维 Agent",
            effective_permissions=frozenset({"builtin_tool:read"}),
        )
        executor = BoardToolExecutor()
        executor.assert_allowed(principal, board="builtin_tool", action="list")

    def test_blocked_board_is_refused_even_with_permission(self):
        """blocked 档是应急熔断：即使有权限也不执行。"""
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        principal = AdminAgentPrincipal(
            admin_user_id=uuid4(),
            agent_id=uuid4(),
            agent_name="运维 Agent",
            effective_permissions=frozenset({"builtin_tool:update"}),
            automation_policy={"builtin_tool": AutomationLevel.BLOCKED},
        )
        executor = BoardToolExecutor()
        with pytest.raises(PermissionError, match="已熔断"):
            executor.assert_allowed(principal, board="builtin_tool", action="update_enabled")

    def test_undeclared_action_is_refused(self):
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        principal = AdminAgentPrincipal(
            admin_user_id=uuid4(),
            agent_id=uuid4(),
            agent_name="x",
            effective_permissions=frozenset({"builtin_tool:update"}),
        )
        executor = BoardToolExecutor()
        with pytest.raises(ValueError):
            executor.assert_allowed(principal, board="builtin_tool", action="nope")


class TestBuiltinToolActionValidation:
    """板块实现体的入参校验必须在触碰 DB 之前完成。"""

    def _principal(self):
        return AdminAgentPrincipal(
            admin_user_id=uuid4(),
            agent_id=uuid4(),
            agent_name="运维 Agent",
            effective_permissions=frozenset({"builtin_tool:read", "builtin_tool:update"}),
            automation_policy={"builtin_tool": AutomationLevel.AUTONOMOUS},
        )

    def test_update_enabled_requires_tool_id_and_bool(self):
        """缺 tool_id 或 enabled 非布尔时必须在调用 service 前拒绝。

        若校验后置，会先触发 set_tool_enabled 的副作用再报错。
        """
        from internal.exception import FailException
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        executor = BoardToolExecutor()
        with pytest.raises(FailException, match="tool_id"):
            executor.execute(
                self._principal(),
                board="builtin_tool",
                action="update_enabled",
                payload={},
            )
        with pytest.raises(FailException, match="tool_id"):
            executor.execute(
                self._principal(),
                board="builtin_tool",
                action="update_enabled",
                payload={"tool_id": "t1", "enabled": "yes"},
            )

    def test_update_metadata_requires_at_least_one_editable_field(self):
        from internal.exception import FailException
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        executor = BoardToolExecutor()
        with pytest.raises(FailException, match="tool_id"):
            executor.execute(
                self._principal(),
                board="builtin_tool",
                action="update_metadata",
                payload={},
            )
        with pytest.raises(FailException, match="至少需要"):
            executor.execute(
                self._principal(),
                board="builtin_tool",
                action="update_metadata",
                payload={"tool_id": "t1", "enabled": False},
            )
```

- [x] **Step 2: 运行测试，确认失败**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_board_tools.py --no-cov -p no:cacheprovider -q
```

预期：FAIL（`get_principal` 与 `admin_agent_board_tools` 均不存在）。

- [x] **Step 3: 实现 `get_principal`**

`api/internal/service/admin_agent_service.py`。新增 import 与顶部注释更新：

```python
from internal.core.admin_agent_authorization import (
    ASSIGNABLE_PERMISSIONS,
    assert_grantable,
    compute_effective_permissions,
)
from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
```

（原文件已 import `ASSIGNABLE_PERMISSIONS` / `assert_grantable` / `AutomationLevel`，补 `compute_effective_permissions` 与 `AdminAgentPrincipal`。）

在授权小节追加：

```python
    def get_principal(
        self,
        *,
        agent_id: UUID,
        admin_user_id: UUID,
        admin_permissions,
    ) -> AdminAgentPrincipal | None:
        """组装执行身份 ``AdminAgentPrincipal``（设计 §4.1 运行时层）。

        每次请求实时重算三重交集，**不依赖任何静态快照**——管理员角色调整
        后 Agent 能力立即随之收紧。

        Returns:
            principal；Agent 不存在时返回 ``None``。

        Raises:
            PermissionError: 非创建者调用，或 Agent 已停用。
        """
        agent = self.get_agent(agent_id=agent_id, admin_user_id=admin_user_id)
        if agent is None:
            return None
        if not bool(getattr(agent, "enabled", True)):
            raise PermissionError("该 Agent 已停用")

        effective = compute_effective_permissions(
            admin_permissions=admin_permissions,
            granted_permissions=list(agent.granted_permissions or []),
        )
        policy = {
            str(board): AutomationLevel(level)
            for board, level in (agent.automation_policy or {}).items()
            if _is_valid_level(level)
        }
        return AdminAgentPrincipal(
            admin_user_id=admin_user_id,
            agent_id=agent.id,
            agent_name=agent.name or "",
            effective_permissions=effective,
            automation_policy=policy,
        )
```

并在文件末尾（类外）追加辅助函数：

```python
def _is_valid_level(level) -> bool:
    """automation_policy 取值合法性判定（非法值直接丢弃 → fail closed 到 supervised）。"""
    try:
        AutomationLevel(level)
    except (ValueError, TypeError):
        return False
    return True
```

- [x] **Step 4: 实现板块工具执行器**

创建 `api/internal/service/admin_agent_board_tools.py`：

```python
"""管理端 Agent 的板块级聚合工具（设计 §7.1）。

设计要点：
- **一个板块一个工具**，内部按 ``action`` 分支。admin 有上百个端点，
  端点级工具会让工具数远超 selected_tools 上限、拉低 LLM 选择准确率；
  且"板块被授权"的语义天然对应板块级工具。
- **每 action 显式声明所需权限点**，未声明即拒绝（fail closed），
  声明表在 ``internal/core/admin_agent_boards.py``。
- 执行四步（设计 §7.1）：校验权限 → 解析自动化级别 → 调 service → 写审计。
  其中"审计"由 ``AdminAgentExecutionService`` 统一负责，本模块只做前三步的
  第 1、3 步与第 2 步的判定，避免审计逻辑散落在各板块。

service 层不感知 Agent（保持纯粹）：板块工具只是"带边界校验的薄转发"。
"""
from __future__ import annotations

import logging
from typing import Any

from internal.core.admin_agent_boards import boards as _boards
from internal.core.admin_agent_boards import resolve_action
from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.exception import FailException

logger = logging.getLogger(__name__)


class BoardToolExecutor:
    """板块动作的统一执行闸门与分发器。

    刻意**不用** ``@inject @dataclass``：它不持有状态、且需要能被测试直接
    构造（``BoardToolExecutor()``）。
    """

    def assert_allowed(
        self,
        principal: AdminAgentPrincipal,
        *,
        board: str,
        action: str,
    ):
        """执行四步中的前三步的前置校验（设计 §7.1）。

        Args:
            principal: 已算好三重交集的执行身份。

        Returns:
            已解析的 ``BoardAction``。

        Raises:
            ValueError: (board, action) 未登记（fail closed）。
            PermissionError: 权限不足，或板块处于 blocked 档。
        """
        declared = resolve_action(board, action)

        if not principal.has_permission(declared.permission_code):
            raise PermissionError(
                f"Agent 无权限执行 {board}.{action}"
                f"（需要 {declared.permission_code}）"
            )

        level = principal.automation_level_for(board)
        if level is AutomationLevel.BLOCKED:
            raise PermissionError(f"板块 {board} 已熔断（blocked），拒绝执行")

        return declared

    @staticmethod
    def requires_draft(principal: AdminAgentPrincipal, board: str) -> bool:
        """该板块的写操作是否需要走变更草稿（supervised 档）。"""
        return principal.automation_level_for(board) is AutomationLevel.SUPERVISED

    # ------------------------------------------------------------------
    # 板块动作实现
    # ------------------------------------------------------------------

    def execute(
        self,
        principal: AdminAgentPrincipal,
        *,
        board: str,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行一个板块动作（**只读或已获批准的写**）。

        写操作的分流（supervised → 草稿 / autonomous → 直接执行）由调用方
        ``AdminAgentExecutionService`` 决定；本方法只负责"权限已通过后真正干活"。

        Raises:
            FailException: 板块未实现（登记了 action 但缺实现体）。
        """
        self.assert_allowed(principal, board=board, action=action)
        handler = getattr(self, f"_do_{board}", None)
        if handler is None:
            raise FailException(f"板块 {board} 尚未实现（已登记动作但无实现体）")
        return handler(principal, action=action, payload=payload or {})

    # ------------------------------------------------------------------
    # builtin_tool（P1b 端到端样板板块）
    # ------------------------------------------------------------------

    def _do_builtin_tool(self, principal, *, action: str, payload: dict) -> dict:
        """内置工具板块的 action 分发。

        复用既有 ``BuiltinToolService``，不重写查询逻辑。
        """
        if action == "list":
            from internal.service.builtin_tool_service import BuiltinToolService

            service = self._builtin_tool_service()
            items = service.get_builtin_tools()
            return {
                "board": "builtin_tool",
                "action": "list",
                "total": len(items),
                "items": [
                    {
                        "id": item.get("id"),
                        "provider": (item.get("provider") or {}).get("name")
                        or item.get("provider_id"),
                        "name": item.get("name"),
                        "label": item.get("label"),
                        "enabled": item.get("enabled"),
                        "source": item.get("source"),
                    }
                    for item in items
                ],
            }

        if action == "update_enabled":
            tool_id = payload.get("tool_id")
            enabled = payload.get("enabled")
            if not tool_id or not isinstance(enabled, bool):
                raise FailException("update_enabled 需要 tool_id 与布尔 enabled")
            tool = self._builtin_tool_service().set_tool_enabled(
                tool_id, enabled, set_custom_source=True
            )
            return {
                "board": "builtin_tool",
                "action": "update_enabled",
                "tool_id": str(getattr(tool, "id", tool_id)),
                "enabled": bool(tool.enabled),
                "source": tool.source,
            }

        if action == "update_metadata":
            tool_id = payload.get("tool_id")
            if not tool_id:
                raise FailException("update_metadata 需要 tool_id")
            from app.http.admin_routes_8 import _builtin_tool_update

            data = {
                k: v
                for k, v in payload.items()
                if k in {"label", "description", "task_keywords"}
            }
            if not data:
                raise FailException("update_metadata 至少需要 label/description/task_keywords 之一")
            result = _builtin_tool_update(tool_id, data)
            if isinstance(result, dict) and result.get("_errors"):
                raise FailException(f"参数校验失败: {result['_errors']}")
            return {
                "board": "builtin_tool",
                "action": "update_metadata",
                "tool_id": str(tool_id),
                "result": result,
            }

        raise FailException(f"builtin_tool 未实现 action: {action}")

    @staticmethod
    def _builtin_tool_service():
        """构造 BuiltinToolService（复用 injector 单例，避免手工 new）。

        走 ``_get_service`` 而非直接实例化：``BuiltinToolService`` 依赖
        ``BuiltinProviderManager``（首次构造会加载全部 builtin provider 并
        dynamic_import），复用单例可避免每次调用都重建全量 map。
        """
        from app.http import asgi_app as a
        from internal.service.builtin_tool_service import BuiltinToolService

        return a._get_service(BuiltinToolService)


def available_boards() -> tuple[str, ...]:
    """对 LLM 暴露的板块清单（工具 schema 用）。"""
    return _boards()
```

- [x] **Step 5: 运行测试，确认通过**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_board_tools.py --no-cov -p no:cacheprovider -q
```

预期：PASS。

- [x] **Step 6: 反向验证（三处）**

逐一执行，每次确认测试失败后恢复：

1. `assert_allowed` 去掉权限检查 → `test_action_without_permission_is_refused` 必须 FAIL。
2. `assert_allowed` 去掉 blocked 判定 → `test_blocked_board_is_refused_even_with_permission` 必须 FAIL。
3. `get_principal` 改为 `effective = frozenset(agent.granted_permissions)`（不取交集）→ `test_admin_losing_permission_shrinks_agent_immediately` 必须 FAIL。

- [x] **Step 7: 提交**

```bash
cd api && git add internal/service/admin_agent_service.py internal/service/admin_agent_board_tools.py test/internal/service/test_admin_agent_board_tools.py
git commit -m "feat(admin-agent): add board tool executor and principal assembly

- AdminAgentService.get_principal()：每次请求实时重算三重交集组装
  AdminAgentPrincipal（不读静态快照），并拒绝已停用 Agent 与非创建者；
  automation_policy 非法取值直接丢弃 → 由 principal 兜底到 supervised。
- BoardToolExecutor：板块动作的统一闸门。assert_allowed 依次做
  ① (board, action) 声明解析（fail closed）② effective_permissions 校验
  ③ blocked 熔断判定；execute 按板块分发到既有 service（service 层不感知
  Agent，保持纯粹）。
- 首个实现的板块是 builtin_tool（list / update_enabled / update_metadata），
  作为 P1b 的端到端样板。"
```

---

## Task 8: 执行层服务（分流 + 审计）

**Files:**
- Create: `api/internal/service/admin_agent_execution_service.py`
- Test: `api/test/internal/service/test_admin_agent_execution_service.py`（新建）

- [x] **Step 1: 写失败测试**

创建 `api/test/internal/service/test_admin_agent_execution_service.py`：

```python
"""管理端 Agent 执行层测试（设计 §5.1 / §6.2 / §9）。

核心不变式：
1. supervised 档**不执行**，只产出变更草稿；
2. autonomous 档直接执行；
3. blocked 档拒绝（由 BoardToolExecutor 抛错）；
4. 每次执行都写 actor_type=agent 的审计，且 admin_user_id 是人类责任人。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.service.admin_agent_execution_service import (
    AdminAgentExecutionService,
    ExecutionOutcome,
)


def _principal(perms=None, policy=None, agent_id=None, admin_id=None):
    return AdminAgentPrincipal(
        admin_user_id=admin_id or uuid4(),
        agent_id=agent_id or uuid4(),
        agent_name="运维 Agent",
        effective_permissions=frozenset(perms or {"builtin_tool:read", "builtin_tool:update"}),
        automation_policy=policy or {},
    )


class _AuditRecorder:
    def __init__(self):
        self.calls = []

    def record(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(**kw)


class TestReadAction:
    def test_read_action_executes_directly(self):
        principal = _principal()
        audit = _AuditRecorder()
        svc = AdminAgentExecutionService(
            board_executor=_StubExecutor(result={"items": []}),
            draft_service=_StubDraft(),
            audit_log_service=audit,
        )
        result = svc.run(principal, board="builtin_tool", action="list", payload={})
        assert result["outcome"] == ExecutionOutcome.EXECUTED.value
        assert result["result"] == {"items": []}
        # 只读动作不产生草稿
        assert result["draft_id"] is None

    def test_read_action_is_audited_as_agent(self):
        principal = _principal()
        audit = _AuditRecorder()
        svc = AdminAgentExecutionService(
            board_executor=_StubExecutor(result={}),
            draft_service=_StubDraft(),
            audit_log_service=audit,
        )
        svc.run(principal, board="builtin_tool", action="list", payload={})
        assert len(audit.calls) == 1
        call = audit.calls[0]
        assert call["actor_type"] == "agent"
        assert call["agent_id"] == principal.agent_id
        # admin_user_id 必须是人类责任人，不是 None、不是 agent_id
        assert call["admin_user_id"] == principal.admin_user_id


class TestSupervisedDraft:
    def test_supervised_write_creates_draft_without_executing(self):
        principal = _principal(policy={"builtin_tool": AutomationLevel.SUPERVISED})
        audit = _AuditRecorder()
        executor = _StubExecutor(result={"should_not": "run"})
        draft = _StubDraft()
        svc = AdminAgentExecutionService(
            board_executor=executor, draft_service=draft, audit_log_service=audit
        )
        result = svc.run(
            principal,
            board="builtin_tool",
            action="update_enabled",
            payload={"tool_id": "t1", "enabled": False},
        )
        assert result["outcome"] == ExecutionOutcome.DRAFTED.value
        assert result["draft_id"] is not None
        # 关键：草稿档绝不能真执行
        assert executor.executed == [], "supervised 档不得调用板块实现体"
        assert draft.created, "必须产出变更草稿"

    def test_draft_carries_agent_id_for_traceability(self):
        principal = _principal(policy={"builtin_tool": AutomationLevel.SUPERVISED})
        draft = _StubDraft()
        svc = AdminAgentExecutionService(
            board_executor=_StubExecutor(),
            draft_service=draft,
            audit_log_service=_AuditRecorder(),
        )
        svc.run(
            principal,
            board="builtin_tool",
            action="update_enabled",
            payload={"tool_id": "t1", "enabled": False},
        )
        assert draft.last_kwargs["agent_id"] == principal.agent_id

    def test_unconfigured_board_defaults_to_supervised(self):
        """未配置 automation_policy 的板块 fail closed 到 supervised（不自动执行）。"""
        principal = _principal(policy={})
        executor = _StubExecutor()
        svc = AdminAgentExecutionService(
            board_executor=executor,
            draft_service=_StubDraft(),
            audit_log_service=_AuditRecorder(),
        )
        result = svc.run(
            principal,
            board="builtin_tool",
            action="update_enabled",
            payload={"tool_id": "t1", "enabled": False},
        )
        assert result["outcome"] == ExecutionOutcome.DRAFTED.value
        assert executor.executed == []


class TestAutonomous:
    def test_autonomous_write_executes_directly(self):
        principal = _principal(policy={"builtin_tool": AutomationLevel.AUTONOMOUS})
        executor = _StubExecutor(result={"enabled": False})
        draft = _StubDraft()
        svc = AdminAgentExecutionService(
            board_executor=executor, draft_service=draft, audit_log_service=_AuditRecorder()
        )
        result = svc.run(
            principal,
            board="builtin_tool",
            action="update_enabled",
            payload={"tool_id": "t1", "enabled": False},
        )
        assert result["outcome"] == ExecutionOutcome.EXECUTED.value
        assert executor.executed == [("builtin_tool", "update_enabled")]
        assert draft.created == [], "autonomous 档不产草稿"


class TestFailureAudited:
    def test_permission_failure_is_audited_and_reraised(self):
        """权限不足必须记审计（设计 §7.1 第 1 步"不足 → 拒绝并记审计"）。"""
        principal = _principal(perms={"builtin_tool:read"})
        audit = _AuditRecorder()
        svc = AdminAgentExecutionService(
            board_executor=_RealGateExecutor(),
            draft_service=_StubDraft(),
            audit_log_service=audit,
        )
        with pytest.raises(PermissionError):
            svc.run(
                principal,
                board="builtin_tool",
                action="update_enabled",
                payload={"tool_id": "t1", "enabled": False},
            )
        assert len(audit.calls) == 1
        assert audit.calls[0]["actor_type"] == "agent"
        assert "denied" in audit.calls[0]["action"]


class _StubExecutor:
    def __init__(self, result=None):
        self._result = result or {}
        self.executed = []

    def assert_allowed(self, principal, *, board, action):
        from internal.core.admin_agent_boards import resolve_action

        return resolve_action(board, action)

    def requires_draft(self, principal, board):
        return principal.automation_level_for(board) is AutomationLevel.SUPERVISED

    def execute(self, principal, *, board, action, payload):
        self.executed.append((board, action))
        return self._result


class _RealGateExecutor:
    """使用真实 BoardToolExecutor 的权限闸门（验证拒绝路径真的会抛）。"""

    def __init__(self):
        from internal.service.admin_agent_board_tools import BoardToolExecutor

        self._inner = BoardToolExecutor()

    def assert_allowed(self, principal, *, board, action):
        return self._inner.assert_allowed(principal, board=board, action=action)

    def requires_draft(self, principal, board):
        return self._inner.requires_draft(principal, board)

    def execute(self, principal, *, board, action, payload):
        raise AssertionError("权限不足时不应到达执行阶段")


class _StubDraft:
    def __init__(self):
        self.created = []
        self.last_kwargs = {}

    def create_draft(self, **kw):
        self.created.append(kw)
        self.last_kwargs = kw
        return SimpleNamespace(id=uuid4())
```

- [x] **Step 2: 运行测试，确认失败**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_execution_service.py --no-cov -p no:cacheprovider -q
```

预期：FAIL（`ModuleNotFoundError`）。

- [x] **Step 3: 实现执行层**

创建 `api/internal/service/admin_agent_execution_service.py`：

```python
"""管理端 Agent 执行层（设计 §6.1 / §7.1 执行四步 / §9 审计）。

为什么新建独立链路而不复用用户端 ``chat()``：
``AssistantAgentService._build_assistant_runtime_tools()`` 是**用户域固有
工具的装配点**，按用户身份装配 create_app / 本机文件三件套 / 电脑控制 /
浏览器 / audio / code_execution / vision / todo / 知识库检索 / skill_detail /
agent_memory 等，且是**条件装配**（逐个 try、受功能开关与运行上下文约束），
实际数量随配置动态变化。复用它只能靠黑名单排除用户域工具，而黑名单对
"随配置动态增减"的集合是不完备的——漏一个就是越权。故本链路只装配
admin 板块工具（白名单式，未登记即不装配）。

本服务承担"执行四步"的第 2 步（自动化级别分流）与第 4 步（写审计），
第 1 步（权限校验）与第 3 步（调 service）委托给 BoardToolExecutor。
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel

logger = logging.getLogger(__name__)


class ExecutionOutcome(str, Enum):
    """一次 Agent 执行的结果类别。"""

    EXECUTED = "executed"      # 已真实执行（只读动作，或 autonomous 档写动作）
    DRAFTED = "drafted"        # 未执行，已产出变更草稿等待人工批准（supervised 档）


class AdminAgentExecutionService:
    """板块动作的执行编排：分流域 + 审计域。

    依赖显式注入（构造参数），便于测试替换；生产侧由路由层组装。
    """

    def __init__(
        self,
        *,
        board_executor,
        draft_service,
        audit_log_service,
    ):
        self.board_executor = board_executor
        self.draft_service = draft_service
        self.audit_log_service = audit_log_service

    def run(
        self,
        principal: AdminAgentPrincipal,
        *,
        board: str,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行一个板块动作，按自动化级别分流并写审计。

        Returns:
            ``{"outcome": "executed"|"drafted", "result": ..., "draft_id": ...}``

        Raises:
            ValueError: (board, action) 未登记。
            PermissionError: 权限不足或板块熔断。
        """
        payload = payload or {}

        # ---- 第 1 步：权限 / 熔断校验（不足 → 拒绝并记审计）----
        try:
            declared = self.board_executor.assert_allowed(
                principal, board=board, action=action
            )
        except (PermissionError, ValueError) as exc:
            self._audit(
                principal,
                action=f"admin_agent.{board}.{action}.denied",
                resource_type=board,
                resource_id=str(payload.get("tool_id") or payload.get("target_id") or ""),
                after_data={"reason": str(exc), "payload": payload},
            )
            raise

        # ---- 第 2 步：自动化级别分流 ----
        needs_draft = declared.is_write and self.board_executor.requires_draft(
            principal, board
        )
        if needs_draft:
            draft = self.draft_service.create_draft(
                policy_type=board,
                target_id=str(payload.get("tool_id") or payload.get("target_id") or ""),
                before_config=payload.get("before_config") or {},
                after_config=payload,
                diff=payload.get("diff") or {},
                impact={"board": board, "action": action, "source": "admin_agent"},
                created_by=principal.admin_user_id,
                agent_id=principal.agent_id,
            )
            draft_id = str(getattr(draft, "id", "") or "")
            self._audit(
                principal,
                action=f"admin_agent.{board}.{action}.drafted",
                resource_type=board,
                resource_id=str(payload.get("tool_id") or ""),
                after_data={
                    "draft_id": draft_id,
                    "action": action,
                    "payload": payload,
                },
            )
            return {
                "outcome": ExecutionOutcome.DRAFTED.value,
                "result": None,
                "draft_id": draft_id,
            }

        # ---- 第 3 步：调板块实现体 ----
        result = self.board_executor.execute(
            principal, board=board, action=action, payload=payload
        )

        # ---- 第 4 步：写审计（actor_type=agent，admin_user_id 为人类责任人）----
        self._audit(
            principal,
            action=f"admin_agent.{board}.{action}",
            resource_type=board,
            resource_id=str(payload.get("tool_id") or payload.get("target_id") or ""),
            after_data={
                "action": action,
                "payload": payload,
                "result": result if isinstance(result, dict) else {"value": result},
            },
        )
        return {
            "outcome": ExecutionOutcome.EXECUTED.value,
            "result": result,
            "draft_id": None,
        }

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _audit(
        self,
        principal: AdminAgentPrincipal,
        *,
        action: str,
        resource_type: str,
        resource_id: str,
        after_data: dict,
    ) -> None:
        """写一条 actor_type=agent 的审计。

        审计失败**不阻断**主流程（与既有 `_write_audit` / `_emit_audit` 的
        容错一致），但必须记日志便于排查。
        """
        try:
            self.audit_log_service.record(
                admin_user_id=principal.admin_user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                actor_type="agent",
                agent_id=principal.agent_id,
                after_data=after_data,
                commit=True,
            )
        except Exception:
            logger.exception(
                "管理端 Agent 审计写入失败 action=%s agent_id=%s",
                action,
                principal.agent_id,
            )
```

- [x] **Step 4: 运行测试，确认通过**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_execution_service.py --no-cov -p no:cacheprovider -q
```

预期：PASS（9 个用例）。

- [x] **Step 5: 反向验证**

临时把 `needs_draft` 改为 `False`（即所有写动作都直接执行），重跑：

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_execution_service.py --no-cov -p no:cacheprovider -q
```

预期：**必须 FAIL**（`test_supervised_write_creates_draft_without_executing`、`test_unconfigured_board_defaults_to_supervised`）。恢复。

再临时把 `_audit` 的 `actor_type="agent"` 改为 `"human"`：

预期：**必须 FAIL**（`test_read_action_is_audited_as_agent`）。恢复。

- [x] **Step 6: 提交**

```bash
cd api && git add internal/service/admin_agent_execution_service.py test/internal/service/test_admin_agent_execution_service.py
git commit -m "feat(admin-agent): add execution service with automation-level routing

按设计 §7.1 的执行四步编排板块动作：
① 权限/熔断校验（委托 BoardToolExecutor；不足则拒绝**并记审计**）
② 自动化级别分流——supervised 档**不执行**、只产变更草稿（fail closed：
   未配置板块一律 supervised），autonomous 档直接执行，blocked 由第①步熔断
③ 调板块实现体（service 层不感知 Agent）
④ 写审计：actor_type=agent + agent_id + admin_user_id（人类责任人）

审计失败不阻断主流程但记日志（与既有 audit 写入的容错一致）。"
```

---

## Task 9: 执行入口路由与板块 Agent 提示词

**Files:**
- Modify: `api/app/http/admin_routes_7.py`（追加端点）
- Modify: `api/app/http/support.py:515-521`（权限映射）
- Create: `api/internal/core/prompts/admin_agent/board_agent.yaml`
- Modify: `api/internal/core/prompts/index.yaml`
- Test: `api/test/app/http/test_admin_agent_invoke_routes.py`（新建）

- [x] **Step 1: 写失败测试**

创建 `api/test/app/http/test_admin_agent_invoke_routes.py`：

```python
"""管理端 Agent 执行入口路由测试。"""
import asyncio

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_7 import register_routes

register_routes(asgi_app.quart_app)


def _admin_ctx(admin_id, permissions):
    async def _fake(permission_code=None):
        return {"id": str(admin_id), "roles": [], "permissions": list(permissions)}, None

    return _fake


class _StubExecutionService:
    """记录调用并返回固定结果（不重写被测逻辑——被测逻辑在 service 层已单测）。"""

    def __init__(self):
        self.calls = []
        self.principal_requests = []

    def run(self, principal, *, board, action, payload):
        self.calls.append(
            {"principal": principal, "board": board, "action": action, "payload": payload}
        )
        return {"outcome": "executed", "result": {"ok": True}, "draft_id": None}


class _StubAgentService:
    def __init__(self, principal):
        self._principal = principal
        self.requests = []

    def get_principal(self, *, agent_id, admin_user_id, admin_permissions):
        self.requests.append(
            {
                "agent_id": agent_id,
                "admin_user_id": admin_user_id,
                "admin_permissions": list(admin_permissions),
            }
        )
        return self._principal


def _wire(monkeypatch, admin_id, permissions, principal):
    from internal.entity.admin_agent_entity import AdminAgentPrincipal

    monkeypatch.setattr(support, "_resolve_admin_permission", _admin_ctx(admin_id, permissions))
    agent_svc = _StubAgentService(principal)
    exec_svc = _StubExecutionService()
    services = {
        "AdminAgentService": agent_svc,
        "AdminAgentExecutionService": exec_svc,
    }

    def _get(cls):
        return services[cls.__name__]

    monkeypatch.setattr(support, "_get_service", _get)
    return agent_svc, exec_svc


class TestInvokeEndpoint:
    def test_invoke_passes_effective_permissions_from_live_admin(self, monkeypatch):
        """路由必须把**当前管理员**的实时权限传给 get_principal（运行时重算）。"""
        from uuid import uuid4

        from internal.entity.admin_agent_entity import AdminAgentPrincipal

        admin_id = uuid4()
        agent_id = uuid4()
        principal = AdminAgentPrincipal(
            admin_user_id=admin_id,
            agent_id=agent_id,
            agent_name="运维 Agent",
            effective_permissions=frozenset({"builtin_tool:update"}),
        )
        agent_svc, exec_svc = _wire(
            monkeypatch, admin_id, ["builtin_tool:read", "builtin_tool:update"], principal
        )

        async def _run():
            client = asgi_app.quart_app.test_client()
            return await client.post(
                f"/admin/agents/{agent_id}/invoke",
                json={"board": "builtin_tool", "action": "list", "payload": {}},
            )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        assert agent_svc.requests[0]["admin_user_id"] == admin_id
        assert set(agent_svc.requests[0]["admin_permissions"]) == {
            "builtin_tool:read",
            "builtin_tool:update",
        }
        assert len(exec_svc.calls) == 1

    def test_unknown_agent_returns_404(self, monkeypatch):
        from uuid import uuid4

        _wire(monkeypatch, uuid4(), ["builtin_tool:read"], None)

        async def _run():
            client = asgi_app.quart_app.test_client()
            return await client.post(
                f"/admin/agents/{uuid4()}/invoke",
                json={"board": "builtin_tool", "action": "list"},
            )

        resp = asyncio.run(_run())
        assert resp.status_code == 404

    def test_permission_error_returns_403(self, monkeypatch):
        from uuid import uuid4

        from internal.entity.admin_agent_entity import AdminAgentPrincipal

        admin_id = uuid4()
        principal = AdminAgentPrincipal(
            admin_user_id=admin_id,
            agent_id=uuid4(),
            agent_name="x",
            effective_permissions=frozenset(),
        )
        _wire(monkeypatch, admin_id, ["builtin_tool:read"], principal)

        class _Deny(_StubExecutionService):
            def run(self, principal, *, board, action, payload):
                raise PermissionError("Agent 无权限执行该动作")

        async def _run():
            client = asgi_app.quart_app.test_client()
            return await client.post(
                f"/admin/agents/{principal.agent_id}/invoke",
                json={"board": "builtin_tool", "action": "update_enabled"},
            )

        resp = asyncio.run(_run())
        assert resp.status_code == 403


class TestPermissionMapping:
    def test_invoke_requires_agent_pool_manage(self):
        """执行入口是写性质操作，必须映射到 agent_pool:manage（不能落到 read）。"""
        assert (
            support._admin_route_permission("POST", "/admin/agents/<uuid:agent_id>/invoke")
            == "agent_pool:manage"
        )

    def test_drafts_list_requires_agent_pool_read(self):
        assert (
            support._admin_route_permission("GET", "/admin/agents/<uuid:agent_id>/drafts")
            == "agent_pool:read"
        )
```

> 注意：上面 `test_permission_error_returns_403` 里 `_Deny` 类被定义但未接入 `_wire`。实现者在写测试时改为先 `_wire(...)` 再 `monkeypatch.setattr` 替换 execution service，或直接给 `_wire` 增加 `execution_service` 参数。以能真正触发 403 为准。

- [x] **Step 2: 运行测试，确认失败**

```bash
cd api && python -m pytest test/app/http/test_admin_agent_invoke_routes.py --no-cov -p no:cacheprovider -q
```

预期：FAIL（404 / 路由不存在；权限映射返回 `agent_pool:manage` 对 `invoke` 可能已通过但 `drafts` 未登记）。

- [x] **Step 3: 登记权限映射**

`api/app/http/support.py` 的 `admin/agents` 分支（L515-521）改为动作粒度：

```python
    if _admin_match(segments, ("admin", "agents")):
        # 执行入口（invoke）是写性质操作：即使动作本身只读，也代表"让 Agent
        # 在后台动手"，必须持 agent_pool:manage，不允许只读权限触发。
        if method == "POST" and _admin_match(
            segments, ("admin", "agents", "<uuid:agent_id>", "invoke")
        ):
            return "agent_pool:manage"
        if method == "GET":
            return "agent_pool:read"
        if method in {"POST", "PATCH", "PUT", "DELETE"}:
            return "agent_pool:manage"
        return None
```

> 实现者注意：`_admin_match` 是前缀比对，路径段里有 flask/quart 的转换器写法 `<uuid:agent_id>`，不能直接原样比对。请改为按段数 + 末段判定，与文件内 `routing-quality` 分支的既有写法保持一致：

```python
    if _admin_match(segments, ("admin", "agents")):
        # POST /admin/agents/<id>/invoke → 执行入口（写性质，需 manage）
        if method == "POST" and len(segments) >= 4 and segments[-1] == "invoke":
            return "agent_pool:manage"
        if method == "GET":
            return "agent_pool:read"
        if method in {"POST", "PATCH", "PUT", "DELETE"}:
            return "agent_pool:manage"
        # 未登记的方法 fail closed
        return None
```

- [x] **Step 4: 追加路由端点**

`api/app/http/admin_routes_7.py`，在 `assignable-permissions` 端点之后追加：

```python
    @quart_app.post("/admin/agents/<uuid:agent_id>/invoke")
    async def admin_agent_invoke(agent_id):
        """执行一个板块动作（管理端 Agent 治理，设计 §7.1 执行四步）。

        权限点由全局 RBAC 门禁强制为 `agent_pool:manage`（见 support.py）——
        执行入口代表"让 Agent 在后台动手"，不接受只读权限触发。
        """
        from app.http import asgi_app as a

        admin, err = await a._resolve_admin_permission("agent_pool:manage")
        if err is not None:
            return err

        from internal.schema.admin_agent_schema import AdminAgentInvokeReq
        from internal.service.admin_agent_execution_service import (
            AdminAgentExecutionService,
        )
        from internal.service.admin_agent_service import AdminAgentService

        payload = await request.get_json(force=True, silent=True) or {}
        form = AdminAgentInvokeReq(data=payload)
        if not form.validate():
            return a._json_resp(
                code="validate_error", message="参数错误", data=form.errors, status=400
            )

        admin_user_id = admin.get("id")
        admin_permissions = list(admin.get("permissions") or [])

        def _run():
            agent_service = a._get_service(AdminAgentService)
            principal = agent_service.get_principal(
                agent_id=agent_id,
                admin_user_id=admin_user_id,
                admin_permissions=admin_permissions,
            )
            if principal is None:
                return None
            execution = AdminAgentExecutionService(
                board_executor=_build_board_executor(),
                draft_service=a._get_service(_draft_service_class()),
                audit_log_service=_build_audit_service(),
            )
            return execution.run(
                principal,
                board=form.board.data,
                action=form.action.data,
                payload=form.payload.data or {},
            )

        try:
            result = await a._to_thread(_run)
        except PermissionError as exc:
            return a._json_resp(code="forbidden", message=str(exc), status=403)
        except ValueError as exc:
            return a._json_resp(code="validate_error", message=str(exc), status=400)
        if result is None:
            return a._json_resp(code="not_found", message="Agent 不存在", status=404)
        return a._ok(result)

    @quart_app.get("/admin/agents/<uuid:agent_id>/drafts")
    async def admin_agent_drafts(agent_id):
        """列出某 Agent 产出的待应用变更草稿。"""
        from app.http import asgi_app as a

        admin, err = await a._resolve_admin_permission("agent_pool:read")
        if err is not None:
            return err

        from internal.schema.admin_agent_schema import AdminAgentDraftListResp
        from internal.service.admin_agent_service import AdminAgentService

        admin_user_id = admin.get("id")

        def _run():
            agent_service = a._get_service(AdminAgentService)
            agent = agent_service.get_agent(
                agent_id=agent_id, admin_user_id=admin_user_id
            )
            if agent is None:
                return None
            draft_service = a._get_service(_draft_service_class())
            drafts = draft_service.list_drafts(status="pending")
            rows = [
                d
                for d in drafts
                if str((d.impact or {}).get("agent_id") or "") == str(agent_id)
            ]
            return {"items": [_dump_draft(d) for d in rows]}

        try:
            result = await a._to_thread(_run)
        except PermissionError as exc:
            return a._json_resp(code="forbidden", message=str(exc), status=403)
        if result is None:
            return a._json_resp(code="not_found", message="Agent 不存在", status=404)
        resp = AdminAgentDraftListResp()
        return a._ok(resp.dump(result))
```

并在文件顶部（模块级，`_registered` 之后）追加三个组装辅助：

```python
def _draft_service_class():
    from internal.service.admin_change_draft_service import AdminChangeDraftService

    return AdminChangeDraftService


def _build_board_executor():
    from internal.service.admin_agent_board_tools import BoardToolExecutor

    return BoardToolExecutor()


def _build_audit_service():
    from internal.service.audit_log_service import AuditLogService

    return AuditLogService()


def _dump_draft(draft) -> dict:
    """序列化变更草稿（UUID / datetime → 字符串）。"""
    from internal.lib.helper import datetime_to_timestamp

    return {
        "id": str(draft.id),
        "policy_type": draft.policy_type,
        "target_id": draft.target_id,
        "before_config": draft.before_config or {},
        "after_config": draft.after_config or {},
        "diff": draft.diff or {},
        "impact": draft.impact or {},
        "status": draft.status,
        "created_at": datetime_to_timestamp(draft.created_at),
    }
```

> `_build_audit_service()` 用 `AuditLogService()`：其构造参数 `session=None` → 走 `db.session`（默认值），与既有 `scoped_knowledge_service._get_audit_log_service()` 的写法一致。
>
> `_draft_service_class()` 返回类、再由 `a._get_service(cls)` 解析：`AdminChangeDraftService` 不是 `@inject`，若 injector 无法构造，请改为直接 `AdminChangeDraftService(db=a._get_service(SQLAlchemy))`。**实现时以实际能否解析为准**；若 injector 报无法构造，就在 `_run()` 内直接实例化：

```python
            from internal.extension.database_extension import db as _db

            from internal.service.admin_change_draft_service import (
                AdminChangeDraftService,
            )

            draft_service = AdminChangeDraftService(db=_db)
```

- [x] **Step 5: 补 schema**

`api/internal/schema/admin_agent_schema.py` 追加：

```python
from marshmallow import Schema, ValidationError, fields, validate, validates_schema


class AdminAgentInvokeReq(Schema):
    """执行一个板块动作的请求体。"""

    board = fields.String(required=True)
    action = fields.String(required=True)
    payload = fields.Dict(load_default=dict)


class AdminAgentDraftResp(Schema):
    id = fields.String()
    policy_type = fields.String()
    target_id = fields.String()
    before_config = fields.Dict()
    after_config = fields.Dict()
    diff = fields.Dict()
    impact = fields.Dict()
    status = fields.String()
    created_at = fields.Integer(allow_none=True)


class AdminAgentDraftListResp(Schema):
    items = fields.List(fields.Nested(AdminAgentDraftResp), dump_default=[])
```

> 顶部原 import 行是 `from marshmallow import Schema, fields`；保留它并追加需要的名称即可（不要出现重复 import）。

- [x] **Step 6: 建板块 Agent 提示词 YAML**

创建 `api/internal/core/prompts/admin_agent/board_agent.yaml`：

```yaml
# 管理端 Agent 系统提示词（板块治理）。
# 此文件由 prompt_sync_service 在启动时同步到 DB prompt_template 表。
# admin 可在后台创建 source=custom 的副本进行覆盖，不会被 YAML 同步覆盖。
# 修改此文件后重启服务即生效（content_hash 变化触发更新）。

prompt_key: admin_agent_board_agent
name: 管理端板块治理 Agent
category: admin_agent
description: 管理端 Agent 的系统提示词：在已授权板块内执行治理动作，写操作按自动化级别分流
variables:
  agent_name: Agent 名称（运行时填充）
  granted_permissions: 该 Agent 生效权限清单（运行时填充）
  automation_policy: 各板块自动化级别（运行时填充）
content: |
  你是「{agent_name}」，一个在管理后台（admin）内工作、受管理员监督的治理 Agent。

  # 你的职责边界
  1. 你**只能**操作被显式授权的板块与动作；
  2. 你**不能**接触任何用户端（C 端）的内容——用户端与你在账号层面完全隔离；
  3. 你**不能**修改管理员账号、角色、权限点——这些对你永久封禁。

  # 当前生效权限
  {granted_permissions}

  # 各板块自动化级别
  {automation_policy}

  级别含义：
  - `supervised`：你的变更会先变成**待批准草稿**，管理员点「应用」后才真正生效。
  - `autonomous`：你的变更**直接生效**。删除类操作会进回收站，写操作有快照可回滚。
  - `blocked`：该板块已熔断，即使你有权限也不会执行。

  # 工作方式
  1. 动手前先调用对应板块的只读动作了解现状（不要凭猜测改配置）；
  2. 每次只做一个明确的变更，说明**为什么**要改、改前改后是什么；
  3. 被拒绝时不要反复重试同一动作——把拒绝原因如实回报给管理员；
  4. 变更完成后简要汇报：改了哪个板块的哪个对象、结果如何、如何回滚。

  # 硬约束
  1. 不要臆造板块或动作名——只使用被授权的板块与动作；
  2. 不要在未读现状的情况下做删除或启停；
  3. 管理员明确否决的变更，不要再提第二次（除非情况已变化并说明）。
```

`api/internal/core/prompts/index.yaml` 追加一行：

```yaml
- key: admin_agent_board_agent
  category: admin_agent
  file: admin_agent/board_agent.yaml
```

- [x] **Step 7: 运行测试，确认通过**

```bash
cd api && python -m pytest test/app/http/test_admin_agent_invoke_routes.py test/app/http/test_admin_rbac_guard.py test/app/http/test_admin_agent_routes.py --no-cov -p no:cacheprovider -q
```

预期：PASS（含 `test_every_registered_admin_route_has_a_permission`——新端点必须已登记权限）。

- [x] **Step 8: 反向验证**

临时把 `support.py` 里 `invoke` 的分支删掉（让它落到 `POST → agent_pool:manage` 的通用分支，值相同）——这条验证不出问题。改为：**临时让 invoke 返回 `agent_pool:read`**，重跑：

```bash
cd api && python -m pytest test/app/http/test_admin_agent_invoke_routes.py::TestPermissionMapping --no-cov -p no:cacheprovider -q
```

预期：**必须 FAIL**（`test_invoke_requires_agent_pool_manage`）。恢复。

- [x] **Step 9: 提交**

```bash
cd api && git add app/http/admin_routes_7.py app/http/support.py internal/schema/admin_agent_schema.py internal/core/prompts/admin_agent/board_agent.yaml internal/core/prompts/index.yaml test/app/http/test_admin_agent_invoke_routes.py
git commit -m "feat(admin-agent): add invoke entry point and board agent prompt

- POST /admin/agents/<id>/invoke：执行一个板块动作。路由层解析当前管理员
  并把其**实时权限**传给 get_principal（运行时重算三重交集），再交由
  AdminAgentExecutionService 分流与审计。权限映射为 agent_pool:manage
  ——执行入口代表"让 Agent 在后台动手"，不接受只读权限触发。
- GET /admin/agents/<id>/drafts：列出该 Agent 产出的待应用草稿（按 impact
  里的 agent_id 过滤），供后台「待批准变更」页消费。
- 板块 Agent 提示词 admin_agent/board_agent.yaml + index.yaml 登记，
  遵循 AGENTS.md 强制规则（prompt 走 YAML seed + admin 可编辑，
  不硬编码在 .py 里）。"
```

---

## Task 10: 文档同步与收尾验证

**Files:**
- Modify: `docs/rbac.md`（追加 §9 的 P1b 补充：板块工具与审计身份）
- Modify: `docs/prd/modules/01-agent-tool-pool.md`（`internal_admin` 池消费方接线状态）
- Modify: `docs/prd/modules/03-orchestration-infra.md`（变更草稿泛化）
- Modify: `docs/prd/architecture-design.md`（管理端 Agent 治理层）
- Modify: `docs/prd/execution-roadmap.md`（P1b 完成记录）
- Modify: `docs/README.md`（若新增顶层文档）
- Modify: `api/internal/schema/admin_audit_log_schema.py`（补 `agent_name` 回源，若 Task 2 Step 11 未做）

- [x] **Step 1: 补 `agent_name` 批量回源**

若 Task 2 只在 schema 声明了 `agent_name` 而没填值，在 `AuditLogService` 补：

`_build_resource_name_map` 同级新增：

```python
    def _build_agent_name_map(self, audit_logs: list) -> dict[str, str]:
        """批量解析 agent_id → Agent 名称（30 条/页，一次 IN 查询即可）。

        审计的 actor_type=agent 记录需要展示"哪个 Agent 干的"；agent_id 是
        UUID，直接展示对管理员没有意义。
        """
        agent_ids = {
            str(log.agent_id)
            for log in audit_logs
            if getattr(log, "agent_id", None)
        }
        if not agent_ids:
            return {}
        try:
            from internal.model.admin_agent import AdminAgent

            rows = (
                self.session.query(AdminAgent.id, AdminAgent.name)
                .filter(AdminAgent.id.in_(list(agent_ids)))
                .all()
            )
        except Exception:
            # 未迁移到位/替身场景：静默降级，不影响列表返回
            return {}
        return {str(row[0]): (row[1] or "") for row in rows}
```

`list_audit_logs` 中构造并透传（与 `resource_name_map` 同模式）：

```python
        resource_name_map = self._build_resource_name_map(audit_logs)
        agent_name_map = self._build_agent_name_map(audit_logs)
```

`_serialize_audit_log` 增加参数并在返回值里输出：

```python
            "agent_name": (
                agent_name_map.get(str(audit_log.agent_id), "")
                if getattr(audit_log, "agent_id", None)
                else ""
            ),
```

- [x] **Step 2: 补测试**

追加到 `api/test/internal/model/test_audit_log_actor_fields.py`：

```python
def test_build_agent_name_map_degrades_silently_on_error():
    """Agent 名解析失败必须静默降级为空 map（不影响审计列表返回）。"""
    from internal.service.audit_log_service import AuditLogService

    class _S:
        def query(self, *a, **kw):
            raise RuntimeError("db down")

    svc = AuditLogService(session=_S())
    assert svc._build_agent_name_map([SimpleNamespace(agent_id=uuid4())]) == {}


def test_build_agent_name_map_empty_when_no_agent():
    from internal.service.audit_log_service import AuditLogService

    svc = AuditLogService(session=None)
    assert svc._build_agent_name_map([SimpleNamespace(agent_id=None)]) == {}
```

（在文件顶部补 `from types import SimpleNamespace` 与 `from uuid import uuid4`，若已存在则不重复。）

- [x] **Step 3: 运行测试**

```bash
cd api && python -m pytest test/internal/model/test_audit_log_actor_fields.py test/internal/service/test_audit_log_service.py --no-cov -p no:cacheprovider -q
```

预期：PASS。

- [x] **Step 4: 同步 `docs/rbac.md`**

在 §9「管理端 Agent 授权模型」末尾追加 §9.7：

```markdown
### 9.7 板块工具与执行分流（P1b）

授权（§9.1-9.4）解决"Agent 能不能碰"，执行层解决"碰的时候要不要等人"。

**板块动作注册表**：`api/internal/core/admin_agent_boards.py` 是「板块动作 → 所需权限点」的**唯一事实源**（`BOARD_ACTIONS` / `resolve_action()`）。采用**显式登记制**：未声明的 `(board, action)` 一律抛 `ValueError`——工具内部按 action 分支，漏声明必须表现为明确报错而非静默放行。`BOARD_IDS` 由 `BOARD_ACTIONS` 派生，禁止手工维护两个清单。

**执行四步**（`AdminAgentExecutionService.run`）：

| 步 | 行为 | 失败处置 |
|---|---|---|
| 1 | 校验 `principal.effective_permissions` 含该 action 所需权限点；判 `blocked` 熔断 | 拒绝**并记审计**（`action=...denied`） |
| 2 | 按 `automation_policy` 分流：`supervised` → 产变更草稿（**不执行**）/ `autonomous` → 继续 / `blocked` → 已在第 1 步拒绝 | 未配置板块一律 `supervised`（fail closed） |
| 3 | 调板块实现体（service 层不感知 Agent，保持纯粹） | 异常向上抛出，审计已记第 1/2 步的拒绝 |
| 4 | 写审计：`actor_type=agent` + `agent_id` + `admin_user_id`（人类责任人） | 审计失败不阻断主流程，记日志 |

**为什么新建独立执行链路而不复用用户端 `chat()`**：`AssistantAgentService._build_assistant_runtime_tools()` 是**用户域固有工具的装配点**，且是**条件装配**（逐个 `try` + 功能开关 + 运行上下文），实际工具数随配置动态变化。复用它只能靠黑名单排除用户域工具，而黑名单对动态集合不完备——漏一个就是越权。新链路只装配 admin 板块工具（白名单式，未登记即不装配），边界可自证。

**可下放的板块**（`ASSIGNABLE_RESOURCES` 中已登记，共 33 个 resource 前缀）：包含 `builtin_tool` / `prompt_template` / `orchestration_flag` / `recycle_bin` / `model_pool` / `agent_pool` 等；**永久封禁**身份与权限体系（`admin:access` / `admin_user:*` / `role:*` / `permission:read`），`user:*` 仅 `:read` 可下放。

**已实现的板块动作（P1b 范围）**：仅 `builtin_tool`（`list` / `update_enabled` / `update_metadata`）——作为端到端样板；其余板块按同一模式增量登记 `BOARD_ACTIONS` 并补 `_do_<board>` 实现体即可。

**审计身份**（§9）：`audit_log.actor_type`（`human`/`agent`，NOT NULL，默认 `human`）+ `agent_id`（可空，**刻意不加 FK**——Agent 可被物理删除，审计必须留住痕迹）。`admin_user_id` 始终保持为人类责任人，因此可精确区分「A 自己改的」与「A 让 AI 改的」。

**回收站 `admin_agent` 来源**：既有 `deleted_by_type="agent"` 被硬约束为仅 7 类用户可见资源，admin 专属资源（`app`/`workflow`/`skill`/`mcp`/`api_tool`/`system_prompt`/`upload_file`）以该来源入站会抛 `ValidateErrorException`。因此新增 `admin_agent` 来源：放行 admin 专属资源、留存按 admin 口径（默认 30 天、可配，区别于用户侧 agent 的固定 7 天）、`_agent_id` 写入快照供追溯。admin 回收站列表改为 `in_(('admin','admin_agent'))`，否则 Agent 代删条目在后台不可见、无法恢复。
```

- [x] **Step 5: 同步 `docs/prd/modules/01-agent-tool-pool.md`**

在 §8 或 `internal_admin` 池相关小节，把「预留未接线」更正为已接线，并写清消费方：

```markdown
> **`internal_admin` 池的消费方（2026-09 已接线）**：该子池此前为"预留未接线"。P1b 起，管理端 Agent 治理链路（`api/internal/service/admin_agent_execution_service.py`）是其消费方——它经 `AdminAgentPrincipal` 携带管理端身份执行板块动作，与用户端 Agent 候选收集（`AgentCandidateCollector`）是**两条互不交叉的链路**：用户端链路按 `account_id` 隔离、走 `AgentPolicyFilter`；管理端链路按 `admin_user_id` 隔离、走板块动作注册表（`admin_agent_boards.py`）。两条链路的候选/授权来源不同，不可互相替代。
```

- [x] **Step 6: 同步 `docs/prd/modules/03-orchestration-infra.md`**

在策略变更相关小节追加：

```markdown
#### 15.x 变更草稿泛化（P1b）

`policy_change_draft` 已由「路由调优专用台账」提升为**通用 admin 变更草稿**（设计 §5.2），承载所有板块 `supervised` 档的「Agent 提议 → 人工批准」：

- `suggestion_id` 由 NOT NULL 改为**可空**（通用草稿不来自路由建议；路由路径仍写入，存量数据零迁移）；
- `policy_type` 语义扩展为**板块标识**（如 `builtin_tool` / `prompt_template`），路由三个既有取值（`model_routing` / `tool_policy` / `agent_policy`）保持兼容；
- 新增 `(status, created_at)` 索引支撑「跨板块列出待应用草稿」；
- 通用台账由 `AdminChangeDraftService` 承担（创建/列出/应用/回滚 + 状态机守卫：仅 `pending` 可应用、仅 `applied` 可回滚）；路由板继续用 `RoutingPolicyChangeService`（含 suggestion 状态联动与特性开关写入）。二者**共用同一张表**，避免 admin 侧并存两套草稿表。
- `agent_id` 写入 `impact` JSONB 以支持追溯「哪个 Agent 提的建议」（不为单一用途扩列）。
```

- [x] **Step 7: 同步 `docs/prd/architecture-design.md`**

在架构分层处补一节管理端 Agent 治理层，写清 L1-L5 与 P1a/P1b 的落地状态：

```markdown
#### 管理端 Agent 治理层（P1a/P1b 已落地）

与用户端 Agent 链路**完全独立**的第二条 Agent 链路，服务于"管理员监督下的后台自动化"：

| 层 | 组件 | 状态 |
|---|---|---|
| L5 入口 | `POST /admin/agents/<id>/invoke`、`GET /admin/agents/<id>/drafts` | ✅ P1b（对话式入口与会话表属 P2） |
| L4 身份 | `AdminAgentPrincipal`（不可变，全链路显式传参） | ✅ P1a |
| L3 授权 | `effective = admin.permissions ∩ agent.granted_permissions ∩ ASSIGNABLE_PERMISSIONS` | ✅ P1a |
| L2 能力 | 板块级聚合工具（`BoardToolExecutor` + `admin_agent_boards.py` 注册表） | ✅ P1b（当前仅 `builtin_tool` 板块） |
| L1 执行 | `AdminAgentExecutionService`（分流域 + 审计域） | ✅ P1b |

关键边界：管理端 Agent **不能接触任何用户端内容**（账号层面已隔离）；**不继承**管理员全部权限（三重交集）；模型成本由系统承担（P4 补预算闸门）。

详见 [rbac.md §9](../rbac.md)（授权与执行机制）与 [01-agent-tool-pool.md](./modules/01-agent-tool-pool.md)（`internal_admin` 池消费方）。
```

- [x] **Step 8: 同步 `docs/prd/execution-roadmap.md`**

在 Phase 表追加一行并补一节：

```markdown
| Phase 16 | 管理端 Agent 治理 P1b（板块工具与执行链路） | ✅ 完成 |
```

```markdown
### 管理端 Agent 治理（P1b 板块工具与执行链路，2026-09-16 完成）

在 P1a 授权内核之上装配能力层与执行层，让 Agent 从「只有授权」变为「能真正执行板块动作」。

| 交付物 | 位置 |
| --- | --- |
| 板块动作注册表（fail closed） | `api/internal/core/admin_agent_boards.py` |
| 通用变更草稿服务（supervised 档载体） | `api/internal/service/admin_change_draft_service.py` |
| 板块级聚合工具与执行闸门 | `api/internal/service/admin_agent_board_tools.py` |
| 执行层（分流 + 审计） | `api/internal/service/admin_agent_execution_service.py` |
| 执行入口 | `POST /admin/agents/<id>/invoke`、`GET /admin/agents/<id>/drafts`（`admin_routes_7.py`） |
| 审计身份 | `audit_log.actor_type` / `agent_id`（迁移 `t8b9c0d1e2f3`） |
| 草稿泛化 | `policy_change_draft.suggestion_id` 可空 + 板块标识（迁移 `u9c0d1e2f3a4`） |
| 回收站 Agent 来源 | `deleted_by_type='admin_agent'`（迁移 `v0d1e2f3a4b5`） |
| builtin 工具写路径补齐 | `BuiltinToolService.set_tool_enabled` + `_builtin_tool_update` 放开 enabled |
| 机制文档 | [rbac.md §9.7](../rbac.md)、[architecture-design.md](./architecture-design.md) |

**执行模型**：`AdminAgentExecutionService.run` 执行四步——① 权限/熔断校验（拒绝并记审计）② 按 `automation_policy` 分流（`supervised` 产草稿不执行 / `autonomous` 直接执行 / `blocked` 熔断）③ 调板块实现体 ④ 写 `actor_type=agent` 审计。未配置板块一律 `supervised`（fail closed）。

**已实现板块**：仅 `builtin_tool`（`list` / `update_enabled` / `update_metadata`）作为端到端样板；其余板块按同一模式增量登记。实现计划见 `docs/superpowers/plans/2026-09-16-admin-agent-p1b-board-tools.md`。

**顺带修复**：4 类审计写入静默丢失（`system_knowledge` 全量、`admin_user.revoke_admin_sessions`、`redeem_code.view_plain` 在 commit 之后写入被回滚；`admin_commerce_routes._write_audit` 绕过 service 且永不提交），并新增 AST 静态守卫 `test_audit_write_commit_guard.py`。

**回归防护**：`test_admin_agent_boards.py`、`test_admin_change_draft_service.py`、`test_admin_agent_board_tools.py`、`test_admin_agent_execution_service.py`、`test_admin_agent_invoke_routes.py`、`test_recycle_bin_admin_agent.py`、`test_builtin_tool_write_paths.py`、`test_audit_write_commit_guard.py`——**均含反向验证**。
```

- [x] **Step 9: 全量测试**

```bash
cd api && python -m pytest --no-cov -p no:cacheprovider -q 2>&1 | tail -30
```

预期：全部 PASS。记录通过数（P1a 结束时为 4444）。

- [x] **Step 10: 空库迁移冒烟**

```bash
cd api && python -m pytest test/internal/migration/ --no-cov -p no:cacheprovider -q
```

预期：PASS 且**无 skip**（若环境连不上 PG 会 skip——CI 必须真实执行）。这条验证三条新迁移在全新数据库上能以正确顺序跑通。

- [x] **Step 11: 接线自检（逐个新符号点名入口）**

对本次新增的每个符号，用全仓搜索确认有生产调用方（排除 `api/test/**` 与文档）：

```bash
cd api && for s in "admin_agent_boards" "resolve_action" "AdminChangeDraftService" "BoardToolExecutor" "AdminAgentExecutionService" "get_principal" "set_tool_enabled" "admin_agent" ; do echo "=== $s ==="; grep -rn "$s" --include=*.py internal app | grep -v "^test/" | grep -v __pycache__ | head -8; done
```

逐条核对并记录到终端：

| 新符号 | 必须能指出的入口 |
| --- | --- |
| `admin_agent_boards.BOARD_ACTIONS` / `resolve_action` | `BoardToolExecutor.assert_allowed` ← `AdminAgentExecutionService.run` ← `POST /admin/agents/<id>/invoke` |
| `AdminChangeDraftService.create_draft` | `AdminAgentExecutionService.run` 的 supervised 分支 |
| `AdminChangeDraftService.list_drafts/apply_draft/rollback_draft` | `GET /admin/agents/<id>/drafts`（list）；apply/rollback 由后续「待批准变更」页消费（本计划已提供能力，UI 属后续） |
| `BoardToolExecutor.execute` | `AdminAgentExecutionService.run` 第 3 步 |
| `AdminAgentExecutionService.run` | `POST /admin/agents/<id>/invoke` |
| `AdminAgentService.get_principal` | `POST /admin/agents/<id>/invoke` 与 `GET /admin/agents/<id>/drafts` |
| `BuiltinToolService.set_tool_enabled` | `BoardToolExecutor._do_builtin_tool` 的 `update_enabled` 分支；`PATCH /admin/builtin-tools/<id>`（`enabled` 字段） |
| `AuditLog.actor_type` / `agent_id` | 写入：`AuditLogService.record(actor_type=...)` ← `AdminAgentExecutionService._audit`；读取：`AuditLogService._serialize_audit_log` ← `GET /admin/audit-logs` |
| `deleted_by_type='admin_agent'` | 写入：`RecycleBinService.delete_resource(deleted_by_type="admin_agent")`（当前由板块工具在 delete 类动作调用；`builtin_tool` 板块暂无删类动作）；读取：`GET /admin/recycle-bin` |

> **注意**：`AdminChangeDraftService.apply_draft` / `rollback_draft` 目前**只有测试调用**——本计划提供能力但尚未接入 UI/路由（「待批准变更」页属后续阶段）。按 AGENTS.md 规则，这必须在文档与回复中**明确标注「已提供能力但未接入」**，不得写成「已实现」。

- [x] **Step 12: 更新 `graphify`**

```bash
cd /d d:\DEMO\openagent-main && python -m graphify update .
```

- [x] **Step 13: 提交**

```bash
git add docs/ api/internal/schema/admin_audit_log_schema.py api/internal/service/audit_log_service.py api/test/internal/model/test_audit_log_actor_fields.py
git commit -m "docs(admin-agent): document P1b board tools, execution routing and audit identity

同步 P1b 的架构文档：
- rbac.md 新增 §9.7（板块动作注册表 / 执行四步 / 独立执行链路的存在理由 /
  已实现板块范围 / 审计身份 / 回收站 admin_agent 来源）；
- 01-agent-tool-pool.md：internal_admin 池由「预留未接线」更正为已接线，
  写清其消费方是管理端 Agent 链路，与用户端候选收集互不交叉；
- 03-orchestration-infra.md：变更草稿泛化的字段语义与两个服务的分工；
- architecture-design.md：管理端 Agent 治理层的 L1-L5 与 P1a/P1b 落地状态；
- execution-roadmap.md：Phase 16 + P1b 交付物与回归防护清单。

另补 AuditLogService._build_agent_name_map（审计列表展示「哪个 Agent 干的」，
失败静默降级为空 map）及对应降级测试。

明确标注未接入项：AdminChangeDraftService.apply_draft / rollback_draft
已提供能力，但「待批准变更」页属后续阶段，当前只有测试调用。"
```

---

## 覆盖度自检

| 设计文档章节 | 对应 Task |
| --- | --- |
| §4.1 三重交集（运行时重算） | Task 7 `get_principal` |
| §4.2 可下放白名单 | P1a 已完成 |
| §4.3 展示 / 保存 / 运行三层 | P1a（前两层）+ Task 7（运行时层） |
| §4.4 权限回收 | P1a 已完成 |
| §5 L4 身份层 | P1a（对象）+ Task 7（装配） |
| §5.1 自动化级别三档 + fail closed | Task 7（`automation_level_for`）+ Task 8（分流） |
| §5.2 通用变更草稿 | Task 4 |
| §6.1 独立执行链路 | Task 8（模块 docstring 说明理由） |
| §6.2 计费 billable=false | 复用既有 feature 机制，本计划不改（已在 P1a 注册的 `_BUILTIN_FEATURES` 外）|
| §6.3 预算闸门 | **P4**（`budget_config` 列已在 P1a 建好） |
| §7.1 板块级聚合工具 | Task 3（注册表）+ Task 6（写路径）+ Task 7（执行器）+ Task 8（编排） |
| §7.1 回收站 `admin_agent` 扩展 | Task 5 |
| §7.2 MCP 动态身份注入 | **P5** |
| §8 记忆主体统一抽象 | **P3** |
| §9 审计身份 | Task 2（列 + 服务）+ Task 8（写入）+ Task 10（展示） |
| §10.1 新建表（会话/消息） | **P2** |
| §10.2 修改表（`audit_log`） | Task 2 |
| §10.2 修改表（`schedule_task.agent_id`） | **P4** |
| §10.2 修改表（记忆三字段） | **P3** |
| §10.2 修改表（`policy_change_draft` 泛化） | Task 4 |
| §10.3 提示词 YAML seed | Task 9 |
| §11 存量清理 | **P6** |
| §12 地基修复 | P0 已完成 |
| §15 文档同步清单 | Task 10 |

**未覆盖且有意留待后续**：
- 对话式入口与会话表 → **P2**
- 记忆主体抽象 → **P3**
- 预算闸门实际执行、`schedule_task.agent_id` → **P4**
- MCP 动态身份注入 → **P5**
- 存量清理迁移 → **P6**
- 「待批准变更」前端页（消费 `apply_draft` / `rollback_draft`）→ 后续阶段
- 除 `builtin_tool` 外的板块动作 → 按同一模式增量登记

---

## 类型一致性自检

| 符号 | 定义处 | 使用处 | 一致 |
| --- | --- | --- | --- |
| `BoardAction.is_write` | Task 3（property） | Task 8 `needs_draft` 判定 | ✅ |
| `resolve_action(board, action)` | Task 3 | Task 7 `assert_allowed`、Task 8 测试替身 | ✅ |
| `AutomationLevel.{SUPERVISED,AUTONOMOUS,BLOCKED}` | P1a | Task 7 / Task 8 | ✅ |
| `AdminAgentPrincipal.automation_level_for(board)` | P1a | Task 7 `requires_draft` 间接、Task 8 | ✅ |
| `AdminAgentPrincipal.has_permission(code)` | P1a | Task 7 `assert_allowed` | ✅ |
| `compute_effective_permissions(admin_permissions=, granted_permissions=)` | P1a | Task 7 `get_principal` | ✅ |
| `AdminChangeDraftService.create_draft(*, policy_type, target_id, before_config, after_config, diff, impact, created_by, agent_id)` | Task 4 | Task 8 supervised 分支 | ✅ |
| `AdminChangeDraftService.list_drafts(*, status, policy_type)` | Task 4 | Task 9 `admin_agent_drafts` | ✅ |
| `BoardToolExecutor.assert_allowed(principal, *, board, action)` | Task 7 | Task 8 第 1 步 | ✅ |
| `BoardToolExecutor.requires_draft(principal, board)` | Task 7 | Task 8 第 2 步 | ✅ |
| `BoardToolExecutor.execute(principal, *, board, action, payload)` | Task 7 | Task 8 第 3 步 | ✅ |
| `AuditLogService.record(*, ..., actor_type, agent_id, commit)` | Task 2 | Task 8 `_audit` | ✅ |
| `BuiltinToolService.set_tool_enabled(tool_id, enabled, *, set_custom_source)` | Task 6 | Task 7 `_do_builtin_tool` | ✅ |
| `RecycleBinService.delete_resource(*, ..., deleted_by_type="admin_agent", agent_id=)` | Task 5 | 板块 delete 类动作（`builtin_tool` 板块暂无） | ✅ |
| `ExecutionOutcome.{EXECUTED,DRAFTED}` | Task 8 | Task 8 测试、Task 9 路由返回值 | ✅ |
| `DraftStatus.{PENDING,APPLIED,ROLLED_BACK}` | Task 4 | Task 4 测试 | ✅ |

---

## 执行交接

计划已保存到 `docs/superpowers/plans/2026-09-16-admin-agent-p1b-board-tools.md`。两种执行方式：

**1. Subagent-Driven（推荐）** — 每个 Task 派一个全新 subagent，Task 之间人工审查，快速迭代

**2. Inline Execution** — 在当前会话内按 `executing-plans` 批量执行，带检查点复审

选哪种？
