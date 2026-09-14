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

当前系统中，管理员也是用户：管理员账号会绑定一个普通 `Account`，管理员登录后既有管理员身份，也会获得用户端身份。因此知识库归属不能只按“创建人是不是管理员”判断，而必须按“操作上下文 + 知识库作用域”判断。

核心原则：

```text
同一个自然人
  -> 以普通用户上下文操作：写入用户个人知识库
  -> 以管理员配置中心上下文操作，并显式选择系统级作用域：写入系统级知识库
```

也就是说，管理员的知识库不天然等于系统级知识库。管理员也可以有自己的用户长期记忆库和用户资料内容库；只有当管理员在配置中心以管理行为创建、维护、发布的知识，才属于系统级知识库。

判定矩阵：

| 操作人 | 操作入口 | 操作上下文 | knowledge_scope | 归属 |
| --- | --- | --- | --- | --- |
| 普通用户 | /home 或用户知识库页面 | user | user_memory | 用户长期记忆库 |
| 普通用户 | /home 或用户知识库页面 | user | user_content | 用户资料内容库 |
| 管理员 | /home 普通问答 | user | user_memory | 管理员自己的长期记忆库 |
| 管理员 | /home 普通问答 | user | user_content | 管理员自己的资料内容库 |
| 管理员 | 配置中心 / 系统知识库管理 | admin | system | 系统级知识库 |
| 管理员 | 配置中心 / 租户知识库管理 | admin | tenant | 租户级知识库 |
| 管理员 | 配置中心 / 项目知识库管理 | admin | project | 项目级知识库 |

因此需要在知识库数据模型中增加或明确以下字段：

| 字段 | 说明 |
| --- | --- |
| owner_account_id | 资源实际归属的用户账号，兼容现有 account_id |
| owner_admin_user_id | 如果由管理员在管理上下文创建，记录管理员身份 |
| operation_context | user / admin / system_job，表示创建或修改时的操作上下文 |
| knowledge_scope | system / tenant / project / user_memory / user_content |
| visibility_scope | private / team / tenant / public / internal |
| target_tenant_id | 租户级知识库归属 |
| target_project_id | 项目级知识库归属 |
| created_from | manual_upload / conversation_memory / admin_config / workflow_import / external_sync |

边界规则：

1. 管理员在 `/home` 的普通提问和回答中产生的长期记忆，默认进入管理员自己的用户长期记忆库。
2. 管理员在用户资料页面上传的文档、图片、视频、音频，默认进入管理员自己的用户资料内容库。
3. 管理员在配置中心创建的知识库，只有显式选择 `system`、`tenant` 或 `project` 作用域时，才进入对应管理级知识库。
4. 系统级知识库必须要求管理员权限，并记录 `owner_admin_user_id`、操作日志和发布状态。
5. 系统级知识库的内容可以被普通用户任务检索引用，但普通用户不能直接写入或管理。
6. 用户个人知识库默认只服务该用户本人，不能因为用户拥有管理员身份而自动变成系统知识。
7. 当同一条知识既可能是个人偏好又可能是系统规范时，必须让管理员明确选择保存到“个人长期记忆”还是“系统级知识库”。

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
- 图片：jpg、jpeg、png、webp、gif、svg 等，L1 视觉理解已落地，L2 深度解析后置。
- 视频：产品演示、会议录像、课程视频等，L1 关键帧视觉描述已落地，L2 深度解析后置。
- 音频：会议录音、访谈、播客、语音备忘等，L1 ASR 转写已落地，L2 深度解析后置。

资料内容库需要支持：

