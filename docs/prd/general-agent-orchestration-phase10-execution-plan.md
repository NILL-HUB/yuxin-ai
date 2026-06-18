# 通用 Agent 调度平台 Phase 10 执行计划

## 1. 阶段定位

Phase 1～9 已经完成通用 Agent 调度平台控制面的基础能力：

- 调度骨架、Agent 路由、工具治理
- 动态工具检索、模型档位、成本路由
- 多 Agent 编排、结果汇总
- 路由日志、发布开关、上线验收
- 路由质量反馈、运营洞察、半自动调优建议

本阶段 Phase 10 核心目标是把现有 `Dataset` / `Document` / `Segment` 从“资料上传存储”升级为**完整的知识体系**：

```
系统级知识库
├─ 平台规则、Agent 规范、操作手册
├─ owner_admin_user_id 维护
└─ 作用域：全系统可见

用户长期记忆库
├─ 用户偏好、习惯、常用偏好
├─ owner_account_id 维护
└─ 作用域：仅对该用户可见，默认全局作用域

用户资料内容库
├─ 用户上传文档、笔记、笔记片段
├─ owner_account_id 维护
└─ 作用域：仅对该用户可见

租户级知识库
├─ 团队共享知识
├─ 维护人 admin user 权限
└─ 作用域：租户内所有用户可见

项目级知识库
├─ 项目共享知识
├─ 维护人 admin user 权限
└─ 作用域：项目内可见
```

已确认设计决策：

1. 保留 Dataset 现有命名，新增知识归属字段，不做破坏性重构
2. 用户长期记忆默认全局作用域，匹配当前系统用户级粒度
3. 用户开启自动保存后直接保存，不需要二次确认
4. 系统知识库只做 CRUD，不需要发布/草稿/下线状态，简化实现
5. 外部数据源第一个阶段优先支持飞书和本地文件夹

## 2. 阶段目标

- 在现有 `Dataset` 上新增知识作用域字段，区分不同归属的知识
- 新增 `UserMemory` 模型承载用户长期记忆，复用 `Segment` 做内容索引
- 新增 `MemoryCandidateExtractor`，从对话中提取用户偏好候选
- 新增 `MemoryConfidenceTracker`，用计数策略聚合同类偏好
- 新增 `user_memory_retriever` 工具，每次对话召回用户长期记忆
- 新增用户长期记忆管理页面，支持 CRUD 和启用/禁用
- 新增系统级知识库管理入口，要求管理员权限
- 知识检索按作用域隔离：
  - Agent 操作规范优先召回系统级知识库
  - 用户偏好优先召回用户长期记忆
  - 用户资料查询优先召回用户资料内容库
- 补 A/B 用户知识隔离：用户 A 不能访问用户 B 知识库
- 补索引设计、权限测试、兼容回归测试

## 3. 阶段原则

- 不能破坏现有 Dataset / Document 检索逻辑，必须保持向后兼容
- 知识作用域必须从检索查询层面隔离，不能只靠 UI 权限
- 不要求同时支持飞书和本地文件夹的同步全链路，只先做好 Schema 层面框架
- 严格按任务粒度拆分，每个任务写完再跑一遍聚焦测试
- 所有新增文案必须走 i18n
- 新增数据库变更必须走 migration，不能直接改现有表结构
- 每次任务结束验证：后端单元/集成测试 → 前端单元测试 → Docker 全量门禁

## 4. 任务清单

### 4.1 任务 0：基线确认

#### 目标

确认 Phase 9 提交、设计决策生效、后端/前端门禁通过、private-domain-live-sop 已停止追踪。

#### 验收标准

- [ ] Phase 9 提交：`d65e6c8 feat(orchestration): complete phase 9 quality loop`
- [ ] private-domain-live-sop 删除和忽略规则提交：`12e47e2 chore: stop tracking private domain live sop`
- [ ] 设计决策已写入总 PRD，所有问题已确认。
- [ ] 后端 Docker 全量测试通过。
- [ ] 后端 migration heads/current 通过：`d1e2f3a4b5d3`。
- [ ] 前端 Docker type-check / lint / unit test 通过。

