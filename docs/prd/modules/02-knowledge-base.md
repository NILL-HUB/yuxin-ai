# 知识库双层设计

> 本文档为主架构文档的子模块，包含系统级知识库、用户资料内容库、检索优先级与隔离策略、现有能力评估和工具池关系的完整内容。
>
> **注意**：用户长期记忆库（原 11.3.1）已由第 16 章[脑启发记忆系统](../architecture-design.md#16-脑启发记忆系统v50-新增)完全接管，不在知识库系统范围内。本文档仅保留 11.3.1 的入口说明和与资料内容库的差异对比。
>
> **主文档**: [architecture-design.md](../architecture-design.md)
> **相关模块**: [01-agent-tool-pool.md](./01-agent-tool-pool.md) | [记忆系统子文档](../memory-system/01-data-models-and-write-path.md)

---

## 11. 知识库双层设计

知识库需要区分系统级知识库和用户个人知识库。两者都可以进入检索工具体系，但定位、权限、数据来源和使用方式不同。

### 11.1 系统级知识库

管理员端的知识库应改名和定位为系统级知识库。它存放的是底层知识、系统性知识、通用操作经验和 Agent 执行规范，用于优化 Agent 的操作体验和执行质量。

系统级知识库内容包括：

- 平台使用说明。
- Agent 操作规范。
- 工具调用说明。
- 通用行业知识。
- 通用办公模板。
- 通用代码规范。
- 常见错误处理经验。
- 系统推荐工作流。
- 管理员沉淀的最佳实践。

系统级知识库的特点：

| 维度 | 策略 |
| --- | --- |
| 维护者 | 管理员 |
| 作用对象 | Agent、Orchestrator、工具选择、结果汇总 |
| 可见性 | 普通用户不直接管理，必要时可引用公开内容 |
| 用途 | 提升系统基础能力，让 Agent 更会用工具、更懂平台规则 |
| 权限 | 平台级或租户级权限控制 |

系统级知识库不应记录某个用户的私人偏好，也不应混入用户个人资料。

### 11.2 管理员身份与知识库归属边界

**管理员与用户端账号已彻底解耦（迁移 `e0a1b2c3d4e5` 起）**：`admin_user.account_id` 恒为 `NULL`，管理员账号**不绑定**普通 `Account`，管理员登录后只有管理员身份，**没有用户端身份**；管理员 JWT（`realm=admin`）访问用户端接口一律 403（见 `docs/rbac.md` §8）。因此**不存在**「管理员既是管理员又是某个用户」的双身份情形。

归属判定只取决于**操作上下文 + 知识库作用域**，且两者一一对应：

```text
用户端上下文（Account 身份）  -> owner_account_id=<用户 id>，owner_admin_user_id=NULL -> user_memory / user_content
管理端上下文（AdminUser 身份） -> owner_account_id=NULL，owner_admin_user_id=<管理员 id> -> system / tenant / project
```

`KnowledgeBase` 的归属字段是**互斥**的：`create_user_base` / `create_user_memory_base` 强制 `owner_account_id=account.id` + `owner_admin_user_id=None`；`create_system_base` 强制 `owner_account_id=None` + `owner_admin_user_id=admin_user.id`，且非管理员调用直接 `ForbiddenException("普通用户不能创建系统级知识库")`。

判定矩阵：

| 操作人 | 操作入口 | 操作上下文 | knowledge_scope | 归属 |
| --- | --- | --- | --- | --- |
| 普通用户 | /home 或用户知识库页面 | user | user_memory | 用户长期记忆库 |
| 普通用户 | /home 或用户知识库页面 | user | user_content | 用户资料内容库 |
| 管理员 | 配置中心 / 系统知识库管理 | admin | system | 系统级知识库 |
| 管理员 | 配置中心 / 租户知识库管理 | admin | tenant | 租户级知识库 |
| 管理员 | 配置中心 / 项目知识库管理 | admin | project | 项目级知识库 |

因此需要在知识库数据模型中增加或明确以下字段：

| 字段 | 说明 |
| --- | --- |
| owner_account_id | 资源实际归属的用户账号（管理员创建的管理级知识库为 NULL） |
| owner_admin_user_id | 由管理员在管理上下文创建时记录管理员身份（用户个人知识库为 NULL） |
| operation_context | user / admin / system_job，表示创建或修改时的操作上下文 |
| knowledge_scope | system / tenant / project / user_memory / user_content |
| visibility_scope | private / team / tenant / public / internal |
| target_tenant_id | 租户级知识库归属 |
| target_project_id | 项目级知识库归属 |
| created_from | manual_upload / conversation_memory / admin_config / workflow_import / external_sync |

边界规则：

1. 管理员要拥有自己的用户长期记忆库 / 用户资料内容库，必须**走用户端注册一个用户账号**（管理员账号本身没有个人知识库）。
2. 管理员在配置中心创建知识库时，只有显式选择 `system`、`tenant` 或 `project` 作用域时，才进入对应管理级知识库。
3. 系统级知识库必须要求管理员权限，并记录 `owner_admin_user_id`、操作日志和发布状态。
4. 系统级知识库的内容可以被普通用户任务检索引用，但普通用户不能直接写入或管理。
5. 用户个人知识库只服务该用户本人——管理员身份不会让任何用户知识库自动变成系统知识（两个 realm 不互通）。

### 11.3 用户个人知识库

用户应该拥有自己的个人知识库，但需要进一步拆成两类：

1. **用户长期记忆库**：基于用户提问、回答反馈、反复表达的偏好和习惯形成的长期记忆。
2. **用户资料内容库**：用户主动上传的文档、图片、视频、音频等资料内容，用于任务检索和上下文增强。

这两类都属于用户个人知识体系，但数据来源、存储结构、确认方式和调用方式不同。

#### 11.3.1 用户长期记忆库

长期记忆库用于沉淀用户偏好、习惯、常用表达、工作方式和个性化规则，让系统越用越懂用户。

长期记忆来源包括：

- 用户反复表达的回答风格偏好。
- 用户明确纠正过的术语、格式和口径。
- 用户经常使用的项目背景和业务上下文。
- 用户在对话中明确说"以后都这样""记住这个偏好"的内容。
- Agent 从用户提问和反馈中识别出的稳定习惯。

> **记忆系统独立运行**：长期记忆库由第 16 章[脑启发记忆系统](../architecture-design.md#16-脑启发记忆系统v50-新增)完全接管。记忆的写入、存储、检索、巩固和用户管理全部由记忆系统负责，不在知识库系统范围内。知识库系统只负责"用户资料内容库"（11.3.2）。
>
> **设计变更**：旧设计的"候选→置信度累计→用户逐条确认→保存"流程已被**自动写入 + 图可视化事后管理**替代。SalienceScorer 评分后自动写入 Neo4j TKG + PostgreSQL pgvector，用户通过图可视化界面随时 CRUD 自己的记忆。系统处于二开阶段，旧代码已删除，不做向后兼容。
>
> 记忆系统的完整设计详见：
> - [memory-system/01-data-models-and-write-path.md](../memory-system/01-data-models-and-write-path.md) — 写入路径（SalienceScorer 评分 + 自动写入）
> - [memory-system/02-storage-and-retrieval.md](../memory-system/02-storage-and-retrieval.md) — 存储检索 + 图可视化 + 降级策略
> - [memory-system/03-consolidation-skill-policy-api.md](../memory-system/03-consolidation-skill-policy-api.md) — 巩固引擎 + API + Policy

长期记忆支持用户通过图可视化界面管理：

- 查看记忆图谱（聚类视图 → 子图视图 → 节点详情）。
- 编辑记忆内容（创建新节点 + 旧节点失效）。
- 软删除记忆（is_active=false，可恢复）。
- 彻底删除记忆（不可恢复）。
- 降低记忆权重（手动触发 HebbianDecay）。
- 按类型、时间范围、关键词筛选。

#### 11.3.2 用户资料内容库

用户资料内容库用于存储用户主动上传、授权接入或从外部数据源同步的资料内容。它更接近现有 Dataset / Document / Segment 知识库能力。

资料内容包括：

- 文档：md、doc、docx、txt、pdf、csv、xlsx、xls、html 等。
- 外部数据源：飞书、Notion、本地文件夹、GitHub 等（同步导入的资料）。
- 其他结构化或半结构化业务资料。
- 图片：jpg、jpeg、png、webp、gif、svg 等，L1 视觉理解已落地，细粒度 OCR 区块坐标等 L2 增强未实现。
- 视频：产品演示、会议录像、课程视频等，L1（音轨 ASR + 关键帧视觉描述 + 关键帧留存）与 L2（区间窗口密抽 + 逐帧视觉详述）均已落地。
- 音频：会议录音、访谈、播客、语音备忘等，L1 ASR 转写已落地，说话人切分等 L2 增强未实现。

资料内容库需要支持：

| 能力 | 说明 |
| --- | --- |
| 上传 | 用户主动上传文件 |
| 外部数据源连接 | 用户授权连接飞书、Notion、本地文件夹、GitHub 等外部数据源 |
| 同步 | 支持手动同步与 Celery 定时自动同步（每 6 小时扫描已授权数据源） |
| 解析 | 文本与结构化资料走 parsing→splitting→indexing；图片/音频/视频走 L1 多模态解析直达入库（见 §11.8），视频可再按需触发 L2 区间窗口密抽（见 §11.11） |
| 分段 | 将长内容切分为可检索片段 |
| 索引 | 建立向量、全文和关键词索引 |
| 检索 | 按任务动态召回相关资料 |
| 权限 | 用户级、项目级、团队级隔离 |
| 管理 | 用户可删除、禁用、重命名、重新索引 |

#### 11.3.3 两类个人知识库的差异

| 维度 | 用户长期记忆库 | 用户资料内容库 |
| --- | --- | --- |
| 管理系统 | 记忆系统（第 16 章） | 知识库系统（本章） |
| 来源 | 对话中自动提取 | 用户上传或连接的数据源 |
| 内容 | 偏好、习惯、口径、长期规则 | 文档、图片、视频、音频、业务资料 |
| 写入方式 | SalienceScorer 评分后自动写入 | 用户主动上传或授权同步 |
| 存储介质 | Neo4j TKG + PostgreSQL pgvector | PostgreSQL pgvector |
| 检索方式 | MemoryRetriever（图遍历 + 向量混合） | layered_search（分层作用域检索） |
| 调用方式 | 优先影响回答风格、默认偏好和任务策略 | 作为任务资料被检索引用 |
| 风险 | 错误记忆、过度个性化、隐私偏好泄露 | 私有文件泄露、跨用户检索、解析失败 |
| 管理方式 | 图可视化界面 CRUD（软删除/彻底删除/编辑/降权） | 知识库管理页面 CRUD（文件/文档/片段/索引） |
| 生命周期 | HebbianDecay 自动衰减 + ConsolidationEngine 定期整理 | 手动删除 / 禁用 |

用户个人知识库的整体特点：

| 维度 | 策略 |
| --- | --- |
| 维护者 | 用户本人，管理员可按合规策略管理存储和配额 |
| 作用对象 | 主入口回答、个性化 Agent、用户任务上下文 |
| 可见性 | 默认仅用户本人和授权范围可见 |
| 用途 | 个性化、长期偏好、私有业务上下文、资料检索 |
| 权限 | 用户级、团队级、项目级权限控制 |

### 11.4 检索优先级与隔离策略

执行任务时，知识检索应按作用域分层：

```text
任务上下文
  -> 用户个人知识库
  -> 用户团队 / 项目知识库
  -> 租户级知识库
  -> 系统级知识库
  -> 公共知识源
```

检索策略：

1. 用户个性化问题优先检索用户个人知识库。
2. 工具使用、Agent 操作、平台规则优先检索系统级知识库。
3. 两类知识库可以同时参与，但必须在结果中保留来源作用域。
4. 用户个人知识库不得污染系统级知识库。
5. 系统级知识库不得泄露管理员内部敏感信息给普通用户。
6. ResultSynthesizer 需要区分“系统规则”和“用户偏好”，冲突时系统规则优先，表达风格可尊重用户偏好。

> **与脑启发记忆系统的融合**：第 16 章定义的 System 1/System 2 双系统架构为分层检索提供了上层路由能力。System 1（快速路径）通过 Memory Digest 直接注入用户画像和活跃技能，无需触发完整分层检索；System 2（慢速路径）在分层检索基础上增加 TKG 图扩展激活（SpreadActivation）和五层漏斗压缩（FunnelCompressor），提升深层记忆召回精度。当前 layered_search 按 knowledge_scope 分 5 层独立检索的架构保持不变，System 2 的图检索和漏斗压缩作为每层内部的检索算法增强。

### 11.5 现有知识库能力评估

当前系统已经有一套 Dataset / Document / Segment 体系，适合演进为“用户资料内容库”的基础，但还不能完整满足“用户长期记忆库”和多媒体资料库需求。

已具备能力：

| 能力 | 现有实现 |
| --- | --- |
| 知识库管理 | `KnowledgeBase` 模型、创建、更新、删除、分页、搜索（原 `Dataset` 命名已弃用，迁移 `x1a2b3c4d5e6`） |
| 文档管理 | `KnowledgeDocument` 模型、上传后创建文档、启用 / 禁用、删除、重命名 |
| 片段管理 | `KnowledgeSegment` 模型、片段增删改查、启用 / 禁用、命中次数 |
| 文件上传 | 通过 `UploadFile` 关联文档 |
| 文档处理 | 支持 automatic / custom 处理规则、分段规则、chunk_size、chunk_overlap |
| 索引状态 | waiting、parsing、splitting、indexing、completed、error |
| 检索策略 | semantic、full_text、hybrid |
| 检索工具 | 运行时名为 `search_knowledge_base`（`KNOWLEDGE_RETRIEVAL_TOOL_NAME`），可被 Agent / Workflow 调用；支持 `partition_id` / `media_types` / `tags` / `score_threshold` 四个可选过滤入参（KB-P3，见 §11.9.3）；`dataset_retrieval` / `recall_dataset` 作为历史别名保留在别名映射中 |
| 召回测试 | `/space/knowledge-bases/<uuid>/hit` 支持召回测试；admin 侧 `/admin/system-knowledge/<uuid>/hit-test` |
| App 绑定 | `AppConfig.knowledge_base_ids`（JSONB）支持应用绑定知识库 |
| Workflow 绑定 | `dataset_retrieval` workflow node 支持工作流检索知识库 |

**代码审计修正（v5.0，2026-09）**：

RAG 检索管线**已完整落地**，不再只是基础 CRUD：

- 索引链路：`KnowledgeIndexingService`（`api/internal/service/knowledge_indexing_service.py`）实现 `_parsing` → `_splitting` → `_indexing` → `_completed` 全流程，逐阶段更新 `Document`/`Segment` 状态。
- 向量检索：`knowledge_vector_service.py` 负责向量化与相似度召回。
- Rerank：`retrieval_service.py` 在召回后执行重排，provider rerank 不可用时走 LLM 兜底（`rerank_fallback`）。
- App 绑定：早期文档提到的 `AppDatasetJoin` 关联表**不存在**，App 与知识库的绑定已改为 `AppConfig.knowledge_base_ids` 列。

现有 TokenBufferMemory 仅是会话短期上下文裁剪（trim_messages strategy="last" max_tokens=2000），不是跨会话长期记忆。长期记忆已由第 16 章脑启发记忆系统完全接管，旧记忆系统代码（long_term_memory_service.py 的 MemoryCandidateExtractor / MemoryConfidenceTracker / UserMemoryConfirmationService）已删除。

当前支持较好的资料类型：

| 类型 | 当前情况 |
| --- | --- |
| 文档 | 已支持 md、doc、docx、txt、pdf、csv、xlsx、xls、html 等 |
| 图片 | 上传层允许 jpg、jpeg、png、webp、gif、svg；L1 视觉理解 + OCR 入库已落地（KB-P2A）；细粒度 OCR 区块坐标等 L2 增强未实现 |
| 视频 | L1 音轨 ASR 转写 + 关键帧抽取 + 视觉描述入库、关键帧留存为 UploadFile（KB-P2A + KB-P3）；关键帧视觉向量索引与 L2 区间窗口密抽（逐帧视觉详述）已落地（KB-P3，见 §11.10 / §11.11）；场景切分未实现 |
| 音频 | L1 ASR 全文转写入库已落地（KB-P2A）；说话人切分、章节切分等 L2 增强未实现 |

明确缺口（KB-P1 数据基座落地后已消解项标注 ✅）：

1. 现有 `KnowledgeBase` 已演进为"用户资料内容库 + 板块"的载体，分层作用域、板块类型与分区体系均已落地（多模态 L1 解析入库见 §11.8，检索取料过滤能力见 §11.9）。
2. 现有 `TokenBufferMemory` 只是会话短期上下文裁剪，不是跨会话长期记忆。长期记忆由第 16 章记忆系统负责。
3. ✅ 已消解：`KnowledgeBase.knowledge_scope` 已落地，可区分系统级知识库、用户资料内容库、团队/租户/项目知识库。
4. ✅ 已消解：归属判断已引入 `owner_account_id` + `owner_admin_user_id`，可区分"管理员自己的个人知识库"和"管理员维护的系统级知识库"。
5. ✅ 已消解：`operation_context`、`owner_admin_user_id`、`visibility_scope` 字段已落地，可表达管理上下文和发布范围。
6. 长期记忆管理已由第 16 章记忆系统接管（图可视化 CRUD），知识库系统不再负责记忆管理。
7. 资料库的**多媒体 L1 基础解析（图片视觉摘要 + OCR、音频 ASR、视频音轨 ASR + 关键帧视觉描述 + 关键帧留存）已接入索引链路**（KB-P2A + KB-P3，见 §11.8）；**关键帧视觉向量索引与 L2 按需解析（视频区间窗口密抽 + 逐帧视觉详述）已在 KB-P3 落地**（见 §11.10 / §11.11）；说话人切分、细粒度 OCR 坐标、场景切分仍未实现。
8. 外部数据源连接与同步**已实现**：`ExternalDataSource` 模型 + lark/notion/github 连接器（真实 API）+ 本地文件夹连接器；凭证经 Fernet 加密存储、API 返回脱敏；支持手动同步与 Celery 定时自动同步；删除数据源时级联清理同步产物（文档/分段/向量/上传文件）。
9. ✅ 已消解：分层检索（`layered_search` 按 `knowledge_scope` 分层）已落地，不再只按 account_id 做基础隔离。
10. 现有 App 绑定知识库是预绑定模式，后续需要接入动态知识检索工具子池（KB-P3 范围）。

由于当前系统没有必须保留的旧数据，数据库模型可以按目标架构直接重构，不需要为了兼容历史数据做复杂迁移策略。实施时可以优先保证新模型清晰，而不是维持旧字段语义。

建议演进方式：

```text
KnowledgeBase / KnowledgeDocument / KnowledgeSegment（原 Dataset / Document / Segment 命名）
  -> 已重构为带 knowledge_scope、owner_scope、visibility_scope 的知识库模型
  -> 已落地 operation_context 与 owner_admin_user_id
  -> 承载系统级知识库 + 用户资料内容库
  -> 新增系统级知识库管理入口和发布状态
  -> 再统一接入 knowledge tool pool
  -> 外部数据源连接/同步已落地（凭证加密 + 定时自动同步 + 级联清理）
  -> 注：长期记忆已由第 16 章记忆系统接管，不在知识库系统改造范围内
```

数据模型策略：

| 模型方向 | 策略 |
| --- | --- |
| KnowledgeBase（原 Dataset） | ✅ 已完成——直接重命名为 `KnowledgeBase`，未保留旧数据兼容逻辑 |
| KnowledgeDocument / KnowledgeSegment | 已按资料内容库重新设计字段，第一阶段优先文本和结构化资料，多媒体解析字段预留但能力后置 |
| UserMemory | 新增独立模型，不复用知识库模型承载长期习惯 |
| ExternalDataSource | 新增外部数据源连接模型，记录来源类型、授权状态、同步状态和作用域 |
| KnowledgeScope | 作为核心枚举字段设计，不作为后补字段 |
| Owner / Visibility | 初始模型就纳入 owner_account_id、owner_admin_user_id、visibility_scope |
| 迁移脚本 | 只需要建新表或重建表，不需要历史数据迁移和兼容转换 |

### 11.6 与工具池的关系

知识库不是单纯的文档页面，而应作为知识检索工具子池进入 ToolPool：

```text
knowledge tool pool
  -> system_knowledge_retriever
  -> user_memory_retriever
  -> user_content_retriever
  -> tenant_knowledge_retriever
  -> project_knowledge_retriever
```

Agent 不直接访问全部知识库，而是通过 ToolPolicyFilter 获取本次任务允许访问的知识检索工具子集。

### 11.7 知识库板块与分区体系（KB-P1 已落地）

KB-KB-KB-P1 数据基座已落地，知识库从"扁平文本库"升级为**全媒体素材中心**的组织结构：板块类型（`base_type`）决定板块可容纳的媒体、分区（`KnowledgePartition`）提供两级归类、标签（复用 `Tag`）提供多重属性，容量由存储配额统一管控。设计源头见 [knowledge-base-product-form-design.md](../knowledge-base-product-form-design.md) §二。

#### 11.7.1 板块类型 base_type（硬约束）

`knowledge_base.base_type` 决定该板块允许上传的媒体类型，**由服务端强制校验**（类型不符直接拒绝，不依赖前端提示）。枚举定义在 `internal/entity/knowledge_entity.py::KnowledgeBaseType`：

| base_type | 允许的媒体类型 | 拒绝行为 | 默认 |
| --- | --- | --- | --- |
| `document` | 文档类（md/doc/docx/pdf/txt/csv/xlsx/html 等） | 图片/音视频 → 服务端拒绝 | |
| `image` | 图片类（jpg/jpeg/png/webp/gif/svg） | 文档/音视频 → 服务端拒绝 | |
| `video` | 视频类（mp4/mov/avi/mkv/webm） | 文档/图片/音频 → 服务端拒绝 | |
| `audio` | 音频类（mp3/wav/m4a/aac/flac） | 文档/图片/视频 → 服务端拒绝 | |
| `mixed` | 不限 | 兼容存量库 | ✅ |

类型到扩展名的映射与两个工具函数 `allowed_extensions_for_base_type()` / `media_type_for_extension()` 位于 `internal/entity/upload_file_entity.py`。`KnowledgeBaseService.create_user_content_base()` 对 `base_type` / `partition_mode` 做取值校验，非法值抛 `ValidateErrorException`。存量 `KnowledgeBase` 默认迁移为 `mixed`（见 §11.7.7 迁移）。

**用户端创建入口**：`POST /space/knowledge-bases` 接受可选 `base_type` / `partition_mode`（未传分别默认 `mixed` / `none`）。用户端知识库列表页（`ui/src/views/space/datasets/ListView.vue`）的新建弹窗提供两个选择器，用户可显式选择板块类型与分区模式；编辑已有库时板块类型选择器置灰（后端语义上不允许中途变更板块类型，避免改变该库允许上传的扩展名），且更新接口不提交这两个字段。

#### 11.7.2 分区模式 partition_mode

`knowledge_base.partition_mode` 定义分区的产生方式，枚举 `PartitionMode`：

| 模式 | 行为 |
| --- | --- |
| `none` | 不分分区，素材平铺（默认） |
| `date_month` | 上传自动归入 `2026-09`，系统按需自动建分区 |
| `date_day` | 上传自动归入 `2026-09-12` |
| `custom` | 用户/小钰手动建命名分区（如「春季新品」） |

#### 11.7.3 KnowledgePartition 两级树

新增 `knowledge_partition` 表承载分区，`parent_id` 自引用形成两级树（父级 `parent_id` 为空表示顶层分区）：

| 字段 | 说明 |
| --- | --- |
| `knowledge_base_id` | 所属板块，级联删除（`ondelete=CASCADE`） |
| `name` | 分区显示名 |
| `partition_key` | 分区业务键，日期模式为 `2026-09`/`2026-09-12`，自定义模式为 slug；同库唯一（`uq_knowledge_partition_base_key`） |
| `parent_id` | 父分区，为空即顶层 |
| `sort_order` | 同级排序 |
| `enabled` | 是否启用 |
| `visibility_scope` | 权限字段预留，默认继承板块可见性（首版分区级权限不做） |

**层级由服务层强制**：`KnowledgePartitionService.create_partition()` 校验父分区存在（否则抛 `FailException`）且父分区自身必须是顶层，第三级创建直接抛 `ValidateErrorException`（`MAX_PARTITION_DEPTH = 1`），避免深树带来的 UI 混乱与 Agent 导航复杂化。`parent_id` 结构天然支持未来放开更深层级，不需改表。

**用户端分区入口**（`api/app/http/knowledge_mcp_routes.py`）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/space/knowledge-bases/<uuid>/partitions` | 列出该板块全部分区（按 `sort_order`、`created_at` 排序），前端据此渲染两级树 |
| POST | `/space/knowledge-bases/<uuid>/partitions` | 创建分区；`name` 必填，`partition_key` 未传时由 `name` 派生，`parent_id` 可选（非空即建为二级） |
| POST | `/space/knowledge-bases/<uuid>/partitions/<uuid>/delete` | 删除分区；**仅空分区可删**——有子分区或仍挂着素材时抛错，避免孤儿分区与素材失去归属 |

三条路由均先调用 `KnowledgeBaseService.get_accessible_base` 校验板块归属，避免越权读取/改动他人分区结构。

`KnowledgePartitionService.delete_partition(knowledge_base_id, partition_id)` 的校验顺序：先查子分区 → 再查该分区下是否仍有 `KnowledgeDocument` → 最后按 `(id, knowledge_base_id)` 定位并删除。

分区权限首版不做——分区是组织手段而非权限边界，权限仍在板块层。

#### 11.7.3.1 对话内建库工具 `create_knowledge_base`

小钰可在对话里直接为用户建板块，工具位于 `api/internal/core/tools/builtin_tools/providers/knowledge_base_tools/`（provider 登记在 `providers.yaml`，`category=tool`）：

- 参数：`name`（必填）、`base_type`、`partition_mode`、`description`。
- 工具内部对 `base_type` / `partition_mode` 做白名单校验（非法值返回可读错误而非抛异常），再调用 `KnowledgeBaseService.create_user_content_base(operation_context="user", ...)`。
- **account 传递**：builtin 工具无全局 `g.account`，沿用 `computer_control` / `host_os` 的范式——运行时挂载点（`assistant_agent_service.py` 的 `_build_assistant_runtime_tools`）用 `kb_tool_factory(account_id=str(account_id))` 注入；工具内再用 `AccountService.get_account()` 换成真实 `Account` 实例（服务层依赖 `account.id`）。
- 只能为**当前登录用户**创建其私有板块，不能代他人建库。

#### 11.7.4 标签关联（复用既有 Tag）

复用 `Tag` 模型与 `TagAssignmentService` 的自动打标能力，仅将作用对象从 App/Workflow 扩展到知识库，对齐既有 `AppTag` / `WorkflowTag` 模式，新增两张关联表：

| 模型 | 表 | 关联 | 唯一约束 | 用途 |
| --- | --- | --- | --- | --- |
| `KnowledgeBaseTag` | `knowledge_base_tag` | 板块 ↔ `Tag` | `(knowledge_base_id, tag_id)` | 跨板块索引导航 |
| `KnowledgeDocumentTag` | `knowledge_document_tag` | 素材 ↔ `Tag` | `(knowledge_document_id, tag_id)` | 素材属性过滤 |

两表均含 `account_id`，标签或板块/素材删除时关联级联清理。

**分区与标签的分工**：分区是互斥层级归类（一个素材只能在一个分区），标签是可交叉叠加的属性（一个素材可有多个标签）。

**服务层 `KnowledgeTagService`**（`internal/service/knowledge_tag_service.py`，KB-P3 已落地），6 个方法：

| 方法 | 职责 |
| --- | --- |
| `attach_base_tag(account_id, knowledge_base_id, tag_id)` | 为板块打标签（幂等：已存在关联直接返回原记录） |
| `attach_document_tag(account_id, knowledge_document_id, tag_id, verify_document=False)` | 为素材打标签（幂等）；`verify_document=True` 时先校验素材存在，不存在抛 `FailException` |
| `detach_document_tag(knowledge_document_id, tag_id)` | 移除素材标签，返回是否确有移除（不存在返回 `False` 而非抛错） |
| `list_document_tags(knowledge_document_id)` | 列出素材全部标签（返回 `Tag` 列表） |
| `resolve_tag_ids_by_names(names)` | 标签名 → 标签 id（供检索工具按名过滤）；名称解析不到时忽略该名称 |
| `document_ids_for_tags(tag_ids, match_all=False)` | 按标签查素材 id；`match_all=True` 取交集（用分组计数实现：`count(tag_id) >= len(set(tag_ids))`），`False` 取并集 |

**用户端素材标签入口**（`api/app/http/knowledge_mcp_routes.py`，服务 `KnowledgeTagService`）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/space/knowledge-bases/<uuid>/documents/<uuid>/tags` | 列出该素材已打标签，返回 `[{"id", "name"}]` |
| POST | `/space/knowledge-bases/<uuid>/documents/<uuid>/tags` | 为素材打标签；body `{"tag_id"}`，缺失或非合法 UUID 返回 400 `validate_error`（不 500）；服务侧 `verify_document=True` 校验素材存在 |
| POST | `/space/knowledge-bases/<uuid>/documents/<uuid>/tags/<uuid>/delete` | 移除素材标签，返回「移除标签成功」 |

三条路由均先调用 `KnowledgeBaseService.get_accessible_base` 校验板块归属，避免越权读改他人素材标签；打标签的 `account_id` 取当前登录账号。

#### 11.7.5 素材多模态字段

`knowledge_document` 新增三个字段，为多模态素材与分级解析预留数据落点：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `partition_id` | UUID FK→`knowledge_partition.id` | 所属分区，可为空表示未归分区；分区删除时 `ondelete=SET NULL`（置空而非级联删素材） |
| `media_type` | VARCHAR(32) | 单个素材的媒体类型：document / image / video / audio，默认 document（枚举 `DocumentMediaType`） |
| `parse_profile` | JSONB | 解析档位与产物索引，默认 `{}`，形如 `{"tier1": {...}, "tier2": {...}, "frames": [...]}` |

同时 `upload_file.size` 由 `Integer` 升级为 `BigInteger`，支撑 GB 级视频素材（原 `Integer` 上限约 2.1GB，必然溢出）。

#### 11.7.6 存储配额与容量计量

知识库容量纳入统一存储配额管控，规则为：

```text
total_quota = max(基线 5GB, 生效套餐 storage_quota_gb) + sum(已购扩展包 GB)
used_bytes  = account_storage_usage.used_bytes   （上传/删除事件同步增减）
```

| 用户类型 | 存储配额 | 配置方式 |
| --- | --- | --- |
| 注册用户 | 5 GB | 系统默认基线（`DEFAULT_STORAGE_QUOTA_GB`） |
| 普通会员 | 100 GB | 套餐权益 `PlanEntitlement.feature_key='storage_quota_gb'` |
| 高级会员 | 500 GB | 同上 |
| 扩展包 | 累加 | `Plan.plan_type='storage_addon'` 套餐，叠加在套餐配额之上 |

- **配额承载**：走 `PlanEntitlement` 的 `feature_key='storage_quota_gb'` 自由键值（非给 `Plan` 加列），管理员在会员套餐板块新增该权益即生效，不改表结构、不改代码。常量与枚举定义在 `internal/entity/storage_quota_entity.py`。该 `feature_key` 属**套餐权益域**，与公共 AI 配置表的同名 `feature_key` 不是同一概念（详见 §24.8.5）。
- **扩展包**：`Plan.plan_type='storage_addon'`，复用既有 `PurchaseOrder` 与 `BalanceAccount` 扣款链路；已放行 `admin_billing_plan_schema` 与 `order_service` 的 plan_type 白名单，`_fulfill_rights` 对其不发放会员/算力权益（容量由已支付订单直接参与配额计算）。
- **计量**：新增 `account_storage_usage` 表（`account_id` 唯一，`used_bytes` 为 `BigInteger`）缓存已用字节，避免每次上传都全表 `sum(upload_file.size)`。
- **服务与收口**：`StorageQuotaService`（`internal/service/storage_quota_service.py`）提供 `resolve_total_quota_bytes` / `get_used_bytes` / `get_usage_summary` / `check_quota` / `add_usage` / `release_usage`；配额校验统一收口到 `RuntimeStorageProxy`——`upload_file` 与 `upload_bytes` 均在写入前 `check_quota`、成功后 `add_usage`，一处覆盖全部后端与全部调用方。超配额抛 `ForbiddenException`（`reason_code=storage_quota_exceeded`），引导购买扩展包。详细存储侧说明见 [06-file-storage.md §17.4](./06-file-storage.md#174-存储配额与用量计量p1-新增)。

#### 11.7.7 数据迁移

KB-KB-KB-P1 全部 DDL 由单个迁移 `p1a2b3c4d5e6_add_knowledge_product_form_base.py`（位于 `api/internal/migration/versions/`）承载，已在真实 DB 落库、迁移链保持单 head、`downgrade` 可逆：

- `knowledge_base` 增加 `base_type` / `partition_mode`（+ `base_type` 索引）
- `knowledge_document` 增加 `partition_id` / `media_type` / `parse_profile`（+ 两个索引）
- `upload_file.size` 由 integer 升级为 bigint
- 新建 `knowledge_partition` / `knowledge_base_tag` / `knowledge_document_tag` / `account_storage_usage`

### 11.8 多模态素材解析（KB-P2A 已落地）

KB-P2A 把 KB-P1 预留的 `media_type` / `parse_profile` 数据落点接上索引链路：图片、音频、视频素材上传后自动解析为可被语义检索命中的文本片段，实现"上传视频 → 能被语义检索命中"。实施计划见 [2026-09-14-knowledge-base-p2a-multimodal-ingest.md](../../superpowers/plans/2026-09-14-knowledge-base-p2a-multimodal-ingest.md)。

#### 11.8.1 KnowledgeMediaExtractorService（三分支）

`KnowledgeMediaExtractorService`（`internal/service/knowledge_media_extractor_service.py`）负责把非文档素材转为文本片段，`extract(document, upload_file, account_id=None, document_id=None)` 按 `document.media_type` 分派：

| 分支 | media_type | 处理链路 | 产物 |
| --- | --- | --- | --- |
| 图片 | `image` | 从对象存储下载 → `path_to_data_uri`（按扩展名推断 MIME，编码前上限 8MB）→ 视觉模型（画面描述 + OCR） | 1 个片段；摘要为空返回 `[]` |
| 音频 | `audio` | 下载 → 包装为 `FileStorage` → `AudioService.audio_to_text` ASR 全文转写 | 1 个片段；转写为空返回 `[]` |
| 视频 | `video` | 下载 → `probe_duration_sec` 探测时长 → `extract_video_frames_with_offsets`（L1 帧数随时长动态、全片均匀取帧，优先系统 ffmpeg，降级 imageio-ffmpeg）→ 逐帧 `path_to_data_uri` 视觉描述；同目录内 `extract_video_audio` 抽音轨 → ASR 转写 | 转写片段（1 个，非空时）+ 每帧 1 个片段；单帧失败跳过，全部失败抛错 |

`account_id` / `document_id` 仅供视频分支的关键帧留存使用（帧的归属账号与来源文档），缺省时视频照常解析但不留存帧（`frame_url` 为空字符串），保证既有调用方向后兼容。

文档类型（`document`）返回空列表，由既有文本链路（parsing → splitting → indexing）处理。

**音轨 ASR 属可降级能力**：视频可能无音轨、ASR 可能不可用，`_transcribe_video_track` 捕获全部异常后只记 warning 并返回空串，帧描述仍作为有效产物产出；音轨临时文件在 `finally` 中删除。

#### 11.8.2 视觉能力共享模块

视觉模型调用与视频抽帧从内置工具中抽取为共享包 `internal/core/vision/vision_invoke.py`，供「内置工具」与「知识库多模态解析」复用，避免两处重复维护：

| 函数 | 职责 |
| --- | --- |
| `path_to_data_uri(path)` | 本地图片 → data URI（按扩展名推断 MIME，8MB 上限） |
| `invoke_vision_model(data_uri, prompt)` | 经 `LanguageModelService.get_feature_model("vision_analyze")` 调用视觉模型 |
| `extract_video_frames(video_path, frame_count=3)` | 抽关键帧，返回 data URI 列表；产物随临时目录销毁；ffmpeg 不可用时降级 imageio-ffmpeg，均不可用抛错 |
| `extract_video_audio(video_path, target_path)` | 抽音轨为单声道 16k WAV（`-vn` / `-ac 1` / `-ar 16000`），返回 `target_path`；无可用 ffmpeg 或未产出文件抛 `RuntimeError` |
| `extract_video_frames_to_dir(video_path, out_dir, frame_count=3)` | 抽帧到指定目录，返回帧文件路径列表；不删目录、不转 data URI，生命周期由调用方负责。**注意：关键帧留存链路已改用 `extract_video_frames_with_offsets`（需时间偏移），本函数当前仅剩测试覆盖，无生产调用方** |
| `probe_duration_sec(video_path)` | 用同一 ffmpeg 可执行文件解析 `Duration:` 行返回秒数（不额外依赖 ffprobe）；无法探测返回 `0.0`，由调用方退回兜底策略 |
| `extract_video_frames_with_offsets(video_path, out_dir, frame_count=None)` | 按视频时长**全片**均匀抽帧，返回 `list[ExtractedFrame]`（`path` + `time_offset` 秒）。L1 关键帧链路的抽帧入口；时长为 0 时退回首帧兜底，仍保证有产物 |
| `extract_video_frames_in_range(video_path, out_dir, start_sec, duration_sec, frame_count=None)` | 只在 `[start_sec, start_sec+duration_sec)` 内密抽（L2 区间入口）：ffmpeg `-ss`/`-t` 限定解码范围 + `-vf fps=1/L2_INTERVAL_SEC`（0.5s/帧）控制密度 + `-frames:v` 封顶。偏移是**视频时间轴绝对位置**，与 L1 帧同一坐标系 |
| `plan_frame_offsets(duration_sec)` / `resolve_l1_frame_count(duration_sec)` | L1 抽帧策略纯函数（`internal/core/vision/frame_sampling.py`）：帧数 `clamp(round(8·log2(sec) − 35), 6, 60)`，**1 小时触顶 60 帧**，全片均匀取偏移 |
| `plan_l2_windows(hit_offsets, duration_sec, explicit_range=None)` / `merge_time_windows(windows)` / `resolve_l2_window_frame_count(duration_sec)` | L2 窗口推导纯函数（同模块）：命中帧 `time_offset` 各向两侧扩 `L2_WINDOW_PADDING_SEC`（10s）并合并重叠/相接窗口；显式区间优先；帧数 = 窗口秒数 × 2，上限 `L2_MAX_FRAMES_PER_WINDOW`（600 帧） |
| `_resolve_ffmpeg_exe()` | 解析可用 ffmpeg 可执行文件：优先系统 `ffmpeg`，其次 `imageio-ffmpeg` 自带静态二进制，均无则抛错 |

`providers/vision_tools/vision_analyze.py` / `video_analyze.py` 已改为复用该模块，对外行为不变（仍使用返回 data URI 的 `extract_video_frames`）。

#### 11.8.3 MediaSegment 产物结构

解析产物 `MediaSegment`（dataclass）直接映射 `KnowledgeSegment` 的 `content` 与 `metadata_`：

```python
@dataclass
class MediaSegment:
    content: str
    metadata: dict[str, Any]
```

| media_type | content | metadata 字段 |
| --- | --- | --- |
| `image` | 视觉摘要（含 OCR） | `media_type`、`vision_summary` |
| `audio` | ASR 转写全文 | `media_type` |
| `video`（音轨转写） | 视频音轨 ASR 转写全文 | `media_type`、`source="audio_transcript"` |
| `video`（关键帧） | 单帧视觉描述（含 OCR） | `media_type`、`scene_index`（帧序号，从 1 起）、`frame_count`（总帧数）、`frame_url`（留存帧的对象 key，未留存/留存失败为空字符串）、`time_offset`（该帧在视频中的时间偏移秒数，L2 区间定位与「改细节」的唯一依据） |

转写片段排在帧片段之前（「讲什么」的检索价值高于「画面是什么」）。

#### 11.8.3.1 关键帧留存为 UploadFile

视频关键帧解析后立即留存，避免后续视觉向量能力上线时重跑整个视频解析：

| 环节 | 行为 |
| --- | --- |
| `_persist_frame(frame_path, *, account_id, document_id)` | 读帧字节 → `cos_service.upload_bytes(filename, content, account_id, mime_type="image/jpeg")`，**直接返回该调用产出的记录**（记录与 `extension="jpg"` / `hash=sha3_256` 等字段均由存储后端在 `upload_bytes` 内建好）。**不得**再调 `create_upload_file`——那会对同一对象 key 建出第二条记录（详见 §11.10.5「记录唯一性」） |
| 降级策略 | `_persist_frame` 抛异常只记 warning 并把 `frame_url` 置空，帧描述片段照常产出——留存是增强能力，不得让整个视频解析失败 |
| 依赖 | 服务保留 dataclass 字段 `upload_file_service: UploadFileService`（具体类型标注，injector 按类型解析）；帧记录实际由存储后端创建 |

> 帧留存本身不写视觉向量；视觉向量的编码与索引由索引链路在写完文本片段向量后单独执行（`_index_visual_vectors`，KB-P3 已落地，见 §11.10.3）。

#### 11.8.4 索引链路按 media_type 分支

`KnowledgeIndexingService.build_document()` 在置 `parsing` 后按 `media_type` 走两条路径：

```text
build_document(document_id)
  ├─ media_type == document（默认）
  │    parsing → splitting → indexing → completed
  │    （文本抽取 → 递归切分 → 向量化 → 收尾）
  └─ media_type in {image, audio, video}
       _build_media_document：解析产物即片段，跳过文本切分
         → 清理该文档旧片段（含向量，保证重解析幂等）
         → 逐条建 KnowledgeSegment（keywords/character_count/token_count，status=indexing, enabled=false）
         → knowledge_vector_service.index_segment 向量化
         → _index_visual_vectors：为带 frame_url 的视频帧建视觉向量（先清空旧向量）
         → _finalize_segments：片段置 completed + enabled，文档置 completed
           parse_profile={"tier1": {...}, "frames": [...]}
```

公共能力经抽取复用：`_get_upload_file`（取关联上传文件，缺失抛 `NotFoundException`）、`_finalize_segments`（统一收尾，`document` 路径不写 `parse_profile`）。多媒体路径解析无产出时抛错，由 `build_document` 统一置 `error`。

#### 11.8.5 上传媒体类型识别与板块类型硬约束

`KnowledgeBaseService.upload_document` 增加两步：

| 步骤 | 行为 |
| --- | --- |
| 媒体类型识别 | `media_type_for_extension(upload_file.extension)` 反查，写入 `knowledge_document.media_type`（未知扩展名归入 `document`） |
| 板块类型校验 | `_assert_media_type_allowed(knowledge_base, incoming_extension)`：按 `base_type` 取 `allowed_extensions_for_base_type(base_type)` 校验，不符抛 `ValidateErrorException`，错误信息含该板块允许的扩展名列表 |

**校验先于落盘**：`_assert_media_type_allowed` 在 `cos_service.upload_file` **之前**调用，被拒绝的文件不写入存储、不占用用户配额。板块 `base_type` 为空时视为 `mixed`（兼容存量库），扩展名为空时不拦截。

#### 11.8.6 存储层白名单的分层设计

存储层只校验"是否允许的媒体类型"，板块级细粒度约束由知识库服务负责：

| 层级 | 校验者 | 白名单来源 | 约束范围 |
| --- | --- | --- | --- |
| 存储层 | `LocalStorageService` / `CosService` / `AliyunOSSService` | `allowed_extensions_for_base_type("mixed")`（图片 + 文档 + 视频 + 音频全类型并集） | 是否为系统允许上传的媒体类型（放行 video/audio） |
| 板块层 | `KnowledgeBaseService._assert_media_type_allowed` | `allowed_extensions_for_base_type(knowledge_base.base_type)` | 该板块允许的具体媒体类型 |

存储层不感知知识库板块语义；`only_image=True` 的调用仍额外要求命中 `ALLOWED_IMAGE_EXTENSION`。分层说明详见 [06-file-storage.md §17.11](./06-file-storage.md#1711-安全要求)。

#### 11.8.7 解析档位与 L2 状态

多媒体路径收尾写入 `parse_profile.tier1`（L1 基础解析状态）：

```json
{"tier1": {"status": "completed", "media_type": "video", "segment_count": 3, "video_frame_count": 3}, "frames": [{"segment_id": "...", "frame_url": "...", "scene_index": 1}]}
```

（`video_frame_count` 与 `frames` 为 KB-P3 新增：由 `_count_frames` / `_collect_frames` 汇总，供「改细节」定位与视觉向量后补。每个 frame 条目含 `segment_id` / `frame_url` / `scene_index` / `time_offset`（`_segment_frame` 输出，时间偏移是该帧在视频中的坐标——缺它则帧清单只能排序、无法换算时间轴位置，L2 区间密抽与「改细节」都无从定位）。）

| 档位 | 状态 | 内容 |
| --- | --- | --- |
| L1 基础解析 | ✅ 已落地（KB-P2A 建链路；视频音轨 ASR 与关键帧留存为 KB-P3 补强，见 §11.8） | 图片视觉摘要 + OCR、音频 ASR 转写、视频「音轨 ASR 转写 + 关键帧视觉描述」，关键帧留存为 UploadFile → 片段 + 向量 |
| L2 深度解析 | ✅ 已落地（KB-P3，见 §11.11） | 视频**区间窗口密抽**：由 L1 命中帧的 `time_offset` 扩窗（±10s，可给显式区间），窗口内按 0.5s/帧密抽并新建 Segment 逐帧详述；说话人切分、细粒度 OCR 坐标、场景切分仍未实现 |

L2 为**按需触发**（Celery 任务 `internal.task.knowledge_l2_tasks.build_document_l2_task`，**不加 beat 条目**），状态写入 `parse_profile.tier2`。检索取料的过滤能力（分区 / 媒体类型 / 标签 / 相似度阈值）与关键帧视觉向量索引均已在 KB-P3 落地，见 §11.9 / §11.10。

---

### 11.9 检索过滤参数（KB-P3 已落地）

KB-P3 为检索链路补上四类结构化过滤，使「自翻素材」可按分区、媒体类型、标签与相似度下限收窄范围。

#### 11.9.1 向量检索的 SQL 下推

`KnowledgeVectorService.search()`（`internal/service/knowledge_vector_service.py`）新增 4 个过滤参数，**全部在 SQL 侧过滤**（而非取回后在 Python 里再筛——否则 `LIMIT` 会先把不匹配的行取走，导致召回数量不足）：

| 参数 | SQL 条件 |
| --- | --- |
| `partition_id` | `AND kd.partition_id = :partition_id` |
| `media_types` | `AND kd.media_type = ANY(:media_types)` |
| `document_ids` | `AND kd.id = ANY(:document_ids)` |
| `score_threshold` | `AND 1 - (v.embedding <=> CAST(:embedding AS vector)) >= :score_threshold` |

- 分区 / 媒体类型通过 `JOIN knowledge_document`（别名 `kd`）在向量 SQL 内命中 **HNSW 索引**，**不额外回查素材表**。
- 用 `= ANY(:media_types)` 而非 `IN :list`：`text()` 的 `IN` 绑定需 `bindparam(expanding=True)` 才可靠展开，`ANY` + 数组更稳且 PostgreSQL 原生支持。

#### 11.9.2 RetrievalFilter 与 fail closed 语义

`retrieval_service.py` 新增 dataclass `RetrievalFilter`（`partition_id` / `media_types` / `tag_ids` / `match_all_tags` / `score_threshold`），`search_in_knowledge_base()` 增加 `retrieval_filter` 参数。三个解析方法：

| 方法 | 职责 |
| --- | --- |
| `_resolve_tag_document_ids(retrieval_filter)` | 标签 → 素材 id；`None` 表示未使用标签过滤，`[]` 表示无命中 |
| `_resolve_structural_document_ids(retrieval_filter)` | 分区 / 媒体类型 → 素材 id（供全文分支使用） |
| `_restricted_document_ids_for_full_text(retrieval_filter, tag_document_ids)` | 全文分支的「标签 ∩ 结构化」受限素材范围 |

> **关键语义：标签无命中必须 fail closed（返回空结果），绝不能退化成"不过滤"**。用户以为已按标签收窄范围，实际却召回全库，是最危险的静默失效模式。实现上必须用 `is None` 而非真假值判断 `tag_ids`——空列表 `[]` 表示「有标签过滤但一个都没匹配上」，属 fail closed 情形；写成 `if not tag_ids` 会让空列表退化成"无标签过滤"。同理，`tag_document_ids == []` 与 `restricted_document_ids == []` 时 `search_in_knowledge_base` 直接 `return []`。

**两个分支的过滤方式不同**：

| 分支 | 过滤方式 |
| --- | --- |
| 向量 / 混合检索的向量部分 | 分区与媒体类型**直接下推 SQL**（命中 HNSW 索引，不额外查素材表）；标签解析出的素材 id 也一并下推 `document_ids` |
| 全文检索（作用于 `knowledge_segment`） | 必须**先把分区 / 媒体类型解析为素材 id** 再限定范围，且与标签取**交集**（`_restricted_document_ids_for_full_text`） |

`score_threshold` 在向量分支由 SQL 侧过滤；`_apply_score_threshold` 作为全文 / 混合分支的兜底（全文分支无分数语义，不施加阈值，避免把结果全滤掉）。

#### 11.9.3 检索工具的四个可选入参

`create_knowledge_retrieval_tool` 构造的 `search_knowledge_base` 工具入参新增 4 个可选字段（`_build_retrieval_filter` 负责组装）：

| 入参 | 类型 | 说明 |
| --- | --- | --- |
| `partition_id` | `str \| None` | 限定在某分区内检索，传分区 ID（非法 UUID 记 warning 并忽略该过滤） |
| `media_types` | `list[str] \| None` | 限定素材类型，取值 `image` / `video` / `audio` / `document` |
| `tags` | `list[str] \| None` | 按标签名过滤，多个标签取**并集**（经 `resolve_tag_ids_by_names` 解析为 tag_id） |
| `score_threshold` | `float \| None` | 相似度下限（0~1），低于该值不返回 |

四个入参全为空时 `_build_retrieval_filter` 返回 `None`（不过滤）；有标签名但解析不到任何标签时返回空 `tag_ids` 的 filter，由检索层 fail closed 处理。

---

### 11.10 关键帧视觉向量（KB-P3 已落地）

#### 11.10.1 数据表 `video_visual_embedding`

新增模型 `VideoVisualEmbedding`（`internal/model/video_visual_embedding.py`）：

| 列 | 说明 |
| --- | --- |
| `account_id` | 归属账号 |
| `knowledge_base_id` / `knowledge_document_id` / `segment_id` | 三个外键均 `ondelete=CASCADE`（板块 / 素材 / 片段删除时向量自动清理）；`segment_id` 上有唯一约束 `uq_video_visual_embedding_segment` |
| `frame_url` | 帧文件在对象存储中的 key（对应 `UploadFile.key`），供「改细节」定位画面 |
| `scene_index` | 帧在该视频中的序号（从 1 起），与 `Segment.metadata.scene_index` 对齐 |
| `model_id` | 生成该向量的模型 id（便于换模型后重建） |
| `embedding` | `Vector(1536)` |

三个普通索引（`knowledge_base_id` / `knowledge_document_id` / `account_id`）+ HNSW 余弦索引（`vector_cosine_ops`）。

**为什么维度是 1536**：选型模型 `Qwen/Qwen3-VL-Embedding-8B` 原生 4096 维，**超出 pgvector `vector` 类型上限 2000**，需经 MRL 降维到 1536（常量 `VISUAL_EMBEDDING_DIMENSION = 1536`）。

#### 11.10.2 VisualEmbeddingService

`VisualEmbeddingService`（`internal/service/visual_embedding_service.py`）独立于 `EmbeddingsService`：

| 方法 | 入参格式 | 说明 |
| --- | --- | --- |
| `embed_text(content)` | 裸字符串 | 文本编码（与图片共享语义空间，可直接跨模态比对） |
| `embed_image(data_uri)` | `{"image": ...}` | 图片编码 |
| `embed_mixed(text_content, data_uri)` | `[{"text": ...}, {"image": ...}]` | 图文混合编码（融合为一个向量） |
| `has_vectors(knowledge_base_ids)` | — | **预检这些库内是否有帧向量**，供检索链路决定是否值得发起编码调用（视觉编码按次计费） |
| `search_by_image(*, image_uri, knowledge_base_id, limit, document_ids, partition_id, media_types)` | — | 以图搜图；结构化过滤在 SQL 侧下推 |
| `search_by_text(*, query, knowledge_base_id, limit, document_ids, partition_id, media_types)` | — | 跨模态文本召图；与文本检索共用同一套过滤语义 |
| `index_frame(*, knowledge_base_id, knowledge_document_id, segment_id, account_id, frame_url, scene_index, embedding, model_id)` | — | 写入 / 覆盖一条帧向量（以 `segment_id` 为冲突键 upsert） |
| `delete_by_document(knowledge_document_id)` | — | 清空某素材的全部视觉向量 |

**为什么不注册进 `model_class_registry`**：Qwen3-VL-Embedding 的 REST 入参与 `OpenAIEmbeddings` **不兼容**（后者只能表达纯文本），若注册进 langchain 的 `model_class_registry`，会**静默只编码文本**——「以图搜图」拿到的其实是文本向量。因此改为独立 HTTP 调用。

**同一语义空间，可直接文本召图（无需融合排序）**：Qwen3-VL-Embedding 把文本、图片、视频映射到同一语义空间，文本 query 可直接与库内图片向量比对余弦相似度，`search_by_text` / `search_by_image` 共用同一套排序逻辑（`_rank`）。这是对设计稿最初「两个独立空间 + 融合排序」假设的实测修正：视觉向量是**并行的补充召回通道**，与文本向量召回结果由上层合并。

**编码失败一律返回空列表**（维度不符 / 请求失败），不写入错误向量破坏索引一致性；调用方据此跳过该帧。

#### 11.10.3 索引链路的视觉向量写入

`KnowledgeIndexingService._index_visual_vectors(document, segments)` 在写完文本片段向量后，为带 `frame_url` 的视频帧片段建立视觉向量：

- **幂等语义**：先 `delete_by_document(document.id)` 清空该素材旧视觉向量再重建——素材是「每次完整重新生成」的产物，与文本片段保持同一幂等语义。
- 逐帧下载帧文件 → `path_to_data_uri` → `service.embed_image(data_uri)` → `service.index_frame(...)`；单帧失败只记 warning 并跳过。
- 相关辅助：`_segment_frame(segment)`（取出片段帧信息，非视频帧片段返回 `None`）、`_collect_frames(segments)`（帧清单）、`_count_frames(segments)`。
- `_build_media_document` 现在把 `account_id` / `document_id` 传给媒体提取器——**不传则帧不留存、`frame_url` 恒空，视觉链路静默失效**；并把 `parse_profile.frames` 与 `tier1.video_frame_count` 写入档案。

**模型池登记**：模型池新增模型类型 `visual_embedding`（`ModelType.VISUAL_EMBEDDING`），共 9 处登记点同步（枚举、两份后端 `MODEL_TYPES` 副本、`CONTEXT_LESS_MODEL_TYPES`、维度探测分支、前端 `ModelsView.vue` / `ModelProvidersView.vue`、i18n 双端）。新增防漂移测试 `api/test/internal/schema/test_model_type_parity.py`（此前这两份后端副本 + 两份前端副本 + `CONTEXT_LESS_MODEL_TYPES` 两份均无一致性测试）。

**迁移**：
- `c9d0e1f2a3b4_add_video_visual_embedding.py`（`down_revision = q2b3c4d5e6f7`）：建表 + 三个外键 + 三个索引 + HNSW 余弦索引。
- `dae1f2a3b4c5_seed_siliconflow_vl_embedding.py`：幂等 seed `SiliconFlow` provider 与 `Qwen/Qwen3-VL-Embedding-8B` 模型（`model_type='visual_embedding'`、`embedding_dimension=1536`）；**不写密钥**，密钥由管理员在 admin 端配置。

#### 11.10.4 视觉向量读取侧接入（自动补充召回）

`RetrievalService._visual_recall_knowledge_base` 把 `VideoVisualEmbedding` 的**读取侧**接进检索主链路——此前只写不读（表有数据、服务有方法，但检索零调用点），导致「以图搜图 / 文本跨模态召回画面」在运行时不可达。

| 项 | 语义 |
| --- | --- |
| 触发时机 | 仅 `semantic` / `hybrid` 策略；`full_text` 是关键词路径，不引入编码调用 |
| 召回方式 | 文本 query 直接与库内帧向量比对余弦相似度（同一语义空间），作为**并行的补充召回通道** |
| 合并去重 | `_merge_visual_documents` 按 `segment_id` 去重，已有文本命中优先保留（帧片段的视觉描述文本可能已被文本分支命中）；合并后总数仍受 `k` 约束 |
| 阈值语义 | `score_threshold` 在**合并之后**统一施加——视觉命中同样是带真实分数的语义结果，若只滤文本分支，低分帧会绕过用户设定的下限 |
| 过滤同源 | 标签收敛出的 `document_ids`、分区、媒体类型**全部下推**到视觉 SQL；视觉召回不得绕过任一过滤 |
| fail closed | `media_types` 明确不含 `video` 时不召回（帧向量必不在范围内）；标签无命中时同样不召回 |
| 成本护栏 | `has_vectors()` 预检：库内没有帧向量则**不发编码调用**（视觉编码按次计费，白跑纯浪费） |
| 降级 | 视觉是补充通道：未注入服务或任何异常都只记日志并返回空，**不影响**主检索结果 |
| 元数据透传 | `layered_search` 额外透传 `frame_url` / `scene_index`，供上游展示缩略图与定位画面（设计稿 §4.1「带缩略图 / 时间戳」）；只透传 `retrieval`/`source` 会让视觉结果退化成无图文本 |

测试：`api/test/internal/service/test_visual_recall_retrieval.py`（含方法级护栏测试——公开路径的「标签无命中 → 空」由上游早返回兜住，若不单独锁护栏，把它误写成 `if not document_ids` 也不会有测试失败，那正是最危险的 fail-open）。

#### 11.10.5 帧留存计入用户存储配额

关键帧是**持久化产物**（落对象存储 + 落 `upload_file` 记录），按「堆积即计费」判据**计入** §11.7.6 的存储配额。

- **计费发生在存储代理层，不在帧代码里**：`_persist_frame` 调 `cos_service.upload_bytes(...)`，而 `ObjectStoragePort` 在 DI 中被绑定到 `RuntimeStorageProxy`（`api/app/http/module.py`），该代理的 `upload_bytes` 内部已执行 `check_quota` + `add_usage`。这是一条**跨模块隐式契约**，由 `api/test/internal/service/test_frame_quota_charge.py` 显式锁定，避免被静默移除后帧变成免费存储。
- **释放**：`purge_knowledge_document`（单文档）与 `purge_knowledge_base`（整库）除主文件外**一并清理帧文件并 `release_usage`**。其快照分别由 `snapshot_knowledge_document`（`frames`）与 `snapshot_knowledge_base`（文档级 `_frames`）采集（按 segment 的 `frame_url` 反查 `UploadFile` 记录）。二者必须成对——只计费不释放会让用户删除素材后帧仍占额（配额泄漏）。
- **准入预留**：素材上传（分片 `complete` / `instant_upload` / `upload_file` 直传）的校验量为「素材大小 + `PARSE_RESERVE_BYTES`（8MB）」，把解析将产生的帧占用一并纳入门槛；该预留**只是门槛、不计入已用**（`consume_quota(reserve_bytes=...)`）。**产物写入路径 `upload_bytes` 不加预留**（帧/Agent 产物逐次写入，加预留会反复卡门槛）。
- **记录唯一性**：帧的 `UploadFile` 记录由 `upload_bytes` 内部创建，`_persist_frame` **直接复用其返回值**，不得再调 `create_upload_file`——同一对象 key 出现两条记录会让 purge 对同一份字节 `release_usage` 两次（配额多还）。purge 侧的 `_purge_storage_targets` 另按 key 去重，作为存量数据与未来回归的防御。
- **purge 顺序（重试安全）**：多目标销毁必须**先删完全部对象、再统一释放配额**，且整库路径先汇总全部文档的目标后一次性处理。若「边删边释放」，删到一半失败时前面的配额已释放，`purge_expired` 保持 pending 重试会把同一份字节再释放一次（配额多还）。
- **记录生命周期**：`physical_delete_knowledge_document` / `physical_delete_knowledge_base` 在物理删除时**一并删除帧 `UploadFile` 记录**（否则帧记录无任何入口再引用，成为永久孤儿）；恢复侧 `restore_*` 必须**成对重建**帧记录，否则恢复后再删除会采不到帧记录（欠释放）。
- **重解析清理**：`_release_stale_frames` 在 `_build_media_document` 清理旧片段**之前**删除上一轮的帧对象、`UploadFile` 记录并 `release_usage`。可达入口为「编辑文档重建索引」（`update_text_document_for_admin` 复用同一 document id）与 Celery `build_document_task`（`max_retries=2`）；不清理则每轮都留下永不释放的孤儿帧（持续配额泄漏）。清理失败只记 warning 不中断本轮解析。

---

### 11.11 L2 按需解析（KB-P3 已落地）

L2 让素材「能被精细修改」，与 L1「能被找到」互补。

#### 11.11.1 任务与触发方式

| 项 | 值 |
| --- | --- |
| 任务名 | `internal.task.knowledge_l2_tasks.build_document_l2_task` |
| 任务配置 | `bind=True`、`max_retries=2`、`default_retry_delay=60` |
| 注册 | 已登记在 `api/app/http/celery_app.py` 的 `TASK_MODULES` 并加显式 import |
| beat 条目 | **不加**——L2 是**按需触发**（检索命中 / 用户显式要求），不做定时轮询（长视频视觉详述最贵） |
| 服务调用 | 任务内经 `injector` 取服务调用 `KnowledgeIndexingService.build_document_l2` |
| **触发入口** | 路由 `POST /space/knowledge-bases/<kb_id>/documents/<document_id>/l2` → `KnowledgeBaseService.trigger_document_l2`（先校验知识库与文档归属，再 `_dispatch_document_l2`：Celery 优先、失败回退同步，避免请求静默丢失）。请求体可选 `start_sec` / `end_sec`，均给出时按显式区间密抽，否则由 L1 命中帧自动推导窗口 |

#### 11.11.2 区间窗口密抽（规格 §5.4）

`KnowledgeIndexingService.build_document_l2(document_id, start_sec=None, end_sec=None)`：

- **窗口推导**：`plan_l2_windows(hit_offsets, duration_sec, explicit_range)`（纯函数，`frame_sampling.py`）。命中帧的 `time_offset` 各向两侧扩 `L2_WINDOW_PADDING_SEC`（10s），重叠/相接窗口合并；`start_sec` + `end_sec` 均给出时按其显式区间。窗口裁剪到 `[0, duration]`。窗口**只由 L1 片段推导**——L2 自己产生的窗口帧若参与推导，会形成「上一轮窗口 → 下一轮更大窗口」的自我放大。
- **窗口内密抽**：`extract_video_frames_in_range`（`vision_invoke.py`）用 ffmpeg `-ss`/`-t` 限定解码范围 + `-vf fps=1/0.5` 控制密度 + `-frames:v` 封顶。帧数 = `resolve_l2_window_frame_count(duration)` = 窗口秒数 × 2（`L2_INTERVAL_SEC = 0.5`），上限 `L2_MAX_FRAMES_PER_WINDOW`（600 帧 = 5 分钟）。帧的 `time_offset` 是**视频时间轴绝对位置**，与 L1 帧同一坐标系。
- **回写语义**：窗口内帧**新建 Segment**（`metadata.tier2_window=True` + `tier2_window_start` / `tier2_window_duration` / `time_offset`），与 L1 全片粗抽帧区分；不再改写 L1 片段 `content`。新建 Segment 同时写入文本向量（`index_segment`）与视觉向量（`_index_visual_vectors`），否则密抽产物不可检索。
- **重复触发先清旧**：`_clear_previous_l2_windows` 清掉上一轮的窗口片段与帧，避免累积重复片段。
- **无命中即不抽**：没有 L1 命中帧且未给显式区间时，窗口列表为空 → 不抽任何帧（L2 是「放大镜」不是「重扫全片」）。
- **成本**：1 小时视频改 20 秒片段，视觉调用从 7,200 次降到约 40 次。
- **配额**：窗口帧是新的持久化产物，经存储代理计入配额（同 L1 帧口径）；重解析会由 `_release_stale_frames` 清理上一轮帧。
- 状态写入 `parse_profile.tier2`（`running` → `completed` / `error`），返回 `{"document_id": ..., "tier2": {...}}`；**失败只标记 error，不回滚 L1 产物**——L1 的「能被找到」能力必须保留。
- `_invoke_l2_vision(data_uri)` 为可替换方法（独立出来便于测试替换），内部调用 `invoke_vision_model` 与 L2 提示词 `_L2_FRAME_PROMPT`。
- 当前仅处理**视频**（`media_type == video`）；图片的细粒度 OCR 坐标、音频的说话人切分等 L2 增强仍未实现；**场景切分（按画面切换选帧）仍为后续增量**——当前按时间窗口密抽，非按场景。

---

### 11.12 迁移链守卫测试（KB-P3 已落地）

`api/test/internal/migration/test_migration_graph_integrity.py` 以 **git 跟踪的文件**（而非磁盘上的全部文件）重建迁移图，断言：

1. 无悬空 `down_revision`（每个 `down_revision` 都能在 git 跟踪的迁移文件中找到定义方）；
2. 迁移图只有一个 head。

背景：历史上曾出现 `down_revision` 指向**未被 git 跟踪**的迁移（`o9d0e1f2a3b4`），开发机因该文件恰好存在而不报错，但全新 clone / CI 上 `alembic upgrade head` 会因 "Revision ... is not present" 直接崩溃。

---

### 11.13 系统预置成品库（KB-P3.7 已落地）

渲染成品需要一个**确定的、唯一的、系统托管的**归集处，故不新增 `base_type`，
而是每用户预置一个成品库（设计 §4.1）。

| 项 | 值 |
| --- | --- |
| 标识 | `knowledge_base.created_from = 'render_output'`（`KnowledgeCreatedFrom.RENDER_OUTPUT`） |
| 名称 | `成品库`（常量 `RENDER_OUTPUT_BASE_NAME`） |
| 归属 | 用户私有（`knowledge_scope=user_content`、`owner_account_id=账号`），每账号**至多一个** |
| 唯一性 | PostgreSQL **部分唯一索引** `knowledge_base_render_output_uniq`（`WHERE created_from='render_output'`）；不能用全表唯一约束——`manual_upload` 等同账号下允许多个 |
| 创建时机 | 首次写成品时 `get_or_create_render_output_base` 幂等创建（不给从未出片的用户平白建库）；并发冲突靠唯一索引兜底后重查 |
| 禁止手动上传 | `upload_document` / `create_document_from_upload_file` / `assert_upload_allowed` 三处均经 `_assert_not_render_output_base` 拒绝 |
| 系统写入 | `KnowledgeBaseService.store_render_output()` —— 落 COS → 建成品库 `KnowledgeDocument`（`source_type='render_output'`、`media_type=video`）→ 触发索引。**该路径不经「禁止上传」校验**（那条只拦用户上传） |

成品库走**同一套 KB-P3 检索**（分区/媒体类型/标签/相似度阈值），因此「可复用」天然成立——
用户可让小钰从成品库翻旧片翻新。

### 11.14 HyperFrames 渲染宿主（KB-P3.7 已落地）

三层编/渲/库流水线，全部由对话内工具触发：

| 层 | 文件 | 职责 |
| --- | --- | --- |
| 编 | `internal/core/video/composition_builder.py`（`build_composition_html`） | 纯函数：结构化 spec → HyperFrames HTML；文本一律 HTML 转义，输出满足 `data-composition-id` / `class="clip"` / `window.__timelines` 契约 |
| 渲 | `internal/core/video/hyperframes_renderer.py`（`render_composition` / `verify_artifact` / `build_render_env` / `build_render_command`） | 写工程目录 → subprocess 调 `npx hyperframes@<钉死版本> render` → ffprobe 校验产物。判定为「退出码 0 **且** 产物非空 **且** ffprobe 读出正时长」三者同时满足 |
| 库 | `KnowledgeBaseService.get_or_create_render_output_base` + `store_render_output` | MP4 落 COS → 成品库建档 → 索引 |

编排与触发：

| 项 | 位置 |
| --- | --- |
| 编排服务 | `internal/service/render_service.py`（`RenderService.render_composition` / `render_to_render_output_base`） |
| Celery 队列与任务 | `config/config.py`（`Queue("render")` + `internal.task.render_tasks.*` 路由）+ `internal/task/render_tasks.py`（`render_composition_task`，`bind=True` / `max_retries=2` / `default_retry_delay=60`） |
| 会话内入口 | builtin provider `video_render_tools`（`render_video`）+ 运行时挂载点 [assistant_agent_service.py](../../../api/internal/service/assistant_agent_service.py) 的 `_build_assistant_runtime_tools`；工具 `_dispatch_render` 做**三级路由**（见下） |
| 配额宽让 | `StorageQuotaService.check_quota_allow_overflow` + `RuntimeStorageProxy.upload_bytes(allow_overflow=True)`：成品由系统写入，剩余 > 0 即放行（允许溢出），恰好为 0 才拒绝（设计 §6.3）；**素材上传仍严格** |
| 渲染运行时配置 | `HYPERFRAMES_BROWSER_PATH` / `HYPERFRAMES_FFMPEG_PATH` / `HYPERFRAMES_FFPROBE_PATH` / `HYPERFRAMES_CLI_VERSION`（默认 `0.8.42`）/ `HYPERFRAMES_CLI_BIN` / `RENDER_TIMEOUT_SEC` |
| 执行位置开关 | `RENDER_LOCAL_ENABLED`（默认 `true`）/ `RENDER_CLOUD_FALLBACK_ENABLED`（默认 `true`）；读取点 `render_video._local_enabled` / `_cloud_fallback_enabled`（容器 config 是普通 dict，须 `.get()`） |

**渲染执行位置 = 三级路由**（`render_video._dispatch_render`）：

| 优先级 | 位置 | 触发/回退条件 |
| --- | --- | --- |
| 1 | **用户本机**（桌面端 render worker） | `RENDER_LOCAL_ENABLED=true` 时优先；经 `resolve_desktop_bridge(account_id, purpose="/render")` 下发，产物经 bridge `/artifact` 取回后复用 `store_render_output` 入库 |
| 2 | **云端 Celery `render` 队列** | 仅当本机**通道不可用**（无在线设备 / 连不上 bridge / HTTP 401·502·503·504）且 `RENDER_CLOUD_FALLBACK_ENABLED=true` |
| 3 | 明确报错 | 两者均不可用 |

> **「通道不可用」与「渲染业务失败」语义必须区分**：前者才回退云端；后者（环境缺二进制、脚本非法等）
> 直接抛 `RenderExecutionError` 报错，**不静默回退**。
>
> 渲染硬依赖三个外部二进制（浏览器 / ffmpeg / ffprobe），缺任一渲染在启动阶段即失败。
> 浏览器须是能响应 `--version` 的 Chrome 构建（chrome-headless-shell 实测正常）；
> ffprobe 必须是**真 ffprobe**（用 ffmpeg 冒充会因 `-print_format` 不支持而失败）。
>
> **云端渲染编排已落地、默认关闭**：`api/Dockerfile.render` + compose 的 `llmops-render-worker`
> 已加 `profiles: ["cloud-render"]`，默认不启动；需云端回退时
> `docker compose --profile cloud-render up -d llmops-render-worker` 一键接通。
> 详见 [deployment-single-node.md](../../deployment-single-node.md) 的「渲染执行位置」与
> [09-desktop-client.md](09-desktop-client.md) 的 render worker 小节。
