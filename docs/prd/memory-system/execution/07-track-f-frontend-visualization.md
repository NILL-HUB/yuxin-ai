# Track F：前端图可视化任务执行文档

> **创建日期**：2026-07-09
> **Track**：F（Frontend Visualization）
> **任务范围**：F1-F6
> **前置条件**：Track D（策略与治理 + 图谱 API）完成，8 个图谱/CRUD 端点可用
> **执行原则**：二开阶段，无生产数据，不做向后兼容，旧代码直接删除
> **关联架构**：[architecture-design.md Ch16](../../architecture-design.md) | [memory-system/03-consolidation-skill-policy-api.md §10](../03-consolidation-skill-policy-api.md)

---

## Track F 总览

| 任务 | 名称 | 文件 | 类型 |
|---|---|---|---|
| F1 | 前端 API 服务 + 类型定义 | `ui/src/services/memory-graph.ts`、`ui/src/models/memory-graph.ts` | 新建 |
| F2 | 聚类视图组件 | `ui/src/components/memory/MemoryClusterView.vue` | 新建 |
| F3 | 子图视图组件（力导向布局） | `ui/src/components/memory/MemoryGraphView.vue` | 新建 |
| F4 | 节点详情面板 | `ui/src/components/memory/MemoryNodeDetail.vue` | 新建 |
| F5 | 记忆管理页面（重写） | `ui/src/views/settings/MemoryView.vue` | 重写 |
| F6 | 路由更新 + 导航菜单 | `ui/src/router/index.ts` 等 | 修改 |

**Track F 依赖关系**：

```
Track D 图谱 API ──→ F1 API 服务 + 类型 ──→ F2 聚类视图
                                      │      F3 子图视图（力导向）
                                      │      F4 节点详情
                                      │        │
                                      └──→ F5 记忆管理页面（集成 F2/F3/F4）
                                                │
                                                └──→ F6 路由 + 导航
```

---

## 现有前端代码现状

| 文件 | 行数 | 说明 | 处理方式 |
|---|---|---|---|
| `ui/src/views/settings/MemoryView.vue` | 623 | 旧记忆管理页面（3 Tab: saved/candidates/settings） | F5 重写 |
| `ui/src/components/MemoryConfirmationCard.vue` | 138 | 旧确认卡片 | 删除（Track G 清理） |
| `ui/src/services/user-memory.ts` | 66 | 旧 API 服务 | F1 删除 |
| `ui/src/models/memory.ts` | 57 | 旧类型定义 | F1 删除 |

**现有 UI 框架**：Vue 3 + TypeScript + Element Plus + Tailwind CSS

**旧设计问题**：
- 候选确认流程（candidates Tab）已被新架构移除（写入路径改为 SalienceScorer 自动评分）
- 旧 API（`/memory-candidates/*`、`/user/memory/*`）已被新 API（`/memory/*`）替代
- 缺少图谱可视化能力

---

## F1：前端 API 服务 + 类型定义

### 任务编号
F1

### 任务名
前端 API 服务封装与类型定义

### 目标
封装 13 个新 API 端点调用，定义前端类型（MemoryNode/MemoryEdge/MemoryCluster/MemoryGraphData/MemoryDetail/SkillInfo 等），并删除旧的服务与类型文件。

### 输入
- Track D 提供的 13 个后端端点（POST /memory/write、POST /memory/retrieve、GET /memory/digest/{user_id}、POST /memory/consolidate/{user_id}、GET /memory/graph/{user_id}、GET /memory/graph/{user_id}/cluster/{type}、GET /memory/{memory_id}、PUT /memory/{memory_id}、DELETE /memory/{memory_id}、DELETE /memory/{memory_id}/hard、POST /memory/{memory_id}/decay、GET /memory/skills/{user_id}、GET /memory/health）
- 现有请求工具：`ui/src/utils/request.ts`（get/post/del/put 封装）
- 现有基础响应类型：`ui/src/models/base.ts`（`BaseResponse`）

### 输出
- 文件路径：
  - 新建 `ui/src/services/memory-graph.ts`
  - 新建 `ui/src/models/memory-graph.ts`
  - 删除 `ui/src/services/user-memory.ts`
  - 删除 `ui/src/models/memory.ts`
