# 记忆系统并行开发任务执行文档

> **创建日期**：2026-07-09
> **关联架构**：[architecture-design.md Ch16](../architecture-design.md) | [memory-system/ 子文档](./)
> **执行原则**：二开阶段，无生产数据，不做向后兼容，旧代码直接删除

---

## 文档导航

| 文档 | 内容 | Track |
|---|---|---|
| [01-phase0-infrastructure.md](./01-phase0-infrastructure.md) | Phase 0：基础设施（I1-I6） | Phase 0 |
| [02-track-a-write-path.md](./02-track-a-write-path.md) | Track A：写入路径（A1-A5） | A |
| [03-track-b-storage-retrieval.md](./03-track-b-storage-retrieval.md) | Track B：存储与检索（B1-B8） | B |
| [04-track-c-consolidation.md](./04-track-c-consolidation.md) | Track C：巩固引擎（C1-C5） | C |
| [05-track-d-policy-governance.md](./05-track-d-policy-governance.md) | Track D：策略与治理（D1-D4） | D |
| [06-track-e-skill-pool.md](./06-track-e-skill-pool.md) | Track E：技能池（E1-E3） | E |
| [07-track-f-frontend-visualization.md](./07-track-f-frontend-visualization.md) | Track F：前端图可视化（F1-F6） | F |
| [08-track-g-cleanup.md](./08-track-g-cleanup.md) | Track G：旧代码清理（G1-G12） | G |
| [09-track-h-monitoring-test.md](./09-track-h-monitoring-test.md) | Track H：监控与集成测试（H1-H5） | H |

---

## 并行执行总览

```
时间 →  T0        T1        T2        T3        T4        T5        T6
        │         │         │         │         │         │         │
Phase 0 ████████  │         │         │         │         │         │
(I1-I6)            │         │         │         │         │         │
        │         │         │         │         │         │         │
Track A           ████████████████  │         │         │         │
(A1-A5)                            │         │         │         │
        │         │         │         │         │         │         │
Track B                       ████████████████████████  │         │
(B1-B8)                                                │         │
        │         │         │         │         │         │         │
Track C                       ████████████████  │         │         │
(C1-C5)                                        │         │         │
        │         │         │         │         │         │         │
Track E                                         ████████  │         │
(E1-E3)                                                   │         │
        │         │         │         │         │         │         │
Track D                                   ████████████  │         │
(D1-D4)                                                │         │
        │         │         │         │         │         │         │
Track F                                                    ██████████████
(F1-F6)                                                              │
        │         │         │         │         │         │         │
Track G     ████  ████  ████  ████  ████  ████  (持续清理)  │
(G1-G12)                                                              │
        │         │         │         │         │         │         │
Track H                                         ████████  ████  ████
(H1-H5)                                                              │
```

---

## 子代理委派策略

| 子代理 | 负责 Track | 前置条件 | 可启动时机 |
|---|---|---|---|
| Agent-Infra | Phase 0 | 无 | 立即 |
| Agent-Write | Track A | Phase 0 完成 | T1 |
| Agent-Retrieve | Track B | Track A 完成 | T2 |
| Agent-Consolidate | Track C | Track A 完成 | T2 |
| Agent-Policy | Track D | Track B 完成 | T3 |
| Agent-Skill | Track E | Track C 完成 | T3 |
| Agent-Frontend | Track F | Track D 完成 | T4 |
| Agent-Cleanup | Track G | 分散执行 | T1 起 |
| Agent-Monitor | Track H | Track B+C 完成 | T3 |

---

## 关键风险与对策

