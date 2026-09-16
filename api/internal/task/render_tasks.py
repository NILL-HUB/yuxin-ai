"""渲染任务：把 composition 渲染为 MP4 并写入成品库。

长任务（分钟级），走独立 `render` 队列；消费 worker 必须显式 `-Q render`，
否则会与业务任务争抢（设计 §3.2）。

失败重试策略：渲染失败多为环境/资源瞬时问题（浏览器崩溃、超时），
故 retry 2 次、间隔 60s；环境配置类错误（缺二进制路径）不重试——
重试也必然失败，只浪费时间。
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="internal.task.render_tasks.render_composition_task",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
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

    try:
        service = injector.get(RenderService)
        return service.render_to_render_output_base(
            composition_spec=composition_spec, account_id=account_id, name=name
        )
    except RenderEnvironmentError:
        # 配置问题：重试无意义，直接失败并留下可读日志
        logger.exception("渲染环境配置不完整，放弃重试")
        raise
    except RenderFailedError as exc:
        logger.warning("渲染失败，准备重试：%s", exc, exc_info=True)
        raise self.retry(exc=exc)
