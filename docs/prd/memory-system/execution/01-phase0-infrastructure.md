# Phase 0：基础设施 -- 任务执行文档

> **创建日期**：2026-07-09
> **Track**：Phase 0（基础设施，I1-I6）
> **关联架构**：[01-data-models-and-write-path.md](../../01-data-models-and-write-path.md) | [02-storage-and-retrieval.md](../../02-storage-and-retrieval.md) | [03-consolidation-skill-policy-api.md](../../03-consolidation-skill-policy-api.md) | [00-overview.md](./00-overview.md)
> **执行原则**：二开阶段，无生产环境，不做向后兼容；所有新增组件需可独立验证；配置项支持环境变量覆盖。
> **前置条件**：无（Phase 0 为所有后续 Track 的前置）

---

## 0. 背景与总体说明

### 0.1 背景

项目处于二开阶段，无生产数据。现有 `docker/docker-compose.yaml` 已包含以下服务：`llmops-ui`、`llmops-api`、`llmops-celery`、`llmops-redis`、`llmops-db`（PostgreSQL 18 + pgvector）、`llmops-nginx`。

新记忆系统需要：
- **Neo4j 5.x**：承载时序知识图谱（TKG），节点（Episode/Entity/Community）与边（双时间模型）。
- **PostgreSQL pgvector**：承载记忆语义向量（`user_memory.embedding` 列，Vector(1536)，HNSW 索引）。知识库向量也在同一 PG 实例中（`knowledge_segment.embedding` 列）。
- **MinIO**：S3 兼容冷存储，归档低权重记忆。

现有 Celery 实例（`llmops-celery`，镜像 `MODE=celery`）已运行，记忆系统复用该实例，仅新增 beat schedule 与任务路由。

### 0.2 现有代码风格约定

执行者必须遵循现有代码风格：
- 配置读取：参考 `api/config/config.py` 的 `_get_env` / `_get_bool_env` 模式（从环境变量读取，带默认值）。
- Celery 初始化：参考 `api/internal/extension/celery_extension.py` 的 `init_app(app)` + `FlaskTask` 包装器模式。
- 数据模型：Pydantic v2 `BaseModel`（`api/internal/entity/*.py` 已广泛使用）。
- Docker Compose：无显式 `networks:` 段，服务默认加入 compose 自动创建的 bridge 网络；新服务沿用此约定。

### 0.3 依赖关系

```
I1 (docker-compose)  ──┐
                       ├──> I3 (Celery app)        ──> 后续所有 Track
I2 (配置类)          ──┤
                       ├──> I4 (Neo4j schema)
                       ├──> I5 (pgvector 向量列就绪验证)
                       └──> I6 (数据模型)          ──> 后续所有 Track
```

I1-I6 之间无强串行依赖，可并行执行；但 I3/I4/I5/I6 引用的配置项需与 I2 保持一致。

---

## I1：docker-compose 新增服务

### 目标

在 `docker/docker-compose.yaml` 中新增 `neo4j`、`minio` 两个服务（向量检索复用现有 `llmops-db` PostgreSQL + pgvector 扩展，无需新增容器），加入现有默认网络，配置端口映射、持久化卷与 healthcheck，确保 `llmops-api` 可通过服务名访问二者。

### 输入

- **前置任务**：无
- **依赖文件**：
  - `docker/docker-compose.yaml`（现有 7 服务配置）
  - `api/.env`（现有环境变量文件，新服务的连接信息将在此补充，由 I2 任务读取）

### 输出

- **修改文件**：`docker/docker-compose.yaml`（新增 2 个 service 段）
- **新增卷目录**（由 compose 自动创建，无需手动建）：
  - `./volumes/neo4j/data`、`./volumes/neo4j/logs`
  - `./volumes/minio/data`
- **关键配置签名**（compose service 片段）：

```yaml
services:
  llmops-neo4j:
    image: neo4j:5-community
    container_name: llmops-neo4j
    ports: ["7474:7474", "7687:7687"]
    environment:
      NEO4J_AUTH: neo4j/openagent
    healthcheck:
      test: ["CMD-SHELL", "wget -O /dev/null -q http://localhost:7474 || exit 1"]

  llmops-minio:
    image: minio/minio:latest
    container_name: llmops-minio
    ports: ["9000:9000", "9001:9001"]
    environment:
      MINIO_ROOT_USER: openagent
      MINIO_ROOT_PASSWORD: openagent123
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
```

### 实现步骤

1. **读取现有 compose**：打开 `docker/docker-compose.yaml`，确认现有服务名前缀为 `llmops-`，无显式 `networks:` 顶层段（服务使用默认网络）。

2. **新增 `llmops-neo4j` 服务**（追加到 `services:` 下）：
   - `image: neo4j:5-community`
   - `container_name: llmops-neo4j`
   - `restart: always`
   - 端口映射：`"7474:7474"`（HTTP/Bolt 浏览器）、`"7687:7687"`（Bolt 协议）；建议绑定 `127.0.0.1:` 前缀以与现有服务一致（仅本机访问，nginx/api 内部走服务名）。
   - `environment`：
     - `NEO4J_AUTH: neo4j/openagent`（用户名 `neo4j`，密码 `openagent`）
     - `NEO4J_PLUGINS: '["apoc"]'`（APOC 库，供后续复杂 Cypher 用，可选但推荐）
   - `volumes`：
     - `./volumes/neo4j/data:/data`
     - `./volumes/neo4j/logs:/logs`
   - `healthcheck`：
     - `test: ["CMD-SHELL", "wget -O /dev/null -q http://localhost:7474 || exit 1"]`（neo4j 镜像无 curl，用 wget）
     - `interval: 10s`、`timeout: 5s`、`retries: 10`、`start_period: 40s`

3. **新增 `llmops-minio` 服务**：
   - `image: minio/minio:latest`
   - `container_name: llmops-minio`
   - `restart: always`
   - 端口：`"9000:9000"`（S3 API）、`"9001:9001"`（管理控制台）。
   - `environment`：
     - `MINIO_ROOT_USER: openagent`
     - `MINIO_ROOT_PASSWORD: openagent123`
   - `command: ["server", "/data", "--console-address", ":9001"]`
   - `volumes`：
     - `./volumes/minio/data:/data`
   - `healthcheck`：
     - `test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]`
     - `interval: 15s`、`timeout: 5s`、`retries: 6`、`start_period: 15s`
   - 说明：minio 镜像内置 curl，可直接使用。

4. **更新 `llmops-api` 依赖**（可选但推荐）：
   - 在 `llmops-api` 的 `depends_on` 下追加：
     - `llmops-neo4j: { condition: service_healthy }`
     - `llmops-minio: { condition: service_started }`（minio 健康检查较松，started 即可）
   - 在 `llmops-api` 的 `environment` 下追加（供 I2 配置类读取）：
     - `NEO4J_URI: bolt://llmops-neo4j:7687`
     - `NEO4J_USER: neo4j`
     - `NEO4J_PASSWORD: openagent`
     - `MINIO_ENDPOINT: llmops-minio:9000`
     - `MINIO_ACCESS_KEY: openagent`
     - `MINIO_SECRET_KEY: openagent123`
   - 说明：向量检索复用现有 `llmops-db` PostgreSQL，需确认其镜像已内置 `pgvector` 扩展并在 `init.sql` 中执行 `CREATE EXTENSION IF NOT EXISTS vector`。

