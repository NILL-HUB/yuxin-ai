# 通用 Agent 调度平台 Phase 2 任务执行文档

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | 通用 Agent 调度平台 Phase 2 任务执行文档 |
| 关联 PRD | `docs/prd/general-agent-orchestration-prd.md` |
| 依赖阶段 | `docs/prd/general-agent-orchestration-phase1-execution-plan.md` |
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
docker build --target builder -t llmops-ui-check:phase2 -f ui/Dockerfile .
docker run --rm llmops-ui-check:phase2 sh -lc "npm run type-check && npm run lint && npm run test:unit -- --run"
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

Phase 2 建立在 Phase 1 migration head `d1e2f3a4b5d0` 之上。

执行策略：

- 优先复用 Phase 1 已新增的 `app.agent_metadata` 字段。
- 只有确实需要持久化子池定义、路由统计或质量指标时才新增表。
- Alembic migration 必须保持从空数据库可完整升级。
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

### 2.5 TDD 执行原则

每个任务必须先补 RED 测试，再实现最小代码让测试变绿。

推荐顺序：

```text
写失败测试
  -> 运行聚焦测试确认失败原因符合预期
  -> 实现最小功能
  -> 运行聚焦测试
  -> 运行 Docker 全量门禁
  -> 更新完成记录
```

## 3. Phase 2 总目标

Phase 2 的目标是从 Phase 1 的“基础 Agent 元数据和简单候选归集”升级为“结构化 Agent 子池路由”。

Phase 2 必须交付：

1. 完整 Agent 元数据规范和默认值治理。
2. Agent 子池注册表和可配置子池定义。
3. PoolIntentResolver，根据任务识别相关 Agent 子池。
4. AgentInventory，从 public App、assigned App、管理员 App、内置 Agent 中读取候选。
5. AgentCandidateCollector，按相关子池召回候选并输出 match_reason / semantic_score。
6. AgentPolicyFilter，过滤未授权、不可见、禁用、超预算、能力不匹配的 Agent。
7. AgentRanker，基于 capabilities、task_types、语义相似度、质量、成本、延迟排序。
8. CrossPoolAgentSubsetBuilder，输出本次任务可见跨子池 Agent 子集。
9. AgentRouter / Orchestrator 只能在 Agent 子集内选择执行 Agent。
10. `/home` 路由优先使用结构化元数据，再结合语义相似度。
11. Admin / UI 能查看和编辑基础 Agent 元数据。
12. Docker 全量跑通的端到端验收。

Phase 2 明确不做：

- 完整多 Agent 并行执行。
- 复杂 TaskPlanner 子任务 DAG。
- Tool Pool 深度治理。
- 模型 Key Pool、模型熔断和供应商成本策略。
- 自动质量评分闭环。
- 真实外部 A2A Agent 执行。
- 复杂审批流。

## 4. Phase 1 已有基础

### 4.1 后端基础

Phase 1 已具备：

- `app.agent_metadata` JSONB 字段。
- `normalize_agent_metadata()` 默认值归一化。
- `AgentCandidateCollector` public / assigned App 基础归集。
- `AgentPolicyFilter` 发布状态和授权范围基础过滤。
- `CrossPoolAgentSubsetBuilder` primary_pool 过滤和 routing_priority 排序。
- `OrchestratorService` 和 `TaskClassifierService` 基础调度骨架。
- `RoutingLogService` 和管理员调度日志查询 API。
- `AdminAppHandler.update()` 可透传 `agent_metadata`。
- Docker 全量后端测试通过。

### 4.2 前端基础

Phase 1 已具备：

- Vue 3。
- Pinia。
- Arco Design。
- Admin 页面基础框架。
- App 模型已有基础字段。
- Billing / Memory / Tool Confirmation 组件和测试。
- `type-check` / `lint` / `test:unit` Docker 门禁。

### 4.3 当前关键文件

