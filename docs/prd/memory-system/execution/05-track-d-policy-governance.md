# Track D：策略与治理任务执行文档

> **创建日期**：2026-07-09
> **Track**：D（Policy & Governance）
> **任务范围**：D1-D4
> **前置条件**：Track B（存储与检索）完成，Neo4j/PostgreSQL pgvector/Redis/Celery 依赖可用
> **执行原则**：二开阶段，无生产数据，不做向后兼容，旧代码直接删除
> **关联架构**：[architecture-design.md Ch16](../../architecture-design.md) | [memory-system/03-consolidation-skill-policy-api.md §9-§10](../03-consolidation-skill-policy-api.md)

---

## Track D 总览

| 任务 | 名称 | 文件 | 关联架构章节 |
|---|---|---|---|
| D1 | PolicyRouter（策略路由器） | `api/internal/service/memory/policy_router.py` | §9.1 |
| D2 | MemoryGovernor（记忆治理器） | `api/internal/service/memory/memory_governor.py` | §9.2 |
| D3 | DegradationManager（降级管理器） | `api/internal/service/memory/degradation_manager.py` | §9.1 降级逻辑 |
| D4 | 图谱 API + 记忆 CRUD API | `api/internal/handler/memory_handler.py`（追加） | §10 |

**Track D 依赖关系**：

```
D3 DegradationManager ─┐
                        ├─→ D4 API（所有写/读路径经 D3 检查）
D1 PolicyRouter ────────┤
                        │
D2 MemoryGovernor ──────┘
```

---

## D1：PolicyRouter（策略路由器）

### 任务编号
D1

### 任务名
PolicyRouter 策略路由器实现

### 目标
实现查询意图分类、视图选择、System 1/2 路由判定与依赖故障时的降级路由，作为记忆读取路径的执行控制中枢。该组件不操作 Ledger，仅做决策路由。

### 输入
- Neo4j 异步驱动（`AsyncDriver`），用于视图可用性检查
- LLM 客户端（`AsyncOpenAI`，可选），用于意图分类；不传则仅使用规则分类
- 用户查询文本（query）
- 用户 ID（user_id）

### 输出
- 文件路径：`api/internal/service/memory/policy_router.py`
- 关键类与函数签名：
  ```python
  class PolicyRouter:
      def __init__(self, neo4j: AsyncDriver, llm_client: Optional[AsyncOpenAI] = None) -> None: ...

      async def classify_query(self, query: str) -> IntentClassification: ...

      async def select_views(self, intent: IntentClassification, user_id: str) -> list[str]: ...

      def should_use_system2(self, intent: IntentClassification) -> bool: ...

      async def select_retrieval_strategy(self) -> str: ...

      # 内部方法
      @staticmethod
      def _rule_classify(query: str) -> IntentClassification: ...

      async def _llm_classify(self, query: str) -> IntentClassification: ...
  ```
- 常量：`PREDEFINED_VIEWS: dict[str, ViewProfile]`（5 个视图定义）
- 数据模型：`QueryIntent`（7 类意图 Enum）、`IntentClassification`、`ViewProfile`

### 实现步骤
1. 定义 `QueryIntent` Enum，包含 7 类意图：
   - `FACTUAL`（事实查询）
   - `TEMPORAL`（时间查询）
   - `RELATIONAL`（关系查询）
   - `ACTION`（行动指令）
   - `REFLECTION`（自省）
   - `GREETING`（问候）
   - `META`（元查询）
2. 定义 `IntentClassification`（Pydantic BaseModel）：`intent`、`confidence`（0.0-1.0）、`entities: list[str]`、`time_reference: Optional[str]`。
3. 定义 `ViewProfile` 模型：`view_name`、`description`、`node_labels`、`edge_types`、`score_boost`。
4. 定义 `PREDEFINED_VIEWS` 常量，5 个视图：
   - `profile`（用户画像视图，节点 User/Trait/Preference，边 HAS_TRAIT/HAS_PREFERENCE）
   - `episodes`（事件记忆视图，节点 Episode，边 NEXT/CAUSED_BY，score_boost=1.2）
   - `skills`（技能视图，节点 Skill，边 REQUIRES/BELONGS_TO）
   - `relations`（关系网络视图，节点 Person/Organization，边 KNOWS/WORKS_WITH/RELATED_TO）
   - `knowledge`（知识视图，节点 SemanticMemory/Fact，边 SUPPORTS/CONTRADICTS）
