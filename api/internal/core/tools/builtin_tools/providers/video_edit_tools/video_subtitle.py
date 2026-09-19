"""视频加字幕工具（对话内改细节）。

将字幕烧录进画面并存入成品库。

**字幕时间轴默认自动生成**：调用方可以不传 `cues`，此时系统按素材已留存的
ASR 时间轴（`metadata.transcript_segments`）生成字幕；未留存则重跑一次 ASR。
实测依据：SiliconFlow ASR 在 `response_format=verbose_json` 下返回
`segments: [{start, end, text}]`（本项目此前未请求该字段，故历史结论「ASR 无
时间戳」是错的）。

`cues` 仍可显式传入以覆盖自动结果（人工修订的文案 / 精确对齐）。
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
    cues: list[dict] | None = Field(
        None,
        description=(
            "可选的字幕条目列表，每项形如 {start: 0.0, end: 1.5, text: '字幕文本'}，"
            "start/end 为秒。**不传则自动根据素材语音生成时间轴**；"
            "仅在需要人工修订文案或精确对齐时才显式提供。"
        ),
    )
    name: str = Field("", description="成品名称，可选")


class VideoSubtitleTool(BaseTool):
    """给视频烧录字幕并存入成品库。"""

    name: str = "video_subtitle"
    description: str = (
        "当用户要求给视频加字幕/烧字幕/配字幕时调用。"
        "默认自动识别素材语音并生成带时间轴的字幕后烧录进画面；"
        "如需人工指定文案，可额外传入带时间轴的字幕条目（start/end 秒 + 文本）。"
    )
    args_schema: type[BaseModel] = VideoSubtitleInput
    account_id: str = ""
    # 会话上下文：任务完成后据此把成品回填到原消息（对话内成片预览）。
    message_id: str = ""
    conversation_id: str = ""

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

        # 空/缺省 cues 合法：交由 service 自动生成时间轴
        normalized: list[dict] | None = None
        if cues:
            checked = self._normalize_cues(cues)
            if isinstance(checked, str):
                return json.dumps({"ok": False, "error": checked}, ensure_ascii=False)
            normalized = checked

        try:
            async_result = _load_task().delay(
                str(knowledge_base_id), str(document_id), normalized,
                str(name or "").strip(), account_id,
                message_id=str(kwargs.get("message_id") or self.message_id or ""),
                conversation_id=str(kwargs.get("conversation_id") or self.conversation_id or ""),
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
                "message": (
                    "字幕已提交后台烧录（将自动识别语音生成时间轴），完成后会自动存入成品库并在对话中展示"
                    if normalized is None
                    else "字幕已提交后台烧录，完成后会自动存入成品库并在对话中展示"
                ),
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _normalize_cues(cues: list[dict]) -> list[dict] | str:
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
    """工厂函数（函数名必须与工具名一致）。

    message_id / conversation_id 必须一并透传：任务完成后要据此把成品
    回填到原对话消息（遗漏则「对话内成片预览」静默失效）。
    """
    return VideoSubtitleTool(
        account_id=str(kwargs.get("account_id") or "").strip(),
        message_id=str(kwargs.get("message_id") or "").strip(),
        conversation_id=str(kwargs.get("conversation_id") or "").strip(),
    )
