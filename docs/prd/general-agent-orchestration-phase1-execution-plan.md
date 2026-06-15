# 通用 Agent 调度平台 Phase 1 任务执行文档

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | 通用 Agent 调度平台 Phase 1 任务执行文档 |
| 关联 PRD | `docs/prd/general-agent-orchestration-prd.md` |
| 适用代码库 | OpenAgent 当前仓库 |
| 执行方式 | 严格按任务顺序执行，完成一项勾选一项 |
| 核心门禁 | 每项任务完成后必须在 Docker 中全量跑通，才能进入下一项 |

## 2. 执行原则

### 2.1 单任务推进原则

每次只允许推进一个任务。

```text
开始任务 N
  -> 修改代码
  -> 补单元测试 / 集成测试
  -> 本地快速测试
  -> Docker 全量构建和运行
  -> Docker 内执行后端测试
  -> Docker 构建前端并通过类型检查 / lint / unit test
  -> 完成端到端冒烟验证
  -> 勾选任务 N
  -> 才能开始任务 N+1
```

### 2.2 Docker 全量门禁原则

任何任务不得只在本地 Python / Node 环境中验证后就进入下一项。必须在 Docker 栈中跑通。

默认 Docker 门禁命令：

```bash
cd docker
docker compose down
docker compose up -d --build
docker compose ps
docker compose logs --tail=200 llmops-api
docker compose logs --tail=200 llmops-celery
docker compose logs --tail=200 llmops-ui
```

API 健康检查：

```bash
curl http://127.0.0.1:5001/healthz
```

后端测试：

```bash
cd docker
docker compose exec llmops-api pytest
```

前端检查：

```bash
cd ..
docker build --target builder -t llmops-ui-check:phase1 -f ui/Dockerfile .
docker run --rm llmops-ui-check:phase1 sh -lc "npm run type-check && npm run lint && npm run test:unit -- --run"
```

前端构建门禁由 `docker compose up -d --build` 覆盖，因为 `ui/Dockerfile` 会执行：

```bash
npm run build
```

### 2.3 失败处理原则

如果任意门禁失败：

1. 不允许勾选当前任务。
2. 不允许进入下一任务。
3. 必须记录失败原因。
4. 修复后重新执行当前任务的完整 Docker 门禁。
5. 不允许只重跑失败的单个测试替代完整门禁。

### 2.4 数据库策略

当前系统无必须保留的旧数据，因此 Phase 1 可以按目标架构直接重构数据库模型。

执行策略：

- 可以新增、重命名或重建表。
- 不需要写复杂历史数据迁移兼容逻辑。
- Alembic migration 仍需保持从空数据库可完整升级。
- Docker 全量验证时允许清理 `docker/volumes/` 后重建。

Windows PowerShell 清库重建命令：

```powershell
cd docker
docker compose down
Remove-Item -Recurse -Force .\volumes
docker compose up -d --build
```

如果在 Linux/macOS 环境执行：

```bash
cd docker
docker compose down
rm -rf volumes/
docker compose up -d --build
```

## 3. Phase 1 总目标

Phase 1 的目标不是一次性完成完整通用调度平台，而是先建立可持续演进的骨架。

Phase 1 必须交付：

1. Orchestrator 结构化调度骨架。
2. Agent 子池标签与基础路由元数据。
3. Tool Pool 元数据与风险等级治理。
4. 知识库作用域重构，包括系统级知识库、用户长期记忆库、用户资料内容库。
5. 外部数据源连接模型与手动同步基础能力。
6. 用户长期记忆三次高置信触发和确认保存闭环。
7. 高风险工具统一确认 UI 和后端确认流。
8. 实时计费统一事件和前端展示。
9. 管理员可观测日志基础。
10. Docker 全量跑通的端到端验收。

Phase 1 明确不做：

