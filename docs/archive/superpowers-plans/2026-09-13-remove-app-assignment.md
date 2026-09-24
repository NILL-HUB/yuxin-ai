# 移除「管理员分配应用」（AppAssignment）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底移除「管理员分配应用」功能（代码/UI/权限/数据/文档），并清理其孤儿审计记录与陈旧缓存，使「我的应用」只剩「商店添加（fork）」来源。

**Architecture:** 自底向上删除：先摘 DB 写入路径（模型/服务/路由/schema/RBAC/网关），再迁移 drop 表并清理孤儿数据，最后清理前端与测试。`MyAppService` 同步收敛为单一 fork 来源（保持既有 `published` 过滤语义，不改可见性）。

**Tech Stack:** Python 3.12 + SQLAlchemy 2 + Alembic + Quart + marshmallow + pytest；Vue 3 + TypeScript + vitest + vue-i18n。

**Spec:** `docs/superpowers/specs/2026-09-13-remove-app-assignment-design.md`

---

## 文件结构

**删除**

| 文件 | 职责 |
| --- | --- |
| `api/internal/service/admin_app_assignment_service.py` | 分配服务（整文件） |
| `api/internal/schema/admin_app_assignment_schema.py` | 分配 schema（整文件） |
| `api/test/internal/model/test_app_assignment_model.py` | 模型测试 |
| `api/test/internal/service/test_admin_app_assignment_service.py` | 服务测试 |
| `ui/src/services/admin-app-assignments.ts` | 前端 service |
| `ui/src/services/__tests__/admin-app-assignments.spec.ts` | 前端 service 测试 |

**修改**

| 文件 | 职责 |
| --- | --- |
| `api/internal/model/app.py` | 删 `AppAssignment` 类 |
| `api/internal/model/__init__.py` | 删导入与 `__all__` 项 |
| `api/app/http/admin_routes_8.py` | 删 3 条 app-assignments 路由 + docstring 行 |
| `api/internal/core/rbac.py` | 删 2 条 PermissionSpec + 2 处默认角色授权 |
| `api/app/http/support.py` | 删 app-assignments 权限映射分支 |
| `api/internal/service/my_app_service.py` | 删 assigned 分支；`get_assigned_app`→`get_user_app` |
| `api/internal/schema/my_app_schema.py` | `MyAppResp` 删 `assignment_id` |
| `api/app/http/apps_routes.py` | chat 路由调用改名 |
| `api/test/internal/service/test_my_app_service.py` | 删分配相关用例与工厂 |
| `api/test/app/http/test_my_apps_routes.py` | 删 `assignment_id` 断言 |
| `api/test/app/http/test_admin_routes_8.py` | 删分配路由用例与 fake |
| `ui/src/views/admin/CustomerUsersView.vue` | 删分配抽屉与逻辑 |
| `ui/src/views/admin/__tests__/CustomerUsersView.spec.ts` | 删分配用例与 mock |
| `ui/src/models/app-assignment.ts` | 删 `AssignedApp`/`AppAssignment*`；`MyApp` 去 `assignment_id` |
| `ui/src/views/admin/AuditLogsView.vue` | 删 assign/revoke/app_assignment 映射 |
| `ui/src/i18n/messages/{zh-CN,en-US}/admin/customerUsers.ts` | 删 15 键 |
| `ui/src/i18n/messages/{zh-CN,en-US}/admin/auditLogs.ts` | 删 3 键 |
| `ui/src/i18n/messages/{zh-CN,en-US}/myApps.ts` | 删 `sourceAssigned` |
| `docs/rbac.md`、`docs/api/audit-log-api.md`、`docs/prd/product-vision.md`、`docs/prd/architecture-design.md` | 删/改相关条目 |

**新增**

| 文件 | 职责 |
| --- | --- |
| `api/internal/migration/versions/n8c9d0e1f2a3_drop_app_assignment.py` | drop 表 + 清孤儿审计 |

---

### Task 1: 后端摘除 AppAssignment 写入路径

**Files:**
- Modify: `api/internal/model/app.py`
- Modify: `api/internal/model/__init__.py`
- Delete: `api/internal/service/admin_app_assignment_service.py`
- Delete: `api/internal/schema/admin_app_assignment_schema.py`
- Modify: `api/app/http/admin_routes_8.py`

