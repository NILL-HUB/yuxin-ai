"""记忆系统巩固引擎 Celery 定时任务（Track C4）。

提供四个定时任务：
    - ``run_daily_consolidation``:  每日凌晨 3:00 执行全量巩固（含技能涌现）
    - ``run_weight_scan``:          每 6 小时执行权重扫描
    - ``run_skill_curation``:       每 7 天凌晨 4:00 执行技能周期治理（剪枝）
    - ``run_skill_stats_flush``:    每小时执行 Redis→Neo4j 技能使用统计合并（基因3）

降级策略:
    - Celery 未运行时任务不执行，不影响主服务
    - 单用户巩固失败不阻断其他用户
    - 整体异常时自动重试（受 max_retries 限制）

设计参考:
    docs/prd/memory-system/03-consolidation-skill-policy-api.md §7.1 §8.7
    docs/prd/memory-system/execution/04-track-c-consolidation.md C4
    docs/prd/memory-system/execution/06-track-e-skill-pool.md E1
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="internal.task.consolidation_tasks.run_daily_consolidation",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_daily_consolidation(self, user_ids: list[str] | None = None):
    """Celery 任务：对指定用户或所有活跃用户执行全量巩固。

    max_retries=2, default_retry_delay=300s（5 分钟）。
    遍历所有用户执行 ``ConsolidationEngine.run_consolidation``。

    Args:
        user_ids: 用户 ID 列表，None 时扫描所有活跃用户（30 天内有活动）

    Returns:
        ``{user_id: {"success": bool, "items": int}}`` 执行摘要
    """
    try:
        from internal.model.memory_models import ConsolidationPhase
        from internal.service.memory.consolidation_engine import ConsolidationEngine

        engine = ConsolidationEngine()

        # user_ids 为 None 时查询所有活跃用户
        if user_ids is None:
            user_ids = _query_active_users()

        results: dict[str, dict] = {}
        for uid in user_ids:
            try:
                report = engine.run_consolidation(str(uid))
                results[str(uid)] = {
                    "success": report.is_success,
                    "items": report.total_items_processed,
                }
            except Exception as exc:
                logger.warning(
                    "run_daily_consolidation: 用户 %s 巩固失败: %s",
                    uid,
                    exc,
                    exc_info=True,
                )
                results[str(uid)] = {
                    "success": False,
                    "error": str(exc),
                }

        return results
    except Exception as exc:
        logger.error("run_daily_consolidation: 整体异常，触发重试: %s", exc, exc_info=True)
        raise self.retry(exc=exc)


@shared_task(
    name="internal.task.consolidation_tasks.run_weight_scan",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def run_weight_scan(self, user_id: str):
    """Celery 任务：单用户权重扫描。

    max_retries=3, default_retry_delay=60s（1 分钟）。
    执行 ``ConsolidationEngine.run_consolidation``，仅取阶段 3（TIER）结果。

    Args:
        user_id: 用户标识

    Returns:
        阶段 3（weight_scan / tier）结果字典
    """
    try:
        from internal.model.memory_models import ConsolidationPhase
        from internal.service.memory.consolidation_engine import ConsolidationEngine

        engine = ConsolidationEngine()
        report = engine.run_consolidation(str(user_id))

        # 仅返回阶段 3（TIER）结果
        phase_key = ConsolidationPhase.TIER.value
        return report.phases.get(phase_key, {})
    except Exception as exc:
        logger.error(
            "run_weight_scan: 用户 %s 权重扫描异常，触发重试: %s",
            user_id,
            exc,
            exc_info=True,
        )
        raise self.retry(exc=exc)


@shared_task(
    name="internal.task.consolidation_tasks.run_skill_curation",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_skill_curation(self, user_ids: list[str] | None = None):
    """Celery 任务：对指定用户或所有活跃用户执行技能周期治理。

    max_retries=2, default_retry_delay=300s（5 分钟）。
    委托 ``SkillEmergence.curate_skills`` 执行：
    - 合并 Redis 实时使用统计到 Neo4j
    - 重算 ACTIVE/STALE 技能的成熟度
    - 执行状态转移（ACTIVE→STALE、STALE→DEPRECATED、STALE→ACTIVE 复活）

    Args:
        user_ids: 用户 ID 列表，None 时扫描所有活跃用户（30 天内有活动）

    Returns:
        ``{user_id: {"scanned": int, "transitioned": int, "deprecated": int}}``
    """
    try:
        from internal.service.memory.skill_emergence import SkillEmergence

        emergence = SkillEmergence()

        # user_ids 为 None 时查询所有活跃用户
        if user_ids is None:
            user_ids = _query_active_users()

        results: dict[str, dict] = {}
        for uid in user_ids:
            try:
                result = emergence.curate_skills(str(uid))
                results[str(uid)] = result
            except Exception as exc:
                logger.warning(
                    "run_skill_curation: 用户 %s 技能治理失败: %s",
                    uid,
                    exc,
                    exc_info=True,
                )
                results[str(uid)] = {
                    "scanned": 0,
                    "transitioned": 0,
                    "deprecated": 0,
                    "error": str(exc),
                }

        return results
    except Exception as exc:
        logger.error(
            "run_skill_curation: 整体异常，触发重试: %s", exc, exc_info=True
        )
        raise self.retry(exc=exc)


@shared_task(
    name="internal.task.consolidation_tasks.run_skill_stats_flush",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def run_skill_stats_flush(self, user_ids: list[str] | None = None):
    """Celery 任务：将 Redis 中的技能使用统计合并到 Neo4j（基因3, §8.7）。

    每小时执行，委托 ``SkillEmergence.flush_bump_use_to_neo4j``：
    - 读取 Redis 中 bump_use 累积的 use_count / last_used_at
    - 累加到 Neo4j Skill 节点
    - 清理已合并的 Redis 键

    与 ``run_skill_curation``（每周）形成双轨：
    - flush: 高频合并统计，保持 Neo4j use_count 近实时
    - curate: 低频重算 maturity + 状态转移 + 剪枝

    Args:
        user_ids: 用户 ID 列表，None 时扫描所有活跃用户（30 天内有活动）

    Returns:
        ``{user_id: {"flushed": int, "errors": int}}``
    """
    try:
        from internal.config.memory_settings import settings as memory_settings
        from internal.service.memory.skill_emergence import SkillEmergence

        # 配置关闭时跳过
        if not memory_settings.skill.bump_use_redis_enabled:
            return {"skipped": "bump_use_redis_enabled=False"}

        emergence = SkillEmergence(config=memory_settings.skill)

        # user_ids 为 None 时查询所有活跃用户
        if user_ids is None:
            user_ids = _query_active_users()

        results: dict[str, dict] = {}
        for uid in user_ids:
            try:
                result = emergence.flush_bump_use_to_neo4j(str(uid))
                results[str(uid)] = result
            except Exception as exc:
                logger.warning(
                    "run_skill_stats_flush: 用户 %s 统计合并失败: %s",
                    uid, exc, exc_info=True,
                )
                results[str(uid)] = {"flushed": 0, "errors": 1, "error": str(exc)}

        return results
    except Exception as exc:
        logger.error(
            "run_skill_stats_flush: 整体异常，触发重试: %s", exc, exc_info=True
        )
        raise self.retry(exc=exc)


def _query_active_users() -> list[str]:
    """查询所有活跃用户（30 天内有活动）。

    从 Neo4j 查询 User 节点，降级时返回空列表。

    Returns:
        用户 ID 字符串列表
    """
    try:
        from internal.extension.neo4j_extension import get_driver

        driver = get_driver()
        if driver is None:
            logger.warning("_query_active_users: Neo4j 不可用，返回空列表")
            return []

        cypher = """
        MATCH (u:User)
        WHERE u.last_active_at IS NULL
           OR u.last_active_at >= datetime() - duration({days: 30})
        RETURN u.id AS user_id
        """
        with driver.session() as session:
            result = session.run(cypher)
            records = list(result)

        return [str(record.get("user_id", "")) for record in records if record.get("user_id")]
    except Exception:
        logger.warning("_query_active_users: 查询活跃用户失败", exc_info=True)
        return []
