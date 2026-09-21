"""外部素材获取工具（KB-P6）。

把公开网页视频/音频 URL 下载、上传、建档入知识库。执行走 Celery，派发后立即返回任务号。
启用与否由工具实例字段 `enabled` 决定，其单一事实源是 admin 公共 AI 配置的
`media_fetch` 开关（挂载点在构造时经 `fetch_media(**kwargs)` 注入 enabled=）。
仅支持平台可匿名抓取内容，不做登录态/Cookies。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _load_task():
    from internal.task.media_fetch_tasks import media_fetch_task
    return media_fetch_task


class FetchMediaInput(BaseModel):
    url: str = Field(..., description="要下载的视频/音频网页 URL（公开可访问）")
    knowledge_base_id: str = Field(..., description="目标知识库 id")
    resolution: str = Field("", description="可选目标分辨率（预留），暂不生效")
    max_bytes: int = Field(0, description="可选体积上限(字节)；0=不限制")


class FetchMediaTool(BaseTool):
    name: str = "fetch_media"
    description: str = (
        "当用户要求把一个外部视频/音频链接保存进知识库时调用。"
        "支持主流平台(YouTube/Bilibili/Vimeo 等)可公开访问的页面，仅获取平台可匿名抓取的内容，"
        "系统会下载、上传并开始解析入库；此能力默认需管理员开启。"
    )
    args_schema: type[BaseModel] = FetchMediaInput
    account_id: str = ""
    message_id: str = ""
    conversation_id: str = ""
    # 启用开关：由挂载点在构造时经 fetch_media(enabled=...) 注入（服务端 admin 公共 AI 配置 media_fetch）。
    enabled: bool = True

    def _run(self, url: str = "", knowledge_base_id: str = "",
             resolution: str = "", max_bytes: int = 0, **kwargs: Any) -> str:
        account_id = str(kwargs.get("account_id") or self.account_id or "").strip()
        if not account_id:
            return json.dumps({"ok": False, "error": "缺少当前账号信息，无法保存素材"}, ensure_ascii=False)
        if not str(url or "").strip() or not str(knowledge_base_id or "").strip():
            return json.dumps({"ok": False, "error": "需要 url 与 knowledge_base_id"}, ensure_ascii=False)
        if not self.enabled:
            return json.dumps({"ok": False, "error": "外部素材获取能力未开启，请在管理后台-公共 AI 配置中开启"}, ensure_ascii=False)
        try:
            size = int(max_bytes or 0)
        except (TypeError, ValueError):
            return json.dumps({"ok": False, "error": "max_bytes 必须是整数(字节)"}, ensure_ascii=False)
        if size < 0:
            return json.dumps({"ok": False, "error": "max_bytes 不能为负"}, ensure_ascii=False)
        try:
            async_result = _load_task().delay(
                str(url).strip(), str(knowledge_base_id).strip(), account_id,
                resolution=str(resolution or "").strip(),
                max_bytes=size if size > 0 else None,
                message_id=str(kwargs.get("message_id") or self.message_id or ""),
                conversation_id=str(kwargs.get("conversation_id") or self.conversation_id or ""),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("外部素材任务提交失败 account_id=%s", account_id, exc_info=True)
            return json.dumps({"ok": False, "error": f"任务提交失败：{exc}"}, ensure_ascii=False)
        return json.dumps({
            "ok": True, "dispatched": True,
            "task_id": str(getattr(async_result, "id", "")),
            "message": "外部素材已提交下载，完成后会自动存入知识库并开始解析",
        }, ensure_ascii=False)

    async def _arun(self, url: str = "", knowledge_base_id: str = "",
                    resolution: str = "", max_bytes: int = 0, **kwargs: Any) -> str:
        return self._run(url=url, knowledge_base_id=knowledge_base_id,
                         resolution=resolution, max_bytes=max_bytes, **kwargs)


def fetch_media(**kwargs: Any) -> BaseTool:
    return FetchMediaTool(
        account_id=str(kwargs.get("account_id") or "").strip(),
        message_id=str(kwargs.get("message_id") or "").strip(),
        conversation_id=str(kwargs.get("conversation_id") or "").strip(),
        enabled=bool(kwargs.get("enabled", True)),
    )