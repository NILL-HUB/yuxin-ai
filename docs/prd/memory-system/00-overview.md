# 脑启发记忆系统概览

> 本文档为记忆系统子文档的概览入口，包含设计原则、脑启发架构映射、最小闭包抽象、System 1/2 双系统架构、技术栈适配、实现路线图和与知识库系统的集成关系。
>
> **主文档**: [architecture-design.md](../architecture-design.md)
> **详细实现**: [01-data-models-and-write-path.md](./01-data-models-and-write-path.md) | [02-storage-and-retrieval.md](./02-storage-and-retrieval.md) | [03-consolidation-skill-policy-api.md](./03-consolidation-skill-policy-api.md)

---

## 16. 脑启发记忆系统（v5.0 新增）

> **定位**：本章定义 OpenAgent 的长期记忆系统。记忆系统与知识库系统（第 11 章）是两个独立系统：知识库系统解决"知识资产管理"问题（文档上传、RAG 检索、外部数据源同步），记忆系统解决"Agent 认知记忆"问题——如何让 Agent 像人脑一样写入、巩固、召回和遗忘记忆。
>
> **与旧记忆系统的关系**：本章**完全替代**旧记忆系统（MemoryCandidateExtractor + MemoryConfidenceTracker + UserMemoryConfirmationService 的"候选→确认→保存"流程）。旧系统的逐条确认流程被**自动写入 + 图可视化事后管理**替代：SalienceScorer 评分后自动写入，用户通过图数据库可视化界面随时 CRUD 自己的记忆。系统处于二开阶段，无生产数据，不做向后兼容，旧代码直接删除。
>
> **完整实现**见子文档：
> - [01-data-models-and-write-path.md](./01-data-models-and-write-path.md) — 数据模型与写入路径
> - [02-storage-and-retrieval.md](./02-storage-and-retrieval.md) — 存储层与读取路径
> - [03-consolidation-skill-policy-api.md](./03-consolidation-skill-policy-api.md) — 巩固引擎、技能池、Policy 与 API

### 16.1 设计原则

| 原则 | 说明 |
|---|---|
| Ledger 只增不改 | 所有原始记忆写入权威账本后不可修改，更新以追加新事实完成，保留完整历史可追溯 |
| Views 可重建 | 派生视图（Digest、Skill Pool）全部从 Ledger 计算，任何时刻可丢弃重建 |
| 写入时过滤，读取时召回 | 写入阶段通过显著性评分前置过滤低价值信息（节省 ~70% 存储），读取阶段多路召回+漏斗压缩精准注入 |
| 自动写入 + 事后图管理 | SalienceScorer 评分后自动写入，无需用户逐条确认；用户通过图可视化界面随时 CRUD 自己的记忆 |
| 双系统推理 | 大多数请求通过预计算视图在单次 LLM 调用完成（System 1，<200ms），仅深层查询启动 agentic 检索循环（System 2） |
| 分级存储与可恢复遗忘 | 四级存储（Hot/Warm/Cold/Frozen）动态管理生命周期，"遗忘"仅降低索引权重，原始数据始终保留 |
| 依赖降级 | 每个新依赖（Neo4j/Celery/Redis）挂掉时功能降级但不崩溃，极端情况下对话功能正常（仅无记忆注入） |

### 16.2 脑启发架构映射

| 脑区 | AI 组件 | 职责 |
|---|---|---|
| 杏仁核 | SalienceScorer | 写入时注入情感/显著性标签，标记越强越容易被后续检索命中 |
| 海马体 CA3 | TKG Episode Subgraph | 快速编码原始经历，提供高分辨率情景索引 |
| 海马体 CA1 | TKG Semantic Subgraph | 提取实体/关系/事实，支持模式补全 |
| 内嗅皮层 | Vector Store | 提供语义嵌入空间的内容寻址能力 |
| 新皮层 | TKG Community Subgraph | 慢速整合跨 episode 共性模式，形成高层概念 |
| 前额叶 | Policy Layer | 执行控制与决策路由，不直接操作存储 |
| 睡眠 SWRs | Consolidation Engine | 非交互时段离线整理：冲突消解、权重衰减、冗余合并 |

### 16.3 最小闭包抽象：(Ledger, Views, Policy)

整个记忆系统的功能归约为三个不可再分的原语：