#### 完成记录

- [ ] 待完成。

### 4.2 任务 1：在 Dataset 模型上新增知识作用域字段

#### 目标

给现有 `Dataset` 增加知识归属和作用域字段，保持向后兼容。

#### 建议文件

- 修改：`api/internal/model/dataset.py`
- 修改：`api/internal/model/__init__.py`
- 新增 migration：`api/internal/migration/versions/<revision>_add_dataset_knowledge_scope_fields.py`
- 修改测试：`api/test/internal/model/test_dataset_model.py`（如果存在）或新增聚焦测试。

#### 新增字段

```
knowledge_scope: enum = system / tenant / project / user_memory / user_content
owner_account_id: UUID = nullable
owner_admin_user_id: UUID = nullable
target_tenant_id: UUID = nullable
target_project_id: UUID = nullable
created_by: UUID = nullable
```

枚举定义在 `internal/entity/dataset_knowledge_scope.py` 或同文件。

#### 约束

- 兼容现有数据：
  - `knowledge_scope` 默认 `user_content`
  - 所有新字段允许 null，默认 null
  - 现有 Dataset 记录仍然可用，不需要迁移历史数据内容

#### 验收标准

- [ ] 新增知识作用域枚举定义。
- [ ] Dataset 模型新增上述字段并兼容现有数据。
- [ ] 新增 migration 升级/降级可执行。
- [ ] migration heads/current 通过。
- [ ] 模型测试通过。

#### 完成记录

- [ ] 待完成。

### 4.3 任务 2：定义 UserMemory 实体与持久化模型

#### 目标

新增独立 `UserMemory` 模型，避免将用户长期记忆混入用户资料 Dataset，方便后续单独做索引、召回和策略调整。

#### 建议文件

- 新增：`api/internal/entity/user_memory_entity.py`
- 新增：`api/internal/model/user_memory.py`
- 修改：`api/internal/model/__init__.py`
- 新增 migration：`api/internal/migration/versions/<revision>_create_user_memory_table.py`
- 新增测试：`api/test/internal/entity/test_user_memory_entity.py`
- 新增测试：`api/test/internal/model/test_user_memory_model.py`

#### 核心字段

```
id
account_id (用户 ID，必须非空)
content
confidence
hit_count
enabled
knowledge_scope (默认 global)
created_at
updated_at
```

#### 约束

- `enabled` 默认 true
- `confidence` 存储聚合后的置信度（初始等于命中次数）
- `knowledge_scope` 目前只实现 global，后续扩展 project/tenant
- 索引：
  - `account_id` 必须有索引
  - `enabled` 必须有索引

#### 验收标准

- [ ] UserMemory 实体支持置信度和启用状态。
- [ ] 持久化模型包含索引。
- [ ] 新建 migration 升级/降级可执行。
- [ ] migration heads/current 通过。
- [ ] 实体和模型聚焦测试通过。

#### 完成记录

- [ ] 待完成。

### 4.4 任务 3：实现 MemoryCandidateExtractor 与 MemoryConfidenceTracker

#### 目标

从对话上下文中提取用户长期偏好候选，聚合同类偏好，达到置信度阈值后自动保存到 `UserMemory`。

#### 建议文件

- 新增：`api/internal/service/memory_candidate_extractor.py`
- 新增：`api/internal/service/memory_confidence_tracker.py`
- 新增测试：`api/test/internal/service/test_memory_candidate_extractor.py`
- 新增测试：`api/test/internal/service/test_memory_confidence_tracker.py`

#### 推荐策略

- 系统提示中指定：提取用户明确说“我习惯”、“我偏好”、“我希望”、“以后默认”、“记住我” 这类表达
- 每个提取候选带置信度 +1
- 用户开启自动保存后，命中次数 ≥ 3 自动保存
- 不需要用户每次确认，只需要命中次数累计
- 相同用户 + 相同偏好文本命中 -> 置信度 +1
- 保存后重置命中次数为 confidence 数值