- 关键类型签名（`ui/src/models/memory-graph.ts`）：
  ```typescript
  // 记忆节点
  export type MemoryNode = {
    id: string
    memory_type: string
    content: string
    confidence: number
    weight: number
    tier: 'HOT' | 'WARM' | 'COLD'
    is_active: boolean
    created_at: string
    last_accessed_at?: string
    source_conversation_id?: string
    metadata?: Record<string, unknown>
  }

  // 记忆边
  export type MemoryEdge = {
    source: string
    target: string
    type: string
    weight: number
  }

  // 聚类摘要
  export type MemoryCluster = {
    memory_type: string
    node_count: number
    last_updated_at: string
  }

  // 图谱总览数据
  export type MemoryGraphData = {
    user_id: string
    clusters: MemoryCluster[]
    total_nodes: number
  }

  // 聚类子图
  export type ClusterSubgraph = {
    nodes: MemoryNode[]
    edges: MemoryEdge[]
    truncated: boolean
  }

  // 关联节点
  export type RelatedNode = {
    node_id: string
    content: string
    memory_type: string
    strength: number
  }

  // 记忆详情
  export type MemoryDetail = {
    memory_id: string
    content: string
    memory_type: string
    confidence: number
    source_conversation_id?: string
    created_at: string
    last_accessed_at?: string
    related: RelatedNode[]
  }

  // 技能信息
  export type SkillInfo = {
    skill_id: string
    name: string
    description: string
    template: string
    parameters: Array<{ name: string; type: string; description: string }>
    status: 'candidate' | 'emerging' | 'active' | 'stale' | 'deprecated'
    maturity: number
    use_count: number
    frequency: number
    first_seen_at: string
    last_used_at?: string
    last_updated_at: string
  }

  // 技能列表响应
  export type SkillListResponse = {
    user_id: string
    skills: SkillInfo[]
    total: number
  }

  // 健康检查响应
  export type MemoryHealth = {
    status: string
    version: string
    neo4j: boolean
    pgvector: boolean
    redis: boolean
    uptime_seconds: number
  }
  ```
- 关键服务函数签名（`ui/src/services/memory-graph.ts`）：
  ```typescript
  export const getMemoryGraph = (userId: string) => get<BaseResponse<MemoryGraphData>>(`/memory/graph/${userId}`)
  export const getClusterSubgraph = (userId: string, type: string) => get<BaseResponse<ClusterSubgraph>>(`/memory/graph/${userId}/cluster/${type}`)
  export const getMemoryDetail = (memoryId: string) => get<BaseResponse<MemoryDetail>>(`/memory/${memoryId}`)
  export const editMemory = (memoryId: string, newContent: string) => put<BaseResponse<{ new_id: string }>>(`/memory/${memoryId}`, { body: { new_content: newContent } })
  export const softDeleteMemory = (memoryId: string) => del<BaseResponse<{ deleted: boolean }>>(`/memory/${memoryId}`)
  export const hardDeleteMemory = (memoryId: string) => del<BaseResponse<{ deleted: boolean }>>(`/memory/${memoryId}/hard`)
  export const decayMemory = (memoryId: string, decayFactor: number, reason?: string) => post<BaseResponse<{ memory_id: string; new_weight: number }>>(`/memory/${memoryId}/decay`, { body: { decay_factor: decayFactor, reason } })
  export const listSkills = (userId: string) => get<BaseResponse<SkillListResponse>>(`/memory/skills/${userId}`)
  export const getMemoryDigest = (userId: string) => get<BaseResponse<unknown>>(`/memory/digest/${userId}`)
  export const triggerConsolidation = (userId: string) => post<BaseResponse<unknown>>(`/memory/consolidate/${userId}`)
  export const writeMemory = (data: { user_id: string; content: string; memory_type?: string; metadata?: Record<string, unknown>; tags?: string[] }) => post<BaseResponse<{ memory_id: string }>>(`/memory/write`, { body: data })
  export const retrieveMemory = (data: { query: string; user_id: string; top_k?: number; time_range_days?: number; budget_tokens?: number; views?: string[] }) => post<BaseResponse<unknown>>(`/memory/retrieve`, { body: data })
  export const getMemoryHealth = () => get<BaseResponse<MemoryHealth>>(`/memory/health`)
  ```

