"""记忆系统统一配置模块。

基于 pydantic v2 与 pydantic-settings，集中封装用户长期记忆（User Memory）
子系统各组件的可调参数，包括：显著性打分、向量存储、图存储、LLM 调用、
写入与实体消歧、衰减与遗忘、检索、摘要、巩固、技能抽取、激活扩散、
漏斗筛选、冷存储以及异步任务队列。

所有配置项均支持通过环境变量覆盖：
- 主配置使用前缀 ``MEMORY_``，嵌套字段以 ``__`` 分隔
  （例如 ``MEMORY_RETRIEVAL__W_COSINE`` 覆盖 ``retrieval.w_cosine``）。
- 部分字段需绑定裸环境变量（如 ``NEO4J_URI``、``CELERY_BROKER_URL``），
  这些字段通过 ``validation_alias`` 显式声明。

模块级单例 ``settings`` 可在应用各处直接导入使用。
"""

import os
from typing import Any

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SalienceConfig(BaseModel):
    """显著性（Salience）打分配置。

    六因子权重，总和应为 1.0。explicitness 为显式陈述检测因子，
    由 ExplicitStatementDetector 前置层传入。
    """

    # 各维度权重，总和应为 1.0
    weights: dict[str, float] = {
        "emotion": 0.20,
        "novelty": 0.16,
        "goal_relevance": 0.20,
        "outcome_impact": 0.16,
        "rehearsal": 0.08,
        "explicitness": 0.20,
    }
    # 记忆存储层级阈值：高于 full 全量保存，高于 summary 摘要保存
    thresholds: dict[str, float] = {"full": 0.7, "summary": 0.3}


class ExplicitDetectionConfig(BaseModel):
    """显式陈述检测配置。

    控制 ExplicitStatementDetector 的行为，包括正则预筛、LLM 确认、
    快路径阈值、降级策略和衰减豁免系数。
    """

    # 总开关
    enabled: bool = True
    # 快路径置信度阈值（≥此值直接 FULL 写入，跳过 SalienceScorer）
    fast_path_threshold: float = 0.85
    # 因子拉高阈值（≥此值走 6 因子评分但 explicitness=0.8）
    boost_threshold: float = 0.5
    # explicitness 因子权重（从原 5 因子权重中分摊，已含在 SalienceConfig.weights 中）
    explicitness_weight: float = 0.20
    # 向量兜底相似度阈值（写时冲突检测的向量兜底）
    vector_fallback_threshold: float = 0.85
    # 衰减豁免系数：preference/identity/aversion 类记忆衰减速率乘以此值
    decay_exemption_strong: float = 0.1
    # 衰减豁免系数：habit/goal/capability 类记忆衰减速率乘以此值
    decay_exemption_medium: float = 0.5
    # LLM 降级策略
    llm_fallback_enabled: bool = True
    # LLM 调用超时（秒）—— DeepSeek-V4-Flash 实际响应 5-15s，原 2s 过短导致频繁降级
    llm_timeout_seconds: float = 20.0


class PgvectorConfig(BaseModel):
    """pgvector 向量存储配置。"""

    table_name: str = "user_memory"
    embedding_column: str = "embedding"
    embedding_dim: int = 1536
    index_type: str = "hnsw"
    # HNSW 索引参数
    m: int = 16
    ef_construction: int = 64
    distance_metric: str = "cosine"


class Neo4jConfig(BaseModel):
    """Neo4j 图存储连接配置。

    裸环境变量（NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD）由 ``Settings``
    的 ``_load_bare_env_vars`` 校验器注入，pydantic-settings v2 的
    ``validation_alias`` 在嵌套 BaseModel 上不生效。
    """

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "yuxin_ai"


class LLMConfig(BaseModel):
    """记忆子系统默认 LLM 调用配置。"""

    model: str = "gpt-4o-mini"
    temperature: float = 0.0
    request_timeout_s: int = 30