- [ ] **Step 1: 删除 AppAssignment 模型类**

修改 `api/internal/model/app.py`，删除文件末尾的整个 `AppAssignment` 类（原 L193-219，含 `__tablename__`/`__table_args__`/全部 Column/relationship）。删除后 `AppConfig` 类应紧接在 `App` 类之后。

- [ ] **Step 2: 从模型聚合导出中移除**

修改 `api/internal/model/__init__.py`：

```python
from .app import App, AppConfig, AppConfigVersion
```

并从 `__all__` 中删除 `"AppAssignment"` 一行。

- [ ] **Step 3: 删除分配服务与 schema 文件**

```bash
git rm api/internal/service/admin_app_assignment_service.py \
       api/internal/schema/admin_app_assignment_schema.py
```

- [ ] **Step 4: 删除 admin 分配路由**

修改 `api/app/http/admin_routes_8.py`，删除：

1. 注释块（原 L747-749）：

```python
    # ------------------------------------------------------------------
    # admin_app_assignment_handler -> AdminAppAssignmentService
    # ------------------------------------------------------------------
```

2. 三条路由函数 `admin_app_assignment_list` / `admin_app_assignment_assign` / `admin_app_assignment_revoke`（原 L750-824）。删除后该段直接接 `# admin_routing_log_handler -> RoutingLogService / RoutingLogRetentionService` 注释块。

- [ ] **Step 5: 确认无残留引用**

Run: `cd d:/DEMO/openagent-main/api && python -c "import internal.model"` 与
`cd d:/DEMO/openagent-main/api && python -c "import app.http.admin_routes_8"`
Expected: 无 `ModuleNotFoundError` / `ImportError`

- [ ] **Step 6: 提交**

```bash
git add api/internal/model/app.py api/internal/model/__init__.py api/app/http/admin_routes_8.py
git commit -m "refactor(admin): remove app assignment model, service, schema and routes"
```

---

### Task 2: 移除 RBAC 权限与网关映射

**Files:**
- Modify: `api/internal/core/rbac.py`
- Modify: `api/app/http/support.py`
- Test: `api/test/internal/core/test_rbac_catalog.py`（若存在；下方以运行时断言替代）

- [ ] **Step 1: 删除权限目录条目**

修改 `api/internal/core/rbac.py`，删除 `PERMISSION_CATALOG` 中两行（原 L87-88）：

```python
    PermissionSpec("app_assignment:read", "查看应用分配", "app_assignment", "read", "查看用户已分配应用"),
    PermissionSpec("app_assignment:update", "管理应用分配", "app_assignment", "update", "分配和撤销用户应用"),
```

- [ ] **Step 2: 删除默认角色授权项**

同一文件，删除 operator 角色授权中的两行（原 L188-189）：

```python
            "app_assignment:read",
            "app_assignment:update",
```

以及 viewer 角色授权中的一行（原 L262）：

```python
            "app_assignment:read",
```

- [ ] **Step 3: 删除网关注解映射分支**

修改 `api/app/http/support.py`，删除（原 L470-472）：

```python
    # 用户管理与应用分配。
    if _admin_match(segments, ("admin", "users")) and "app-assignments" in segments:
        return "app_assignment:read" if method == "GET" else "app_assignment:update"
    if _admin_match(segments, ("admin", "users")):
```

改为保留（即把上方最后一行 `if _admin_match(...)` 提升为删除后的首行）：

```python
    if _admin_match(segments, ("admin", "users")):
```

- [ ] **Step 4: 校验权限目录自洽**

Run: `cd d:/DEMO/openagent-main/api && python -c "from internal.core.rbac import PERMISSION_CATALOG; assert not [p for p in PERMISSION_CATALOG if p.code.startswith('app_assignment')]; print('ok')"`
Expected: 输出 `ok`

Run: `cd d:/DEMO/openagent-main/api && python -c "from internal.core.rbac import DEFAULT_ROLES; import json; s=json.dumps([list(r.permission_codes) for r in DEFAULT_ROLES]); assert 'app_assignment' not in s; print('ok')"`
Expected: 输出 `ok`

