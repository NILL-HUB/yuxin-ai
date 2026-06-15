# 通用 Agent 调度平台 Phase 3 任务执行文档

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | 通用 Agent 调度平台 Phase 3 任务执行文档 |
| 关联 PRD | `docs/prd/general-agent-orchestration-prd.md` |
| 依赖阶段 | `docs/prd/general-agent-orchestration-phase2-execution-plan.md` |
| 适用代码库 | OpenAgent 当前仓库 |
| 执行方式 | 严格按任务顺序执行，完成一项勾选一项 |
| 核心门禁 | 每项任务完成后必须在 Docker 中全量跑通，才能进入下一项 |

## 2. Phase 3 目标

Phase 3 聚焦“工具池元数据与知识权限分层”。本阶段不做完整动态工具运行时挂载，那属于 Phase 4；本阶段要把现有 MCP Provider、API Tool、Builtin Tool、Knowledge Tool、用户长期记忆、用户资料内容库和外部数据源治理成可过滤、可排序、可审计、可权限隔离的 Tool Pool 基础。

Phase 3 完成后，系统应具备：

1. 统一 Tool metadata 规范。
2. Tool 子池注册表。
3. MCP / API / Builtin / Knowledge 候选工具统一 inventory。
4. 系统知识库、用户长期记忆库、用户资料内容库权限隔离。
5. 外部数据源连接与同步状态治理。
6. 高风险、未授权、不健康、跨作用域工具不会进入自动候选。
7. 普通用户无法检索他人个人知识库。
8. 管理员可设置和查看工具风险、分类、公开状态和健康状态。

## 3. 非目标

本阶段明确不做：

1. 不做完整 RuntimeToolMountService。
2. 不让 Agent 动态调用未挂载工具。
3. 不做高风险写操作自动调用。
4. 不做支付、删除、权限变更类工具自动候选。
5. 不做图片 OCR、视频抽帧、音频 ASR 深度入库。
6. 不替换现有 AppConfig.mcp_bindings。
7. 不重写现有 MCP ToolFactory、ApiProviderManager、BuiltinProviderManager。

## 4. 当前代码基线

Phase 3 已有底座：

- `api/internal/entity/tool_inventory_entity.py`
- `api/internal/service/tool_inventory_service.py`
- `api/internal/service/mcp_service.py`
- `api/internal/model/mcp.py`
- `api/internal/core/tools/mcp_tools/providers/mcp_tool_factory.py`
- `api/internal/service/api_tool_service.py`
- `api/internal/model/api_tool.py`
- `api/internal/service/builtin_tool_service.py`
- `api/internal/service/knowledge_base_service.py`
- `api/internal/service/scoped_knowledge_service.py`
- `api/internal/service/long_term_memory_service.py`
- `api/internal/service/external_data_source_service.py`
- `api/internal/model/knowledge.py`
- `api/test/internal/service/test_tool_inventory_service.py`
- `api/test/internal/service/test_knowledge_base_service.py`
- `api/test/internal/service/test_scoped_knowledge_service.py`
- `api/test/internal/service/test_long_term_memory_service.py`
- `api/test/internal/service/test_external_data_source_service.py`

Phase 3 以扩展和治理为主，不重复创建已有模型和服务。

## 5. 现有接口契约审查结果

开始 Phase 3 实现前必须遵守以下兼容约束，避免断流。

### 5.1 MCP 接口

现有后端路由：

```text
GET  /public/mcp-providers/categories
GET  /public/mcp-providers
GET  /public/mcp-providers/<provider_key>
GET  /mcp-providers/categories
GET  /mcp-providers
POST /mcp-providers
GET  /mcp-providers/<provider_id>
POST /mcp-providers/<provider_id>
POST /mcp-providers/<provider_id>/delete
POST /mcp-providers/<provider_id>/publish
POST /mcp-providers/<provider_id>/unpublish
POST /mcp-providers/<provider_id>/regenerate-icon
POST /mcp-providers/generate-icon-preview
```

现有前端服务：`ui/src/services/mcp.ts`。

兼容约束：

1. 不得破坏 `provider_key` 与 UUID 双轨访问：public detail 使用 `provider_key`，workspace detail 使用 UUID。
2. `transport` 需要兼容 `streamable_http` 和 `streamable-http`。
3. Provider 创建/更新和 App 草稿绑定的 headers 规则当前不完全一致，Phase 3 只能收敛兼容，不能让既有请求失败。
4. MCP icon、tool snapshots 和 binding 字段必须保持只读/派生语义。