| 层 | 职责 | 约束 | 存储介质 |
|---|---|---|---|
| **Ledger（权威账本）** | 所有原始记忆的不可变存储 | Append-Only | Neo4j (TKG) + PostgreSQL pgvector (Vector) + Redis (Profile) |
| **Views（派生视图）** | 从 Ledger 计算的压缩/结构化摘要 | 可随时丢弃重建 | Memory Digest, Skill Pool, 查询自适应视图 |
| **Policy（控制层）** | 决定何时读、写什么、读什么、注入哪些 Views | 不直接操作 Ledger | SalienceScorer, PolicyRouter, EarlyStop |

### 16.4 System 1 / System 2 双系统架构

```
用户请求
    │
    ▼
┌──────────────────────────┐
│  System 1（快速路径）      │  ← 单次 LLM 调用，< 200ms
│  1. Policy: 查询意图解析   │
│  2. Views: 注入 Digest    │
│  3. LLM: 直接推理输出     │
└──────────┬───────────────┘
           │ 需要深层记忆检索？
           ▼
┌──────────────────────────┐
│  System 2（慢速路径）      │  ← Agentic 循环
│  1. TKG 粗召回 (Neo4j)   │
│  2. 向量精召回 (pgvector) │
│  3. 证据累积 & Early Stop │
│  4. LLM 压缩 & 结构化     │
│  5. 注入 System 1 上下文  │
└──────────────────────────┘
```

System 1 依赖预计算的 Views（Digest + Skills），确保大多数请求在单次 LLM 调用中完成。System 2 仅在需要深层记忆检索时启动。

**与现有 Orchestrator 的集成**：System 1 对应第 13.2 节"快速路径"，System 2 对应第 13.3 节"复杂路径"。Orchestrator 的复杂度判断结果直接路由到对应的记忆检索路径。

### 16.5-16.15 详细内容

以下内容详见记忆系统子文档：

| 小节 | 内容 | 子文档 |
|---|---|---|
| 16.5 写入路径 | SalienceScorer 五因子评分、LedgerWriter 双通道写入、TKG 实体消解 | [01-data-models-and-write-path.md](./01-data-models-and-write-path.md) |
| 16.6 存储层 | 四级存储分层、HebbianDecay 赫布权重衰减、冷存储与 Key 重建 | [02-storage-and-retrieval.md](./02-storage-and-retrieval.md) |
| 16.7 读取路径 | 混合检索评分、SpreadActivation 图扩展激活、FunnelCompressor 五层漏斗压缩、DigestManager Memory Digest | [02-storage-and-retrieval.md](./02-storage-and-retrieval.md) |
| 16.8 巩固引擎 | 五阶段巩固流程、冲突检测与事实失效、表征排斥 | [03-consolidation-skill-policy-api.md](./03-consolidation-skill-policy-api.md) |
| 16.9 技能池涌现 | 从行为数据涌现可复用模式、技能成熟度计算 | [03-consolidation-skill-policy-api.md](./03-consolidation-skill-policy-api.md) |
| 16.10 Policy 层 | PolicyRouter 策略路由器、MemoryGovernor 记忆治理 | [03-consolidation-skill-policy-api.md](./03-consolidation-skill-policy-api.md) |
| 16.11 技术栈适配 | Neo4j/MinIO/Celery 与 PostgreSQL 18+pgvector/Redis 关系 | 本文下文 |
| 16.12 API 接口 | 13 个端点定义（替代旧 API） | [03-consolidation-skill-policy-api.md](./03-consolidation-skill-policy-api.md) |
| 16.13 监控与度量 | 任务有效性/记忆质量/效率/治理四维指标 | [03-consolidation-skill-policy-api.md](./03-consolidation-skill-policy-api.md) |
| 16.14 实现路线图 | P0-P5 七阶段交付 | 本文下文 |
| 16.15 与知识库系统的集成关系 | 两个独立系统的集成架构图 + 集成要点 | 本文下文 |
| 16.16 用户记忆图可视化 | 三层交互设计 + 节点操作策略 + 性能保障 | [02-storage-and-retrieval.md](./02-storage-and-retrieval.md) |
| 16.17 降级策略 | 四依赖降级矩阵 + 极端情况处理 | [02-storage-and-retrieval.md](./02-storage-and-retrieval.md) |
| 16.18 公共 AI 资源配置与异步精准架构 | memory_* feature_key 模型选择 / 高推理模型 + 探针机制 / 任务分流 / 前后端 memory_type 对齐 | [../modules/07-public-ai-config.md](../modules/07-public-ai-config.md) + 本文下文 |

