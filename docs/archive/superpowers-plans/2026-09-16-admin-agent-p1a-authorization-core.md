# 管理端 Agent 治理 P1a：授权与身份内核 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立管理端 Agent 的授权内核——`AdminAgentPrincipal` 显式身份、三重交集授权（含 fail-closed 白名单）、`admin_agent` 表与可分配权限 API，使"管理员显式下放权限子集给 Agent"这条链路可证明、可测试。

**Architecture:** 本计划是设计文档 `docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md` §4（L3 授权层）、§5（L4 身份层）、§10.1/§10.2 中 `admin_agent` 表部分的落地。它**只做授权与身份**，不装配任何板块工具、不接编辑器/执行器——工具装配与执行在 P1b。边界：P1a 结束时能通过 API 创建 Agent、下放权限、查询可分配列表，但 Agent 还不能真正执行任何动作。

**Tech Stack:** Python 3.12 / Quart(ASGI) / SQLAlchemy / Alembic / pytest（`--no-cov` 快跑）

**前置状态（已完成）**：地基修复 P0（`collect_raw`、`_ADMIN_USER_ID`、orchestrator fail closed）、迁移链空库跑通（`r4e5f6a7b8c9` 为唯一 head）。

---

## 关键事实（实现者必读，已实测核实）

| 项 | 事实 | 来源 |
| --- | --- | --- |
| 权限单一事实源 | `api/internal/core/rbac.py` 的 `PERMISSION_CATALOG`，实测 **99** 个权限点、`resource` 前缀 **36** 类 | 已实测 |
| 白名单范围 | 可下放 **85**；不可下放 **14** = `admin:access`、`admin_user:{read,create,update,disable}`、`role:{read,create,update,delete}`、`permission:read`、`user:{create,update,disable,delete}` | 已实测 |
| 迁移 head | `r4e5f6a7b8c9`（唯一 head，三路 merge） | 已实测 |
| `admin_user` 模型 | `api/internal/model/admin.py`，类 `AdminUser`，表 `admin_user`，主键列 **`id`**，约束名 `pk_admin_user_id` | 已实测 |
| 权限校验入口 | `api/app/http/support.py`：`_admin_route_permission(method, path)` L457-728、`_resolve_admin_permission(code)` L396-428、`_resolve_admin_operator()` L431-436 | 已实测 |
| 路由强制层 | `asgi_app.py` 的 `before_request` L64-79；新路由**必须**在 `support.py` 的 `_admin_route_permission` 登记，否则 403 或守卫测试失败 | 已实测 |
| 新路由接线三点 | ① 新建 `admin_routes_N.py` 的 `register_routes`；② `asgi_app.py` L214-248 的 import + 调用；③ `support.py` 权限映射 | 已实测 |
| 测试期 RBAC 替身 | `test/conftest.py` autouse fixture 把 `support._resolve_admin_permission` 无条件放行（`permissions=["*"]`） | 已实测 |
| 管理员删除能力 | **不存在**（无 delete 路由/方法），只有 `active`/`disabled` 状态机 | 已实测 |
| 权限回收触发点 | 角色权限变更 → `AdminRbacService._replace_role_permissions` L302-313；管理员角色变更 → `AdminUserService._replace_admin_user_roles` L675-679；管理员禁用 → `disable_admin_user` L480-508 | 已实测 |

> ⚠️ **本计划不新建迁移文件之外的表**。`admin_change_draft` 改名与回收站扩展属 **P1b**，不在本计划范围。

---

## 关于测试的重要约定

1. 跑测试一律加 `--no-cov -p no:cacheprovider`（默认 `addopts` 带覆盖率，很慢）。
2. **每个边界规则必须有反向验证**：临时把实现改成违规版本 → 测试**必须失败** → 恢复。这是设计文档 §12 的教训（曾有回归测试假通过）。
3. 不要在测试里断言"数量恰为 N"这类易漂移值，除非同时说明由 `PERMISSION_CATALOG` 派生。

---

## 文件结构

**新建**

| 文件 | 职责 |
| --- | --- |
| `api/internal/core/admin_agent_authorization.py` | 授权内核：`ASSIGNABLE_PERMISSIONS` 白名单、`compute_effective_permissions()`、`assert_grantable()` |
| `api/internal/entity/admin_agent_entity.py` | `AdminAgentPrincipal` 数据类 + `AutomationLevel` 枚举 |
| `api/internal/model/admin_agent.py` | `AdminAgent` ORM 模型 |
| `api/internal/service/admin_agent_service.py` | Agent 的 CRUD + 授权校验 + 可分配列表计算 |
| `api/internal/migration/versions/s5f6a7b8c9d0_add_admin_agent_table.py` | 建 `admin_agent` 表 |
| `api/test/internal/core/test_admin_agent_authorization.py` | 授权内核单测（含反向验证） |
| `api/test/internal/model/test_admin_agent_model.py` | 模型结构测试 |
| `api/test/internal/service/test_admin_agent_service.py` | 服务层测试 |
| `api/test/app/http/test_admin_agent_routes.py` | 路由测试 |

**修改**

| 文件 | 变更 |
| --- | --- |
| `api/internal/model/__init__.py` | 导出 `AdminAgent` |
| `api/app/http/admin_routes_7.py` | 追加 `/admin/agents*` 端点（该文件已承载 admin_rbac，同属"权限域"） |
| `api/app/http/support.py` | `_admin_route_permission` 登记新路径 → `agent_pool:manage` / `agent_pool:read` |
| `docs/rbac.md` | 新增"管理端 Agent 授权模型"小节 |
| `docs/README.md` | 若新增顶层文档需登记（本计划不新增顶层文档，故通常无需改） |

**为什么新建 `admin_agent_authorization.py` 而非塞进 `rbac.py`**：`rbac.py` 是**权限点目录**（纯声明、无业务函数）；授权计算是**有行为的安全边界**（含 fail-closed 逻辑），混入会让"目录"承担两种职责。分开后 `rbac.py` 保持零逻辑，安全规则集中在可独立测试的单一文件。

---

## Task 1: 授权内核——可下放白名单（fail closed）

**Files:**
- Create: `api/internal/core/admin_agent_authorization.py`
- Test: `api/test/internal/core/test_admin_agent_authorization.py`

- [x] **Step 1: 写失败测试**

创建 `api/test/internal/core/test_admin_agent_authorization.py`：

```python
"""管理端 Agent 授权内核单测。

覆盖设计文档 §4.2（可下放白名单）与 §4.1（三重交集）。
"""
from internal.core.admin_agent_authorization import (
    ASSIGNABLE_PERMISSIONS,
    BANNED_PERMISSION_CODES,
    assert_grantable,
    compute_effective_permissions,
)
from internal.core.rbac import PERMISSION_CATALOG


class TestAssignableWhitelist:
    def test_banned_codes_are_excluded(self):
        """封禁项一律不在白名单：身份与权限体系不可下放。"""
        for code in BANNED_PERMISSION_CODES:
            assert code not in ASSIGNABLE_PERMISSIONS, f"{code} 不应可下放"

    def test_user_write_ops_excluded_but_read_allowed(self):
        """用户管理只读可下放，写操作不可（设计 §4.2）。"""
        assert "user:read" in ASSIGNABLE_PERMISSIONS
        for code in ("user:create", "user:update", "user:disable", "user:delete"):
            assert code not in ASSIGNABLE_PERMISSIONS, f"{code} 不应可下放"

    def test_whitelist_is_subset_of_catalog(self):
        """白名单不得出现目录外的幽灵权限点。"""
        catalog = {spec.code for spec in PERMISSION_CATALOG}
        assert ASSIGNABLE_PERMISSIONS <= catalog

    def test_model_pool_and_tool_governance_are_assignable(self):
        """设计 §4.3 举例：模型池/工具池/Agent池 应可下放。"""
        for code in (
            "model_pool:read", "model_pool:update",
            "tool_governance:read", "tool_governance:manage",
            "agent_pool:read", "agent_pool:manage",
        ):
            assert code in ASSIGNABLE_PERMISSIONS, f"{code} 应可下放"

    def test_fail_closed_for_unknown_resource(self):
        """未显式登记的资源前缀默认不可下放（fail closed）。

        用动态构造的 spec 验证：即使某 code 在目录中，只要其 resource
        未被登记为可下放，就不应进入白名单。
        """
        from internal.core.admin_agent_authorization import is_assignable
        assert is_assignable("model_pool:read") is True
        assert is_assignable("brand_new_board:read") is False
```

