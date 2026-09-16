# 审计日志 接口文档

> 对应实现：`api/app/http/admin_routes_8.py`（`GET /admin/audit-logs`、`GET /admin/audit-logs/overview`）、`api/internal/service/audit_log_service.py`、`api/internal/schema/admin_audit_log_schema.py`、`api/internal/model/admin.py`（`AuditLog`）
> 前端实现：`ui/src/services/admin-audit-logs.ts`、`ui/src/views/admin/AuditLogsView.vue`
> 数据表：`audit_log`（模型 `AuditLog`）

## 通用约定

- 统一响应：`{ "code": "success", "message": "", "data": {...} }`；业务错误返回非 success code 与 HTTP 4xx/5xx。
- 认证：管理侧接口需**有效管理员登录态**；无 token / token 失效返回 401，缺权限返回 403。
- 权限点：`audit_log:read`（`GET /admin/audit-logs` 与 `GET /admin/audit-logs/overview` 共用；RBAC 映射见 `api/app/http/support.py`）。`super_admin` 天然包含；默认角色中 `auditor` / `viewer` 含该权限，`operator` / `finance` / `support` 不含。
- 时间窗口：`start_time` / `end_time` 均为**秒级 Unix 时间戳**，服务端转为 naive UTC 后按 `created_at` 过滤；非法值静默忽略（不过滤）。
- 分页：`paginator = { "total_record", "total_page", "current_page", "page_size" }`；入参 `current_page`（默认 1）、`page_size`（默认 20，**上限 50**，超出按 50 截断）。
- 列表排序：`created_at DESC`（最新在前）。
- 前端调用前缀：Web 端经 nginx 以 `/api` 前缀代理（`/api/admin/audit-logs`）；直连后端为 `http://<host>:5001/admin/audit-logs`。

## 一、接口清单

| 方法/路径 | 说明 | 请求 | 响应要点 |
|---|---|---|---|
| `GET /admin/audit-logs` | 审计日志分页列表 | query：`action`、`resource_type`、`admin_user_id`、`start_time`、`end_time`、`current_page`、`page_size` | `{list:[AuditLog...], paginator}` |
| `GET /admin/audit-logs/overview` | 观测概览聚合（SQL 级全量） | query：`action`、`resource_type`、`start_time`、`end_time` | `{total, by_action[], by_resource_type[], trend[], top_admins[]}` |

> `list` 未提供 `account_id` 过滤入参（service 层保留了该形参，但 HTTP 路由未接线）。

## 二、`GET /admin/audit-logs` — 分页列表

### 2.1 请求参数（query，均可选）

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `action` | string | `""` | 按操作类型精确过滤（如 `delete`、`set_status`） |
| `resource_type` | string | `""` | 按资源类型精确过滤（如 `customer_user`、`plan`） |
| `admin_user_id` | string | `""` | 按操作管理员 ID 精确过滤 |
| `start_time` | int | 无 | 起始时间，秒级时间戳（含） |
| `end_time` | int | 无 | 结束时间，秒级时间戳（含） |
| `current_page` | int | `1` | 页码，最小 1 |
| `page_size` | int | `20` | 每页条数，范围 1–50，超出按 50 截断 |

### 2.2 响应字段（`AuditLog`）

| 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|
| `id` | string(uuid) | 否 | 审计记录 ID |
| `admin_user_id` | string(uuid) | 是 | 操作管理员 ID；系统任务（如 `ghost_memory_cleanup`）为 `null` |
| `admin_user_name` | string | 否 | 操作管理员展示名（`username` 优先，回退 `name`）；无法解析时为空串 |
| `account_id` | string(uuid) | 是 | 关联用户账号 ID（用户侧工具调用审计时记录） |
| `account_name` | string | 否 | 关联账号展示名（`name` 优先，回退 `email`）；无法解析时为空串 |
| `action` | string | 否 | 操作类型（见 §四枚举） |
| `resource_type` | string | 否 | 资源类型（见 §四枚举） |
| `resource_id` | string | 否 | 资源标识；通常是资源 UUID，也可能是业务键（如 `billing_config.code`、`payment_provider_config.provider`）或逗号拼接的多 ID（`storage.file_delete`） |
| `resource_name` | string | 否 | **资源可读名称**（见 §三解析规则）；无法解析时为空串，前端回退展示 `resource_id` |
| `ip` | string | 否 | 操作来源 IP |
| `user_agent` | string | 否 | 操作来源 UA |
| `before_data` | object(JSONB) | 否 | 变更前快照（无变更时 `{}`） |
| `after_data` | object(JSONB) | 否 | 变更后快照（如删除类操作只含 `{"status":"deleted",...}`） |
| `created_at` | int | 否 | 创建时间，秒级 Unix 时间戳 |

