"""视频轻量剪辑的 Celery 任务（trim / concat / subtitle）。

薄委托范式（与 knowledge_l2_tasks 一致）：任务体只做「取 service + 委托 + 重试」，
业务全在 VideoEditService。

重试语义分层：
- `VideoEditError` 是业务失败（参数非法 / 素材不存在 / 字幕为空），**不重试**，
  重试只会重复失败并放大噪音；
- 其他异常（IO / 存储抖动）重试。

队列：走默认 `celery` 队列（不新建队列/容器）。理由见计划 §0：
剪辑是秒级 IO 操作，主 worker 镜像已内含 imageio_ffmpeg，无需专属消费者。
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)

__all__ = ["video_concat_task", "video_subtitle_task", "video_trim_task"]


def _load_service():
    """延迟导入重依赖（避免 Celery 启动期加载应用依赖）。"""
    from app.http.module import injector
    from internal.service.video_edit_service import VideoEditService

    return injector.get(VideoEditService)


def _load_account(account_id: str):
    from uuid import UUID

    from app.http.module import injector
    from internal.service.account_service import AccountService

    return injector.get(AccountService).get_account(UUID(str(account_id)))


def _delegate(self, action: str, fn):
    """统一的重试/异常分层。业务失败不重试，其余交给 Celery 重试。"""
    from internal.service.video_edit_service import VideoEditError

    try:
        return fn()
    except VideoEditError:
        logger.warning("视频编辑业务失败 action=%s", action, exc_info=True)
        raise
    except Exception as exc:
        logger.exception("视频编辑失败 action=%s，将重试", action)
        raise self.retry(exc=exc)


@shared_task(
    name="internal.task.video_edit_tasks.video_trim_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def video_trim_task(
    self, knowledge_base_id: str, document_id: str,
    start_sec: float, end_sec, name: str, account_id: str, reencode: bool = False,
):
    """裁剪库内视频并存入成品库。"""
    service = _load_service()
    account = _load_account(account_id)

    def _run():
        return service.trim_document(
            account=account, knowledge_base_id=knowledge_base_id,
            document_id=document_id, start_sec=start_sec, end_sec=end_sec,
            name=name, reencode=reencode,
        )

    return _delegate(self, "trim", _run)


@shared_task(
    name="internal.task.video_edit_tasks.video_concat_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def video_concat_task(
    self, knowledge_base_id: str, document_ids: list, name: str, account_id: str
):
    """按给定顺序拼接库内视频并存入成品库。"""
    service = _load_service()
    account = _load_account(account_id)

    def _run():
        return service.concat_documents(
            account=account, knowledge_base_id=knowledge_base_id,
            document_ids=list(document_ids or []), name=name,
        )

    return _delegate(self, "concat", _run)


@shared_task(
    name="internal.task.video_edit_tasks.video_subtitle_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def video_subtitle_task(
    self, knowledge_base_id: str, document_id: str, cues: list,
    name: str, account_id: str,
):
    """给库内视频烧录字幕并存入成品库。"""
    service = _load_service()
    account = _load_account(account_id)

    def _run():
        return service.subtitle_document(
            account=account, knowledge_base_id=knowledge_base_id,
            document_id=document_id, cues=list(cues or []), name=name,
        )

    return _delegate(self, "subtitle", _run)