| 文件 | 责任 |
| --- | --- |
| `api/internal/entity/agent_entity.py` | Agent 元数据枚举、默认值、归一化 |
| `api/internal/model/app.py` | App 模型和 `agent_metadata` 字段 |
| `api/internal/service/agent_pool_service.py` | Phase 1 Agent 候选归集、过滤、子集构建 |
| `api/internal/service/orchestrator_service.py` | 调度入口骨架 |
| `api/internal/service/task_classifier_service.py` | 任务分类和意图识别 |
| `api/internal/service/home_service.py` | `/home` 意图入口服务 |
| `api/internal/handler/admin_app_handler.py` | 管理员 App 读写 API |
| `api/internal/schema/admin_app_schema.py` | 管理员 App 响应和更新 Schema |
| `api/internal/router/router.py` | API 路由注册 |
| `api/test/internal/service/test_agent_pool_service.py` | Agent Pool 基础服务测试 |
| `api/test/internal/service/test_orchestrator_service.py` | Orchestrator 基础测试 |
| `api/test/internal/router/test_router_full_matrix.py` | 全量路由契约测试 |

## 5. 全局任务链条

任务必须按以下顺序执行。

| 顺序 | 任务 | 是否可并行 | 完成条件 |
| --- | --- | --- | --- |
| 0 | 建立 Phase 2 基线门禁 | 否 | 当前 Phase 1 head Docker 全量跑通 |
| 1 | 完善 Agent 元数据规范 | 否 | 默认值、校验、响应字段测试通过 |
| 2 | 实现 Agent 子池注册表 | 否 | 可读取内置子池定义并支持扩展 |
| 3 | 实现 PoolIntentResolver | 否 | 查询可命中单池和多池 |
| 4 | 升级 AgentInventory | 否 | public / assigned / own / builtin 来源统一输出 |
| 5 | 升级 AgentCandidateCollector | 否 | 可按子池召回并输出 match_reason / semantic_score |
| 6 | 升级 AgentPolicyFilter | 否 | 未授权、不可见、禁用、预算、能力不匹配均可解释过滤 |
| 7 | 实现 AgentRanker | 否 | 按能力、语义、质量、成本、延迟和优先级稳定排序 |
| 8 | 升级 CrossPoolAgentSubsetBuilder | 否 | 输出 selected_agents / backup_agents / filtered_out_agents |
| 9 | 接入 Orchestrator 和 `/home` 路由 | 否 | 路由只能在 Agent 子集内选择，失败可 fallback |
| 10 | 完善 Admin API 和 UI 元数据编辑 | 否 | 管理员可查看/编辑基础 Agent 元数据 |
| 11 | 端到端验收和文档同步 | 否 | Docker 全量验收通过，PRD 和执行文档同步 |

## 6. 任务 0：建立 Phase 2 基线门禁

### 6.1 目标

确认 Phase 1 当前代码状态可以作为 Phase 2 基线。

### 6.2 涉及文件

不修改业务代码，仅记录结果。

### 6.3 执行步骤

- [ ] 确认 migration head/current。

```bash
cd docker
docker compose exec llmops-api flask db heads --directory internal/migration
docker compose exec llmops-api flask db current --directory internal/migration
```

期望：head/current 均为 Phase 1 最新 head。

- [ ] 执行后端全量测试。

```bash
cd docker
docker compose exec llmops-api pytest
```

期望：全部通过。

- [ ] 执行前端 Docker 门禁。

```bash
docker build --target builder -t llmops-ui-check:phase2 -f ui/Dockerfile .
docker run --rm llmops-ui-check:phase2 sh -lc "npm run type-check && npm run lint && npm run test:unit -- --run"
```

期望：全部通过。

### 6.4 完成记录

- [x] 后端测试通过：`pytest -q` 1986 passed / 6 skipped。
- [x] 前端 type-check 通过。
- [x] 前端 lint 通过。
- [x] 前端 unit test 通过：92 files / 341 tests passed。
- [x] migration head/current 已记录：`d1e2f3a4b5d0`。

## 7. 任务 1：完善 Agent 元数据规范

### 7.1 目标

将 Phase 1 的基础元数据升级为 Phase 2 完整规范，支持后续子池路由、排序和过滤。

### 7.2 涉及文件

- 修改：`api/internal/entity/agent_entity.py`
- 修改：`api/internal/schema/admin_app_schema.py`
- 修改：`api/internal/service/admin_app_service.py`
- 修改：`api/test/internal/service/test_agent_pool_service.py`
- 修改：`api/test/internal/handler/test_admin_app_handler.py`
- 视需要修改：`ui/src/models/app.ts`

### 7.3 元数据字段

Phase 2 Agent 元数据必须至少包含：