### 2.3 响应示例

```json
{
  "code": "success",
  "message": "",
  "data": {
    "list": [
      {
        "id": "6a055496-ed25-4d3b-ab19-d54d796c13ff",
        "admin_user_id": "a2c88e02-7afd-4da3-9c55-4aea4d238c49",
        "admin_user_name": "admin",
        "account_id": null,
        "account_name": "",
        "action": "delete",
        "resource_type": "customer_user",
        "resource_id": "229261e4-2211-4463-ad26-72703ba1419d",
        "resource_name": "t67545",
        "ip": "172.18.0.1",
        "user_agent": "Mozilla/5.0 ...",
        "before_data": { "name": "t67545", "email": "", "status": "active" },
        "after_data": { "status": "deleted", "cleanup": { "pg_rows": 0 }, "revoked_sessions": 0 },
        "created_at": 1788670486
      }
    ],
    "paginator": { "total_record": 1, "total_page": 1, "current_page": 1, "page_size": 20 }
  }
}
```

## 三、`resource_name` 解析规则

`resource_id` 是 UUID / 内部标识，直接展示无法辨识「删的是哪个用户 / 哪个套餐」。`resource_name` 由 `AuditLogService` 在**读取时**解析（无需数据迁移，对存量记录同样生效），分两层：

1. **优先取快照**（`_extract_resource_name`）：按固定优先级扫描 `before_data` / `after_data` 中的名称字段，顺序为
   `resource_name → name → username → display_name → title → tool_name → code → order_no → user_name → email → key`；
   先看 `after_data`（变更后最终态），为空回退 `before_data`（删除类操作的名称只存在于变更前快照）。覆盖 `create/update/delete` 等把名称写入快照的操作。
2. **回源表兜底**（`_build_resource_name_map`）：`disable/enable/set_status/revoke_sessions` 等**状态变更类操作**快照里只有状态字段（如 `{"status":"active"}`），没有名称。此时按 `resource_type` 分组，对缺名称的记录批量各发一次 `IN` 查询回源表补全（映射表 `_RESOURCE_NAME_LOOKUPS` 登记了 30 个资源类型 → 模型 / 匹配列 / 名称列），避免 N+1 查询。快照已有名称时不触发回源。

**健壮性**：未登记的资源类型、非 UUID 的 `resource_id`、模型导入失败或查询异常均静默降级为空串，不影响列表返回。

**已知缺口**：目标资源被**物理硬删除**且名称只存在于回源表时（快照也无名称），无法解析，`resource_name` 为空串——前端回退展示 `resource_id`。

## 四、枚举取值

`action` 与 `resource_type` 为自由字符串（表列为 `String(255)`），以下为**当前写入 `audit_log` 的实际取值**。

### 4.1 `action`

| `resource_type` | 写入的 `action` |
|---|---|
| `admin_user` | `create`、`update`、`disable`、`enable`、`reset_password`、`revoke_admin_sessions`、`delete` |
| `role` | `create`、`update`、`delete` |
| `customer_user` | `create`、`update`、`delete`、`disable`、`enable`、`revoke_sessions` |
| `plan` | `create`、`update`、`set_status`、`delete` |
| `billing_config` | `upsert` |
| `redeem_code_batch` | `generate`、`disable` |
| `redeem_code` | `view_plain`、`disable` |
| `skill` | `skill.enable`、`skill.disable`、`skill.sync`（点分复合） |
| `mcp` | `mcp.create`、`mcp.update`、`mcp.delete`、`mcp.publish`、`mcp.unpublish`、`mcp.import_mcp_json`、`mcp.import_url`、`mcp.import_json`（点分复合） |
| `storage_file` | `storage.file_delete`（点分复合） |
| `system_knowledge` | `create`、`update`、`delete` |
| `distribution_relation` | `bind_superior`、`unbind_superior` |
| `purchase_order` | `close_order` |
| `withdrawal_request` | `withdraw_approve`、`withdraw_reject` |
| `return_request` | `refund_approve`、`refund_reject` |
| `payment_provider_config` | `payment_config_enabled` |
| `policy_change_draft` | `policy_change_apply`、`policy_change_rollback` |
| `tool` | `tool_invocation` |
| `memory` | `ghost_memory_cleanup`（系统自愈脚本，`admin_user_id=NULL`，`resource_id` 为空） |

> 点分复合 action（如 `storage.file_delete`）前端按「资源 · 动作」组合翻译；未知值回退语义字典。

### 4.2 `resource_type`

当前写入 `audit_log` 的取值：`admin_user`、`role`、`customer_user`、`plan`、`billing_config`、`redeem_code`、`redeem_code_batch`、`skill`、`mcp`、`storage_file`、`system_knowledge`、`distribution_relation`、`purchase_order`、`withdrawal_request`、`return_request`、`payment_provider_config`、`policy_change_draft`、`tool`、`memory`。