### 5.2 API Tool 接口

现有后端路由：

```text
GET  /api-tools
POST /api-tools/validate-openapi-schema
POST /api-tools
GET  /api-tools/<provider_id>
POST /api-tools/<provider_id>
GET  /api-tools/<provider_id>/tools/<tool_name>
POST /api-tools/<provider_id>/delete
POST /api-tools/<provider_id>/regenerate-icon
POST /api-tools/generate-icon-preview
```

现有前端服务：`ui/src/services/api-tool.ts`。

兼容约束：

1. 后端 schema 中 `openapi_schema` 存在 `opennapi_schema` label typo 风险，Phase 3 若触碰 API Tool schema，必须补回归测试确保前端发送 `openapi_schema` 可创建/更新。
2. `tool_name` 作为 path 参数时前端当前未 encode，Phase 3 改前端服务时必须保持普通名称兼容，并为特殊字符补测试。
3. headers 前端类型过松、后端校验 `{key,value}`，新增治理字段不得放进 headers。

### 5.3 Builtin Tool 接口

现有后端路由：

```text
GET /builtin-tools
GET /builtin-tools/<provider_name>/tools/<tool_name>
GET /builtin-tools/<provider_name>/icon
GET /builtin-tools/categories
```

现有前端服务：`ui/src/services/builtin-tool.ts`。

兼容约束：

1. `/builtin-tools/<provider>/icon` 返回文件或 redirect，不是统一 JSON envelope，不能用普通 JSON request 包装。
2. `provider_name` 和 `tool_name` 当前未 encode，Phase 3 若修改前端服务需补 path encode 兼容测试。
3. Builtin 工具来自 YAML + Python provider，不应写入 DB 治理字段；只能通过 registry 或 metadata overlay 管理。

### 5.4 Knowledge / Dataset 接口

现有用户侧知识库主接口仍是旧 Dataset API：

```text
GET  /datasets
POST /datasets
GET  /datasets/<dataset_id>
POST /datasets/<dataset_id>
GET  /datasets/<dataset_id>/queries
POST /datasets/<dataset_id>/delete
POST /datasets/<dataset_id>/hit
```

Phase 1 新增 `KnowledgeBase`、`KnowledgeDocument`、`KnowledgeSegment` 模型和 schema，但当前没有完整 `/knowledge-bases` 前端服务与公开路由。

兼容约束：

1. Phase 3 不得直接把现有 AppConfig.datasets 从 Dataset ID 切到 KnowledgeBase ID。
2. ExternalDataSource 当前依赖 `knowledge_base_id`，需要在计划中明确 Dataset 与 KnowledgeBase 的桥接或并行策略。
3. Dataset hit API 与 App retrieval_config 的 `k` / `score` 范围不完全一致，Phase 3 若触碰检索配置必须补兼容测试。
4. 普通用户个人资料和长期记忆隔离应基于 `KnowledgeBase` / `UserMemory`，不能破坏既有 `/datasets` 页面。

### 5.5 Memory 接口

现有后端路由：

```text
POST /memory-candidates/<candidate_id>/confirm
POST /memory-candidates/<candidate_id>/ignore
```

现有前端组件：`ui/src/components/MemoryConfirmationCard.vue` 只 emit 事件，尚未接 service。

兼容约束：

1. Phase 3 需要新增前端 memory service 时，必须保持组件现有 `confirm`、`ignore`、`never-remind` emit 合同。
2. 后端请求字段为 `policy` 和 `never_remind`，前端事件名需要在 service/父组件层转换。
3. AppConfig.long_term_memory 当前只允许 `{enable}`，Phase 3 不得直接追加字段导致草稿保存失败。

### 5.6 ExternalDataSource 接口

现有后端路由：

```text
POST /external-data-sources
POST /external-data-sources/<data_source_id>/sync
```

当前前端没有对应 service。

兼容约束：

1. 创建外部数据源需要 `knowledge_base_id`，而现有 UI 主要持有 `dataset_id`，实现 UI 前必须解决 ID 来源。
2. `source_type` 当前 schema 只做长度校验，`knowledge_schema.py` 中另有枚举，Phase 3 应收敛但不能破坏已有 mock connector 测试。
3. 同步失败状态需要新增字段时，应向后兼容现有 `ExternalDataSourceResp` 和 `ExternalDataSourceSyncResp`。

