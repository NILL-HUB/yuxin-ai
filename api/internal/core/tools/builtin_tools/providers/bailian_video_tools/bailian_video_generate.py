"""百炼文生视频工具（对话内 AI 出片）。

把用户的画面描述交给百炼（通义万相）生成 AI 视频，产物存入成品库（可检索复用）。
执行走 Celery（分钟级，不阻塞对话），派发后立即返回任务号；
完成后经 artifact 回填在对话中内联播放。

实现细节见 `internal.service.bailian_video_service`（bl CLI 调用与入库）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "wan2.7-t2v"
_VALID_RESOLUTIONS = {"720P", "1080P"}
_VALID_RATIOS = {"16:9", "9:16", "1:1", "4:3", "3:4"}
_MAX_DURATION_SEC = 15


def _load_task():
    from internal.task.bailian_video_tasks import bailian_video_generate_task

    return bailian_video_generate_task


class BailianVideoGenerateInput(BaseModel):
    """百炼文生视频输入。"""

    prompt: str = Field(..., description="视频画面描述（中文或英文），越具体效果越好")
    name: str = Field("", description="成品名称，可选")
    model: str = Field("", description=f"模型 id，默认 {_DEFAULT_MODEL}；一般无需填写")
    duration: int = Field(0, description=f"时长（秒，1-{_MAX_DURATION_SEC}），默认由模型决定（约 5 秒）")
    resolution: str = Field("", description="分辨率 720P 或 1080P，默认 720P（更省成本）")
    ratio: str = Field("", description="画面比例，如 16:9 / 9:16 / 1:1，默认 16:9")
    image_url: str = Field("", description="图生视频时的首帧图片地址（可公开访问的 URL），可选")


class BailianVideoGenerateTool(BaseTool):
    """调用百炼（通义万相）生成 AI 视频并存入成品库。"""

    name: str = "bailian_video_generate"
    description: str = (
        "当用户要求生成/创作 AI 视频、文生视频、图生视频（无既有素材、从文字描述出片）时调用。"
        "传入画面描述（prompt），系统经百炼（通义万相）生成视频并自动存入成品库。"
        "生成耗时数分钟到半小时（取决于排队），会转入后台执行，完成后在对话中展示可播放成片。"
        "注意：若用户是对知识库已有素材做裁剪/拼接/加字幕，应改用 video_trim / video_concat / video_subtitle。"
    )
    args_schema: type[BaseModel] = BailianVideoGenerateInput
    account_id: str = ""
    # 会话上下文：任务完成后据此把成品回填到原消息（对话内成片预览）。
    message_id: str = ""
    conversation_id: str = ""

    def _run(
        self,
        prompt: str = "",
        name: str = "",
        model: str = "",
        duration: int = 0,
        resolution: str = "",
        ratio: str = "",
        image_url: str = "",
        **kwargs: Any,
    ) -> str:
        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps(
                {"ok": False, "error": "缺少当前账号信息，无法生成视频"}, ensure_ascii=False
            )

        prompt = str(prompt or "").strip()
        if not prompt:
            return json.dumps(
                {"ok": False, "error": "视频描述（prompt）不能为空"}, ensure_ascii=False
            )

        try:
            duration_value = int(duration or 0)
        except (TypeError, ValueError):
            return json.dumps({"ok": False, "error": "时长必须是整数秒"}, ensure_ascii=False)
        if duration_value < 0 or duration_value > _MAX_DURATION_SEC:
            return json.dumps(
                {"ok": False, "error": f"时长需在 1-{_MAX_DURATION_SEC} 秒之间"},
                ensure_ascii=False,
            )

        resolution_value = str(resolution or "").strip().upper()
        if resolution_value and resolution_value not in _VALID_RESOLUTIONS:
            return json.dumps(
                {"ok": False, "error": "分辨率仅支持 720P 或 1080P"}, ensure_ascii=False
            )

        ratio_value = str(ratio or "").strip()
        if ratio_value and ratio_value not in _VALID_RATIOS:
            return json.dumps(
                {"ok": False, "error": f"画面比例仅支持 {'/'.join(sorted(_VALID_RATIOS))}"},
                ensure_ascii=False,
            )

        try:
            async_result = _load_task().delay(
                prompt,
                str(name or "").strip(),
                str(model or "").strip(),
                duration_value,
                resolution_value,
                ratio_value,
                str(image_url or "").strip(),
                account_id,
                message_id=str(kwargs.get("message_id") or self.message_id or ""),
                conversation_id=str(kwargs.get("conversation_id") or self.conversation_id or ""),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("百炼视频生成任务提交失败 account_id=%s", account_id, exc_info=True)
            return json.dumps(
                {"ok": False, "error": f"视频生成任务提交失败：{exc}"}, ensure_ascii=False
            )

        return json.dumps(
            {
                "ok": True,
                "dispatched": True,
                "task_id": str(getattr(async_result, "id", "")),
                "message": "AI 视频生成已提交后台处理（数分钟到半小时），完成后会自动存入成品库并在对话中展示",
            },
            ensure_ascii=False,
        )

    async def _arun(
        self,
        prompt: str = "",
        name: str = "",
        model: str = "",
        duration: int = 0,
        resolution: str = "",
        ratio: str = "",
        image_url: str = "",
        **kwargs: Any,
    ) -> str:
        return self._run(
            prompt=prompt, name=name, model=model, duration=duration,
            resolution=resolution, ratio=ratio, image_url=image_url, **kwargs,
        )


def bailian_video_generate(**kwargs: Any) -> BaseTool:
    """工厂函数（函数名必须与工具名一致，Provider 按此动态导入）。

    message_id / conversation_id 必须一并透传：任务完成后要据此把成品
    回填到原对话消息（遗漏则「对话内成片预览」静默失效）。
    """
    return BailianVideoGenerateTool(
        account_id=str(kwargs.get("account_id") or "").strip(),
        message_id=str(kwargs.get("message_id") or "").strip(),
        conversation_id=str(kwargs.get("conversation_id") or "").strip(),
    )