5. 实现 `PolicyRouter.__init__(neo4j, llm_client=None)`，保存 Neo4j 与可选 LLM 客户端。
6. 实现 `classify_query(query)`：
   - 优先调用 `_rule_classify`（规则匹配），若返回置信度 < 阈值（0.7）且 LLM 可用，则调用 `_llm_classify`
   - LLM 调用失败时回退到规则分类结果，记录 warning 日志
7. 实现 `_rule_classify`（静态方法）：基于关键词匹配 7 类意图
   - 时间关键词（昨天/上周/前天/最近/什么时候/几号/哪天）→ TEMPORAL，confidence=0.7
   - 关系关键词（关系/认识/朋友/同事/谁是）→ RELATIONAL，confidence=0.7
   - 行动关键词（帮我/安排/设置/提醒/创建）→ ACTION，confidence=0.8
   - 自省关键词（我最近/总结/回顾/我的/忙什么）→ REFLECTION，confidence=0.7
   - 问候关键词（你好/嗨/hello/hi）→ GREETING，confidence=0.9
   - 元查询关键词（你记得/你认识/你知道什么/记忆）→ META，confidence=0.7
   - 默认 → FACTUAL，confidence=0.5
8. 实现 `_llm_classify`：构造包含 7 类意图的 prompt，调用 LLM（gpt-4o-mini，temperature=0.0，response_format=json_object），解析返回的 `intent/confidence/entities/time_reference` 构造 `IntentClassification`。
9. 实现 `select_views(intent, user_id)`：根据意图映射到预定义视图子集
   - FACTUAL → knowledge
   - TEMPORAL → episodes
   - RELATIONAL → relations
   - ACTION → profile, skills
   - REFLECTION → profile, episodes, knowledge
   - GREETING → profile
   - META → 全部 5 个视图
   - 过滤返回存在于 `PREDEFINED_VIEWS` 中的视图名
10. 实现 `should_use_system2(intent)`：
    - GREETING / META → False（System 1 足够）
    - TEMPORAL / RELATIONAL / REFLECTION → True
    - FACTUAL 且 confidence < 0.9 → True
    - 其余 → False
11. 实现 `select_retrieval_strategy()`：根据依赖健康状态返回降级策略
    - Neo4j 不可用 → `"vector_only"`（仅 pgvector）
    - pgvector 不可用（PostgreSQL 向量检索不可用）→ `"graph_only"`（仅 TKG）
    - 两者都不可用 → `"digest_only"`（仅 Redis 缓存）
    - 全部不可用 → `"disabled"`（跳过记忆注入）
    - 全部可用 → `"full"`
    - 健康检查通过尝试建立 Neo4j/pgvector 连接（带超时）实现，可复用 D3 的 DegradationManager 状态
12. 在模块顶部添加 `from __future__ import annotations` 与必要的 import（logging、Enum、Optional、pydantic、neo4j.AsyncDriver、openai.AsyncOpenAI）。

### 验收标准
- [ ] 7 类意图（FACTUAL/TEMPORAL/RELATIONAL/ACTION/REFLECTION/GREETING/META）规则分类正确，每类至少 1 个测试用例
- [ ] `classify_query` 在规则置信度低时正确触发 LLM 分类，LLM 失败时回退到规则结果
- [ ] `select_views` 对 7 类意图返回正确的视图子集，META 返回全部 5 个视图
- [ ] `should_use_system2` 对 GREETING/META 返回 False，对 TEMPORAL/RELATIONAL/REFLECTION 返回 True
- [ ] `select_retrieval_strategy` 在 Neo4j/pgvector/Redis 各种故障组合下返回正确的降级策略（full/vector_only/graph_only/digest_only/disabled）
- [ ] `PREDEFINED_VIEWS` 包含 5 个视图定义，字段完整
- [ ] `python -m py_compile internal/service/memory/policy_router.py` 通过
- [ ] `python -m pytest test/internal/service/memory/test_policy_router.py -v` 全部通过

