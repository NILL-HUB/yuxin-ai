# 工作流编排 + 应用编排 全量开发路线图

> **状态**：待确认
> **创建日期**：2026-07-04
> **基于**：架构设计文档 + 业界调研（Dify/Coze/n8n/FastGPT）+ 现状 Gap 分析

## 一、总体目标

将现有的"工作流编排系统"和"应用编排系统"从"admin 端复用 space 端组件"的半成品状态，升级为：
- admin 端独立化编排能力（跨账号资源选择、全平台池范围、池治理字段编辑）
- 参考 Dify/Coze 重写执行引擎与编排架构
- 扩展高级节点（循环/子流程/意图识别）
- 新增应用类型（Workflow/Completion）
- 补齐所有功能 Gap

## 二、现状摘要

### 已具备（可复用）
- 后端：12 种工作流节点 + LangGraph StateGraph 引擎 + OrchestratorService + DAGEngine
- 后端：AppConfig 14 字段 + AppConfigVersion 版本管理 + 24 个用户端 API + 8 个 admin API
- 前端：Vue Flow 画布 + 12 节点组件 + 14 个 AbilityItem 组件
- 画布 P0 bug 已修复（布局容器尺寸冲突）

### 主要 Gap
| # | Gap | 影响 |
|---|-----|------|
| G1 | admin 编排画布完全复用 space 端组件，能力边界模糊 | admin 无法跨账号选择资源/编辑池治理字段 |
| G2 | Workflow 缺版本历史表（对比 AppConfigVersion） | 工作流无法回滚到任意历史版本 |
| G3 | admin AppsView 缺状态筛选 + 批量操作 | 列表管理体验差 |
| G4 | page_size 上限 50 与硬约束（100）冲突 | 分页不一致 |
| G5 | app_service.py 2578 行未拆分 | 可维护性差 |
| G6 | RoutingDecision 响应字段不完整 | 调试可观测性弱 |
| G7 | 缺循环/子流程/意图识别等高级节点 | 编排能力不足 |
| G8 | 应用类型仅 Chatbot/Agent，缺 Workflow/Completion | 应用场景受限 |

## 三、计划拆分（4 个独立计划，可并行）

### 计划 A：工作流编排 admin 端独立化 + Gap 补齐
**目标**：admin 端工作流编排画布独立，补齐版本历史/批量操作/状态筛选等 Gap
**依赖**：无（可立即开始）
**预计任务数**：~25 个 bite-sized 任务

**范围**：
1. 后端：新增 WorkflowVersion 表 + 版本历史/回滚 API
2. 后端：admin_workflow_service page_size 上限改 100
3. 后端：admin 工作流批量发布/下架 API
4. 后端：RoutingDecision 响应扩展（agent_subset/tool_subset/cost_policy）
5. 前端：AdminWorkflowDetailView 独立化（不再复用 space 端组件）
6. 前端：admin 画布支持跨账号资源选择（工具/知识库/工作流选择器走 admin API）
7. 前端：admin 画布支持池治理字段编辑（agent_metadata）
8. 前端：AdminWorkflowsView 补齐状态筛选 + 批量操作
9. 前端：版本历史抽屉 + 回滚 UI

**关键文件**：
- 后端：`api/internal/model/workflow.py`、`api/internal/service/workflow_service.py`、`api/internal/handler/admin_workflow_handler.py`、`api/internal/schema/admin_workflow_schema.py`
- 前端：`ui/src/views/admin/workflows/AdminWorkflowDetailView.vue`、`ui/src/views/admin/AdminWorkflowsView.vue`、`ui/src/services/admin-workflows.ts`

---

