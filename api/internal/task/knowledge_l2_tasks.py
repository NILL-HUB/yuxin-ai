"""知识库 L2 深度解析任务（按需触发）。

**L1 / L2 的分工**（设计稿 §3.3）：
- L1（上传即跑）：让素材「能被找到」——关键帧 + ASR 即可检索；
- L2（按需/后台）：让素材「能被精细修改」——由 L1 命中帧定位时间窗口，
  只在窗口内按 0.5 秒/帧密抽并逐帧详述（**不重扫全片**）。

L2 由检索命中、用户显式要求等场景触发，**不做定时轮询**（长视频视觉详述最贵）。
窗口内新帧**新建 Segment**（`metadata.tier2_window=True`），与 L1 全片粗抽帧区分；
重复触发会先清理上一轮窗口片段与其帧（避免累积重复与配额泄漏）。
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="internal.task.knowledge_l2_tasks.build_document_l2_task",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def build_document_l2_task(self, document_id: str):
    """对指定文档执行 L2 深度解析。

    幂等：重复执行会覆盖同一批 Segment，不产生重复片段。
    """
    from app.http.module import injector
    from internal.service.knowledge_indexing_service import KnowledgeIndexingService

    indexing_service = injector.get(KnowledgeIndexingService)
    try:
        return indexing_service.build_document_l2(document_id)
    except Exception as exc:
        logger.exception("L2 深度解析失败 document_id=%s", document_id)
        raise self.retry(exc=exc)
