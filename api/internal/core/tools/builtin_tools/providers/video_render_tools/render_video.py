"""渲染视频工具（对话内出片）。

小钰把编排好的视频脚本交给渲染链路：编译为 HyperFrames composition →
渲染为 MP4 → 自动存入用户的成品库（系统预置、每用户唯一）。

account 获取方式与 create_knowledge_base 一致：由运行时挂载点通过工厂参数
account_id 注入当前账号。builtin 工具没有全局 g.account，不做上下文穿透。

渲染是分钟级长任务，**必须走 Celery `render` 队列**：派发前先过渲染闸门
（每账号并发=1 + 防重锁 + 队列积压保护），后台上跑不动时**直接报错而不是
回退同步**——同步渲染会在请求线程里吃掉 GB 级内存并挂住对话（4C4G 单机
不可承受），这是与 L2 触发**不同**的容错口径，见设计 §3.3 闸门 7。
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _load_render_guard():
    from app.http.module import injector
    from internal.service.render_guard_service import RenderGuardService

    return injector.get(RenderGuardService)


def _composition_fingerprint(composition: dict) -> str:
    """脚本指纹：用于防重锁识别「同一脚本重复提交」。"""
    try:
        payload = json.dumps(composition, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        payload = str(composition)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _dispatch_render(composition: dict, account_id: str, name: str) -> dict:
    """派发渲染：过闸门 → 入 Celery `render` 队列。

    返回 {"mode": "celery", "result": ...}。失败一律抛异常，由调用方转成
    可读错误返回给 Agent——不静默回退同步（见模块 docstring）。
    """
    from internal.task.render_tasks import render_composition_task

    fingerprint = _composition_fingerprint(composition)
    guard = _load_render_guard()

    admission = guard.admit(account_id=account_id, fingerprint=fingerprint)
    if not admission.allowed:
        logger.info("渲染被闸门拒绝 account_id=%s reason=%s", account_id, admission.reason)
        raise RenderRejectedError(admission.reason)

    try:
        async_result = render_composition_task.delay(composition, account_id, name)
    except Exception:
        # 派发失败：释放已占用的槽位与防重锁，避免额度泄漏
        guard.release(account_id=account_id, fingerprint=fingerprint)
        logger.warning("渲染派发 Celery 失败 account_id=%s", account_id, exc_info=True)
        raise

    guard.mark_enqueued()
    return {"mode": "celery", "result": async_result, "fingerprint": fingerprint}


class RenderRejectedError(Exception):
    """渲染被闸门拒绝（并发/重复/积压），消息面向用户可直接展示。"""


class RenderVideoInput(BaseModel):
    """渲染视频的输入模型。"""

    composition: dict = Field(
        ...,
        description=(
            "视频脚本。形如 {composition_id, width, height, duration, segments}，"
            "segments 每项含 start（秒）、duration（秒）、以及 text 或 media_src（素材路径）"
        ),
    )
    name: str = Field("", description="成品名称，可选")


class RenderVideoTool(BaseTool):
    """把视频脚本渲染为 MP4 并存入成品库。"""

    name: str = "render_video"
    description: str = (
        "当用户要求生成/渲染/制作/导出视频成片时调用。"
        "传入结构化视频脚本，系统会渲染为 MP4 并自动存入用户的成品库（可在成品库检索复用）。"
        "渲染耗时较长（分钟级），会转入后台执行。"
    )
    args_schema: type[BaseModel] = RenderVideoInput
    account_id: str = ""

    def _run(
        self,
        composition: dict | None = None,
        name: str = "",
        **kwargs: Any,
    ) -> str:
        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps(
                {"ok": False, "error": "缺少当前账号信息，无法出片"}, ensure_ascii=False
            )

        if not isinstance(composition, dict) or not composition.get("segments"):
            return json.dumps(
                {"ok": False, "error": "视频脚本为空：需要 composition.segments 至少一段"},
                ensure_ascii=False,
            )

        normalized_name = str(name or "").strip()
        try:
            dispatched = _dispatch_render(composition, account_id, normalized_name)
        except RenderRejectedError as exc:
            # 闸门拒绝：提示面向用户可直接展示，不当作系统故障
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        except Exception as exc:
            logger.warning("渲染视频失败 account_id=%s", account_id, exc_info=True)
            return json.dumps(
                {
                    "ok": False,
                    "error": f"渲染视频失败：{exc}（渲染服务暂不可用，请稍后重试）",
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "ok": True,
                "dispatched": True,
                "task_id": str(getattr(dispatched["result"], "id", "")),
                "message": "视频渲染已提交后台处理，完成后会自动存入成品库",
            },
            ensure_ascii=False,
        )

    async def _arun(
        self, composition: dict | None = None, name: str = "", **kwargs: Any
    ) -> str:
        return self._run(composition=composition, name=name, **kwargs)


def render_video(**kwargs: Any) -> BaseTool:
    """工厂函数：返回渲染视频的 LangChain 工具。"""
    return RenderVideoTool(account_id=str(kwargs.get("account_id") or "").strip())