5. **同步更新 `llmops-celery`**：在 `llmops-celery` 的 `environment` 追加与 `llmops-api` 相同的 `NEO4J_*`、`MINIO_*` 环境变量（celery worker 需访问同一基础设施）。

6. **校验 compose 语法**：执行 `docker compose -f docker/docker-compose.yaml config` 确认无语法错误。

### 验收标准

- [ ] `docker compose -f docker/docker-compose.yaml config` 无报错输出。
- [ ] `docker compose -f docker/docker-compose.yaml up -d llmops-neo4j llmops-minio` 两个容器均 `healthy`（neo4j 约 40s 后健康）。
- [ ] 浏览器访问 `http://localhost:7474` 可见 Neo4j Browser，用 `neo4j/openagent` 可登录。
- [ ] `curl http://localhost:9000/minio/health/live` 返回 200。
- [ ] 从 `llmops-api` 容器内 `ping llmops-neo4j` / `llmops-minio` 可解析（服务名互通）。
- [ ] 两服务重启后数据持久化（卷挂载生效）。
- [ ] `llmops-db` PostgreSQL 中 `SELECT extname FROM pg_extension WHERE extname='vector';` 返回 `vector`（pgvector 扩展就绪）。

### 关联架构文档章节

- [02-storage-and-retrieval.md](../../02-storage-and-retrieval.md) §存储基础设施（Neo4j TKG / PostgreSQL pgvector 向量 / 冷存储）
- [00-overview.md](./00-overview.md) §代码目录结构规划

---

## I2：记忆系统配置类

### 目标

创建 `api/internal/config/memory_settings.py`，使用 Pydantic `BaseSettings` 封装记忆系统全部配置组（salience、pgvector、neo4j、llm、write、decay、retrieval、digest、consolidation、skill、spread、funnel、cold_storage、celery），所有配置项支持从环境变量读取并带默认值，作为后续所有 Track 的单一配置来源。

### 输入

- **前置任务**：I1（compose 提供的环境变量名需与此处一致）
- **依赖文件**：
  - `api/requirements.txt`（已含 `pydantic==2.12.5`、`pydantic-settings==2.13.1`）
  - `api/config/config.py`（现有 `_get_env` 模式参考）
  - `api/.env.example`（环境变量命名约定参考）

### 输出

- **新增文件**：`api/internal/config/memory_settings.py`
- **关键类签名**：

```python
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SalienceConfig(BaseModel): ...
class PgvectorConfig(BaseModel): ...
class Neo4jConfig(BaseModel): ...
class LLMConfig(BaseModel): ...
class WriteConfig(BaseModel): ...
class DecayConfig(BaseModel): ...
class RetrievalConfig(BaseModel): ...
class DigestConfig(BaseModel): ...
class ConsolidationConfig(BaseModel): ...
class SkillConfig(BaseModel): ...
class SpreadConfig(BaseModel): ...
class FunnelConfig(BaseModel): ...
class ColdStorageConfig(BaseModel): ...
class CeleryConfig(BaseModel): ...

class Settings(BaseSettings):
    """记忆系统统一配置入口"""
    model_config = SettingsConfigDict(env_prefix="MEMORY_", env_nested_delimiter="__", extra="ignore")
    salience: SalienceConfig = Field(default_factory=SalienceConfig)
    pgvector: PgvectorConfig = Field(default_factory=PgvectorConfig)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    write: WriteConfig = Field(default_factory=WriteConfig)
    decay: DecayConfig = Field(default_factory=DecayConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)
    consolidation: ConsolidationConfig = Field(default_factory=ConsolidationConfig)
    skill: SkillConfig = Field(default_factory=SkillConfig)
    spread: SpreadConfig = Field(default_factory=SpreadConfig)
    funnel: FunnelConfig = Field(default_factory=FunnelConfig)
    cold_storage: ColdStorageConfig = Field(default_factory=ColdStorageConfig)
    celery: CeleryConfig = Field(default_factory=CeleryConfig)

settings = Settings()  # 模块级单例
```

### 实现步骤

1. **新建目录与文件**：创建 `api/internal/config/` 目录（若不存在）及 `__init__.py`（空文件），再创建 `memory_settings.py`。

2. **定义各子配置类**（每个类为 `BaseModel`，字段带默认值；环境变量通过 `Settings` 的 `env_prefix` + 嵌套分隔符映射，或子类字段直接用 `validation_alias` 绑定具体环境变量名）。各子类字段定义如下：

   - **SalienceConfig**：
     ```python
     class SalienceConfig(BaseModel):
         weights: dict[str, float] = Field(default={"emotion": 0.25, "novelty": 0.20, "goal_relevance": 0.25, "outcome_impact": 0.20, "rehearsal": 0.10})
         thresholds: dict[str, float] = Field(default={"full": 0.7, "summary": 0.3})
     ```

   - **PgvectorConfig**：向量列在 `user_memory.embedding`（Vector(1536)），索引类型 HNSW，复用现有 PostgreSQL 连接（无需独立 host/port）。
     ```python
     class PgvectorConfig(BaseModel):
         table_name: str = Field(default="user_memory")
         embedding_column: str = Field(default="embedding")
         embedding_dim: int = Field(default=1536)
         index_type: str = Field(default="hnsw")
         # HNSW 索引参数（与 init.sql / Alembic 迁移保持一致）
         m: int = Field(default=16)
         ef_construction: int = Field(default=64)
         distance_metric: str = Field(default="cosine")  # <=> 余弦距离
     ```

   - **Neo4jConfig**：
     ```python
     class Neo4jConfig(BaseModel):
         uri: str = Field(default="bolt://localhost:7687", validation_alias="NEO4J_URI")
         user: str = Field(default="neo4j", validation_alias="NEO4J_USER")
         password: str = Field(default="openagent", validation_alias="NEO4J_PASSWORD")
     ```

   - **LLMConfig**：
     ```python
     class LLMConfig(BaseModel):
         model: str = Field(default="gpt-4o-mini")
         temperature: float = Field(default=0.0)
         request_timeout_s: int = Field(default=30)
     ```

   - **WriteConfig**：
     ```python
     class WriteConfig(BaseModel):
         class EntityResolution(BaseModel):
             merge_threshold: float = 0.75
             edit_distance_threshold: int = 3
             vector_weight: float = 0.4
             bm25_weight: float = 0.3
             llm_judge_weight: float = 0.3
         entity_resolution: EntityResolution = Field(default_factory=EntityResolution)
     ```

   - **DecayConfig**：
     ```python
     class DecayConfig(BaseModel):
         lambda_decay: float = 0.05
         alpha_cooccurrence: float = 0.2
         beta_interference: float = 0.15
         cooccurrence_window_hours: int = 168
         hot_threshold: float = 0.7
         warm_threshold: float = 0.3
     ```

   - **RetrievalConfig**：
     ```python
     class RetrievalConfig(BaseModel):
         w_cosine: float = 0.4
         w_bm25: float = 0.3
         w_graph: float = 0.3
         time_decay_half_life_hours: float = 168.0
         early_stop_top_k: int = 10
         early_stop_score_gap: float = 0.15
     ```

   - **DigestConfig**：
     ```python
     class DigestConfig(BaseModel):
         cache_ttl_seconds: int = 300
         cache_key_prefix: str = "memory:digest:"
         max_tokens: int = 2000
         profile_max_items: int = 5
         skills_max_items: int = 10
         events_max_items: int = 10
         tasks_max_items: int = 5
         render_model: str = "gpt-4o-mini"
         render_temperature: float = 0.0
     ```

   - **ConsolidationConfig**：
     ```python
     class ConsolidationConfig(BaseModel):
         episode_age_days: int = 7
         semantic_min_examples: int = 3
         semantic_similarity_threshold: float = 0.8
         conflict_check_batch_size: int = 50
         conflict_similarity_threshold: float = 0.85
         cold_threshold: float = 0.3
         merge_similarity_threshold: float = 0.9
         llm_model: str = "gpt-4o-mini"
         llm_temperature: float = 0.0
     ```

   - **SkillConfig**：
     ```python
     class SkillConfig(BaseModel):
         min_pattern_frequency: int = 3
         pattern_window_days: int = 30
         maturity_active_threshold: float = 0.7
         maturity_stale_threshold: float = 0.2
         stale_days: int = 90
         extraction_model: str = "gpt-4o-mini"
         extraction_temperature: float = 0.2
     ```

   - **SpreadConfig**：
     ```python
     class SpreadConfig(BaseModel):
         max_hops: int = 3
         activation_decay: float = 0.5
         min_activation: float = 0.01
         top_k: int = 20
     ```

   - **FunnelConfig**：
     ```python
     class FunnelConfig(BaseModel):
         dedup_similarity_threshold: float = 0.85
         evidence_max_items: int = 30
         early_stop_confidence: float = 0.9
         early_stop_min_items: int = 3
         llm_model: str = "gpt-4o-mini"
         llm_temperature: float = 0.0
         llm_max_tokens: int = 2000
     ```

   - **ColdStorageConfig**：
     ```python
     class ColdStorageConfig(BaseModel):
         s3_bucket: str = "openagent-cold-memory"
         s3_prefix: str = "cold-memories/"
         aws_region: str = "us-east-1"
         threshold_weight: float = 0.5
         min_support: int = 3
     ```
     > 注：MinIO 作为 S3 兼容存储，`endpoint` 由调用方从 `MINIO_ENDPOINT` 读取后注入 client，此处仅存 bucket 级配置。

   - **CeleryConfig**：
     ```python
     class CeleryConfig(BaseModel):
         broker_url: str = Field(default="redis://localhost:6379/1", validation_alias="CELERY_BROKER_URL")
         result_backend: str = Field(default="redis://localhost:6379/2", validation_alias="CELERY_RESULT_BACKEND")
     ```