### 实现步骤
1. 创建 `ui/src/models/memory-graph.ts`，定义上述所有类型（MemoryNode、MemoryEdge、MemoryCluster、MemoryGraphData、ClusterSubgraph、RelatedNode、MemoryDetail、SkillInfo、SkillListResponse、MemoryHealth）。
2. 创建 `ui/src/services/memory-graph.ts`：
   - import `get/post/put/del` from `@/utils/request`
   - import `BaseResponse` from `@/models/base`
   - import 上述类型 from `@/models/memory-graph`
   - 封装 13 个 API 调用函数（每个函数返回 Promise<BaseResponse<T>>）
3. 删除 `ui/src/services/user-memory.ts`（旧 API 服务）。
4. 删除 `ui/src/models/memory.ts`（旧类型定义）。
5. 全局搜索引用旧文件的位置（`MemoryConfirmationCard.vue`、`MemoryView.vue` 等），确保不再引用旧类型；引用处将在 F2-F5 中替换为新服务/类型。
6. 运行 `cd ui && npx vue-tsc --noEmit` 验证类型检查通过（此时旧 MemoryView.vue 引用未更新会报错，F5 重写后修复）。

### 验收标准
- [ ] `ui/src/models/memory-graph.ts` 定义 10+ 类型，字段完整
- [ ] `ui/src/services/memory-graph.ts` 封装 13 个 API 端点调用
- [ ] 旧文件 `ui/src/services/user-memory.ts` 和 `ui/src/models/memory.ts` 已删除
- [ ] `cd ui && npx vue-tsc --noEmit` 类型检查通过（F5 完成后整体通过）
- [ ] `cd ui && npx vitest run` 测试通过

### 关联架构文档章节
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §10 API 接口定义（13 个端点）
- `docs/prd/memory-system/execution/00-overview.md` 代码目录结构规划（ui/src/services/memory-graph.ts）

---

## F2：聚类视图组件

### 任务编号
F2

### 任务名
MemoryClusterView 聚类视图组件

### 目标
创建聚类视图组件，展示 6 个 memory_type 区块（画像/偏好/关系/事件/项目/密钥），每个区块显示节点数量与最近更新时间，点击区块触发 `select-cluster` 事件。

### 输入
- F1 类型定义：`MemoryCluster`、`MemoryGraphData`
- Element Plus Card 组件
- Tailwind CSS 网格布局

### 输出
- 文件路径：`ui/src/components/memory/MemoryClusterView.vue`（新建，需先创建 `ui/src/components/memory/` 目录）
- 组件 Props/Emits 签名：
  ```typescript
  // Props
  defineProps<{
    clusters: MemoryCluster[]   // 6 个聚类摘要数据
    loading?: boolean
    selectedType?: string       // 当前选中的 memory_type（高亮）
  }>()

  // Emits
  defineEmits<{
    (e: 'select-cluster', type: string): void
  }>()
  ```

### 实现步骤
1. 创建目录 `ui/src/components/memory/`。
2. 创建 `MemoryClusterView.vue`（`<script setup lang="ts">`）：
   - import `MemoryCluster` from `@/models/memory-graph`
   - import Element Plus 的 `ElCard`、`ElSkeleton`
   - import 时间格式化工具（`@/utils/time-formatter` 或 moment）
3. 定义 6 个 memory_type 的元信息常量（与后端 6 类对应）：
   ```typescript
   const CLUSTER_META: Array<{ value: string; label: string; icon: string; color: string }> = [
     { value: 'profile', label: '画像', icon: 'User', color: '#409EFF' },
     { value: 'preference', label: '偏好', icon: 'Star', color: '#67C23A' },
     { value: 'relationship', label: '关系', icon: 'Connection', color: '#9C27B0' },
     { value: 'event', label: '事件', icon: 'Calendar', color: '#E6A23C' },
     { value: 'project', label: '项目', icon: 'Folder', color: '#00BCD4' },
     { value: 'secret', label: '密钥', icon: 'Key', color: '#F56C6C' },
   ]
   ```
4. 模板使用 Tailwind Grid 布局（`grid grid-cols-2 md:grid-cols-3 gap-4`），每个聚类用 `ElCard` 渲染：
   - 顶部：图标 + 类型名称
   - 中部：节点数量（大字号）
   - 底部：最近更新时间（相对时间，如"2 小时前"）
   - 选中状态：边框高亮（`ring-2 ring-blue-500`）