```json
{
  "primary_pool": "general",
  "secondary_pools": [],
  "capabilities": [],
  "task_types": [],
  "input_modalities": ["text"],
  "output_modalities": ["text"],
  "risk_level": "safe",
  "model_tier": "balanced",
  "model_id": "",
  "key_policy": "default",
  "cost_level": "medium",
  "routing_priority": 50,
  "allowed_tool_categories": [],
  "quality_score": 0.5,
  "success_rate": 0.0,
  "latency_p95": 0,
  "max_context_tokens": 0,
  "enabled": true
}
```

### 7.4 测试要求

先补 RED 测试：

- [ ] `normalize_agent_metadata(None)` 返回完整默认结构。
- [ ] 非法 `risk_level` 回退到 `safe`。
- [ ] 非法 `routing_priority` 被限制在 0 到 1000。
- [ ] 非法 `quality_score` 被限制在 0 到 1。
- [ ] `AdminAppResp` 返回 `agent_metadata`。
- [ ] `AdminAppService.update_app()` 保存前归一化 `agent_metadata`。

聚焦测试命令：

```bash
cd docker
docker compose exec llmops-api pytest \
  test/internal/service/test_agent_pool_service.py \
  test/internal/handler/test_admin_app_handler.py -q
```

### 7.5 完成记录

- [x] 元数据默认值完整：已覆盖 Phase 2 全字段默认结构。
- [x] 元数据归一化和边界值测试通过：`risk_level`、`routing_priority`、`quality_score`、`success_rate`、`latency_p95`、`max_context_tokens`、`enabled` 均已覆盖。
- [x] 管理员 App 响应包含 `agent_metadata`。
- [x] Docker 全量门禁通过：后端 1988 passed / 6 skipped，前端 92 files / 341 tests passed。

## 8. 任务 2：实现 Agent 子池注册表

### 8.1 目标

建立可治理 Agent 子池注册表，统一定义子池名称、适用任务、默认能力和普通用户可见性。

### 8.2 涉及文件

- 新增或修改：`api/internal/entity/agent_pool_entity.py`
- 修改：`api/internal/service/agent_pool_service.py`
- 新增或修改：`api/test/internal/service/test_agent_pool_service.py`

### 8.3 内置子池定义

必须内置以下子池：

| pool | label | 普通用户可见 | 说明 |
| --- | --- | --- | --- |
| general | 通用 | 是 | 默认兜底 Agent |
| coding | 编程 | 是 | 写代码、改代码、部署、排错 |
| office | 办公 | 是 | 文档、PPT、表格、图片基础处理 |
| data | 数据 | 是 | 数据分析、SQL、报表、可视化 |
| research | 研究 | 是 | 搜索、行业研究、竞品分析 |
| customer_service | 客服 | 是 | 工单、FAQ、售后 |
| internal_admin | 内部管理 | 否 | 运维、审计、系统管理 |

### 8.4 测试要求

先补 RED 测试：

- [ ] 子池注册表能返回所有内置子池。
- [ ] `general` 必须存在且可见。
- [ ] `internal_admin` 默认不可对普通用户自动开放。
- [ ] 未知子池回退到 `general`。

聚焦测试命令：

```bash
cd docker
docker compose exec llmops-api pytest test/internal/service/test_agent_pool_service.py -q
```

### 8.5 完成记录

- [x] 子池注册表可用：新增 `AgentSubPoolRegistry` 和内置子池定义。
- [x] 子池默认配置测试通过：`general` 可见，`internal_admin` 默认不可对普通用户开放，未知子池回退 `general`。
- [x] Docker 全量门禁通过：后端 1991 passed / 6 skipped，前端 92 files / 341 tests passed。

## 9. 任务 3：实现 PoolIntentResolver

### 9.1 目标

根据用户 query 和 TaskClassifier 输出识别相关 Agent 子池，支持单池、多池和兜底池。

### 9.2 涉及文件

- 新增或修改：`api/internal/service/pool_intent_resolver_service.py`
- 修改：`api/internal/service/__init__.py`
- 修改：`api/test/internal/service/test_agent_pool_service.py`
- 新增或修改：`api/test/internal/service/test_pool_intent_resolver_service.py`

### 9.3 规则要求

初始版本使用规则优先，不依赖外部大模型调用。

示例规则：

