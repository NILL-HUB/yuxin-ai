# 脑启发 AI 记忆系统 — 架构索引

> **版本**: v3.1 (集成版)
> **日期**: 2026-07-09
> **定位**: 本文档已作为 **第 16 章** 集成进 [OpenAgent 架构设计文档](./architecture-design.md#16-脑启发记忆系统v50-新增)。本文件保留为子文档索引和快速导航入口。
> **核心原则**: 记忆不是存储，而是把历史转成当前可用信息的通道

---

## 文档关系

```
architecture-design.md（主架构文档）
  └── 第 11 章：知识库双层设计（知识资产管理）
        └── 11.3.1 用户长期记忆库（用户交互层：候选→确认→保存）
              └── 第 16 章：脑启发记忆系统（记忆引擎层）  ← 本系统
                    ├── memory-system/01-data-models-and-write-path.md
                    ├── memory-system/02-storage-and-retrieval.md
                    └── memory-system/03-consolidation-skill-policy-api.md
```

**第 11.3.1 节**定义记忆系统的**用户交互层**（候选提取→置信度累计→用户确认→保存）。
**第 16 章**定义记忆的**引擎层**（显著性评分→时序知识图谱→分级存储→巩固压缩→双系统检索）。
两者是前后端关系，不是替代关系。

---

## 子文档索引

| 子文档 | 覆盖模块 | 核心类 |
|---|---|---|
| [01 - 数据模型与写入路径](./memory-system/01-data-models-and-write-path.md) | 数据模型 + 写入路径 | MemoryEvent, MemoryNode, MemoryEdge, SalienceResult, MemoryDigest, Skill, RetrievalResult, ConsolidationReport, SalienceScorer, LedgerWriter, entity_resolution |
| [02 - 存储层与读取路径](./memory-system/02-storage-and-retrieval.md) | 存储分级 + 读取路径 | HebbianDecay, ColdStorageManager, MemoryRetriever, SpreadActivation, FunnelCompressor, DigestManager |
| [03 - 巩固引擎、技能池、Policy 与 API](./memory-system/03-consolidation-skill-policy-api.md) | 巩固引擎 + 技能池 + Policy + API + 监控 | ConsolidationEngine, ConflictDetector, RepresentationRepulsion, SkillEmergence, PolicyRouter, MemoryGovernor, FastAPI 路由, Prometheus metrics, 附录 A-D |

---

## 架构速查

### 脑启发映射

| 脑区 | AI 组件 | 职责 |
|---|---|---|
| 杏仁核 | SalienceScorer | 写入时显著性评分，前置过滤低价值信息 |
| 海马体 CA3 | TKG Episode Subgraph | 快速编码原始经历，情景索引 |
| 海马体 CA1 | TKG Semantic Subgraph | 提取实体/关系/事实，模式补全 |
| 内嗅皮层 | Vector Store (PostgreSQL pgvector) | 语义嵌入空间内容寻址 |
| 新皮层 | TKG Community Subgraph | 跨 episode 共性模式整合 |
| 前额叶 | Policy Layer | 执行控制与决策路由 |
| 睡眠 SWRs | Consolidation Engine | 离线整理：冲突消解、权重衰减、冗余合并 |

### 最小闭包：(Ledger, Views, Policy)

| 层 | 职责 | 约束 | 存储 |
|---|---|---|---|
| Ledger | 原始记忆不可变存储 | Append-Only | Neo4j (TKG) + PostgreSQL pgvector (Vector) + Redis (Profile) |
| Views | 从 Ledger 计算的摘要 | 可重建 | Memory Digest, Skill Pool |
| Policy | 读写决策控制 | 不操作 Ledger | SalienceScorer, PolicyRouter, EarlyStop |

### System 1 / System 2

- **System 1（快速路径）**：Digest 注入 → 单次 LLM 调用 → < 200ms
- **System 2（慢速路径）**：TKG 粗召回 → 向量精召回 → 证据累积 → LLM 压缩

### 技术栈

| 组件 | 技术 | 用途 |
|---|---|---|
| 图数据库 | Neo4j 5.x+ | TKG Episode/Entity/Community 三级子图 |
| 向量数据库 | PostgreSQL 18 + pgvector | 1024d 语义嵌入 + HNSW 索引 |
| 缓存 | Redis 7.x+ | Digest/Profile/Skill Pool 热缓存 + Celery broker |
| 对象存储 | MinIO | Frozen 层记忆归档 |
| 任务调度 | Celery + Redis | 巩固引擎 6h 定时任务 |
| TKG 引擎 | Graphiti (getzep) | 实体提取/消解/社区检测 |
| LLM | OpenAI 兼容 | NER/情感分析/评分/摘要/压缩 |
| 嵌入模型 | text-embedding-3-large 1024d | 语义嵌入编码 |

### 实现路线图

| 阶段 | 交付物 | 验收标准 |
|---|---|---|
| P0 | docker-compose 新增 Neo4j/MinIO + Celery；PostgreSQL 18 启用 pgvector | 所有服务可连接 |
| P1 | SalienceScorer + LedgerWriter + API | 可接收事件并写入 TKG + Vector |
| P2 | Retriever + Digest + Funnel | 可准确召回，System 1 可用 |
| P2.5 | SkillEmergence + Digest 集成 | 技能自动涌现 |
| P3 | ConsolidationEngine + Celery | 非交互时段自动整理 |
| P4 | Router + Governor + 监控 | 完整策略控制 |
| P5 | 社区子图 + Key 重建 | 生产级可靠性 |

---

## 配置参考

完整配置文件（config.yaml）包含 37 项配置，涵盖 salience 权重、weight_decay 参数、retrieval 混合权重、consolidation 调度、digest 更新策略等。详见 [子文档 03: 附录 A](./memory-system/03-consolidation-skill-policy-api.md#附录-a配置项速查表)。

关键 Cypher 查询（13 条）见 [子文档 03: 附录 B](./memory-system/03-consolidation-skill-policy-api.md#附录-bcypher-查询速查表)。

LLM Prompt 模板（7 个）见 [子文档 03: 附录 C](./memory-system/03-consolidation-skill-policy-api.md#附录-cllm-prompt-模板速查表)。
