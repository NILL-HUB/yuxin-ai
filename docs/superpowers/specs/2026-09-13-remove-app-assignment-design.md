# 移除「管理员分配应用」（AppAssignment）设计

> **状态**：设计已评审确认。本轮（P1）只做删除；「我的应用」分栏（P2）与用户自建应用/发布审核流（P3）为后续独立子项目。
> **日期**：2026-09-13

## 1. 背景与目标

产品流程被重新明确为：

1. 用户自建的应用 → 用户自己发布 → 进 admin 审核流程 → 通过后才显示在应用商店。
2. 用户在应用商店里对已上架应用「添加到我的应用」，并对自己的副本有 CRUD 权限。
3. 其余应用由管理员在后台创建并上传到商店，供用户使用。
4. 用户对自己创建的应用有 CRUD 权限。

在这套流程下，**「管理员分配应用」不再是必要功能**：用户获取应用的唯一入口是「应用商店添加」，而应用进入商店的守门人由「后续的审核流」承担，无需管理员逐用户分配。

**目标**：彻底移除 AppAssignment 功能，消除其全部代码、UI、权限、数据与文档足迹；并清理因此产生的孤儿数据，避免后续误导（例如审计页出现无对应 i18n 键的残记录）。

## 2. 范围

### 2.1 本轮删除范围（P1）

| 层 | 删除内容 |
| --- | --- |
| 数据表 | `app_assignment` 表（新增迁移 drop） |
| 遗留数据 | `audit_log` 中 `resource_type='app_assignment'` 的孤儿记录（当前实测 2 条，`action='assign'`） |
| 陈旧产物 | 无源码对应的 `test_admin_app_assignment_handler` / `test_my_app_handler` 的 `.pyc` 缓存 |
| 模型 | `AppAssignment` 类 + `internal/model/__init__.py` 导入与 `__all__` |
| 服务 | `admin_app_assignment_service.py`（整文件） |
| 路由 | `admin_routes_8.py` 的 3 条 `app-assignments` 路由 + 模块 docstring 描述 |
| Schema | `admin_app_assignment_schema.py`（整文件：`AssignAppsReq` / `AssignedAppResp` / `AppAssignmentResp` / `AppAssignmentListResp` / `AssignAppsResp`） |
| RBAC | `rbac.py` 两条 `PermissionSpec("app_assignment:read"/"app_assignment:update")` + operator/viewer 默认角色授权项 |
| 网关 | `support.py` 的 `app-assignments` → 权限映射分支 |
| MyAppService | `AppAssignment` import；`list_my_apps` 的 assigned 分支；`get_assigned_app` 的 assignment 分支；`MyAppResp.assignment_id` 字段 |
| 前端 | `services/admin-app-assignments.ts`（+ spec）；`CustomerUsersView.vue` 分配抽屉与相关状态/方法（+ spec 用例）；`models/app-assignment.ts` 中 `AppAssignment*` 与 `AssignedApp` 类型；i18n 键；`AuditLogsView.vue` 的 `assign/revoke/app_assignment` 映射分支 |
| i18n | `admin/customerUsers.ts` 分配相关 15 键（zh/en）；`myApps.ts` 的 `sourceAssigned`；`admin/auditLogs.ts` 的 `actionAssign`/`actionRevoke`/`resourceAppAssignment` |
| 文档 | `docs/rbac.md`、`docs/api/audit-log-api.md`、`docs/prd/product-vision.md`、`docs/prd/architecture-design.md` 中相关条目 |

### 2.2 最小必要连带改动

删除 `AppAssignment` 后，`MyAppService.list_my_apps` 的「管理员分配」来源会直接报错，必须同步摘除。P1 的 `my_apps()` 收敛为：

- 仅保留「本人商店添加（fork）」来源（`account_id == 本人` 且 `original_app_id IS NOT NULL`）。
- 维持既有 `status == published` 过滤（P1 不改变可见性语义）。
- `MyAppResp` 删除 `assignment_id`；`source` 保留但只可能为 `'forked'`。

> 说明：fork 副本当前被创建为 `draft`，在既有「严格过滤」下暂时不可见——这是已知的既有缺口，P2 会随「我的应用」重构（含草稿/正式分栏）一并修正。P1 不改变该行为。

`get_assigned_app` 重命名为 `get_user_app`（语义不再含「分配」），并同步 `/my/apps/<app_id>/chat` 调用点。

### 2.3 明确不在范围（后续子项目）

- **P2**：「我的应用」重构（来源=本人应用含自建+fork；前端「草稿/正式」分页栏；admin 端同构镜像一个「我的应用」）。
- **P3**：用户自建应用 CRUD + 发布 + 审核流（`AppStatus` 扩展 `pending_review`/`rejected`；解封用户 `/apps` 写接口；审核后台）。

## 3. 关键决策

| 决策点 | 结论 | 理由 |
| --- | --- | --- |
| `app_assignment` 表 | **直接 drop** | 本仓库二开阶段约定：无必须保留的历史数据，不为兼容留死表 |
| 历史审计记录 | **i18n 标签与记录一并删除** | 避免审计页出现「无键值的废弃记录」而误判为缺键 |
| fork 副本可见性 | P1 维持现状（不改） | 与「口径重构」解耦，降低单次变更面；P2 统一处理 |
| `source` 字段 | P1 保留，仅可能为 `'forked'` | 避免牵连 ListView；P2 随分栏重构再决定去留 |

## 4. 数据迁移

新增迁移（`down_revision = m7b8c9d0e1f2`，当前 head）执行：

1. `DELETE FROM audit_log WHERE resource_type = 'app_assignment'`（清理孤儿审计）。
2. `DROP TABLE app_assignment`（含其索引与外键）。

`downgrade` 不可逆（表已删、审计已删），抛 `NotImplementedError` 并提示走备份恢复——与仓库既有不可逆迁移一致。

## 5. 验证与验收

1. 后端全量 `pytest` 全绿（用例总数因删除相关测试而下降属预期）。
2. 前端全量 `vitest` 全绿；i18n parity（`parity.spec.ts`）通过。
3. `vue-tsc` 错误数不高于基线（当前 14）。
4. 迁移在容器内 `upgrade head` 成功；`\dt app_assignment` 不存在；`audit_log` 无 `app_assignment` 行。
5. 全库检索零残留：`AppAssignment`、`app_assignment`、`app-assignments`、`assignment_id`、`assigned` 来源、`sourceAssigned`、`actionAssign`、`actionRevoke`、`resourceAppAssignment`。
6. `python -m graphify update .` 执行成功。

### 完成标准

- [ ] `app_assignment` 表已 drop，孤儿审计记录已清除
- [ ] 后端不再有任何 AppAssignment 引用；`/my/apps` 仅 fork 来源且可用
- [ ] RBAC 不再有 `app_assignment:*`；网关无对应映射
- [ ] 前端客户用户页无分配入口；i18n zh/en 键集合一致（parity 通过）
- [ ] 审计页不再引用已删标签与资源类型
- [ ] 文档同步；graphify 已刷新