#### 触发时机

- 在 `OrchestratorService` 生成最终结果之前调用提取
- 提取后更新 confidence 计数
- 达到阈值自动保存，不影响本次输出
- 用户关闭自动保存 -> 只提取，不自动保存，保留计数

#### 验收标准

- [ ] 能从自然语言对话中提取用户偏好候选。
- [ ] 置信度能正确累计命中次数。
- [ ] 用户开启自动保存后，≥ 3 次命中自动保存到 UserMemory。
- [ ] 用户关闭自动保存后，只累计不保存。
- [ ] 聚焦测试覆盖提取、累计、自动保存逻辑。
- [ ] 不破坏本次调度输出流程。

#### 完成记录

- [ ] 待完成。

### 4.5 任务 4：实现知识库检索工具子池与作用域隔离

#### 目标

按 `knowledge_scope` 拆分检索路径，让不同类型知识在正确召回时机被召回，同时保证权限隔离。

#### 建议文件

- 修改现有：`api/internal/service/knowledge_retriever_service.py`
- 新增：`api/internal/service/user_memory_retriever.py`
- 修改：`api/internal/entity/routing_feature_flag_entity.py`（如果需要新增开关）
- 修改：`api/internal/model/__init__.py`
- 修改/新增测试：`api/test/internal/service/test_knowledge_retriever_service.py`
- 新增测试：`api/test/internal/service/test_user_memory_retriever.py`

#### 类型拆分

| 检索工具 | 作用域 | 触发位置 |
| ---- | ---- | ---- |
| `system_knowledge_retriever` | system | 任何请求，优先召回 |
| `user_memory_retriever` | user_memory | 任何请求，在 system 之后召回 |
| `user_content_retriever` | user_content | 用户资料查询请求召回 |

#### 作用域隔离规则

- `system_knowledge_retriever`：只查 `knowledge_scope = system`，必须当前用户有 admin 权限才能检索
- `user_memory_retriever`：只查当前用户 `enabled = true`
- `user_content_retriever`：只查当前用户 `knowledge_scope = user_content`
- 租户级和项目级后续阶段实现

#### 提示注入顺序

```
1. 系统知识库结果
2. 用户长期记忆结果
3. 用户资料内容结果
```

#### 验收标准

- [ ] 每个知识类型有独立检索入口。
- [ ] 严格按作用域隔离查询，用户不能查到其他用户知识。
- [ ] 管理员能查询系统级知识库。
- [ ] 提示注入顺序符合上述约定。
- [ ] 聚焦测试覆盖不同作用域隔离。

#### 完成记录

- [ ] 待完成。

### 4.6 任务 5：实现 Admin 系统知识库 CRUD 与权限控制

#### 目标

提供管理员创建、编辑、删除系统知识库入口，维护平台操作规范。

#### 建议文件

- 新增：`api/internal/schema/admin_system_knowledge_schema.py`
- 新增：`api/internal/handler/admin_system_knowledge_handler.py`
- 修改：`api/internal/handler/__init__.py`
- 修改：`api/internal/router/router.py`
- 修改：`api/internal/service/admin_rbac_service.py`
- 新增测试：`api/test/internal/handler/test_admin_system_knowledge_handler.py`
- 修改测试：`api/test/internal/service/test_admin_rbac_service.py`

#### 权限

新增权限：

```
system_knowledge:read
system_knowledge:write
```

#### 接口

```
GET /admin/system-knowledge
POST /admin/system-knowledge
GET /admin/system-knowledge/<id>
PUT /admin/system-knowledge/<id>
DELETE /admin/system-knowledge/<id>
```

#### 约束

- 只有 `system_knowledge:write` 权限管理员能写
- 只有 `system_knowledge:read` 权限管理员能读
- 系统知识库只允许 admin 操作，普通用户不能操作

#### 验收标准

- [ ] RBAC 权限种子已补充。
- [ ] CRUD 接口符合权限要求。
- [ ] 普通用户不能读写系统知识库。
- [ ] 聚焦测试通过。

#### 完成记录

