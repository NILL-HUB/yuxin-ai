# 管理端 RBAC 设计与运维

## 1. 模型

管理端 RBAC 使用经典四表模型：

- `admin_user`：管理员账号，UUID 主键。
- `role`：角色，UUID 主键，`code` 唯一且作为外部稳定标识。
- `permission`：权限点，UUID 主键，`code` 唯一且作为外部稳定标识。
- `admin_user_role` / `role_permission`：管理员-角色、角色-权限绑定。

权限 code 是系统唯一可读标识，例如 `app:read`、`workflow:update`、`recycle_bin:write`。
UUID 只存在于数据库内部；角色与权限的 API 响应、角色标签、权限下拉框均只返回/展示
`code`、`name`、`description` 等可读字段，不再暴露 `id`。

## 2. 权限目录与默认角色

权限目录和默认角色模板的单一事实源位于：

`api/internal/core/rbac.py`

- `PERMISSION_CATALOG`：全部权限点。
- `DEFAULT_ROLES`：内置角色及其默认授权模板。
- `super_admin`：系统保留角色，自动获得全部权限（含未来新增权限）。

默认角色：

| 角色 | 用途 |
| --- | --- |
| `super_admin` | 拥有全部权限，不可修改、不可删除 |
| `operator` | 运营管理员，管理应用、工作流、知识库、工具、用户和日常运营 |
| `finance` | 财务管理员，管理套餐、卡密和收入数据 |
| `support` | 客服人员，查询用户和基础资料 |
| `auditor` | 审核人员，审核资源与案例展示，查看审计日志 |
| `viewer` | 只读观察员 |

## 3. 鉴权门禁

所有 `/admin/*` 请求在 Quart `before_request` 统一经过 RBAC 门禁：

1. `/admin/auth/login` 放行。
2. `/admin/auth/me`、`/admin/auth/logout`、`/admin/auth/password` 只要求有效管理员会话，不要求业务权限。
3. 其余管理端路由按“HTTP 方法 + 路径”解析所需权限 code，权限映射位于 `app/http/support.py` 的 `_admin_route_permission`。
4. 未登记的管理端路径默认拒绝（fail closed），返回 403。
5. 权限校验每次实时读取管理员会话、角色和权限，不依赖 JWT 中的静态权限快照；角色调整即时生效。

路由内不再信任 `X-Admin-Id` 等客户端头作为操作者身份，操作者统一从管理员 token 解析。

## 4. API 契约

角色管理：

- `GET /admin/roles`
- `POST /admin/roles`，入参 `code`、`name`、`description`、`permission_codes`
- `GET /admin/roles/<role_code>`
- `PATCH /admin/roles/<role_code>`，入参 `permission_codes`
- `DELETE /admin/roles/<role_code>`
- `GET /admin/permissions`

管理员管理：

- 创建/更新管理员使用 `role_codes`，响应中的 `roles` 返回角色 code。
- 系统角色不可修改、不可删除；已分配给管理员的自定义角色不可删除。
- 系统始终保留至少一个有效超级管理员。

## 5. 安全约束

- 超级管理员角色拥有通配权限，不需要随新权限逐个补绑。
- 自定义角色编码禁止使用内置角色 code。
- 角色删除前校验占用，避免悬空授权。
- 管理员不能移除自己的全部角色。
- RBAC 写操作（角色创建/更新/删除、管理员角色变更）写入审计日志，字段使用可读 code。

## 6. 数据同步

- 服务启动初始化与 Alembic 迁移 `c1d2e3f4a5b6_sync_rbac_catalog` 都会幂等同步权限目录、默认角色和默认授权。
- 新增权限只需在 `PERMISSION_CATALOG` 增加一项并运行 `python -m graphify update .`，无需手工写 SQL。
- 若需要为默认角色调整模板，修改 `DEFAULT_ROLES` 后执行一次 `AdminRbacService.initialize_defaults()` 或运行数据库迁移。
