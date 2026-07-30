# Track H：监控与集成测试 -- 任务执行文档

> **创建日期**：2026-07-09
> **Track**：H（监控与集成测试，H1-H5）
> **关联架构**：[01-data-models-and-write-path.md](../../01-data-models-and-write-path.md) | [02-storage-and-retrieval.md](../../02-storage-and-retrieval.md) | [03-consolidation-skill-policy-api.md](../../03-consolidation-skill-policy-api.md) | [00-overview.md](./00-overview.md)
> **执行原则**：监控指标覆盖 RED/USE 两套基线；集成测试覆盖全链路 happy path 与降级场景；指标埋点与功能开发同步推进。

---

## 0. 背景与目标

### 0.1 背景

Track A-F 完成了记忆系统的写入、存储检索、巩固、策略治理、技能池与前端可视化功能。Track H 在此基础上补齐生产可观测性与端到端测试能力，确保系统在二开完成后具备上线监控基线和回归测试基线。

### 0.2 目标

- **可观测性**：通过 Prometheus 指标覆盖四层监控（RED、USE、巩固、业务事件），所有关键操作可被指标化追踪。
- **健康检查**：提供 `/memory/health` 端点暴露各依赖（Neo4j、pgvector、Redis）状态，配合降级管理器。
- **E2E 测试**：覆盖写入 → 检索 → Digest → 巩固 → 图可视化 → CRUD → 降级 全链路。

### 0.3 任务总览

| 任务 | 内容 | 时机 | 前置条件 |
|---|---|---|---|
| H1 | Prometheus 指标定义 | T3 | Track B+C 完成 |
| H2 | MetricsCollector + observe_latency + 埋点 | T3 | H1 完成 |
| H3 | /metrics 端点 | T3 | H1 完成 |
| H4 | 健康检查 API | T4 | H2、D3 完成 |
| H5 | E2E 集成测试 | T5 | Track A-F 完成 |

---

## H1：Prometheus 指标定义

- **执行时机**：T3（Track B+C 完成后）
- **前置条件**：Track B（存储与检索）、Track C（巩固引擎）已完成，所有需要埋点的组件已存在
- **文件**：`api/internal/service/memory/metrics.py`
- **类型**：新建文件

### 任务内容

在 `api/internal/service/memory/metrics.py` 中定义 14 个 Prometheus 指标，覆盖四层监控：

#### Layer 1：RED（Rate / Errors / Duration）-- 写入与检索

| 指标名 | 类型 | Labels | 说明 |
|---|---|---|---|
| `memory_write_total` | Counter | - | 记忆写入总数 |
| `memory_write_latency_seconds` | Histogram | - | 记忆写入延迟 |
| `memory_retrieve_total` | Counter | - | 记忆检索总数 |
| `memory_retrieve_latency_seconds` | Histogram | - | 记忆检索延迟 |
| `memory_retrieve_results_count` | Histogram | - | 单次检索返回结果数量分布 |

#### Layer 2：USE（Utilization / Saturation / Errors）-- 存储层

| 指标名 | 类型 | Labels | 说明 |
|---|---|---|---|
| `memory_storage_tier_nodes` | Gauge | `tier` | 各存储层级节点数（hot/warm/cold/archive） |
| `memory_skill_count` | Gauge | - | 已涌现技能总数 |
| `memory_digest_cache_hit` | Gauge | - | Digest 缓存命中率 |

#### Layer 3：巩固与 LLM 调用

| 指标名 | 类型 | Labels | 说明 |
|---|---|---|---|
| `memory_consolidation_duration_seconds` | Histogram | - | 巩固阶段总耗时 |
| `memory_consolidation_errors_total` | Counter | - | 巩固阶段错误总数 |
| `memory_llm_tokens_total` | Counter | `model`, `operation` | LLM 调用 token 消耗（按模型与操作分类） |

#### Layer 4：业务事件

| 指标名 | 类型 | Labels | 说明 |
|---|---|---|---|
| `memory_conflict_detected_total` | Counter | `type` | 检测到的冲突总数（按冲突类型分类） |
| `memory_pii_filtered_total` | Counter | - | PII 过滤命中总数 |
| `memory_spread_activation_depth` | Histogram | - | 扩展激活遍历深度分布 |

### 实现要求

- 使用 `prometheus_client` 库
- Histogram 的 buckets 需合理设置（延迟类使用 `[0.01, 0.05, 0.1, 0.5, 1, 5, 10]`，结果数使用 `[0, 5, 10, 20, 50, 100]`）
- 指标命名遵循 Prometheus 命名规范（snake_case，带单位后缀）
- 模块级定义，全局单例

### 验收

