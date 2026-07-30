"""记忆系统巩固引擎 Celery 定时任务（Track C4）。

提供两个定时任务：
    - ``run_daily_consolidation``: 每日凌晨 3:00 执行全量巩固
    - ``run_weight_scan``:         每 6 小时执行权重扫描

降级策略:
    - Celery 未运行时任务不执行，不影响主服务
    - 单用户巩固失败不阻断其他用户
    - 整体异常时自动重试（受 max_retries 限制）

设计参考:
    docs/prd/memory-system/03-consolidation-skill-policy-api.md §7.1
    docs/prd/memory-system/execution/04-track-c-consolidation.md C4
"""

import logging

from celery import shared_task
from celery.schedules import crontab

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


def _query_active_users() -> list[str]:
    """查询所有活跃用户（30 天内有活动）。

    从 Neo4j 查询 User 节点，降级时返回空列表。

    Returns:
        用户 ID 字符串列表
    """
    try:
        from flask import current_app

        driver = current_app.extensions.get("neo4j")
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


# =========================================================
# Celery beat 定时配置
# =========================================================

try:
    from celery import current_app as _celery_app

    _celery_app.conf.beat_schedule = {
        "daily-consolidation": {
            "task": "internal.task.consolidation_tasks.run_daily_consolidation",
            "schedule": crontab(hour=3, minute=0),
            "args": [],
        },
        "weight-scan": {
            "task": "internal.task.consolidation_tasks.run_weight_scan",
            "schedule": crontab(hour="*/6", minute=30),
            "args": [],
        },
    }
    _celery_app.conf.task_routes = {
        "internal.task.consolidation_tasks.*": {"queue": "consolidation"},
    }
except Exception:
    logger.warning("consolidation_tasks: Celery beat 配置注册失败", exc_info=True)
