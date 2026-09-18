"""渲染视频工具（对话内出片）。

小钰把编排好的视频脚本交给渲染链路：编译为 HyperFrames composition →
渲染为 MP4 → 自动存入用户的成品库（系统预置、每用户唯一）。

**执行位置（三级路由）**：
1. **用户本机优先**：经桌面 bridge 下发到用户设备上的 render worker，
   吃用户自己的 CPU——把重负载算力外部化，平台服务器只处理轻量内容；
2. **云端回退**：本机通道不可用时，派发 Celery `render` 队列（受
   `RENDER_CLOUD_FALLBACK_ENABLED` 控制，云端链路完整保留、可随时接通）；
3. **明确报错**：两者都不可用时返回可读错误。

注意「通道不可用」与「渲染业务失败」的区别：前者才回退云端，后者直接报错
（详见 local_render_runner 的语义说明）。

account 获取方式与 create_knowledge_base 一致：由运行时挂载点通过工厂参数
account_id 注入当前账号。builtin 工具没有全局 g.account，不做上下文穿透。
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


def _local_enabled() -> bool:
    """本机渲染是否启用（默认启用）。

    注意：容器 config 是**普通 dict**（不是 Flask 那种带 ``__getattr__`` 的子类），
    必须用 ``.get()`` 读取；用 ``getattr`` 会静默取到默认值、开关形同虚设。
    """
    from internal.context import current_app

    return bool(current_app.config.get("RENDER_LOCAL_ENABLED", True))


def _cloud_fallback_enabled() -> bool:
    """云端回退是否启用（默认启用）。"""
    from internal.context import current_app

    return bool(current_app.config.get("RENDER_CLOUD_FALLBACK_ENABLED", True))


def _run_local_render(*, composition: dict, account_id: str, name: str) -> dict:
    from internal.core.tools.builtin_tools.providers.video_render_tools.local_render_runner import (
        render_on_local_device,
    )

    return render_on_local_device(
        composition=composition, account_id=account_id, name=name
    )


def _dispatch_cloud_render(*, composition: dict, account_id: str, name: str) -> dict:
    """派发云端 Celery（原 _dispatch_render 的逻辑原样保留）。"""
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
        guard.release(account_id=account_id, fingerprint=fingerprint)
        logger.warning("渲染派发 Celery 失败 account_id=%s", account_id, exc_info=True)
        raise

    guard.mark_enqueued()
    return {"mode": "celery", "result": async_result, "fingerprint": fingerprint}


def _composition_fingerprint(composition: dict) -> str:
    """脚本指纹：用于防重锁识别「同一脚本重复提交」。"""
    try:
        payload = json.dumps(composition, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        payload = str(composition)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _dispatch_render(composition: dict, account_id: str, name: str) -> dict:
    """三级路由：本机优先 → 云端回退 → 明确报错。"""
    local_attempted = False
    if _local_enabled():
        local_attempted = True
        local_result = _run_local_render(
            composition=composition, account_id=account_id, name=name
        )
        if local_result.get("ok"):
            return {
                "mode": "local",
                "result": local_result,
                "size_bytes": local_result.get("size_bytes", 0),
            }
        if not local_result.get("unavailable"):
            # 通道可用但业务失败：不回退，直接报错
            raise RenderExecutionError(
                local_result.get("error") or "本机渲染失败"
            )
        logger.info(
            "本机渲染通道不可用，尝试云端回退 account_id=%s reason=%s",
            account_id,
            local_result.get("error"),
        )
        local_error = local_result.get("error") or "本机渲染通道不可用"

    if _cloud_fallback_enabled():
        return _dispatch_cloud_render(
            composition=composition, account_id=account_id, name=name
        )

    if local_attempted:
        raise RenderExecutionError(
            f"本机渲染不可用（{local_error}），且云端渲染回退已关闭。"
            "请启动桌面客户端后重试。"
        )
    raise RenderExecutionError("渲染不可用：本机渲染未启用且云端回退已关闭。")


class RenderRejectedError(Exception):
    """渲染被闸门拒绝（并发/重复/积压），消息面向用户可直接展示。"""


class RenderExecutionError(Exception):
    """渲染执行失败（本机与云端均不可用，或本机业务失败），消息可直接展示。"""


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
        except (RenderRejectedError, RenderExecutionError) as exc:
            # 闸门拒绝 / 执行不可用：提示面向用户可直接展示，不当作系统故障
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

        if dispatched.get("mode") == "local":
            return json.dumps(
                {
                    "ok": True,
                    "mode": "local",
                    "message": "视频已在你的电脑上渲染完成，正在存入成品库",
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