5. 卡片点击事件：`@click="emit('select-cluster', meta.value)"`
6. 处理聚类数据缺失情况：若 `clusters` 中某类型不存在，显示节点数 0。
7. loading 状态使用 `ElSkeleton` 占位。
8. 空状态：`clusters` 为空时显示 ElEmpty。

### 验收标准
- [ ] 6 个 memory_type 区块（画像/偏好/关系/事件/项目/密钥）正确渲染
- [ ] 每个区块显示节点数量与最近更新时间
- [ ] 点击区块触发 `select-cluster` 事件，payload 为 memory_type 字符串
- [ ] 选中区块高亮显示
- [ ] loading 状态显示骨架屏
- [ ] 空状态显示 ElEmpty
- [ ] 缺失类型显示节点数 0
- [ ] `cd ui && npx vue-tsc --noEmit` 类型检查通过

### 关联架构文档章节
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §10 `GET /memory/graph/{user_id}` 响应（6 个 memory_type 区块）
- `docs/prd/memory-system/execution/00-overview.md` 代码目录结构规划

---

## F3：子图视图组件（力导向布局）

### 任务编号
F3

### 任务名
MemoryGraphView 子图视图组件（力导向布局）

### 目标
使用 d3-force 力导向布局渲染记忆子图，节点按 HebbianDecay 权重排列大小、按 Tier 分色（HOT=红/WARM=橙/COLD=灰），边按权重分粗细，支持拖拽/缩放/点击节点/搜索筛选，≤200 节点限制。

### 输入
- F1 类型定义：`MemoryNode`、`MemoryEdge`、`ClusterSubgraph`
- d3-force 库（需安装：`d3-force` 或 `vis-network`）
- 聚类子图数据（nodes + edges + truncated）

### 输出
- 文件路径：`ui/src/components/memory/MemoryGraphView.vue`（新建）
- 组件 Props/Emits 签名：
  ```typescript
  defineProps<{
    subgraph: ClusterSubgraph | null
    loading?: boolean
  }>()

  defineEmits<{
    (e: 'select-node', nodeId: string): void
  }>()
  ```
- 依赖：需在 `ui/package.json` 添加 `d3-force`（或 `vis-network`）依赖

### 实现步骤
1. 安装依赖：`cd ui && npm install d3-force`（推荐 d3-force，轻量；或 vis-network 自带渲染）。
   - 若用 d3-force，需配合 Canvas 或 SVG 渲染（推荐 Canvas 性能更好，200 节点无压力）
   - 若用 vis-network，自带 Canvas 渲染与交互
2. 创建 `MemoryGraphView.vue`（`<script setup lang="ts">`）：
   - import `MemoryNode`、`MemoryEdge`、`ClusterSubgraph` from `@/models/memory-graph`
   - import d3-force 模块（`forceSimulation`、`forceLink`、`forceManyBody`、`forceCenter`、`forceCollide`）
   - import Element Plus 的 `ElInput`、`ElSelect`、`ElDatePicker`、`ElMessage`、`ElAlert`
3. 定义 Tier 颜色映射常量：
   ```typescript
   const TIER_COLORS: Record<string, string> = {
     HOT: '#F56C6C',    // 红色
     WARM: '#E6A23C',   // 橙色
     COLD: '#909399',   // 灰色
   }
   ```
4. 定义节点大小映射函数：`nodeRadius = 8 + weight * 20`（weight 范围 0-1，半径 8-28）。
5. 定义边粗细映射函数：`edgeWidth = 1 + weight * 4`（weight 范围 0-1，粗细 1-5）。
6. 实现力导向布局：
   - `forceSimulation(nodes)` 创建模拟
   - `forceLink(edges).id(d => d.id).distance(80)` 连接力
   - `forceManyBody().strength(-200)` 斥力
   - `forceCenter(width/2, height/2)` 中心力
   - `forceCollide(28)` 碰撞检测（避免节点重叠）
   - `simulation.on('tick', render)` 每帧重绘 Canvas
7. 实现 Canvas 渲染：
   - `<canvas ref="canvasRef">` 元素，宽高响应式
   - 清空画布 → 绘制边（按 weight 粗细）→ 绘制节点（按 Tier 颜色 + weight 大小）→ 绘制节点标签（hover 时显示）