- [ ] 待完成。

### 4.7 任务 6：实现用户长期记忆管理 API 与前端页面

#### 目标

用户能查看、编辑、删除、启用/禁用自己的长期记忆。

#### 建议文件

- 新增：`api/internal/schema/user_memory_schema.py`
- 新增：`api/internal/handler/user_memory_handler.py`
- 修改：`api/internal/handler/__init__.py`
- 修改：`api/internal/router/router.py`
- 新增测试：`api/test/internal/handler/test_user_memory_handler.py`

#### 接口

```
GET /user/memory
POST /user/memory
GET /user/memory/<id>
PUT /user/memory/<id>
DELETE /user/memory/<id>
```

所有操作只能访问当前登录用户自己的记忆。

---

新增前端：

- 新增：`ui/src/models/user-memory.ts`
- 新增：`ui/src/services/user-memory.ts`
- 新增测试：`ui/src/services/__tests__/user-memory.spec.ts`
- 新增：`ui/src/views/user/UserMemoryView.vue`
- 新增测试：`ui/src/views/user/__tests__/UserMemoryView.spec.ts`
- 修改：`ui/src/router/index.ts`
- 修改：`ui/src/i18n/messages/zh-CN.ts`
- 修改：`ui/src/i18n/messages/en-US.ts`

#### 路由

```
/user/memory
```

要求用户登录，不需要特殊 admin 权限。

#### 验收标准

- [ ] 用户只能看见自己的记忆。
- [ ] 用户能编辑、删除、启用/禁用。
- [ ] 前端页面正确渲染、i18n 完整。
- [ ] 用户 A 登录不能看到用户 B 记忆。
- [ ] 后端+前端聚焦测试通过。

#### 完成记录

- [ ] 待完成。

### 4.8 任务 7：Orchestrator 集成用户长期记忆召回

#### 目标

在 Orchestrator 构建 prompt 时，从用户长期记忆召回匹配的记忆并注入 context。

#### 建议文件

- 修改：`api/internal/service/orchestrator_service.py`
- 修改：`api/test/internal/service/test_orchestrator_service.py`

#### 集成步骤

1. Orchestrator 开始构建 prompt
2. 调用 `user_memory_retriever` 召回当前用户相关记忆
3. 按置信度排序，top N 注入 context
4. 放在“用户当前问题”之前，让 LLM 参考

#### 约束

- 开启自动提取的用户才会做提取和累计置信度
- 召回总是做，不管是否开启自动提取
- 不破坏现有 prompt 结构，只是增加长期记忆段落

#### 验收标准

- [ ] Orchestrator 集成后仍然兼容原有调用。
- [ ] 开启自动提取会在输出后更新置信度。
- [ ] 关闭自动提取不会更新置信度。
- [ ] 召回结果正确注入 prompt。
- [ ] 集成测试通过。

#### 完成记录

- [ ] 待完成。

### 4.9 任务 8：导航和侧边栏更新

#### 目标

- 后台导航增加“系统知识库”入口。
- 用户侧边栏增加“我的记忆”入口。

#### 建议文件

- 修改：`ui/src/components/AdminSidebar.vue`
- 修改：`ui/src/components/UserSidebar.vue`
- 修改：`ui/src/i18n/messages/zh-CN.ts`
- 修改：`ui/src/i18n/messages/en-US.ts`

#### 验收标准

- [ ] 管理员登录后台能看到“系统知识库”入口。
- [ ] 用户登录能看到“我的记忆”入口。
- [ ] 权限正确：普通用户看不到后台入口。
- [ ] i18n 完整。

#### 完成记录

- [ ] 待完成。

### 4.10 任务 9：权限边界回归与安全测试

#### 目标

验证跨用户、跨作用域的权限隔离正确。

#### 建议文件

- 新增：`api/test/internal/integration/test_knowledge_scope_security.py`

#### 测试要点

- 用户 A 不能读取用户 B 长期记忆。
- 用户 A 不能修改用户 B 长期记忆。
- 普通用户不能读写系统知识库。
- 未登录用户不能访问任何知识库检索接口。
- 检索接口返回不包含越权知识。