### 关联架构文档章节
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §9.1 PolicyRouter 完整 Python 实现
- `docs/prd/AI记忆系统架构设计文档.md` 脑启发映射表（前额叶 → Policy Layer）
- `docs/prd/memory-system/execution/00-overview.md` 代码目录结构规划

---

## D2：MemoryGovernor（记忆治理器）

### 任务编号
D2

### 任务名
MemoryGovernor 记忆治理器实现

### 目标
实现记忆的软删除、彻底删除、编辑（创建新节点 + 旧节点失效）、GDPR 级联删除与 PII 过滤，所有关键操作记录审计日志。

### 输入
- Neo4j 异步驱动（`AsyncDriver`）
- 审计日志回调函数（`audit_log_func: Optional[callable]`，可选）
- SQLAlchemy `AsyncSession`（用于 pgvector 向量移除，由调用方注入或通过依赖管理器获取）
- Redis 客户端（用于缓存清理，由调用方注入或通过依赖管理器获取）
- memory_id、user_id、new_content 等操作参数

### 输出
- 文件路径：`api/internal/service/memory/memory_governor.py`
- 关键类与函数签名：
  ```python
  class MemoryGovernor:
      def __init__(self, neo4j: AsyncDriver, audit_log_func: Optional[callable] = None) -> None: ...

      async def soft_delete_memory(self, memory_id: str, user_id: str) -> bool: ...

      async def hard_delete_memory(self, memory_id: str, user_id: str) -> bool: ...

      async def edit_memory(self, memory_id: str, user_id: str, new_content: str) -> Optional[str]: ...

      async def gdpr_delete(self, user_id: str) -> dict: ...

      async def filter_pii(self, content: str) -> str: ...

      async def _log_audit(self, action: str, user_id: str, **kwargs) -> None: ...
  ```
- 数据模型：`AuditEntry`（审计日志条目）、`PIIField`（PII 字段定义）

### 实现步骤
1. 定义 `AuditEntry`（Pydantic BaseModel）：`timestamp`、`action`、`user_id`、`memory_id: Optional[str]`、`details: dict`、`actor`（默认 "system"）。
2. 定义 `PIIField` 模型：`field_name`、`pii_type`（email/phone/ssn/name/address）、`masking_rule`（hash/redact/truncate，默认 hash）。
3. 实现 `MemoryGovernor.__init__(neo4j, audit_log_func=None)`，保存 Neo4j 驱动；`audit_log_func` 为空时使用默认 logger 回调。
4. 实现 `soft_delete_memory(memory_id, user_id)`：
   - 权限校验：Cypher 查询 `MemoryNode` 的 owner 是否为 user_id
   - 校验失败返回 False 并记录 warning
   - Cypher 设置 `n.is_active = false, n.deleted_at = datetime()`
   - 通过 `AsyncSession` 从 `user_memory` 表删除对应向量行（`DELETE FROM user_memory WHERE id = :memory_id`）
   - Redis 清理相关缓存（digest/profile/skill 缓存键）
   - 调用 `_log_audit(action="SOFT_DELETE_MEMORY", ...)`
   - 返回 True
5. 实现 `hard_delete_memory(memory_id, user_id)`：
   - 权限校验同上
   - Cypher `DETACH DELETE n`（物理删除节点及关联边）
   - 通过 `AsyncSession` 从 `user_memory` 表删除对应向量行
   - 调用 `_log_audit(action="HARD_DELETE_MEMORY", ...)`
   - 返回 True
