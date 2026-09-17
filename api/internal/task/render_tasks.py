"""渲染任务：把 composition 渲染为 MP4 并写入成品库。

长任务（分钟级），走独立 `render` 队列；消费 worker 必须显式 `-Q render`，
否则会与业务任务争抢（设计 §3.2）。

失败重试策略：渲染失败多为环境/资源瞬时问题（浏览器崩溃、超时），
故 retry 2 次、间隔 60s；环境配置类错误（缺二进制路径）不重试——
重试也必然失败，只浪费时间。

可靠性（闸门 5/6）：
- ``acks_late=True`` + ``reject_on_worker_lost=True``：worker 中途被杀时任务
  重新入队，不会静默丢失；
- ``soft_time_limit`` 略大于 subprocess 超时，超时抛 SoftTimeLimitExceeded；
- 任务开始即 ``mark_dequeued``（队列积压计数减一），结束/失败时 ``release``
  归还账号槽位与防重锁——保证闸门计数不泄漏。
"""
from __future__ import annotations

import logging
from uuid import UUID

from celery import shared_task

logger = logging.getLogger(__name__)

# subprocess 超时（RENDER_TIMEOUT_SEC，4C4G 上 900s）+ 落库/建档开销
_SOFT_TIME_LIMIT_SEC = 1200


@shared_task(
    name="internal.task.render_tasks.render_composition_task",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=_SOFT_TIME_LIMIT_SEC,
)
def render_composition_task(self, composition_spec: dict, account_id: str, name: str = ""):
    """渲染一段 composition 并把成品写入成品库。

    入参：composition_spec（结构化脚本，见 composition_builder）、
    account_id（成品的归属账号）、name（成品名称，缺省用文件名）。
    """
    from app.http.module import injector
    from internal.core.video.hyperframes_renderer import (
        RenderEnvironmentError,
        RenderFailedError,
    )
    from internal.service.render_service import RenderService

    guard = _load_guard()
    fingerprint = _composition_fingerprint(composition_spec)
    if guard is not None:
        guard.mark_dequeued()

    try:
        service = injector.get(RenderService)
        result = service.render_to_render_output_base(
            composition_spec=composition_spec, account_id=account_id, name=name
        )
    except RenderEnvironmentError:
        # 配置问题：重试无意义，直接失败并留下可读日志
        _notify_render_finished(account_id=account_id, name=name, result=None)
        logger.exception("渲染环境配置不完整，放弃重试")
        raise
    except RenderFailedError as exc:
        logger.warning("渲染失败，准备重试：%s", exc, exc_info=True)
        # 仅在与重试次数耗尽时才通知失败，避免中途重试也发失败通知
        if self.request.retries >= self.max_retries:
            _notify_render_finished(account_id=account_id, name=name, result=None)
        raise self.retry(exc=exc)
    finally:
        if guard is not None:
            guard.release(account_id=account_id, fingerprint=fingerprint)

    # 成功：回链通知用户（前端订阅 document_index_notification，room = account_id）
    _notify_render_finished(account_id=account_id, name=name, result=result)
    return result


def _notify_render_finished(*, account_id: str, name: str, result: dict | None) -> None:
    """渲染结束时回链通知用户。

    复用既有 `document_index_notification` 通道（前端已订阅、后端已有订阅处理器，
    此前只缺生产者）。成品本质就是一篇入库文档，故沿用该通道的字段语义，
    不自造新事件——前端零改动即可收到。失败不抛，避免影响任务本身结果。
    """
    try:
        from app.http.module import injector
        from internal.lib.websocket_manager import ws_manager
        from internal.schema.document_index_notification_schema import (
            DocumentIndexNotificationSchema,
        )
        from internal.service.notification_service import NotificationService

        if result:
            document_id = result.get("document_id") or ""
            document_name = result.get("name") or name or "渲染成品"
            status, error_message = "success", ""
        else:
            document_id = ""
            document_name = name or "渲染成品"
            status, error_message = "error", "视频渲染失败，请稍后重试"

        notification = injector.get(NotificationService).create_notification(
            user_id=UUID(str(account_id)),
            dataset_id=UUID(str(result.get("knowledge_base_id"))) if result and result.get("knowledge_base_id") else UUID(int=0),
            document_id=UUID(str(document_id)) if document_id else UUID(int=0),
            document_name=document_name,
            segment_count=0,
            index_duration=0.0,
            status=status,
            error_message=error_message,
        )
        payload = DocumentIndexNotificationSchema().dump(notification)
        ws_manager.emit_notification_to_user(
            str(account_id), payload, event="document_index_notification"
        )
        logger.info("渲染完成通知已推送 account_id=%s status=%s", account_id, status)
    except Exception:
        logger.warning("渲染完成回链失败 account_id=%s", account_id, exc_info=True)


def _load_guard():
    """取渲染闸门服务；不可用时返回 None（任务不应因闸门故障而无法执行）。"""
    try:
        from app.http.module import injector
        from internal.service.render_guard_service import RenderGuardService

        return injector.get(RenderGuardService)
    except Exception:
        logger.warning("加载渲染闸门服务失败，跳过计数归还", exc_info=True)
        return None


def _composition_fingerprint(composition: dict) -> str:
    """与派发端一致的脚本指纹（防重锁需两端同值才能正确释放）。"""
    import hashlib
    import json

    try:
        payload = json.dumps(composition, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        payload = str(composition)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