- [ ] **Step 5: 提交**

```bash
git add api/internal/core/rbac.py api/app/http/support.py
git commit -m "refactor(rbac): drop app_assignment permissions and gateway mapping"
```

---

### Task 3: `MyAppService` 收敛为单一 fork 来源

**Files:**
- Modify: `api/internal/service/my_app_service.py`
- Modify: `api/internal/schema/my_app_schema.py`
- Modify: `api/app/http/apps_routes.py`
- Test: `api/test/internal/service/test_my_app_service.py`
- Test: `api/test/app/http/test_my_apps_routes.py`

- [ ] **Step 1: 改写测试（先失败）**

修改 `api/test/internal/service/test_my_app_service.py`：

(a) 删除文件顶部 `AppAssignment` 导入与 `_assignment()` 工厂（原 L8 import 与 L59-70）。

(b) 将 import 行改为仅 `from internal.model.app import App`。

(c) 删除以下用例：`test_list_my_apps_should_return_active_published_assignments`、`test_list_my_apps_should_skip_unpublished_apps`、`test_get_assigned_app_should_return_app_for_active_assignment`、`test_get_assigned_app_should_raise_when_not_assigned`、`test_get_assigned_app_should_reject_unpublished_app`。

(d) 保留并适配 fork 用例（`test_list_my_apps_should_expose_published_forked_apps` 等），其中 `list_my_apps` 的查询桩数量由「分配查询 + fork 查询」改为**仅 fork 查询**：把 `_SessionStub([_QueryStub(all_result=[]), _QueryStub(all_result=[forked])])` 改为 `_SessionStub([_QueryStub(all_result=[forked])])`。

(e) 追加新用例，断言 `get_user_app` 对本人已发布 fork 副本放行、对草稿副本拒绝：

```python
    def test_get_user_app_should_return_published_forked_app(self):
        account_id = uuid4()
        forked = _app(
            account_id=account_id,
            status=AppStatus.PUBLISHED.value,
            original_app_id=uuid4(),
        )
        service = MyAppService(session=_SessionStub([_QueryStub(one_or_none_result=forked)]))

        result = service.get_user_app(account_id, forked.id)

        assert result.id == forked.id

    def test_get_user_app_should_reject_draft_forked_app(self):
        account_id = uuid4()
        forked = _app(
            account_id=account_id,
            status=AppStatus.DRAFT.value,
            original_app_id=uuid4(),
        )
        service = MyAppService(session=_SessionStub([_QueryStub(one_or_none_result=forked)]))

        with pytest.raises(FailException):
            service.get_user_app(account_id, forked.id)
```

(f) 断言 `MyAppResp` 不再暴露 `assignment_id`：

```python
def test_my_app_resp_schema_should_not_expose_assignment_id():
    """移除管理员分配后，MyAppResp 不应再声明 assignment_id。"""
    from internal.schema.my_app_schema import MyAppResp

    dumped = MyAppResp().dump(
        {
            "id": "app-1",
            "name": "Contract AI",
            "icon": "",
            "description": "desc",
            "created_at": 1893456000,
            "source": "forked",
            "status": "published",
            "can_edit": False,
        }
    )

    assert "assignment_id" not in dumped
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd d:/DEMO/openagent-main/api && python -m pytest test/internal/service/test_my_app_service.py -q --no-cov`
Expected: FAIL — `AttributeError: 'MyAppService' object has no attribute 'get_user_app'`

- [ ] **Step 3: 改写 `MyAppService`**

修改 `api/internal/service/my_app_service.py`：删除 `AppAssignment` 导入（原 L7 改为 `from internal.model.app import App`），`list_my_apps` 改为：

```python
    def list_my_apps(self, account_id: UUID) -> dict[str, object]:
        """返回用户“我的应用”：仅本人从应用商店添加（fork）且已发布的应用。

        可见性规则：只展示 `status == published` 的应用；草稿/下架状态不出现。
        """
        apps = []
        forked_apps = self._list_forked_apps(account_id)
        for app in forked_apps:
            if app.status != AppStatus.PUBLISHED.value:
                continue
            apps.append(self._serialize_forked_app(app))
        return {"list": apps}
```