| 风险 | 对策 |
|---|---|
| 文档 1/2 之间的类型冲突（StorageTier str Enum vs IntEnum, MemoryEdge 字段不一致, RetrievalResult 两版定义） | I6 数据模型层统一为单一实现，所有 Track 引用同一份模型 |
| Neo4j Cypher 语句复杂度高（四时间戳双时间模型、entity_resolution 三信号融合） | A2 先实现基础写入，复杂 Cypher 分步验证 |
| LLM 调用成本（SalienceScorer 5 因子 + ConflictDetector + SkillEmergence 都调 LLM） | 优先用 gpt-4o-mini；SalienceScorer 的 rehearsal_boost 因子不调 LLM（纯 Redis 计数器） |
| 前端图渲染性能（200+ 节点） | 限制子图视图 ≤ 200 节点 + LOD 降级 + d3-force 布局 |
| 降级逻辑覆盖面广 | D3 降级管理器作为统一入口，所有记忆操作都经过 D3 检查 |

---

## 代码目录结构规划

```
api/internal/
├── config/
│   └── memory_settings.py          # I2: 记忆系统配置类
├── model/
│   └── memory_models.py            # I6: 统一数据模型（20+ BaseModel/dataclass）
├── service/memory/                 # 新建目录
│   ├── __init__.py
│   ├── salience_scorer.py          # A1: 五因子评分器
│   ├── ledger_writer.py            # A2: 权威账本写入器
│   ├── entity_resolution.py        # A3: 实体消解（三信号融合）
│   ├── hebbian_decay.py            # B1: 赫布权重衰减
│   ├── cold_storage_manager.py     # B2: 冷存储管理
│   ├── retriever.py                # B3: 混合检索器
│   ├── spread_activation.py        # B4: 图扩展激活
│   ├── funnel_compressor.py        # B5: 五层漏斗压缩
│   ├── digest_manager.py           # B6: Digest 管理器
│   ├── consolidation_engine.py     # C1: 巩固引擎
│   ├── conflict_detector.py        # C2: 冲突检测器
│   ├── representation_repulsion.py # C3: 表征排斥
│   ├── policy_router.py            # D1: 策略路由器
│   ├── memory_governor.py          # D2: 记忆治理器
│   ├── degradation_manager.py      # D3: 降级管理器
│   ├── skill_emergence.py          # E1: 技能涌现器
│   └── metrics.py                  # H1-H2: 监控指标
├── handler/
│   └── memory_handler.py           # A4/B7/C5/D4/E2/H4: 统一 API handler
├── task/
│   └── consolidation_tasks.py      # C4: Celery 定时任务
└── migration/
    ├── neo4j_init.cypher           # I4: Neo4j schema
    └── pgvector_hnsw_index.py      # I5: pgvector HNSW 索引（init.sql 已内置 CREATE EXTENSION vector）

api/test/internal/service/memory/   # 新建测试目录
├── test_salience_scorer.py
├── test_ledger_writer.py
├── test_entity_resolution.py
├── test_hebbian_decay.py
├── test_retriever.py
├── test_funnel_compressor.py
├── test_digest_manager.py
├── test_consolidation_engine.py
├── test_conflict_detector.py
├── test_skill_emergence.py
├── test_policy_router.py
├── test_memory_governor.py
└── test_degradation_manager.py

ui/src/
├── services/
│   └── memory-graph.ts             # F1: 前端 API 服务
├── models/
│   └── memory-graph.ts             # F1: 前端类型定义
├── components/memory/              # 新建目录
│   ├── MemoryClusterView.vue       # F2: 聚类视图
│   ├── MemoryGraphView.vue         # F3: 子图视图（力导向布局）
│   └── MemoryNodeDetail.vue        # F4: 节点详情面板
└── views/settings/
    └── MemoryView.vue              # F5: 记忆管理页面（重写）
```

---

## 验证命令

每个任务完成后执行以下验证：

```bash
# 后端类型检查
cd api && python -m py_compile internal/service/memory/*.py

# 后端单元测试
cd api && python -m pytest test/internal/service/memory/ -v

# 前端类型检查
cd ui && npx vue-tsc --noEmit

# 前端单元测试
cd ui && npx vitest run

# 容器健康检查
cd docker && docker compose ps
```