8. 实现交互：
   - 拖拽节点：监听 `mousedown/mousemove/mouseup`，调用 `simulation.alphaTarget(0.3).restart()` + 设置 `fx/fy`
   - 缩放：监听 `wheel`，调整 Canvas transform scale
   - 点击节点：监听 `click`，命中检测后 `emit('select-node', node.id)`
9. 实现搜索栏（顶部）：
   - 类型筛选：`ElSelect`（多选 memory_type）
   - 时间范围：`ElDatePicker`（range 模式）
   - 关键词：`ElInput`（搜索节点 content）
   - 筛选变化时重新过滤 nodes/edges 并重启 simulation
10. 实现 ≤200 节点限制：
    - 若 `subgraph.nodes.length > 200`，按 weight 降序截取前 200
    - 显示 `ElAlert` 提示"节点数超过 200，已按权重截断显示"
    - `truncated` 为 true 时也显示提示
11. loading 状态显示加载动画。
12. 组件卸载时调用 `simulation.stop()` 释放资源。
13. 监听 `subgraph` prop 变化，重新初始化 simulation。

### 验收标准
- [ ] 力导向布局正确渲染节点与边
- [ ] 节点按 HebbianDecay 权重排列大小（weight 越大节点越大）
- [ ] 节点按 Tier 分色（HOT=红/WARM=橙/COLD=灰）
- [ ] 边按权重分粗细
- [ ] 支持拖拽节点（拖拽时仿真继续运行）
- [ ] 支持滚轮缩放
- [ ] 点击节点触发 `select-node` 事件
- [ ] ≤200 节点限制生效，超出时按权重截断 + 提示
- [ ] 搜索栏支持按类型/时间范围/关键词筛选
- [ ] `truncated=true` 时显示截断提示
- [ ] 组件卸载时释放 simulation 资源
- [ ] `cd ui && npx vue-tsc --noEmit` 类型检查通过

### 关联架构文档章节
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §10 `GET /memory/graph/{user_id}/cluster/{type}` 响应（ClusterSubgraph）
- `docs/prd/memory-system/execution/00-overview.md` 关键风险与对策（前端图渲染性能 200+ 节点 → 限制 ≤200 + LOD 降级 + d3-force）

---

## F4：节点详情面板

### 任务编号
F4

### 任务名
MemoryNodeDetail 节点详情面板组件

### 目标
创建节点详情面板，展示记忆完整信息（内容/类型/置信度/来源/时间/关联节点），提供 5 个操作按钮（编辑/软删除/彻底删除/降低权重/标记不再重要），各操作 emit 对应事件。

### 输入
- F1 类型定义：`MemoryDetail`、`RelatedNode`
- Element Plus 的 `ElDialog`、`ElInput`（TextArea）、`ElButton`、`ElMessageBox`、`ElTag`、`ElDescriptions`
- 节点详情数据（通过 `GET /memory/{memory_id}` 获取）

### 输出
- 文件路径：`ui/src/components/memory/MemoryNodeDetail.vue`（新建）
- 组件 Props/Emits 签名：
  ```typescript
  defineProps<{
    detail: MemoryDetail | null
    loading?: boolean
  }>()

  defineEmits<{
    (e: 'edit', memoryId: string, newContent: string): void
    (e: 'soft-delete', memoryId: string): void
    (e: 'hard-delete', memoryId: string): void
    (e: 'decay', memoryId: string, decayFactor: number): void
    (e: 'mark-unimportant', memoryId: string): void
    (e: 'close'): void
  }>()
  ```

### 实现步骤
1. 创建 `MemoryNodeDetail.vue`（`<script setup lang="ts">`）：
   - import `MemoryDetail`、`RelatedNode` from `@/models/memory-graph`
   - import Element Plus 组件：`ElDialog`、`ElInput`、`ElButton`、`ElMessageBox`、`ElTag`、`ElDescriptions`、`ElDescriptionsItem`、`ElMessage`
   - import 时间格式化工具