### 16.11 技术栈适配

> **v5.1 技术栈变更（2026-07-09）**：原规划使用 Qdrant（记忆向量）+ Weaviate（知识库向量）双向量库方案。经评估 PostgreSQL 18 + pgvector 扩展的 HNSW 索引性能（10 万 768 维索引 ~40s，KNN 延迟 <5ms）已满足项目千万级向量需求，且可消除关系数据与向量数据的双写一致性问题，故决定：
> - 移除 Qdrant 容器（代码层从未实现，零迁移成本）
> - 移除 Weaviate 容器（向量迁移到 PostgreSQL pgvector）
> - 向量检索统一到 PostgreSQL 18 + pgvector，利用 SQL JOIN 实现 knowledge_scope 权限过滤
> - 保留 Neo4j 用于 TKG 时序知识图谱
> - Redis 8 Vector Set 作为后续语义缓存的可选项

脑启发记忆系统引入 Neo4j（时序知识图谱）作为核心图存储。知识库系统和记忆系统的向量检索统一使用 PostgreSQL 18 + pgvector 扩展：

| 组件 | 知识库系统 | 记忆系统 | 说明 |
|---|---|---|---|
| 关系数据 | PostgreSQL 18 | PostgreSQL 18（共享） | 用户管理、App 配置共用；知识库元数据和记忆元数据各用各的表 |
| 向量检索 | PostgreSQL 18 + pgvector | PostgreSQL 18 + pgvector（共享） | 知识库向量存于 `segment.embedding` / `knowledge_segment.embedding`；记忆向量存于 `user_memory.embedding`。HNSW 索引，SQL JOIN 过滤 knowledge_scope |
| 图存储 | 无 | Neo4j 2026 | Neo4j 仅用于记忆系统 TKG，知识库系统不需要图存储 |
| 缓存 | Redis 8 | Redis 8（共享） | 知识库系统用 Redis 做通用缓存；记忆系统额外用 Redis 做 Digest/Profile/Skill 缓存 |
| 对象存储 | 无 | MinIO（S3 兼容） | MinIO 仅用于记忆系统 Frozen 层归档 |
| 任务调度 | 无 | Celery + Redis Broker | Celery 仅用于记忆系统巩固引擎定时任务 |
| LLM | OpenAI 兼容 | 同左（共享） | 复用现有 LLM 调用基础设施 |
| 嵌入模型 | 现有 embedding | text-embedding-3-large (1024d) | 记忆向量使用独立 embedding 模型，与知识库向量隔离 |

**部署增量**：在现有 docker-compose 中新增 neo4j、minio 两个服务（Qdrant 和 Weaviate 已移除），不影响现有服务运行。

### 16.14 实现路线图

| 阶段 | 交付物 | 验收标准 |
|---|---|---|
| P0: 基础设施 | docker-compose 新增 Neo4j/MinIO + Celery；PostgreSQL 18 启用 pgvector 扩展 | 所有服务可连接、健康检查通过；pgvector 扩展可用 |
| P1: 写入路径 | SalienceScorer + LedgerWriter + API | 可接收事件并正确写入 TKG + Vector |
| P2: 读取路径 | Retriever + Digest + Funnel | 可准确召回，System 1 可用 |
| P2.5: 技能池 | SkillEmergence + Digest 集成 | 技能自动涌现 + 增量更新 |
| P3: 巩固引擎 | ConsolidationEngine + Celery | 非交互时段自动整理记忆 |
| P4: Policy 完善 | Router + Governor + 监控 | 完整策略控制 + 四层度量 |
| P5: 进阶优化 | 社区子图 + Key 重建 + Latent Injection | 生产级性能和可靠性 |

### 16.15 与知识库系统的集成关系

记忆系统和知识库系统是两个独立系统，各自有独立的写入路径、存储介质和检索路径。它们在 ResultSynthesizer 处汇合，统一合成最终回答。