- `api/internal/service/memory/metrics.py` 文件存在
- `cd api && python -c "from internal.service.memory.metrics import *"` 无报错
- 14 个指标均可通过 `prometheus_client` 默认 registry 注册
- Prometheus 可抓取指标（H3 完成后验证）

---

## H2：MetricsCollector + observe_latency

- **执行时机**：T3（H1 完成后）
- **前置条件**：H1 已完成，14 个指标已定义
- **文件**：`api/internal/service/memory/metrics.py`（同 H1 文件，追加）
- **类型**：追加实现 + 组件埋点

### 任务内容

#### MetricsCollector 静态方法

在 `metrics.py` 中实现 `MetricsCollector` 类，提供以下静态方法（封装对底层指标的更新）：

| 方法 | 对应指标 | 说明 |
|---|---|---|
| `record_write(latency_seconds)` | memory_write_total, memory_write_latency_seconds | 记录一次写入 |
| `record_retrieve(latency_seconds, results_count)` | memory_retrieve_total, memory_retrieve_latency_seconds, memory_retrieve_results_count | 记录一次检索 |
| `update_storage_tier(tier, count)` | memory_storage_tier_nodes | 更新某层级节点数 |
| `record_digest_cache(hit: bool)` | memory_digest_cache_hit | 记录 Digest 缓存命中/未命中 |
| `record_consolidation_phase(duration_seconds, error: bool)` | memory_consolidation_duration_seconds, memory_consolidation_errors_total | 记录巩固阶段 |
| `record_llm_tokens(model, operation, tokens)` | memory_llm_tokens_total | 记录 LLM token 消耗 |
| `record_conflict(conflict_type)` | memory_conflict_detected_total | 记录冲突检测 |
| `record_pii()` | memory_pii_filtered_total | 记录 PII 过滤 |
| `record_spread_depth(depth)` | memory_spread_activation_depth | 记录扩展激活深度 |

#### observe_latency 异步上下文管理器

实现 `observe_latency` 异步上下文管理器，用于自动测量异步操作耗时并记录到指定指标：

```python
from contextlib import asynccontextmanager
import time

@asynccontextmanager
async def observe_latency(record_fn):
    """自动测量异步操作耗时的上下文管理器

    用法：
        async with observe_latency(lambda s: MetricsCollector.record_write(s)):
            await ledger_writer.write(event)
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        record_fn(time.perf_counter() - start)
```

#### 各组件埋点

在以下组件中埋点调用 MetricsCollector：

| 组件 | 文件 | 埋点位置 | 指标 |
|---|---|---|---|
| SalienceScorer | `salience_scorer.py` | score() 调用 LLM 后 | memory_llm_tokens_total |
| LedgerWriter | `ledger_writer.py` | write() 完成后 | memory_write_total, memory_write_latency_seconds |
| MemoryRetriever | `retriever.py` | retrieve() 完成后 | memory_retrieve_total, memory_retrieve_latency_seconds, memory_retrieve_results_count |
| DigestManager | `digest_manager.py` | get_digest() 缓存判断处 | memory_digest_cache_hit |
| ConsolidationEngine | `consolidation_engine.py` | run_consolidation() 完成后 | memory_consolidation_duration_seconds, memory_consolidation_errors_total |
| ConflictDetector | `conflict_detector.py` | detect() 检出冲突时 | memory_conflict_detected_total |
| SkillEmergence | `skill_emergence.py` | detect_skills() 完成后 | memory_skill_count |

### 验收

- `MetricsCollector` 类与 9 个静态方法实现完整
- `observe_latency` 异步上下文管理器实现完整
- 各组件埋点位置正确，操作后指标正确更新
- 单元测试验证：执行一次写入后 `memory_write_total` 增加 1，延迟直方图有观测值
- 单元测试验证：执行一次检索后 `memory_retrieve_total` 增加 1，结果数直方图有观测值
- `cd api && python -m pytest test/internal/service/memory/test_metrics.py -v` 通过（若新建测试文件）

---

## H3：/metrics 端点

- **执行时机**：T3（H1 完成后）
- **前置条件**：H1 已完成，指标已注册到默认 registry
- **文件**：`api/internal/handler/metrics_handler.py`
- **类型**：新建文件 + 路由注册

### 任务内容

1. 新建文件 `api/internal/handler/metrics_handler.py`：
   - 实现 `GET /metrics` 端点
   - 返回 Prometheus 格式的指标文本（`Content-Type: text/plain; version=0.0.4`）
   - 使用 `prometheus_client.generate_latest()` 生成响应体
2. 在 `api/internal/router/router.py` 中注册路由：
   - 路径：`/metrics`
   - 方法：GET
   - 不需要鉴权（监控端点，由网络层隔离）

