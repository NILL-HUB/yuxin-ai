# 前端架构收敛与后台管理重建设计

## 1. 背景与问题

### 1.1 当前割裂现状

OpenAgent 基于开源用户 Agent 平台二开。后端已按 PRD 八层架构实现了运行时治理层（L2-L8），但前端仍是原版的用户自助配置 UI。具体表现为：

- **管理员在用"用户自助配置 UI"当管理后台**：`/space/apps`（应用编排）、`/space/workflows`（工作流编辑器）、`/space/datasets`（知识库）等页面本质是给用户自己配的，只是用门禁（`getCustomerConfigGuardRedirect` + `v-if="isAdminLoggedIn"`）把普通用户挡在 403。
- **两套布局两套心智模型**：`/space/*` 和 `/admin/*` 是两套布局，管理员在两个入口间跳转，体验割裂。
- **7 个管理页仍是占位**：工作流/知识库/MCP/Skills/管理员管理/角色权限/审计日志都是 `<h2>xxx</h2>` 占位。
- **后端管理 API 覆盖仅 55%**：L5 模型池管理完全缺失，L3 Agent 池配置缺失，L4 工具池配置只是空占位。
- **前端仅接入 45% 的已有后端 API**：RBAC 管理、审计日志、工作流管理、系统知识库等后端已实现的 API 前端未接入。

### 1.2 PRD 目标

PRD 3.2/7.2 明确：
- 普通用户只在 `/home` 输入需求，系统自动完成能力选择、工具选择、执行和汇总。
- 普通用户不应看到配置中心、Agent 池内部、工具池内部、模型选择细节、Prompt 和工具参数、路由候选和过滤细节。
- 管理员负责配置 Agent 子池、工具子池、MCP Provider、模型池、Key 池、成本策略、权限策略、审计和路由日志。

### 1.3 改造目标

将前端从"原版用户自助驱动"彻底转变为"管理员驱动 + 用户只问"。原版功能不删除，全部用 RBAC 收敛进 `/admin/*` 后台。

## 2. 改造后前端三区

### 2.1 用户端（普通用户可见，6 个页面）

| 路由 | 功能 | 说明 |
|------|------|------|
| `/home` | 首页对话 | 唯一交互入口，只传 query+图片+确认深度思考 |
| `/memory` | 个人记忆管理 | 用户长期记忆库 |
| `/external-data-sources` | 外部数据源连接 | 飞书/Notion/GitHub 等 |
| `/my-knowledge` | 个人知识库 | 用户资料内容库（原 /space/datasets 收窄） |
| `/showcase` | 用户案例展示 | 新功能，公开展示好评案例 |
| `/search` | 会话搜索 | 历史会话搜索 |
| `/settings` | 个人设置 | 账号设置 |

### 2.2 管理后台（仅管理员可见 /admin/*）

原版 `/space/*` + `/store/*` + `/openapi/*` 全部收敛于此，复用编辑器代码，用 RBAC 守卫限制仅管理员。

```
▸ 仪表盘（/admin 首页概览）
▸ RBAC管理
  - 管理员管理（/admin/admin-users）← 后端已有API，前端补页面
  - 角色权限（/admin/roles）← 后端已有API，前端补页面
  - 客户用户（/admin/users）← 已接入
▸ 资源编排（复用原版编辑器）
  - 应用编排（/admin/apps/:id/edit）← /space/apps 收敛
  - 工作流编排（/admin/workflows/:id/edit）← /space/workflows 收敛
  - 知识库管理（/admin/datasets/*）← /space/datasets 收敛
  - API工具管理（/admin/tools）← /space/tools 收敛
  - MCP管理（/admin/mcp）← /space/mcp 收敛
  - Skills管理（/admin/skills）← /space/skills 收敛
▸ 资源运营（商店管理）
  - 公开应用/工作流/工具/MCP/Skills 上架下架审核
▸ 池治理（新增管理能力）
  - Agent池配置（/admin/agents）← L3 元数据/健康/过滤策略
  - 工具池治理（/admin/tool-governance）← L4 风险等级/可见性/过滤策略
  - 模型池管理（/admin/models）← L5 模型CRUD/档位策略/Key池/成本策略
▸ 观测中心
  - 路由日志（/admin/routing-logs）← 已接入
  - 路由质量（/admin/routing-quality）← 已接入
  - 审计日志（/admin/audit-logs）← 后端已有API，前端补页面
▸ 编排控制
  - 功能开关（/admin/orchestration-flags）← 已接入
▸ 计费运营
  - 套餐管理（/admin/billing）← 已接入
▸ OpenAPI管理（/admin/openapi）← /openapi 收敛
```

### 2.3 仅废弃

| 路由 | 原因 |
|------|------|
| `/my-ai/*` | 原版让用户选应用，二开不需要 |

## 3. 用户案例展示功能（新增）

### 3.1 功能流程

```
用户在 /home 完成对话
  → 用户点击"好评"（thumbs up）
  → 系统弹出确认卡片："是否将此对话设为公开展示案例？"
  → 用户确认 → 对话被收录到 /showcase
  → 管理员可在后台审核/下架案例
```

### 3.2 数据模型

