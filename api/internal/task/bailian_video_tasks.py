"""百炼视频生成的 Celery 任务（薄委托范式，与 video_edit_tasks 一致）。

队列：走默认 `celery` 队列。视频生成是分钟级外部 IO（等百炼云端出片），
CPU 占用低，主 worker 即可承载，无需专属队列/容器。

重试语义：**不重试**。`bl video generate` 会向百炼真实提交付费任务，
失败重试会重复提交、重复计费；错误消息已面向用户可直接展示。
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)

__all__ = ["bailian_video_generate_task"]


def _load_service():
    """延迟导入重依赖（避免 Celery 启动期加载应用依赖）。"""
    from app.http.module import injector
    from internal.service.bailian_video_service import BailianVideoService

    return injector.get(BailianVideoService)


def _load_account(account_id: str):
    from uuid import UUID

    from app.http.module import injector
    from internal.service.account_service import AccountService

    return injector.get(AccountService).get_account(UUID(str(account_id)))


@shared_task(
    name="internal.task.bailian_video_tasks.bailian_video_generate_task",
    bind=True,
    max_retries=0,
)
def bailian_video_generate_task(
    self,
    prompt: str,
    name: str,
    model: str,
    duration: int,
    resolution: str,
    ratio: str,
    image_url: str,
    account_id: str,
    message_id: str = "",
    conversation_id: str = "",
):
    """调用百炼 CLI 生成视频并存入成品库，完成后回填到原对话消息。"""
    # 回填逻辑与剪辑链路共用同一实现（_notify_artifact 在 video_edit_tasks 内定义）
    from internal.task.video_edit_tasks import _notify_artifact

    service = _load_service()
    account = _load_account(account_id)
    result = service.generate_video(
        account=account,
        prompt=prompt,
        name=name,
        model=model,
        duration=int(duration or 0),
        resolution=resolution,
        ratio=ratio,
        image_url=image_url,
    )
    _notify_artifact(
        account_id=account_id,
        message_id=message_id,
        conversation_id=conversation_id,
        result=result,
        tool="bailian_video_generate",
    )
    return result