### 实现示例

```python
"""Prometheus 指标暴露端点"""
from fastapi import APIRouter
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response

router = APIRouter(tags=["metrics"])

@router.get("/metrics")
async def metrics():
    """返回 Prometheus 格式指标"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

### 验收

- `api/internal/handler/metrics_handler.py` 文件存在
- `GET /metrics` 路由已注册
- `curl http://localhost:8000/metrics` 返回 200，Content-Type 为 `text/plain; version=0.0.4`
- 返回内容包含 H1 定义的 14 个指标名
- `cd api && python -m pytest test/internal/handler/test_metrics_handler.py -v` 通过（若新建测试文件）

---

## H4：健康检查 API

- **执行时机**：T4（H2、D3 完成后）
- **前置条件**：H2 已完成（metrics 可用），D3（DegradationManager）已完成
- **文件**：`api/internal/handler/memory_handler.py`（追加）
- **类型**：追加端点

### 任务内容

在 `api/internal/handler/memory_handler.py` 中追加健康检查端点：

1. `GET /memory/health`：返回 `HealthResponse`
2. `HealthResponse` 模型字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | str | 整体状态（healthy / degraded / unhealthy） |
| `version` | str | 记忆系统版本号 |
| `neo4j` | str | Neo4j 连接状态（healthy / unreachable） |
| `pgvector` | str | pgvector 连接状态（PostgreSQL 向量检索可用性） |
| `redis` | str | Redis 连接状态 |
| `uptime_seconds` | float | 服务运行时长（秒） |

3. 实现：
   - 调用 `DegradationManager`（D3 产物）获取各依赖状态
   - 整体 status 取最差状态：任一依赖 unreachable → degraded；多数 unreachable → unhealthy
   - version 从配置或常量读取
   - uptime_seconds 从服务启动时间计算

### 实现示例

```python
class HealthResponse(BaseModel):
    status: str
    version: str
    neo4j: str
    pgvector: str
    redis: str
    uptime_seconds: float

@router.get("/memory/health", response_model=HealthResponse)
async def memory_health(degradation_manager: DegradationManager = Depends(...)):
    neo4j_status = await degradation_manager.check_neo4j()
    pgvector_status = await degradation_manager.check_pgvector()
    redis_status = await degradation_manager.check_redis()
    deps = [neo4j_status, pgvector_status, redis_status]
    if all(s == "healthy" for s in deps):
        status = "healthy"
    elif sum(s == "unreachable" for s in deps) >= 2:
        status = "unhealthy"
    else:
        status = "degraded"
    return HealthResponse(
        status=status,
        version=MEMORY_SYSTEM_VERSION,
        neo4j=neo4j_status,
        pgvector=pgvector_status,
        redis=redis_status,
        uptime_seconds=time.time() - SERVICE_START_TIME,
    )
```

### 验收

- `GET /memory/health` 端点可访问
- 各依赖状态正确反映（启动 Docker compose 后 neo4j/pgvector/redis 均为 healthy）
- 模拟某依赖挂掉（如停止 Redis 容器）后，对应字段变为 unreachable，整体 status 变为 degraded
- `curl http://localhost:8000/memory/health` 返回正确 JSON
- `cd api && python -m pytest test/internal/handler/test_memory_handler.py::test_health -v` 通过

---

## H5：E2E 集成测试

- **执行时机**：T5（Track A-F 完成后）
- **前置条件**：Track A-F 全部完成，Track G 清理完成（无旧代码干扰），Docker compose 可启动 Neo4j/PostgreSQL pgvector/Redis
- **文件**：`api/test/internal/service/memory/test_e2e_memory.py`
- **类型**：新建测试文件

### 任务内容

在 `api/test/internal/service/memory/test_e2e_memory.py` 中实现全链路 E2E 集成测试，覆盖以下 7 个场景：

#### 场景 1：写入（FULL 路径）

```python
async def test_e2e_write_full_path():
    """写入：POST /memory/write（FULL 路径）→ 验证 Neo4j 节点 + pgvector 向量"""
    # 1. 构造 MemoryEvent，POST /memory/write
    # 2. 验证返回 memory_id
    # 3. 查询 Neo4j：对应 MemoryNode 节点存在，字段正确
    # 4. 查询 user_memory 表：对应向量行存在，embedding 列非空，metadata 包含 memory_id
```

#### 场景 2：检索

```python
async def test_e2e_retrieve():
    """检索：POST /memory/retrieve → 验证返回结果"""
    # 1. 写入若干条记忆
    # 2. POST /memory/retrieve 带查询
    # 3. 验证返回 RetrievalResult 列表
    # 4. 验证结果相关性（包含预期记忆）
    # 5. 验证 spread_activation 生效（返回相关联的记忆）
```

