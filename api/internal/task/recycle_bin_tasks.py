"""系统资源回收站 Celery 定时任务。

提供到期销毁任务：
    - ``run_recycle_bin_expiration``: 每小时扫描回收站中已到留存期的条目并彻底销毁

回收站不可手动清空，条目只能到期后由本任务销毁。
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="internal.task.recycle_bin_tasks.run_recycle_bin_expiration",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_recycle_bin_expiration(self):
    """扫描回收站中已到留存期的条目并标记销毁。

    Returns:
        ``{"purged": int, "failed": int, "total": int}`` 执行摘要
    """
    try:
        from internal.service.recycle_bin_service import RecycleBinService

        service = RecycleBinService()
        result = service.purge_expired()
        logger.info("回收站到期销毁完成: %s", result)
        return result
    except Exception:
        logger.exception("回收站到期销毁任务失败")
        raise self.retry()