3. **定义 `Settings` 主类**：
   - 继承 `BaseSettings`。
   - `model_config = SettingsConfigDict(env_prefix="MEMORY_", env_nested_delimiter="__", extra="ignore")`：允许通过 `MEMORY_PGVECTOR__EMBEDDING_DIM` 等覆盖嵌套字段。
   - 14 个子配置字段，均带 `default_factory`。
   - 子类中使用 `validation_alias` 绑定 I1 compose 注入的裸环境变量名（如 `NEO4J_URI`），避免与 `env_prefix` 冲突（`validation_alias` 优先级高于 prefix）。pgvector 复用现有 PostgreSQL 连接，无需独立环境变量。

4. **模块级单例**：文件末尾导出 `settings = Settings()`，供其他模块 `from internal.config.memory_settings import settings` 使用。

5. **补充依赖**：确认 `pydantic-settings` 在 `api/requirements.txt`（已确认存在），无需新增。

6. **补充环境变量样例**：在 `api/.env.example` 末尾追加 `NEO4J_URI`、`MINIO_ENDPOINT` 等样例条目（注释说明默认值）。

### 验收标准

- [ ] `cd api && python -c "from internal.config.memory_settings import settings; print(settings.pgvector.table_name, settings.neo4j.uri, settings.salience.weights)"` 正常输出默认值。
- [ ] 设置 `MEMORY_PGVECTOR__EMBEDDING_DIM=768` 后，`settings.pgvector.embedding_dim` 返回 `768`（嵌套覆盖生效）。
- [ ] 设置 `MEMORY_SALIENCE__WEIGHTS='{"emotion":0.3}'` 后，`settings.salience.weights["emotion"]` 为 `0.3`（嵌套覆盖生效）。
- [ ] `python -m py_compile api/internal/config/memory_settings.py` 无语法错误。
- [ ] 所有 14 个子配置组的默认值与本任务规格表完全一致。

### 关联架构文档章节

- [01-data-models-and-write-path.md](../../01-data-models-and-write-path.md) §SalienceScorer 五因子权重 / §写入路径阈值
- [02-storage-and-retrieval.md](../../02-storage-and-retrieval.md) §检索权重 / §衰减参数 / §漏斗配置 / §Digest 配置
- [03-consolidation-skill-policy-api.md](../../03-consolidation-skill-policy-api.md) §巩固参数 / §技能涌现阈值 / §冷存储阈值

---

## I3：Celery app 初始化

### 目标

复用现有 `llmops-celery` 实例（同一镜像 `MODE=celery`），为记忆系统新增 Celery beat schedule 与任务路由配置，注册两个定时任务（daily-consolidation、weight-scan）和一条任务路由（`tasks.consolidation_tasks.*` → `consolidation` 队列）。

> **决策说明**：不新建独立 Celery 实例。现有 `api/internal/extension/celery_extension.py` 已通过 `init_app(app)` 创建 Celery 实例并从 `app.config["CELERY"]` 读取配置。记忆系统通过向该配置字典追加 `beat_schedule` 与 `task_routes`、`task_queues` 实现扩展，无需独立 `celery_app.py` 模块。任务规格中提及的 `api/internal/celery_app.py` 不再单独创建，改为在 `config.py` 的 `CELERY` 字典内扩展。

### 输入

- **前置任务**：I1（celery 容器需能访问 redis）、I2（`CeleryConfig` 提供 broker/result_backend，但实际 broker 仍走现有 `app.config["CELERY"]["broker_url"]`）
- **依赖文件**：
  - `api/internal/extension/celery_extension.py`（现有 Celery 初始化入口）
  - `api/config/config.py`（现有 `CELERY` 配置字典，第 142-170 行）
  - `api/internal/task/`（现有任务目录，新增 `consolidation_tasks.py` 由 Track C 实现，本任务仅注册调度）

### 输出

- **修改文件**：`api/config/config.py`（在 `self.CELERY` 字典中追加 `beat_schedule`、扩展 `task_queues`、扩展 `task_routes`）
- **关键配置签名**（追加到 `Config.__init__` 的 `self.CELERY` 字典）：

```python
from celery.schedules import crontab
from kombu import Queue

self.CELERY = {
    # ... 现有 broker_url / result_backend / 等 ...
    "task_queues": (
        Queue("celery"),
        Queue("mail"),
        Queue("consolidation"),   # 新增：巩固任务队列
    ),
    "task_routes": {
        "internal.task.email_task.send_verification_email_task": {"queue": "mail"},
        "tasks.consolidation_tasks.*": {"queue": "consolidation"},   # 新增
    },
    "beat_schedule": {   # 新增整个段
        "daily-consolidation": {
            "task": "tasks.consolidation_tasks.run_daily_consolidation",
            "schedule": crontab(hour=3, minute=0),
        },
        "weight-scan": {
            "task": "tasks.consolidation_tasks.run_weight_scan",
            "schedule": crontab(hour="*/6", minute=30),
        },
    },
}
```

