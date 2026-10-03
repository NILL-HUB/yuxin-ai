"""计算机控制工具。

⚠️ 能力归属（重要）：本工具真正的执行端是**桌面客户端**（本机 bridge + cua-driver
定向控制）。Web 端**不能操作用户本机**；服务端的 `llmops-computer-worker` 只提供
**容器内 xvfb 虚拟桌面**，且默认不启动（compose profile: local-workers）。

因此未安装桌面端时，本工具返回**诚实的「不可用」**并引导安装桌面端，不做静默降级。
该工具按高风险审批门处理，默认不会自动放行。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from ..worker_client import call_host_worker


logger = logging.getLogger(__name__)


class ComputerActionInput(BaseModel):
    """计算机操作输入。"""

    actions: list[dict[str, Any]] = Field(
        ...,
        description=(
            "动作序列，每项为 {action, ...}。"
            "【前台坐标动作】move/click 需 x/y 坐标；scroll 需 amount（正负控制方向）；"
            "type 需 text；press 需 key；hotkey 需 keys 列表；screenshot 无必需参数。"
            "【cua 观察】capture：返回目标窗口可访问性元素树"
            "（tree_markdown / elements，每项含 element_index 供后续寻址）；"
            "参数 include_accessibility_tree / include_screenshot（默认均 true），"
            "可附 pid 或 window_id 绑定窗口；capture 只返回元素树，不回传截图。"
            "【cua 元素寻址】click/double_click/right_click/set_value/type/press/scroll "
            "可带 element_index 或 element_token（来自 capture 结果）按元素定位，"
            "带元素参数时 click 类动作不需要 x/y；set_value 需 value。"
            "【cua 应用管理】list_apps / list_windows / launch_app"
            "（launch_app 需 name/path/aumid/bundle_id 之一）。"
            "【cua 拖拽】drag：需 from_x/from_y/to_x/to_y 坐标（可附 pid/window_id 定位窗口）。"
            "【行为语义】cua 动作由桌面端 cua-driver 后台执行，不抢焦点、不移动真实鼠标；"
            "回执含 verified/effect/escalation/delivery（delivery.mode=background|foreground），"
            "据此判断执行效果，仅当动作被结构化拒绝（escalation）时才升级为前台坐标方式；"
            "回执 backend 字段标明实际执行后端，auto 模式下 cua 不可用时共享动作可能自动回退前台执行。"
            "【截图回传】screenshot 动作仅当 return_base64=true 时回传截图"
            "（默认不回传，节省流量与配额）。"
        ),
    )


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _call_worker(payload: dict[str, Any]) -> dict[str, Any]:
    return call_host_worker(
        payload,
        purpose="/control",
        error_prefix="调用计算机控制失败",
        static_url_env="COMPUTER_CONTROL_URL",
        static_token_env="COMPUTER_CONTROL_TOKEN",
        unavailable_error=(
            "无法操作你的电脑：当前账号没有可用的在线桌面设备。"
            "「操作本机」只能由桌面客户端完成——请安装并登录桌面端、保持其在线；"
            "Web 端不操作用户本机（服务端仅提供容器内虚拟桌面通道，且默认不启用）。"
        ),
    )


def _persist_screenshot(base64_str: str, requester: str) -> str:
    """截图落存储并返回稳定 URL（FileCenterService 权威入口）。失败抛错交调用方兜底。"""
    import base64 as b64lib
    import uuid

    content = b64lib.b64decode(base64_str, validate=True)
    filename = f"computer_control_{uuid.uuid4().hex}.png"
    if requester:
        from app.http.module import injector
        from internal.service.file_center_service import FileCenterService

        return injector.get(FileCenterService).save_generated_asset(
            requester,
            filename=filename,
            content=content,
            folder="generated-images",
        )["url"]
    from app.http.module import injector
    from internal.service.storage.runtime_storage_service import RuntimeStorageProxy

    return injector.get(RuntimeStorageProxy).upload_bytes_without_record(
        filename=filename,
        content=content,
        folder="generated-images",
    )


def _replace_screenshot(result: dict[str, Any], requester: str) -> dict[str, Any]:
    """把 worker 回传的 base64 截图替换为存储 URL。

    base64 绝不进工具结果（会撑爆 token）；存储失败时标注 screenshot_saved=false，
    元素树/动作回执等主干字段不受影响。
    """
    if not isinstance(result, dict):
        return result
    base64_str = str(result.pop("screenshot_base64", "") or "")
    if not base64_str:
        return result
    try:
        url = _persist_screenshot(base64_str, requester)
    except Exception:
        logger.warning("截图落存储失败", exc_info=True)
        result["screenshot_saved"] = False
        return result
    result["screenshot_saved"] = True
    result["screenshot_url"] = url
    result["screenshot"] = f"![screenshot]({url})"
    return result


class ComputerActionTool(BaseTool):
    """在用户授权的本机执行屏幕/鼠标/键盘操作。"""

    name: str = "computer_action"
    description: str = (
        "在用户授权的主机执行计算机控制，遵循「观察-行动」循环："
        "先用 capture 获取目标窗口可访问性元素树（tree_markdown，含 element_index），"
        "再按 element_index 元素寻址执行 click/set_value/type 等动作"
        "（cua 后台执行，不抢焦点、不移动真实鼠标）；"
        "回执 verified/effect/escalation 用于判断执行效果，"
        "仅当被结构化拒绝时才升级前台坐标方式。"
        "也支持前台坐标动作（move/click/scroll/type/press/hotkey/screenshot）"
        "与应用管理（list_apps/list_windows/launch_app）。"
        "⚠️ 文件治理禁令：不得用本工具删除、修改文件或执行命令（包括打开资源管理器删除、"
        "往终端窗口输入命令等）——文件操作一律走 os_file_task / os_recycle_bin / os_terminal"
        "（有写前快照与回收站治理、可回滚），本工具仅用于没有命令行等价物的 GUI 操作；"
        "GUI 操作没有快照兜底，破坏不可恢复。"
        "⚠️ 需要账号有在线桌面设备，或已配置服务端控制通道（容器内虚拟桌面，非用户真实电脑）；"
        "操作用户真实电脑的执行端为桌面客户端，两者皆无时返回不可用。按高风险审批。"
    )
    args_schema: type[BaseModel] = ComputerActionInput
    requester: str = ""
    device_id: str = ""

    def _run(self, **kwargs: Any) -> str:
        payload = {
            "actions": list(kwargs.get("actions") or []),
            "requester": _normalize_text(kwargs.get("requester") or self.requester),
            "device_id": _normalize_text(kwargs.get("device_id") or self.device_id),
        }
        result = _replace_screenshot(_call_worker(payload), str(payload["requester"]))
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)


def computer_action(**kwargs: Any) -> BaseTool:
    """工厂函数：返回计算机控制工具。"""
    return ComputerActionTool(
        requester=_normalize_text(kwargs.get("requester")),
        device_id=_normalize_text(kwargs.get("device_id")),
    )
