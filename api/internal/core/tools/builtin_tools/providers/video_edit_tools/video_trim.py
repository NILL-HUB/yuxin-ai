"""视频裁剪工具（对话内改细节）。

把库内某个视频按时间区间裁出一段，产物存入成品库（可检索复用）。
执行走 Celery（不阻塞对话），派发后立即返回任务号。

注意：本工具**不自造剪辑能力**，ffmpeg 命令构造与执行见
`internal.core.video.ffmpeg_edit` / `internal.service.video_edit_service`。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _load_task():
    from internal.task.video_edit_tasks import video_trim_task

    return video_trim_task


class VideoTrimInput(BaseModel):
    """裁剪输入。"""

    knowledge_base_id: str = Field(..., description="素材所在知识库 id")
    document_id: str = Field(..., description="要裁剪的视频素材 id")
    start_sec: float = Field(..., description="开始时间（秒）")
    end_sec: float = Field(0, description="结束时间（秒）；不传或 0 表示裁到末尾")
    name: str = Field("", description="成品名称，可选")


class VideoTrimTool(BaseTool):
    """把视频按时间区间裁剪并存入成品库。"""

    name: str = "video_trim"
    description: str = (
        "当用户要求裁剪/截取/剪出一段视频时调用。"
        "传入素材所在知识库与视频 id、起止秒数，系统会裁剪并存入成品库。"
    )
    args_schema: type[BaseModel] = VideoTrimInput
    account_id: str = ""

    def _run(
        self,
        knowledge_base_id: str = "",
        document_id: str = "",
        start_sec: float = 0,
        end_sec: float = 0,
        name: str = "",
        **kwargs: Any,
    ) -> str:
        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps({"ok": False, "error": "缺少当前账号信息，无法裁剪"}, ensure_ascii=False)
        if not str(knowledge_base_id or "").strip() or not str(document_id or "").strip():
            return json.dumps(
                {"ok": False, "error": "缺少知识库或素材信息：需要 knowledge_base_id 与 document_id"},
                ensure_ascii=False,
            )

        try:
            start = float(start_sec or 0)
            end_raw = float(end_sec or 0)
        except (TypeError, ValueError):
            return json.dumps({"ok": False, "error": "起止时间必须是数字（秒）"}, ensure_ascii=False)
        if start < 0:
            return json.dumps({"ok": False, "error": "开始时间不能为负"}, ensure_ascii=False)
        # end=0 视为「裁到末尾」，交由 service 与时长比对
        end = end_raw if end_raw > 0 else None
        if end is not None and end <= start:
            return json.dumps(
                {"ok": False, "error": "结束时间必须晚于开始时间"}, ensure_ascii=False
            )

        try:
            async_result = _load_task().delay(
                str(knowledge_base_id), str(document_id), start, end,
                str(name or "").strip(), account_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("裁剪任务提交失败 account_id=%s", account_id, exc_info=True)
            return json.dumps(
                {"ok": False, "error": f"裁剪任务提交失败：{exc}"}, ensure_ascii=False
            )

        return json.dumps(
            {
                "ok": True,
                "dispatched": True,
                "task_id": str(getattr(async_result, "id", "")),
                "message": "视频裁剪已提交后台处理，完成后会自动存入成品库",
            },
            ensure_ascii=False,
        )

    async def _arun(
        self, knowledge_base_id: str = "", document_id: str = "",
        start_sec: float = 0, end_sec: float = 0, name: str = "", **kwargs: Any
    ) -> str:
        return self._run(
            knowledge_base_id=knowledge_base_id, document_id=document_id,
            start_sec=start_sec, end_sec=end_sec, name=name, **kwargs,
        )


def video_trim(**kwargs: Any) -> BaseTool:
    """工厂函数（函数名必须与工具名一致，Provider 按此动态导入）。"""
    return VideoTrimTool(account_id=str(kwargs.get("account_id") or "").strip())