class EntityResolution(BaseModel):
    """实体消歧（Entity Resolution）配置。"""

    merge_threshold: float = 0.75
    edit_distance_threshold: int = 3
    # 三路打分权重，总和应为 1.0
    vector_weight: float = 0.4
    bm25_weight: float = 0.3
    llm_judge_weight: float = 0.3


class WriteConfig(BaseModel):
    """记忆写入路径配置，内嵌实体消歧子模型。"""

    entity_resolution: EntityResolution = Field(default_factory=EntityResolution)
    # ── 基因4: Agent-Curated Memory（§2.5）──
    memory_add_max_per_session: int = 5
    # ── 基因5: 周期性 Nudge（§2.6）──
    nudge_enabled: bool = True
    nudge_min_tool_calls: int = 5
    nudge_min_conversation_turns: int = 10
    nudge_max_per_session: int = 3
    nudge_model: str = "gpt-4o-mini"


class DecayConfig(BaseModel):
    """记忆衰减与遗忘配置。"""

    # 基础时间衰减系数
    lambda_decay: float = 0.05
    # 共现增强系数
    alpha_cooccurrence: float = 0.2
    # 干扰抑制系数
    beta_interference: float = 0.15
    # 共现统计时间窗（小时），默认一周
    cooccurrence_window_hours: int = 168
    # 热度分级阈值
    hot_threshold: float = 0.7
    warm_threshold: float = 0.3


class RetrievalConfig(BaseModel):
    """混合检索配置。"""

    # 向量、BM25、图三路融合权重，总和应为 1.0
    w_cosine: float = 0.4
    w_bm25: float = 0.3
    w_graph: float = 0.3
    # 时间衰减半衰期（小时），默认一周
    time_decay_half_life_hours: float = 168.0
    # 早停参数：命中 top_k 后若分数差距不足 gap 则提前停止
    early_stop_top_k: int = 10
    early_stop_score_gap: float = 0.15


class DigestConfig(BaseModel):
    """记忆摘要（Digest）渲染与缓存配置。"""

    cache_ttl_seconds: int = 300
    cache_key_prefix: str = "memory:digest:"
    max_tokens: int = 2000
    # 是否强制 token 预算截断（False=用户体验优先，不截断显式陈述）
    enforce_token_limit: bool = False
    # 各分项最大条目数
    profile_max_items: int = 5
    skills_max_items: int = 10
    events_max_items: int = 10
    tasks_max_items: int = 5
    # 显式陈述分组渲染最大条目数（高默认值，实际不限量）
    explicit_max_items: int = 50
    # 摘要渲染所用 LLM
    render_model: str = "gpt-4o-mini"
    render_temperature: float = 0.0
    # ── 基因2: Progressive Disclosure 分层加载（§8.6）──
    skill_tier0_max_tokens: int = 3000
    skill_tier0_max_items: int = 50
    skill_tier1_max_concurrent: int = 3
    skill_tier2_enabled: bool = True


class ConsolidationConfig(BaseModel):
    """记忆巩固（Consolidation）配置。"""

    # 情节记忆转化为语义记忆的最小年龄（天）
    episode_age_days: int = 7
    semantic_min_examples: int = 3
    semantic_similarity_threshold: float = 0.8
    # 冲突检测参数
    conflict_check_batch_size: int = 50
    conflict_similarity_threshold: float = 0.85
    # 冷记忆阈值
    cold_threshold: float = 0.3
    # 合并相似度阈值
    merge_similarity_threshold: float = 0.9
    # 巩固所用 LLM
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0