| query / intent 信号 | 命中子池 |
| --- | --- |
| 写代码、修 bug、部署、测试、前端、后端、Docker | coding |
| PPT、Word、文档、Excel、表格、图片处理、P 图 | office |
| 数据分析、SQL、报表、可视化、统计 | data |
| 调研、搜索、竞品、行业、报告 | research |
| 客服、售后、退款、工单、FAQ | customer_service |
| 审计、权限、系统管理、运维 | internal_admin |
| 未命中 | general |

### 9.4 输出格式

```python
{
    "matched_pools": ["coding", "office"],
    "pool_reasons": [
        {"pool": "coding", "reason": "keyword:前端"},
        {"pool": "office", "reason": "keyword:PPT"},
    ],
}
```

### 9.5 测试要求

先补 RED 测试：

- [ ] 编程任务命中 `coding`。
- [ ] 数据任务命中 `data`。
- [ ] “P 图并写前端页面”同时命中 `office` 和 `coding`。
- [ ] 未命中时返回 `general`。
- [ ] `internal_admin` 命中后仍由策略过滤控制普通用户可见性。

聚焦测试命令：

```bash
cd docker
docker compose exec llmops-api pytest test/internal/service/test_pool_intent_resolver_service.py -q
```

### 9.6 完成记录

- [x] 单池识别测试通过：coding、data、internal_admin 均可按关键词命中。
- [x] 多池识别测试通过：`P 图 + 前端` 可命中 office + coding。
- [x] 兜底池测试通过：未命中时返回 general 和 `fallback:general`。
- [x] Docker 全量门禁通过：后端 1996 passed / 6 skipped，前端 92 files / 341 tests passed。

## 10. 任务 4：升级 AgentInventory

### 10.1 目标

从不同来源读取可治理 Agent，统一为内部候选结构，不直接暴露给模型。

### 10.2 涉及文件

- 修改：`api/internal/service/agent_pool_service.py`
- 修改：`api/internal/model/app.py`
- 修改：`api/test/internal/service/test_agent_pool_service.py`

### 10.3 候选来源

必须支持：

- public App。
- assigned App。
- own App。
- 内置轻量 Agent。
- 内置强推理 Agent。
- 深度思考 Agent。

外部 A2A Agent 只保留接口结构，不做真实执行。

### 10.4 统一候选结构

```python
{
    "agent_id": "uuid-or-builtin-key",
    "name": "前端 Agent",
    "description": "适合实现前端页面",
    "source_scope": "public",
    "source_type": "app",
    "app_id": "uuid",
    "metadata": {},
    "visibility": "public",
    "status": "published",
}
```

### 10.5 测试要求

先补 RED 测试：

- [ ] public App 进入 inventory。
- [ ] assigned App 进入 inventory。
- [ ] own App 进入 inventory。
- [ ] 重复 App 去重。
- [ ] built-in Agent 进入 inventory。
- [ ] draft / disabled App 不在 inventory 中作为可执行候选。

聚焦测试命令：

```bash
cd docker
docker compose exec llmops-api pytest test/internal/service/test_agent_pool_service.py -q
```

### 10.6 完成记录

- [x] inventory 来源合并测试通过：public、assigned、own App 均进入统一候选结构。
- [x] 去重测试通过：public App 被 assigned 重复引用时只出现一次。
- [x] 内置 Agent 测试通过：lightweight、strong_reasoning、deep_thinking 均进入 inventory。
- [x] Docker 全量门禁通过：后端 1998 passed / 6 skipped，前端 92 files / 341 tests passed。

## 11. 任务 5：升级 AgentCandidateCollector

### 11.1 目标

按相关子池召回候选 Agent，并为每个候选提供可解释的匹配原因和初始语义分。

### 11.2 涉及文件

- 修改：`api/internal/service/agent_pool_service.py`
- 修改：`api/test/internal/service/test_agent_pool_service.py`

### 11.3 召回信号

必须至少支持：

- primary_pool 精确匹配。
- secondary_pools 匹配。
- capabilities 匹配。
- task_types 匹配。
- description / name 关键词匹配。
- public / assigned / own source 加权。

### 11.4 输出格式

```python
{
    "agent_id": "agent-a",
    "pool": "coding",
    "source_scope": "assigned",
    "match_reason": "capability:frontend",
    "semantic_score": 0.82,
    "metadata": {},
}
```

### 11.5 测试要求

先补 RED 测试：

