"""分片上传暂存清理 Celery 定时任务。

提供残留清理任务：
    - ``cleanup_stale_chunk_sessions``: 每小时清理已无会话的残留分片目录

分片暂存目录在 complete/abort 时会清理；但用户中途放弃且不调 abort 时，
目录会残留（不计配额），由本任务兜底回收。
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="internal.task.chunked_upload_tasks.cleanup_stale_chunk_sessions",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def cleanup_stale_chunk_sessions(self):
    """清理不再活跃的会话分片暂存目录。

    Returns:
        ``{"cleaned": int, "sessions": list[str]}`` 执行摘要
    """
    try:
        from internal.service.chunked_upload_session_service import ChunkedUploadSessionService
        from internal.service.storage.local_storage_service import LocalStorageService
        from app.http.module import injector

        session_service = injector.get(ChunkedUploadSessionService)
        storage = injector.get(LocalStorageService)

        def _is_active(session_id: str) -> bool:
            return session_service.is_alive(session_id)

        cleaned = storage.cleanup_stale_session_dirs(_is_active)
        for session_id in cleaned:
            session_service.forget_session(session_id)

        logger.info("分片暂存清理完成: %s", {"cleaned": len(cleaned), "sessions": cleaned})
        return {"cleaned": len(cleaned), "sessions": cleaned}
    except Exception:
        logger.exception("分片暂存清理任务失败")
        raise self.retry()