### 实现步骤

1. **确认现有 Celery 配置位置**：打开 `api/config/config.py`，定位 `self.CELERY = {...}`（约第 142 行）。现有配置已含 `broker_url`、`result_backend`、`task_default_queue`、`task_queues`（含 `celery`、`mail` 两个队列）、`task_routes`（含 email 路由）。

2. **新增 `consolidation` 队列**：在 `task_queues` 元组中追加 `Queue("consolidation")`。注意 `Queue` 已在文件顶部 `from kombu import Queue` 导入。

3. **新增任务路由**：在 `task_routes` 字典中追加 `"tasks.consolidation_tasks.*": {"queue": "consolidation"}`。
   - 任务名前缀约定：Track C 实现 `consolidation_tasks.py` 时，任务用 `@celery_app.task(name="tasks.consolidation_tasks.run_daily_consolidation")` 显式命名（与路由前缀一致）。

4. **新增 `beat_schedule`**：
   - 在 `self.CELERY` 字典中新增 `"beat_schedule"` 键。
   - 顶部 `from celery.schedules import crontab`（若未导入则添加）。
   - `daily-consolidation`：`crontab(hour=3, minute=0)`，每日 03:00 执行 `run_daily_consolidation`。
   - `weight-scan`：`crontab(hour="*/6", minute=30)`，每 6 小时的第 30 分钟执行 `run_weight_scan`（即 00:30、06:30、12:30、18:30）。

5. **启用 beat（compose 层）**：
   - 现有 `llmops-celery` 容器仅运行 worker（`MODE=celery` 启动 worker）。beat scheduler 需独立进程。
   - **方案**：在 `docker/docker-compose.yaml` 新增一个 `llmops-celery-beat` 服务，复用同一镜像，`MODE=celery-beat`，运行 `celery -A app.celery beat`。
   - 修改 `api/docker/entrypoint.sh`：增加 `MODE=celery-beat` 分支，启动 `celery -A app.celery beat --loglevel=info`（具体 app 名称以现有 entrypoint 为准，需阅读 `api/docker/entrypoint.sh` 确认 celery app 挂载路径）。
   - 若不想新增容器，可临时由 `llmops-celery` 同时跑 worker + beat（`celery -A app.celery worker -B`），但生产不建议；二开阶段可接受。**本任务采用新增 `llmops-celery-beat` 容器方案**，与 I1 同步在 compose 中添加。

6. **占位任务模块**：创建 `api/internal/task/consolidation_tasks.py` 占位文件（仅含两个空函数签名 + `@celery_app.task` 装饰器），确保 beat 启动时任务可被导入。实际实现由 Track C（C4）完成。

   ```python
   # api/internal/task/consolidation_tasks.py（占位，Track C 实现）
   from internal.extension.celery_extension import celery_app  # 路径以实际为准

   @celery_app.task(name="tasks.consolidation_tasks.run_daily_consolidation")
   def run_daily_consolidation():
       """每日巩固任务 -- Track C 实现"""
       raise NotImplementedError("Track C 未实现")

   @celery_app.task(name="tasks.consolidation_tasks.run_weight_scan")
   def run_weight_scan():
       """权重扫描任务 -- Track C 实现"""
       raise NotImplementedError("Track C 未实现")
   ```
   > 注：`celery_app` 的实际导入路径需根据 `celery_extension.py` 挂载方式确认；若 Celery 实例未在模块级暴露，需在 `celery_extension.py` 补充模块级 `celery_app` 引用或通过 `current_app.extensions["celery"]` 获取。执行者需先读 `api/app/http/app.py` 确认初始化链路。

7. **验证 beat 配置**：启动后执行 `celery -A app.celery inspect scheduled` 确认两条 schedule 已注册。

### 验收标准

- [ ] `cd api && python -c "from config.config import Config; c=Config(); print(c.CELERY['beat_schedule'])"` 输出含 `daily-consolidation` 与 `weight-scan` 两条。
- [ ] `cd api && python -c "from config.config import Config; c=Config(); print(c.CELERY['task_routes'])"` 含 `tasks.consolidation_tasks.*` → `consolidation`。
- [ ] `cd api && python -c "from config.config import Config; c=Config(); print([q.name for q in c.CELERY['task_queues']])"` 含 `consolidation`。
- [ ] `llmops-celery-beat` 容器启动后日志显示两条 beat entry。
- [ ] 占位任务 `consolidation_tasks.py` 可被 `python -c "import internal.task.consolidation_tasks"` 导入无报错。
- [ ] 现有 email 任务路由不受影响（回归测试 `test_email_task.py` 通过）。

### 关联架构文档章节

- [03-consolidation-skill-policy-api.md](../../03-consolidation-skill-policy-api.md) §巩固引擎定时任务（每日巩固 / 权重扫描）
- [00-overview.md](./00-overview.md) §代码目录结构规划（`task/consolidation_tasks.py`）

---

## I4：Neo4j schema 初始化脚本

### 目标

创建 `api/internal/migration/neo4j_init.cypher`，定义记忆系统 TKG 的约束（UNIQUE）、索引（B-tree/Range）、全文索引，确保 Neo4j 5.x 语法正确，支持节点（Episode/Entity/MemoryNode）与边的高效查询。

### 输入

- **前置任务**：I1（neo4j 服务可用）、I6（数据模型定义节点/边字段，本任务先按已知字段建 schema）
- **依赖文件**：
  - `docs/prd/memory-system/01-data-models-and-write-path.md` §1.3 MemoryNode / §1.4 MemoryEdge（字段定义）
  - Neo4j 5.x Cypher 语法手册（`CREATE CONSTRAINT ... IF NOT EXISTS`、`CREATE INDEX ... IF NOT EXISTS`、`CREATE FULLTEXT INDEX ... IF NOT EXISTS`）

### 输出

- **新增文件**：`api/internal/migration/neo4j_init.cypher`
- **关键 schema 签名**：

```cypher
// 约束
CREATE CONSTRAINT episode_node_id_unique IF NOT EXISTS FOR (n:Episode) REQUIRE n.node_id IS UNIQUE;
CREATE CONSTRAINT entity_node_id_unique IF NOT EXISTS FOR (n:Entity) REQUIRE n.node_id IS UNIQUE;
CREATE CONSTRAINT entity_name_user_unique IF NOT EXISTS FOR (n:Entity) REQUIRE (n.name, n.user_id) IS UNIQUE;
CREATE CONSTRAINT memorynode_id_unique IF NOT EXISTS FOR (n:MemoryNode) REQUIRE n.id IS UNIQUE;

// 索引
CREATE INDEX episode_user_id_idx IF NOT EXISTS FOR (n:Episode) ON (n.user_id);
CREATE INDEX episode_tier_idx IF NOT EXISTS FOR (n:Episode) ON (n.tier);
CREATE INDEX episode_created_at_idx IF NOT EXISTS FOR (n:Episode) ON (n.created_at);
CREATE INDEX episode_is_active_idx IF NOT EXISTS FOR (n:Episode) ON (n.is_active);
CREATE INDEX entity_user_id_idx IF NOT EXISTS FOR (n:Entity) ON (n.user_id);
CREATE INDEX entity_tier_idx IF NOT EXISTS FOR (n:Entity) ON (n.tier);
CREATE INDEX memorynode_user_id_idx IF NOT EXISTS FOR (n:MemoryNode) ON (n.user_id);
CREATE INDEX memorynode_storage_tier_idx IF NOT EXISTS FOR (n:MemoryNode) ON (n.storage_tier);
CREATE INDEX memorynode_is_active_idx IF NOT EXISTS FOR (n:MemoryNode) ON (n.is_active);

// 全文索引
CREATE FULLTEXT INDEX memoryFullText IF NOT EXISTS FOR (n:MemoryNode) ON EACH [n.content];
CREATE FULLTEXT INDEX entityFullText IF NOT EXISTS FOR (n:Entity) ON EACH [n.name, n.summary];
```