- 完整多 Agent 并行编排。
- 完整自动 Agent / Tool 质量评分。
- 支付、删除、权限变更类真实高风险工具执行。
- 图片 OCR / 视觉理解深度入库。
- 视频抽帧 / 字幕提取 / 视频理解入库。
- 音频 ASR / 说话人切分 / 转写入库。
- 复杂审批流。
- 复杂历史数据迁移兼容。

## 4. 当前系统基础

### 4.1 已有后端基础

当前后端已经具备：

- Flask API。
- SQLAlchemy 模型。
- Alembic migration。
- Celery。
- Redis。
- PostgreSQL。
- Weaviate。
- Assistant Agent。
- PublicAgentA2AService。
- MCP Provider。
- Dataset / Document / Segment。
- AppConfig datasets / MCP / workflow 绑定。
- Admin/User 双身份体系。
- Billing / Credit 基础模型。
- SSE / OpenAPI Chat 基础能力。

### 4.2 已有前端基础

当前前端已经具备：

- Vue 3。
- Pinia。
- Arco Design。
- 首页对话入口。
- 配置中心页面。
- Dataset 页面。
- Admin 页面。
- Billing 页面。
- hooks / services / models 分层。
- Vitest 单元测试。
- type-check / lint / build 流程。

### 4.3 Docker 基础

当前 Docker 栈包括：

- `llmops-api`
- `llmops-celery`
- `llmops-ui`
- `llmops-db`
- `llmops-redis`
- `llmops-weaviate`
- `llmops-nginx`

Docker Compose 文件：

```text
docker/docker-compose.yaml
```

## 5. 全局任务链条

任务必须按以下顺序执行。

| 顺序 | 任务 | 是否可并行 | 完成条件 |
| --- | --- | --- | --- |
| 0 | 建立 Phase 1 基线门禁 | 否 | Docker 全量跑通当前系统 |
| 1 | 重构知识库和记忆数据模型 | 否 | 新空库 migration + 测试通过 |
| 2 | 实现 Orchestrator 调度骨架 | 否 | `/home` 或 assistant 入口有结构化决策且原流程可 fallback |
| 3 | 实现 Agent 子池元数据 | 否 | 管理员可配置基础标签，路由可读取 |
| 4 | 实现 Tool Pool 元数据和风险等级 | 否 | 工具候选可按风险和权限过滤 |
| 5 | 实现知识库三层作用域 | 否 | system / user_memory / user_content 隔离通过 |
| 6 | 实现外部数据源基础模型 | 否 | 可创建连接、授权状态、手动同步记录 |
| 7 | 实现长期记忆候选和确认保存 | 否 | 三次高置信触发、用户确认后保存 |
| 8 | 实现高风险工具确认协议 | 否 | 后端阻断未确认调用，前端展示统一确认 UI |
| 9 | 实现实时计费事件协议 | 否 | SSE 推送 billing 事件，前端只展示已发生消耗 |
| 10 | 实现调度日志和管理员观测基础 | 否 | 管理员可查看调度决策、过滤原因和成本事件 |
| 11 | 端到端验收和文档同步 | 否 | 完整 Docker 全量验收通过 |

## 6. 任务 0：建立 Phase 1 基线门禁

### 6.1 目标

在开始改代码前，确认当前系统可以在 Docker 中完整构建、启动和测试。

### 6.2 执行清单

- [x] 确认 `api/.env` 存在。
- [x] 确认 `api/.env` 中 `VITE_API_PREFIX` 已配置。
- [x] 确认 Docker 可用。
- [x] 执行 Docker 全量构建。
- [x] 执行 API 健康检查。
- [x] 执行后端测试。
- [x] 执行前端 type-check、lint、unit test。
- [x] 记录基线结果。

### 6.3 命令

```bash
cd docker
docker compose down
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:5001/healthz
docker compose exec llmops-api pytest
cd ..
docker build --target builder -t llmops-ui-check:phase1 -f ui/Dockerfile .
docker run --rm llmops-ui-check:phase1 sh -lc "npm run type-check && npm run lint && npm run test:unit -- --run"
```