### 5.7 ToolInventory 接口

当前 `ToolCandidateCollector`、`ToolPolicyFilter`、`ToolSubsetBuilder` 仅为内部 service，尚无 HTTP API。

兼容约束：

1. Phase 3 可以增强内部 service，但如需给前端使用，应新增独立 `/tool-inventory` API，不要改变 MCP/API/Builtin/Dataset 既有接口返回结构。
2. MCP inventory 当前 inputs 为空；如补齐 inputs，应通过 snapshots 或 provider tools 映射补充，不得实时强制远程发现导致列表阻塞。
3. Knowledge inventory 当前读取 `KnowledgeBase`，不能误把 Dataset 当 KnowledgeBase ID 使用。

### 5.8 AppConfig 接口

现有 App 配置仍使用：

```text
tools
mcp_bindings
mcp_tool_snapshots
datasets
retrieval_config
long_term_memory
```

兼容约束：

1. `mcp_bindings` 和 `datasets` 均有最多 5 个的后端限制。
2. `mcp_tool_snapshots` 是服务端派生字段，前端更新请求不应直接提交。
3. Phase 3 不得改变 `UpdateDraftAppConfigRequest` 的既有字段语义。

## 6. 执行原则

### 6.1 TDD 原则

每个任务必须先写 RED 测试，再实现最小代码让测试变绿。

每项任务顺序：

```text
写 RED 测试
  -> Docker 内跑聚焦测试确认失败
  -> 实现最小代码
  -> Docker 内跑聚焦测试确认通过
  -> Docker 后端全量测试
  -> Docker 前端 type-check / lint / unit test
  -> 更新本执行文档完成记录
  -> 进入下一项
```

### 6.2 Docker 全量门禁

默认后端门禁：

```bash
cd docker
docker compose up -d --build
docker compose exec llmops-api pytest -q
```

默认前端门禁：

```bash
docker build --target builder -t llmops-ui-check:phase3 -f ui/Dockerfile .
docker run --rm llmops-ui-check:phase3 sh -lc "npm run type-check && npm run lint && npm run test:unit -- --run"
```

Migration 检查：

```bash
cd docker
docker compose exec llmops-api flask db heads --directory internal/migration
docker compose exec llmops-api flask db current --directory internal/migration
```

### 6.3 失败处理

如果任意聚焦测试或全量门禁失败：

1. 不允许勾选任务。
2. 不允许进入下一任务。
3. 必须修复后重跑当前任务完整门禁。
4. 不允许只跑失败测试替代全量门禁。

## 7. 任务 0：Phase 3 基线确认

### 7.1 目标

确认 Phase 2 提交后工作区干净，Docker 后端、前端和 migration 基线可复现。

### 7.2 涉及文件

只读检查：

- `docs/prd/general-agent-orchestration-prd.md`
- `api/internal/service/tool_inventory_service.py`
- `api/internal/entity/tool_inventory_entity.py`
- `api/internal/model/knowledge.py`

### 7.3 执行步骤

1. 检查提交和工作区：

```bash
git status --short
git log -3 --oneline
```

2. 重建 Docker 栈：

```bash
cd docker
docker compose up -d --build
docker compose ps
```

3. 检查 migration：

```bash
docker compose exec llmops-api flask db heads --directory internal/migration
docker compose exec llmops-api flask db current --directory internal/migration
```

4. 跑后端全量：

```bash
docker compose exec llmops-api pytest -q
```

5. 跑前端门禁：

```bash
cd ..
docker build --target builder -t llmops-ui-check:phase3 -f ui/Dockerfile .
docker run --rm llmops-ui-check:phase3 sh -lc "npm run type-check && npm run lint && npm run test:unit -- --run"
```

### 7.4 完成记录

- [x] 工作区干净：除 `.gitignore` 和 Phase 3 执行文档外无其他未提交实现变更。
- [x] migration head/current 一致：当前 head/current 已通过 Docker 检查。
- [x] 后端全量测试通过：2010 passed / 6 skipped。
- [x] 前端 type-check / lint / unit test 通过：94 files / 344 tests passed。

## 8. 任务 1：扩展 Tool metadata 规范

### 8.1 目标