### 实现步骤

1. **新建文件**：创建 `api/internal/migration/neo4j_init.cypher`（注意：该目录现有 Alembic 迁移，cypher 脚本与 Alembic 无关，独立放置即可）。

2. **编写文件头注释**：说明用途、Neo4j 版本要求（5.x）、执行方式（`cat neo4j_init.cypher | cypher-shell -u neo4j -p openagent` 或通过 Neo4j Browser 粘贴执行）。

3. **编写约束段（4 条 UNIQUE 约束）**：
   - `Episode.node_id` UNIQUE
   - `Entity.node_id` UNIQUE
   - `Entity (name, user_id)` 复合 UNIQUE（Neo4j 5.x 支持复合属性约束 `REQUIRE (n.name, n.user_id) IS UNIQUE`）
   - `MemoryNode.id` UNIQUE
   - 全部加 `IF NOT EXISTS` 保证幂等可重复执行。
   - Neo4j 5.x 语法：`CREATE CONSTRAINT <name> IF NOT EXISTS FOR (n:Label) REQUIRE n.prop IS UNIQUE;`

4. **编写索引段（9 条索引）**：
   - Episode: `user_id`、`tier`、`created_at`、`is_active`
   - Entity: `user_id`、`tier`
   - MemoryNode: `user_id`、`storage_tier`、`is_active`
   - Neo4j 5.x 语法：`CREATE INDEX <name> IF NOT EXISTS FOR (n:Label) ON (n.prop);`（默认 B-tree 索引，足够范围查询）。

5. **编写全文索引段（2 条）**：
   - `memoryFullText` ON `MemoryNode(content)`：用于 BM25 关键词检索（检索器 w_bm25 分量）。
   - `entityFullText` ON `Entity(name, summary)`：用于实体名/摘要的关键词匹配。
   - Neo4j 5.x 语法：`CREATE FULLTEXT INDEX <name> IF NOT EXISTS FOR (n:Label) ON EACH [n.prop1, n.prop2];`

6. **添加执行验证查询**（文件末尾，注释段）：
   ```cypher
   // 验证：查看所有约束与索引
   // SHOW CONSTRAINTS;
   // SHOW INDEXES;
   ```

7. **幂等性检查**：所有语句均带 `IF NOT EXISTS`，重复执行不报错。

8. **字段一致性核对**：与 I6 `MemoryNode` 模型字段对照——MemoryNode 用 `id`（非 `node_id`）、`storage_tier`（非 `tier`）、`is_active`、`user_id`、`content`。Episode/Entity 用 `node_id`、`tier`、`user_id`、`is_active`、`name`、`summary`、`created_at`、`content`。执行者需以 I6 最终模型为准，若 I6 字段名与本任务规格不符，以 I6 为准并同步更新本 cypher。

### 验收标准

- [ ] 文件可被 `cypher-shell` 完整执行无报错：`cat api/internal/migration/neo4j_init.cypher | docker exec -i llmops-neo4j cypher-shell -u neo4j -p openagent`。
- [ ] 执行后 `SHOW CONSTRAINTS;` 返回 4 条约束。
- [ ] 执行后 `SHOW INDEXES;` 返回 9 条 B-tree 索引 + 2 条 fulltext 索引。
- [ ] 重复执行（幂等）不报错。
- [ ] 全文索引可被查询调用：`CALL db.index.fulltext.queryNodes('memoryFullText', 'test') YIELD node RETURN node LIMIT 1;` 不报错（无数据时返回空）。
- [ ] Neo4j 5.x 语法合规（无 4.x 旧式 `CREATE CONSTRAINT ON ... ASSERT ... IS UNIQUE` 写法）。

### 关联架构文档章节

- [01-data-models-and-write-path.md](../../01-data-models-and-write-path.md) §1.3 MemoryNode / §1.4 MemoryEdge（字段定义）
- [02-storage-and-retrieval.md](../../02-storage-and-retrieval.md) §检索器（全文索引用于 BM25）

---

## I5：pgvector 向量列就绪验证

### 目标

创建 `api/internal/migration/pgvector_hnsw_index.py`（可独立运行的 Python 脚本）与对应的 Alembic 迁移，验证 `init.sql` 中 `CREATE EXTENSION IF NOT EXISTS vector` 已执行、`user_memory.embedding` 列（Vector(1536)）已存在、HNSW 索引已创建。若 HNSW 索引缺失则通过 Alembic 迁移补建，确保后续 Track A/C 的向量写入与检索可直接使用 pgvector SQLAlchemy API。

### 输入

- **前置任务**：I1（`llmops-db` PostgreSQL 服务可用，pgvector 扩展随 init.sql 安装）、I2（`PgvectorConfig` 提供 table_name/embedding_column/embedding_dim/index_type/m/ef_construction/distance_metric）
- **依赖文件**：
  - `api/requirements.txt`（已含 `SQLAlchemy`、`asyncpg`、`alembic`；需确认 `pgvector` Python 包是否已安装，若未安装需追加）
  - `llmops-db` 的 init.sql 或 docker entrypoint（应已执行 `CREATE EXTENSION IF NOT EXISTS vector`）
- **环境变量**：复用现有 `POSTGRES_*` / `SQLALCHEMY_DATABASE_URI`（无独立向量库变量，pgvector 复用 PostgreSQL 连接）

### 输出

- **新增文件**：`api/internal/migration/pgvector_hnsw_index.py`
- **新增依赖**（若 requirements.txt 未含）：`pgvector>=0.3.0`（追加到 `api/requirements.in` 与 `requirements.txt`，提供 SQLAlchemy 的 `Vector` 类型与 `<=>` / `<->` / `<#>` 操作符支持）
- **新增 Alembic 迁移**：`api/migrations/versions/<rev>_create_user_memory_embedding_hnsw.py`（若 init.sql 未建索引时补建）
- **关键函数签名**：

```python
#!/usr/bin/env python
"""pgvector 向量列就绪验证脚本 -- 验证 user_memory.embedding 列与 HNSW 索引"""
import os
import sys
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

TABLE_NAME = os.getenv("PGVECTOR_TABLE", "user_memory")
EMBEDDING_COLUMN = os.getenv("PGVECTOR_EMBEDDING_COLUMN", "embedding")
EMBEDDING_DIM = int(os.getenv("PGVECTOR_EMBEDDING_DIM", "1536"))
INDEX_NAME = os.getenv("PGVECTOR_INDEX_NAME", "user_memory_embedding_hnsw_idx")
DATABASE_URL = os.getenv("SQLALCHEMY_DATABASE_URI", "postgresql+asyncpg://openagent:openagent@llmops-db:5432/openagent")

async def verify_extension(engine) -> bool: ...
async def verify_embedding_column(engine) -> bool: ...
async def verify_hnsw_index(engine) -> bool: ...
async def create_hnsw_index(engine) -> None: ...

async def main() -> int: ...

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

### 实现步骤

1. **确认依赖**：检查 `api/requirements.txt` 是否含 `pgvector`。若不含，追加 `pgvector>=0.3.0` 到 `api/requirements.in` 与 `requirements.txt`，并在 `api/Dockerfile` 构建后确认安装（依赖现有构建流程）。

2. **新建脚本文件**：创建 `api/internal/migration/pgvector_hnsw_index.py`，文件头加 shebang `#!/usr/bin/env python` 与模块 docstring。