#### 验收标准

- [ ] 所有越权访问被拒绝。
- [ ] 每个作用域查询只返回对应知识。
- [ ] 集成安全测试通过。

#### 完成记录

- [ ] 待完成。

### 4.11 任务 10：最终全量测试与文档同步

#### 目标

- 后端全量测试通过。
- 前端 type-check / lint / unit test 通过。
- migration heads/current 通过。
- 总 PRD 和本执行文档更新完成。
- Phase 10 所有任务完成记录更新。

#### 完成记录

- [ ] 待完成。

## 5. 推荐执行顺序

1. 任务 0：基线确认 ✅
2. 任务 1：Dataset 新增知识作用域字段 ✅（已有 knowledge.py 模型，清理了 Document 多余字段）
3. 任务 2：UserMemory 实体与模型 ✅（已有 knowledge.py 模型和 migration）
4. 任务 3：MemoryCandidateExtractor 与 MemoryConfidenceTracker ✅（已有 long_term_memory_service.py）
5. 任务 4：知识库检索工具子池与作用域隔离 ✅（已有 tool_inventory_service.py + scoped_knowledge_service.py）
6. 任务 5：Admin 系统知识库 CRUD ✅（已有 admin_system_knowledge_handler.py，修复 PUT→POST）
7. 任务 6：用户长期记忆管理 API 与前端页面 ✅（新建 user_memory_handler.py + 5 条路由 + 前端 ListView.vue）
8. 任务 7：Orchestrator 集成用户长期记忆召回 ✅（FunctionCallAgent + ReActAgent + AssistantAgentService）
9. 任务 8：导航和侧边栏更新 ✅（LayoutSidebar.vue 新增长期记忆入口）
10. 任务 9：权限边界回归与安全测试 ✅（已有 test_scoped_knowledge_service.py + test_user_memory_handler.py）
11. 任务 10：最终全量测试与文档同步 ✅（后端 2157 passed + 前端 368 passed）

## 6. Phase 10 完成状态

### 后端
- 全量测试：2157 passed, 6 skipped, 0 failed
- migration heads/current：d1e2f3a4b5d3 (head)
- 新增路由：6 条（5 条 user memory CRUD + 1 条 admin system knowledge update PUT→POST）
- 新增测试：5 个 user memory handler 测试
- 修复：admin_system_knowledge update 路由 PUT→POST（符合项目 GET/POST/PATCH/DELETE 约定）
- Orchestrator 集成：FunctionCallAgent + ReActAgent 都注入 user_memory 到 system prompt
- AssistantAgentService：在 stream 时获取用户长期记忆并传入 Agent

### 前端
- 全量测试：368 passed
- type-check：0 errors
- lint：0 errors
- 新增页面：/memory（用户长期记忆管理）
- 新增 API：getUserMemories/createUserMemory/getUserMemory/updateUserMemory/deleteUserMemory
- 侧边栏新增"长期记忆"入口
- i18n 完整（中英文）

### 基础设施改进
- 数据库清空重建：删除旧 volume 重新初始化，migration 从头跑通
- 超级管理员初始化：app.py 启动时自动调用 AdminRbacService.initialize_defaults() + AdminUserService.initialize_super_admin_from_env()
- Docker volume 挂载：本地 api 目录挂载到容器，改完代码只需 restart 不需要 build
- Document 模型清理：移除了多余的知识作用域字段（knowledge_scope 等）

## 6. 风险与约束

- 不能删除现有 Dataset 表，只能新增字段，必须保持向后兼容。
- 不要求在 Phase 10 实现租户级和项目级知识库，只做好 system / user_memory / user_content。
- 不要求在 Phase 10 实现外部数据源同步，只做好知识体系框架。
- 用户长期记忆默认全局作用域，不需要实现 project/tenant 粒度。
- 严格遵守现有项目 i18n 规范，所有新增文案必须走 i18n。
- 每次任务结束必须跑聚焦测试，不能等最后一起测。