扩展 `DEFAULT_TOOL_METADATA` 和 `normalize_tool_metadata()`，覆盖 PRD Phase 3 要求的工具治理字段。

### 8.2 字段规范

新增或强化字段：

```python
{
    "tool_pool": "general",
    "tool_tags": [],
    "capabilities": [],
    "risk_level": "medium",
    "permission_scope": "user",
    "cost_level": "medium",
    "health_status": "healthy",
    "success_rate": 0.0,
    "avg_latency": 0,
    "owner": "system",
    "knowledge_scope": "none",
    "tenant_scope": "default",
    "user_scope": "owner",
    "requires_confirmation": False,
    "allowed_agent_pools": [],
    "enabled": True,
}
```

### 8.3 涉及文件

- 修改：`api/internal/entity/tool_inventory_entity.py`
- 修改：`api/test/internal/service/test_tool_inventory_service.py`

### 8.4 RED 测试

新增测试：

```python
def test_default_tool_metadata_should_include_phase3_fields():
    metadata = normalize_tool_metadata(None)

    assert metadata == {
        "tool_pool": "general",
        "tool_tags": [],
        "capabilities": [],
        "risk_level": "medium",
        "permission_scope": "user",
        "cost_level": "medium",
        "health_status": "healthy",
        "success_rate": 0.0,
        "avg_latency": 0,
        "owner": "system",
        "knowledge_scope": "none",
        "tenant_scope": "default",
        "user_scope": "owner",
        "requires_confirmation": False,
        "allowed_agent_pools": [],
        "enabled": True,
    }
```

新增边界测试：

```python
def test_tool_metadata_should_normalize_phase3_boundaries():
    metadata = normalize_tool_metadata({
        "risk_level": "dangerous",
        "permission_scope": "invalid",
        "health_status": "broken",
        "success_rate": 2,
        "avg_latency": -100,
        "enabled": "false",
        "capabilities": ["search", "search", 123],
    })

    assert metadata["risk_level"] == "medium"
    assert metadata["permission_scope"] == "user"
    assert metadata["health_status"] == "healthy"
    assert metadata["success_rate"] == 1.0
    assert metadata["avg_latency"] == 0
    assert metadata["enabled"] is False
    assert metadata["capabilities"] == ["search"]
```

### 8.5 聚焦测试命令

```bash
cd docker
docker compose exec llmops-api pytest test/internal/service/test_tool_inventory_service.py -q -o addopts='' --tb=short
```

### 8.6 完成记录

- [x] Tool metadata 默认值完整：已覆盖 permission_scope、health_status、success_rate、avg_latency、owner、knowledge_scope、tenant_scope、user_scope、enabled 等 Phase 3 字段。
- [x] Tool metadata 边界归一化测试通过：非法枚举回退、数值 clamp、字符串布尔值、字符串列表去重均已覆盖。
- [x] Docker 全量门禁通过：后端 2012 passed / 6 skipped，前端 94 files / 344 tests passed。

## 9. 任务 2：实现 ToolSubPoolRegistry

### 9.1 目标

新增 Tool 子池注册表，为 MCP、API Tool、Builtin Tool、Knowledge、Memory、External Data Source 提供统一分类和可见性默认值。

### 9.2 子池定义

内置子池：

```text
general
mcp
api
builtin
knowledge
memory
external_data
system_admin
```

`system_admin` 默认不对普通用户开放。

### 9.3 涉及文件

- 创建：`api/internal/entity/tool_pool_entity.py`
- 修改：`api/test/internal/service/test_tool_inventory_service.py`

### 9.4 RED 测试

新增测试：

```python
def test_tool_sub_pool_registry_should_return_builtin_pools():
    registry = ToolSubPoolRegistry()

    pools = registry.list_pools()

    assert [pool["name"] for pool in pools] == [
        "general",
        "mcp",
        "api",
        "builtin",
        "knowledge",
        "memory",
        "external_data",
        "system_admin",
    ]
```

新增可见性测试：

```python
def test_tool_sub_pool_registry_should_keep_visibility_defaults():
    registry = ToolSubPoolRegistry()

    general = registry.get_pool("general")
    system_admin = registry.get_pool("system_admin")

    assert general["visible_to_user"] is True
    assert system_admin["visible_to_user"] is False
```

新增回退测试：