```
┌─────────────────────────────────────────────────────────────────────┐
│ 知识库系统（知识资产管理） — 详见 modules/02-knowledge-base.md          │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐                                │
│  │ 系统级知识库  │  │ 用户资料内容库 │                                │
│  │ (system)     │  │ (user_content)│                                │
│  └──────┬───────┘  └──────┬───────┘                                │
│         │                 │                                         │
│         │   RAG 管线       │                                         │
│         │   parse→split   │                                         │
│         │   →index        │                                         │
│         ▼                 ▼                                         │
│  ┌──────────────────────────────┐                                   │
│  │ PostgreSQL pgvector           │                                   │
│  │ (知识库向量, knowledge_scope   │                                   │
│  │  隔离, HNSW 索引)             │                                   │
│  └──────────────┬───────────────┘                                   │
│                 │                                                    │
│  ┌──────────────────────────────┐                                   │
│  │ layered_search 分层检索       │                                   │
│  └──────────────┬───────────────┘                                   │
└─────────────────┼────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 记忆系统（Agent 认知记忆） — 详见 memory-system/                       │
│                                                                     │
│  对话事件                                                            │
│      │                                                              │
│      ▼                                                              │
│  SalienceScorer 评分（五因子）                                        │
│      │                                                              │
│      ├── score > 0.7  → FULL 自动写入                                │
│      ├── 0.3 < score ≤ 0.7 → SUMMARY 自动写入                        │
│      └── score ≤ 0.3  → 不写入（仅更新计数器）                         │
│      │                                                              │
│      ▼                                                              │
│  LedgerWriter → Neo4j TKG + PostgreSQL pgvector                      │
│      │                                                              │
│      ├── 四级存储 + HebbianDecay 衰减                                 │
│      ├── ConsolidationEngine 定期整理（冲突检测/冗余合并/权重扫描）      │
│      └── DigestManager 预计算 Memory Digest（Redis 缓存）              │
│      │                                                              │
│      ▼                                                              │
│  ┌──────────────────────────────┐  ┌──────────────────────────────┐ │
│  │ MemoryRetriever 检索          │  │ 图可视化界面（用户事后管理）    │ │
│  │ System 1: Digest 快速路径     │  │ 三层交互：聚类→子图→详情      │ │
│  │ System 2: TKG+pgvector 深层  │  │ CRUD：软删除/彻底删除/编辑    │ │
│  └──────────────┬───────────────┘  └──────────────────────────────┘ │
└─────────────────┼────────────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│              检索结果合并 + 上下文注入                                 │
│  知识库片段（带 knowledge_scope）+ 记忆片段（带 tier/scope）           │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ResultSynthesizer — 详见 modules/03-orchestration-infra.md           │
│  SystemRulePriorityResolver 区分系统规则 vs 用户偏好                   │
│  + Memory Digest 注入用户画像和活跃技能                               │
└─────────────────────────────────────────────────────────────────────┘
```

**集成要点**：

1. **两个独立系统**：知识库系统管"文档资产"（RAG 管线 + PostgreSQL pgvector），记忆系统管"认知记忆"（TKG + pgvector）。各自有独立的写入路径、存储介质和检索路径。
2. **写入路径分离**：知识库文档通过 RAG 管线写入 `segment.embedding` / `knowledge_segment.embedding`（带 knowledge_scope）；记忆事件通过 SalienceScorer 评分后自动写入 Neo4j TKG + `user_memory.embedding`。两个写入路径完全独立。
3. **检索融合**：layered_search 分层检索知识库片段；MemoryRetriever 检索记忆片段。两类结果在 ResultSynthesizer 合成时统一处理，知识库片段按 knowledge_scope 分类，记忆片段按 tier/scope 分类。
4. **上下文注入**：System 1 路径下，Memory Digest 作为默认上下文注入（用户画像+活跃技能+近期事件+任务状态），仅在 Digest 不足以回答时触发 System 2 深层检索。Memory Digest 只替代 token_buffer_memory 的 relevant_facts 部分，recent_messages 和 distant_summary 仍由对话管理负责。
5. **巩固触发**：记忆自动写入后，巩固引擎在非交互时段自动整理（冲突检测、冗余合并、权重扫描）。不需要用户确认触发。
6. **用户事后管理**：用户通过图可视化界面查看自己的记忆图谱，可以软删除、彻底删除、编辑、降低权重。这是用户对记忆的控制权——不是事前逐条确认，而是事后全局管理。
7. **降级策略**：每个新依赖（Neo4j/Celery/Redis）挂掉时功能降级但不崩溃。极端情况下（全部不可用）对话功能正常，仅无记忆注入。详见 [02-storage-and-retrieval.md](./02-storage-and-retrieval.md) §降级策略。
8. **技能反哺**：巩固引擎涌现的技能通过 Digest 注入 Agent 上下文，成熟度高的技能可被管理员提升为预配置 Agent 模板。