| 能力 | 说明 |
| --- | --- |
| 上传 | 用户主动上传文件 |
| 外部数据源连接 | 用户授权连接飞书、Notion、本地文件夹、GitHub 等外部数据源 |
| 同步 | 支持手动同步与 Celery 定时自动同步（每 6 小时扫描已授权数据源） |
| 解析 | 文本与结构化资料走 parsing→splitting→indexing；图片/音频/视频走 L1 多模态解析直达入库（见 §11.8），L2 深度解析后置 |
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
| 知识库管理 | `Dataset` 模型、创建、更新、删除、分页、搜索 |
| 文档管理 | `Document` 模型、上传后创建文档、启用 / 禁用、删除、重命名 |
| 片段管理 | `Segment` 模型、片段增删改查、启用 / 禁用、命中次数 |
| 文件上传 | 通过 `UploadFile` 关联文档 |
| 文档处理 | 支持 automatic / custom 处理规则、分段规则、chunk_size、chunk_overlap |
| 索引状态 | waiting、parsing、splitting、indexing、completed、error |
| 检索策略 | semantic、full_text、hybrid |
| 检索工具 | `dataset_retrieval` 可作为 LangChain Tool 被 Agent / Workflow 调用 |
| 召回测试 | `/datasets/<id>/hit` 支持召回测试和最近查询记录 |
| App 绑定 | `AppDatasetJoin`、`AppConfig.datasets` 支持应用绑定知识库 |
| Workflow 绑定 | dataset_retrieval workflow node 支持工作流检索知识库 |

**代码审计修正（v4.0）**：

上述"已具备能力"中，检索策略 semantic/full_text/hybrid 和 dataset_retrieval 工具在代码层面存在但生产链路不完整。knowledge_base_service.py 仅有基础 CRUD（create/get/delete），未见完整的 RAG 检索管线：缺失向量索引构建、chunk 切分执行、embedding 生成、相似度召回、rerank 等核心环节。App 绑定知识库的 AppDatasetJoin 存在，但 Agent 执行时是否真正调用知识库检索需要验证。

现有 TokenBufferMemory 仅是会话短期上下文裁剪（trim_messages strategy="last" max_tokens=2000），不是跨会话长期记忆。长期记忆已由第 16 章脑启发记忆系统完全接管，旧记忆系统代码（long_term_memory_service.py 的 MemoryCandidateExtractor / MemoryConfidenceTracker / UserMemoryConfirmationService）已删除。

当前支持较好的资料类型：

| 类型 | 当前情况 |
| --- | --- |
| 文档 | 已支持 md、doc、docx、txt、pdf、csv、xlsx、xls、html 等 |
| 图片 | 上传层允许 jpg、jpeg、png、webp、gif、svg；L1 视觉理解 + OCR 入库已落地（P2A），细粒度 OCR 区块坐标等 L2 能力后置 |
| 视频 | L1 关键帧抽取 + 视觉描述入库已落地（P2A）；ASR 音轨提取、场景切分、视觉向量索引等 L2 能力后置 |
| 音频 | L1 ASR 全文转写入库已落地（P2A）；说话人切分、章节切分等 L2 能力后置 |

明确缺口（P1 数据基座落地后已消解项标注 ✅）：

1. 现有 `KnowledgeBase` 已演进为"用户资料内容库 + 板块"的载体，分层作用域、板块类型与分区体系均已落地（多模态 L1 解析入库见 §11.8，检索取料能力属 P3）。
2. 现有 `TokenBufferMemory` 只是会话短期上下文裁剪，不是跨会话长期记忆。长期记忆由第 16 章记忆系统负责。
3. ✅ 已消解：`KnowledgeBase.knowledge_scope` 已落地，可区分系统级知识库、用户资料内容库、团队/租户/项目知识库。
4. ✅ 已消解：归属判断已引入 `owner_account_id` + `owner_admin_user_id`，可区分"管理员自己的个人知识库"和"管理员维护的系统级知识库"。
5. ✅ 已消解：`operation_context`、`owner_admin_user_id`、`visibility_scope` 字段已落地，可表达管理上下文和发布范围。
6. 长期记忆管理已由第 16 章记忆系统接管（图可视化 CRUD），知识库系统不再负责记忆管理。
7. 资料库的**多媒体 L1 基础解析（图片视觉摘要 + OCR、音频 ASR、视频关键帧视觉描述）已接入索引链路**（P2A 已落地，见 §11.8）；**L2 深度解析链路（视频 ASR 音轨提取、说话人切分、关键帧视觉向量索引）尚未实现**，属 P3 范围。
8. 外部数据源连接与同步**已实现**：`ExternalDataSource` 模型 + lark/notion/github 连接器（真实 API）+ 本地文件夹连接器；凭证经 Fernet 加密存储、API 返回脱敏；支持手动同步与 Celery 定时自动同步；删除数据源时级联清理同步产物（文档/分段/向量/上传文件）。
9. ✅ 已消解：分层检索（`layered_search` 按 `knowledge_scope` 分层）已落地，不再只按 account_id 做基础隔离。
10. 现有 App 绑定知识库是预绑定模式，后续需要接入动态知识检索工具子池（P3 范围）。