#### 场景 3：Digest

```python
async def test_e2e_digest():
    """Digest：GET /memory/digest/{user_id} → 验证 Digest 内容"""
    # 1. 写入若干条记忆
    # 2. GET /memory/digest/{user_id}
    # 3. 验证返回 Digest 结构（主题、时间范围、关键记忆）
    # 4. 第二次请求验证缓存命中
```

#### 场景 4：巩固

```python
async def test_e2e_consolidate():
    """巩固：POST /memory/consolidate/{user_id} → 验证巩固报告"""
    # 1. 写入若干条记忆（含可合并的相似记忆、可涌现的技能模式）
    # 2. POST /memory/consolidate/{user_id}
    # 3. 验证返回巩固报告（合并数、涌现技能数、冲突数）
    # 4. 验证 Neo4j 中相似记忆已合并（节点数减少）
    # 5. 验证 SkillLabel 节点已创建
```

#### 场景 5：图可视化

```python
async def test_e2e_graph():
    """图可视化：GET /memory/graph/{user_id} → 验证聚类数据"""
    # 1. 写入若干条记忆（含聚类关系）
    # 2. GET /memory/graph/{user_id}
    # 3. 验证返回 GraphData 结构（nodes, edges, clusters）
    # 4. 验证节点数 ≤ 200（LOD 限制）
    # 5. 验证聚类标签存在
```

#### 场景 6：CRUD

```python
async def test_e2e_crud():
    """CRUD：PUT/DELETE /memory/{id} → 验证编辑/软删除/彻底删除"""
    # 1. 写入一条记忆
    # 2. PUT /memory/{id}：修改 content
    # 3. 验证 Neo4j 节点 content 已更新，updated_at 已变更
    # 4. DELETE /memory/{id}?hard=false：软删除
    # 5. 验证 Neo4j 节点 is_deleted=true，但节点仍存在
    # 6. DELETE /memory/{id}?hard=true：彻底删除
    # 7. 验证 Neo4j 节点不存在，user_memory 表对应向量行已删除
```

#### 场景 7：降级

```python
async def test_e2e_degradation():
    """降级：模拟 Neo4j 挂掉 → 验证 vector_only 降级"""
    # 1. 正常写入若干条记忆
    # 2. 停止 Neo4j 容器（或 mock 连接失败）
    # 3. POST /memory/retrieve
    # 4. 验证 DegradationManager 切换到 vector_only 模式
    # 5. 验证返回结果仍来自 pgvector（无图扩展激活）
    # 6. 验证 /memory/health 中 neo4j 状态为 unreachable，整体 status 为 degraded
    # 7. 恢复 Neo4j 容器
    # 8. 验证 DegradationManager 自动恢复到 full 模式
```

### 测试要求

- 使用 pytest + asyncio
- 测试前置 fixture：启动 Docker compose（Neo4j/PostgreSQL pgvector/Redis），清空数据库
- 每个测试用例独立，测试间通过 fixture 清理数据
- 测试用例按场景顺序执行（场景 1 的写入数据可被后续场景复用，但需保证独立性）
- 降级测试需能控制 Neo4j 容器启停（或使用 mock）

### 验收

- `api/test/internal/service/memory/test_e2e_memory.py` 文件存在
- 7 个场景测试用例实现完整
- `cd api && python -m pytest test/internal/service/memory/test_e2e_memory.py -v` 全部通过
- 全链路测试通过：写入 → 检索 → Digest → 巩固 → 图可视化 → CRUD → 降级 均正常

---

## 2. 全局验收（Track H 完成后）

执行以下检查确认 Track H 全部完成：

```bash
# 指标定义与埋点
cd api && python -c "from internal.service.memory.metrics import MetricsCollector, observe_latency; print('OK')"

# /metrics 端点
curl -s http://localhost:8000/metrics | grep -E "memory_write_total|memory_retrieve_total|memory_storage_tier_nodes|memory_consolidation_duration_seconds|memory_conflict_detected_total|memory_pii_filtered_total"

# 健康检查
curl -s http://localhost:8000/memory/health | python -m json.tool

# E2E 测试
cd api && python -m pytest test/internal/service/memory/test_e2e_memory.py -v

# 全量测试回归
cd api && python -m pytest test/internal/ -v
```

### 完成标志

- `/metrics` 端点返回 14 个指标定义
- 各组件埋点后指标正确更新
- `/memory/health` 正确反映各依赖状态
- E2E 集成测试 7 个场景全部通过
- 全量后端测试无回归
