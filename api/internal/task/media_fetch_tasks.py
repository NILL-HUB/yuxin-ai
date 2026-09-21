"""外部素材获取的 Celery 任务（KB-P6）。

薄委托范式（与 video_edit_tasks 一致）：任务体只取 service/kb + 委托 + 重试。
MediaFetchError 为业务失败（URL 不支持/超上限/白名单不符）不重试；其余重试。
队列：媒体下载可能较久，走默认 celery 队列（可在 task_routes 按需调整）。
"""
from __future__ import annotations

import logging
import tempfile
from uuid import UUID

from celery import shared_task

logger = logging.getLogger(__name__)

__all__ = ["media_fetch_task"]


def _format_for(base_type: str) -> str:
    from internal.entity.knowledge_entity import KnowledgeBaseType
    typed = str(base_type or "").strip().lower()
    if typed in {"audio", KnowledgeBaseType.AUDIO.value}:
        return "ba"  # 纯音频
    return "bv*+ba/b"  # 视频/mixed 默认视频


@shared_task(
    name="internal.task.media_fetch_tasks.media_fetch_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def media_fetch_task(
    self,
    url: str,
    knowledge_base_id: str,
    account_id: str,
    resolution: str = "",
    max_bytes=None,
):
    """按 URL 下载外部素材并建档入库。

    KnowledgeBase / Account 为模型对象，由任务从 injector 取 service 解析后交给
    MediaFetchService.import_document 处理。业务失败不重试，其余交给 Celery。
    """
    from app.http.module import injector
    from internal.service.account_service import AccountService
    from internal.service.knowledge_base_service import KnowledgeBaseService
    from internal.service.media_fetch_service import MediaFetchError

    account = injector.get(AccountService).get_account(UUID(str(account_id)))
    kb = injector.get(KnowledgeBaseService).get_accessible_base(str(knowledge_base_id), account)

    def _run():
        from internal.service.media_fetch_service import MediaFetchService
        svc = injector.get(MediaFetchService)
        with tempfile.TemporaryDirectory() as temp_dir:
            return svc.import_document(
                url=url, knowledge_base=kb, account=account,
                temp_dir=temp_dir, max_bytes=_normalize_max_bytes(max_bytes),
                format_spec=_format_for(getattr(kb, "base_type", "") or ""),
            )

    try:
        return _run()
    except MediaFetchError:
        logger.warning("外部素材获取业务失败 url=%s", url, exc_info=True)
        raise
    except Exception as exc:  # noqa: BLE001
        # 已上传的成果 best-effort 清理由 service 负责；此处仅负责重试策略。
        logger.exception("外部素材获取失败 url=%s，将重试", url)
        raise self.retry(exc=exc)


def _normalize_max_bytes(value) -> int | None:
    try:
        v = str(value or "").strip()
        return None if v in ("", "None", "none") else max(0, int(v))
    except (TypeError, ValueError):
        return None