3. **读取配置**：从环境变量读取 `SQLALCHEMY_DATABASE_URI`（复用现有 PG 连接）、`PGVECTOR_TABLE`（默认 `user_memory`）、`PGVECTOR_EMBEDDING_COLUMN`（默认 `embedding`）、`PGVECTOR_EMBEDDING_DIM`（默认 `1536`）、`PGVECTOR_INDEX_NAME`。

4. **初始化 engine**：
   ```python
   engine = create_async_engine(DATABASE_URL)
   ```

5. **`verify_extension(engine)`**：
   - 执行 `SELECT extname, extversion FROM pg_extension WHERE extname='vector'`。
   - 存在记录则打印 `[OK] pgvector extension installed (version=...)`；否则打印 `[FAIL] pgvector extension missing` 并返回 False（需在 init.sql 补 `CREATE EXTENSION vector`）。

6. **`verify_embedding_column(engine)`**：
   - 执行 `SELECT column_name, data_type, udt_name FROM information_schema.columns WHERE table_name=:t AND column_name=:c`。
   - 存在记录且 `udt_name='vector'` 则打印 `[OK] column {TABLE}.{COL} is vector type`；否则返回 False（需在 Alembic 迁移补 `ALTER TABLE user_memory ADD COLUMN embedding vector(1536)`）。

7. **`verify_hnsw_index(engine)`**：
   - 执行 `SELECT indexname, indexdef FROM pg_indexes WHERE tablename=:t AND indexname=:i`。
   - 存在记录且 `indexdef` 含 `USING hnsw` 则打印 `[OK] HNSW index exists`；否则返回 False。

8. **`create_hnsw_index(engine)`**：
   - 执行幂等 DDL：
     ```sql
     CREATE INDEX IF NOT EXISTS user_memory_embedding_hnsw_idx
       ON user_memory USING hnsw (embedding vector_cosine_ops)
       WITH (m = 16, ef_construction = 64);
     ```
   - 打印 `[OK] HNSW index created`。

9. **`main()`**：按顺序 verify_extension → verify_embedding_column → verify_hnsw_index；若索引缺失则调 create_hnsw_index；捕获异常打印错误并返回非零退出码；成功返回 0。

10. **Alembic 迁移（可选但推荐）**：创建 `api/migrations/versions/<rev>_create_user_memory_embedding_hnsw.py`，`upgrade()` 中执行与步骤 8 相同的 `CREATE INDEX IF NOT EXISTS`，`downgrade()` 执行 `DROP INDEX IF EXISTS`。若 init.sql 已建索引则此迁移幂等跳过。

11. **独立可运行**：脚本需支持 `python api/internal/migration/pgvector_hnsw_index.py` 直接执行（不依赖 Flask app 上下文）。

### 验收标准

- [ ] `python api/internal/migration/pgvector_hnsw_index.py` 退出码 0，输出含 `[OK] pgvector extension installed`、`[OK] column user_memory.embedding is vector type`、`[OK] HNSW index exists`（或 `[OK] HNSW index created`）。
- [ ] 重复执行（幂等）退出码 0，全部输出 `[OK] ... exists`。
- [ ] `psql -c "SELECT extname FROM pg_extension WHERE extname='vector';"` 返回 `vector`。
- [ ] `psql -c "\d user_memory"` 中 `embedding` 列类型为 `vector(1536)`。
- [ ] `psql -c "SELECT indexname FROM pg_indexes WHERE tablename='user_memory' AND indexname='user_memory_embedding_hnsw_idx';"` 返回索引名。
- [ ] Alembic 迁移可重复执行（幂等）不报错。
- [ ] 脚本不依赖 Flask app 上下文，可独立运行。

### 关联架构文档章节

- [02-storage-and-retrieval.md](../../02-storage-and-retrieval.md) §向量存储（pgvector user_memory.embedding 列 / HNSW 索引设计）
- [01-data-models-and-write-path.md](../../01-data-models-and-write-path.md) §写入路径（向量写入字段）

---

## I6：统一数据模型层

### 目标

创建 `api/internal/model/memory_models.py`，统一定义记忆系统全部数据模型（Pydantic v2 `BaseModel`），解决文档 1/2/3 之间的类型冲突（StorageTier 统一为 str Enum、MemoryEdge 合并两版字段、RetrievalResult 合并两版并含 RetrievalScore 子结构），作为所有后续 Track 的单一数据模型来源。

### 输入

- **前置任务**：无（可与 I1-I5 并行）
- **依赖文件**：
  - `docs/prd/memory-system/01-data-models-and-write-path.md`（MemoryEvent/StorageTier/MemoryNode/MemoryEdge/SalienceResult/MemoryDigest 等）
  - `docs/prd/memory-system/02-storage-and-retrieval.md`（RetrievalResult/RetrievalScore/SpreadConfig/FunnelConfig/EvidenceItem/ColdStorageEntry/RebuildResult 等）
  - `docs/prd/memory-system/03-consolidation-skill-policy-api.md`（ConsolidationReport/ConflictResolution/Skill/SkillMaturity/ConflictType 等）
  - `api/requirements.txt`（已含 `pydantic==2.12.5`）

### 输出

- **新增文件**：`api/internal/model/memory_models.py`
- **文件头注释**：标注每个模型来源文档章节（见下方"模型来源映射表"）
- **关键类签名清单**（按文档分组，全部为 Pydantic v2 `BaseModel`，枚举为 `str, Enum`）：

