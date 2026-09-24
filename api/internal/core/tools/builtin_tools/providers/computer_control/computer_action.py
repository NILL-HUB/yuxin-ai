"""计算机控制工具。

通过外部 Computer Control Worker（pyautogui）执行受限的屏幕/鼠标/键盘动作。
平台侧默认关闭：未配置 COMPUTER_CONTROL_URL / COMPUTER_CONTROL_TOKEN 时返回
明确错误。该工具按高风险审批门处理，默认不会自动放行。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)


class ComputerActionInput(BaseModel):
    """计算机操作输入。"""

    actions: list[dict[str, Any]] = Field(
        ...,
        description=(
            "动作序列，每项为 {action, x?, y?, button?, clicks?, amount?, text?, key?, keys?, return_base64?}。"
            "支持 move/click/scroll/type/press/hotkey/screenshot。"
        ),
    )


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _call_worker(payload: dict[str, Any]) -> dict[str, Any]:
    # 1.优先按账号动态解析已注册的桌面设备 bridge（解决随机 token 无法静态配置的断链）
    from internal.service.desktop_bridge_resolver import resolve_desktop_bridge
    from internal.service.tool_credential_resolver import get_tool_credential

    resolved = resolve_desktop_bridge(payload.get("requester"), purpose="/control")
    if resolved:
        endpoint, token = resolved
    else:
        # 2.回退独立 computer worker（DESKTOP_BRIDGE 的静态回退已在 resolve 内部完成）
        endpoint = get_tool_credential("COMPUTER_CONTROL_URL")
        token = get_tool_credential("COMPUTER_CONTROL_TOKEN")
    if not endpoint or not token:
        return {
            "ok": False,
            "error": "未找到可用的桌面设备连接（当前账号未注册在线设备），"
                     "且 DESKTOP_BRIDGE_URL/TOKEN、COMPUTER_CONTROL_URL/TOKEN 均未配置",
        }
    # 桌面桥自带 /control 路由；直连 worker 时才补路径
    url = endpoint if endpoint.rstrip("/").endswith("/control") else endpoint.rstrip("/") + "/control"
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            error_payload = {"error": str(exc)}
        return {"ok": False, "error": error_payload.get("error", str(exc))}
    except Exception as exc:
        return {"ok": False, "error": f"调用计算机控制失败: {exc}"}


class ComputerActionTool(BaseTool):
    """在用户授权的本机执行屏幕/鼠标/键盘操作。"""

    name: str = "computer_action"
    description: str = (
        "在用户授权的主机执行计算机控制：移动/点击鼠标、滚动、输入文本、按键/快捷键、截屏。"
        "用于帮助用户操作桌面应用、填写表单、点击按钮、打开程序。默认关闭，"
        "需要平台配置 COMPUTER_CONTROL_URL / COMPUTER_CONTROL_TOKEN 且按高风险审批。"
    )
    args_schema: type[BaseModel] = ComputerActionInput
    requester: str = ""

    def _run(self, **kwargs: Any) -> str:
        payload = {
            "actions": list(kwargs.get("actions") or []),
            "requester": _normalize_text(kwargs.get("requester") or self.requester),
        }
        result = _call_worker(payload)
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)


def computer_action(**kwargs: Any) -> BaseTool:
    """工厂函数：返回计算机控制工具。"""
    return ComputerActionTool(
        requester=_normalize_text(kwargs.get("requester")),
    )