class SkillConfig(BaseModel):
    """技能（Skill）抽取与成熟度配置。"""

    min_pattern_frequency: int = 3
    pattern_window_days: int = 30
    # 成熟度分级阈值
    maturity_active_threshold: float = 0.7
    maturity_stale_threshold: float = 0.2
    stale_days: int = 90
    # 技能抽取所用 LLM
    extraction_model: str = "gpt-4o-mini"
    extraction_temperature: float = 0.2
    # ── 基因1: Skill 即时触发（§8.5）──
    instant_emergence_enabled: bool = True
    instant_emergence_min_tool_calls: int = 5
    instant_emergence_async: bool = True
    # ── 基因3: Curator + bump_use（§8.7）──
    curator_enabled: bool = True
    curator_interval_days: int = 7
    curator_merge_similarity_threshold: float = 0.85
    curator_stale_to_deprecated_days: int = 30
    bump_use_redis_enabled: bool = True
    bump_use_neo4j_flush_interval: int = 3600


class SpreadConfig(BaseModel):
    """图上激活扩散（Spreading Activation）配置。"""

    max_hops: int = 3
    activation_decay: float = 0.5
    min_activation: float = 0.01
    top_k: int = 20


class FunnelConfig(BaseModel):
    """漏斗筛选（Funnel）配置。"""

    dedup_similarity_threshold: float = 0.85
    evidence_max_items: int = 30
    # 早停参数：置信度足够高且条目数达标时提前结束
    early_stop_confidence: float = 0.9
    early_stop_min_items: int = 3
    # 漏斗判定所用 LLM
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2000


class ColdStorageConfig(BaseModel):
    """冷存储（Cold Storage）配置。"""

    s3_bucket: str = "yuxin-ai-cold-memory"
    s3_prefix: str = "cold-memories/"
    aws_region: str = "us-east-1"
    # 转入冷存储的权重阈值
    threshold_weight: float = 0.5
    # 最小支持度，低于该值的记忆可归档
    min_support: int = 3


class CeleryConfig(BaseModel):
    """Celery 异步任务队列配置。

    裸环境变量（CELERY_BROKER_URL / CELERY_RESULT_BACKEND）由 ``Settings``
    的 ``_load_bare_env_vars`` 校验器注入。
    """

    broker_url: str = "redis://localhost:6379/1"
    result_backend: str = "redis://localhost:6379/2"


class Settings(BaseSettings):
    """记忆系统总配置。

    通过环境变量覆盖任意子配置项，命名规则为 ``MEMORY_<子配置>__<字段>``，
    例如 ``MEMORY_NEO4J__URI`` 覆盖 ``neo4j.uri``。
    """

    model_config = SettingsConfigDict(
        env_prefix="MEMORY_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # 记忆引擎总开关：False 时跳过所有自动写入（降级用）
    memory_engine_enabled: bool = True

    salience: SalienceConfig = Field(default_factory=SalienceConfig)
    explicit_detection: ExplicitDetectionConfig = Field(default_factory=ExplicitDetectionConfig)
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

    @model_validator(mode="before")
    @classmethod
    def _load_bare_env_vars(cls, data: Any) -> Any:
        """读取裸环境变量并注入嵌套配置。

        pydantic-settings v2 的 validation_alias 在嵌套 BaseModel 上不生效，
        需手动读取 NEO4J_URI / CELERY_BROKER_URL 等裸环境变量注入对应嵌套配置。
        覆盖默认值，但低于 MEMORY_ 前缀显式覆盖（显式覆盖已在 data 中）。
        """
        if not isinstance(data, dict):
            return data
        bare_env_map = {
            "neo4j": {"uri": "NEO4J_URI", "user": "NEO4J_USER", "password": "NEO4J_PASSWORD"},
            "celery": {"broker_url": "CELERY_BROKER_URL", "result_backend": "CELERY_RESULT_BACKEND"},
        }
        for section, field_map in bare_env_map.items():
            section_data = dict(data.get(section) or {})
            for field_name, env_key in field_map.items():
                env_val = os.getenv(env_key)
                if env_val is not None and field_name not in section_data:
                    section_data[field_name] = env_val
            data[section] = section_data
        return data


settings = Settings()