删除 `_serialize_my_app` 方法（原 L99-117，仅服务分配来源），并将 `_serialize_forked_app` 中的 `assigned_at` 键改名为 `created_at`：

```python
    def _serialize_forked_app(self, app: App) -> dict[str, object]:
        return {
            "id": str(app.id),
            "name": app.name,
            "icon": app.icon,
            "description": app.description,
            "created_at": self._timestamp(app.created_at),
            "source": "forked",
            "status": app.status,
            "can_edit": False,
        }
```

将 `get_assigned_app` 重命名为 `get_user_app`，删除 assignment 查询分支：

```python
    def get_user_app(self, account_id: UUID, app_id: UUID) -> App:
        """校验用户可用应用：本人从商店添加（fork）且已发布的应用。"""
        forked_app = (
            self.session.query(App)
            .filter(
                App.id == app_id,
                App.account_id == account_id,
                App.original_app_id.isnot(None),
            )
            .one_or_none()
        )
        if forked_app is not None:
            if forked_app.status != AppStatus.PUBLISHED.value:
                raise FailException("AI 功能未发布，暂不可用")
            return forked_app
        raise NotFoundException("AI 功能不存在")
```

- [ ] **Step 4: 更新 schema**

修改 `api/internal/schema/my_app_schema.py`：

```python
class MyAppResp(Schema):
    id = fields.String()
    name = fields.String()
    icon = fields.String()
    description = fields.String()
    created_at = fields.Integer(allow_none=True)
    source = fields.String(dump_default="forked")
    status = fields.String(dump_default="")
    can_edit = fields.Boolean(dump_default=False)
```

- [ ] **Step 5: 更新 chat 路由调用点**

修改 `api/app/http/apps_routes.py` 的 `async_my_app_chat`（原 L548）：

```python
        await _to_thread(_get_service(MyAppService).get_user_app, account.id, app_id)
```

- [ ] **Step 6: 更新路由契约测试**

修改 `api/test/app/http/test_my_apps_routes.py`：将 fake service 的方法名由 `list_my_apps` 对应的返回体去掉 `assignment_id`，并把断言 `items[0]["can_edit"] is False` 保留、新增 `assert "assignment_id" not in items[0]`。

- [ ] **Step 7: 运行测试确认通过**

Run: `cd d:/DEMO/openagent-main/api && python -m pytest test/internal/service/test_my_app_service.py test/app/http/test_my_apps_routes.py -q --no-cov`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add api/internal/service/my_app_service.py api/internal/schema/my_app_schema.py api/app/http/apps_routes.py api/test/internal/service/test_my_app_service.py api/test/app/http/test_my_apps_routes.py
git commit -m "refactor(my-apps): drop assignment source and rename get_assigned_app to get_user_app"
```

---

### Task 4: 数据库迁移（drop 表 + 清孤儿审计 + 清陈旧缓存）

**Files:**
- Create: `api/internal/migration/versions/n8c9d0e1f2a3_drop_app_assignment.py`

- [ ] **Step 1: 编写迁移脚本**

新建 `api/internal/migration/versions/n8c9d0e1f2a3_drop_app_assignment.py`：

```python
"""drop app_assignment table and purge its orphan audit logs

Revision ID: n8c9d0e1f2a3
Revises: m7b8c9d0e1f2
Create Date: 2026-09-13 00:00:00.000000

「管理员分配应用」功能已下线：
1. 删除 audit_log 中 resource_type='app_assignment' 的孤儿记录
   （对应 i18n 标签已随功能一并移除，保留会导致审计页出现“无键值记录”）。
2. drop table app_assignment（含索引与 FK）。

downgrade 不可逆（表与审计记录均已删除），需走备份恢复。
"""
from alembic import op
from sqlalchemy import text

revision = "n8c9d0e1f2a3"
down_revision = "m7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    removed_audits = conn.execute(
        text("DELETE FROM audit_log WHERE resource_type = 'app_assignment'")
    ).rowcount

    op.drop_table("app_assignment")

    print(f"[migration] 清理 app_assignment 孤儿审计：{removed_audits} 行；已 drop table app_assignment")


def downgrade():
    raise NotImplementedError(
        "该迁移不可逆（app_assignment 表与相关审计记录均已删除），请走备份恢复。"
    )
