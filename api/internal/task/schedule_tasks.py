"""定时任务系统 Celery 扫描执行器。

提供 ``run_scheduled_tasks``：
    - 每分钟由 celery-beat 触发
    - 扫描 ``schedule_task`` 中 enabled 且 next_run_at 已到的任务
    - 以任务归属用户身份走完整编排链执行（ScheduleExecutionService）
    - 执行后推进 next_run_at（秒级精度由 croniter 在 service 内计算）

降级策略:
    - 单个任务失败不阻断其他任务，错误计入 schedule_task_run.error_message
    - 连续失败 5 次自动停用（ScheduleExecutionService 内处理）
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="internal.task.schedule_tasks.run_scheduled_tasks",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def run_scheduled_tasks(self):
    """每分钟扫描到期定时任务并执行（秒级精度在 service 内判断）。"""
    from app.http.module import injector
    from internal.extension.database_extension import db
    from internal.service.schedule_execution_service import ScheduleExecutionService
    from internal.service.schedule_task_service import ScheduleTaskService

    svc = ScheduleTaskService(db)
    execution = injector.get(ScheduleExecutionService)
    due_tasks = svc.scan_due_tasks()
    if not due_tasks:
        logger.info("无到期定时任务")
        return {"scanned": 0}
    for task in due_tasks:
        try:
            execution.execute_task(task)
            # 重算下次执行时间（跳过 account 校验）
            svc.advance_next_run(task)
        except Exception as exc:
            logger.exception("定时任务扫描执行失败 task_id=%s", task.id)
    return {"scanned": len(due_tasks)}