由于当前系统没有必须保留的旧数据，数据库模型可以按目标架构直接重构，不需要为了兼容历史数据做复杂迁移策略。实施时可以优先保证新模型清晰，而不是维持旧字段语义。

建议演进方式：

```text
现有 Dataset / Document / Segment
  -> 直接重构为带 knowledge_scope、owner_scope、visibility_scope 的知识库模型
  -> 增加 operation_context 与 owner_admin_user_id
  -> 承载系统级知识库 + 用户资料内容库
  -> 新增系统级知识库管理入口和发布状态
  -> 再统一接入 knowledge tool pool
  -> 外部数据源连接/同步已落地（凭证加密 + 定时自动同步 + 级联清理）
  -> 注：长期记忆已由第 16 章记忆系统接管，不在知识库系统改造范围内
```

数据模型策略：

| 模型方向 | 策略 |
| --- | --- |
| Dataset | 可直接扩展或重命名为 KnowledgeBase，不需要保留旧数据兼容逻辑 |
| Document / Segment | 可按资料内容库重新设计字段，第一阶段优先文本和结构化资料，多媒体解析字段预留但能力后置 |
| UserMemory | 新增独立模型，不建议复用 Dataset 承载长期习惯 |
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

### 11.7 知识库板块与分区体系（P1 已落地）

P1 数据基座已落地，知识库从"扁平文本库"升级为**全媒体素材中心**的组织结构：板块类型（`base_type`）决定板块可容纳的媒体、分区（`KnowledgePartition`）提供两级归类、标签（复用 `Tag`）提供多重属性，容量由存储配额统一管控。设计源头见 [knowledge-base-product-form-design.md](../knowledge-base-product-form-design.md) §二。

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

分区权限首版不做——分区是组织手段而非权限边界，权限仍在板块层。

#### 11.7.4 标签关联（复用既有 Tag）

复用 `Tag` 模型与 `TagAssignmentService` 的自动打标能力，仅将作用对象从 App/Workflow 扩展到知识库，对齐既有 `AppTag` / `WorkflowTag` 模式，新增两张关联表：

| 模型 | 表 | 关联 | 唯一约束 | 用途 |
| --- | --- | --- | --- | --- |
| `KnowledgeBaseTag` | `knowledge_base_tag` | 板块 ↔ `Tag` | `(knowledge_base_id, tag_id)` | 跨板块索引导航 |
| `KnowledgeDocumentTag` | `knowledge_document_tag` | 素材 ↔ `Tag` | `(knowledge_document_id, tag_id)` | 素材属性过滤 |

两表均含 `account_id`，标签或板块/素材删除时关联级联清理。

**分区与标签的分工**：分区是互斥层级归类（一个素材只能在一个分区），标签是可交叉叠加的属性（一个素材可有多个标签）。

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

P1 全部 DDL 由单个迁移 `p1a2b3c4d5e6_add_knowledge_product_form_base.py`（位于 `api/internal/migration/versions/`）承载，已在真实 DB 落库、迁移链保持单 head、`downgrade` 可逆：