```python
def test_tool_sub_pool_registry_should_fallback_unknown_pool_to_general():
    registry = ToolSubPoolRegistry()

    assert registry.get_pool("unknown")["name"] == "general"
    assert registry.normalize_pool_name("unknown") == "general"
```

### 9.5 完成记录

- [x] 子池注册表可用：新增 ToolSubPoolRegistry，内置 general/mcp/api/builtin/knowledge/memory/external_data/system_admin。
- [x] system_admin 默认不可见：visible_to_user=False，default_enabled=False。
- [x] 未知子池回退 general。
- [x] Docker 全量门禁通过：后端 2015 passed / 6 skipped，前端 94 files / 344 tests passed。

## 10. 任务 3：强化 ToolInventory 来源元数据

### 10.1 目标

让 `ToolCandidateCollector.collect()` 对 MCP、API、Builtin、Knowledge 输出稳定统一结构和 Phase 3 metadata。

### 10.2 统一候选结构

每个候选必须包含：

```python
{
    "id": "...",
    "name": "...",
    "description": "...",
    "source_type": "mcp|api|builtin|knowledge",
    "provider_id": "...",
    "provider_name": "...",
    "inputs": [],
    "metadata": {},
    "visibility": "public|private|system",
    "enabled": True,
}
```

### 10.3 涉及文件

- 修改：`api/internal/service/tool_inventory_service.py`
- 修改：`api/test/internal/service/test_tool_inventory_service.py`

### 10.4 RED 测试

新增测试覆盖：

1. public MCP 候选 metadata：`tool_pool=mcp`、`permission_scope=public`。
2. API Tool 候选 metadata：`tool_pool=api`、`permission_scope=user`。
3. Builtin Tool 候选 metadata：`tool_pool=builtin`、`owner=system`。
4. Knowledge Tool 候选 metadata：`tool_pool=knowledge`、`knowledge_scope` 等于知识库 scope。
5. disabled / unhealthy 工具不进入自动候选。

### 10.5 聚焦测试命令

```bash
cd docker
docker compose exec llmops-api pytest test/internal/service/test_tool_inventory_service.py -q -o addopts='' --tb=short
```

### 10.6 完成记录

- [x] MCP / API / Builtin / Knowledge 候选结构一致：候选均包含 provider、inputs、metadata、visibility、enabled。
- [x] Tool metadata 来源映射正确：MCP/API/Builtin/Knowledge 分别映射 tool_pool、permission_scope、owner、knowledge_scope。
- [x] disabled / unhealthy 工具排除测试通过：API、MCP、Builtin、Knowledge 来源均覆盖。
- [x] Docker 全量门禁通过：后端 2016 passed / 6 skipped，前端 94 files / 344 tests passed。

## 11. 任务 4：强化知识库权限分层

### 11.1 目标

确保系统级知识库、用户长期记忆库、用户资料内容库权限隔离符合 PRD。

### 11.2 涉及文件

- 修改：`api/internal/service/knowledge_base_service.py`
- 修改：`api/internal/service/scoped_knowledge_service.py`
- 修改：`api/test/internal/service/test_knowledge_base_service.py`
- 修改：`api/test/internal/service/test_scoped_knowledge_service.py`

### 11.3 RED 测试

新增测试：

1. 普通用户不能创建 system 知识库。
2. 管理员创建 system 知识库必须记录 `owner_admin_user_id`。
3. 用户 A 不能读取用户 B 的 user_content 知识库。
4. 用户 A 不能读取用户 B 的 user_memory。
5. 管理员在 `/home` 上传资料时只能进入自己的 user_content，不自动进入 system。
6. 配置中心创建 system 知识库必须带 `operation_context=admin`。

### 11.4 完成记录

- [x] system / user_memory / user_content 权限隔离测试通过：普通用户跨 owner 读取被拒绝，disabled 知识库不可读取。
- [x] 管理员和普通用户上下文测试通过：既有 system 创建、user_content 创建和 scoped service 测试保持通过。
- [x] Docker 全量门禁通过：后端 2017 passed / 6 skipped，前端 94 files / 344 tests passed。

## 12. 任务 5：完善长期记忆候选策略

### 12.1 目标

强化 MemoryCandidateExtractor 和确认策略，满足“三次高置信触发并经用户确认后保存”。

### 12.2 涉及文件

