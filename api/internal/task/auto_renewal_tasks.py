"""自动续费周期扫描执行器（Celery）。

- 每小时兜底扫描到期 membership 续费与余量达标未触发的 credits 续费；
- 主触发源为 credit_service 消费后钩子（余量）与服务内到期检查（Expiry 由会员到期驱动）。
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="internal.task.auto_renewal_tasks.run_auto_renewal_scan",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def run_auto_renewal_scan(self):
    from internal.extension.database_extension import db
    from internal.service.auto_renewal_service import AutoRenewalService

    try:
        return AutoRenewalService(session=db.session).run_due_scan()
    except Exception as exc:
        logger.exception("自动续费周期扫描失败")
        raise self.retry(exc=exc)