```
# 枚举
EventSource(str, Enum)           # 01 §1.1
StorageTier(str, Enum)           # 01 §1.2  -- 统一为 str Enum，非 IntEnum
NodeType(str, Enum)              # 01 §1.3
WritePath(str, Enum)             # 01 §写入路径
SkillStatus(str, Enum)           # 03 §技能
SkillMaturity(str, Enum)         # 03 §技能
ConflictType(str, Enum)          # 03 §冲突
ConsolidationPhase(str, Enum)    # 03 §巩固
IntentClassification(str, Enum)  # 02 §检索意图
FunnelLayer(str, Enum)           # 02 §漏斗
ViewProfile(str, Enum)           # 02 §视图

# 核心模型（01 数据模型与写入路径）
MemoryEvent                      # 01 §1.1
MemoryNode                       # 01 §1.3
MemoryEdge                       # 01 §1.4  -- 合并两版字段
ScoreFactors                     # 01 §1.5（SalienceResult 拆分）
SalienceResult                   # 01 §1.5
UserProfile                      # 01 §1.6
RecentEventSummary               # 01 §1.6
TaskStatus                       # 01 §1.6
MemoryDigest                     # 01 §1.6

# 检索模型（02 存储与检索）
RetrievalScore                   # 02 §检索结果（子结构：semantic/keyword/graph/time_decay/total）
RetrievalResult                  # 02 §检索结果  -- 合并两版，含 evidence_chain
RetrievalOptions                 # 02 §检索选项
RetrievalConfig                  # 02 §检索配置
SpreadConfig                     # 02 §扩展激活
FunnelConfig                     # 02 §漏斗
EvidenceItem                     # 02 §漏斗证据
QueryIntent                      # 02 §意图识别
IntentClassification(...)        # 枚举（见上）
DigestConfig                     # 02 §Digest
DecayConfig                      # 02 §衰减
ColdStorageEntry                 # 02 §冷存储
RebuildResult                    # 02 §重建

# 巩固模型（03 巩固/技能/策略/API）
ConsolidationConfig              # 03 §巩固
ConsolidationReport              # 03 §巩固
ConflictResolution               # 03 §冲突
ConflictResult                   # 03 §冲突
DedupMerge                       # 03 §去重
TierTransition                   # 03 §分层
Skill                            # 03 §技能
AuditEntry                       # 03 §审计
PIIField                         # 03 §PII

# 写入辅助模型
EntityCandidate                  # 01 §实体消解
EntityResolutionResult           # 01 §实体消解
```

### 实现步骤

1. **新建文件**：创建 `api/internal/model/memory_models.py`（目录已存在，含其他 model 文件）。

2. **编写文件头注释**：包含模块说明 + 模型来源映射表（列出每个类对应文档章节），便于追溯。示例：
   ```python
   """
   记忆系统统一数据模型层。

   本模块统一定义文档 1/2/3 中的所有数据模型，解决跨文档类型冲突：
   - StorageTier 统一为 str Enum（"hot"/"warm"/"cold"/"frozen"），不使用 IntEnum。
   - MemoryEdge 合并文档 1 与文档 2 两版字段，包含四时间戳 + 访问统计 + 共现计数。
   - RetrievalResult 合并两版定义，含 RetrievalScore 子结构与 evidence_chain。

   模型来源映射：
   - MemoryEvent / StorageTier / NodeType / MemoryNode / MemoryEdge / SalienceResult /
     ScoreFactors / WritePath / MemoryDigest / UserProfile / RecentEventSummary /
     TaskStatus / EntityCandidate / EntityResolutionResult
       <- 01-data-models-and-write-path.md §1.1-1.6, §写入路径, §实体消解
   - RetrievalScore / RetrievalResult / RetrievalOptions / RetrievalConfig /
     SpreadConfig / FunnelConfig / EvidenceItem / QueryIntent / IntentClassification /
     FunnelLayer / DigestConfig / DecayConfig / ColdStorageEntry / RebuildResult / ViewProfile
       <- 02-storage-and-retrieval.md §检索, §扩展, §漏斗, §Digest, §衰减, §冷存储, §重建
   - ConsolidationConfig / ConsolidationReport / ConflictResolution / ConflictResult /
     ConflictType / DedupMerge / TierTransition / Skill / SkillStatus / SkillMaturity /
     ConsolidationPhase / AuditEntry / PIIField
       <- 03-consolidation-skill-policy-api.md §巩固, §冲突, §技能, §审计, §PII
   """
   ```

3. **导入与基础设置**：
   ```python
   from __future__ import annotations
   from datetime import datetime
   from enum import Enum
   from typing import Any, Optional
   from uuid import UUID, uuid4
   from pydantic import BaseModel, Field
   ```

4. **定义枚举（全部 `str, Enum`）**：
   - `EventSource`：`USER_MESSAGE / AGENT_ACTION / SYSTEM_OBSERVATION / EXTERNAL_FEED`
   - `StorageTier`：`HOT="hot" / WARM="warm" / COLD="cold" / FROZEN="frozen"`（**关键：str Enum，非 IntEnum**）
   - `NodeType`：`EPISODE / ENTITY / COMMUNITY`
   - `WritePath`：`FULL / SUMMARY / SKETCH / REJECT`（评分阈值决定）
   - `SkillStatus`：`EMERGING / ACTIVE / STALE / ARCHIVED`
   - `SkillMaturity`：`EMERGING / ACTIVE / STALE`
   - `ConflictType`：`CONTRADICTION / REFINEMENT / DUPLICATE / SUPERSEDE`
   - `ConsolidationPhase`：`EXTRACT / RESOLVE / MERGE / TIER / REPORT`
   - `IntentClassification`：`FACTUAL / PROCEDURAL / EPISODIC / PREFERENCE / UNKNOWN`
   - `FunnelLayer`：`RECALL / DEDUP / RANK / EVIDENCE / RENDER`
   - `ViewProfile`：`FULL / DIGEST / GRAPH`

5. **定义核心模型（按 01 文档）**：
   - `MemoryEvent`：参考 01 §1.1（event_id/timestamp/source/content/context_messages/metadata/session_id/user_id）。
   - `MemoryNode`：参考 01 §1.3（node_id/node_type/name/summary/content/properties/embedding/tier/created_at/last_accessed/access_count/is_active/user_id）。**追加 `user_id` 字段**（多用户隔离，与 I4 schema 一致）。
   - `MemoryEdge`（**合并两版**）：包含以下全部字段：
     ```python
     class MemoryEdge(BaseModel):
         edge_id: UUID = Field(default_factory=uuid4)
         source_id: UUID
         target_id: UUID
         relation_type: str
         properties: dict[str, Any] = Field(default_factory=dict)
         weight: float = Field(default=1.0, ge=0.0, le=2.0)
         # 四时间戳（双时间模型）
         t_valid_at: datetime = Field(default_factory=datetime.utcnow)
         t_invalidated_at: Optional[datetime] = None
         t_transaction_start: datetime = Field(default_factory=datetime.utcnow)
         t_transaction_end: Optional[datetime] = None
         # 访问统计
         created_at: datetime = Field(default_factory=datetime.utcnow)
         last_accessed_at: datetime = Field(default_factory=datetime.utcnow)
         access_count: int = 0
         # 共现统计（赫布学习）
         cooccurrence_count: int = 0
         # 状态
         is_active: bool = True
         invalidated_by: Optional[UUID] = None
     ```
   - `ScoreFactors`：拆分自 SalienceResult，含 emotion_intensity/novelty/goal_relevance/outcome_impact/rehearsal_boost。
   - `SalienceResult`：含 event 引用 / total_score / 各因子 / write_path / reasoning。
   - `UserProfile` / `RecentEventSummary` / `TaskStatus` / `MemoryDigest`：参考 01 §1.6。
   - `EntityCandidate`：实体候选（name/type/aliases/embedding/score）。
   - `EntityResolutionResult`：消解结果（merged_entity/candidates/confidence/method）。