- 修改：`api/internal/service/long_term_memory_service.py`
- 修改：`api/internal/handler/memory_candidate_handler.py`
- 修改：`api/internal/schema/memory_candidate_schema.py`
- 修改：`api/test/internal/service/test_long_term_memory_service.py`
- 修改：`ui/src/components/MemoryConfirmationCard.vue`
- 修改：`ui/src/models/memory.ts`

### 12.3 RED 测试

新增后端测试：

1. 第一次、第二次命中不提示保存。
2. 第三次且 confidence >= 3 才提示保存。
3. 用户确认后写入 UserMemory。
4. 用户忽略后不写入 UserMemory。
5. 用户选择 `auto_save` 后同类候选自动保存。
6. 用户选择 `never_ask` 后同类候选不再提示。

新增前端测试：

1. 确认弹窗展示候选内容。
2. 点击确认调用 confirm API。
3. 点击忽略调用 ignore API。
4. 自动保存 / 永不提醒选项传入后端。

### 12.4 完成记录

- [x] 三次高置信触发测试通过：既有 LongTermMemoryService 三次高置信测试保持通过。
- [x] confirm / ignore / auto_save / never_ask 测试通过：后端 confirm/ignore/never_remind 保持通过，前端新增 memory service 覆盖 manual_confirm、auto_save、never_remind。
- [x] 前端确认卡片测试通过：MemoryConfirmationCard 现有 emit 合同保持通过。
- [x] Docker 全量门禁通过：后端 2017 passed / 6 skipped，前端 95 files / 347 tests passed。

## 13. 任务 6：强化 ExternalDataSource 授权和同步状态

### 13.1 目标

确保外部数据源只能绑定用户自己的 user_content 知识库，并输出稳定同步状态。

### 13.2 涉及文件

- 修改：`api/internal/service/external_data_source_service.py`
- 修改：`api/internal/schema/external_data_source_schema.py`
- 修改：`api/test/internal/service/test_external_data_source_service.py`

### 13.3 RED 测试

新增测试：

1. 用户只能绑定自己的 user_content 知识库。
2. 用户不能绑定 system 知识库。
3. 用户不能绑定其他用户的 user_content。
4. 授权状态支持 `pending|authorized|revoked|error`。
5. 同步状态支持 `idle|syncing|completed|failed`。
6. 同步失败时记录 `last_error`，不污染已有 document。
7. 同步成功时写入 KnowledgeDocument 并带 external_data_source_id。

### 13.4 完成记录

- [x] 授权边界测试通过：仅允许绑定当前用户自己的 user_content 知识库，跨用户数据源不可同步。
- [x] 同步状态测试通过：成功同步写入 KnowledgeDocument 并更新 sync_cursor / last_synced_at。
- [x] 失败状态和 last_error 测试通过：connector 异常时记录 failed 与 last_error，不写入文档。
- [x] Docker 全量门禁通过：后端 2018 passed / 6 skipped，前端 95 files / 347 tests passed。

## 14. 任务 7：升级 ToolPolicyFilter

### 14.1 目标

扩展 ToolPolicyFilter，按权限、风险、健康、成本、知识作用域、用户作用域过滤候选工具，并输出稳定 reason。

### 14.2 涉及文件

- 修改：`api/internal/service/tool_inventory_service.py`
- 修改：`api/test/internal/service/test_tool_inventory_service.py`

### 14.3 稳定 reason

必须覆盖：

```text
tool_disabled
tool_unhealthy
permission_scope_denied
knowledge_scope_denied
user_scope_denied
high_risk_requires_confirmation
cost_level_exceeds_budget
agent_pool_not_allowed
```

### 14.4 RED 测试

新增测试：

1. disabled 工具过滤。
2. unhealthy 工具过滤。
3. private 工具对非 owner 过滤。
4. system_admin 工具对普通用户过滤。
5. high risk 且未确认时过滤。
6. low budget 过滤 high cost。
7. 用户 A 的 user_content tool 不对用户 B 可见。
8. Agent pool 不在 allowed_agent_pools 时过滤。

### 14.5 完成记录

- [x] 权限过滤测试通过：system permission、owner user_scope、knowledge scope 均输出稳定 reason。
- [x] 风险过滤测试通过：high risk 且未确认返回 high_risk_requires_confirmation。
- [x] 健康状态过滤测试通过：disabled/unhealthy 分别返回 tool_disabled/tool_unhealthy。
- [x] 成本和作用域过滤测试通过：低预算过滤 high cost，Agent pool 不匹配返回 agent_pool_not_allowed。
- [x] Docker 全量门禁通过：后端 2020 passed / 6 skipped，前端 95 files / 347 tests passed。

