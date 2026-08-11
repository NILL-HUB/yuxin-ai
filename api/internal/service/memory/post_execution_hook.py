"""对话后即时技能涌现钩子（基因1, §8.5）+ 周期性 Nudge（基因5, §2.6）。

挂在 AssistantAgentService._write_memory_from_conversation 之后，
检查触发条件，满足时异步调用 SkillEmergence 做即时涌现。
形成"即时涌现 + 批量巩固"双路径。

基因5（周期性 Nudge）: 对话满足条件时生成 Nudge Prompt 存入 Redis，
下一轮对话通过 Digest 注入，提示 Agent 调用 memory_add 记录有价值信息。

灵感来源：Hermes Agent — "Autonomous skill creation after complex tasks"
实施优先级：P0
依赖：断裂点 ⚠️-1 已修复（SkillEmergence.scan_and_emerge 已接通巩固引擎）

设计参考：docs/prd/memory-system/03-consolidation-skill-policy-api.md §8.5 §2.6
"""

import logging
from datetime import UTC, datetime
from threading import Thread
from typing import Optional

from internal.config.memory_settings import WriteConfig
from internal.service.memory.skill_emergence import SkillConfig, SkillEmergence

logger = logging.getLogger(__name__)


class NudgeEvaluator:
    """周期性 Nudge 评估器（基因5, §2.6）。

    评估对话是否满足 Nudge 触发条件，满足时生成 Nudge Prompt 存入 Redis。
    下一轮对话通过 DigestManager 读取并注入到 system prompt，
    提示 Agent 反思并调用 memory_add 记录有价值信息。

    触发条件（全部满足）:
        - 对话轮数 >= nudge_min_conversation_turns
        - 工具调用次数 >= nudge_min_tool_calls
        - 本会话已 nudge 次数 < nudge_max_per_session

    Redis 键设计:
        - 会话统计: nudge:stats:{user_id}:{conversation_id} → Hash {turns, tool_calls, nudge_count}
        - Nudge Prompt: nudge:prompt:{user_id} → String（TTL=1h）
    """

    def __init__(self, config: Optional[WriteConfig] = None):
        self._config = config or WriteConfig()

    def maybe_nudge(
        self,
        user_id: str,
        conversation_id: str,
        ai_response: str,
    ) -> None:
        """评估对话条件，满足时生成 Nudge Prompt 存入 Redis。

        完全静默，失败不影响主流程。

        Args:
            user_id: 用户标识
            conversation_id: 会话 ID
            ai_response: Agent 本次回复（用于检测工具调用次数）
        """
        if not self._config.nudge_enabled:
            return

        try:
            redis_client = self._get_redis()
            if redis_client is None:
                return

            stats_key = f"nudge:stats:{user_id}:{conversation_id}"

            # 1. 累加对话轮数
            pipe = redis_client.pipeline()
            pipe.hincrby(stats_key, "turns", 1)

            # 2. 检测工具调用次数（从 ai_response 中计数）
            tool_call_count = ai_response.lower().count("tool_call") + ai_response.count("```")
            if tool_call_count > 0:
                pipe.hincrby(stats_key, "tool_calls", tool_call_count)

            # TTL 24h（会话级）
            pipe.expire(stats_key, 86400)
            pipe.execute()

            # 3. 读取累计统计
            stats = redis_client.hgetall(stats_key)
            turns = int(stats.get(b"turns", stats.get("turns", 0)))
            tool_calls = int(stats.get(b"tool_calls", stats.get("tool_calls", 0)))
            nudge_count = int(stats.get(b"nudge_count", stats.get("nudge_count", 0)))

            # 4. 评估触发条件
            if (
                turns < self._config.nudge_min_conversation_turns
                or tool_calls < self._config.nudge_min_tool_calls
                or nudge_count >= self._config.nudge_max_per_session
            ):
                return

            # 5. 生成 Nudge Prompt 存入 Redis
            prompt = self._build_nudge_prompt(turns, tool_calls)
            prompt_key = f"nudge:prompt:{user_id}"
            redis_client.setex(prompt_key, 3600, prompt)  # TTL=1h

            # 6. 累加 nudge_count
            redis_client.hincrby(stats_key, "nudge_count", 1)

            logger.info(
                "Nudge 已触发: user=%s conv=%s turns=%d tool_calls=%d nudge_count=%d",
                user_id, conversation_id, turns, tool_calls, nudge_count + 1,
            )
        except Exception:
            logger.warning("Nudge 评估失败，不影响主流程", exc_info=True)

    @staticmethod
    def _build_nudge_prompt(turns: int, tool_calls: int) -> str:
        """生成 Nudge Prompt（系统提示词库可管理，YAML 兜底）。"""
        from internal.service.system_prompt_library_service import SystemPromptLibraryService
        return SystemPromptLibraryService().get_prompt_or_default(
            "memory_nudge_prompt"
        ).format(turns=turns, tool_calls=tool_calls)

    def _get_redis(self):
        """获取 Redis 客户端，不可用时返回 None。"""
        try:
            from internal.context import current_app

            return current_app.extensions.get("redis")
        except RuntimeError:
            pass
        try:
            from internal.extension.redis_extension import redis_client

            return redis_client
        except Exception:
            return None

    @staticmethod
    def consume_nudge_prompt(user_id: str) -> str:
        """读取并消费 Nudge Prompt（供 DigestManager 调用）。

        读取后删除 Redis 中的 Prompt，确保每条 Nudge 只注入一次。

        Args:
            user_id: 用户标识

        Returns:
            Nudge Prompt 文本，无则返回空字符串
        """
        try:
            from internal.context import current_app

            redis_client = current_app.extensions.get("redis")
            if redis_client is None:
                return ""
            prompt_key = f"nudge:prompt:{user_id}"
            prompt = redis_client.get(prompt_key)
            if prompt is None:
                return ""
            if isinstance(prompt, bytes):
                prompt = prompt.decode("utf-8")
            # 读取后删除，确保只注入一次
            redis_client.delete(prompt_key)
            return prompt
        except Exception:
            return ""