6. 实现 `edit_memory(memory_id, user_id, new_content)`：
   - 权限校验同上，失败返回 None
   - 生成新节点 ID：`f"mem_{uuid.uuid4().hex[:12]}"`
   - Cypher：旧节点 `SET old.t_invalidated_at = datetime()` + 创建新 `MemoryNode` + `MERGE (old)-[:SUPERSEDED_BY]->(new)`
   - 通过 `AsyncSession` 向 `user_memory` 表写入新向量行、删除旧向量行
   - 调用 `_log_audit(action="EDIT_MEMORY", ..., details={"new_id": new_id})`
   - 返回新节点 ID
7. 实现 `gdpr_delete(user_id)`：
   - Neo4j：`MATCH (u:User {id: $user_id}) OPTIONAL MATCH (u)-[r]-(n) DETACH DELETE u, n`，统计删除节点/边数
   - pgvector：通过 `AsyncSession` 执行 `DELETE FROM user_memory WHERE user_id = :user_id`，统计删除行数
   - Redis：删除该用户所有缓存键（digest:{user_id}、profile:{user_id}、skill:pool:{user_id} 等）
   - MinIO：删除该用户的 Frozen 层归档对象（如配置）
   - 调用 `_log_audit(action="GDPR_DELETE", ..., details=stats)`
   - 返回删除统计 dict（`neo4j_nodes`、`neo4j_edges`、`pgvector_rows`、`redis_keys`）
8. 实现 `filter_pii(content)`：使用正则替换脱敏
   - 邮箱：`\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b` → `[EMAIL_REDACTED]`
   - 中国大陆手机号：`\b1[3-9]\d{9}\b` → `[PHONE_REDACTED]`
   - 身份证号：`\b\d{17}[\dXx]\b` → `[ID_REDACTED]`
   - 银行卡号：`\b\d{16,19}\b` → `[CARD_REDACTED]`
   - 返回脱敏后内容
9. 实现 `_log_audit(action, user_id, **kwargs)`：构造 `AuditEntry`，调用 `self._audit` 回调；回调异常时记录 error 日志但不抛出。
10. 注意：pgvector/Redis/MinIO 操作需通过依赖注入或调用方传入客户端，本类只负责 Neo4j 直接操作 + 协调调用其他客户端；具体依赖获取方式与 D3 DegradationManager 配合。

### 验收标准
- [ ] 软删除：`is_active=false` + `deleted_at` 设置，`user_memory` 表对应向量行删除，Redis 缓存清理，可恢复（节点保留）
- [ ] 彻底删除：`DETACH DELETE` 物理删除，节点不可恢复，`user_memory` 表对应向量行删除
- [ ] 编辑：创建新 `MemoryNode` 节点，旧节点 `t_invalidated_at` 设置，`SUPERSEDED_BY` 关系建立，返回新节点 ID
- [ ] 非授权用户操作（owner 不匹配）返回 False/None 并记录 warning
- [ ] GDPR 删除：Neo4j + pgvector + Redis + MinIO 全部清理，返回删除统计
- [ ] PII 过滤：邮箱/手机号/身份证号/银行卡号 4 类正则替换正确
- [ ] 所有操作记录审计日志（action/user_id/memory_id/details）
- [ ] `python -m py_compile internal/service/memory/memory_governor.py` 通过
- [ ] `python -m pytest test/internal/service/memory/test_memory_governor.py -v` 全部通过

### 关联架构文档章节
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §9.2 记忆治理（MemoryGovernor）
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §10 API 接口定义（DELETE/PUT 端点对应治理操作）
- `docs/prd/memory-system/execution/00-overview.md` Track D 依赖关系

---

## D3：DegradationManager（降级管理器）

### 任务编号
D3

### 任务名
DegradationManager 降级管理器实现

### 目标
作为记忆系统依赖健康检查的统一入口，启动时检查 Neo4j/PostgreSQL pgvector/Redis/Celery 连接，定期（每 30s）健康检查，提供检索策略、写入可用性、巩固可用性的查询接口，供 D1/D2/API 层决策降级路径。

