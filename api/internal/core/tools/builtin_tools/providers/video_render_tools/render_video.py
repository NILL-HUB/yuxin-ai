"""渲染视频工具（对话内出片）。

小钰把编排好的视频脚本交给渲染链路：编译为 HyperFrames composition →
渲染为 MP4 → 自动存入用户的成品库（系统预置、每用户唯一）。

account 获取方式与 create_knowledge_base 一致：由运行时挂载点通过工厂参数
account_id 注入当前账号。builtin 工具没有全局 g.account，不做上下文穿透。

渲染是分钟级长任务：优先派发 Celery `render` 队列，不可用时回退同步执行，
避免请求静默丢失（与 L2 触发同一容错口径）。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _load_render_service():
    from app.http.module import injector
    from internal.service.render_service import RenderService

    return injector.get(RenderService)


def _dispatch_render(composition: dict, account_id: str, name: str) -> dict:
    """派发渲染：Celery `render` 队列优先，不可用时回退同步执行。

    渲染是分钟级长任务，必须走后台，否则会把对话请求挂住。但派发本身可能失败
    （broker 不可用），此时**回退同步**而不是把请求丢掉——与 L2 触发同一容错口径
    （`KnowledgeBaseService._dispatch_document_l2`）。

    返回 {"mode": "celery"|"sync", "result": ...}。
    """
    try:
        from internal.task.render_tasks import render_composition_task

        async_result = render_composition_task.delay(composition, account_id, name)
        return {"mode": "celery", "result": async_result}
    except Exception:
        logger.warning(
            "渲染派发 Celery 失败，回退同步执行 account_id=%s", account_id, exc_info=True
        )
        service = _load_render_service()
        return {
            "mode": "sync",
            "result": service.render_to_render_output_base(
                composition_spec=composition, account_id=account_id, name=name
            ),
        }


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
        except Exception as exc:
            logger.warning("渲染视频失败 account_id=%s", account_id, exc_info=True)
            return json.dumps(
                {"ok": False, "error": f"渲染视频失败：{exc}"}, ensure_ascii=False
            )

        if dispatched["mode"] == "celery":
            return json.dumps(
                {
                    "ok": True,
                    "dispatched": True,
                    "task_id": str(getattr(dispatched["result"], "id", "")),
                    "message": "视频渲染已提交后台处理，完成后会自动存入成品库",
                },
                ensure_ascii=False,
            )

        result = dispatched["result"]
        return json.dumps(
            {
                "ok": True,
                "dispatched": False,
                "document_id": result.get("document_id", ""),
                "knowledge_base_id": result.get("knowledge_base_id", ""),
                "name": result.get("name", ""),
                "message": "视频已渲染完成并存入成品库",
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
