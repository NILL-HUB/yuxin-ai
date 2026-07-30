# 知识库系统完善路线图

> **状态**：执行中
> **创建日期**：2026-07-06
> **基于**：architecture-design.md 第 11 节（知识库双层设计）+ 现状代码审计

## 一、现状摘要

经代码审计，知识库后端底座已远超架构文档 v4.0 审计描述，RAG 管线与记忆候选提取均已功能完整。

### 已具备（可复用）

| 能力 | 实现位置 | 状态 |
| --- | --- | --- |
| KnowledgeBase/Document/Segment/UserMemory/MemoryCandidate/ExternalDataSource 模型 | model/knowledge.py | ✅ 完整（含 scope/owner/visibility 全字段） |
| 数据库迁移 | d1e2f3a4b5c7 + e1f2a3b4c5d7 + j1e2f3a4b5c0 + d1e2f3a4b5d5 | ✅ 字段无漂移 |
| RAG 管线：parsing→splitting→indexing→completed | KnowledgeIndexingService | ✅ 完整 |
| 向量检索 + rerank（semantic/full_text/hybrid） | KnowledgeVectorService + RetrievalService | ✅ 完整 |
| 系统级知识库 CRUD API + RBAC | admin_system_knowledge_handler + SystemKnowledgeService | ✅ 完整 |
| 长期记忆候选 LLM 抽取（6 类记忆） | MemoryCandidateExtractor | ✅ 已升级（非硬编码） |
| 置信度累计 + 3 次触发 | MemoryConfidenceTracker | ✅ 完整 |
| 记忆确认/忽略流程 | UserMemoryConfirmationService | ✅ 基础完整 |
| 记忆向量索引 + 召回 | MemoryVectorService + UserMemoryService.recall_relevant_memories | ✅ 完整 |
| 用户资料库上传 + 索引 | KnowledgeBaseService.upload_document | ✅ 完整 |
| 外部数据源连接 + 授权 + 手动同步骨架 | ExternalDataSourceService + ConnectorFactory | ✅ 骨架完整 |
| KnowledgeBase LangChain 检索工具 | RetrievalService.create_knowledge_retrieval_tool | ✅ 完整 |

### 主要 Gap

| # | Gap | 影响 |
|---|-----|------|
| K1 | dataset_retrieval 工作流节点仍用旧版 Dataset 检索，未接入新版 KnowledgeBase | 工作流无法用新知识库 |
| K2 | 外部数据源 manual_sync 创建 Segment 但不写向量库 | 同步文档无法被检索召回 |
| K3 | 记忆 confirm() 不支持"编辑后保存" | 用户无法修正候选记忆内容 |
| K4 | 缺"后续自动保存"全局开关 + 阈值可配置 | 记忆体验不完整 |
| K5 | KnowledgeCreatedFrom 缺 WORKFLOW_IMPORT 枚举 | 与架构文档 11.2 不一致 |
| K6 | Admin 端无系统知识库管理 UI（后端 API 已就绪） | 管理员无法在界面管理系统知识 |
| K7 | 前端两套记忆实现并存（完整版未挂路由+硬编码中文；简版挂路由+i18n） | 记忆管理混乱 |
| K8 | AdminDatasetSegmentsView 纯只读，无 CRUD | 片段管理不完整 |

## 二、任务拆分（3 个并行 Track）

### Track A：后端修复与增强（独立，无前端依赖）

| 任务 | 文件 | 说明 |
| --- | --- | --- |
| **A1 升级 dataset_retrieval_node 接入 KnowledgeBase** | dataset_retrieval_node.py, dataset_retrieval_entity.py | 节点支持选择 KnowledgeBase（新增 knowledge_base_ids 字段），调用 RetrievalService.create_knowledge_retrieval_tool；保留 dataset_ids 向后兼容 |
| **A2 修复外部数据源同步写向量库** | external_data_source_service.py | manual_sync 创建 KnowledgeSegment 后调用 KnowledgeVectorService.index_segment()，使同步文档可被检索召回 |
| **A3 记忆增强：编辑后保存 + 自动保存开关 + 阈值可配置** | long_term_memory_service.py, scoped_knowledge_service.py, user_memory_handler.py | confirm() 支持 edited_content 参数；新增用户记忆设置（auto_save/never_remind/threshold）存取；UserMemoryService 增加设置读写方法 |
| **A4 补 WORKFLOW_IMPORT 枚举** | knowledge_entity.py | KnowledgeCreatedFrom 新增 WORKFLOW_IMPORT = "workflow_import" |

### Track B：前端系统知识库管理 UI（独立，后端 API 已就绪）

| 任务 | 文件 | 说明 |
| --- | --- | --- |
| **B1 创建 admin-system-knowledge service + model** | services/admin-system-knowledge.ts, models/admin-system-knowledge.ts | listSystemKnowledge/createSystemKnowledge/getSystemKnowledge/updateSystemKnowledge/deleteSystemKnowledge，对接 /admin/system-knowledge |
| **B2 创建 AdminSystemKnowledgeView.vue** | views/admin/AdminSystemKnowledgeView.vue | 卡片网格列表（跨账号）+ 创建/编辑弹窗（name/description/visibility_scope）+ 删除确认；复用 ResourceCardDescription + CardGridSkeleton |
| **B3 路由 + 菜单 + i18n + 权限** | router/index.ts, AdminLayout.vue, i18n/messages/zh-CN.ts, en-US.ts | 新增 admin-system-knowledge 路由（permission: system_knowledge:read），菜单"系统知识库"置于资源编排分组，i18n 双语 |

### Track C：前端记忆体系统一 + 片段 CRUD（独立，无后端依赖）

| 任务 | 文件 | 说明 |
| --- | --- | --- |
| **C1 统一记忆 UI** | views/settings/MemoryView.vue, views/memory/ListView.vue, services/memory.ts, services/user-memory.ts, models/memory.ts | 合并两套实现：保留完整版（候选记忆确认+CRUD），接入 i18n（memory.* 键），挂载到 /memory 路由，删除冗余简版 |
| **C2 AdminDatasetSegmentsView 补 CRUD** | views/admin/AdminDatasetSegmentsView.vue, services/admin-dataset-segments.ts | 复用用户侧 dataset.ts 的 createSegment/updateSegment/deleteSegment/updateSegmentEnabled（与文档治理同模式），补新增/编辑弹窗+启停+删除 |

## 三、并行执行策略

```
Track A（后端修复）     ████████░░░░░░░░░░░░  独立
Track B（系统知识 UI）  ░░░░████████░░░░░░░░  独立（后端 API 已就绪）
Track C（记忆统一+片段） ░░░░░░░░░░████████░░  独立
                        ↑ 三 Track 完全并行
```

三 Track 无文件冲突、无依赖关系，可完全并行执行。完成后统一测试验证。

## 四、验收标准

| 指标 | 目标 |
| --- | --- |
| 工作流检索节点 | 支持选择 KnowledgeBase 并成功检索 |
| 外部数据源同步 | 同步后文档可被向量检索召回 |
| 记忆编辑保存 | confirm 支持传入编辑后内容 |
| 记忆自动保存 | 用户可设置全局自动保存开关 |
| 系统知识库 UI | 管理员可在 admin 端 CRUD 系统知识库 |
| 记忆 UI 统一 | 单一记忆管理页，i18n 完整，候选确认可用 |
| 片段 CRUD | Admin 端可新增/编辑/启停/删除片段 |
| 测试 | pytest 通过（不新增失败），vue-tsc 通过 |