### 输入
- Neo4j 异步驱动（`AsyncDriver`）
- SQLAlchemy `AsyncSession`（pgvector 向量检索，复用 PostgreSQL 连接）
- Redis 异步客户端（`aioredis.Redis`）
- Celery 应用实例（用于检查 broker 连通性）
- 健康检查间隔（默认 30s）

### 输出
- 文件路径：`api/internal/service/memory/degradation_manager.py`
- 关键类与函数签名：
  ```python
  class DegradationManager:
      def __init__(
          self,
          neo4j: AsyncDriver,
          db_session: AsyncSession,
          redis: aioredis.Redis,
          celery_app,
          check_interval_seconds: int = 30,
      ) -> None: ...

      async def start(self) -> None: ...
      async def stop(self) -> None: ...

      async def check_all(self) -> dict[str, bool]: ...

      def get_retrieval_strategy(self) -> str: ...
      def is_write_available(self) -> bool: ...
      def is_consolidation_available(self) -> bool: ...

      @property
      def memory_engine_enabled(self) -> bool: ...
  ```
- 状态字段：`_neo4j_ok`、`_pgvector_ok`、`_redis_ok`、`_celery_ok`、`memory_engine_enabled`

### 实现步骤
1. 实现 `DegradationManager.__init__`，保存四个依赖客户端与检查间隔，初始化四个状态标志为 False，`memory_engine_enabled = False`。
2. 实现 `start()`：立即执行一次 `check_all()`，然后启动一个 asyncio 后台任务（或 Celery beat 任务）每 30s 执行 `check_all()`；设置 `memory_engine_enabled = True`（若至少 Neo4j 可用）。
3. 实现 `stop()`：取消后台健康检查任务。
4. 实现 `check_all()`：
   - Neo4j 检查：执行 `RETURN 1` 简单查询，带 2s 超时，成功设 `_neo4j_ok=True`
   - pgvector 检查：执行 `SELECT 1` + 验证向量扩展（如 `SELECT extname FROM pg_extension WHERE extname='vector'`），带 2s 超时，成功设 `_pgvector_ok=True`
   - Redis 检查：调用 `ping()`，带 2s 超时，成功设 `_redis_ok=True`
   - Celery 检查：检查 broker 连通性（如 `celery_app.control.ping(timeout=2)`），成功设 `_celery_ok=True`
   - 任意检查异常时对应标志设 False 并记录 warning
   - 更新 `memory_engine_enabled`：Neo4j 可用即 True
   - 返回 `{"neo4j": bool, "pgvector": bool, "redis": bool, "celery": bool}`
5. 实现 `get_retrieval_strategy()`：
   - Neo4j + pgvector 都可用 → `"full"`
   - 仅 Neo4j 不可用 → `"vector_only"`
   - 仅 pgvector 不可用（PostgreSQL 向量检索不可用）→ `"graph_only"`
   - Neo4j + pgvector 都不可用但 Redis 可用 → `"digest_only"`
   - 全部不可用 → `"disabled"`
6. 实现 `is_write_available()`：Neo4j + pgvector 都可用时返回 True（写入需要图库 + 向量库双写）
7. 实现 `is_consolidation_available()`：Neo4j + Celery 都可用时返回 True（巩固引擎依赖图库扫描 + Celery 调度）
8. 实现 `memory_engine_enabled` 属性：返回当前引擎启用状态（Neo4j 可用为最低要求）
9. 提供单例获取方式（如模块级 `get_degradation_manager()` 函数），供 D1/D2/API 层注入。
10. 在应用启动钩子中调用 `start()`，关闭钩子中调用 `stop()`。

### 验收标准
- [ ] 启动时检查 Neo4j/pgvector/Redis/Celery 四个依赖，设置 `memory_engine_enabled` 标志
- [ ] 定期健康检查每 30s 执行一次
- [ ] `get_retrieval_strategy()` 在以下场景返回正确策略：
  - 全部可用 → `"full"`
  - Neo4j 单独故障 → `"vector_only"`
  - pgvector 单独故障（PostgreSQL 向量检索不可用）→ `"graph_only"`
  - Neo4j + pgvector 故障（Redis 可用）→ `"digest_only"`
  - 全部故障 → `"disabled"`