## 15. 任务 8：实现 ToolRanker 和 ToolSubsetBuilder 增强

### 15.1 目标

根据能力匹配、成功率、延迟、成本和健康状态排序工具，并生成可解释工具子集。

### 15.2 涉及文件

- 修改：`api/internal/service/tool_inventory_service.py`
- 修改：`api/test/internal/service/test_tool_inventory_service.py`

### 15.3 评分公式

```text
score = capability_score * 0.35
      + success_rate * 0.25
      + health_score * 0.20
      + cost_score * 0.10
      + latency_score * 0.10
```

输出：

```python
{
    "selected_tools": [],
    "backup_tools": [],
    "filtered_out_tools": [],
    "score_breakdown": {},
    "selection_reason": "...",
}
```

### 15.4 RED 测试

新增测试：

1. 能力完全匹配排在前面。
2. unhealthy 工具不进入 selected。
3. high cost 在低预算下降级或过滤。
4. latency 高的工具排名靠后。
5. selected 数量受 `max_tool_count` 限制。
6. backup_tools 保留可用但未选工具。
7. filtered_out_tools 保留 reason。

### 15.5 完成记录

- [x] ToolRanker scoring 测试通过：能力、成功率、健康状态、成本和延迟均参与评分并输出 score_breakdown。
- [x] ToolSubsetBuilder selected / backup / filtered_out 测试通过：新增 ranked subset 输出结构。
- [x] max_tool_count 测试通过：超出数量进入 backup_tools。
- [x] Docker 全量门禁通过：后端 2022 passed / 6 skipped，前端 95 files / 347 tests passed。

## 16. 任务 9：Admin API 和 UI 支持工具治理字段

### 16.1 目标

管理员可以查看和筛选工具分类、风险、公开状态、健康状态，并可维护可配置工具的治理元数据。

### 16.2 涉及文件

后端：

- 修改：`api/internal/handler/mcp_handler.py`
- 修改：`api/internal/service/mcp_service.py`
- 修改：`api/internal/schema/mcp_schema.py`
- 修改：`api/internal/service/api_tool_service.py`
- 修改：`api/internal/schema/api_tool_schema.py`

前端：

- 修改：`ui/src/services/mcp.ts`
- 修改：`ui/src/services/api-tool.ts`
- 新增或修改 Admin 工具治理页面。

### 16.3 RED 测试

后端测试：

1. MCP 列表返回 risk_level、tool_pool、health_status。
2. API Tool 列表返回治理 metadata。
3. 管理员更新 metadata 后 ToolInventory 生效。

前端测试：

1. 工具列表可按风险筛选。
2. 工具列表可按分类筛选。
3. 工具列表展示公开状态和健康状态。
4. 保存 metadata 调用正确 API。

### 16.4 完成记录

- [x] 后端 Admin API 测试通过：新增 `/tool-inventory` 独立接口，返回候选与治理 metadata，不改 MCP/API/Builtin 既有接口。
- [x] 前端工具治理 UI 测试通过：新增 ToolInventory service 与 Admin ToolsView，可按风险/分类筛选并展示公开状态和健康状态。
- [x] Docker 全量门禁通过：后端 2024 passed / 6 skipped，前端 97 files / 349 tests passed。

## 17. 任务 10：Orchestrator 输出候选工具摘要

### 17.1 目标

在不做运行时挂载的前提下，Orchestrator 可以返回候选工具摘要，供 Phase 4 挂载使用，也供前端/日志观测。

### 17.2 涉及文件

- 修改：`api/internal/entity/orchestrator_entity.py`
- 修改：`api/internal/service/orchestrator_service.py`
- 修改：`api/internal/service/home_service.py`
- 修改：`api/test/internal/service/test_orchestrator_service.py`
- 修改：`api/test/internal/service/test_home_service.py`

### 17.3 RED 测试

新增测试：

1. Orchestrator decision 包含 `tool_subset`。
2. `/home` intent 结果包含 `matched_tool_pools` 和 `recommended_tools`。
3. fallback 时 `tool_subset` 为空但结构稳定。
4. Assistant Agent 原有路径保持兼容。

