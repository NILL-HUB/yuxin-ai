"""外部数据源自动同步 Celery 定时任务。

提供周期同步任务：
    - ``run_external_data_source_auto_sync``: 扫描已授权数据源并逐个同步
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


def _get_service():
    """经 DI 容器获取服务（延迟导入，避免 Celery 启动期循环依赖）。"""
    from app.http.module import injector
    from internal.service.external_data_source_service import ExternalDataSourceService

    return injector.get(ExternalDataSourceService)


@shared_task(
    name="internal.task.external_data_source_tasks.run_external_data_source_auto_sync",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def run_external_data_source_auto_sync(self):
    """扫描已授权数据源并自动同步。

    Returns:
        ``{"scanned": int, "synced": int, "failed": int}`` 执行摘要
    """
    try:
        result = _get_service().auto_sync_all()
        logger.info("外部数据源自动同步完成: %s", result)
        return result
    except Exception:
        logger.exception("外部数据源自动同步任务失败")
        raise self.retry()
