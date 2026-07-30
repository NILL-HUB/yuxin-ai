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
- 外部数据源：飞书、Notion、网盘、GitHub、企业知识库、业务系统导出的资料等。
- 其他结构化或半结构化业务资料。
- 图片：jpg、jpeg、png、webp、gif、svg 等，第一阶段先后置深度解析。
- 视频：产品演示、会议录像、课程视频等，第一阶段先后置深度解析。
- 音频：会议录音、访谈、播客、语音备忘等，第一阶段先后置深度解析。

资料内容库需要支持：

| 能力 | 说明 |
| --- | --- |
| 上传 | 用户主动上传文件 |
| 外部数据源连接 | 用户授权连接飞书、Notion、网盘、GitHub、企业知识库等外部数据源 |
| 同步 | 支持手动同步和后续扩展定时同步 |
| 解析 | 第一阶段优先处理文本和结构化资料；图片、视频、音频深度解析后置 |
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
| 图片 | 上传层允许 jpg、jpeg、png、webp、gif、svg；第一阶段不要求完整 OCR / 视觉理解入库，深度解析后置 |
| 视频 | 第一阶段不要求视频解析、抽帧、字幕提取、ASR 入库，深度解析后置 |
| 音频 | 第一阶段不要求音频 ASR、说话人切分、转写入库，深度解析后置 |

明确缺口：

1. 现有 Dataset 更像"用户上传资料型知识库"，适合作为用户资料内容库的基础。
2. 现有 `TokenBufferMemory` 只是会话短期上下文裁剪，不是跨会话长期记忆。长期记忆由第 16 章记忆系统负责。
3. 现有知识库缺少 `knowledge_scope`，无法区分系统级知识库、用户资料内容库、团队知识库。（长期记忆库已移出知识库系统）
4. 现有知识库主要使用 `account_id` 做归属判断，但管理员账号也绑定普通 `Account`，因此仅靠 `account_id` 无法区分“管理员自己的个人知识库”和“管理员维护的系统级知识库”。
5. 现有知识库缺少 `operation_context`、`owner_admin_user_id`、`visibility_scope` 等字段，无法表达管理上下文和发布范围。
6. 长期记忆管理已由第 16 章记忆系统接管（图可视化 CRUD），知识库系统不再负责记忆管理。
7. 现有资料库主要覆盖文本类文档，多媒体资料的 OCR、ASR、视频抽帧、视觉摘要、音视频转写等处理链路后置，不阻塞第一阶段。
8. 现有知识库缺少外部数据源连接和同步能力，后续需要支持飞书、Notion、网盘、GitHub、企业知识库等来源。
9. 现有检索只按 account_id 做基础隔离，后续需要扩展用户级、团队级、项目级、租户级作用域。
10. 现有 App 绑定知识库是预绑定模式，后续需要接入动态知识检索工具子池。

由于当前系统没有必须保留的旧数据，数据库模型可以按目标架构直接重构，不需要为了兼容历史数据做复杂迁移策略。实施时可以优先保证新模型清晰，而不是维持旧字段语义。

建议演进方式：

```text
现有 Dataset / Document / Segment
  -> 直接重构为带 knowledge_scope、owner_scope、visibility_scope 的知识库模型
  -> 增加 operation_context 与 owner_admin_user_id
  -> 承载系统级知识库 + 用户资料内容库
  -> 新增系统级知识库管理入口和发布状态
  -> 再统一接入 knowledge tool pool
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