```

- [ ] **Step 2: 校验语法与迁移链**

Run: `cd d:/DEMO/openagent-main/api && python -m py_compile internal/migration/versions/n8c9d0e1f2a3_drop_app_assignment.py; Write-Output "compile-ok"`
Expected: 输出 `compile-ok`

- [ ] **Step 3: 应用迁移**

Run: `docker exec -e PYTHONPATH=/app/api llmops-api sh -c "cd /app/api && alembic -c internal/migration/alembic.ini upgrade head"`
Expected: 输出 `Running upgrade m7b8c9d0e1f2 -> n8c9d0e1f2a3, drop app_assignment table ...` 且含 `[migration] 清理 app_assignment 孤儿审计：2 行`

- [ ] **Step 4: 验证数据库状态**

Run: `docker exec -e PYTHONPATH=/app/api llmops-api sh -c "cd /app/api && alembic -c internal/migration/alembic.ini heads"`
Expected: `n8c9d0e1f2a3 (head)`

Run: `docker exec llmops-db psql -U postgres -d llmops -c "SELECT to_regclass('public.app_assignment');"`
Expected: 返回空（`NULL`）

Run: `docker exec llmops-db psql -U postgres -d llmops -c "SELECT count(*) FROM audit_log WHERE resource_type = 'app_assignment';"`
Expected: `count = 0`

- [ ] **Step 5: 清理陈旧 pyc 缓存（无源码对应）**

```bash
Get-ChildItem -Recurse -File api/test -Filter "test_admin_app_assignment_handler*.pyc" | Remove-Item -Force
Get-ChildItem -Recurse -File api/test -Filter "test_my_app_handler*.pyc" | Remove-Item -Force
```

- [ ] **Step 6: 提交**

```bash
git add api/internal/migration/versions/n8c9d0e1f2a3_drop_app_assignment.py
git commit -m "feat(migration): drop app_assignment table and purge orphan audit logs"
```

---

### Task 5: 前端清理客户用户页分配功能

**Files:**
- Delete: `ui/src/services/admin-app-assignments.ts`
- Delete: `ui/src/services/__tests__/admin-app-assignments.spec.ts`
- Modify: `ui/src/views/admin/CustomerUsersView.vue`
- Modify: `ui/src/views/admin/__tests__/CustomerUsersView.spec.ts`
- Modify: `ui/src/models/app-assignment.ts`
- Modify: `ui/src/i18n/messages/zh-CN/admin/customerUsers.ts`
- Modify: `ui/src/i18n/messages/en-US/admin/customerUsers.ts`
- Modify: `ui/src/i18n/messages/zh-CN/myApps.ts`
- Modify: `ui/src/i18n/messages/en-US/myApps.ts`

- [ ] **Step 1: 删除前端 service 及其测试**

```bash
git rm ui/src/services/admin-app-assignments.ts ui/src/services/__tests__/admin-app-assignments.spec.ts
```

- [ ] **Step 2: 清理 `CustomerUsersView.vue`**

删除：三方法 import（原 L15）与 `AppAssignment` 类型 import（原 L17）；状态 `selectedAssignmentUser / assignments / assignmentAppIds / availableApps`（原 L51-54）；方法 `loadAvailableApps / openAssignments / closeAssignments / handleAssignApps / handleRevokeAssignment`（原 L102-214 中对应片段）；模板中「分配应用」按钮（原 L577）与整个分配抽屉 `a-drawer` 块（原 L606-659）。若 `loadAvailableApps` 是唯一使用 `listAdminApps` 的位置，同步删除该 import。

- [ ] **Step 3: 清理 `CustomerUsersView.spec.ts`**

删除 mock 三方法（原 L13-15）与 `vi.mock('@/services/admin-app-assignments')`（原 L28-32）；删除「分配」与「撤销」两个用例（原 L239、L256）；删除其列表返回桩（原 L136-138）。

- [ ] **Step 4: 收敛前端类型**

修改 `ui/src/models/app-assignment.ts`：删除 `AssignedApp`、`AppAssignment`、`AppAssignmentListResponse`、`AssignAppsResponse` 四个导出，保留 `MyApp`/`MyAppListResponse`/`MyAppChatRequest` 并按新契约改写：

```ts
import { type BaseResponse } from '@/models/base'