- [ ] `is_write_available()` 在 Neo4j+pgvector 都可用时返回 True，否则 False
- [ ] `is_consolidation_available()` 在 Neo4j+Celery 都可用时返回 True，否则 False
- [ ] 健康检查异常不导致服务崩溃（异常被捕获并记录日志）
- [ ] `python -m py_compile internal/service/memory/degradation_manager.py` 通过
- [ ] `python -m pytest test/internal/service/memory/test_degradation_manager.py -v` 全部通过

### 关联架构文档章节
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §9.1 降级逻辑（PolicyRouter 降级注释）
- `docs/prd/memory-system/execution/00-overview.md` 关键风险与对策（降级逻辑覆盖面广 → D3 作为统一入口）

---

## D4：图谱 API + 记忆 CRUD API

### 任务编号
D4

### 任务名
图谱查询 API 与记忆 CRUD API 追加实现

### 目标
在 `memory_handler.py` 中追加 8 个端点，提供记忆图谱聚类视图、子图查询、单条记忆详情/编辑/软删除/彻底删除/手动降权能力，对接 D2 MemoryGovernor 与 HebbianDecay。

### 输入
- D1 PolicyRouter、D2 MemoryGovernor、D3 DegradationManager 已实现
- HebbianDecay（Track B1）已实现，用于手动降权
- Neo4j 异步驱动（用于图谱查询）

### 输出
- 文件路径：`api/internal/handler/memory_handler.py`（追加，不新建文件）
- 关键端点签名：
  ```python
  @router.get("/memory/graph/{user_id}")
  async def get_memory_graph(user_id: str) -> dict: ...

  @router.get("/memory/graph/{user_id}/cluster/{type}")
  async def get_cluster_subgraph(user_id: str, type: str) -> dict: ...

  @router.get("/memory/{memory_id}")
  async def get_memory_detail(memory_id: str) -> dict: ...

  @router.put("/memory/{memory_id}")
  async def edit_memory(memory_id: str, body: EditMemoryRequest) -> dict: ...

  @router.delete("/memory/{memory_id}")
  async def soft_delete_memory(memory_id: str) -> dict: ...

  @router.delete("/memory/{memory_id}/hard")
  async def hard_delete_memory(memory_id: str) -> dict: ...

  @router.post("/memory/{memory_id}/decay")
  async def decay_memory(memory_id: str, body: DecayRequest) -> dict: ...
  ```
- 请求/响应模型：`EditMemoryRequest`、`DecayRequest`、`GraphResponse`、`ClusterSubgraphResponse`、`MemoryDetailResponse`

### 实现步骤
1. 在 `memory_handler.py` 顶部 import `MemoryGovernor`、`DegradationManager`、`HebbianDecay`，并通过依赖注入获取实例。
2. 定义请求/响应 Pydantic 模型：
   - `EditMemoryRequest`：`new_content: str`（min_length=1, max_length=10000）
   - `DecayRequest`：`decay_factor: float = 0.5`（0.0-1.0）、`reason: Optional[str]`
   - `GraphResponse`：`user_id`、`clusters: list[ClusterSummary]`、`total_nodes`
   - `ClusterSummary`：`memory_type`、`node_count`、`last_updated_at`
   - `ClusterSubgraphResponse`：`nodes: list[dict]`、`edges: list[dict]`、`truncated: bool`
   - `MemoryDetailResponse`：`memory_id`、`content`、`memory_type`、`confidence`、`source_conversation_id`、`created_at`、`last_accessed_at`、`related: list[RelatedNode]`
3. 实现 `GET /memory/graph/{user_id}`：
   - 查询 6 个 memory_type 区块（画像/偏好/关系/事件/项目/密钥）的节点数与最近更新时间
   - Cypher 按 `memory_type` 分组统计 `count(n)` 与 `max(n.updated_at)`
   - 返回 `GraphResponse`（6 个 ClusterSummary + total_nodes）