2. 实现详情展示区（使用 `ElDescriptions`）：
   - 记忆内容（content，多行文本）
   - 类型（memory_type，用 `ElTag` 着色）
   - 置信度（confidence，百分比）
   - 来源对话（source_conversation_id，可点击跳转）
   - 创建时间（created_at，绝对 + 相对时间）
   - 最后访问时间（last_accessed_at）
3. 实现关联节点列表：
   - 标题"关联节点"
   - 列表展示每个 `RelatedNode`：content（截断 50 字）+ memory_type 标签 + 关联强度（strength，进度条或百分比）
   - 点击关联节点可触发跳转（emit 父组件加载该节点详情）
4. 实现 5 个操作按钮（底部按钮区）：
   - 编辑：打开 `ElDialog`，内含 `ElInput type="textarea"` 编辑 newContent，确认后 `emit('edit', memoryId, newContent)`
   - 软删除：`ElMessageBox.confirm('确认软删除？删除后可恢复', '提示', { type: 'warning' })` 确认后 `emit('soft-delete', memoryId)`
   - 彻底删除：`ElMessageBox.confirm('确认彻底删除？此操作不可恢复！', '危险操作', { type: 'error', confirmButtonText: '确认删除' })` 确认后 `emit('hard-delete', memoryId)`
   - 降低权重：打开小 Dialog 输入 decayFactor（默认 0.5），确认后 `emit('decay', memoryId, decayFactor)`
   - 标记不再重要：`ElMessageBox.confirm` 确认后 `emit('mark-unimportant', memoryId)`（内部调 decay 到极低值或软删除）
5. 关闭按钮：`emit('close')`
6. loading 状态显示骨架屏。
7. detail 为 null 时不渲染面板（或显示空状态 ElEmpty）。
8. 编辑 Dialog 中的 newContent 初始值为 detail.content，最大长度 10000。
9. 操作按钮根据权限/状态禁用（如已软删除的节点禁用编辑按钮）。

### 验收标准
- [ ] 详情展示完整：记忆内容/类型/置信度/来源对话/创建时间/最后访问时间
- [ ] 关联节点列表展示 content + memory_type + 关联强度
- [ ] 5 个操作按钮可用：编辑/软删除/彻底删除/降低权重/标记不再重要
- [ ] 编辑用 `ElDialog` + `ElInput type="textarea"`
- [ ] 删除用 `ElMessageBox.confirm` 确认
- [ ] 各操作 emit 对应事件，payload 正确
- [ ] loading 状态显示骨架屏
- [ ] detail 为 null 时显示空状态
- [ ] `cd ui && npx vue-tsc --noEmit` 类型检查通过

### 关联架构文档章节
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §10 `GET /memory/{memory_id}` 响应（MemoryDetail）
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §10 PUT/DELETE/decay 端点（对应 5 个操作）

---

## F5：记忆管理页面（重写）

### 任务编号
F5

### 任务名
MemoryView 记忆管理页面重写

### 目标
重写 `MemoryView.vue`，集成 F2 聚类视图 + F3 子图视图 + F4 节点详情面板，实现三视图联动（选聚类→加载子图→选节点→显示详情），移除旧的 candidates/settings Tab 设计。

### 输入
- F1 API 服务：`getMemoryGraph`、`getClusterSubgraph`、`getMemoryDetail`
- F2 组件：`MemoryClusterView`
- F3 组件：`MemoryGraphView`
- F4 组件：`MemoryNodeDetail`
- Element Plus 布局组件（`ElContainer`、`ElAside`、`ElMain`、`ElHeader`）

### 输出
- 文件路径：`ui/src/views/settings/MemoryView.vue`（重写，覆盖原 623 行）
- 页面布局结构：
  ```
  ┌─────────────────────────────────────────────┐
  │  顶部：搜索栏 + 过滤器 + 健康状态指示          │
  ├──────────────┬──────────────────────────────┤
  │ 左侧（30%）   │ 右侧（70%）                   │
  │ F2 聚类视图   │ F3 子图视图（力导向）          │
  │ 6 个区块      │ 节点+边渲染                    │
  │              │                              │
  ├──────────────┴──────────────────────────────┤
  │ 底部/弹出：F4 节点详情面板（选中节点时显示）    │
  └─────────────────────────────────────────────┘
  ```