class PostExecutionHook:
    """对话后即时技能涌现钩子 + 周期性 Nudge。

    基因1（即时涌现）触发条件（满足任一）:
        - 用户纠正 Agent 输出（query 中有纠正信号）
        - 复杂任务（ai_response 较长或包含代码块/工具调用痕迹）
        - 非显而易见的工作流（novel workflow detection）

    基因5（Nudge）触发条件（全部满足）:
        - 对话轮数 >= nudge_min_conversation_turns
        - 工具调用次数 >= nudge_min_tool_calls
        - 本会话已 nudge 次数 < nudge_max_per_session

    触发后异步执行:
        1. 收集执行轨迹（从最近的 Episode 节点）
        2. 调用 SkillEmergence._extract_template() 提取技能模板
        3. 查找已有 Skill（_find_existing_skill）
        4. 命中 → bump_use / 未命中 → _persist_skill
        5. Nudge 评估，满足时生成 Prompt 存入 Redis
        6. 完全静默，用户无感
    """

    # 用户纠正信号关键词（命中任一即触发）
    _CORRECTION_SIGNALS = frozenset({
        "不对", "错了", "不是这样", "重新", "纠正", "不是",
        "no,", "wrong", "incorrect", "not right", "redo",
    })

    def __init__(
        self,
        config: Optional[SkillConfig] = None,
        write_config: Optional[WriteConfig] = None,
    ):
        self._config = config or SkillConfig()
        self._nudge = NudgeEvaluator(config=write_config)

    def maybe_trigger_emergence(
        self,
        user_id: str,
        query: str,
        ai_response: str,
        conversation_id: str,
    ) -> None:
        """检查触发条件，满足时异步触发即时技能涌现 + Nudge 评估。

        完全静默，用户无感。失败不影响主流程。

        Args:
            user_id: 用户标识
            query: 用户本次输入
            ai_response: Agent 本次回复
            conversation_id: 会话 ID
        """
        # 基因5: Nudge 评估（同步执行，轻量级 Redis 操作）
        self._nudge.maybe_nudge(user_id, conversation_id, ai_response)

        # 基因1: 即时技能涌现
        if not self._config.instant_emergence_enabled:
            return

        if not self._should_trigger(query, ai_response):
            return

        if self._config.instant_emergence_async:
            Thread(
                target=self._do_instant_emergence,
                args=(user_id, query, ai_response, conversation_id),
                daemon=True,
            ).start()
        else:
            self._do_instant_emergence(user_id, query, ai_response, conversation_id)

    def _should_trigger(self, query: str, ai_response: str) -> bool:
        """检查是否满足即时涌现触发条件。

        条件1: 用户纠正（query 中有否定/纠正信号）
        条件2: 复杂任务（ai_response 较长，可能包含复杂工作流）
        条件3: ai_response 中有代码块或工具调用痕迹
        """
        # 条件1: 用户纠正信号
        query_lower = query.lower()
        for signal in self._CORRECTION_SIGNALS:
            if signal in query_lower:
                return True

        # 条件2: 复杂任务（回复超过 2000 字符，大概率是复杂工作流）
        if len(ai_response) > 2000:
            return True

        # 条件3: 代码块或工具调用痕迹
        if "```" in ai_response or "tool_call" in ai_response.lower():
            return True

        return False

    def _do_instant_emergence(
        self,
        user_id: str,
        query: str,
        ai_response: str,
        conversation_id: str,
    ) -> None:
        """执行即时技能涌现（复用 SkillEmergence 方法）。

        1. 收集执行轨迹（从最近的 Episode 节点）
        2. 调用 SkillEmergence._extract_template() 提取技能模板
        3. 查找已有 Skill（_find_existing_skill）
        4. 命中 → _update_skill / 未命中 → _persist_skill
        """
        try:
            emergence = SkillEmergence(config=self._config)

            # 1. 收集执行轨迹（从最近的 Episode 节点）
            memories = self._fetch_recent_episodes(emergence, user_id)
            if not memories or len(memories) < self._config.instant_emergence_min_tool_calls:
                return

            # 2. 提取技能模板（复用现有代码）
            new_skill = emergence._extract_template(memories)
            if new_skill is None:
                return

            # 3. 查找已有技能（复用现有代码）
            existing = emergence._find_existing_skill(user_id, new_skill.name)

            if existing is not None:
                # 4a. 基因3: 通过 bump_use 累加 Redis 实时计数（§8.7）
                # 不调用 _update_skill 以避免 use_count 重复计数（_update_skill 已在
                # scan_and_emerge 批量巩固路径中更新 use_count）。frequency/maturity
                # 由 curate_skills 定期重算。flush 任务每小时合并 Redis → Neo4j。
                emergence.bump_use(user_id, existing.skill_id)
                logger.info(
                    "即时技能涌现-bump_use: user=%s skill=%s",
                    user_id, existing.name,
                )
            else:
                # 4b. 创建新技能
                new_skill.user_id = user_id
                new_skill.frequency = 1
                new_skill.source_memories = [m.get("id", "") for m in memories]
                new_skill.first_seen_at = datetime.now(UTC)
                new_skill.last_updated_at = datetime.now(UTC)
                new_skill.status = emergence._transition_status(new_skill)
                emergence._persist_skill(new_skill)
                logger.info(
                    "即时技能涌现-新建: user=%s skill=%s",
                    user_id, new_skill.name,
                )
        except Exception:
            logger.warning("即时技能涌现失败，不影响主流程", exc_info=True)

    def _fetch_recent_episodes(
        self,
        emergence: SkillEmergence,
        user_id: str,
    ) -> list[dict]:
        """获取最近 1 小时的 Episode 节点作为执行轨迹。

        优先按 conversation_id 查询，回退到按 user_id 查最近 N 条。
        """
        driver = emergence._get_driver()
        if driver is None:
            return []

        try:
            # 查询最近 1 小时的 Episode 节点（按时间倒序，最多 20 条）
            cypher = """
            MATCH (e:Episode {user_id: $user_id})
            WHERE e.created_at >= datetime() - duration({hours: 1})
            RETURN e.node_id AS id, e.content AS content, e.created_at AS created_at
            ORDER BY e.created_at DESC
            LIMIT 20
            """

            with driver.session() as session:
                result = session.run(cypher, user_id=user_id)
                records = list(result)

            return [
                {
                    "id": str(record.get("id", "")),
                    "content": record.get("content", ""),
                    "created_at": record.get("created_at"),
                }
                for record in records
            ]
        except Exception:
            logger.warning("_fetch_recent_episodes: 查询失败", exc_info=True)
            return []