6. **定义检索模型（按 02 文档）**：
   - `RetrievalScore`（**子结构**）：
     ```python
     class RetrievalScore(BaseModel):
         semantic: float = 0.0
         keyword: float = 0.0       # BM25
         graph: float = 0.0
         time_decay: float = 1.0
         total: float = 0.0
     ```
   - `RetrievalResult`（**合并两版**）：
     ```python
     class RetrievalResult(BaseModel):
         memory_id: str
         content: str
         score: float
         source: str                          # "neo4j" / "pgvector" / "hybrid"
         timestamp: datetime
         metadata: dict[str, Any] = Field(default_factory=dict)
         evidence_chain: list[EvidenceItem] = Field(default_factory=list)
         score_breakdown: RetrievalScore = Field(default_factory=RetrievalScore)
     ```
   - `RetrievalOptions`：top_k/filters/weights 覆盖/early_stop 等。
   - `RetrievalConfig`：w_cosine/w_bm25/w_graph/time_decay_half_life_hours/early_stop_top_k/early_stop_score_gap（与 I2 RetrievalConfig 一致，但此处为模型层定义）。
   - `SpreadConfig`：max_hops/activation_decay/min_activation/top_k。
   - `FunnelConfig`：dedup_similarity_threshold/evidence_max_items/early_stop_confidence/early_stop_min_items/llm_model/llm_temperature/llm_max_tokens。
   - `EvidenceItem`：content/source/score/relevance。
   - `QueryIntent`：classification/keywords/target_entities。
   - `DigestConfig`：cache_ttl_seconds/cache_key_prefix/max_tokens/profile_max_items/skills_max_items/events_max_items/tasks_max_items/render_model/render_temperature。
   - `DecayConfig`：lambda_decay/alpha_cooccurrence/beta_interference/cooccurrence_window_hours/hot_threshold/warm_threshold。
   - `ColdStorageEntry`：entry_id/node_id/user_id/s3_key/archived_at/support_count/weight。
   - `RebuildResult`：success/rebuilt_count/errors/duration_s。

7. **定义巩固模型（按 03 文档）**：
   - `ConsolidationConfig`：episode_age_days/semantic_min_examples/semantic_similarity_threshold/conflict_check_batch_size/conflict_similarity_threshold/cold_threshold/merge_similarity_threshold/llm_model/llm_temperature。
   - `ConsolidationReport`：run_id/started_at/finished_at/phases/merged_count/conflicts_resolved/cold_archived/skills_emerged/errors。
   - `ConflictResolution`：conflict_id/type/resolution/winner_id/loser_id/reason。
   - `ConflictResult`：conflict_id/type/entity_a/entity_b/similarity/resolution。
   - `DedupMerge`：source_id/target_id/similarity/fields_merged。
   - `TierTransition`：node_id/from_tier/to_tier/reason/weight/at_time。
   - `Skill`：skill_id/name/pattern/frequency/maturity/status/confidence/last_seen/first_seen/examples。
   - `AuditEntry`：entry_id/timestamp/actor/action/target/before/after。
   - `PIIField`：field_name/value/category/action（mask/redact/retain）。

8. **类型冲突解决说明**（文件内注释）：
   - `StorageTier`：文档 1 用 str Enum，文档 2 部分示例用 IntEnum；**统一为 str Enum**，值 `"hot"/"warm"/"cold"/"frozen"`。
   - `MemoryEdge`：文档 1 含四时间戳 + is_active + invalidated_by；文档 2 补充 created_at/last_accessed_at/access_count/cooccurrence_count；**合并为单一类含全部字段**。
   - `RetrievalResult`：文档 1 版本含 memory_id/content/score/source/timestamp/metadata；文档 2 版本含 evidence_chain 与 score_breakdown；**合并为单一类含全部字段**，score_breakdown 类型为 `RetrievalScore`。

9. **Pydantic v2 规范**：
   - 全部用 `BaseModel`（非 dataclass），与项目现有 `entity/*.py` 一致。
   - `Field(default_factory=...)` 用于可变默认值。
   - `Optional[...] = None` 用于可空字段。
   - 不使用 `class Config:` 旧式配置（v2 用 `model_config`，本模型层无需额外配置）。

10. **验证导入**：执行 `python -c "import internal.model.memory_models"` 确认无循环导入、无语法错误。

### 验收标准

- [ ] `cd api && python -c "import internal.model.memory_models; print('OK')"` 输出 OK。
- [ ] `cd api && python -m py_compile internal/model/memory_models.py` 无错误。
- [ ] `StorageTier` 为 `str, Enum` 子类：`issubclass(StorageTier, str)` 为 True；`StorageTier.HOT.value == "hot"`。
- [ ] `MemoryEdge` 含全部 16 个字段（edge_id/source_id/target_id/relation_type/properties/weight/t_valid_at/t_invalidated_at/t_transaction_start/t_transaction_end/created_at/last_accessed_at/access_count/cooccurrence_count/is_active/invalidated_by）。
- [ ] `RetrievalResult` 含 `evidence_chain` 与 `score_breakdown` 字段；`score_breakdown` 类型为 `RetrievalScore`。
- [ ] `RetrievalScore` 含 semantic/keyword/graph/time_decay/total 五个 float 字段。
- [ ] 文件头注释含模型来源映射表，每个类可追溯到文档章节。
- [ ] 所有枚举为 `str, Enum`（非 IntEnum）。
- [ ] 所有模型为 Pydantic v2 `BaseModel`（非 dataclass），与 `api/internal/entity/*.py` 风格一致。
- [ ] 文档 1/2/3 中提及的所有模型均已定义（对照任务规格清单逐项核对，无遗漏）。

### 关联架构文档章节

- [01-data-models-and-write-path.md](../../01-data-models-and-write-path.md) §1.1-1.6（核心模型） / §写入路径 / §实体消解
- [02-storage-and-retrieval.md](../../02-storage-and-retrieval.md) §检索结果 / §扩展激活 / §漏斗 / §Digest / §衰减 / §冷存储 / §重建
- [03-consolidation-skill-policy-api.md](../../03-consolidation-skill-policy-api.md) §巩固引擎 / §冲突检测 / §技能涌现 / §审计 / §PII
- [00-overview.md](./00-overview.md) §关键风险与对策（类型冲突由 I6 统一）

---

## 附录 A：环境变量清单

I1-I6 引入的环境变量汇总（供 `api/.env.example` 补充）：

| 变量名 | 默认值 | 来源任务 | 说明 |
|---|---|---|---|
| `NEO4J_URI` | `bolt://localhost:7687` | I1/I2 | Neo4j Bolt 连接 URI |
| `NEO4J_USER` | `neo4j` | I1/I2 | Neo4j 用户名 |
| `NEO4J_PASSWORD` | `openagent` | I1/I2 | Neo4j 密码 |
| `MINIO_ENDPOINT` | `localhost:9000` | I1 | MinIO S3 endpoint |
| `MINIO_ACCESS_KEY` | `openagent` | I1 | MinIO access key |
| `MINIO_SECRET_KEY` | `openagent123` | I1 | MinIO secret key |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | I2/I3 | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | I2/I3 | Celery result backend |
| `MEMORY_SALIENCE__WEIGHTS` | （JSON） | I2 | 显著性权重覆盖 |
| `MEMORY_*__*` | - | I2 | 任意子配置嵌套覆盖 |

## 附录 B：Phase 0 完成判定

Phase 0（I1-I6）全部完成的标志：
1. `docker compose -f docker/docker-compose.yaml up -d` 后所有容器 healthy。
2. `neo4j_init.cypher` 与 `pgvector_hnsw_index.py` 各执行一次成功。
3. `from internal.config.memory_settings import settings` 与 `import internal.model.memory_models` 均无报错。
4. `llmops-celery-beat` 日志显示两条 beat schedule。
5. 上述 I1-I6 各自验收标准全部勾选。

满足后即可解锁 Track A（写入路径）启动。
