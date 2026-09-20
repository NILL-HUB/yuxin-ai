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

__all__ = ["video_concat_task", "video_subtitle_task", "video_trim_task", "video_reassemble_task"]


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


def _notify_artifact(
    *, account_id: str, message_id: str, conversation_id: str,
    result: dict | None, tool: str,
) -> None:
    """把已就绪的成品回填到原对话消息（对话内成片预览）。

    失败不抛：任务本身已成功落库，回填只是「让用户不必去成品库翻」的增强，
    不应因推送失败把成功的任务标记成失败。
    """
    if not result:
        return
    artifact = result.get("artifact")
    if not artifact:
        logger.info("成品未生成可播放地址，跳过回填 tool=%s", tool)
        return

    from internal.service.artifact_notification_service import notify_artifact_ready

    notify_artifact_ready(
        account_id=account_id,
        message_id=message_id,
        conversation_id=conversation_id,
        artifact=artifact,
        tool=tool,
    )


@shared_task(
    name="internal.task.video_edit_tasks.video_trim_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def video_trim_task(
    self, knowledge_base_id: str, document_id: str,
    start_sec: float, end_sec, name: str, account_id: str, reencode: bool = False,
    message_id: str = "", conversation_id: str = "",
    segment_index: int = 0,
):
    """裁剪库内视频并存入成品库，完成后回填到原对话消息。

    `segment_index`（1-based）可选：>0 时按该素材第几段 L1 时间线段落裁剪
    （忽略 start/end 秒数）；<=0 则视为未选段，走手填秒数路径。
    """
    service = _load_service()
    account = _load_account(account_id)

    def _run():
        return service.trim_document(
            account=account, knowledge_base_id=knowledge_base_id,
            document_id=document_id, start_sec=start_sec, end_sec=end_sec,
            name=name, reencode=reencode,
            segment_index=int(segment_index or 0) if int(segment_index or 0) > 0 else None,
        )

    result = _delegate(self, "trim", _run)
    _notify_artifact(
        account_id=account_id, message_id=message_id, conversation_id=conversation_id,
        result=result, tool="video_trim",
    )
    return result


@shared_task(
    name="internal.task.video_edit_tasks.video_concat_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def video_concat_task(
    self, knowledge_base_id: str, document_ids: list, name: str, account_id: str,
    message_id: str = "", conversation_id: str = "",
):
    """按给定顺序拼接库内视频并存入成品库，完成后回填到原对话消息。"""
    service = _load_service()
    account = _load_account(account_id)

    def _run():
        return service.concat_documents(
            account=account, knowledge_base_id=knowledge_base_id,
            document_ids=list(document_ids or []), name=name,
        )

    result = _delegate(self, "concat", _run)
    _notify_artifact(
        account_id=account_id, message_id=message_id, conversation_id=conversation_id,
        result=result, tool="video_concat",
    )
    return result


@shared_task(
    name="internal.task.video_edit_tasks.video_subtitle_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def video_subtitle_task(
    self, knowledge_base_id: str, document_id: str, cues,
    name: str, account_id: str,
    message_id: str = "", conversation_id: str = "",
):
    """给库内视频烧录字幕并存入成品库，完成后回填到原对话消息。

    `cues` 为 None / 空列表时由 service 自动生成时间轴（复用已留存 ASR 时间轴，
    缺失则重跑 ASR）——这是「用户只说『给这个视频加字幕』」的正常路径。
    """
    service = _load_service()
    account = _load_account(account_id)

    def _run():
        return service.subtitle_document(
            account=account, knowledge_base_id=knowledge_base_id,
            document_id=document_id, cues=list(cues or []) or None, name=name,
        )

    result = _delegate(self, "subtitle", _run)
    _notify_artifact(
        account_id=account_id, message_id=message_id, conversation_id=conversation_id,
        result=result, tool="video_subtitle",
    )
    return result


@shared_task(
    name="internal.task.video_edit_tasks.video_reassemble_task",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def video_reassemble_task(
    self, knowledge_base_id: str, document_id: str, clips,
    name: str, account_id: str,
    message_id: str = "", conversation_id: str = "",
):
    """按时间线编排重建库内视频并存入成品库，完成后回填到原对话消息。

    `clips` 为有序编排片段（每项含 document_id / segment_index），
    由工具或前端编辑器提交；业务校验全在
    `VideoEditService.reassemble_document`（素材归属/序号越界/参数非法）。
    """
    service = _load_service()
    account = _load_account(account_id)

    def _run():
        return service.reassemble_document(
            account=account, knowledge_base_id=knowledge_base_id,
            document_id=document_id, clips=list(clips or []), name=name,
        )

    result = _delegate(self, "reassemble", _run)
    _notify_artifact(
        account_id=account_id, message_id=message_id, conversation_id=conversation_id,
        result=result, tool="video_reassemble",
    )
    return result
