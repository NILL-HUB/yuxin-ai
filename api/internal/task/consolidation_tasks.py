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

from internal.entity.memory_owner_entity import (
    NEO4J_ADMIN_LEVEL_AGENT_SENTINEL,
    MemoryOwnerKey,
)

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
        from internal.entity.memory_owner_entity import MemoryOwnerKey
        from internal.model.memory_models import ConsolidationPhase
        from internal.service.memory.consolidation_engine import ConsolidationEngine

        engine = ConsolidationEngine()

        # subject 列表为 None 时查询全部活跃主体（用户 + admin）
        if user_ids is None:
            user_ids = _query_active_subjects()

        results: dict[str, dict] = {}
        for uid in user_ids:
            try:
                # 主体键：裸 UUID → 用户主体（逐字节等价）；admin:{...} → admin 主体
                owner_key = _subject_key_of(uid)
                report = engine.run_consolidation(owner_key)
                results[str(uid)] = {
                    "success": report.is_success,
                    "items": report.total_items_processed,
                }
                # 巩固落库变更 → 失效 Digest 缓存（内容变更驱动重建）
                if report.is_success and report.total_items_processed > 0:
                    _invalidate_digest_cache(owner_key)
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
        # 主体键：裸 UUID → 用户主体（逐字节等价）；admin:{...} → admin 主体
        owner_key = _subject_key_of(user_id)
        report = engine.run_consolidation(owner_key)

        # 仅返回阶段 3（TIER）结果
        phase_key = ConsolidationPhase.TIER.value
        # 权重扫描可能触发 tier 变更 → 失效 Digest 缓存
        if report.is_success and report.total_items_processed > 0:
            _invalidate_digest_cache(owner_key)
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
        from internal.entity.memory_owner_entity import MemoryOwnerKey
        from internal.service.memory.skill_emergence import SkillEmergence

        emergence = SkillEmergence()

        # subject 列表为 None 时查询全部活跃主体（用户 + admin）
        if user_ids is None:
            user_ids = _query_active_subjects()

        results: dict[str, dict] = {}
        for uid in user_ids:
            try:
                # 主体键：裸 UUID → 用户主体（逐字节等价）；admin:{...} → admin 主体
                owner_key = _subject_key_of(uid)
                result = emergence.curate_skills(owner_key)
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
        from internal.entity.memory_owner_entity import MemoryOwnerKey
        from internal.service.memory.skill_emergence import SkillEmergence

        # 配置关闭时跳过
        if not memory_settings.skill.bump_use_redis_enabled:
            return {"skipped": "bump_use_redis_enabled=False"}

        emergence = SkillEmergence(config=memory_settings.skill)

        # subject 列表为 None 时查询全部活跃主体（用户 + admin）
        if user_ids is None:
            user_ids = _query_active_subjects()

        results: dict[str, dict] = {}
        for uid in user_ids:
            try:
                # 主体键：裸 UUID → 用户主体（逐字节等价）；admin:{...} → admin 主体
                owner_key = _subject_key_of(uid)
                result = emergence.flush_bump_use_to_neo4j(owner_key)
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


def _subject_key_of(subject: str) -> str:
    """把「用户 id 或 admin 主体键」规范化为跨层主体键。

    裸 UUID → 用户主体（与历史 ``str(uid)`` 逐字节一致）；
    ``admin:{uuid}[:{uuid}]`` → admin 主体。非法输入抛 ``MemoryOwnerKeyError``
    （fail-closed：不猜主体）。
    """
    return MemoryOwnerKey.parse(str(subject)).to_key()


def _admin_key_from_row(admin_user_id, agent_id) -> str:
    """扫描结果行 → 规范 admin 主体键。

    管理员级（``agent_id`` 为 NULL 或哨兵）产出两级键，Agent 级产出三级键。
    """
    from uuid import UUID

    agent = "" if agent_id is None else str(agent_id)
    if not agent or agent == NEO4J_ADMIN_LEVEL_AGENT_SENTINEL:
        return MemoryOwnerKey.for_admin(UUID(str(admin_user_id))).to_key()
    return MemoryOwnerKey.for_admin(
        UUID(str(admin_user_id)), agent_id=UUID(agent)
    ).to_key()


def _get_neo4j_driver():
    """获取 Neo4j 驱动（可替换点，便于测试）。"""
    from internal.extension.neo4j_extension import get_driver

    return get_driver()


def _query_active_admin_subjects() -> list[str]:
    """查询拥有记忆归属的 admin / Agent 主体键。

    与 ``_query_active_users``（扫 ``(u:User)``）互补：admin 记忆的归属属性是
    ``admin_user_id`` + ``agent_id``，不会出现在 ``User`` 节点上，故必须单独扫描。
    否则 admin 记忆**永不**进入巩固/治理/flush（ADMIN-P3c-3）。

    Returns:
        规范主体键列表（``admin:{uuid}`` / ``admin:{uuid}:{uuid}``），降级返回空列表。
    """
    try:
        driver = _get_neo4j_driver()
        if driver is None:
            logger.warning("_query_active_admin_subjects: Neo4j 不可用，返回空列表")
            return []

        cypher = """
        MATCH (n)
        WHERE (n:MemoryNode OR n:Episode OR n:Entity OR n:Community OR n:Skill)
          AND n.admin_user_id IS NOT NULL
        WITH DISTINCT n.admin_user_id AS admin_user_id, n.agent_id AS agent_id
        RETURN admin_user_id, agent_id
        """
        with driver.session() as session:
            records = list(session.run(cypher))

        keys: list[str] = []
        for record in records:
            admin_user_id = record.get("admin_user_id")
            if not admin_user_id:
                continue
            try:
                keys.append(
                    _admin_key_from_row(admin_user_id, record.get("agent_id"))
                )
            except Exception:
                logger.warning(
                    "_query_active_admin_subjects: 跳过非法归属行 admin=%s",
                    admin_user_id,
                    exc_info=True,
                )
        return keys
    except Exception:
        logger.warning("_query_active_admin_subjects: 查询失败", exc_info=True)
        return []


def _query_active_subjects() -> list[str]:
    """巩固派发全集：活跃用户主体 + 拥有记忆的 admin 主体。"""
    return list(_query_active_users()) + _query_active_admin_subjects()


def _invalidate_digest_cache(subject: str) -> None:
    """主动失效主体 Digest 缓存（内容变更后调用，避免陈旧摘要长期滞留）。

    ``subject`` 为**已规范化的主体键**（裸 UUID 或 ``admin:{...}``）。
    直接构造 DigestManager（redis 已由 extension 初始化），删除缓存键；
    Redis 不可用时静默降级，不影响巩固主流程。
    """
    try:
        from internal.extension.redis_extension import redis_client
        from internal.service.memory.digest_manager import DigestManager

        DigestManager(redis_client=redis_client).invalidate(str(subject))
    except Exception:
        logger.warning(
            "invalidate_digest_cache: 失效 Digest 缓存失败 subject=%s",
            subject,
            exc_info=True,
        )


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