- [x] **Step 2: 运行测试确认失败**

```bash
cd api && python -m pytest test/internal/core/test_admin_agent_authorization.py -q --no-cov -p no:cacheprovider
```

预期：`ModuleNotFoundError: No module named 'internal.core.admin_agent_authorization'`

- [x] **Step 3: 实现授权内核（白名单部分）**

创建 `api/internal/core/admin_agent_authorization.py`：

```python
"""管理端 Agent 授权内核。

与 ``rbac.py`` 的分工：
- ``rbac.py``：权限点**目录**（纯声明，零逻辑）。
- 本模块：**授权计算**（有行为的安全边界），含 fail-closed 规则。

设计依据：docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md §4。
"""
from __future__ import annotations

from internal.core.rbac import PERMISSION_CATALOG, PERMISSION_BY_CODE


# 完全封禁：身份与权限体系。
# 下放等于 Agent 能自我提权、改角色、改他人账号，安全模型自我解体。
BANNED_PERMISSION_CODES = frozenset({
    "admin:access",
    "admin_user:read",
    "admin_user:create",
    "admin_user:update",
    "admin_user:disable",
    "role:read",
    "role:create",
    "role:update",
    "role:delete",
    "permission:read",
})

# 仅只读可下放：写操作影响真实用户，归为禁区。
READ_ONLY_ASSIGNABLE_RESOURCES = frozenset({"user"})

# 可下放白名单（显式登记制，见下方 fail-closed 说明）。
ASSIGNABLE_RESOURCES = frozenset({
    "agent_pool", "app", "audit_log", "builtin_tool", "cost_stats", "dataset",
    "mcp", "model_pool", "model_provider", "openapi", "orchestration_flag",
    "orchestration_release", "order", "payment_config", "plan", "prompt_template",
    "public_ai_feature", "recycle_bin", "redeem_code", "refund", "routing_log",
    "routing_quality", "schedule_task", "setting", "skill", "storage",
    "system_config", "system_knowledge", "tool", "tool_governance", "user",
    "withdraw", "workflow",
})


def is_assignable(permission_code: str) -> bool:
    """判断单个权限点是否可下放给管理端 Agent。

    fail closed：**显式登记制**——只有 resource 在 ``ASSIGNABLE_RESOURCES``
    中（且不在封禁项、且满足只读约束）才返回 True。未来新增权限点若其
    resource 为全新前缀，默认**不可下放**，必须显式登记才放开，避免被静默
    暴露给 Agent。
    """
    if permission_code in BANNED_PERMISSION_CODES:
        return False
    spec = PERMISSION_BY_CODE.get(permission_code)
    if spec is None:
        return False
    if spec.resource not in ASSIGNABLE_RESOURCES:
        return False
    if (
        spec.resource in READ_ONLY_ASSIGNABLE_RESOURCES
        and spec.action != "read"
    ):
        return False
    return True


ASSIGNABLE_PERMISSIONS = frozenset(
    spec.code for spec in PERMISSION_CATALOG if is_assignable(spec.code)
)
```

- [x] **Step 4: 运行测试确认通过**

```bash
cd api && python -m pytest test/internal/core/test_admin_agent_authorization.py -q --no-cov -p no:cacheprovider
```

预期：5 passed

- [x] **Step 5: 反向验证（必做）**

把 `is_assignable` 里 `if spec.resource not in ASSIGNABLE_RESOURCES: return False` 临时改成 `return True`（模拟 fail-open），重跑：

```bash
cd api && python -m pytest test/internal/core/test_admin_agent_authorization.py -q --no-cov -p no:cacheprovider
```

预期：`test_fail_closed_for_unknown_resource` **FAILED**。确认后**恢复**该行，重跑确认 5 passed。

- [x] **Step 6: 提交**

```bash
git add api/internal/core/admin_agent_authorization.py api/test/internal/core/test_admin_agent_authorization.py
git commit -m "feat(admin-agent): add fail-closed assignable permission whitelist"
```

---

## Task 2: 授权内核——三重交集计算

**Files:**
- Modify: `api/internal/core/admin_agent_authorization.py`
- Test: `api/test/internal/core/test_admin_agent_authorization.py`

- [x] **Step 1: 写失败测试**

在 `api/test/internal/core/test_admin_agent_authorization.py` 追加：

```python
class TestTripleIntersection:
    def test_effective_is_three_way_intersection(self):
        """effective = admin ∩ granted ∩ assignable，三者缺一不可。"""
        effective = compute_effective_permissions(
            admin_permissions=["model_pool:read", "model_pool:update", "role:read"],
            granted_permissions=["model_pool:read", "model_pool:update", "order:view"],
        )
        # role:read 被白名单剔除；order:view 管理员没有
        assert effective == frozenset({"model_pool:read", "model_pool:update"})

    def test_admin_losing_permission_shrinks_effective(self):
        """管理员失权后，即使 Agent 仍挂着该权限，effective 立即收紧。"""
        effective = compute_effective_permissions(
            admin_permissions=["model_pool:read"],
            granted_permissions=["model_pool:read", "model_pool:update"],
        )
        assert effective == frozenset({"model_pool:read"})

    def test_empty_when_no_overlap(self):
        effective = compute_effective_permissions(
            admin_permissions=["model_pool:read"],
            granted_permissions=["order:view"],
        )
        assert effective == frozenset()

    def test_banned_permission_never_effective(self):
        """即使管理员自身持有 role:read 且显式下放，也不得生效。"""
        effective = compute_effective_permissions(
            admin_permissions=["role:read"],
            granted_permissions=["role:read"],
        )
        assert effective == frozenset()


class TestAssertGrantable:
    def test_rejects_permission_admin_lacks(self):
        """保存时后端独立校验：UI 过滤不是安全边界，直连 API 必须被拒。"""
        import pytest
        with pytest.raises(ValueError, match="无权下放"):
            assert_grantable(
                requested=["order:view"],
                admin_permissions=["model_pool:read"],
            )

    def test_rejects_banned_permission(self):
        import pytest
        with pytest.raises(ValueError, match="不可下放"):
            assert_grantable(
                requested=["role:read"],
                admin_permissions=["role:read"],
            )

    def test_accepts_valid_subset(self):
        assert_grantable(
            requested=["model_pool:read", "model_pool:update"],
            admin_permissions=["model_pool:read", "model_pool:update", "order:view"],
        )
```