### 6.4 验收标准

- [x] 所有容器正常启动。
- [x] `llmops-api` healthcheck 为 healthy。
- [x] `/healthz` 返回成功。
- [x] 后端 `pytest` 通过：1934 passed, 6 skipped。
- [x] 前端 `type-check` 通过。
- [x] 前端 `lint` 通过。
- [x] 前端 `test:unit` 通过：89 files / 332 tests passed。
- [x] 当前任务勾选完成后，才允许进入任务 1。

## 7. 任务 1：重构知识库和记忆数据模型

### 7.1 目标

建立 Phase 1 的核心数据模型，直接按目标架构重构，不为旧数据兼容让步。

### 7.2 后端改动范围

建议新增或重构模型：

- `KnowledgeBase`
- `KnowledgeDocument`
- `KnowledgeSegment`
- `UserMemory`
- `MemoryCandidate`
- `ExternalDataSource`
- `BillingEvent`
- `ToolConfirmation`
- `RoutingLog`

建议保留兼容服务名但内部切换新模型：

- `DatasetService`
- `DocumentService`
- `SegmentService`
- `RetrievalService`

核心字段：

| 字段 | 适用模型 | 说明 |
| --- | --- | --- |
| `knowledge_scope` | KnowledgeBase | system / tenant / project / user_memory / user_content |
| `owner_account_id` | KnowledgeBase / UserMemory | 用户归属 |
| `owner_admin_user_id` | KnowledgeBase | 管理员上下文归属 |
| `operation_context` | KnowledgeBase | user / admin / system_job |
| `visibility_scope` | KnowledgeBase | private / team / tenant / public / internal |
| `target_tenant_id` | KnowledgeBase | 租户级归属 |
| `target_project_id` | KnowledgeBase | 项目级归属 |
| `created_from` | KnowledgeBase / UserMemory | manual_upload / conversation_memory / admin_config / external_sync |
| `source_type` | ExternalDataSource | lark / notion / drive / github / enterprise_knowledge |
| `authorization_status` | ExternalDataSource | pending / granted / revoked / expired |
| `sync_status` | ExternalDataSource | idle / syncing / success / failed |

### 7.3 执行清单

- [ ] 新增或重构 SQLAlchemy 模型。
- [ ] 新增 Alembic migration。
- [ ] 更新 schema/entity。
- [ ] 更新 service 层最小 CRUD。
- [ ] 更新测试工厂和 fixtures。
- [ ] 覆盖管理员双身份归属测试。
- [ ] 覆盖 system / user_memory / user_content 作用域测试。
- [ ] 从空数据库执行 migration 成功。
- [ ] Docker 全量门禁通过。

### 7.4 验收标准

- [ ] 空库可完整 migration。
- [ ] 管理员在普通用户上下文创建的资料归入自己的 user_content。
- [ ] 管理员在配置中心创建 system 知识库时记录 `owner_admin_user_id`。
- [ ] 普通用户无法写入 system 知识库。
- [ ] 用户 A 无法读取用户 B 的 user_memory / user_content。
- [ ] Docker 全量门禁通过。

### 7.5 Docker 门禁

必须执行任务 0 的完整命令。

额外执行：

```bash
cd docker
docker compose exec llmops-api flask db upgrade --directory internal/migration
```

## 8. 任务 2：实现 Orchestrator 调度骨架

### 8.1 目标

在现有 Assistant Agent 执行前增加结构化调度决策层。

### 8.2 后端改动范围

建议新增：

- `internal/service/orchestrator_service.py`
- `internal/service/task_classifier_service.py`
- `internal/entity/orchestrator_entity.py`
- `internal/schema/orchestrator_schema.py`

核心结构：

```json
{
  "intent": "general_qa",
  "complexity": "simple",
  "execution_mode": "direct_answer",
  "needs_tools": false,
  "needs_agent": false,
  "needs_multi_agent": false,
  "recommended_model_tier": "cheap",
  "risk_level": "safe",
  "reason": "用户问题是简单常识问答"
}
```