export type MyApp = {
  id: string
  name: string
  icon: string
  description: string
  created_at: number | null
  source: 'forked'
  status?: string
  can_edit?: boolean
}
export type MyAppListResponse = BaseResponse<{ list: MyApp[] }>
export type MyAppChatRequest = {
  query: string
  image_urls?: string[]
  conversation_id?: string
}
```

- [ ] **Step 5: 处理 `ListView.vue` 的来源徽标**

修改 `ui/src/views/space/my-apps/ListView.vue`。来源只剩 fork，因此去掉「分配」分支。改动点（按现有行号）：

(a) 脚本（原 L56-61）：`sourceLabel` 保留入参签名（模板已传参），去掉三元判断；`isForked` 整个删除：

```ts
const sourceLabel = () => t('myApps.sourceForked')
```

(b) 卡片来源徽标（原 L162-169）：类名固定 `my-badge-fork`，图标固定 `icon-branch`：

```vue
              <span
                class="my-badge-fork inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
              >
                <icon-branch class="h-3 w-3" />
                {{ sourceLabel() }}
              </span>
```

(c) 对话页顶栏来源徽标（原 L232-237）：

```vue
            <span
              class="my-badge-fork inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
            >
              {{ sourceLabel() }}
            </span>
```

(d) `my-app-chat-panel` 的 `:source-label`（原 L246）改为 `:source-label="sourceLabel()"`。

(e) 样式：删除 `.my-badge-assign` 块（原 L308-311）。

- [ ] **Step 6: 清理 i18n（zh/en 同步）**

`admin/customerUsers.ts` 删除 15 键：`loadAssignmentsFailed`、`appAssigned`、`assignFailed`、`assignmentRevoked`、`revokeAssignmentFailed`、`assignApp`、`assignTitle`、`assignDesc`、`appSelectPlaceholder`、`confirmAssign`、`assigned`、`revoked`、`revoke`、`assignedApps`、`noAssignments`。zh-CN 与 en-US 各删一遍（键名相同、位置对应）。

`myApps.ts` 删除 `sourceAssigned`（zh/en 各一处）。

- [ ] **Step 7: 运行 parity 与相关测试**

Run: `cd d:/DEMO/openagent-main/ui && npx vitest run src/i18n/__tests__/parity.spec.ts src/views/admin/__tests__/CustomerUsersView.spec.ts src/views/space/my-apps`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add -A ui/src/services ui/src/views/admin ui/src/models ui/src/i18n ui/src/views/space/my-apps
git commit -m "refactor(ui): remove app assignment UI, service, types and i18n keys"
```

---

### Task 6: 清理审计页标签与映射

**Files:**
- Modify: `ui/src/views/admin/AuditLogsView.vue`
- Modify: `ui/src/i18n/messages/zh-CN/admin/auditLogs.ts`
- Modify: `ui/src/i18n/messages/en-US/admin/auditLogs.ts`

- [ ] **Step 1: 删除审计页映射分支**

修改 `ui/src/views/admin/AuditLogsView.vue`：删除 action 映射中的 `assign`/`revoke` 两项（原 L59-60）与 resource_type 映射中的 `app_assignment` 一项（原 L87）。

- [ ] **Step 2: 删除 i18n 标签（zh/en 同步）**

`admin/auditLogs.ts` 删除 `actionAssign`、`actionRevoke`、`resourceAppAssignment`（zh-CN 与 en-US 各一处）。

- [ ] **Step 3: 运行 parity 与审计页测试**

Run: `cd d:/DEMO/openagent-main/ui && npx vitest run src/i18n/__tests__/parity.spec.ts src/views/admin/__tests__/AuditLogsView.spec.ts`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add ui/src/views/admin/AuditLogsView.vue ui/src/i18n/messages/zh-CN/admin/auditLogs.ts ui/src/i18n/messages/en-US/admin/auditLogs.ts
git commit -m "refactor(ui): drop app_assignment audit labels and mappings"
```

---

### Task 7: 后端测试清理与全量回归

**Files:**
- Delete: `api/test/internal/model/test_app_assignment_model.py`
- Delete: `api/test/internal/service/test_admin_app_assignment_service.py`
- Modify: `api/test/app/http/test_admin_routes_8.py`

- [ ] **Step 1: 删除分配专项测试**

```bash
git rm api/test/internal/model/test_app_assignment_model.py \
       api/test/internal/service/test_admin_app_assignment_service.py