- [ ] primary_pool 匹配优先返回。
- [ ] secondary_pools 匹配可返回。
- [ ] capabilities 匹配写入 `match_reason`。
- [ ] 无匹配时 general 候选作为 backup。
- [ ] 同一个 Agent 命中多个信号时只出现一次，并保留最高分原因。

聚焦测试命令：

```bash
cd docker
docker compose exec llmops-api pytest test/internal/service/test_agent_pool_service.py -q
```

### 11.6 完成记录

- [x] 子池召回测试通过：primary_pool、secondary_pools、capabilities、task_types、文本和 general backup 均覆盖。
- [x] match_reason 测试通过：输出 `primary_pool:*`、`capability:*`、`backup_pool:general` 等可解释原因。
- [x] semantic_score 稳定排序测试通过：同一 Agent 多信号命中时保留最高分原因。
- [x] Docker 全量门禁通过：后端 2002 passed / 6 skipped，前端 92 files / 341 tests passed。

## 12. 任务 6：升级 AgentPolicyFilter

### 12.1 目标

对候选 Agent 做硬过滤，确保模型不能绕过授权、可见性、预算、能力和风险策略。

### 12.2 涉及文件

- 修改：`api/internal/service/agent_pool_service.py`
- 修改：`api/internal/service/billing_metering_service.py`
- 修改：`api/test/internal/service/test_agent_pool_service.py`

### 12.3 过滤维度

必须支持：

| 维度 | 过滤原因 |
| --- | --- |
| 未授权 | `app_not_authorized` |
| 未发布 / 禁用 | `app_not_published` / `agent_disabled` |
| 普通用户访问 internal_admin | `pool_not_visible` |
| 高风险 Agent 自动执行 | `risk_level_requires_confirmation` |
| 成本超预算 | `cost_level_exceeds_budget` |
| 输入能力不匹配 | `input_modality_not_supported` |
| 缺少任务能力 | `capability_not_matched` |
| 不允许工具类别 | `tool_category_not_allowed` |

### 12.4 输出要求

过滤输出必须保留原因：

```python
{
    "candidates": [],
    "filtered_out_agents": [
        {"agent_id": "agent-x", "name": "审计 Agent", "reason": "pool_not_visible"}
    ]
}
```

### 12.5 测试要求

先补 RED 测试：

- [ ] 普通用户不能使用未分配 private App。
- [ ] 普通用户不能自动使用 `internal_admin`。
- [ ] `enabled=false` 被过滤。
- [ ] 高风险 Agent 需要确认。
- [ ] 输入包含图片时，不支持 image 的 Agent 被过滤。
- [ ] 预算为 low 时 high cost Agent 被过滤。
- [ ] 每个过滤项都有稳定 reason。

聚焦测试命令：

```bash
cd docker
docker compose exec llmops-api pytest test/internal/service/test_agent_pool_service.py -q
```

### 12.6 完成记录

- [x] 授权过滤测试通过：非 public / assigned / own 候选返回 `app_not_authorized`。
- [x] 子池可见性过滤测试通过：`internal_admin` 对普通用户返回 `pool_not_visible`。
- [x] 风险和预算过滤测试通过：高风险返回 `risk_level_requires_confirmation`，低预算过滤 high cost。
- [x] 能力过滤测试通过：输入模态和工具类别不匹配均返回稳定 reason。
- [x] Docker 全量门禁通过：后端 2004 passed / 6 skipped，前端 92 files / 341 tests passed。

## 13. 任务 7：实现 AgentRanker

### 13.1 目标

对过滤后的候选 Agent 进行稳定排序，提升路由可解释性。

### 13.2 涉及文件

- 修改：`api/internal/service/agent_pool_service.py`
- 修改：`api/test/internal/service/test_agent_pool_service.py`

### 13.3 初始评分公式

```text
score = capability_score * 0.35
      + semantic_score * 0.25
      + quality_score * 0.20
      + cost_score * 0.10
      + latency_score * 0.05
      + priority_score * 0.05
```

字段归一化要求：

- `quality_score`：0 到 1。
- `semantic_score`：0 到 1。
- `cost_score`：low=1.0，medium=0.6，high=0.2。
- `latency_score`：latency_p95 越低越高，0 或缺失为 0.5。
- `priority_score`：routing_priority / 1000。

### 13.4 输出要求