### 8.3 执行清单

- [ ] 定义 `RoutingDecision`。
- [ ] 实现 `TaskClassifier` 规则版最小分类。
- [ ] 实现 `OrchestratorService.decide()`。
- [ ] 在 `/home` 或 assistant 入口前接入调度决策。
- [ ] 决策失败 fallback 到原流程。
- [ ] 决策结果写入 `RoutingLog` 或 agent thought。
- [ ] 增加单元测试。
- [ ] 增加入口集成测试。
- [ ] Docker 全量门禁通过。

### 8.4 验收标准

- [ ] 简单问题产生 `direct_answer`。
- [ ] 明确垂直任务产生 `single_agent`。
- [ ] 工具类问题产生 `needs_tools=true`。
- [ ] 高风险任务产生 `reject_or_confirm`。
- [ ] 原 assistant 流式响应不被破坏。
- [ ] Docker 全量门禁通过。

## 9. 任务 3：实现 Agent 子池元数据

### 9.1 目标

让现有 App / Assistant Agent 具备结构化 Agent 元数据，支持后续跨子池路由。

### 9.2 改动范围

建议扩展：

- `App` 或新增 `AgentMetadata`。
- `AdminAppService`。
- `AppService`。
- UI 配置中心 App 编辑页。

字段：

- `primary_pool`
- `secondary_pools`
- `capabilities`
- `task_types`
- `model_tier`
- `cost_level`
- `routing_priority`
- `allowed_tool_categories`

### 9.3 执行清单

- [ ] 后端模型增加 Agent 元数据。
- [ ] schema 增加字段校验。
- [ ] 管理员 API 支持读取/更新字段。
- [ ] 前端配置中心支持编辑主子池和标签。
- [ ] 增加默认值。
- [ ] 实现 `AgentCandidateCollector` 最小版本。
- [ ] 实现 `AgentPolicyFilter` 最小版本。
- [ ] 实现 `CrossPoolAgentSubsetBuilder` 最小版本。
- [ ] 测试 public / assigned App 候选合并。
- [ ] Docker 全量门禁通过。

### 9.4 验收标准

- [ ] 管理员可编辑 Agent 主子池。
- [ ] 管理员可编辑辅助子池标签。
- [ ] 未配置字段有默认值。
- [ ] `/home` 路由可读取结构化元数据。
- [ ] 未授权 App 不进入候选。
- [ ] Docker 全量门禁通过。

## 10. 任务 4：实现 Tool Pool 元数据和风险等级

### 10.1 目标

将 MCP、API Tool、Builtin Tool、知识检索工具统一治理为工具池候选。

### 10.2 改动范围

建议新增：

- `ToolMetadata`
- `ToolInventory`
- `ToolCandidateCollector`
- `ToolPolicyFilter`
- `CrossPoolToolSubsetBuilder`

字段：

- `tool_pool`
- `capabilities`
- `risk_level`
- `permission_scope`
- `cost_level`
- `health_status`
- `knowledge_scope`
- `tenant_scope`
- `user_scope`

### 10.3 执行清单

- [ ] 统一 MCP / API / Builtin / Knowledge tool 元数据结构。
- [ ] 管理员可设置工具风险等级。
- [ ] 实现风险等级过滤。
- [ ] 实现权限作用域过滤。
- [ ] 实现健康状态过滤。
- [ ] 实现工具候选输出结构。
- [ ] 暂缓真实高风险写操作执行。
- [ ] 增加单元测试。
- [ ] 增加集成测试。
- [ ] Docker 全量门禁通过。

### 10.4 验收标准

- [ ] safe 工具可进入候选。
- [ ] disabled / unhealthy 工具不进入候选。
- [ ] sensitive / dangerous 工具默认不自动执行。
- [ ] 工具过滤结果包含 `filtered_out_tools.reason`。
- [ ] Docker 全量门禁通过。