### 实现步骤
1. 重写 `MemoryView.vue`（`<script setup lang="ts">`），清空旧内容（移除 candidates/settings Tab 相关代码）。
2. import F1 服务函数：`getMemoryGraph`、`getClusterSubgraph`、`getMemoryDetail`、`editMemory`、`softDeleteMemory`、`hardDeleteMemory`、`decayMemory`、`getMemoryHealth`。
3. import F2/F3/F4 组件：`MemoryClusterView`、`MemoryGraphView`、`MemoryNodeDetail`。
4. import Element Plus 组件与 ElMessage。
5. 定义响应式状态：
   ```typescript
   const userId = ref<string>(currentUserId)  // 从 useAuth 获取当前用户 ID
   const graphData = ref<MemoryGraphData | null>(null)  // 聚类总览
   const selectedClusterType = ref<string>('')  // 当前选中聚类类型
   const subgraph = ref<ClusterSubgraph | null>(null)  // 当前聚类子图
   const selectedNodeId = ref<string>('')  // 当前选中节点 ID
   const nodeDetail = ref<MemoryDetail | null>(null)  // 节点详情
   const loadingGraph = ref(false)
   const loadingSubgraph = ref(false)
   const loadingDetail = ref(false)
   const healthStatus = ref<MemoryHealth | null>(null)
   ```
6. 实现 `loadGraphData()`：调用 `getMemoryGraph(userId.value)`，设置 `graphData`。
7. 实现 `onSelectCluster(type: string)`：
   - 设置 `selectedClusterType`
   - 调用 `getClusterSubgraph(userId.value, type)`，设置 `subgraph`
   - 清空 `selectedNodeId` 和 `nodeDetail`
8. 实现 `onSelectNode(nodeId: string)`：
   - 设置 `selectedNodeId`
   - 调用 `getMemoryDetail(nodeId)`，设置 `nodeDetail`
   - 显示 F4 详情面板（弹出或底部展开）
9. 实现 F4 操作回调：
   - `onEdit(memoryId, newContent)`：调用 `editMemory`，成功后刷新详情 + ElMessage.success
   - `onSoftDelete(memoryId)`：调用 `softDeleteMemory`，成功后刷新子图 + 详情关闭
   - `onHardDelete(memoryId)`：调用 `hardDeleteMemory`，成功后刷新子图 + 详情关闭
   - `onDecay(memoryId, decayFactor)`：调用 `decayMemory`，成功后刷新详情
   - `onMarkUnimportant(memoryId)`：调用 `decayMemory(memoryId, 0.01)`（降到极低）
10. 实现 `loadHealthStatus()`：调用 `getMemoryHealth()`，显示依赖健康状态指示器（Neo4j/pgvector/Redis 状态点）。
11. `onMounted` 时调用 `loadGraphData()` + `loadHealthStatus()`。
12. 模板布局：
    - `ElContainer` 垂直布局
    - `ElHeader`：标题"我的记忆" + 健康状态指示器 + 刷新按钮
    - `ElContainer` 水平布局：
      - `ElAside width="30%"`：`<MemoryClusterView :clusters="graphData?.clusters" @select-cluster="onSelectCluster" />`
      - `ElMain`：`<MemoryGraphView :subgraph="subgraph" @select-node="onSelectNode" />`
    - 底部/弹出：`<MemoryNodeDetail :detail="nodeDetail" @edit="onEdit" @soft-delete="onSoftDelete" @hard-delete="onHardDelete" @decay="onDecay" @mark-unimportant="onMarkUnimportant" @close="onCloseDetail" />`
13. 不再有 candidates/settings Tab（旧设计完全移除）。
14. 错误处理：API 失败时显示 ElMessage.error，不阻塞页面。
15. 响应式：移动端切换为垂直布局（聚类在上、子图在下）。

### 验收标准
- [ ] 三个组件（F2 聚类视图、F3 子图视图、F4 节点详情）正确集成
- [ ] 三视图联动：选聚类→加载子图→选节点→显示详情
- [ ] 不再有 candidates/settings Tab（旧设计移除）
- [ ] 5 个操作（编辑/软删除/彻底删除/降低权重/标记不再重要）正确调用 API 并刷新视图
- [ ] 健康状态指示器显示 Neo4j/pgvector/Redis 状态
- [ ] 数据正确加载：onMounted 时加载聚类总览
- [ ] 错误处理：API 失败显示 ElMessage.error
- [ ] 响应式：移动端垂直布局
- [ ] `cd ui && npx vue-tsc --noEmit` 类型检查通过
- [ ] `cd ui && npx vitest run` 测试通过