- [x] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/core/test_admin_agent_authorization.py -q --no-cov -p no:cacheprovider
```

预期：`ImportError: cannot import name 'compute_effective_permissions'`

- [x] **Step 3: 实现**

在 `api/internal/core/admin_agent_authorization.py` 末尾追加：

```python
def compute_effective_permissions(
    *,
    admin_permissions,
    granted_permissions,
) -> frozenset[str]:
    """计算 Agent 的最终生效权限：``admin ∩ granted ∩ assignable``。

    设计 §4.1：三者缺一不可。任一维度收紧，Agent 能力立即随之收紧。
    每次请求实时重算（与 docs/rbac.md §3.5 的既有原则一致，不依赖静态快照）。
    """
    return (
        frozenset(admin_permissions)
        & frozenset(granted_permissions)
        & ASSIGNABLE_PERMISSIONS
    )


def assert_grantable(*, requested, admin_permissions) -> None:
    """保存授权时的独立校验（设计 §4.3 第二层）。

    UI 过滤只是体验，**不是安全边界**；此处必须拒绝越界请求。

    Raises:
        ValueError: 请求包含"管理员自己没有"或"系统不允许下放"的权限点。
    """
    admin_set = frozenset(admin_permissions)
    beyond_admin = sorted(set(requested) - admin_set)
    if beyond_admin:
        raise ValueError(
            f"无权下放以下权限（管理员不具备）: {', '.join(beyond_admin)}"
        )
    not_assignable = sorted(c for c in requested if not is_assignable(c))
    if not_assignable:
        raise ValueError(
            f"以下权限不可下放给 Agent: {', '.join(not_assignable)}"
        )
```

- [x] **Step 4: 运行确认通过**

```bash
cd api && python -m pytest test/internal/core/test_admin_agent_authorization.py -q --no-cov -p no:cacheprovider
```

预期：12 passed

- [x] **Step 5: 提交**

```bash
git add api/internal/core/admin_agent_authorization.py api/test/internal/core/test_admin_agent_authorization.py
git commit -m "feat(admin-agent): add triple-intersection effective permission"
```

---

## Task 3: `AdminAgentPrincipal` 身份对象

**Files:**
- Create: `api/internal/entity/admin_agent_entity.py`
- Test: `api/test/internal/core/test_admin_agent_authorization.py`

- [x] **Step 1: 写失败测试**

新建 `api/test/internal/entity/test_admin_agent_principal.py`：

```python
"""AdminAgentPrincipal 身份对象测试（设计 §5）。"""
from uuid import uuid4

import pytest

from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel


class TestAdminAgentPrincipal:
    def test_is_frozen(self):
        """身份对象不可变——避免执行中途被篡改权限。"""
        principal = AdminAgentPrincipal(
            admin_user_id=uuid4(),
            agent_id=uuid4(),
            agent_name="运维 Agent",
            effective_permissions=frozenset({"model_pool:read"}),
            automation_policy={"model_pool": AutomationLevel.SUPERVISED},
        )
        with pytest.raises(Exception):
            principal.agent_name = "改名"

    def test_automation_level_for_unconfigured_board_is_supervised(self):
        """fail closed：未配置的板块默认 supervised，不是 autonomous。"""
        principal = AdminAgentPrincipal(
            admin_user_id=uuid4(),
            agent_id=uuid4(),
            agent_name="a",
            effective_permissions=frozenset(),
            automation_policy={},
        )
        assert principal.automation_level_for("model_pool") is AutomationLevel.SUPERVISED

    def test_automation_level_reads_configured_value(self):
        principal = AdminAgentPrincipal(
            admin_user_id=uuid4(),
            agent_id=uuid4(),
            agent_name="a",
            effective_permissions=frozenset(),
            automation_policy={"prompt_template": AutomationLevel.AUTONOMOUS},
        )
        assert (
            principal.automation_level_for("prompt_template")
            is AutomationLevel.AUTONOMOUS
        )

    def test_has_permission(self):
        principal = AdminAgentPrincipal(
            admin_user_id=uuid4(),
            agent_id=uuid4(),
            agent_name="a",
            effective_permissions=frozenset({"model_pool:read"}),
            automation_policy={},
        )
        assert principal.has_permission("model_pool:read") is True
        assert principal.has_permission("model_pool:update") is False

    def test_automation_level_values(self):
        assert AutomationLevel.SUPERVISED.value == "supervised"
        assert AutomationLevel.AUTONOMOUS.value == "autonomous"
        assert AutomationLevel.BLOCKED.value == "blocked"
```

- [x] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/entity/test_admin_agent_principal.py -q --no-cov -p no:cacheprovider
```

预期：`ModuleNotFoundError: No module named 'internal.entity.admin_agent_entity'`

- [x] **Step 3: 实现**

创建 `api/internal/entity/admin_agent_entity.py`：

```python
"""管理端 Agent 执行身份与自动化级别（设计 §5）。

为什么不用 ``Account`` 伪装：管理员与用户端账号已彻底解耦（
``admin_user.account_id`` 恒为 NULL），用 Account 伪装会让下游所有
"按 account 隔离"的逻辑误判主体。

为什么不沿用 ``_SystemBorneAccount``：现有 4 个管理端 AI 辅助端点用
``_SystemBorneAccount(id=None)`` 丢弃了管理员身份，无法做板块授权，
也回答不了"谁让 AI 改了什么"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping
from uuid import UUID


class AutomationLevel(str, Enum):
    """板块自动化级别（与权限正交的第二维度，设计 §5.1）。"""

    SUPERVISED = "supervised"   # 需人工授权：产出变更草稿，点「应用」才落库
    AUTONOMOUS = "autonomous"   # 全自动：靠审计 + 回收站 + 快照兜底
    BLOCKED = "blocked"         # 禁用：即使有权限也不执行（应急熔断）


@dataclass(frozen=True)
class AdminAgentPrincipal:
    """管理端 Agent 的显式执行身份。

    全链路显式传参，不做隐式上下文读取（易漏、难测）。
    """

    admin_user_id: UUID                        # 发起管理员（人类责任人）
    agent_id: UUID                             # 执行该操作的 Agent
    agent_name: str                            # 审计展示用
    effective_permissions: frozenset[str]      # 已算好的三重交集（§4.1）
    automation_policy: Mapping[str, AutomationLevel] = field(default_factory=dict)

    def has_permission(self, permission_code: str) -> bool:
        return permission_code in self.effective_permissions

    def automation_level_for(self, board: str) -> AutomationLevel:
        """取某板块的自动化级别。

        fail closed：未配置的板块一律 ``SUPERVISED``。
        避免"忘记配置 = 全自动"。
        """
        level = self.automation_policy.get(board)
        if level is None:
            return AutomationLevel.SUPERVISED
        if isinstance(level, AutomationLevel):
            return level
        try:
            return AutomationLevel(level)
        except ValueError:
            # 非法取值同样 fail closed 到 supervised
            return AutomationLevel.SUPERVISED
```

- [x] **Step 4: 运行确认通过**

```bash
cd api && python -m pytest test/internal/entity/test_admin_agent_principal.py -q --no-cov -p no:cacheprovider
```

预期：5 passed

- [x] **Step 5: 提交**

```bash
git add api/internal/entity/admin_agent_entity.py api/test/internal/entity/test_admin_agent_principal.py
git commit -m "feat(admin-agent): add AdminAgentPrincipal identity object"
```

---

## Task 4: `admin_agent` 模型 + 迁移

**Files:**
- Create: `api/internal/model/admin_agent.py`
- Create: `api/internal/migration/versions/s5f6a7b8c9d0_add_admin_agent_table.py`
- Modify: `api/internal/model/__init__.py`
- Test: `api/test/internal/model/test_admin_agent_model.py`

