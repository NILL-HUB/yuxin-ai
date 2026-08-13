"""本机文件回收站工具。

安全删除模型：删除本机文件/目录前先移入 worker 本地回收站并记录清单，
不物理删除，可随时恢复原处。Agent 自写测试/调试文件可放临时目录，不走回收站。
由于删除可回滚，该工具默认不要求确认弹窗（仍受安全根目录约束）。
用户反馈误删/乱删时，Agent 应优先调用本工具 list 搜索并 restore。
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


class OsRecycleBinInput(BaseModel):
    """本机回收站操作输入。"""

    op: Literal["delete", "list", "restore", "purge"] = Field(
        ...,
        description="delete=移入回收站（不物理删除）；list=列出可恢复条目；restore=按 entry_id/原路径恢复，或按 task_id 批量恢复；purge=物理清理已过留存期的过期条目",
    )
    paths: list[str] = Field(
        default_factory=list,
        description="op=delete 时要移入回收站的文件/目录路径列表",
    )
    path: str = Field(
        "",
        description="op=restore 时按原路径恢复；也可用 entry_id",
    )
    entry_id: str = Field(
        "",
        description="op=restore 时按清单条目 ID 恢复",
    )
    keyword: str = Field(
        "",
        description="op=list 时按路径/原因/任务 ID 搜索关键词",
    )
    task_id: str = Field(
        "",
        description="关联的任务 ID，用于删除清单与列表过滤",
    )
    reason: str = Field(
        "",
        description="删除原因（写入清单，便于误删恢复检索）",
    )
    retention_days: int = Field(
        30,
        ge=1,
        le=365,
        description="回收站留存天数，默认 30；到期后可 purge 物理清理",
    )
    working_dir: str = Field(
        "",
        description="宿主机工作目录；留空表示安全根目录（默认用户主目录）",
    )
    requester: str = Field(
        "",
        description="调用方账号 ID，用于审计",
    )


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _call_worker(payload: dict[str, Any]) -> dict[str, Any]:
    bridge_url = _normalize_text(os.getenv("DESKTOP_BRIDGE_URL"))
    bridge_token = _normalize_text(os.getenv("DESKTOP_BRIDGE_TOKEN"))
    if bridge_url and bridge_token:
        endpoint = bridge_url.rstrip("/") + "/recycle"
        token = bridge_token
    else:
        endpoint = _normalize_text(os.getenv("OS_AUTOMATION_URL"))
        token = _normalize_text(os.getenv("OS_AUTOMATION_TOKEN"))
    if not endpoint or not token:
        return {
            "ok": False,
            "error": "DESKTOP_BRIDGE_URL/TOKEN 或 OS_AUTOMATION_URL/TOKEN 未配置，无法调用本机回收站",
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
        return {"ok": False, "error": f"调用本机回收站失败: {exc}"}


class OsRecycleBinTool(BaseTool):
    """本机文件安全删除与恢复工具。"""

    name: str = "os_recycle_bin"
    description: str = (
        "管理本机文件回收站：delete 把文件/目录移入回收站（可恢复，不物理删除），"
        "list 搜索可恢复条目，restore 恢复原处。用户说误删/乱删时优先调用本工具 "
        "list 搜索并 restore；一次误删多文件时用同一个 task_id 批量恢复，而不是重新创建文件。"
    )
    args_schema: type[BaseModel] = OsRecycleBinInput
    requester: str = ""

    def _run(self, **kwargs: Any) -> str:
        payload = {
            "op": _normalize_text(kwargs.get("op") or "").lower(),
            "paths": list(kwargs.get("paths") or []),
            "path": _normalize_text(kwargs.get("path")),
            "entry_id": _normalize_text(kwargs.get("entry_id")),
            "keyword": _normalize_text(kwargs.get("keyword")),
            "task_id": _normalize_text(kwargs.get("task_id")),
            "reason": _normalize_text(kwargs.get("reason")),
            "retention_days": int(kwargs.get("retention_days") or 30),
            "working_dir": _normalize_text(kwargs.get("working_dir")),
            "requester": _normalize_text(kwargs.get("requester") or self.requester),
        }
        result = _call_worker(payload)
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)


def os_recycle_bin(**kwargs: Any) -> BaseTool:
    """工厂函数：返回本机回收站工具。"""
    return OsRecycleBinTool(requester=_normalize_text(kwargs.get("requester")))
