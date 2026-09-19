"""视频加字幕工具（对话内改细节）。

将字幕烧录进画面并存入成品库。

**字幕时间轴由调用方显式提供**（`cues=[{start,end,text}]`）——这是经实测的
刻意设计：现有 ASR（`AudioService.audio_to_text`）只返回纯文本、零时间戳，
无法自动生成时间轴。需要自动对齐时，应由上层（LLM 读 ASR 文本 + 视频时长）
先分配时间轴再传入，而非在本工具内猜测。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _load_task():
    from internal.task.video_edit_tasks import video_subtitle_task

    return video_subtitle_task


class VideoSubtitleInput(BaseModel):
    """字幕输入。"""

    knowledge_base_id: str = Field(..., description="素材所在知识库 id")
    document_id: str = Field(..., description="要加字幕的视频素材 id")
    cues: list[dict] = Field(
        ...,
        description=(
            "字幕条目列表，每项形如 {start: 0.0, end: 1.5, text: '字幕文本'}，"
            "start/end 为秒。**必须由调用方给出时间轴**（系统不做自动对齐）。"
        ),
    )
    name: str = Field("", description="成品名称，可选")


class VideoSubtitleTool(BaseTool):
    """给视频烧录字幕并存入成品库。"""

    name: str = "video_subtitle"
    description: str = (
        "当用户要求给视频加字幕/烧字幕/配字幕时调用。"
        "须提供带时间轴的字幕条目（start/end 秒 + 文本），系统会烧录进画面并存入成品库。"
    )
    args_schema: type[BaseModel] = VideoSubtitleInput
    account_id: str = ""

    def _run(
        self,
        knowledge_base_id: str = "",
        document_id: str = "",
        cues: list[dict] | None = None,
        name: str = "",
        **kwargs: Any,
    ) -> str:
        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps({"ok": False, "error": "缺少当前账号信息，无法加字幕"}, ensure_ascii=False)
        if not str(knowledge_base_id or "").strip() or not str(document_id or "").strip():
            return json.dumps(
                {"ok": False, "error": "缺少知识库或素材信息：需要 knowledge_base_id 与 document_id"},
                ensure_ascii=False,
            )

        normalized = self._normalize_cues(cues)
        if isinstance(normalized, str):
            return json.dumps({"ok": False, "error": normalized}, ensure_ascii=False)

        try:
            async_result = _load_task().delay(
                str(knowledge_base_id), str(document_id), normalized,
                str(name or "").strip(), account_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("字幕任务提交失败 account_id=%s", account_id, exc_info=True)
            return json.dumps(
                {"ok": False, "error": f"字幕任务提交失败：{exc}"}, ensure_ascii=False
            )

        return json.dumps(
            {
                "ok": True,
                "dispatched": True,
                "task_id": str(getattr(async_result, "id", "")),
                "message": "字幕已提交后台烧录，完成后会自动存入成品库",
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _normalize_cues(cues: list[dict] | None) -> list[dict] | str:
        """校验并归一化字幕条目；不合法时返回错误消息字符串。

        在工具层拦下非法时间（早于 service，避免把明显错误的输入丢进 Celery）。
        """
        if not cues:
            return "字幕内容为空：需要至少一条 {start, end, text}"
        normalized: list[dict] = []
        for index, cue in enumerate(cues, start=1):
            if not isinstance(cue, dict):
                return f"第 {index} 条字幕格式错误：应为 {{start, end, text}} 对象"
            text = str(cue.get("text") or "").strip()
            if not text:
                continue
            try:
                start = float(cue.get("start"))
                end = float(cue.get("end"))
            except (TypeError, ValueError):
                return f"第 {index} 条字幕时间非法：start/end 必须是数字（秒）"
            if start < 0:
                return f"第 {index} 条字幕开始时间不能为负"
            if end <= start:
                return f"第 {index} 条字幕结束时间必须晚于开始时间"
            normalized.append({"start": start, "end": end, "text": text})
        if not normalized:
            return "字幕内容为空：至少需要一条非空文本"
        return normalized

    async def _arun(
        self, knowledge_base_id: str = "", document_id: str = "",
        cues: list[dict] | None = None, name: str = "", **kwargs: Any
    ) -> str:
        return self._run(
            knowledge_base_id=knowledge_base_id, document_id=document_id,
            cues=cues, name=name, **kwargs,
        )


def video_subtitle(**kwargs: Any) -> BaseTool:
    """工厂函数（函数名必须与工具名一致）。"""
    return VideoSubtitleTool(account_id=str(kwargs.get("account_id") or "").strip())
