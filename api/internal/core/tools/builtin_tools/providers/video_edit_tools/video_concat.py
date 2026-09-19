"""视频拼接工具（对话内改细节）。

把库内多段视频按给定顺序拼成一段，产物存入成品库。
要求各段编码参数一致（concat demuxer + 流拷贝），否则应改用重编码路径。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _load_task():
    from internal.task.video_edit_tasks import video_concat_task

    return video_concat_task


class VideoConcatInput(BaseModel):
    """拼接输入。"""

    knowledge_base_id: str = Field(..., description="素材所在知识库 id")
    document_ids: list[str] = Field(..., description="要拼接的视频素材 id 列表，按拼接顺序给出")
    name: str = Field("", description="成品名称，可选")


class VideoConcatTool(BaseTool):
    """把多段视频按顺序拼接并存入成品库。"""

    name: str = "video_concat"
    description: str = (
        "当用户要求把多段视频拼成一段/合并视频/串起来时调用。"
        "按传入的素材顺序拼接，产物存入成品库。"
    )
    args_schema: type[BaseModel] = VideoConcatInput
    account_id: str = ""

    def _run(
        self,
        knowledge_base_id: str = "",
        document_ids: list[str] | None = None,
        name: str = "",
        **kwargs: Any,
    ) -> str:
        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps({"ok": False, "error": "缺少当前账号信息，无法拼接"}, ensure_ascii=False)
        if not str(knowledge_base_id or "").strip():
            return json.dumps(
                {"ok": False, "error": "缺少知识库信息：需要 knowledge_base_id"}, ensure_ascii=False
            )

        ids = [str(i).strip() for i in (document_ids or []) if str(i).strip()]
        if len(ids) < 2:
            return json.dumps(
                {"ok": False, "error": "拼接至少需要两段视频素材"}, ensure_ascii=False
            )
        if len(set(ids)) != len(ids):
            return json.dumps(
                {"ok": False, "error": "拼接素材不能重复：请检查 document_ids"}, ensure_ascii=False
            )

        try:
            async_result = _load_task().delay(
                str(knowledge_base_id), ids, str(name or "").strip(), account_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("拼接任务提交失败 account_id=%s", account_id, exc_info=True)
            return json.dumps(
                {"ok": False, "error": f"拼接任务提交失败：{exc}"}, ensure_ascii=False
            )

        return json.dumps(
            {
                "ok": True,
                "dispatched": True,
                "task_id": str(getattr(async_result, "id", "")),
                "message": "视频拼接已提交后台处理，完成后会自动存入成品库",
            },
            ensure_ascii=False,
        )

    async def _arun(
        self, knowledge_base_id: str = "", document_ids: list[str] | None = None,
        name: str = "", **kwargs: Any
    ) -> str:
        return self._run(
            knowledge_base_id=knowledge_base_id, document_ids=document_ids, name=name, **kwargs
        )


def video_concat(**kwargs: Any) -> BaseTool:
    """工厂函数（函数名必须与工具名一致）。"""
    return VideoConcatTool(account_id=str(kwargs.get("account_id") or "").strip())