- `knowledge_base` 增加 `base_type` / `partition_mode`（+ `base_type` 索引）
- `knowledge_document` 增加 `partition_id` / `media_type` / `parse_profile`（+ 两个索引）
- `upload_file.size` 由 integer 升级为 bigint
- 新建 `knowledge_partition` / `knowledge_base_tag` / `knowledge_document_tag` / `account_storage_usage`

### 11.8 多模态素材解析（P2A 已落地）

P2A 把 P1 预留的 `media_type` / `parse_profile` 数据落点接上索引链路：图片、音频、视频素材上传后自动解析为可被语义检索命中的文本片段，实现"上传视频 → 能被语义检索命中"。实施计划见 [2026-09-14-knowledge-base-p2a-multimodal-ingest.md](../../superpowers/plans/2026-09-14-knowledge-base-p2a-multimodal-ingest.md)。

#### 11.8.1 KnowledgeMediaExtractorService（三分支）

`KnowledgeMediaExtractorService`（`internal/service/knowledge_media_extractor_service.py`）负责把非文档素材转为文本片段，`extract(document, upload_file)` 按 `document.media_type` 分派：

| 分支 | media_type | 处理链路 | 产物 |
| --- | --- | --- | --- |
| 图片 | `image` | 从对象存储下载 → `path_to_data_uri`（按扩展名推断 MIME，编码前上限 8MB）→ 视觉模型（画面描述 + OCR） | 1 个片段；摘要为空返回 `[]` |
| 音频 | `audio` | 下载 → 包装为 `FileStorage` → `AudioService.audio_to_text` ASR 全文转写 | 1 个片段；转写为空返回 `[]` |
| 视频 | `video` | 下载 → `extract_video_frames`（默认 3 帧，优先系统 ffmpeg，降级 imageio-ffmpeg）→ 逐帧视觉描述 | 每帧 1 个片段；单帧失败跳过，全部失败抛错 |

文档类型（`document`）返回空列表，由既有文本链路（parsing → splitting → indexing）处理。

#### 11.8.2 视觉能力共享模块

视觉模型调用与视频抽帧从内置工具中抽取为共享包 `internal/core/vision/vision_invoke.py`，供「内置工具」与「知识库多模态解析」复用，避免两处重复维护：

| 函数 | 职责 |
| --- | --- |
| `path_to_data_uri(path)` | 本地图片 → data URI（按扩展名推断 MIME，8MB 上限） |
| `invoke_vision_model(data_uri, prompt)` | 经 `LanguageModelService.get_feature_model("vision_analyze")` 调用视觉模型 |
| `extract_video_frames(video_path, frame_count=3)` | 抽关键帧，返回 data URI 列表；ffmpeg 不可用时降级 imageio-ffmpeg，均不可用抛错 |

`providers/vision_tools/vision_analyze.py` / `video_analyze.py` 已改为复用该模块，对外行为不变。

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
| `video` | 单帧视觉描述（含 OCR） | `media_type`、`scene_index`（帧序号，从 1 起）、`frame_count`（总帧数） |

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
         → _finalize_segments：片段置 completed + enabled，文档置 completed
           parse_profile={"tier1": {...}}
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

#### 11.8.7 解析档位与 L2 未实现

多媒体路径收尾写入 `parse_profile.tier1`（L1 基础解析状态）：

```json
{"tier1": {"status": "completed", "media_type": "video", "segment_count": 3}}
```

| 档位 | 状态 | 内容 |
| --- | --- | --- |
| L1 基础解析 | ✅ 已落地（P2A） | 图片视觉摘要 + OCR、音频 ASR 转写、视频关键帧视觉描述 → 片段 + 向量 |
| L2 深度解析 | ❌ 未实现（属 P3） | 视频 ASR 音轨提取、说话人切分、关键帧视觉向量索引（CLIP 类视觉编码 + 独立索引 + 融合排序） |

L2 按需解析触发、关键帧视觉向量索引与检索取料的过滤能力（板块/分区/标签/媒体类型）均属 P3 范围；`parse_profile.tier2` 字段已在 §11.7.5 预留但当前不写入。
