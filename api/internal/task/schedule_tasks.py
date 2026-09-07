"""定时任务系统 Celery 扫描执行器。

提供两个任务：
- ``run_scheduled_tasks``：每分钟由 celery-beat 触发，扫描到期任务并逐个
  投递 ``schedule_task_execute``，然后立即返回（扫描/执行解耦）。
- ``schedule_task_execute``：真正执行单个定时任务（以任务归属用户身份走完整
  编排链）。长任务（数小时）在自己独立的 celery 任务里运行，不阻塞每分钟扫描。

为什么解耦（演进说明）：
    旧实现是 run_scheduled_tasks 内同步 for 循环执行每个到期任务，并套了一个
    90 秒硬超时——本意是保护每分钟扫描不被单个长任务阻塞，但代价是：
    1) 90s 必然误杀需要数小时的复杂定时 Agent 任务；
    2) 超时只是「主线程放弃等待」，daemon 线程里的 Agent 仍在后台空转。
    解耦后：扫描只投递立即返回，长任务在独立任务中自然跑完（去掉 90s 超时），
    每分钟扫描永远准时。任务不重入由 Redis 锁保证，单用户并发由每用户上限治理。

降级策略:
    - 单个任务失败不阻断其他任务，错误计入 schedule_task_run.error_message
    - 连续失败 5 次自动停用（ScheduleExecutionService 内处理）
"""
import logging
import os
from datetime import UTC, datetime, timedelta

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="internal.task.schedule_tasks.run_scheduled_tasks",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def run_scheduled_tasks(self):
    """每分钟扫描到期定时任务并投递执行（扫描与执行解耦，秒级精度在 service 内判断）。"""
    from app.http.module import injector
    from internal.extension.database_extension import db
    from internal.service.schedule_task_service import ScheduleTaskService

    svc = ScheduleTaskService(db)
    due_tasks = svc.scan_due_tasks()
    if not due_tasks:
        logger.info("无到期定时任务")
        return {"scanned": 0}

    from internal.task.schedule_tasks import schedule_task_execute

    dispatched = 0
    for task in due_tasks:
        try:
            # 先推进 next_run_at，防止下个 tick 重复扫描到同一任务
            # （执行结果由 schedule_task_execute 回写 run 记录）
            svc.advance_next_run(task)
            schedule_task_execute.delay(str(task.id))
            dispatched += 1
        except Exception as exc:
            logger.exception("定时任务投递失败 task_id=%s", task.id)
    logger.info("到期定时任务 %d 个，已投递 %d 个", len(due_tasks), dispatched)
    return {"scanned": len(due_tasks), "dispatched": dispatched}


@shared_task(
    name="internal.task.schedule_tasks.schedule_task_execute",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
    reject_on_worker_lost=True,
)
def schedule_task_execute(self, schedule_task_id: str):
    """执行单个定时任务（独立 celery 任务，可长跑数小时，不阻塞每分钟扫描）。

    acks_late=True + reject_on_worker_lost=True：任务执行中途 worker 崩溃/被杀时，
    消息不会被确认，broker 会重新投递给存活 worker。execute_task 内部有
    Redis 锁防重入（幂等），崩溃后重投不会造成同一任务并行执行。
    """
    from app.http.module import injector
    from internal.extension.database_extension import db
    from internal.model import ScheduleTask
    from internal.service.schedule_execution_service import ScheduleExecutionService

    execution = injector.get(ScheduleExecutionService)
    task = (
        db.session.query(ScheduleTask)
        .filter(ScheduleTask.id == schedule_task_id)
        .one_or_none()
    )
    if task is None:
        logger.warning("定时任务不存在，跳过执行 schedule_task_id=%s", schedule_task_id)
        return {"executed": False, "reason": "not_found"}
    if not task.enabled:
        logger.info("定时任务已停用，跳过执行 schedule_task_id=%s", schedule_task_id)
        return {"executed": False, "reason": "disabled"}
    try:
        execution.execute_task(task)
    except Exception as exc:
        logger.exception("定时任务执行失败 task_id=%s", schedule_task_id)
        # execute_task 内部已捕获业务异常并写入 run 记录；
        # 这里仅兜底任务级异常，避免 celery 标记任务失败导致重试风暴
        return {"executed": True, "error": str(exc)}
    return {"executed": True}


@shared_task(
    name="internal.task.schedule_tasks.cleanup_stale_runs",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def cleanup_stale_runs(self):
    """清理僵尸运行记录：把超过阈值仍 running 的 ScheduleTaskRun 标记为 failed。

    背景：worker 崩溃/被 kill/进程重启时，任务执行中的 run 记录会永久停在
    running（旧机制无任何后台任务回收）。本任务由 celery-beat 周期触发（如每
    15 分钟），把 started_at 超过 ``SCHEDULE_STALE_RUN_HOURS``（默认 8h，与执行
    锁 TTL 对齐）仍 running 的记录标记为 failed，附带原因「worker 中断/超时」。

    注意：Redis 执行锁的 8h TTL 独立于此标记——锁过期后下个 tick 允许重新执行，
    僵尸 run 记录被标记 failed 后不再占用「每用户并发额度」（该额度只统计 6h
    窗口内 running 记录），从而避免额度被僵尸占满。
    """
    from internal.extension.database_extension import db
    from internal.model import ScheduleTaskRun

    stale_hours = 8
    raw_hours = os.getenv("SCHEDULE_STALE_RUN_HOURS", "").strip()
    if raw_hours:
        try:
            stale_hours = int(raw_hours)
        except (TypeError, ValueError):
            pass

    try:
        threshold = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=stale_hours)
        stale_runs = (
            db.session.query(ScheduleTaskRun)
            .filter(
                ScheduleTaskRun.status == "running",
                ScheduleTaskRun.started_at.isnot(None),
                ScheduleTaskRun.started_at < threshold,
            )
            .limit(500)
            .all()
        )
    except Exception as exc:
        logger.exception("查询僵尸运行记录失败: %s", exc)
        return {"cleaned": 0, "error": str(exc)}

    cleaned = 0
    for run in stale_runs:
        try:
            db.session.query(ScheduleTaskRun).filter(ScheduleTaskRun.id == run.id).update(
                {
                    "status": "failed",
                    "finished_at": datetime.now(UTC).replace(tzinfo=None),
                    "error_message": "worker 中断/超时：运行超过 %d 小时仍未结束，判定为崩溃残留" % stale_hours,
                },
                synchronize_session=False,
            )
            cleaned += 1
        except Exception:
            logger.exception("标记僵尸运行记录失败 run_id=%s", run.id)
    try:
        db.session.commit()
    except Exception:
        logger.exception("提交僵尸清理失败")
        db.session.rollback()
    logger.info("僵尸运行记录清理完成: cleaned=%d/%d threshold_hours=%d", cleaned, len(stale_runs), stale_hours)
    return {"cleaned": cleaned, "scanned": len(stale_runs)}