```python
@dataclass
class ShowcaseCase:
    id: UUID
    conversation_id: UUID
    account_id: UUID  # 贡献者
    title: str  # 案例标题（用户可编辑）
    summary: str  # AI 生成的摘要
    query: str  # 原始问题
    answer: str  # 最终回答
    tags: list[str]  # 标签
    rating: int  # 评分（默认5）
    status: str  # pending/approved/rejected/offline
    created_at: datetime
    approved_at: datetime | None
    approved_by: UUID | None  # 管理员
```

### 3.3 API 设计

| 方法 | 路径 | 功能 | 权限 |
|------|------|------|------|
| POST | /showcase/cases | 用户提交案例 | user |
| GET | /showcase/cases | 公开案例列表 | public |
| GET | /showcase/cases/:id | 案例详情 | public |
| GET | /admin/showcase/cases | 管理员案例列表（含pending） | admin |
| POST | /admin/showcase/cases/:id/approve | 审核通过 | admin |
| POST | /admin/showcase/cases/:id/reject | 审核拒绝 | admin |
| POST | /admin/showcase/cases/:id/offline | 下架 | admin |

### 3.4 前端页面

- `/showcase`：公开案例展示页（所有用户可见），支持标签筛选+关键词搜索
- `/admin/showcase`：管理员审核页（仅管理员可见）

## 4. 实施阶段拆解

### Phase A：后端管理 API 补齐（P0 缺口）

补齐后端缺失的管理 API，为前端收敛提供接口支撑：

- A1: L5 模型池管理 API（ModelPool/KeyPool/ModelAssignmentPolicy/CostPolicy 的 admin CRUD）
- A2: L3 Agent 池配置 API（AgentPoolService/AgentInventory 的 admin 查询+配置）
- A3: L4 工具池治理 API（ToolPolicyFilter 策略配置 + /admin/tools 真实 CRUD）
- A4: 用户案例展示 API（ShowcaseCase CRUD + 审核流程）

### Phase B：前端路由收敛与 RBAC 守卫

- B1: 路由重构——/space/* /store/* /openapi/* 全部收敛进 /admin/*
- B2: AdminLayout 侧边栏重建——按 2.2 结构组织菜单
- B3: 用户端导航精简——普通用户侧边栏只留 6 个入口
- B4: RBAC 守卫强化——所有原版配置路由强制 adminRequired

### Phase C：管理后台页面补齐

- C1: RBAC 管理页面（管理员管理/角色权限）——接后端已有 API
- C2: 审计日志页面——接后端已有 API
- C3: 工作流管理页面——接后端已有 API + 复用原版编辑器
- C4: 知识库管理页面——接后端已有 API + 复用原版编辑器
- C5: 模型池管理页面（新增）——接 A1 新 API
- C6: Agent 池配置页面（新增）——接 A2 新 API
- C7: 工具池治理页面（增强）——接 A3 新 API

### Phase D：用户端精简

- D1: 用户端侧边栏只留 6 个入口
- D2: /my-knowledge 从 /space/datasets 收窄为用户个人知识库
- D3: 删除 /my-ai/* 路由
- D4: HomeView 好评→案例提交流程

### Phase E：用户案例展示功能

- E1: /showcase 公开案例展示页
- E2: /admin/showcase 管理员审核页
- E3: HomeView 好评→提交案例确认卡片

## 5. 复用策略

### 5.1 原版编辑器复用

以下原版编辑器直接收敛进 /admin/*，复用组件代码：

| 原版路由 | 收敛后路由 | 复用组件 |
|----------|-----------|----------|
| /space/apps/:id | /admin/apps/:id/edit | DetailView.vue + 全部子组件 |
| /space/workflows/:id | /admin/workflows/:id/edit | DetailView.vue + 12节点编辑器 |
| /space/datasets/* | /admin/datasets/* | ListView + documents + segments |
| /space/tools | /admin/tools | ListView.vue |
| /space/mcp | /admin/mcp | ListView.vue |
| /store/* | /admin/store/* | 各商店 ListView |
| /openapi/* | /admin/openapi/* | IndexView + api-keys |

### 5.2 复用原则

- 组件代码原封不动复用，只改路由路径和父布局
- 去掉"用户视角"文案，改为"管理员编排"视角
- 用 `adminRequired` + `permissions` 守卫限制访问
- 商店类页面从"用户安装"改为"管理员上架下架审核"

## 6. 测试策略

- 后端：每个新 API 补单元测试 + 集成测试
- 前端：路由守卫测试（普通用户访问 /admin/* 跳 403）+ 页面渲染测试
- E2E：管理员登录→进后台→编排应用→发布；用户登录→首页对话→好评→提交案例→showcase 展示

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 路由收敛范围大，可能遗漏 | 先做路由映射表，逐条验证 |
| 原版编辑器残留用户视角逻辑 | 收敛后逐一审查，清理用户视角文案 |
| 后端新 API 工作量大 | 按 Phase A 优先级：L5 模型池 > L4 工具池 > L3 Agent 池 > 案例展示 |
| 测试回归 | 每个 Phase 完成后跑全量回归（后端 1700+ 前端 370+）