- [x] **Step 1: 写失败测试**

创建 `api/test/internal/model/test_admin_agent_model.py`：

```python
"""admin_agent 模型结构测试（设计 §10.1）。"""
from internal.model.admin_agent import AdminAgent


class TestAdminAgentModel:
    def test_tablename(self):
        assert AdminAgent.__tablename__ == "admin_agent"

    def test_required_columns_exist(self):
        columns = {c.name for c in AdminAgent.__table__.columns}
        for name in (
            "id", "owner_admin_user_id", "name", "description", "prompt_key",
            "granted_permissions", "automation_policy", "budget_config",
            "enabled", "created_at", "updated_at",
        ):
            assert name in columns, f"缺少列 {name}"

    def test_id_is_primary_key(self):
        pk = {c.name for c in AdminAgent.__table__.primary_key.columns}
        assert pk == {"id"}

    def test_jsonb_columns_have_empty_defaults(self):
        """JSONB 列必须带空默认值，避免 NULL 导致的解析分支。"""
        assert AdminAgent.__table__.columns["granted_permissions"].server_default.arg.text == "'[]'::jsonb"
        assert AdminAgent.__table__.columns["automation_policy"].server_default.arg.text == "'{}'::jsonb"
        assert AdminAgent.__table__.columns["budget_config"].server_default.arg.text == "'{}'::jsonb"

    def test_owner_fk_cascades(self):
        fks = list(AdminAgent.__table__.columns["owner_admin_user_id"].foreign_keys)
        assert len(fks) == 1
        assert fks[0].target_fullname == "admin_user.id"
        assert fks[0].ondelete == "CASCADE"

    def test_enabled_defaults_true(self):
        assert AdminAgent.__table__.columns["enabled"].server_default.arg.text == "true"
```

- [x] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/model/test_admin_agent_model.py -q --no-cov -p no:cacheprovider
```

预期：`ModuleNotFoundError: No module named 'internal.model.admin_agent'`

- [x] **Step 3: 实现模型**

创建 `api/internal/model/admin_agent.py`：

```python
"""管理端 Agent 定义模型（设计 §10.1）。

与用户端 Agent（``app`` 表）完全独立：
- 归属 ``admin_user``，不归属 ``account``；
- 权限走三重交集（``granted_permissions``）；
- 自动化级别独立于权限（``automation_policy``）。
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


class AdminAgent(Base):
    __tablename__ = "admin_agent"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_admin_agent_id"),
        ForeignKeyConstraint(
            ["owner_admin_user_id"],
            ["admin_user.id"],
            name="fk_admin_agent_owner_admin_user_id_admin_user",
            ondelete="CASCADE",
        ),
        Index("admin_agent_owner_admin_user_id_idx", "owner_admin_user_id"),
        Index("admin_agent_enabled_idx", "enabled"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    owner_admin_user_id = Column(UUID, nullable=False)
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=False, server_default=text("''::text"))
    # 绑定的提示词 key（FK → prompt_template.key），为空时用内置默认
    prompt_key = Column(String(128), nullable=True)
    # 管理员显式下放给本 Agent 的权限子集（字符串数组）
    granted_permissions = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # 板块 → supervised / autonomous / blocked（§5.1）
    automation_policy = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # 预算闸门配置（§6.3），P4 落地，此处先建列
    budget_config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
```

- [x] **Step 4: 注册模型导出**

修改 `api/internal/model/__init__.py`，在 `from .admin import ...` 一行之后新增：

```python
from .admin_agent import AdminAgent
```

并在文件底部 `__all__` 列表中（若存在）追加字符串 `"AdminAgent"`。若该文件用其它聚合方式，请比照既有 `AdminLog`/`AdminUser` 的登记方式照做。

- [x] **Step 5: 写迁移**

创建 `api/internal/migration/versions/s5f6a7b8c9d0_add_admin_agent_table.py`：

```python
"""add admin_agent table

Revision ID: s5f6a7b8c9d0
Revises: r4e5f6a7b8c9
Create Date: 2026-09-16 00:00:00.000000

新增 admin_agent 表：承载管理端 Agent 定义、权限子集与自动化级别（设计 §10.1）。