4. 实现 `GET /memory/graph/{user_id}/cluster/{type}`：
   - 按 type 查询该聚类的子图（节点 + 边）
   - 限制 ≤ 200 节点，超出按 `weight` 降序截断，设置 `truncated=True`
   - 返回 `ClusterSubgraphResponse`
5. 实现 `GET /memory/{memory_id}`：
   - Cypher 查询单条记忆详情 + 关联节点列表（关联强度 = 边 weight）
   - 返回 `MemoryDetailResponse`
6. 实现 `PUT /memory/{memory_id}`：
   - 接收 `EditMemoryRequest`
   - 调用 `MemoryGovernor.edit_memory(memory_id, current_user.id, body.new_content)`
   - 返回新节点 ID，失败（返回 None）抛 403/500
7. 实现 `DELETE /memory/{memory_id}`：
   - 调用 `MemoryGovernor.soft_delete_memory(memory_id, current_user.id)`
   - 返回 `{"deleted": true}`，失败返回 false
8. 实现 `DELETE /memory/{memory_id}/hard`：
   - 调用 `MemoryGovernor.hard_delete_memory(memory_id, current_user.id)`
   - 返回 `{"deleted": true}`
9. 实现 `POST /memory/{memory_id}/decay`：
   - 接收 `DecayRequest`
   - 调用 `HebbianDecay` 手动降低该记忆权重（按 `decay_factor` 衰减）
   - 返回 `{"memory_id", "new_weight"}`
10. 所有端点经过 D3 `DegradationManager.is_write_available()` 检查（写操作），不可用时返回 503。
11. 在路由注册处（router.py）挂载这些端点。

### 验收标准
- [ ] `GET /memory/graph/{user_id}` 返回 6 个 memory_type 区块，每个含节点数与最近更新时间
- [ ] `GET /memory/graph/{user_id}/cluster/{type}` 返回子图（节点+边），≤200 节点限制生效，超出时 `truncated=true`
- [ ] `GET /memory/{memory_id}` 返回完整详情（内容/类型/置信度/来源/时间/关联节点）
- [ ] `PUT /memory/{memory_id}` 调用 `MemoryGovernor.edit_memory`，返回新节点 ID
- [ ] `DELETE /memory/{memory_id}` 软删除成功，节点 `is_active=false`
- [ ] `DELETE /memory/{memory_id}/hard` 彻底删除，节点不可查
- [ ] `POST /memory/{memory_id}/decay` 手动降权，返回新权重
- [ ] 8 个端点集成测试通过（含权限校验、降级 503 场景）
- [ ] `python -m pytest test/internal/handler/test_memory_handler.py -v` 全部通过

### 关联架构文档章节
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §10 API 接口定义（端点表）
- `docs/prd/memory-system/03-consolidation-skill-policy-api.md` §10.1 FastAPI 路由定义
- `docs/prd/memory-system/execution/00-overview.md` 代码目录结构规划（memory_handler.py 统一 API handler）

---

## Track D 整体验收

- [ ] D1/D2/D3 三个服务文件 + D4 handler 追加全部完成
- [ ] `cd api && python -m py_compile internal/service/memory/policy_router.py internal/service/memory/memory_governor.py internal/service/memory/degradation_manager.py internal/handler/memory_handler.py` 通过
- [ ] `cd api && python -m pytest test/internal/service/memory/test_policy_router.py test/internal/service/memory/test_memory_governor.py test/internal/service/memory/test_degradation_manager.py test/internal/handler/test_memory_handler.py -v` 全部通过
- [ ] 降级路由在 Neo4j/pgvector/Redis/Celery 各种故障组合下正确切换
- [ ] GDPR 删除流程可在 30s 内完成（架构文档 P4 验收标准）
- [ ] 所有写操作经过 DegradationManager 检查，依赖不可用时返回 503
