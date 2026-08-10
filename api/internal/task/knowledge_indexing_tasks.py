"""知识库文档异步索引 Celery 任务。

将文档索引（解析/切分/向量化）从 HTTP 请求线程解耦：
上传/新建/编辑文档的接口立即返回，索引在 Celery worker 中后台执行，
前端通过轮询文档状态展示「解析→切分→向量化→完成」的实时进度。

设计：
- 通过 AppContextTask（首次执行时初始化运行时容器）访问 current_app.injector
- 索引内部异常由 KnowledgeIndexingService.build_document 自行标记 ERROR 状态并吞掉，
  本任务仅在基础设施级异常（如注入失败）时触发 Celery 重试
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="internal.task.knowledge_indexing_tasks.build_document_task",
    bind=True,
    max_retries=2,
    default_retry_delay=10,
)
def build_document_task(self, document_id: str, account_id: str | None = None):
    """Celery 任务：后台构建知识库文档索引（解析→切分→向量化→完成）。

    Args:
        document_id: 文档 ID（UUID 字符串）
        account_id: 触发账号 ID（当前仅用于兼容签名，索引流程暂不使用）
    """
    from app.http.module import injector
    from internal.service.knowledge_indexing_service import KnowledgeIndexingService

    indexing_service = injector.get(KnowledgeIndexingService)
    try:
        indexing_service.build_document(document_id, None)
        logger.info("build_document_task: 文档索引完成 document_id=%s", document_id)
    except Exception as exc:
        logger.exception("build_document_task: 文档索引任务失败 document_id=%s", document_id)
        raise self.retry(exc=exc)