### 16.18 公共 AI 资源配置与异步精准架构（v5.1 新增）

> **设计变更（2026-07-22）**：记忆系统的所有 LLM 调用必须通过 `LanguageModelService.get_feature_model(feature_key)` 取模型，禁止直连 `get_cheap_chat_model()`。完整的公共 AI 配置架构详见 [../modules/07-public-ai-config.md](../modules/07-public-ai-config.md)。

#### 16.18.1 异步精准架构原则

**核心原则**：整套链路（模型路由池 → Agent 子池 → 工具子池）给用户交付的是**精准正确的结果**，不是秒级智障回复。速度重要但分任务。

**任务分流**：主入口 LLM 是调度器，根据用户输入类型决定走哪条路径：

| 用户输入类型 | 主入口 LLM 决策 | 后续流程 |
|---|---|---|
| 寒暄/简单问答（"你好"、"你是谁"、"能帮我做什么"） | 直接回答 | **结束流程**，不走 Agent/工具池 |
| 复杂任务（"帮我用 Python 做一个飞行棋游戏"） | 分析需求 | 挑选 Agent 子池 → 派发任务 → Agent 在工具子池选工具执行 → 汇总结果 |

**记忆系统异步执行**：记忆系统的所有 AI 调用（写入、提炼、归档、巩固）都是**后台异步任务**，不影响用户交互响应延迟。这类任务追求**精准度而非速度**，应使用**语义理解强大的高推理模型**——推理模型具备思维链能力，对语义的深度理解远强于非推理 chat 模型，慢几十秒无所谓因为是后台任务。

```
用户消息处理
    │
    ├──→ 同步快通道：用户感知响应
    │        ├── 简单问答 → 直接回答，结束流程
    │        └── 复杂任务 → Agent 子池 + 工具子池执行 → 汇总返回
    │
    └──→ Celery 后台异步任务（无用户等待）
                ├── 显式记忆检测（高推理模型）
                ├── 显著性评分（高推理模型）
                ├── 实体抽取与冲突消解（高推理模型）
                └── 巩固引擎（凌晨 3 点批量，无延迟约束）
                │
                └── 探针式活性检测（每 60s）
                        ├── 模型仍在产出 token → 继续等待不干扰
                        └── 模型死机/卡死 → 终止写入链路，不写入任何东西
```

#### 16.18.2 模型选择：高推理模型 + 探针机制

**反面案例**（v5.0 错误）：记忆系统 LLM 调用使用**固定短超时**（2-5s）包装：
- 高推理模型还在思考阶段就被超时切断 → 降级为正则匹配/默认值 0.5/空列表
- **降级机制反而制造垃圾记忆污染大脑**
- 错误归因："推理模型延迟太高" → 实际上是"超时阈值切断思考"

**正确做法**（v5.1 修正）：
- 记忆系统使用**高推理模型**（语义理解强，具备思维链）
- **废除固定超时**，改为**探针式活性检测**：每 60s 探测一次，模型仍在产出 token 就继续等待不干扰，模型死机/卡死才终止
- **宁可不写，也不写垃圾**：探针检测到死机时终止写入链路，不写入任何东西，记录日志
- 文档不硬编码推荐任何具体模型版本，由 admin 在后台按 feature_key 绑定

#### 16.18.3 11 个 memory_* feature_key 清单

DB 实际预置（11 个，全部 billable=false，model_type=chat）：

| feature_key | 功能 |
|---|---|
| `memory_explicit_detection` | 显式记忆信号检测 |
| `memory_salience_scoring` | 显著性五因子评分 |
| `memory_entity_extraction` | 实体、关系、事实抽取 |
| `memory_entity_resolution` | 实体消解 |
| `memory_write_conflict_resolution` | 写入时冲突消解 |
| `memory_policy_routing` | PolicyRouter 意图分类 |
| `memory_digest` | Digest LLM 精炼 |
| `memory_compression` | 漏斗压缩 LLM 压缩 |
| `memory_skill_emergence` | 技能模板抽取与更新 |
| `memory_consolidation` | 巩固引擎各阶段 |
| `memory_conflict_detection` | 巩固阶段 2 冲突检测 |

#### 16.18.4 探针式活性检测机制

**废除固定超时**，改为**双信号探针**（LLM 流式 token 活性 + Celery 任务状态）：

