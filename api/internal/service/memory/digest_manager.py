"""Memory Digest 管理器（DigestManager）。

维护用户记忆摘要视图，由 Neo4j 重建 + Redis 缓存。
Digest 包含用户画像（含显式陈述分组）、已习得技能、近期事件、待办任务，作为
System 1 快速路径与对话 system prompt 注入的数据源。

显式陈述分组渲染（记忆写入优化）:
    用户画像部分整合显式陈述记忆，按 category + polarity 分组为
    偏好/厌恶/习惯/身份/目标/能力 六组展示，无 token 预算硬限制（用户体验优先）。

缓存策略:
    - Redis 缓存键: ``memory:digest:{user_id}``，TTL=300s
    - 缓存命中直接返回，miss 则从 Neo4j 重建

降级策略:
    - Redis 不可用时直接走 Neo4j 重建
    - Neo4j 不可用时返回空字符串
    - LLM 渲染异常时使用模板拼接（不调 LLM）

设计参考:
    docs/prd/memory-system/02-storage-and-retrieval.md §6.5
    docs/prd/memory-system/execution/03-track-b-storage-retrieval.md B6
    docs/prd/memory-write-optimization-design.md §5.8
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from dataclasses import dataclass
from injector import inject
from redis import Redis

from internal.config.memory_settings import settings
from internal.service.language_model_service import LanguageModelService
from internal.service.memory.metrics import MetricsCollector

logger = logging.getLogger(__name__)


@inject
@dataclass
class DigestManager:
    """Memory Digest 管理器。

    依赖注入:
        redis_client: Redis 实例（缓存层）
        Neo4j 驱动通过 ``current_app.extensions['neo4j']`` 获取，不在构造函数注入
    """

    redis_client: Redis

    # =========================================================
    # 主入口
    # =========================================================

    def get_digest(self, user_id: str) -> str:
        """先查 Redis 缓存，miss 则调用 update_digest 重建。

        Args:
            user_id: 用户标识

        Returns:
            Digest 文本字符串，不可用时返回空字符串
        """
        cache_key = self._cache_key(user_id)

        # 1. 查 Redis 缓存
        try:
            cached = self.redis_client.get(cache_key)
            if cached is not None:
                MetricsCollector.record_digest_cache(hit=True)
                if isinstance(cached, bytes):
                    cached = cached.decode("utf-8")
                data = json.loads(cached)
                return data.get("text", "")
        except Exception:
            logger.warning(
                "get_digest: Redis 缓存读取失败 user=%s，将走重建路径",
                user_id,
                exc_info=True,
            )

        # 2. 缓存 miss，重建
        MetricsCollector.record_digest_cache(hit=False)
        try:
            return self.update_digest(user_id)
        except Exception:
            logger.warning(
                "get_digest: 重建 Digest 失败 user=%s", user_id, exc_info=True
            )
            return ""

    def update_digest(self, user_id: str) -> str:
        """从 Neo4j 查 4 部分 → 渲染 → 写 Redis。

        Args:
            user_id: 用户标识

        Returns:
            渲染后的 Digest 文本
        """
        # 1. 从 Neo4j 拉取数据（含显式陈述分组）
        profile = self._fetch_profile(user_id)
        skills = self._fetch_skills(user_id)
        events = self._fetch_recent_episodes(user_id)
        tasks = self._fetch_tasks(user_id)

        # 2. 渲染 Digest
        digest_text = self._render_digest(profile, skills, events, tasks)

        # 3. Token 计数与截断（enforce_token_limit=False 时不截断，用户体验优先）
        token_count = self._count_tokens(digest_text)
        max_tokens = settings.digest.max_tokens
        if settings.digest.enforce_token_limit and token_count > max_tokens:
            digest_text = self._truncate_digest(
                digest_text, profile, skills, events, tasks, max_tokens
            )
            token_count = self._count_tokens(digest_text)

        # 4. 基因5: 检查并注入 Nudge Prompt（§2.6）
        # Nudge Prompt 在截断后追加，确保不被截断。读取后自动消费（删除），
        # 每条 Nudge 只注入一次。Agent 看到后可自主调用 memory_add 记录有价值信息。
        try:
            from internal.service.memory.post_execution_hook import NudgeEvaluator

            nudge_prompt = NudgeEvaluator.consume_nudge_prompt(user_id)
            if nudge_prompt:
                digest_text += f"\n\n{nudge_prompt}"
                token_count = self._count_tokens(digest_text)
        except Exception:
            logger.warning("Nudge Prompt 注入失败", exc_info=True)

        # 5. 写 Redis 缓存
        cache_key = self._cache_key(user_id)
        cache_data = json.dumps(
            {
                "text": digest_text,
                "tokens": token_count,
                "updated_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        )
        try:
            self.redis_client.set(
                cache_key,
                cache_data,
                ex=settings.digest.cache_ttl_seconds,
            )
        except Exception:
            logger.warning(
                "update_digest: Redis 缓存写入失败 user=%s", user_id, exc_info=True
            )

        return digest_text

    # =========================================================
    # Neo4j 数据拉取
    # =========================================================

    def _fetch_profile(self, user_id: str) -> str:
        """查用户画像（显式陈述分组 + Entity 节点 type='person'/'profile'）。

        优先渲染显式陈述分组（偏好/厌恶/习惯/身份/目标/能力），再补充 Entity 画像。
        无数据返回 "暂无用户画像数据"。
        """
        parts = []

        # 1. 显式陈述分组渲染（记忆写入优化 §5.8）
        explicit_profile = self._fetch_explicit_memories(user_id)
        if explicit_profile:
            parts.append(explicit_profile)

        # 2. Entity 画像补充
        entity_profile = self._fetch_entity_profile(user_id)
        if entity_profile and entity_profile != "暂无用户画像数据":
            parts.append(entity_profile)

        return "\n".join(parts) if parts else "暂无用户画像数据"

    def _fetch_explicit_memories(self, user_id: str) -> str:
        """查询带 explicit_category 属性的 Episode 节点，按 category + polarity 分组渲染。

        Cypher 过滤 t_invalidated_at IS NULL，排除已被写时冲突解决标记的失效记忆。
        无数据返回空字符串。
        """
        driver = self._get_driver()
        if driver is None:
            return ""

        try:
            cypher = """
            MATCH (e:Episode {user_id: $user_id})
            WHERE e.explicit_category IS NOT NULL
              AND e.t_invalidated_at IS NULL
              AND (e.status IS NULL OR NOT (e.status IN ['superseded', 'deprecated']))
            RETURN e.explicit_category AS category,
                   e.explicit_polarity AS polarity,
                   e.content AS content,
                   e.summary AS summary
            ORDER BY e.created_at DESC
            LIMIT $limit
            """
            with driver.session() as session:
                result = session.run(
                    cypher,
                    {"user_id": user_id, "limit": settings.digest.explicit_max_items},
                )
                records = list(result)

            if not records:
                return ""

            return self._render_explicit_profile(records)
        except Exception:
            logger.warning("_fetch_explicit_memories: 查询失败", exc_info=True)
            return ""

    @staticmethod
    def _render_explicit_profile(records: list) -> str:
        """按 category + polarity 分组渲染显式陈述为六组结构化文本。

        分组: 偏好(preference+positive) / 厌恶(aversion或preference+negative) /
              习惯(habit) / 身份(identity) / 目标(goal) / 能力(capability)
        """
        groups: dict[str, list[str]] = {
            "偏好": [],
            "厌恶": [],
            "习惯": [],
            "身份": [],
            "目标": [],
            "能力": [],
        }

        for record in records:
            category = record.get("category", "") or ""
            polarity = record.get("polarity", "") or ""
            summary = record.get("summary") or record.get("content") or ""

            if not summary:
                continue

            if category == "preference" and polarity == "negative":
                groups["厌恶"].append(summary)
            elif category == "aversion":
                groups["厌恶"].append(summary)
            elif category == "preference":
                groups["偏好"].append(summary)
            elif category == "habit":
                groups["习惯"].append(summary)
            elif category == "identity":
                groups["身份"].append(summary)
            elif category == "goal":
                groups["目标"].append(summary)
            elif category == "capability":
                groups["能力"].append(summary)
            elif category == "meta_instruction":
                # 元指令归入偏好组
                groups["偏好"].append(summary)

        lines = []
        for group_name, items in groups.items():
            if items:
                lines.append(f"【{group_name}】{'、'.join(items)}")

        return "\n".join(lines)

    def _fetch_entity_profile(self, user_id: str) -> str:
        """查 Entity 画像（type='person' 或 'profile'），作为显式陈述的补充。

        无数据返回 "暂无用户画像数据"。
        """
        driver = self._get_driver()
        if driver is None:
            return "暂无用户画像数据"

        try:
            cypher = """
            MATCH (e:Entity {user_id: $user_id})
            WHERE e.type IN ['person', 'profile', 'user']
            RETURN e.name AS name, e.summary AS summary
            LIMIT $limit
            """
            with driver.session() as session:
                result = session.run(
                    cypher,
                    {"user_id": user_id, "limit": settings.digest.profile_max_items},
                )
                records = list(result)

            if not records:
                return "暂无用户画像数据"

            lines = []
            for record in records:
                name = record.get("name", "")
                summary = record.get("summary", "")
                if summary:
                    lines.append(f"- {name}: {summary[:100]}")
                else:
                    lines.append(f"- {name}")

            return "\n".join(lines) if lines else "暂无用户画像数据"
        except Exception:
            logger.warning("_fetch_entity_profile: 查询失败", exc_info=True)
            return "暂无用户画像数据"

    def _fetch_skills(self, user_id: str) -> str:
        """查活跃技能 Tier0 摘要（基因2, §8.6）。

        Tier0 只注入 name + description + use_count，不加载 template/parameters，
        控制 context 成本。Agent 可通过 ``get_skill_detail`` 工具按需加载 Tier1/Tier2。

        优先从 Redis 缓存读取（key: skill:pool:{user_id}）。
        无数据返回 "暂无已习得技能"。
        """
        # 优先从 Redis 缓存读取
        if self.redis_client is not None:
            try:
                cached = self.redis_client.get(f"skill:pool:{user_id}")
                if cached:
                    cached_text = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                    if cached_text:
                        return cached_text
            except Exception:
                logger.warning("_fetch_skills: Redis 缓存读取失败", exc_info=True)

        driver = self._get_driver()
        if driver is None:
            return "暂无已习得技能"

        try:
            # Tier0: 只查摘要字段，不查 template（减少查询开销与 context 占用）
            cypher = """
            MATCH (s:Skill {user_id: $user_id})
            WHERE s.status = 'active'
            RETURN s.name AS name, s.description AS description,
                   s.use_count AS use_count
            ORDER BY s.maturity DESC, s.use_count DESC
            LIMIT $limit
            """
            tier0_max = settings.digest.skill_tier0_max_items
            with driver.session() as session:
                result = session.run(
                    cypher,
                    {"user_id": user_id, "limit": tier0_max},
                )
                records = list(result)

            if not records:
                return "暂无已习得技能"

            lines = []
            for record in records:
                name = record.get("name", "")
                desc = record.get("description", "")
                count = record.get("use_count", 0)
                if desc:
                    lines.append(f"- {name}: {desc} (使用: {count}次)")
                else:
                    lines.append(f"- {name} (使用: {count}次)")

            # Tier0 提示：引导 Agent 使用 get_skill_detail 工具加载详情
            if lines:
                lines.append("（如需技能模板与参数详情，调用 get_skill_detail 工具）")

            skills_text = "\n".join(lines) if lines else "暂无已习得技能"

            # 写回 Redis 缓存（TTL 5min）
            if self.redis_client is not None:
                try:
                    self.redis_client.setex(f"skill:pool:{user_id}", 300, skills_text)
                except Exception:
                    logger.warning("_fetch_skills: Redis 缓存写入失败", exc_info=True)

            return skills_text
        except Exception:
            logger.warning("_fetch_skills: 查询失败", exc_info=True)
            return "暂无已习得技能"

    def get_skill_detail(self, user_id: str, skill_name: str, tier: int = 1) -> str:
        """基因2: 按需加载技能详情（Tier1/Tier2, §8.6）。

        与 ``_fetch_skills``（Tier0 摘要注入）配合实现 Progressive Disclosure：
        - Tier0: Digest 注入 name + description + use_count（每轮对话自动）
        - Tier1: Agent 调用本方法查看 template + parameters（按需）
        - Tier2: Agent 调用本方法查看 source_memories + 相关 Episode（深度按需）

        Args:
            user_id: 用户标识
            skill_name: 技能名称（支持 CONTAINS 模糊匹配）
            tier: 加载层级（1=模板+参数，2=模板+参数+来源记忆）

        Returns:
            技能详情文本，未找到返回提示信息
        """
        driver = self._get_driver()
        if driver is None:
            return "技能详情不可用：图存储未连接"

        try:
            if tier <= 1:
                # Tier1: template + parameters
                cypher = """
                MATCH (s:Skill {user_id: $user_id})
                WHERE s.status IN ['active', 'emerging']
                  AND s.name CONTAINS $skill_name
                RETURN s.name AS name, s.description AS description,
                       s.template AS template, s.parameters AS parameters,
                       s.use_count AS use_count, s.maturity AS maturity
                LIMIT 1
                """
            else:
                # Tier2: template + parameters + source_memories
                cypher = """
                MATCH (s:Skill {user_id: $user_id})
                WHERE s.status IN ['active', 'emerging']
                  AND s.name CONTAINS $skill_name
                RETURN s.name AS name, s.description AS description,
                       s.template AS template, s.parameters AS parameters,
                       s.use_count AS use_count, s.maturity AS maturity,
                       s.source_memories AS source_memories
                LIMIT 1
                """

            with driver.session() as session:
                result = session.run(
                    cypher,
                    {"user_id": user_id, "skill_name": skill_name[:50]},
                )
                record = result.single()

            if record is None:
                return f"未找到名称包含 '{skill_name}' 的技能"

            name = record.get("name", "")
            desc = record.get("description", "")
            template = record.get("template", "")
            parameters = record.get("parameters", [])
            use_count = record.get("use_count", 0)
            maturity = record.get("maturity", 0.0)

            lines = [
                f"技能: {name}",
                f"描述: {desc}",
                f"使用次数: {use_count}, 成熟度: {maturity:.2f}",
            ]

            if template:
                lines.append(f"模板:\n{template}")

            if parameters:
                param_text = self._format_parameters(parameters)
                if param_text:
                    lines.append(f"参数:\n{param_text}")

            # Tier2: 加载 source_memories 内容
            if tier >= 2:
                source_memories = record.get("source_memories", [])
                if source_memories:
                    memory_texts = self._fetch_memory_contents(source_memories[:5])
                    if memory_texts:
                        lines.append(f"来源记忆:\n{memory_texts}")

            return "\n".join(lines)
        except Exception:
            logger.warning("get_skill_detail: 查询失败", exc_info=True)
            return "技能详情查询失败"

    @staticmethod
    def _format_parameters(parameters) -> str:
        """格式化参数列表为文本。"""
        if not parameters:
            return ""
        try:
            if isinstance(parameters, str):
                params = json.loads(parameters)
            else:
                params = parameters
            if not isinstance(params, list):
                return str(params)
            lines = []
            for p in params:
                if isinstance(p, dict):
                    name = p.get("name", "")
                    ptype = p.get("type", "")
                    pdesc = p.get("description", "")
                    lines.append(f"  - {name} ({ptype}): {pdesc}")
                else:
                    lines.append(f"  - {p}")
            return "\n".join(lines)
        except Exception:
            return str(parameters)

    def _fetch_memory_contents(self, memory_ids: list[str]) -> str:
        """批量获取记忆节点内容（用于 Tier2 深度加载）。"""
        if not memory_ids:
            return ""
        driver = self._get_driver()
        if driver is None:
            return ""
        try:
            cypher = """
            UNWIND $ids AS mid
            MATCH (n) WHERE (n:MemoryNode OR n:Episode) AND n.node_id = mid
            RETURN n.content AS content, n.summary AS summary
            LIMIT 10
            """
            with driver.session() as session:
                result = session.run(cypher, ids=memory_ids)
                records = list(result)
            lines = []
            for r in records:
                text = r.get("summary") or r.get("content") or ""
                if text:
                    lines.append(f"  - {text[:100]}")
            return "\n".join(lines)
        except Exception:
            logger.warning("_fetch_memory_contents: 查询失败", exc_info=True)
            return ""

    def _fetch_recent_episodes(self, user_id: str) -> str:
        """查近期事件（Episode 节点，storage_tier IN ['hot','warm'] 或 IS NULL）。

        无数据返回 "暂无近期事件"。
        """
        driver = self._get_driver()
        if driver is None:
            return "暂无近期事件"

        try:
            cypher = """
            MATCH (e:Episode {user_id: $user_id})
            WHERE e.storage_tier IS NULL OR e.storage_tier IN ['hot', 'warm']
            RETURN e.summary AS summary, e.content AS content, e.created_at AS created_at
            ORDER BY e.created_at DESC
            LIMIT $limit
            """
            with driver.session() as session:
                result = session.run(
                    cypher,
                    {"user_id": user_id, "limit": settings.digest.events_max_items},
                )
                records = list(result)

            if not records:
                return "暂无近期事件"

            lines = []
            for record in records:
                summary = record.get("summary") or record.get("content") or ""
                created_at = record.get("created_at", "")
                # 格式化时间
                time_str = ""
                if created_at:
                    try:
                        if isinstance(created_at, str):
                            time_str = created_at[:16]
                        else:
                            time_str = str(created_at)[:16]
                    except Exception:
                        time_str = ""
                lines.append(f"- [{time_str}] {summary[:100]}")

            return "\n".join(lines) if lines else "暂无近期事件"
        except Exception:
            logger.warning("_fetch_recent_episodes: 查询失败", exc_info=True)
            return "暂无近期事件"

    def _fetch_tasks(self, user_id: str) -> str:
        """查任务状态（Entity 节点中 type='task'）。

        无数据返回 "暂无待办任务"。
        """
        driver = self._get_driver()
        if driver is None:
            return "暂无待办任务"

        try:
            cypher = """
            MATCH (e:Entity {user_id: $user_id})
            WHERE e.type IN ['task', 'todo']
            RETURN e.name AS name, e.summary AS summary
            LIMIT $limit
            """
            with driver.session() as session:
                result = session.run(
                    cypher,
                    {"user_id": user_id, "limit": settings.digest.tasks_max_items},
                )
                records = list(result)

            if not records:
                return "暂无待办任务"

            lines = []
            for record in records:
                name = record.get("name", "")
                summary = record.get("summary", "")
                if summary:
                    lines.append(f"- {name}: {summary[:80]}")
                else:
                    lines.append(f"- {name}")

            return "\n".join(lines) if lines else "暂无待办任务"
        except Exception:
            logger.warning("_fetch_tasks: 查询失败", exc_info=True)
            return "暂无待办任务"

    # =========================================================
    # 渲染
    # =========================================================

    def _render_digest(
        self,
        profile: str,
        skills: str,
        events: str,
        tasks: str,
    ) -> str:
        """渲染 Digest 为结构化文本。

        优先使用模板拼接，可选调用 LLM 进一步精炼。
        """
        # 模板拼接
        from internal.service.system_prompt_library_service import SystemPromptLibraryService

        digest_template = SystemPromptLibraryService().get_prompt_or_default(
            "memory_digest_template"
        )
        text = digest_template.format(
            updated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
            profile=profile,
            skills=skills,
            events=events,
            tasks=tasks,
        )

        # 可选：调用 LLM 精炼（探针检测到死机或异常时使用模板结果）
        from internal.service.memory.llm_activity_probe import (
            LLMActivityProbe,
            LLMActivityTimeoutError,
        )

        try:
            llm = LanguageModelService.get_feature_model("memory_digest")
            from internal.service.system_prompt_library_service import SystemPromptLibraryService
            prompt = SystemPromptLibraryService().get_prompt_or_default(
                "memory_digest_refine_prompt"
            ).format(text=text)
            result = LLMActivityProbe.invoke_with_probe(
                llm, prompt, feature_key="memory_digest"
            )
            content = getattr(result, "content", None)
            if content and len(content) > 50:
                return content
        except LLMActivityTimeoutError as exc:
            logger.warning(
                "_render_digest: LLM 探针检测到死机，使用模板结果（不写垃圾）: %s",
                exc,
            )
        except Exception:
            logger.warning("_render_digest: LLM 精炼失败，使用模板结果", exc_info=True)

        return text

    # =========================================================
    # 辅助方法
    # =========================================================

    def _cache_key(self, user_id: str) -> str:
        """构造 Redis 缓存键。"""
        return f"{settings.digest.cache_key_prefix}{user_id}"

    @staticmethod
    def _count_tokens(text: str) -> int:
        """估算文本 token 数。

        优先使用 tiktoken，不可用时按 1.5 中文字符 / 4 英文字符估算。
        """
        if not text:
            return 0
        try:
            import tiktoken

            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except Exception:
            # 简化估算
            chinese_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
            other_count = len(text) - chinese_count
            return int(chinese_count * 1.5 + other_count / 4)

    def _truncate_digest(
        self,
        full_text: str,
        profile: str,
        skills: str,
        events: str,
        tasks: str,
        max_tokens: int,
    ) -> str:
        """超过 max_tokens 时按段截断（优先保留画像与技能）。"""
        from internal.service.system_prompt_library_service import SystemPromptLibraryService

        digest_template = SystemPromptLibraryService().get_prompt_or_default(
            "memory_digest_template"
        )
        # 逐步缩减 events 和 tasks
        for reduce_factor in [0.5, 0.25, 0.1, 0.0]:
            truncated_events = "\n".join(events.split("\n")[: max(1, int(len(events.split("\n")) * reduce_factor))])
            truncated_tasks = "\n".join(tasks.split("\n")[: max(1, int(len(tasks.split("\n")) * reduce_factor))])
            text = digest_template.format(
                updated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
                profile=profile,
                skills=skills,
                events=truncated_events,
                tasks=truncated_tasks,
            )
            if self._count_tokens(text) <= max_tokens:
                return text

        # 最终兜底：仅保留画像
        return digest_template.format(
            updated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
            profile=profile,
            skills="",
            events="",
            tasks="",
        )

    def _get_driver(self):
        """获取 Neo4j 驱动，不可用时返回 None。"""
        try:
            from internal.context import current_app

            driver = current_app.extensions.get("neo4j")
            if driver is not None:
                return driver
        except RuntimeError:
            pass
        try:
            from internal.extension.neo4j_extension import get_driver

            return get_driver()
        except Exception:
            logger.warning("_get_driver: 获取 Neo4j 驱动失败", exc_info=True)
            return None