### 计划 B：工作流执行引擎重写 + 高级节点扩展
**目标**：参考 Dify 重写 DAG 执行引擎（VariablePool + {{#node.var#}} + SSE 流式节点事件），新增循环/子流程/意图识别节点
**依赖**：建议在计划 A 完成后开始（避免冲突），但可并行设计
**预计任务数**：~35 个 bite-sized 任务

**范围**：
1. 后端：实现 VariablePool（系统变量 + 节点输出变量 + 会话变量）
2. 后端：实现 {{#node_id.field#}} 引用语法解析器
3. 后端：重写 GraphEngine（拓扑排序 + 并行 wave + SSE 流式事件）
4. 后端：WorkflowRun + WorkflowNodeExecution 表（执行历史）
5. 后端：新增 ITERATION 循环节点（数组遍历）
6. 后端：新增 SubWorkflow 子流程节点（workflow 调用 workflow）
7. 后端：新增 IntentClassifier 意图识别节点（文本分类打标）
8. 后端：节点级 retry 配置（retry_on_fail/max_tries/retry_interval）
9. 前端：3 个新节点的画布组件 + 信息面板
10. 前端：SSE 流式调试面板（节点级输入输出实时展示）
11. 前端：执行历史面板（节点级回放）

**关键文件**：
- 后端：`api/internal/core/workflow/workflow.py`、`api/internal/core/workflow/nodes/`、`api/internal/service/workflow_service.py`、`api/internal/model/workflow.py`
- 前端：`ui/src/views/space/workflows/components/`、`ui/src/views/admin/workflows/`

---

### 计划 C：应用编排 admin 端独立化 + Gap 补齐
**目标**：admin 端应用编排画布独立，app_service.py 拆分，补齐 Gap
**依赖**：无（可立即开始，与计划 A 并行）
**预计任务数**：~25 个 bite-sized 任务

**范围**：
1. 后端：app_service.py 拆分（按 debug_chat/publish/runtime_tools/agent_binding 四大职责）
2. 后端：admin_app_service page_size 上限改 100
3. 后端：admin 应用批量下架/删除 API
4. 后端：RoutingDecision 响应扩展（与计划 A 共享）
5. 前端：AdminAppDetailView 独立化（不再复用 space 端 AgentAppAbility）
6. 前端：admin 画布支持跨账号资源选择（工具/MCP/Skill/工作流/Agent 绑定选择器走 admin API）
7. 前端：admin 画布支持池治理字段编辑（primary_pool/risk_level/model_tier/routing_priority）
8. 前端：AdminAppsView 补齐状态筛选 + 批量操作

**关键文件**：
- 后端：`api/internal/service/app_service.py`、`api/internal/service/admin_app_service.py`、`api/internal/handler/admin_app_handler.py`
- 前端：`ui/src/views/admin/apps/AdminAppDetailView.vue`、`ui/src/views/admin/AppsView.vue`、`ui/src/services/admin-apps.ts`

---

### 计划 D：应用编排架构重写 + 新增应用类型
**目标**：参考 Dify 重写应用-工作流绑定关系，新增 Workflow/Completion 应用类型
**依赖**：建议在计划 C 完成后开始（避免冲突），但可并行设计
**预计任务数**：~30 个 bite-sized 任务

**范围**：
1. 后端：App 模型扩展 app_type（chatbot/agent/workflow/completion）
2. 后端：Workflow 应用类型实现（绑定一个 workflow，对话式调用工作流）
3. 后端：Completion 应用类型实现（单轮文本生成，无对话记忆）
4. 后端：应用-工作流绑定关系重写（应用本身可绑定 graph 配置）
5. 后端：会话变量持久化（ConversationVariable 表）
6. 前端：应用类型选择器（4 种类型）
7. 前端：Workflow 应用编辑器（内嵌工作流画布）
8. 前端：Completion 应用编辑器（单轮文本生成配置）
9. 前端：会话变量管理 UI

**关键文件**：
- 后端：`api/internal/model/app.py`、`api/internal/service/app_service.py`、`api/internal/entity/app_entity.py`
- 前端：`ui/src/views/admin/apps/`、`ui/src/views/space/apps/`

## 四、并行开发策略

```
时间轴 ──────────────────────────────────────────────────────►

计划 A（工作流 admin 独立化）  ████████░░░░░░░░░░░░░░░░░░░░░░
计划 C（应用 admin 独立化）    ░░░░░░░░████████░░░░░░░░░░░░░░░
                                ↑ 并行阶段 1（admin 独立化 + Gap 补齐）

计划 B（工作流引擎重写）       ░░░░░░░░░░░░░░░░████████████░░░░
计划 D（应用架构重写）         ░░░░░░░░░░░░░░░░░░░░░░░░████████
                                ↑ 并行阶段 2（引擎重写 + 新类型）
```

**并行阶段 1**（立即开始）：计划 A + 计划 C 并行
- 两者无文件冲突（A 改 workflow，C 改 app）
- 共享 RoutingDecision 响应扩展（在 A 中实现，C 直接复用）

**并行阶段 2**（阶段 1 完成后）：计划 B + 计划 D 并行
- B 改工作流引擎，D 改应用架构
- 共享会话变量设计（在 B 中实现，D 直接复用）

## 五、技术决策

| 决策点 | 选型 | 理由 |
|--------|------|------|
| 画布库 | Vue Flow（已在用） | 已验证，无需替换 |
| 变量引用语法 | {{#node_id.field#}} | Dify 风格，比 Jinja2 更适合 DAG |
| 流式通信 | SSE | 节点执行状态实时推送 |
| 执行引擎 | 自研 GraphEngine（参考 Dify） | AI 工作流场景特殊，第三方库不契合 |
| 版本管理 | draft/published + Version 表 | 对标 AppConfigVersion |
| 代码沙箱 | 复用现有 SCF/沙箱执行器 | 已实现，无需重写 |

## 六、风险与缓解

| 风险 | 缓解 |
|------|------|
| 两套图执行引擎并存（LangGraph + DAGEngine） | 计划 B 统一为 GraphEngine，废弃 LangGraph 路径 |
| admin/space 复用边界模糊 | 计划 A/C 独立化 admin 组件，用 route.meta.realm 强类型判定 |
| app_service.py 拆分风险 | 计划 C 先拆分再加新功能，保留原接口签名 |
| 引擎重写影响现有工作流 | 计划 B 提供 graph 迁移脚本，旧 graph 自动转换 |

## 七、下一步

请确认：
1. 路线图方向是否正确？
2. 并行阶段 1（计划 A + 计划 C）是否立即开始？
3. 是否需要调整优先级或范围？

确认后，我将为计划 A 和计划 C 分别制定详细的 bite-sized 实现步骤。