## 11. 任务 5：实现知识库三层作用域

### 11.1 目标

实现系统级知识库、用户长期记忆库、用户资料内容库的最小闭环和隔离。

### 11.2 执行清单

- [ ] 实现 `SystemKnowledgeService`。
- [ ] 实现 `UserMemoryService`。
- [ ] 实现 `UserContentKnowledgeService`。
- [ ] 知识库创建时必须明确 `knowledge_scope`。
- [ ] 管理员配置中心可创建 system 知识库。
- [ ] 用户资料页面可创建 user_content。
- [ ] `/home` 对话只能访问当前用户授权知识。
- [ ] 系统知识可被检索引用但普通用户不可写。
- [ ] 增加权限隔离测试。
- [ ] Docker 全量门禁通过。

### 11.3 验收标准

- [ ] system 知识库只能由 admin context 创建。
- [ ] user_memory 只能归属当前用户。
- [ ] user_content 只能归属当前用户或授权团队/项目。
- [ ] 管理员在 `/home` 上传资料不会进入 system。
- [ ] 管理员在配置中心创建 system 知识库会记录 admin 身份。
- [ ] Docker 全量门禁通过。

## 12. 任务 6：实现外部数据源基础模型

### 12.1 目标

支持用户资料内容库连接外部数据源，并提供手动同步基础能力。

### 12.2 第一阶段范围

优先支持通用抽象，不强制完成所有第三方深度集成。

外部来源类型：

- 飞书。
- Notion。
- 网盘。
- GitHub。
- 企业知识库。
- 业务系统导出资料。

### 12.3 执行清单

- [ ] 新增 `ExternalDataSource` 模型。
- [ ] 新增 source type 枚举。
- [ ] 新增授权状态字段。
- [ ] 新增同步状态字段。
- [ ] 新增手动同步 API。
- [ ] 同步结果写入 user_content 知识库。
- [ ] 第一阶段可使用 mock connector 或本地导入 connector。
- [ ] 增加授权状态测试。
- [ ] 增加同步状态测试。
- [ ] Docker 全量门禁通过。

### 12.4 验收标准

- [ ] 用户可以创建外部数据源连接记录。
- [ ] 用户可以触发手动同步。
- [ ] 同步后可检索文本 / 结构化资料。
- [ ] 用户 A 不能读取用户 B 的外部数据源。
- [ ] 媒体深度解析不作为本任务验收项。
- [ ] Docker 全量门禁通过。

## 13. 任务 7：实现长期记忆候选和确认保存

### 13.1 目标

实现用户长期记忆的三次高置信触发、确认弹窗和用户设置。

### 13.2 执行清单

- [ ] 实现 `MemoryCandidateExtractor`。
- [ ] 实现 `MemoryConfidenceTracker`。
- [ ] 同类偏好累计或连续出现 3 次后生成候选。
- [ ] 实现 `MemoryCandidate` 存储。
- [ ] 实现用户确认 API。
- [ ] 实现用户忽略 API。
- [ ] 实现后续自动保存策略。
- [ ] 实现永不保存和提醒策略。
- [ ] 前端实现长期记忆确认卡片。
- [ ] 用户设置中增加长期记忆开关。
- [ ] 增加单元测试和前端测试。
- [ ] Docker 全量门禁通过。

### 13.3 验收标准

- [ ] 相同偏好不足 3 次不弹窗。
- [ ] 相同偏好达到 3 次且高置信后弹窗。
- [ ] 用户保存后进入 UserMemory。
- [ ] 用户忽略后不写入。
- [ ] 用户选择自动保存后，后续高置信候选不再弹窗。
- [ ] 用户选择永不保存和提醒后，不再提示。
- [ ] Docker 全量门禁通过。

## 14. 任务 8：实现高风险工具确认协议

### 14.1 目标