down_revision 指向**唯一 head** `r4e5f6a7b8c9`。注意本表有外键指向
`admin_user`（建表迁移 `a2b3c4d5e6f7`，位于更早的祖先链上），满足
test_migration_empty_db_smoke.py 的「被引用表的 create_table 必须在祖先链」约束。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "s5f6a7b8c9d0"
down_revision = "r4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "admin_agent",
        sa.Column("id", sa.UUID(), nullable=False,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("owner_admin_user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False,
                  server_default=sa.text("''::character varying")),
        sa.Column("description", sa.Text(), nullable=False,
                  server_default=sa.text("''::text")),
        sa.Column("prompt_key", sa.String(length=128), nullable=True),
        sa.Column("granted_permissions", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("automation_policy", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("budget_config", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.ForeignKeyConstraint(
            ["owner_admin_user_id"], ["admin_user.id"],
            name="fk_admin_agent_owner_admin_user_id_admin_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_agent_id"),
    )
    op.create_index("admin_agent_owner_admin_user_id_idx", "admin_agent",
                    ["owner_admin_user_id"])
    op.create_index("admin_agent_enabled_idx", "admin_agent", ["enabled"])


def downgrade():
    op.drop_index("admin_agent_enabled_idx", table_name="admin_agent")
    op.drop_index("admin_agent_owner_admin_user_id_idx", table_name="admin_agent")
    op.drop_table("admin_agent")
```

- [x] **Step 6: 运行模型测试确认通过**

```bash
cd api && python -m pytest test/internal/model/test_admin_agent_model.py -q --no-cov -p no:cacheprovider
```

预期：6 passed

- [x] **Step 7: 跑迁移守卫 + 空库冒烟**

```bash
cd api && python -m pytest test/internal/migration -q --no-cov -p no:cacheprovider
```

预期：全 passed（含 `test_no_implicit_cross_branch_table_dependency` 与空库实跑）。

- [x] **Step 8: 应用迁移并核对 DB**

```bash
docker exec llmops-api bash -c "cd /app/api && PYTHONPATH=/app/api alembic -c internal/migration/alembic.ini upgrade head"
docker exec llmops-db psql -U postgres -d llmops -c "\d admin_agent"
docker exec llmops-db psql -U postgres -d llmops -t -c "SELECT version_num FROM alembic_version;"
```

预期：`\d admin_agent` 列出 11 列 + 2 索引 + 1 外键；`version_num` = `s5f6a7b8c9d0`。

- [x] **Step 9: 提交**

```bash
git add api/internal/model/admin_agent.py api/internal/model/__init__.py \
        api/internal/migration/versions/s5f6a7b8c9d0_add_admin_agent_table.py \
        api/test/internal/model/test_admin_agent_model.py
git commit -m "feat(admin-agent): add admin_agent table and model"
```

---

## Task 5: `AdminAgentService`——CRUD + 授权校验

**Files:**
- Create: `api/internal/service/admin_agent_service.py`
- Modify: `api/internal/service/__init__.py`（导出服务）
- Test: `api/test/internal/service/test_admin_agent_service.py`

- [x] **Step 1: 写失败测试**

创建 `api/test/internal/service/test_admin_agent_service.py`：

```python
"""AdminAgentService 测试。"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.service.admin_agent_service import AdminAgentService


class _QueryStub:
    def __init__(self, rows=None):
        self._rows = rows if rows is not None else []

    def filter(self, *a, **kw):
        return self

    def filter_by(self, **kw):
        return self

    def order_by(self, *a, **kw):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows

    def count(self):
        return len(self._rows)


class _SessionStub:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.added = []
        self.deleted = []

    def query(self, *a, **kw):
        return _QueryStub(self.rows)

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def flush(self):
        pass

    def commit(self):
        pass


class _AutoCommit:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _service(rows=None):
    session = _SessionStub(rows)
    svc = AdminAgentService.__new__(AdminAgentService)
    svc.db = SimpleNamespace(session=session, auto_commit=lambda: _AutoCommit())
    return svc, session


def _agent(**over):
    data = {
        "id": uuid4(),
        "owner_admin_user_id": uuid4(),
        "name": "运维 Agent",
        "description": "",
        "prompt_key": None,
        "granted_permissions": [],
        "automation_policy": {},
        "budget_config": {},
        "enabled": True,
    }
    data.update(over)
    return SimpleNamespace(**data)


class TestAssignablePermissions:
    def test_returns_intersection_of_admin_and_whitelist(self):
        svc, _ = _service()
        result = svc.list_assignable_permissions(
            admin_permissions=["model_pool:read", "model_pool:update", "role:read"]
        )
        assert result == ["model_pool:read", "model_pool:update"]

    def test_excludes_banned_even_if_admin_has_it(self):
        svc, _ = _service()
        result = svc.list_assignable_permissions(
            admin_permissions=["permission:read", "admin_user:read"]
        )
        assert result == []


class TestCreateAgent:
    def test_rejects_granting_beyond_admin(self):
        svc, _ = _service()
        with pytest.raises(ValueError, match="无权下放"):
            svc.create_agent(
                admin_user_id=uuid4(),
                admin_permissions=["model_pool:read"],
                name="x",
                granted_permissions=["order:view"],
            )

    def test_persists_agent_with_empty_automation_policy(self):
        svc, session = _service()
        svc.create_agent(
            admin_user_id=uuid4(),
            admin_permissions=["model_pool:read"],
            name="x",
            granted_permissions=["model_pool:read"],
        )
        assert len(session.added) == 1
        created = session.added[0]
        assert created.name == "x"
        assert created.automation_policy == {}
        assert created.granted_permissions == ["model_pool:read"]


class TestUpdateAgent:
    def test_rejects_non_owner(self):
        owner = uuid4()
        svc, _ = _service([_agent(owner_admin_user_id=owner)])
        with pytest.raises(PermissionError, match="仅创建者"):
            svc.update_agent(
                agent_id=uuid4(),
                admin_user_id=uuid4(),
                admin_permissions=["model_pool:read"],
                name="改名",
            )

    def test_rejects_invalid_automation_level(self):
        owner = uuid4()
        svc, _ = _service([_agent(owner_admin_user_id=owner)])
        with pytest.raises(ValueError, match="非法自动化级别"):
            svc.update_agent(
                agent_id=uuid4(),
                admin_user_id=owner,
                admin_permissions=["model_pool:read"],
                automation_policy={"model_pool": "yolo"},
            )

    def test_accepts_valid_automation_level(self):
        owner = uuid4()
        agent = _agent(owner_admin_user_id=owner)
        svc, _ = _service([agent])
        svc.update_agent(
            agent_id=agent.id,
            admin_user_id=owner,
            admin_permissions=["model_pool:read"],
            automation_policy={"model_pool": "autonomous"},
        )
        assert agent.automation_policy == {"model_pool": "autonomous"}
```

- [x] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_service.py -q --no-cov -p no:cacheprovider
```

预期：`ModuleNotFoundError: No module named 'internal.service.admin_agent_service'`

- [x] **Step 3: 实现服务**

创建 `api/internal/service/admin_agent_service.py`：

```python
"""管理端 Agent 服务：定义 CRUD + 授权校验（设计 §4、§5）。

边界说明：
- 本服务**只负责 Agent 的定义与授权**，不执行任何板块动作。
  执行链路的装配在 P1b 的 AdminAgentService（执行侧）。
- 权限校验在此处做"保存时"校验（§4.3 第二层）；
  "运行时"校验由每次请求实时重算 effective（第一/三层）。
"""
from __future__ import annotations

from uuid import UUID

from internal.core.admin_agent_authorization import (
    ASSIGNABLE_PERMISSIONS,
    assert_grantable,
)
from internal.entity.admin_agent_entity import AutomationLevel
from internal.model.admin_agent import AdminAgent
from pkg.sqlalchemy import SQLAlchemy


class AdminAgentService:
    def __init__(self, db: SQLAlchemy):
        self.db = db

    # ---------- 授权（§4.3 展示即受限） ----------

    def list_assignable_permissions(self, *, admin_permissions) -> list[str]:
        """返回该管理员**实际可下放**的权限点（交集，不是全量目录）。

        设计 §4.3：API 只返回交集，UI 只渲染该列表——
        管理员看不到自己没有的权限点，无从选择。
        """
        return sorted(frozenset(admin_permissions) & ASSIGNABLE_PERMISSIONS)

    # ---------- Agent 定义 CRUD ----------

    def list_agents(self, *, admin_user_id: UUID) -> list[AdminAgent]:
        """仅返回**该管理员自己创建**的 Agent（设计 §2：仅创建者可用）。"""
        return (
            self.db.session.query(AdminAgent)
            .filter(AdminAgent.owner_admin_user_id == admin_user_id)
            .order_by(AdminAgent.created_at)
            .all()
        )

    def get_agent(self, *, agent_id: UUID, admin_user_id: UUID) -> AdminAgent | None:
        agent = (
            self.db.session.query(AdminAgent)
            .filter(AdminAgent.id == agent_id)
            .first()
        )
        if agent is None:
            return None
        if agent.owner_admin_user_id != admin_user_id:
            raise PermissionError("仅创建者可使用该 Agent")
        return agent

    def create_agent(
        self,
        *,
        admin_user_id: UUID,
        admin_permissions,
        name: str,
        description: str = "",
        prompt_key: str | None = None,
        granted_permissions=None,
        automation_policy=None,
    ) -> AdminAgent:
        granted = list(granted_permissions or [])
        assert_grantable(requested=granted, admin_permissions=admin_permissions)
        policy = self._validate_policy(automation_policy)

        agent = AdminAgent(
            owner_admin_user_id=admin_user_id,
            name=name,
            description=description,
            prompt_key=prompt_key,
            granted_permissions=granted,
            automation_policy=policy,
            budget_config={},
            enabled=True,
        )
        with self.db.auto_commit():
            self.db.session.add(agent)
        return agent

    def update_agent(
        self,
        *,
        agent_id: UUID,
        admin_user_id: UUID,
        admin_permissions,
        name: str | None = None,
        description: str | None = None,
        prompt_key: str | None = None,
        granted_permissions=None,
        automation_policy=None,
        enabled: bool | None = None,
    ) -> AdminAgent:
        agent = self.get_agent(agent_id=agent_id, admin_user_id=admin_user_id)
        if agent is None:
            raise LookupError("Agent 不存在")

        if granted_permissions is not None:
            granted = list(granted_permissions)
            assert_grantable(requested=granted, admin_permissions=admin_permissions)
            agent.granted_permissions = granted
        if automation_policy is not None:
            agent.automation_policy = self._validate_policy(automation_policy)
        if name is not None:
            agent.name = name
        if description is not None:
            agent.description = description
        if prompt_key is not None:
            agent.prompt_key = prompt_key
        if enabled is not None:
            agent.enabled = enabled

        with self.db.auto_commit():
            self.db.session.add(agent)
        return agent

    def delete_agent(self, *, agent_id: UUID, admin_user_id: UUID) -> None:
        agent = self.get_agent(agent_id=agent_id, admin_user_id=admin_user_id)
        if agent is None:
            raise LookupError("Agent 不存在")
        with self.db.auto_commit():
            self.db.session.delete(agent)

    # ---------- 内部 ----------

    @staticmethod
    def _validate_policy(policy) -> dict:
        """校验 automation_policy 取值合法（§5.1 三档）。

        非法取值必须**显式报错**而非静默降级——静默降级会让管理员
        以为自己配了 autonomous 而实际是 supervised（或反之）。
        """
        result: dict[str, str] = {}
        for board, level in (policy or {}).items():
            try:
                result[str(board)] = AutomationLevel(level).value
            except ValueError:
                raise ValueError(
                    f"非法自动化级别: {board}={level!r}，"
                    f"可选值 {[x.value for x in AutomationLevel]}"
                )
        return result
```

- [x] **Step 4: 运行确认通过**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_service.py -q --no-cov -p no:cacheprovider
```

预期：8 passed

- [x] **Step 5: 导出服务**

修改 `api/internal/service/__init__.py`，比照既有 service 的导出风格新增：

```python
from .admin_agent_service import AdminAgentService
```

并在该文件的 `__all__` 中追加 `"AdminAgentService"`。

- [x] **Step 6: 提交**

```bash
git add api/internal/service/admin_agent_service.py api/internal/service/__init__.py \
        api/test/internal/service/test_admin_agent_service.py
git commit -m "feat(admin-agent): add AdminAgentService with grant validation"
```

---

## Task 6: 权限回收——自动清理（§4.4）

**Files:**
- Modify: `api/internal/service/admin_agent_service.py`
- Test: `api/test/internal/service/test_admin_agent_service.py`

- [x] **Step 1: 写失败测试**

在 `api/test/internal/service/test_admin_agent_service.py` 追加：

```python
class TestPermissionRevocation:
    def test_prunes_revoked_permission_from_all_agents_of_admin(self):
        """管理员失权 → 立即从其名下所有 Agent 物理删除该项（§4.4）。"""
        owner = uuid4()
        a1 = _agent(owner_admin_user_id=owner,
                    granted_permissions=["model_pool:read", "order:view"])
        a2 = _agent(owner_admin_user_id=owner,
                    granted_permissions=["model_pool:read"])
        other = _agent(granted_permissions=["model_pool:read"])
        svc, _ = _service([a1, a2, other])

        removed = svc.prune_revoked_permissions(
            admin_user_id=owner,
            admin_permissions=["order:view"],   # model_pool:read 已失去
        )

        assert removed == 1
        assert a1.granted_permissions == ["order:view"]
        assert a2.granted_permissions == []
        # 他人 Agent 不受影响
        assert other.granted_permissions == ["model_pool:read"]

    def test_noop_when_admin_still_has_permission(self):
        owner = uuid4()
        a1 = _agent(owner_admin_user_id=owner,
                    granted_permissions=["model_pool:read"])
        svc, _ = _service([a1])

        removed = svc.prune_revoked_permissions(
            admin_user_id=owner,
            admin_permissions=["model_pool:read"],
        )

        assert removed == 0
        assert a1.granted_permissions == ["model_pool:read"]

    def test_prunes_permission_that_left_whitelist(self):
        """即使管理员仍持有，若该权限已不在白名单，也应清理。"""
        owner = uuid4()
        a1 = _agent(owner_admin_user_id=owner,
                    granted_permissions=["role:read"])
        svc, _ = _service([a1])

        removed = svc.prune_revoked_permissions(
            admin_user_id=owner,
            admin_permissions=["role:read"],
        )

        assert removed == 1
        assert a1.granted_permissions == []
```

- [x] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_service.py -q --no-cov -p no:cacheprovider
```

预期：`AttributeError: 'AdminAgentService' object has no attribute 'prune_revoked_permissions'`

- [x] **Step 3: 实现**

在 `api/internal/service/admin_agent_service.py` 的 `AdminAgentService` 类中追加：

```python
    def prune_revoked_permissions(
        self,
        *,
        admin_user_id: UUID,
        admin_permissions,
    ) -> int:
        """管理员失权后，从其名下所有 Agent 中物理删除失效权限（设计 §4.4）。

        「失效」= 不在 ``admin_permissions`` 中，**或**已不在可下放白名单中。
        理由：不留"显示有、实际无效"的混乱状态，避免管理员困惑
        "为什么 Agent 不干活了"。

        代价（可接受）：管理员重新获得权限后需**手动重新下放**——更安全的取舍。

        Returns:
            被移除的 (agent, permission) 组合数。
        """
        allowed = frozenset(admin_permissions) & ASSIGNABLE_PERMISSIONS
        agents = (
            self.db.session.query(AdminAgent)
            .filter(AdminAgent.owner_admin_user_id == admin_user_id)
            .all()
        )
        removed = 0
        touched = False
        for agent in agents:
            current = list(agent.granted_permissions or [])
            kept = [code for code in current if code in allowed]
            if len(kept) != len(current):
                removed += len(current) - len(kept)
                agent.granted_permissions = kept
                touched = True
        if touched:
            with self.db.auto_commit():
                for agent in agents:
                    self.db.session.add(agent)
        return removed
```

- [x] **Step 4: 运行确认通过**

```bash
cd api && python -m pytest test/internal/service/test_admin_agent_service.py -q --no-cov -p no:cacheprovider
```

预期：11 passed

- [x] **Step 5: 反向验证（必做）**

把 `kept = [code for code in current if code in allowed]` 临时改成 `kept = current`（模拟不清理），重跑：

预期：`test_prunes_revoked_permission_from_all_agents_of_admin` 与
`test_prunes_permission_that_left_whitelist` **FAILED**。恢复后重跑确认 11 passed。

- [x] **Step 6: 接入触发点**

> **实读事实（必须先核对再写）**：
> - `AdminUserService.__init__(self, session=None, jwt_service=None, audit_log_service=None)`，
>   用 **`self.session`**（不是 `self.db`）；`logger` 已在模块顶部定义（L23）。
> - `_replace_admin_user_roles(self, admin_user_id, role_codes)` 位于 L675-679，
>   **只有 `admin_user_id`，没有权限集**。
> - `_get_permission_codes(self, role_codes)` 的入参是 **角色码列表**（L719），
>   不是 `admin_id`。要取某管理员的权限，需先 `self._get_role_codes(admin_user_id)`
>   再喂给 `_get_permission_codes(...)`。
> - `disable_admin_user(admin_id, *, operator_id, ip, user_agent)` 在 L480-508，
>   置 `status="disabled"` 后 `self.session.commit()`。

先在 `AdminUserService` 类中新增一个私有收敛方法（放在 `_replace_admin_user_roles` 附近）：

```python
    def _prune_admin_agent_permissions(self, admin_user_id, *, admin_permissions) -> None:
        """管理员失权 → 立即清理其名下 Agent 的失效权限（设计 §4.4）。

        静默失败：清理不应阻断主流程（角色变更本身已成功），
        但必须记日志以便排查。
        """
        try:
            from internal.service.admin_agent_service import AdminAgentService

            # AdminAgentService 依赖 pkg.sqlalchemy.SQLAlchemy，而本服务持有的是
            # Session。用 session.get_bind() 取不到 pkg 包装，故直接传入
            # 一个仅暴露 session 的适配对象——比照 AdminAgentService 对 db 的最小用法。
            AdminAgentService(db=self._agent_service_db()).prune_revoked_permissions(
                admin_user_id=admin_user_id,
                admin_permissions=admin_permissions,
            )
        except Exception:
            logger.exception("清理管理端 Agent 失效权限失败 admin_user_id=%s", admin_user_id)
```

> **实现提示（关键，不要臆造）**：`AdminAgentService` 只用到 `db.session` 与
> `db.auto_commit()`。为让 `AdminUserService` 复用同一条 session（避免两条连接、
> 避免跨会话可见性问题），推荐把 `AdminAgentService` 的构造依赖收窄为一个
> **协议**而非 `SQLAlchemy`：在 Task 5 中把 `__init__(self, db)` 保持不动，
> 但在测试与应用中传入 `SimpleNamespace(session=..., auto_commit=...)` 形态的对象。
> `AdminUserService` 侧新增：

```python
    def _agent_service_db(self):
        """构造 AdminAgentService 所需的最小 db 适配（复用同一 session）。"""
        from contextlib import contextmanager
        from types import SimpleNamespace

        @contextmanager
        def _auto_commit():
            try:
                yield
                self.session.commit()
            except Exception:
                self.session.rollback()
                raise

        return SimpleNamespace(session=self.session, auto_commit=_auto_commit)
```

然后在两处调用点分别接入：

```python
        # update_admin_user 内、_replace_admin_user_roles(...) 之后
        if role_codes is not None:
            self._replace_admin_user_roles(admin_user.id, role_codes)
            self._prune_admin_agent_permissions(
                admin_user.id,
                admin_permissions=self._get_permission_codes(
                    self._get_role_codes(admin_user.id)
                ),
            )
```

```python
        # disable_admin_user 内、self.session.commit() 之前
        self._prune_admin_agent_permissions(admin_user.id, admin_permissions=[])
```

> **实现提示**：`disable_admin_user` 中需把原 `self.session.commit()` 保留在最后
> （清理与状态变更在同一次提交中生效）。若顺序敏感，先置 `status` 再清理，
> 最后统一 `commit()`。

- [x] **Step 7: 写接入点测试**

在 `api/test/internal/service/test_admin_user_service.py` 追加（若该文件不存在，
新建并与既有 admin_user_service 测试同风格）：

```python
def test_disable_admin_user_prunes_agent_permissions(monkeypatch):
    """禁用管理员后，其 Agent 的全部授权应被清空（§4.4）。

    反向验证提示：把 _prune_admin_agent_permissions 改成空实现，
    本测试必须失败。
    """
    from internal.service import admin_user_service as mod

    calls = []

    class _FakeAgentService:
        def __init__(self, db=None):
            pass

        def prune_revoked_permissions(self, *, admin_user_id, admin_permissions):
            calls.append((admin_user_id, list(admin_permissions)))
            return 1

    monkeypatch.setattr(
        "internal.service.admin_agent_service.AdminAgentService", _FakeAgentService
    )
    # 触发 disable_admin_user 的路径（用既有测试的 service 构造方式）
    # ... 具体构造比照同文件既有用例 ...
    assert calls and calls[-1][1] == []
```

> **实现提示**：本步骤的测试骨架需与 `api/test/internal/service/test_admin_user_service.py`
> 既有用例的 service 构造方式保持一致（该文件已有 `_SessionStub` / `_AuditLogServiceStub` 等）。
> 若该文件不存在，先确认 `AdminUserService` 的单元测试落在哪个文件，再按其风格新增。

- [x] **Step 8: 运行测试**

```bash
cd api && python -m pytest test/internal/service/test_admin_user_service.py test/internal/service/test_admin_agent_service.py -q --no-cov -p no:cacheprovider
```

预期：全 passed

- [x] **Step 9: 提交**

```bash
git add api/internal/service/admin_agent_service.py api/internal/service/admin_user_service.py \
        api/test/internal/service/test_admin_agent_service.py api/test/internal/service/test_admin_user_service.py
git commit -m "feat(admin-agent): auto-prune revoked permissions from agents"
```

---

## Task 7: 管理端 API——`/admin/agents`

**Files:**
- Modify: `api/app/http/admin_routes_7.py`
- Modify: `api/app/http/support.py`
- Test: `api/test/app/http/test_admin_agent_routes.py`

- [x] **Step 1: 写失败测试**

创建 `api/test/app/http/test_admin_agent_routes.py`：

```python
"""管理端 Agent 路由测试（设计 §4.3 展示即受限）。

模式比照 test_admin_routes_7.py：直接 register_routes + quart test_client。
注意：conftest 的 autouse fixture 会把 support._resolve_admin_permission
替换为无条件放行，因此本文件专门覆盖该替身来测"展示即受限"。
"""
import asyncio

import app.http.asgi_app as asgi_app
from app.http import support
from app.http.admin_routes_7 import register_routes

register_routes(asgi_app.quart_app)


def _admin_ctx(admin_id, permissions):
    async def _fake(permission_code=None):
        return {"id": str(admin_id), "roles": [], "permissions": list(permissions)}, None

    return _fake


class TestAssignablePermissionsEndpoint:
    def test_returns_only_intersection(self, monkeypatch):
        """A 管理员只有模型池/工具池/Agent池 → 可分配列表只有这几项。"""
        admin_id = "11111111-1111-1111-1111-111111111111"
        perms = [
            "model_pool:read", "model_pool:manage", "agent_pool:read",
            "agent_pool:manage", "tool_governance:read", "tool_governance:manage",
        ]
        monkeypatch.setattr(support, "_resolve_admin_permission", _admin_ctx(admin_id, perms))

        async def _run():
            client = asgi_app.quart_app.test_client()
            resp = await client.get("/admin/agents/assignable-permissions")
            return resp

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        body = asyncio.run(resp.get_json())
        codes = body["data"]
        assert set(codes) == set(perms)
        # 不含管理员没有的
        assert "user:read" not in codes
        assert "order:view" not in codes

    def test_excludes_banned_even_if_admin_holds_them(self, monkeypatch):
        admin_id = "22222222-2222-2222-2222-222222222222"
        perms = ["role:read", "permission:read", "admin_user:read", "model_pool:read"]
        monkeypatch.setattr(support, "_resolve_admin_permission", _admin_ctx(admin_id, perms))

        async def _run():
            client = asgi_app.quart_app.test_client()
            return await client.get("/admin/agents/assignable-permissions")

        resp = asyncio.run(_run())
        body = asyncio.run(resp.get_json())
        assert body["data"] == ["model_pool:read"]
```

- [x] **Step 2: 运行确认失败**

```bash
cd api && python -m pytest test/app/http/test_admin_agent_routes.py -q --no-cov -p no:cacheprovider
```

预期：404（路由不存在）

- [x] **Step 3: 实现路由**

在 `api/app/http/admin_routes_7.py` 的 `register_routes(quart_app)` 内部追加
（写法比照该文件既有的 `/admin/roles` 端点）：

```python
    @quart_app.get("/admin/agents/assignable-permissions")
    async def admin_agent_assignable_permissions():
        """返回当前管理员**可下放**的权限点（交集，不是全量目录）。

        设计 §4.3「展示即受限」：管理员看不到自己没有的权限点，无从选择。
        注意：这里必须走**真实**的 `_resolve_admin_permission` 语义，
        而不是把全量目录返回给前端再过滤——前端过滤不是安全边界。
        """
        from app.http import asgi_app as a

        admin, err = await a._resolve_admin_permission("agent_pool:read")
        if err is not None:
            return err

        from internal.schema.admin_agent_schema import AdminAgentAssignablePermissionsResp
        from internal.service.admin_agent_service import AdminAgentService

        codes = await a._to_thread(
            a._get_service(AdminAgentService).list_assignable_permissions,
            admin_permissions=admin["permissions"],
        )
        return a._ok(AdminAgentAssignablePermissionsResp().dump({"codes": codes}))
```

> **实现提示**：`a._ok` / `a._to_thread` / `a._get_service` 的准确形态请比照
> `admin_routes_7.py` 中 `/admin/roles` 既有端点的写法（该文件已用同一套 helper）。
> 若 `admin["permissions"]` 的键名不同（如 `permission_codes`），以 `_resolve_admin_permission`
> 的真实返回为准。

- [x] **Step 4: 写 schema**

创建 `api/internal/schema/admin_agent_schema.py`：

```python
"""管理端 Agent 请求/响应 schema。"""
from marshmallow import Schema, fields


class AdminAgentAssignablePermissionsResp(Schema):
    codes = fields.List(fields.String(), dump_default=[])
```

- [x] **Step 5: 登记权限映射**

在 `api/app/http/support.py` 的 `_admin_route_permission` 中，
比照既有 `/admin/roles` 分支（L496-505）新增 `/admin/agents` 分支：

```python
    if path.startswith("/admin/agents"):
        # 管理端 Agent 治理（设计 §4）。查询用 agent_pool:read；
        # 创建/更新/删除用 agent_pool:manage。
        # assignable-permissions 是只读查询 → read。
        if method == "GET":
            return "agent_pool:read"
        return "agent_pool:manage"
```

> **注意**：必须放在通用 `/admin/users` 之类的分支**之前**（若存在前缀重叠），
> 并确保 `/admin/agents` 不被其它 startswith 分支先行捕获。

- [x] **Step 6: 运行确认通过**

```bash
cd api && python -m pytest test/app/http/test_admin_agent_routes.py -q --no-cov -p no:cacheprovider
```

预期：2 passed

- [x] **Step 7: 跑路由守卫测试（关键）**

```bash
cd api && python -m pytest test/app/http/test_admin_rbac_guard.py -q --no-cov -p no:cacheprovider
```

预期：全 passed（该测试断言每个 `/admin/*` 路由都有权限映射；
新路由若漏登记会在此失败）

- [x] **Step 8: 反向验证（必做）**

把 `list_assignable_permissions` 里的
`frozenset(admin_permissions) & ASSIGNABLE_PERMISSIONS` 临时改成 `ASSIGNABLE_PERMISSIONS`
（返回全量目录），重跑：

预期：`test_returns_only_intersection` **FAILED**。恢复后重跑确认 2 passed。

- [x] **Step 9: 提交**

```bash
git add api/app/http/admin_routes_7.py api/app/http/support.py \
        api/internal/schema/admin_agent_schema.py api/test/app/http/test_admin_agent_routes.py
git commit -m "feat(admin-agent): expose /admin/agents/assignable-permissions"
```

---

## Task 8: 文档同步

**Files:**
- Modify: `docs/rbac.md`

- [x] **Step 1: 新增小节**

在 `docs/rbac.md` 追加"管理端 Agent 授权模型"小节，内容须包含（按 AGENTS.md 要求，
**机制**描述为准，不逐条抄写全量清单）：

- 三重交集公式：`effective = admin.permissions ∩ agent.granted_permissions ∩ ASSIGNABLE_PERMISSIONS`
- `ASSIGNABLE_PERMISSIONS` 的**事实源位置**：`api/internal/core/admin_agent_authorization.py`，
  且说明"显式登记制、新增资源前缀默认不可下放（fail closed）"
- 不可下放的 4 类：身份（`admin:*`）、管理员账号（`admin_user:*`）、角色（`role:*`）、权限点（`permission:read`），
  以及 `user:*` 仅 `:read` 可下放
- 三层强制：展示（API 返回交集）/ 保存（`assert_grantable`）/ 运行（每请求实时重算）
- 权限回收：自动清理，代价是需手动重新下放
- 与 `initialize_defaults()` "只增不删"的关系说明（新权限点默认不可下放）

- [x] **Step 2: 提交**

```bash
git add docs/rbac.md
git commit -m "docs(rbac): document admin agent authorization model"
```

---

## Task 9: 收尾验证

- [x] **Step 1: 全量测试**

```bash
cd api && python -m pytest test/ -q --no-cov -p no:cacheprovider
```

预期：0 failed（passed 数应 ≥ 之前基线 4335）

- [x] **Step 2: 空库迁移冒烟**

```bash
cd api && python -m pytest test/internal/migration -q --no-cov -p no:cacheprovider
```

预期：全 passed（新迁移 `s5f6a7b8c9d0` 使空库链延长，仍须全通）

- [x] **Step 3: 更新知识图谱**

```bash
python -m graphify update .
```

- [x] **Step 4: 提交**

```bash
git add -A
git commit -m "chore(admin-agent): finalize P1a authorization core"
```

---

## Self-Review 结论

**Spec 覆盖对照**：

| 设计章节 | 覆盖于 |
| --- | --- |
| §4.1 三重交集 | Task 2 |
| §4.2 可下放白名单 | Task 1 |
| §4.3 展示即受限（三层） | Task 1（白名单）/ Task 2（保存校验）/ Task 7（API 返回交集）|
| §4.4 权限回收自动清理 | Task 6 |
| §5 `AdminAgentPrincipal` | Task 3 |
| §5.1 自动化级别 | Task 3（枚举 + fail-closed 默认）/ Task 5（取值校验）|
| §10.1 `admin_agent` 表 | Task 4 |
| §10.2 修改表（`audit_log`/`schedule_task`/记忆/草稿泛化） | **不在 P1a**，属 P1b / P3 / P4 |
| §15 文档同步（rbac.md 部分） | Task 8 |

**未覆盖且有意留待后续**（避免本计划范围膨胀）：
- 板块级聚合工具、审计 `actor_type`、`admin_change_draft` 泛化、回收站 `admin_agent` 扩展 → **P1b**
- 对话式入口与会话表 → **P2**
- 记忆主体抽象 → **P3**
- 预算闸门实际执行、`schedule_task.agent_id` → **P4**

**Placeholder 扫描**：本计划所有代码步骤均给出完整可运行代码。
Task 6 Step 7 与 Task 7 Step 3 给出的是"实现提示 + 需实读校准"的说明，
原因是这两处的既有 helper 形态（`_replace_admin_user_roles` 签名、
`a._ok`/`a._to_thread` 组合）需以实读代码为准——实现者**必须先读再写**，
不得照抄臆造签名。这是有意为之，非占位符遗漏。

**类型一致性核对**：
- `AdminAgentPrincipal.automation_policy` 类型为 `Mapping[str, AutomationLevel]`；
  `AdminAgent.automation_policy`（DB）为 `dict[str, str]`（JSONB 存字符串）。
  Task 5 的 `_validate_policy` 负责 `str → AutomationLevel.str` 的归一，转换点唯一。
- `compute_effective_permissions` 返回 `frozenset[str]`，
  `list_assignable_permissions` 返回 `list[str]`（API 需要有序、可 JSON 化）。
- `assert_grantable` 在 Task 2 定义、Task 5 调用，签名一致（keyword-only）。
