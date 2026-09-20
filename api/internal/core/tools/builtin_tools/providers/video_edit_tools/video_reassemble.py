"""视频成片编排工具（对话内改细节）。

把库内一个成片/视频按时间线段落重新编排（调整顺序 / 删除 / 用其他素材段落
替换），产物存入成品库（可检索复用）。执行走 Celery（不阻塞对话），派发后
立即返回任务号。

clips 以 **JSON 字符串** 传入（工具参数 type 枚举限制，见 video_reassemble.yaml）：
  [{"document_id": "...", "segment_index": 3}, ...]
`segment_index` 为 1-based 段落序号；0 / 缺省表示取该素材完整视频。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _load_task():
    from internal.task.video_edit_tasks import video_reassemble_task

    return video_reassemble_task


class VideoReassembleInput(BaseModel):
    """成片编排输入。"""

    knowledge_base_id: str = Field(..., description="素材所在知识库 id")
    document_id: str = Field(..., description="主视频（成片）素材 id")
    clips: str = Field(
        ...,
        description="编排片段 JSON 数组字符串，如 [{\"document_id\":\"..\",\"segment_index\":3}]；"
        "segment_index 为 1-based 段落序号，0/缺省取整段",
    )
    name: str = Field("", description="成品名称，可选")


class VideoReassembleTool(BaseTool):
    """把视频按时间线编排重排/删段/替换并存入成品库。"""

    name: str = "video_reassemble"
    description: str = (
        "当用户要求把一段成片/视频的时间线段落重新编排（调整顺序、删除某段、"
        "用其他素材的段落替换某段）时调用。clips 传 JSON 字符串数组，"
        "每项含 document_id 与 segment_index（1-based 段落序号，0/缺省取整段）。"
    )
    args_schema: type[BaseModel] = VideoReassembleInput
    account_id: str = ""
    # 会话上下文：任务完成后据此把成品回填到原消息（对话内成片预览）。
    message_id: str = ""
    conversation_id: str = ""

    def _run(
        self, knowledge_base_id: str = "", document_id: str = "",
        clips: str = "", name: str = "", **kwargs: Any,
    ) -> str:
        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps({"ok": False, "error": "缺少当前账号信息，无法编排"}, ensure_ascii=False)
        if not str(knowledge_base_id or "").strip() or not str(document_id or "").strip():
            return json.dumps(
                {"ok": False, "error": "缺少知识库或素材信息：需要 knowledge_base_id 与 document_id"},
                ensure_ascii=False,
            )

        try:
            parsed = json.loads(str(clips or "").strip() or "[]")
        except json.JSONDecodeError:
            return json.dumps({"ok": False, "error": "编排片段必须是合法 JSON 数组"}, ensure_ascii=False)
        if not isinstance(parsed, list) or not parsed:
            return json.dumps({"ok": False, "error": "编排至少需要一个片段"}, ensure_ascii=False)
        for clip in parsed:
            if not isinstance(clip, dict) or not str(clip.get("document_id") or "").strip():
                return json.dumps({"ok": False, "error": "编排片段缺少 document_id"}, ensure_ascii=False)
            try:
                seg = int(clip.get("segment_index") or 0)
            except (TypeError, ValueError):
                return json.dumps({"ok": False, "error": "段落序号必须是整数（1-based）"}, ensure_ascii=False)
            if seg < 0:
                return json.dumps({"ok": False, "error": "段落序号不能为负"}, ensure_ascii=False)

        try:
            async_result = _load_task().delay(
                str(knowledge_base_id), str(document_id), parsed,
                str(name or "").strip(), account_id,
                message_id=str(kwargs.get("message_id") or self.message_id or ""),
                conversation_id=str(kwargs.get("conversation_id") or self.conversation_id or ""),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("编排任务提交失败 account_id=%s", account_id, exc_info=True)
            return json.dumps({"ok": False, "error": f"编排任务提交失败：{exc}"}, ensure_ascii=False)

        return json.dumps(
            {
                "ok": True,
                "dispatched": True,
                "task_id": str(getattr(async_result, "id", "")),
                "message": "成片编排已提交后台处理，完成后会自动存入成品库并在对话中展示",
            },
            ensure_ascii=False,
        )

    async def _arun(
        self, knowledge_base_id: str = "", document_id: str = "",
        clips: str = "", name: str = "", **kwargs: Any,
    ) -> str:
        return self._run(
            knowledge_base_id=knowledge_base_id, document_id=document_id,
            clips=clips, name=name, **kwargs,
        )


def video_reassemble(**kwargs: Any) -> BaseTool:
    """工厂函数（函数名必须与工具名一致，Provider 按此动态导入）。

    message_id / conversation_id 必须一并透传：任务完成后要据此把成品
    回填到原对话消息（遗漏则「对话内成片预览」静默失效）。
    """
    return VideoReassembleTool(
        account_id=str(kwargs.get("account_id") or "").strip(),
        message_id=str(kwargs.get("message_id") or "").strip(),
        conversation_id=str(kwargs.get("conversation_id") or "").strip(),
    )
