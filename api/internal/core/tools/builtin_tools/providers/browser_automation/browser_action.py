"""浏览器自动化工具。

通过外部 browser automation worker（Playwright）执行受限的浏览器操作。
平台侧默认关闭：未配置 BROWSER_AUTOMATION_URL / BROWSER_AUTOMATION_TOKEN 时
返回明确错误，不会执行任何浏览器动作。该工具按高风险审批门处理。
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)


class BrowserActionInput(BaseModel):
    """浏览器操作输入。"""

    action: Literal["navigate", "snapshot", "click", "type", "scroll", "back"] = Field(
        "navigate",
        description="浏览器操作：navigate=打开页面，snapshot=读取页面文本，click=点击元素，type=填充输入，scroll=滚动到元素，back=返回",
    )
    url: str = Field(
        "",
        description="目标 URL（仅 http/https）；navigate/snapshot 必填",
    )
    selector: str = Field(
        "",
        description="CSS 选择器；click/type/scroll 必填",
    )
    text: str = Field(
        "",
        description="type 操作要填入的文本",
    )
    wait_ms: int = Field(
        0,
        ge=0,
        le=60000,
        description="操作后等待毫秒数，默认 0",
    )
    timeout: int = Field(
        30000,
        ge=1000,
        le=120000,
        description="浏览器操作超时毫秒数，默认 30000",
    )


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _call_worker(payload: dict[str, Any]) -> dict[str, Any]:
    bridge_url = _normalize_text(os.getenv("DESKTOP_BRIDGE_URL"))
    bridge_token = _normalize_text(os.getenv("DESKTOP_BRIDGE_TOKEN"))
    if bridge_url and bridge_token:
        endpoint = bridge_url.rstrip("/") + "/browser"
        token = bridge_token
    else:
        endpoint = _normalize_text(os.getenv("BROWSER_AUTOMATION_URL"))
        token = _normalize_text(os.getenv("BROWSER_AUTOMATION_TOKEN"))
    if not endpoint or not token:
        return {
            "ok": False,
            "error": "DESKTOP_BRIDGE_URL/TOKEN 或 BROWSER_AUTOMATION_URL/TOKEN 未配置，浏览器自动化默认关闭",
        }
    url = endpoint
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
    timeout = (int(payload.get("timeout") or 30000) // 1000) + 30
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            error_payload = {"error": str(exc)}
        return {"ok": False, "error": error_payload.get("error", str(exc))}
    except Exception as exc:
        return {"ok": False, "error": f"调用浏览器自动化失败: {exc}"}


class BrowserActionTool(BaseTool):
    """在受控浏览器环境中执行网页操作。"""

    name: str = "browser_action"
    description: str = (
        "在受控浏览器中打开网页、读取页面内容、点击元素、填写表单、滚动或返回。"
        "用于需要动态渲染、登录后页面、表单操作的网页任务。该工具默认关闭，"
        "需要平台配置 BROWSER_AUTOMATION_URL / BROWSER_AUTOMATION_TOKEN 且按高风险审批。"
    )
    args_schema: type[BaseModel] = BrowserActionInput

    def _run(self, **kwargs: Any) -> str:
        payload = {
            "action": _normalize_text(kwargs.get("action") or "navigate").lower(),
            "url": _normalize_text(kwargs.get("url")),
            "selector": _normalize_text(kwargs.get("selector")),
            "text": str(kwargs.get("text") or ""),
            "wait_ms": int(kwargs.get("wait_ms") or 0),
            "timeout": int(kwargs.get("timeout") or 30000),
        }
        result = _call_worker(payload)
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)


def browser_action(**kwargs: Any) -> BaseTool:
    """工厂函数：返回浏览器自动化工具。"""
    return BrowserActionTool()