### 关联架构文档章节
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §10 API 接口定义（页面调用的全部端点）
- `docs/prd/memory-system/execution/00-overview.md` 代码目录结构规划（MemoryView.vue 重写）

---

## F6：路由更新 + 导航菜单

### 任务编号
F6

### 任务名
路由配置更新与导航菜单调整

### 目标
更新路由配置确保 MemoryView 使用新组件（F5 重写后的），导航菜单"我的记忆"指向新页面，路由 name 与 meta 保持一致。

### 输入
- 现有路由配置：`ui/src/router/index.ts`（已有 `path: 'memory', name: 'user-memory-list'` 指向 `MemoryView.vue`）
- 现有导航菜单配置（侧边栏/设置页入口）
- F5 重写后的 `MemoryView.vue`

### 输出
- 文件路径：
  - 修改 `ui/src/router/index.ts`（路由配置已存在，验证 name/meta 正确）
  - 修改导航菜单配置文件（如 `ui/src/layouts/` 或 `ui/src/config/` 下的菜单定义）
- 路由定义：
  ```typescript
  {
    path: 'memory',
    name: 'user-memory-list',
    component: () => import('@/views/settings/MemoryView.vue'),
    meta: { requiresAuth: true, title: '我的记忆' },
  }
  ```

### 实现步骤
1. 检查 `ui/src/router/index.ts` 中 `path: 'memory'` 路由定义：
   - 确认 `component` 指向 `@/views/settings/MemoryView.vue`（F5 重写后的）
   - 确认 `name: 'user-memory-list'`（保持不变，避免破坏现有链接）
   - 添加 `meta.title: '我的记忆'`（若不存在）
   - 确认 `meta.requiresAuth: true`
2. 查找导航菜单配置（搜索 `memory` 或 `我的记忆` 关键词，定位菜单定义文件）：
   - 可能在 `ui/src/layouts/AdminLayout.vue`、`ui/src/config/` 或 i18n messages 中
   - 确保菜单项"我的记忆"的路由跳转目标为 `{ name: 'user-memory-list' }` 或 `/settings/memory`（根据实际上下文路径）
3. 更新菜单项文案（若需要）：使用 i18n key `menu.memory` 或 `memory.title`。
4. 验证从首页/导航栏点击"我的记忆"能正确跳转到新页面。
5. 若导航菜单有图标，确认图标与新记忆图谱主题一致（如 `IconStorage` 或图谱类图标）。
6. 确保路由守卫（`requiresAuth`）生效，未登录用户跳转到登录页。

### 验收标准
- [ ] 路由 `path: 'memory'` 指向重写后的 `MemoryView.vue`
- [ ] 路由 name 保持 `user-memory-list`（不破坏现有链接）
- [ ] `meta.requiresAuth: true` 生效
- [ ] 导航菜单"我的记忆"指向新页面，点击可正确跳转
- [ ] 未登录用户访问该路由跳转到登录页
- [ ] 页面标题显示"我的记忆"
- [ ] `cd ui && npx vue-tsc --noEmit` 类型检查通过

### 关联架构文档章节
- `docs/prd/memory-system/execution/00-overview.md` 代码目录结构规划
- 现有路由配置 `ui/src/router/index.ts`（`path: 'memory'`）

---

## Track F 整体验收

- [ ] F1-F6 全部完成
- [ ] `cd ui && npx vue-tsc --noEmit` 类型检查通过
- [ ] `cd ui && npx vitest run` 单元测试通过
- [ ] 旧文件 `ui/src/services/user-memory.ts` 和 `ui/src/models/memory.ts` 已删除
- [ ] 旧组件 `MemoryConfirmationCard.vue` 不再被引用（删除由 Track G 处理）
- [ ] 新页面三视图联动：聚类视图 → 子图视图 → 节点详情
- [ ] 力导向图渲染 ≤200 节点，性能流畅
- [ ] 5 个节点操作（编辑/软删除/彻底删除/降低权重/标记不再重要）可用
- [ ] 导航菜单"我的记忆"可访问新页面
- [ ] 移动端响应式布局正常