```

- [ ] **Step 2: 清理 `test_admin_routes_8.py`**

删除：`_app_assignment_dict()` 工厂（原 L131-141）；`_FakeAdminAppAssignmentService` 类（原 L304-318）；路由注册断言中 `app-assignments` 相关行（原 L586 附近）；`TestAdminAppAssignment` 测试类（原 L1032 起，含 list/assign/assign_empty/revoke 四用例）。

- [ ] **Step 3: 后端全量测试**

Run: `cd d:/DEMO/openagent-main/api && python -m pytest -q -p no:cacheprovider --no-cov`
Expected: 全部 PASS，0 failed（用例总数较 3912 下降属预期）

- [ ] **Step 4: 提交**

```bash
git add -A api/test
git commit -m "test: remove app assignment test suites and fixtures"
```

---

### Task 8: 前端全量回归与文档同步

**Files:**
- Modify: `docs/rbac.md`
- Modify: `docs/api/audit-log-api.md`
- Modify: `docs/prd/product-vision.md`
- Modify: `docs/prd/architecture-design.md`

- [ ] **Step 1: 前端全量测试**

Run: `cd d:/DEMO/openagent-main/ui && npx vitest run`
Expected: 全部 PASS

- [ ] **Step 2: 类型检查**

Run: `cd d:/DEMO/openagent-main/ui && npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | Select-String -Pattern "error TS" | Measure-Object -Line`
Expected: 错误数 ≤ 14（基线，不新增）

- [ ] **Step 3: 更新 RBAC 文档**

修改 `docs/rbac.md`：删除 `app_assignment:read` / `app_assignment:update` 权限条目，以及 operator/viewer 角色授权中的对应项；删除「客户用户管理」中描述应用分配的文字。

- [ ] **Step 4: 更新审计 API 文档**

修改 `docs/api/audit-log-api.md`：删除 `app_assignment` 的 action（`assign`/`revoke`）与 resource_type 取值条目、未登记回源类型清单中的 `app_assignment`、写入来源中的 `AdminAppAssignmentService`。

- [ ] **Step 5: 更新产品与架构文档**

`docs/prd/product-vision.md`：§三-12「我的应用列表」说明改为「来源=应用商店添加（fork）；管理员分配功能已下线」。
`docs/prd/architecture-design.md`：删除「后台应用分配 | `AppAssignment`、`AdminAppAssignmentService`」一行。

- [ ] **Step 6: 全库残留检查**

Run:
```bash
Get-ChildItem -Recurse -File -Include *.py,*.ts,*.vue,*.md api ui/src docs | Where-Object { $_.FullName -notmatch 'superpowers|archive' } | Select-String -Pattern "AppAssignment|app_assignment|app-assignments|assignment_id|sourceAssigned|actionAssign|actionRevoke|resourceAppAssignment|get_assigned_app" | Select-Object Path,LineNumber,Line
```
Expected: 无输出

- [ ] **Step 7: 更新知识图谱**

Run: `cd d:/DEMO/openagent-main && python -m graphify update .`
Expected: 输出 `Code graph updated.`

- [ ] **Step 8: 提交**

```bash
git add docs/ graphify-out/
git commit -m "docs: sync removal of app assignment across rbac, audit and prd"
```

---

## 完成标准

- [ ] `app_assignment` 表已 drop，孤儿审计记录已清零
- [ ] 后端零 `AppAssignment` 引用；`/my/apps` 仅 fork 来源且可用；chat 路由走 `get_user_app`
- [ ] RBAC 无 `app_assignment:*`；网关无对应映射
- [ ] 前端客户用户页无分配入口；审计页无已删标签；i18n parity 通过
- [ ] 后端 `pytest` 与前端 `vitest` 全绿；`vue-tsc` 不高于基线
- [ ] 文档同步；graphify 已刷新；全库残留检查为空