实现统一高风险工具确认协议和前端 UI，确保模型不能绕过确认直接执行高风险工具。

### 14.2 执行清单

- [ ] 新增 `ToolConfirmation` 模型或实体。
- [ ] 新增确认状态：pending / confirmed / cancelled / expired。
- [ ] `ToolPolicyFilter` 对 sensitive / dangerous 返回 confirm_required。
- [ ] ToolInvoker 在未确认时拒绝执行。
- [ ] 实现确认创建 API。
- [ ] 实现确认执行 API。
- [ ] 实现取消 API。
- [ ] 前端实现统一确认 UI。
- [ ] 高风险确认 UI 展示当前已发生消耗。
- [ ] 增加绕过确认失败测试。
- [ ] Docker 全量门禁通过。

### 14.3 验收标准

- [ ] sensitive 工具触发确认卡片。
- [ ] dangerous 工具必须用户主动确认。
- [ ] 未确认时 ToolInvoker 不执行。
- [ ] 用户取消后任务继续汇总已完成内容。
- [ ] 确认 UI 字段符合 PRD。
- [ ] Docker 全量门禁通过。

## 15. 任务 9：实现实时计费事件协议

### 15.1 目标

统一模型、工具、Agent、A2A 的计费事件，用户侧只展示当前已发生消耗。

### 15.2 执行清单

- [ ] 新增 `BillingMetering`。
- [ ] 新增 `BillingEvent` 持久化。
- [ ] 定义 `billing_started`。
- [ ] 定义 `billing_delta`。
- [ ] 定义 `billing_summary`。
- [ ] 定义 `billing_cancelled`。
- [ ] 定义 `billing_final`。
- [ ] 接入模型 token usage。
- [ ] 接入工具调用成本。
- [ ] 接入高风险工具确认 UI 当前已消耗展示。
- [ ] 前端对话区展示当前已消耗。
- [ ] 前端停止按钮常驻可见。
- [ ] 用户停止后只展示已发生成本。
- [ ] Docker 全量门禁通过。

### 15.3 验收标准

- [ ] 长任务持续推送 `billing_delta`。
- [ ] 前端不展示预估最终成本。
- [ ] 停止后产生 `billing_cancelled`。
- [ ] 正常结束产生 `billing_final`。
- [ ] 高风险工具确认 UI 当前消耗与主 UI 一致。
- [ ] Docker 全量门禁通过。

## 16. 任务 10：实现调度日志和管理员观测基础

### 16.1 目标

让管理员可以看到每次主入口请求的调度决策、候选 Agent、候选工具、过滤原因和计费事件。

### 16.2 执行清单

- [ ] 新增或完善 `RoutingLog`。
- [ ] 记录 TaskClassifier 输出。
- [ ] 记录 Agent 候选和过滤原因。
- [ ] 记录 Tool 候选和过滤原因。
- [ ] 记录 knowledge_scope 命中情况。
- [ ] 记录 billing events。
- [ ] 管理员 API 支持分页查询。
- [ ] 管理员前端提供基础列表和详情。
- [ ] 普通用户不可访问调度日志。
- [ ] Docker 全量门禁通过。

### 16.3 验收标准

- [ ] 每次主入口请求生成 routing log。
- [ ] 管理员可以按用户、状态、模型、Agent、工具筛选。
- [ ] 普通用户访问返回 403。
- [ ] 日志中可看到 filtered_out reason。
- [ ] Docker 全量门禁通过。

## 17. 任务 11：端到端验收和文档同步

### 17.1 目标

确认 Phase 1 的所有核心能力在 Docker 中完整跑通，并同步文档。

### 17.2 端到端验收场景