| 探测信号 | 检测方式 | 判定 |
|---|---|---|
| LLM token 活性 | 检测 LLM 流式响应是否仍在产出 token | 有新 token 产出 → 模型正常思考中 |
| Celery 任务状态 | 检测 Celery 任务是否仍在 RUNNING 状态 | RUNNING → 任务正常执行中 |

**探针流程**（每 60s 执行一次）：

```
记忆写入任务启动
    ↓
探针每 60s 检测一次
    ├── LLM 仍在产出 token + Celery 任务 RUNNING
    │   → 模型正常思考中，不干扰，继续等待
    │
    └── LLM 无 token 产出 / Celery 任务非 RUNNING
        → 判定为死机/卡死
        → 终止写入链路
        → 不写入任何东西
        → 记录日志（feature_key / 耗时 / 探针检测结果）
```

**核心原则**：**宁可不写，也不写垃圾**。探针检测的是模型活性，不是限制思考时长。高推理模型思考几十秒甚至几分钟是正常的，只要还在产出 token 就让它继续。

**已实现组件**：`LLMActivityProbe` 工具类（`api/internal/service/memory/llm_activity_probe.py`），已于 2026-07-23 落地。复用 `DegradationManager`（`degradation_manager.py`）的后台线程模式 + `_probe_embedding_dimension`（`admin_model_pool_service.py`）的探针模式。11 个记忆系统调用点全部接入：

| 调用点 | feature_key | 调用方式 |
|---|---|---|
| `explicit_detector._call_llm_structured` | `memory_explicit_detection` | `invoke_structured_with_probe` |
| `salience_scorer._call_llm_structured` | `memory_salience_scoring` | `invoke_structured_with_probe` |
| `entity_extractor._call_llm_structured_with_timeout` | `memory_entity_extraction` | `invoke_structured_with_probe` |
| `write_time_conflict_resolver._llm_judge` | `memory_write_conflict_resolution` | `invoke_structured_with_probe` |
| `consolidation_engine._extract_semantic` | `memory_consolidation` | `invoke_with_probe` |
| `digest_manager._render_digest` | `memory_digest` | `invoke_with_probe` |
| `conflict_detector._detect_pair` | `memory_conflict_detection` | `invoke_structured_with_probe` |
| `funnel_compressor._llm_compress` | `memory_compression` | `invoke_with_probe` |
| `policy_router._classify_intent` | `memory_policy_routing` | `invoke_with_probe` |
| `entity_resolution._compute_llm_scores` | `memory_entity_resolution` | `invoke_structured_with_probe` |
| `skill_emergence._extract_template` / `_llm_update_judgment` | `memory_skill_emergence` | `invoke_with_probe` |

所有调用点捕获 `LLMActivityTimeoutError` 走降级路径（返回 None / 空列表 / 默认值，不写入垃圾）。

#### 16.18.5 前后端 memory_type 对齐（v5.1 修复）

**问题**：前端 `MemoryClusterView.vue` 硬编码 6 种 memory_type（profile / preference / relationship / event / project / secret），后端原查询用 `labels(n)[0]` 返回 Neo4j 标签（Episode / Entity / SemanticMemory），导致前端 6 个聚类卡片始终显示 0 节点。

**修复**（`memory_handler.py`）：
- `get_memory_graph`：改为 `MATCH (n:MemoryNode)` + `coalesce(n.memory_type, labels(n)[0])`
- `get_cluster_subgraph`：增加 `n.memory_type = $cluster_type` 属性匹配，兼容前端传值
- 边数据结构：从 `dict(r)` 改为显式构造 `{source, target, type, weight, edge_id}`

**节点写入约定**：所有 MemoryNode 必须设置 `memory_type` 属性（与前端 6 种类型对齐），Neo4j 标签作为辅助分类保留。

#### 16.18.6 billable 计费集成

记忆系统的 11 个 `memory_*` feature_key 全部 `billable=false`（系统基础设施，不扣用户配额）。`CreditService.consume_for_feature` 对这些 feature_key 直接返回 None，平台承担 LLM 调用成本。

用户付费能力（`billable=true`）8 个：`direct_answer` / `conversation_summary` / `assistant_agent_intro` / `rerank_fallback` / `prompt_optimization` / `code_assistant` / `schema_assistant` / `tag_assignment`。详见 [../modules/07-public-ai-config.md](../modules/07-public-ai-config.md) §24.3.6。