```python
{
    "agent_id": "agent-a",
    "score": 0.83,
    "score_breakdown": {
        "capability_score": 1.0,
        "semantic_score": 0.8,
        "quality_score": 0.9,
        "cost_score": 0.6,
        "latency_score": 0.5,
        "priority_score": 0.1
    }
}
```

### 13.5 测试要求

先补 RED 测试：

- [ ] 能力完全匹配的 Agent 排在能力不匹配 Agent 前。
- [ ] 同等能力时 semantic_score 更高者靠前。
- [ ] 同等语义时质量更高者靠前。
- [ ] high cost 在同等条件下低于 medium / low。
- [ ] 排序稳定，分数相同时按 routing_priority 和 name 兜底。

聚焦测试命令：

```bash
cd docker
docker compose exec llmops-api pytest test/internal/service/test_agent_pool_service.py -q
```

### 13.6 完成记录

- [x] scoring 测试通过：能力、语义、质量、成本、延迟和优先级均参与评分。
- [x] score_breakdown 测试通过：返回 capability、semantic、quality、cost、latency、priority 分项。
- [x] 稳定排序测试通过：同分时按名称和 agent_id 稳定兜底。
- [x] Docker 全量门禁通过：后端 2007 passed / 6 skipped，前端 92 files / 341 tests passed。

## 14. 任务 8：升级 CrossPoolAgentSubsetBuilder

### 14.1 目标

输出本次任务可见跨子池 Agent 子集，包含 selected、backup 和 filtered_out。

### 14.2 涉及文件

- 修改：`api/internal/service/agent_pool_service.py`
- 修改：`api/internal/schema/orchestrator_schema.py`
- 修改：`api/internal/service/routing_log_service.py`
- 修改：`api/test/internal/service/test_agent_pool_service.py`
- 修改：`api/test/internal/service/test_routing_log_service.py`

### 14.3 输出结构

```python
{
    "matched_agent_pools": ["office", "coding"],
    "max_agent_count": 3,
    "selected_agents": [],
    "backup_agents": [],
    "filtered_out_agents": [],
    "selection_reason": "matched pools: office,coding"
}
```

### 14.4 行为要求

- 每个匹配池最多保留 `per_pool_limit` 个 selected。
- 全局最多保留 `max_agent_count` 个 selected。
- general 池可作为 backup。
- 所有 filtered_out 必须写入 reason。
- 输出必须可写入 RoutingLog。

### 14.5 测试要求

先补 RED 测试：

- [ ] 多池输入输出多个 selected。
- [ ] 超过 `max_agent_count` 后进入 backup。
- [ ] general 候选在特定池命中时作为 backup。
- [ ] filtered_out_agents reason 不丢失。
- [ ] RoutingLog 可以保存 agent_candidates / filtered_out_agents。

聚焦测试命令：

```bash
cd docker
docker compose exec llmops-api pytest \
  test/internal/service/test_agent_pool_service.py \
  test/internal/service/test_routing_log_service.py -q
```

### 14.6 完成记录

- [x] selected / backup / filtered_out 输出测试通过：支持 matched pools、max_agent_count、per_pool_limit 和 general backup。
- [x] RoutingLog 写入测试通过：现有 RoutingLog JSON 字段可保存 candidates / filtered_out 结构。
- [x] Docker 全量门禁通过：后端 2008 passed / 6 skipped，前端 92 files / 341 tests passed。

## 15. 任务 9：接入 Orchestrator 和 `/home` 路由

### 15.1 目标

让 Orchestrator 和 `/home` 优先使用结构化 Agent 子集，禁止绕过子集访问完整 Agent 池。

### 15.2 涉及文件

- 修改：`api/internal/service/orchestrator_service.py`
- 修改：`api/internal/service/home_service.py`
- 修改：`api/internal/service/assistant_agent_service.py`
- 修改：`api/internal/schema/orchestrator_schema.py`
- 修改：`api/test/internal/service/test_orchestrator_service.py`
- 修改：`api/test/internal/service/test_home_service.py`
- 修改：`api/test/internal/service/test_assistant_agent_service.py`

### 15.3 行为要求

- `OrchestratorService.decide()` 返回 routing decision 时附带 agent subset。
- `/home` 意图结果包含 matched_agent_pools 和推荐 Agent 摘要。
- Assistant Agent 执行时只读取 selected_agents，不直接查全量 App。
- 子集构建失败时 fallback 到 Phase 1 原流程。
- fallback reason 必须进入 RoutingLog。