- [ ] 普通用户简单问答，产生 direct_answer 决策。
- [ ] 普通用户垂直任务，产生 single_agent 决策。
- [ ] 用户资料查询，命中 user_content。
- [ ] 用户偏好问题，命中 user_memory。
- [ ] Agent 操作规范问题，命中 system knowledge。
- [ ] 管理员在 `/home` 上传资料，不进入 system。
- [ ] 管理员在配置中心创建 system knowledge，普通用户可检索引用但不可写。
- [ ] 用户外部数据源手动同步后可检索文本资料。
- [ ] 同类偏好出现 3 次后弹长期记忆确认。
- [ ] 用户选择永不保存和提醒后不再提示。
- [ ] 高风险工具触发统一确认 UI。
- [ ] 未确认高风险工具不会执行。
- [ ] 长任务持续推送 billing_delta。
- [ ] 用户停止任务后只扣已发生成本。
- [ ] 管理员可查看 routing log。

### 17.3 最终 Docker 全量门禁

```bash
cd docker
docker compose down
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:5001/healthz
docker compose exec llmops-api pytest
docker compose run --rm --entrypoint sh llmops-ui -c "cd /app/web && npm run type-check && npm run lint && npm run test:unit -- --run"
```

### 17.4 文档同步

- [ ] 更新 PRD 中 Phase 1 状态。
- [ ] 更新 README 或开发文档中的新环境变量。
- [ ] 更新 API 文档或接口说明。
- [ ] 更新管理员使用说明。
- [ ] 更新用户长期记忆和资料内容库说明。

### 17.5 最终验收标准

- [ ] Docker 全量构建通过。
- [ ] Docker 全服务启动通过。
- [ ] 后端测试通过。
- [ ] 前端 type-check 通过。
- [ ] 前端 lint 通过。
- [ ] 前端 unit test 通过。
- [ ] 端到端验收场景全部通过。
- [ ] 所有任务清单已勾选。

## 18. 每项任务完成记录模板

每完成一个任务，必须在任务下方补充记录。

```text
完成任务：任务 X - 标题
完成日期：YYYY-MM-DD
代码范围：
- api/internal/...
- ui/src/...
测试结果：
- docker compose up -d --build：通过 / 失败
- docker compose exec llmops-api pytest：通过 / 失败
- npm run type-check：通过 / 失败
- npm run lint：通过 / 失败
- npm run test:unit -- --run：通过 / 失败
端到端验证：通过 / 失败
遗留问题：无 / 说明
是否允许进入下一任务：是 / 否
```

## 19. 禁止事项

- 不允许跳过 Docker 全量门禁。
- 不允许多个任务混在一个提交或一次验收中。
- 不允许只改后端不跑前端门禁。
- 不允许只改前端不跑后端门禁。
- 不允许高风险工具绕过确认 UI。
- 不允许用户长期记忆静默写入。
- 不允许普通用户写入 system knowledge。
- 不允许管理员普通用户上下文写入 system knowledge。
- 不允许前端展示预估最终成本。
- 不允许媒体深度解析成为 Phase 1 阻塞项。

## 20. 推荐提交粒度

建议每个任务单独提交，提交前必须满足当前任务 Docker 全量门禁。

推荐提交顺序：

1. `feat(schema): add knowledge and orchestration phase1 models`
2. `feat(orchestrator): add routing decision skeleton`
3. `feat(agent): add pool metadata and candidate builder`
4. `feat(tool): add tool pool metadata and policy filter`
5. `feat(knowledge): add scoped system user memory and content services`
6. `feat(knowledge): add external data source sync foundation`
7. `feat(memory): add candidate confirmation flow`
8. `feat(tool): add high risk confirmation protocol`
9. `feat(billing): add realtime billing events`
10. `feat(admin): add routing observability panel`
11. `test(e2e): add phase1 docker acceptance coverage`

## 21. Phase 1 完成定义

Phase 1 完成必须同时满足：

1. 所有任务清单完成。
2. 每个任务都有完成记录。
3. 每个任务都通过 Docker 全量门禁。
4. 最终端到端验收通过。
5. PRD 与执行文档同步更新。
6. 无阻塞性遗留问题。

只有满足以上条件，才能进入 Phase 2。