> **注意**：`resource_name` 回源映射（`_RESOURCE_NAME_LOOKUPS`，见 §三）共登记 **30** 个类型，与审计实际取值**不完全重合**：
> - 审计已产生但**未登记**回源的类型（`withdrawal_request`、`policy_change_draft`、`memory`）只依赖快照取名；
> - 映射额外预留了当前由**回收站**（`recycle_bin` 表）写入、审计暂未产生的类型（`app`、`workflow`、`api_tool`、`knowledge_base`、`knowledge_document`、`conversation`、`schedule_task`、`external_data_source`、`upload_file`、`model`、`model_provider`、`orchestration_flag`、`prompt_template`，以及 `customer_user` 的别名 `account`），供未来这些类型纳入审计时即插即用。
>
> 未登记类型仅在快照无名称时降级为空名，不影响列表返回。
> 前端另有别名映射：`skill_package → skill`、`mcp_provider → mcp`、`storage → storage_file`。

## 五、`GET /admin/audit-logs/overview` — 观测概览

### 5.1 请求参数（query，均可选）

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `action` | string | `""` | 过滤条件，影响 `total` / `by_action` / `by_resource_type` |
| `resource_type` | string | `""` | 过滤条件，同上 |
| `start_time` | int | 无 | 起始时间，秒级时间戳 |
| `end_time` | int | 无 | 结束时间，秒级时间戳 |

> `trend` 与 `top_admins` **不受** `action` / `resource_type` 过滤（仅受时间窗口约束），用于呈现窗口内的整体趋势与活跃管理员。

### 5.2 响应字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `total` | int | 窗口内（含 `action` / `resource_type` 过滤）总记录数 |
| `by_action` | `{name,count}[]` | 按操作类型分布，Top 15，`name` 为空归一 `unknown` |
| `by_resource_type` | `{name,count}[]` | 按资源类型分布，Top 15，`name` 为空归一 `unknown` |
| `trend` | `{timestamp,count}[]` | 按日聚合趋势（`date_trunc('day')`），`timestamp` 秒级；不含过滤条件 |
| `top_admins` | `{name,count}[]` | 活跃管理员，Top 10，只统计 `admin_user_id` 非空；`name` 为管理员展示名，无法解析时回退 ID；不含过滤条件 |

### 5.3 响应示例

```json
{
  "code": "success",
  "message": "",
  "data": {
    "total": 250,
    "by_action": [
      { "name": "create", "count": 120 },
      { "name": "delete", "count": 50 }
    ],
    "by_resource_type": [
      { "name": "customer_user", "count": 100 },
      { "name": "plan", "count": 40 }
    ],
    "trend": [
      { "timestamp": 1765843200, "count": 10 },
      { "timestamp": 1765929600, "count": 20 }
    ],
    "top_admins": [
      { "name": "admin", "count": 90 }
    ]
  }
}
```

## 六、写入来源（供排查参考）

审计记录由各管理操作在成功后写入（失败通常静默跳过，不阻塞主流程）。主要写入点：

- 管理员 / 角色 / 客户用户 / 套餐 / 计费配置 / 卡密：`AdminUserService`、`AdminRbacService`、`AdminCustomerUserService`、`AdminBillingPlanService`、`AdminBillingConfigService`、`AdminRedeemCodeService`
- 技能 / MCP：`admin_routes_4.py` 的 `_record_mutation_audit`
- 存储文件删除：`admin_routes_7.py`（`resource_id` 为逗号拼接的多个文件 ID）
- 系统知识库：`ScopedKnowledgeService`（固定 `resource_type=system_knowledge`）
- 调优策略变更草稿：`RoutingPolicyChangeService`（`resource_type=policy_change_draft`）
- 订单 / 提现 / 售后 / 支付配置：`admin_commerce_routes.py` 的 `_write_audit`
  > 管理端已于 2026-09-14 移除分销能力（`distribution/*` 与 `PUT /admin/users/<id>/superior` 端点删除），`_write_audit` 不再产生 `bind_superior` / `unbind_superior` 记录；历史记录仍可读（`action` 与 `resource_type=distribution_relation` 的渲染标签保留）。
- 工具调用审计：`ToolInvocationAuditService`（`resource_type=tool`，同时写 `account_id`）
- 记忆自愈脚本：`action=ghost_memory_cleanup`、`resource_type=memory`、`admin_user_id=NULL`

## 相关文档

- 观测中心聚合接口背景：[Conductor 编排、执行协调与可观测性](../prd/modules/03-orchestration-infra.md) §15.4、§15.6
- 权限模型：[RBAC 权限模型](../rbac.md)