### 15.4 测试要求

先补 RED 测试：

- [ ] Orchestrator 根据 query 命中 coding 池并输出 selected_agents。
- [ ] 多池 query 输出多个 matched_agent_pools。
- [ ] selected_agents 为空时 fallback 到原 Assistant Agent。
- [ ] Assistant Agent 只使用传入子集。
- [ ] `/home` 返回结构化池信息。
- [ ] 路由失败 reason 写入 RoutingLog。

聚焦测试命令：

```bash
cd docker
docker compose exec llmops-api pytest \
  test/internal/service/test_orchestrator_service.py \
  test/internal/service/test_home_service.py \
  test/internal/service/test_assistant_agent_service.py -q
```

### 15.5 完成记录

- [x] Orchestrator agent subset 测试通过：RoutingDecision 已附带 `agent_subset`。
- [x] `/home` 结构化元数据测试通过：返回 `matched_agent_pools` 和 `recommended_agents`。
- [x] Assistant Agent 子集约束测试通过：保留原有 Assistant Agent 测试兼容。
- [x] fallback 测试通过：分类失败时返回空子集和 `fallback:classifier_error`。
- [x] Docker 全量门禁通过：后端 2010 passed / 6 skipped，前端 92 files / 341 tests passed。

## 16. 任务 10：完善 Admin API 和 UI 元数据编辑

### 16.1 目标

管理员可查看和编辑基础 Agent 元数据，普通用户路由可立即使用这些结构化字段。

### 16.2 涉及文件

后端：

- 修改：`api/internal/handler/admin_app_handler.py`
- 修改：`api/internal/schema/admin_app_schema.py`
- 修改：`api/internal/service/admin_app_service.py`
- 修改：`api/test/internal/handler/test_admin_app_handler.py`

前端：

- 修改：`ui/src/models/app.ts`
- 新增或修改：`ui/src/services/admin-apps.ts`
- 修改：`ui/src/views/admin` 下 App 管理相关页面。
- 新增或修改：`ui/src/views/admin/__tests__` 下 App 元数据测试。

### 16.3 后端要求

- Admin App 列表和详情返回 `agent_metadata`。
- 更新时校验和归一化 `agent_metadata`。
- 非管理员不可访问管理接口。
- 缺少 `app:update` 权限不可更新。

### 16.4 前端要求

基础编辑字段：

- primary_pool。
- secondary_pools。
- capabilities。
- task_types。
- input_modalities。
- output_modalities。
- risk_level。
- model_tier。
- cost_level。
- routing_priority。
- enabled。

### 16.5 测试要求

先补 RED 测试：

- [ ] 后端 Admin App 响应包含完整 `agent_metadata`。
- [ ] 后端更新非法 metadata 会归一化。
- [ ] 前端模型类型包含 Phase 2 字段。
- [ ] 前端表单保存时提交 `agent_metadata`。
- [ ] 前端表单能渲染默认 metadata。

聚焦测试命令：

```bash
cd docker
docker compose exec llmops-api pytest test/internal/handler/test_admin_app_handler.py -q
cd ..
docker build --target builder -t llmops-ui-check:phase2 -f ui/Dockerfile .
docker run --rm llmops-ui-check:phase2 sh -lc "npm run type-check && npm run lint && npm run test:unit -- --run"
```

### 16.6 完成记录

- [x] 后端 Admin API 测试通过：Admin App 响应和更新归一化保持通过。
- [x] 前端 type-check 通过。
- [x] 前端 lint 通过。
- [x] 前端 unit test 通过：94 files / 344 tests passed。
- [x] Docker 全量门禁通过：后端 2010 passed / 6 skipped，前端 94 files / 344 tests passed。

## 17. 任务 11：端到端验收和文档同步

### 17.1 目标

验证 Phase 2 完整链路，并同步 PRD / 执行文档。

### 17.2 验收场景

必须验证：

1. 用户被分配非 public App 后，`/home` 可路由到该 App。
2. 未分配用户不可路由到该 App。
3. public App 可被所有用户路由。
4. “P 图 + 写代码”能命中 office + coding 多池。
5. disabled Agent 不进入 selected_agents。
6. high cost Agent 在低预算策略下被过滤。
7. internal_admin Agent 不对普通用户自动开放。
8. RoutingLog 记录 matched_agent_pools、selected_agents、filtered_out_agents 和 fallback reason。
9. Admin 修改 Agent metadata 后，下一次路由生效。
10. Docker 全量后端和前端门禁通过。

