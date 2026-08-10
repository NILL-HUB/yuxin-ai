"""E1 SkillEmergence 技能涌现器。

从高频行为模式中自动提取可复用技能，执行技能生命周期状态转移
（CANDIDATE→EMERGING→ACTIVE→STALE→DEPRECATED），并通过 LLM 增量更新技能模板。

种子提示机制（记忆写入优化 §5.7）:
    显式 capability 类陈述**不直接创建 Skill**，而是注册为"种子提示"存入 Redis。
    有 positive 种子提示的技能，其 min_pattern_frequency 从 3 降为 1，加速成熟，
    但仍需实际行为验证（用户使用该技能完成任务）才会创建 Skill 节点。
    negative 种子提示将技能加入"避免推荐"列表。

灵感来源：procedural memory（程序性记忆）—— 通过重复练习形成的自动化技能模式。

设计参考:
    docs/prd/memory-system/03-consolidation-skill-policy-api.md §8.1
    docs/prd/memory-system/execution/06-track-e-skill-pool.md E1
    docs/prd/memory-write-optimization-design.md §5.7
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from internal.service.memory.metrics import MetricsCollector

logger = logging.getLogger(__name__)


class SkillStatus(str, Enum):
    """技能状态枚举（5 个状态）。"""

    CANDIDATE = "candidate"
    EMERGING = "emerging"
    ACTIVE = "active"
    STALE = "stale"
    DEPRECATED = "deprecated"


class Skill(BaseModel):
    """技能模型。"""

    skill_id: str
    name: str
    description: str = ""
    template: str = ""
    parameters: list[dict] = Field(default_factory=list)
    user_id: str = ""
    status: SkillStatus = SkillStatus.CANDIDATE
    maturity: float = 0.0
    use_count: int = 0
    frequency: int = 0
    first_seen_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    last_updated_at: Optional[datetime] = None
    source_memories: list[str] = Field(default_factory=list)


class SkillConfig(BaseModel):
    """技能涌现配置。"""

    min_pattern_frequency: int = 3
    pattern_window_days: int = 30
    maturity_active_threshold: float = 0.7
    maturity_stale_threshold: float = 0.2
    stale_days: int = 90
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


# =========================================================
# 状态转移规则表
# =========================================================

SKILL_TRANSITIONS: dict[SkillStatus, list[SkillStatus]] = {
    SkillStatus.CANDIDATE: [SkillStatus.EMERGING, SkillStatus.DEPRECATED],
    SkillStatus.EMERGING: [SkillStatus.ACTIVE, SkillStatus.CANDIDATE, SkillStatus.DEPRECATED],
    SkillStatus.ACTIVE: [SkillStatus.STALE, SkillStatus.DEPRECATED],
    SkillStatus.STALE: [SkillStatus.ACTIVE, SkillStatus.DEPRECATED],
    SkillStatus.DEPRECATED: [],
}


class SkillEmergence:
    """技能涌现器（同步实现）。

    不使用 ``@inject``：通过构造函数接收 Neo4j/Redis 驱动。
    LLM 调用通过 ``LanguageModelService.get_cheap_chat_model()`` 获取。
    """

    def __init__(
        self,
        neo4j_driver=None,
        redis_client=None,
        config: Optional[SkillConfig] = None,
    ) -> None:
        """初始化技能涌现器。

        Args:
            neo4j_driver: Neo4j 驱动（同步）
            redis_client: Redis 客户端（同步），用于技能池缓存
            config: 技能配置，None 时使用默认 SkillConfig()
        """
        self._neo4j_driver = neo4j_driver
        self._redis = redis_client
        self._config = config or SkillConfig()

    def scan_and_emerge(self, user_id: str) -> list[Skill]:
        """扫描高频行为模式并涌现技能。

        种子提示机制（§5.7）: 有 positive 种子提示的技能，min_pattern_frequency
        从 3 降为 1，加速成熟但仍需行为验证。

        Args:
            user_id: 用户标识

        Returns:
            新涌现或更新的技能列表
        """
        patterns = self._scan_high_frequency_patterns(user_id)
        if not patterns:
            MetricsCollector.update_skill_count(0)
            return []

        # 获取种子提示，用于降低频次阈值
        seed_hints = self._get_seed_hints(user_id)

        results: list[Skill] = []
        for pattern in patterns:
            pattern_key = pattern.get("pattern", "")
            frequency = pattern.get("count", 0)
            memory_ids = pattern.get("keys", [])

            # 检查已有技能
            existing = self._find_existing_skill(user_id, pattern_key)

            if existing is not None:
                # 增量更新
                updated = self._update_skill(existing, {"frequency": frequency, "memory_ids": memory_ids})
                if updated is not None:
                    results.append(updated)
            else:
                # 确定频次阈值：有 positive 种子提示 → 降为 1，否则用配置默认值（3）
                min_freq = self._config.min_pattern_frequency
                seed = self._match_seed_hint(seed_hints, pattern_key)
                if seed and seed.get("polarity") == "positive":
                    min_freq = 1

                if frequency >= min_freq:
                    # 新技能提取（需行为验证：frequency >= min_freq）
                    memories = self._fetch_memories(memory_ids)
                    if memories:
                        new_skill = self._extract_template(memories)
                        if new_skill is not None:
                            new_skill.user_id = user_id
                            new_skill.frequency = frequency
                            new_skill.source_memories = memory_ids
                            new_skill.first_seen_at = datetime.utcnow()
                            new_skill.last_updated_at = datetime.utcnow()
                            new_skill.status = self._transition_status(new_skill)
                            self._persist_skill(new_skill)
                            results.append(new_skill)

        MetricsCollector.update_skill_count(len(results))
        return results

    # =========================================================
    # 种子提示（§5.7）
    # =========================================================

    def register_seed_hint(
        self,
        user_id: str,
        skill_name: str,
        polarity: str,
        source: str = "explicit_statement",
    ) -> bool:
        """注册显式能力陈述作为种子提示，不创建 Skill 节点。

        polarity=positive → 该技能的 min_pattern_frequency 从 3 降为 1
        polarity=negative → 该技能加入"避免推荐"列表

        种子提示存入 Redis，TTL=90 天。

        Args:
            user_id: 用户标识
            skill_name: 技能/能力名称（显式陈述的 subject）
            polarity: 'positive' 或 'negative'
            source: 来源标记，默认 'explicit_statement'

        Returns:
            注册成功返回 True
        """
        if not self._redis or not skill_name:
            return False
        try:
            key = f"seed:{user_id}:{skill_name}"
            value = json.dumps(
                {
                    "polarity": polarity,
                    "source": source,
                    "created_at": datetime.utcnow().isoformat(),
                },
                ensure_ascii=False,
            )
            self._redis.setex(key, 90 * 86400, value)  # 90 天 TTL
            logger.info(
                "种子提示已注册: user=%s skill=%s polarity=%s",
                user_id,
                skill_name,
                polarity,
            )
            return True
        except Exception:
            logger.warning("register_seed_hint: 注册失败", exc_info=True)
            return False

    def _get_seed_hints(self, user_id: str) -> dict[str, dict]:
        """获取用户的所有种子提示。

        Returns:
            {skill_name: {"polarity": ..., "source": ..., "created_at": ...}}
        """
        if not self._redis:
            return {}
        try:
            pattern = f"seed:{user_id}:*"
            keys = self._redis.keys(pattern)
            hints: dict[str, dict] = {}
            for key in keys:
                raw = self._redis.get(key)
                if not raw:
                    continue
                text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                data = json.loads(text)
                # key 格式: seed:{user_id}:{skill_name}
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                parts = key_str.split(":", 2)
                skill_name = parts[2] if len(parts) >= 3 else ""
                if skill_name:
                    hints[skill_name] = data
            return hints
        except Exception:
            logger.warning("_get_seed_hints: 获取失败", exc_info=True)
            return {}

    @staticmethod
    def _match_seed_hint(seed_hints: dict[str, dict], pattern_key: str) -> Optional[dict]:
        """匹配模式键与种子提示（支持 CONTAINS 模糊匹配）。

        Args:
            seed_hints: _get_seed_hints 返回的字典
            pattern_key: 行为模式键

        Returns:
            匹配的种子提示 dict，无匹配返回 None
        """
        if not seed_hints or not pattern_key:
            return None
        # 精确匹配优先
        if pattern_key in seed_hints:
            return seed_hints[pattern_key]
        # 模糊匹配：pattern_key 包含 seed skill_name 或反之
        pk_lower = pattern_key.lower()
        for skill_name, hint in seed_hints.items():
            sn_lower = skill_name.lower()
            if sn_lower in pk_lower or pk_lower in sn_lower:
                return hint
        return None

    # =========================================================
    # 内部方法
    # =========================================================

    def _scan_high_frequency_patterns(self, user_id: str) -> list[dict]:
        """扫描高频行为模式（30 天内出现 ≥ min_pattern_frequency 次）。"""
        driver = self._get_driver()
        if driver is None:
            return []

        try:
            window_days = self._config.pattern_window_days
            min_freq = self._config.min_pattern_frequency

            cypher = """
            MATCH (e:Episode {user_id: $user_id})
            WHERE e.created_at >= datetime() - duration({days: $window_days})
            WITH e.content AS pattern, collect(e.id) AS eids
            WHERE size(eids) >= $min_freq
            RETURN pattern AS pattern, size(eids) AS count, eids AS keys
            ORDER BY count DESC
            LIMIT 20
            """

            with driver.session() as session:
                result = session.run(
                    cypher,
                    {
                        "user_id": user_id,
                        "window_days": window_days,
                        "min_freq": min_freq,
                    },
                )
                records = list(result)

            return [
                {
                    "pattern": record.get("pattern", ""),
                    "count": record.get("count", 0),
                    "keys": record.get("keys", []),
                }
                for record in records
            ]
        except Exception:
            logger.warning("_scan_high_frequency_patterns: 查询失败", exc_info=True)
            return []

    def _find_existing_skill(self, user_id: str, pattern_key: str) -> Optional[Skill]:
        """查找已有技能（status IN candidate/emerging/active 且 name CONTAINS pattern_key）。"""
        if not pattern_key:
            return None

        driver = self._get_driver()
        if driver is None:
            return None

        try:
            cypher = """
            MATCH (s:Skill {user_id: $user_id})
            WHERE s.status IN ['candidate', 'emerging', 'active']
              AND s.name CONTAINS $pattern_key
            RETURN s
            LIMIT 1
            """

            with driver.session() as session:
                result = session.run(
                    cypher,
                    {"user_id": user_id, "pattern_key": pattern_key[:50]},
                )
                record = result.single()

            if record is None:
                return None

            node = record.get("s", {})
            return self._node_to_skill(node)
        except Exception:
            logger.warning("_find_existing_skill: 查询失败", exc_info=True)
            return None

    def _fetch_memories(self, memory_ids: list[str]) -> list[dict]:
        """批量获取记忆内容。"""
        if not memory_ids:
            return []

        driver = self._get_driver()
        if driver is None:
            return []

        try:
            cypher = """
            UNWIND $ids AS mid
            MATCH (n) WHERE (n:MemoryNode OR n:Episode) AND (n.node_id = mid OR n.id = mid)
            RETURN n.node_id AS id, n.content AS content, n.created_at AS created_at
            """

            with driver.session() as session:
                result = session.run(cypher, ids=memory_ids)
                records = list(result)

            return [
                {
                    "id": record.get("id", ""),
                    "content": record.get("content", ""),
                    "created_at": record.get("created_at"),
                }
                for record in records
            ]
        except Exception:
            logger.warning("_fetch_memories: 查询失败", exc_info=True)
            return []

    def _extract_template(self, pattern_memories: list[dict]) -> Optional[Skill]:
        """使用 LLM 从重复行为序列提取技能模板。"""
        if not pattern_memories:
            return None

        try:
            from internal.service.language_model_service import LanguageModelService
            from internal.service.memory.llm_activity_probe import (
                LLMActivityProbe,
                LLMActivityTimeoutError,
            )

            # 取前 10 条拼接
            sequences_text = "\n".join(
                f"- {m.get('content', '')}"
                for m in pattern_memories[:10]
            )

            from internal.service.system_prompt_library_service import SystemPromptLibraryService

            prompt = SystemPromptLibraryService().get_prompt_or_default(
                "memory_skill_extraction_prompt"
            ).format(sequences=sequences_text)

            llm = LanguageModelService.get_feature_model("memory_skill_emergence")
            response = LLMActivityProbe.invoke_with_probe(
                llm, prompt, feature_key="memory_skill_emergence"
            )
            content = response.content if hasattr(response, "content") else str(response)

            data = json.loads(content)

            name = data.get("name", "")
            if not name:
                return None

            skill_id = f"skill_{hashlib.md5(name.encode('utf-8')).hexdigest()[:12]}"

            return Skill(
                skill_id=skill_id,
                name=name,
                description=data.get("description", ""),
                template=data.get("template", ""),
                parameters=data.get("parameters", []) or [],
                status=SkillStatus.CANDIDATE,
                use_count=0,
                maturity=0.0,
            )
        except LLMActivityTimeoutError as exc:
            logger.warning(
                "_extract_template: LLM 探针检测到死机，终止写入（不写垃圾）: %s",
                exc,
            )
            return None
        except Exception:
            logger.warning("_extract_template: LLM 提取失败", exc_info=True)
            return None

    def _update_skill(self, existing: Skill, new_evidence: dict) -> Optional[Skill]:
        """根据新证据增量更新已有技能。"""
        try:
            # 更新 frequency（取 max）、use_count、时间戳
            new_freq = new_evidence.get("frequency", existing.frequency)
            existing.frequency = max(existing.frequency, new_freq)
            existing.use_count += 1
            existing.last_used_at = datetime.utcnow()
            existing.last_updated_at = datetime.utcnow()

            # 重新计算 maturity
            existing.maturity = self._compute_maturity(existing)

            # 新记忆数 > 2 时调用 LLM 判定
            new_memories = new_evidence.get("memory_ids", [])
            if len(new_memories) > 2:
                action = self._llm_update_judgment(existing, new_memories)
                if action == "deprecate":
                    existing.status = SkillStatus.DEPRECATED
                elif action == "update":
                    # LLM 可能返回更新字段，此处简化处理
                    pass
                # keep: 不变

            # 状态转移
            existing.status = self._transition_status(existing)

            # 持久化
            self._persist_skill(existing)

            return existing
        except Exception:
            logger.warning("_update_skill: 更新失败", exc_info=True)
            return existing

    def _llm_update_judgment(self, skill: Skill, new_memory_ids: list[str]) -> str:
        """调用 LLM 判断技能更新操作（keep/update/deprecate）。"""
        try:
            from internal.service.language_model_service import LanguageModelService
            from internal.service.memory.llm_activity_probe import (
                LLMActivityProbe,
                LLMActivityTimeoutError,
            )

            memories = self._fetch_memories(new_memory_ids[:5])
            new_evidence_text = "\n".join(f"- {m.get('content', '')}" for m in memories)

            from internal.service.system_prompt_library_service import SystemPromptLibraryService

            prompt = SystemPromptLibraryService().get_prompt_or_default(
                "memory_skill_update_prompt"
            ).format(
                name=skill.name,
                description=skill.description,
                template=skill.template,
                new_evidence=new_evidence_text,
            )

            llm = LanguageModelService.get_feature_model("memory_skill_emergence")
            response = LLMActivityProbe.invoke_with_probe(
                llm, prompt, feature_key="memory_skill_emergence"
            )
            content = response.content if hasattr(response, "content") else str(response)

            data = json.loads(content)
            return data.get("action", "keep")
        except LLMActivityTimeoutError as exc:
            logger.warning(
                "_llm_update_judgment: LLM 探针检测到死机，默认 keep（不写垃圾）: %s",
                exc,
            )
            return "keep"
        except Exception:
            logger.warning("_llm_update_judgment: LLM 判断失败，默认 keep", exc_info=True)
            return "keep"

    def _compute_maturity(self, skill: Skill) -> float:
        """计算技能成熟度（[0, 1] 范围）。

        freq_factor = log1p(frequency) / log(10)
        usage_factor = log1p(use_count) / log(20)
        recency_factor = 0.9 ** days_since_last_use
        raw = freq_factor * 0.4 + usage_factor * 0.4 + recency_factor * 0.2
        return sigmoid(5 * (raw - 0.5))
        """
        freq_factor = math.log1p(skill.frequency) / math.log(10)

        usage_factor = math.log1p(skill.use_count) / math.log(20)

        if skill.last_used_at is not None:
            now = datetime.utcnow()
            if isinstance(skill.last_used_at, datetime):
                days_since = (now - skill.last_used_at).days
            else:
                days_since = 0
            recency_factor = 0.9 ** days_since
        else:
            recency_factor = 1.0

        raw = freq_factor * 0.4 + usage_factor * 0.4 + recency_factor * 0.2
        maturity = 1.0 / (1.0 + math.exp(-5.0 * (raw - 0.5)))

        return max(0.0, min(1.0, maturity))

    def _transition_status(self, skill: Skill) -> SkillStatus:
        """根据当前状态和属性执行状态转移。"""
        current = skill.status

        # CANDIDATE + template 非空 → EMERGING
        if current == SkillStatus.CANDIDATE and skill.template:
            if SkillStatus.EMERGING in SKILL_TRANSITIONS.get(current, []):
                return SkillStatus.EMERGING

        # EMERGING + maturity >= active_threshold → ACTIVE
        if current == SkillStatus.EMERGING and skill.maturity >= self._config.maturity_active_threshold:
            if SkillStatus.ACTIVE in SKILL_TRANSITIONS.get(current, []):
                return SkillStatus.ACTIVE

        # ACTIVE + last_used_at 距今 > stale_days → STALE
        if current == SkillStatus.ACTIVE and skill.last_used_at is not None:
            if isinstance(skill.last_used_at, datetime):
                days_since = (datetime.utcnow() - skill.last_used_at).days
                if days_since > self._config.stale_days:
                    if SkillStatus.STALE in SKILL_TRANSITIONS.get(current, []):
                        return SkillStatus.STALE

        # STALE + 最近 24h 内使用 → ACTIVE
        if current == SkillStatus.STALE and skill.last_used_at is not None:
            if isinstance(skill.last_used_at, datetime):
                hours_since = (datetime.utcnow() - skill.last_used_at).total_seconds() / 3600
                if hours_since < 24:
                    if SkillStatus.ACTIVE in SKILL_TRANSITIONS.get(current, []):
                        return SkillStatus.ACTIVE

        return current

    def _persist_skill(self, skill: Skill) -> None:
        """持久化技能到 Neo4j 并失效 Redis 缓存。"""
        driver = self._get_driver()
        if driver is None:
            return

        try:
            cypher = """
            MERGE (s:Skill {id: $skill_id})
            SET s.name = $name,
                s.description = $description,
                s.template = $template,
                s.parameters = $parameters,
                s.user_id = $user_id,
                s.status = $status,
                s.maturity = $maturity,
                s.use_count = $use_count,
                s.frequency = $frequency,
                s.first_seen_at = $first_seen_at,
                s.last_used_at = $last_used_at,
                s.last_updated_at = $last_updated_at,
                s.source_memories = $source_memories
            """

            with driver.session() as session:
                session.run(
                    cypher,
                    {
                        "skill_id": skill.skill_id,
                        "name": skill.name,
                        "description": skill.description,
                        "template": skill.template,
                        "parameters": skill.parameters,
                        "user_id": skill.user_id,
                        "status": skill.status.value,
                        "maturity": skill.maturity,
                        "use_count": skill.use_count,
                        "frequency": skill.frequency,
                        "first_seen_at": skill.first_seen_at,
                        "last_used_at": skill.last_used_at,
                        "last_updated_at": skill.last_updated_at,
                        "source_memories": skill.source_memories,
                    },
                ).consume()

            # 失效 Redis 缓存
            if self._redis is not None:
                try:
                    self._redis.delete(f"skill:pool:{skill.user_id}")
                except Exception:
                    logger.warning("_persist_skill: Redis 缓存失效失败", exc_info=True)
        except Exception:
            logger.warning("_persist_skill: 持久化失败", exc_info=True)

    def _node_to_skill(self, node: dict) -> Optional[Skill]:
        """将 Neo4j 节点转换为 Skill 对象。"""
        try:
            status_str = node.get("status", "candidate")
            try:
                status = SkillStatus(status_str)
            except ValueError:
                status = SkillStatus.CANDIDATE

            return Skill(
                skill_id=node.get("id", ""),
                name=node.get("name", ""),
                description=node.get("description", ""),
                template=node.get("template", ""),
                parameters=node.get("parameters", []) or [],
                user_id=node.get("user_id", ""),
                status=status,
                maturity=float(node.get("maturity", 0.0)),
                use_count=int(node.get("use_count", 0)),
                frequency=int(node.get("frequency", 0)),
                first_seen_at=node.get("first_seen_at"),
                last_used_at=node.get("last_used_at"),
                last_updated_at=node.get("last_updated_at"),
                source_memories=node.get("source_memories", []) or [],
            )
        except Exception:
            logger.warning("_node_to_skill: 转换失败", exc_info=True)
            return None

    def _get_driver(self):
        """获取 Neo4j 驱动，不可用时返回 None。"""
        if self._neo4j_driver is not None:
            return self._neo4j_driver
        try:
            from internal.context import current_app

            driver = current_app.extensions.get("neo4j")
            return driver
        except RuntimeError:
            pass
        try:
            from internal.extension.neo4j_extension import get_driver

            return get_driver()
        except Exception:
            logger.warning("_get_driver: 获取 Neo4j 驱动失败", exc_info=True)
            return None

    # =========================================================
    # Curator 周期治理（修复断裂点 ⚠️-3）
    # =========================================================

    def curate_skills(self, user_id: str) -> dict:
        """周期性技能治理：重算成熟度 + 状态转移 + 剪枝。

        合并 Redis 实时使用统计到 Neo4j，重算所有 ACTIVE/STALE 技能的成熟度，
        执行状态转移（ACTIVE→STALE、STALE→DEPRECATED、STALE→ACTIVE 复活）。

        设计参考：docs/prd/memory-system/03-consolidation-skill-policy-api.md §8.7

        Args:
            user_id: 用户标识

        Returns:
            ``{"scanned": int, "transitioned": int, "deprecated": int}``
        """
        driver = self._get_driver()
        if driver is None:
            return {"scanned": 0, "transitioned": 0, "deprecated": 0}

        # 1. 查询所有 ACTIVE/STALE 技能
        try:
            cypher = """
            MATCH (s:Skill {user_id: $user_id})
            WHERE s.status IN ['active', 'stale']
            RETURN s
            """
            with driver.session() as session:
                result = session.run(cypher, {"user_id": user_id})
                records = list(result)
        except Exception:
            logger.warning("curate_skills: 查询技能失败", exc_info=True)
            return {"scanned": 0, "transitioned": 0, "deprecated": 0}

        if not records:
            return {"scanned": 0, "transitioned": 0, "deprecated": 0}

        # 2. 合并 Redis 实时统计 + 重算成熟度 + 状态转移
        redis_stats = self._read_skill_stats(user_id)
        scanned = 0
        transitioned = 0
        deprecated = 0

        for record in records:
            node = record.get("s", {})
            skill = self._node_to_skill(node)
            if skill is None:
                continue

            scanned += 1

            # 合并 Redis 统计
            stat = redis_stats.get(skill.skill_id, {})
            if stat:
                skill.use_count += int(stat.get("use_count", 0))
                redis_last = stat.get("last_used_at")
                if redis_last and (
                    skill.last_used_at is None or redis_last > skill.last_used_at
                ):
                    skill.last_used_at = redis_last

            # 重算成熟度
            old_status = skill.status
            skill.maturity = self._compute_maturity(skill)
            skill.status = self._transition_status(skill)
            skill.last_updated_at = datetime.utcnow()

            if skill.status != old_status:
                transitioned += 1
                if skill.status == SkillStatus.DEPRECATED:
                    deprecated += 1

            # 持久化
            self._persist_skill(skill)

        # 3. 清理已合并的 Redis 统计
        self._clear_skill_stats(user_id)

        logger.info(
            "curate_skills: user=%s scanned=%d transitioned=%d deprecated=%d",
            user_id,
            scanned,
            transitioned,
            deprecated,
        )
        return {
            "scanned": scanned,
            "transitioned": transitioned,
            "deprecated": deprecated,
        }

    def _read_skill_stats(self, user_id: str) -> dict[str, dict]:
        """从 Redis 读取技能实时使用统计（bump_use 累积的计数）。"""
        if not self._redis:
            return {}
        try:
            key = f"skill:stats:{user_id}"
            raw = self._redis.hgetall(key)
            if not raw:
                return {}
            stats: dict[str, dict] = {}
            for field, value in raw.items():
                field_str = field.decode("utf-8") if isinstance(field, bytes) else field
                value_str = value.decode("utf-8") if isinstance(value, bytes) else value
                # field 格式: {skill_id}:use_count 或 {skill_id}:last_used_at
                if ":" not in field_str:
                    continue
                skill_id, metric = field_str.rsplit(":", 1)
                if skill_id not in stats:
                    stats[skill_id] = {}
                if metric == "use_count":
                    stats[skill_id]["use_count"] = int(value_str)
                elif metric == "last_used_at":
                    stats[skill_id]["last_used_at"] = value_str
            return stats
        except Exception:
            logger.warning("_read_skill_stats: 读取失败", exc_info=True)
            return {}

    def _clear_skill_stats(self, user_id: str) -> None:
        """清理已合并的 Redis 统计键。"""
        redis_client = self._get_redis()
        if redis_client is None:
            return
        try:
            redis_client.delete(f"skill:stats:{user_id}")
        except Exception:
            logger.warning("_clear_skill_stats: 清理失败", exc_info=True)

    def _get_redis(self):
        """获取 Redis 客户端，不可用时返回 None。

        优先使用构造函数传入的 ``self._redis``，回退到
        ``current_app.extensions['redis']``，最后回退到全局 ``redis_client``。
        """
        if self._redis is not None:
            return self._redis
        try:
            from internal.context import current_app

            return current_app.extensions.get("redis")
        except RuntimeError:
            pass
        try:
            from internal.extension.redis_extension import redis_client

            return redis_client
        except Exception:
            logger.warning("_get_redis: 获取 Redis 客户端失败", exc_info=True)
            return None

    # =========================================================
    # 基因3: bump_use 实时统计（§8.7）
    # =========================================================

    def bump_use(self, user_id: str, skill_id: str) -> bool:
        """技能使用实时计数（基因3, §8.7）。

        使用 Redis HINCRBY 累加 use_count，HSET 更新 last_used_at。
        高频调用（每次技能被使用/即时涌现触发时），避免频繁写 Neo4j。
        由 ``flush_bump_use_to_neo4j`` 或 ``curate_skills`` 定期合并到 Neo4j。

        设计为"写入侧"，与 ``_read_skill_stats``（读取侧）、
        ``_clear_skill_stats``（清理侧）组成完整的 Redis 统计生命周期。

        Args:
            user_id: 用户标识
            skill_id: 技能 ID

        Returns:
            成功返回 True，Redis 不可用或配置关闭返回 False
        """
        if not self._config.bump_use_redis_enabled:
            return False

        redis_client = self._get_redis()
        if redis_client is None:
            return False

        try:
            key = f"skill:stats:{user_id}"
            now = datetime.utcnow().isoformat()
            pipe = redis_client.pipeline()
            pipe.hincrby(key, f"{skill_id}:use_count", 1)
            pipe.hset(key, f"{skill_id}:last_used_at", now)
            pipe.execute()
            return True
        except Exception:
            logger.warning("bump_use: Redis 计数失败", exc_info=True)
            return False

    def flush_bump_use_to_neo4j(self, user_id: str) -> dict:
        """将 Redis 中的技能使用统计合并到 Neo4j（基因3, §8.7）。

        独立于 ``curate_skills``，只做统计合并，不做 maturity 重算和状态转移。
        将 Redis 中的 use_count 累加到 Neo4j Skill 节点，更新 last_used_at，
        然后清理 Redis。

        设计为高频定时任务（默认每小时），与低频 ``curate_skills``（每周）形成双轨：
        - flush: 高频合并统计，保持 Neo4j use_count 近实时
        - curate: 低频重算 maturity + 状态转移 + 剪枝

        Returns:
            ``{"flushed": int, "errors": int}``
        """
        redis_client = self._get_redis()
        if redis_client is None:
            return {"flushed": 0, "errors": 0}

        driver = self._get_driver()
        if driver is None:
            return {"flushed": 0, "errors": 0}

        # 1. 读取 Redis 统计
        redis_stats = self._read_skill_stats(user_id)
        if not redis_stats:
            return {"flushed": 0, "errors": 0}

        # 2. 逐个合并到 Neo4j
        flushed = 0
        errors = 0
        for skill_id, stat in redis_stats.items():
            try:
                use_count_delta = int(stat.get("use_count", 0))
                last_used_at = stat.get("last_used_at")
                if use_count_delta <= 0:
                    continue

                cypher = """
                MATCH (s:Skill {skill_id: $skill_id, user_id: $user_id})
                SET s.use_count = coalesce(s.use_count, 0) + $delta,
                    s.last_used_at = CASE
                        WHEN $last_used_at IS NOT NULL
                         AND ($last_used_at > coalesce(toString(s.last_used_at), ''))
                        THEN $last_used_at
                        ELSE s.last_used_at
                    END,
                    s.last_updated_at = datetime()
                """
                with driver.session() as session:
                    session.run(cypher, {
                        "skill_id": skill_id,
                        "user_id": user_id,
                        "delta": use_count_delta,
                        "last_used_at": last_used_at,
                    })
                flushed += 1
            except Exception:
                logger.warning(
                    "flush_bump_use_to_neo4j: 合并 %s 失败", skill_id, exc_info=True
                )
                errors += 1

        # 3. 清理已合并的 Redis 统计
        if flushed > 0:
            self._clear_skill_stats(user_id)

        logger.info(
            "flush_bump_use_to_neo4j: user=%s flushed=%d errors=%d",
            user_id, flushed, errors,
        )
        return {"flushed": flushed, "errors": errors}
