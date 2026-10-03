# 会话级工作区授权（Session Workspace Scope）设计

> 状态：**已落地**（2026-10-04 设计并实现，落地记录见文末）。解决「文件三件套被静态安全根挡住、GUI 却整机可达」的覆盖缺口。
> 关联：[08-os-automation.md §治理模型矩阵](../../prd/modules/08-os-automation.md)

## 问题陈述

当前治理边界 = 静态 `OS_AUTOMATION_SAFE_ROOT`（默认用户主目录）：

| 能力 | 可达范围 | 治理 |
| --- | --- | --- |
| 文件三件套（os_file_task / os_recycle_bin / os_terminal） | 安全根内 | 完整（快照 + 回收站 + 删除守卫） |
| computer_action（GUI） | **整机** | 逐次人审 + 文件操作禁令（无快照） |

覆盖缺口 = **安全根之外的目录**（其他盘符、Program Files 等）：Agent 合法需要在这些目录干活时
（如整理 D 盘素材、改 C:\server 配置），三件套硬拒绝，只剩 GUI（无快照兜底）或用户手工——
治理在缺口处退化。GUI 每动作逐次确认也拖垮体验（已缓解项：纯观察动作免确认、轮内一次放行）。

## 目标

1. 三件套的治理覆盖面与 GUI 对齐：**任意目录**都可被治理通道触达；
2. 范围扩展必须经**用户显式授权**，不引入静默放行；
3. 授权范围内享受与安全根内完全相同的治理（写前快照、回收站、删除守卫、changes/recovery_hint）。

## 设计

### 1. 会话工作区（scope）

- 会话（conversation）可绑定 0..N 个**授权根目录**（scope_root）：
  - 来源：用户在会话中显式添加；或 Agent 请求时经授权流用户批准；
  - 生命周期：默认随会话结束失效；平台提供撤销入口（复用 `desktop_device` revoke 的交互模式）。
- `OS_AUTOMATION_SAFE_ROOT` 语义降级为**未授权时的默认边界**，不再是硬上限；
  会话授权根可以位于安全根之外（这正是本设计的意义）。

### 2. 授权流（fail-closed）

```text
Agent 调用三件套，working_dir 超出（安全根 ∪ 已授权根）
  → 工具返回结构化 {ok:false, needs_scope_grant:true, path:"D:\proj-x", session_id}
  → 前端弹窗：「Agent 请求在本会话操作 D:\proj-x」[仅本会话允许] [拒绝]
  → 批准 → POST /desktop/session-scopes（account_id + session_id + scope_root + 设备指纹）落库
  → Agent 重试同一调用（payload 自动携带会话授权根集合）
  → worker 校验通过，正常执行；后续同会话调用不再弹窗
```

- 每次授权都是**用户显式行为 + 明确目录**，粒度清晰、可审计（授权记录进审计日志）；
- 拒绝时 Agent 收到明确拒绝语义，转而引导用户手动处理或换路径。

### 3. 传递与校验

- **平台侧**：`SessionScopeService`（新增）：授权 CRUD + 会话维度查询 + 过期清理；
  工具层构建 payload 时注入 `session_scopes`（该会话已授权根列表，加密传输与 bridge token 同级）；
- **worker 侧**：`_resolve_safe_root(requested)` 升级为
  `_resolve_allowed_roots(requested, session_scopes)`——请求路径必须落在
  `安全根 ∪ session_scopes` 内，否则回退安全根（现有 fail-closed 语义不变）；
- **快照与回收站**：每个 scope_root 一套 `<scope_root>/.yujianwo_snapshots` 与
  `.yujianwo_recycle`（与安全根同构，复用全部现有机制，无第二套实现）；
  回滚入口 `os_snapshot` 按 `working_dir` 解析对应 scope 的 manifest，天然支持跨 scope。

### 4. 治理不变式（重构后依然成立）

| 区域 | 治理 |
| --- | --- |
| 安全根 ∪ 已授权根（会话内） | 自动化执行：快照/回收站/删除守卫/change 清单全量生效 |
| 上述之外 | 三件套硬拒绝 → 触发授权流（用户决定）；GUI 保持逐次人审 + 文件操作禁令 |

### 5. 与 GUI 体验的配套（已落地部分）

- 纯观察动作（screenshot/capture/list_apps/list_windows）已免确认（`ToolPolicy.requires_confirmation`）；
- 轮内一次放行已存在（`authorized_tools` 随 state 累积）；管理员可经智能审批策略进一步放行；
- 本设计落地后，GUI 的使用频率将大幅下降（文件类任务全部走三件套），逐次确认的体验负担
  自然收敛到「真正需要 GUI 的少数场景」。

## 不做什么

- 不做全盘默认放行（安全根/授权根始终是白名单语义）；
- 不做静默范围扩展（任何越界都必须经过用户批准）；
- 不做第二套快照/回收站实现（scope 复用同构机制）。

## 落地范围（估）

平台：SessionScopeService + 授权路由 + 工具 payload 注入 + 前端授权弹窗（约 4 个模块）；
worker：`_resolve_allowed_roots` + scope 级快照/回收站根解析（改动集中在 `_resolve_safe_root`
与其调用方）；测试与文档同步。建议拆分：worker 侧能力先行（scope 校验 + 快照同构）→
平台授权流 → 前端弹窗。

## 落地记录（2026-10-04）

| 层 | 产物 |
| --- | --- |
| worker（硬边界） | `_allowed_scope_roots`（payload.session_scopes 校验：绝对路径/存在/是目录/上限 16）、`_resolve_scope_context` / `_root_for_path` / `_scope_denied_response`；`/file` `/recycle` `/snapshot` `/exec` 全部接线——未授权越界返回 `{ok:false, needs_scope_grant:true, path, message}`（不再静默回退）；回收站按**文件所属根**分别入站；快照/回滚 manifest 落操作根（授权根内自成一套）；快照额外根范围限定在允许集合内 |
| 平台-存储 | `session_workspace_scope` 表（account+session+root 唯一，status/expires_at/granted_via）+ 迁移 `f1a2b3c4d5e6`（down_revision=d5f6a7b8c9e0，单 head） |
| 平台-服务 | `SessionScopeService`：grant（幂等刷新、上限 8、绝对路径校验、TTL 12h）/ list_active_roots / list_scopes / revoke |
| 平台-注入 | `worker_client.call_host_worker` 单点注入 `session_scopes`（四工具自动获得，查询失败按无授权 fail-closed） |
| 平台-授权流 | 新工具 `os_workspace_scope`（高风险 + `always_confirm_tool_names` 每次必确认，不受轮内放行/智能审批影响）；确认摘要显示目标目录与原因；系统提示词规则 19 |
| 测试 | worker +4（授权可用/未授权 needs_scope_grant/回收站按根/幽灵条目忽略/补丁越界拒绝/缺目录语义）、工具 +8、真机端到端（exec/patch/recycle 在授权根内全部可用且可回滚） |

**语义变化（有意为之）**：`working_dir` 指向"存在但未授权"的目录时，从「静默回退安全根」改为「拒绝 + needs_scope_grant」——避免在错误目录执行命令；不存在的目录仍宽容回退。