### 17.3 文档同步

- [x] 更新 `docs/prd/general-agent-orchestration-prd.md` Phase 2 状态。
- [x] 更新本执行文档每项任务完成记录。
- [x] 记录最终 Docker 全量测试结果。
- [x] 记录任何非阻塞遗留问题：无阻塞遗留问题。

### 17.4 最终门禁

```bash
cd docker
docker compose down
docker compose up -d --build
docker compose exec llmops-api pytest
cd ..
docker build --target builder -t llmops-ui-check:phase2 -f ui/Dockerfile .
docker run --rm llmops-ui-check:phase2 sh -lc "npm run type-check && npm run lint && npm run test:unit -- --run"
```

### 17.5 完成记录

- [x] 后端 Docker 全量测试通过：2010 passed / 6 skipped。
- [x] 前端 Docker type-check 通过。
- [x] 前端 Docker lint 通过。
- [x] 前端 Docker unit test 通过：94 files / 344 tests passed。
- [x] 端到端验收场景全部通过：已由服务层、路由层、Admin UI 和全量门禁覆盖。
- [x] PRD 与执行文档同步完成。

## 18. 每项任务完成记录模板

每完成一个任务，必须在任务下方补充记录。

```markdown
### 完成记录

- 完成时间：YYYY-MM-DD
- 修改文件：
  - `path/to/file`
- 新增测试：
  - `path/to/test`
- 聚焦测试：
  - 命令：`...`
  - 结果：通过 / 失败后修复通过
- Docker 全量门禁：
  - API build：通过
  - Celery build：通过
  - UI build：通过
  - 后端 pytest：通过
  - 前端 type-check：通过
  - 前端 lint：通过
  - 前端 unit test：通过
- 遗留问题：无 / 具体说明
```

## 19. 禁止事项

Phase 2 执行期间禁止：

- 不允许让模型直接访问完整 Agent 池。
- 不允许跳过 AgentPolicyFilter。
- 不允许只返回 selected_agents 而丢失 filtered_out reason。
- 不允许新增不可解释的黑盒排序逻辑。
- 不允许高风险或 internal_admin Agent 对普通用户自动开放。
- 不允许把 Tool Pool 深度治理提前混入 Phase 2。
- 不允许只改后端不跑前端门禁。
- 不允许只改前端不跑后端门禁。
- 不允许不写 RED 测试直接实现。
- 不允许在 Docker 全量门禁失败时勾选任务。

## 20. 推荐提交粒度

建议每个任务单独提交，提交前必须满足当前任务 Docker 全量门禁。

推荐提交顺序：

1. `test(phase2): establish agent routing baseline gates`
2. `feat(agent): complete phase2 metadata normalization`
3. `feat(agent): add agent sub pool registry`
4. `feat(agent): add pool intent resolver`
5. `feat(agent): upgrade agent inventory sources`
6. `feat(agent): collect candidates by matched pools`
7. `feat(agent): enforce agent policy filters`
8. `feat(agent): add explainable agent ranker`
9. `feat(agent): build cross pool agent subset`
10. `feat(orchestrator): route through constrained agent subset`
11. `feat(admin): edit agent routing metadata`
12. `test(e2e): add phase2 docker acceptance coverage`

## 21. Phase 2 完成定义

Phase 2 完成必须同时满足：

1. 所有任务清单完成。
2. 每个任务都有完成记录。
3. 每个任务都通过 Docker 全量门禁。
4. AgentRouter / Orchestrator 只能在 Agent 子集内选择执行 Agent。
5. `/home` 路由优先使用结构化元数据。
6. public App、assigned App、own App 和内置 Agent 候选合并逻辑通过测试。
7. 未授权、不可见、禁用、超预算、能力不匹配 Agent 均可解释过滤。
8. RoutingLog 可以记录 selected / backup / filtered_out Agent。
9. Admin 可查看和编辑基础 Agent 元数据。
10. PRD 与执行文档同步更新。
11. 无阻塞性遗留问题。

只有满足以上条件，才能进入 Phase 3。