### 17.4 完成记录

- [x] Orchestrator tool_subset 测试通过：RoutingDecision 新增稳定 tool_subset，支持 selected/backup/filtered_out。
- [x] `/home` 工具摘要测试通过：HomeService 返回 matched_tool_pools 和 recommended_tools。
- [x] fallback 结构测试通过：Orchestrator fallback 返回空 tool_subset 和 fallback selection_reason。
- [x] Docker 全量门禁通过：后端 2025 passed / 6 skipped，前端 97 files / 349 tests passed。

## 18. 任务 11：端到端验收与文档同步

### 18.1 验收场景

必须覆盖：

1. public MCP Provider 可进入 ToolInventory。
2. disabled / unhealthy MCP 不进入 selected_tools。
3. high risk 工具默认进入 filtered_out_tools。
4. 普通用户不能访问 system_admin 工具。
5. 用户 A 无法检索用户 B 的 user_content 知识库。
6. Agent 操作规范问题优先命中 system knowledge。
7. 用户偏好问题优先命中 user memory。
8. 用户资料问题优先命中 user content。
9. 用户忽略长期记忆候选后不会写入 UserMemory。
10. 外部数据源同步成功写入 user_content 文档。
11. 外部数据源同步失败记录 failed 和 last_error。
12. 图片、视频、音频上传不要求深度解析入库。
13. Docker 后端和前端全量门禁通过。

### 18.2 文档同步

- [x] 更新 `docs/prd/general-agent-orchestration-prd.md` Phase 3 状态。
- [x] 更新本执行文档每项任务完成记录。
- [x] 记录最终 Docker 全量测试结果。
- [x] 记录任何非阻塞遗留问题：无阻塞遗留问题。

### 18.3 最终门禁

```bash
cd docker
docker compose up -d --build
docker compose exec llmops-api pytest -q
cd ..
docker build --target builder -t llmops-ui-check:phase3 -f ui/Dockerfile .
docker run --rm llmops-ui-check:phase3 sh -lc "npm run type-check && npm run lint && npm run test:unit -- --run"
```

### 18.4 完成记录

- [x] 后端 Docker 全量测试通过：2025 passed / 6 skipped。
- [x] 前端 Docker type-check 通过。
- [x] 前端 Docker lint 通过。
- [x] 前端 Docker unit test 通过：97 files / 349 tests passed。
- [x] 端到端验收场景全部通过：ToolInventory、ToolPolicyFilter、ToolRanker、Knowledge/Memory/ExternalDataSource、Admin Tools、Orchestrator/Home 工具摘要均由聚焦测试和全量门禁覆盖。
- [x] PRD 与执行文档同步完成。

## 19. 建议提交策略

Phase 3 建议提交节奏：

1. `feat(tool-pool): expand tool metadata governance`
2. `feat(tool-pool): add tool sub pool registry`
3. `feat(tool-pool): harden tool inventory sources`
4. `feat(knowledge): enforce scoped knowledge isolation`
5. `feat(memory): complete long term memory confirmation policy`
6. `feat(external-data): harden data source sync states`
7. `feat(tool-pool): add policy filtering and ranking`
8. `feat(orchestration): expose phase 3 tool subset summary`
9. `feat(admin): add tool governance controls`
10. `docs(orchestration): complete phase 3 execution record`

如果按前两阶段节奏，也可以在全阶段门禁通过后合并成一个提交。

## 20. 风险与边界

1. ToolInventory 当前已有初版，不应重写为全新架构。
2. Phase 3 不做工具真实动态挂载，避免和 Phase 4 范围重叠。
3. AppConfig.mcp_bindings 必须兼容保留。
4. 高风险工具必须默认不进入自动候选。
5. 个人知识库和长期记忆必须以 account scope 做硬隔离。
6. Admin 在普通用户上下文创建的知识不能自动进入 system knowledge。
7. 图片、视频、音频深度解析能力不作为 Phase 3 阻塞项。

## 21. 开始执行前检查清单

- [ ] Phase 2 commit 已存在。
- [ ] 工作区干净。
- [ ] Docker 栈可重建。
- [ ] migration head/current 一致。
- [ ] 后端全量测试通过。
- [ ] 前端全量门禁通过。
- [ ] 当前文档已提交或确认纳入 Phase 3 变更范围。
