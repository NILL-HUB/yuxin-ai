"""Codex OS 自动化工具。

通过宿主机 OS automation worker 调用 Codex CLI，在真实操作系统上执行
用户已确认的系统自动化任务（如磁盘清理、文件整理、环境检查）。
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


class RunOsTaskInput(BaseModel):
    """运行宿主机系统自动化任务的输入。"""

    task: str = Field(
        ...,
        description="用户请求的系统自动化任务描述，例如：安全分析并清理 C 盘临时文件",
    )
    mode: Literal["preview", "apply"] = Field(
        "preview",
        description="preview=只读检查并生成计划；apply=用户确认后执行",
    )
    approval_token: str = Field(
        "",
        description="preview 返回的一次性审批令牌；mode=apply 时必须携带",
    )
    working_dir: str = Field(
        "",
        description="宿主机工作目录；留空表示用户主目录",
    )
    timeout: int = Field(
        180,
        ge=1,
        le=600,
        description="Codex 执行超时秒数，默认 180",
    )
    requester: str = Field(
        "",
        description="调用方账号 ID，用于 worker 审计",
    )


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _call_worker(payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = _normalize_text(os.getenv("OS_AUTOMATION_URL"))
    token = _normalize_text(os.getenv("OS_AUTOMATION_TOKEN"))
    if not endpoint or not token:
        return {
            "ok": False,
            "error": "OS_AUTOMATION_URL / OS_AUTOMATION_TOKEN 未配置，无法调用宿主机自动化",
        }
    url = endpoint.rstrip("/") + "/run"
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
    timeout = int(payload.get("timeout") or 180) + 30
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
        return {"ok": False, "error": f"调用宿主机自动化失败: {exc}"}


class RunOsTaskTool(BaseTool):
    """在宿主机执行经确认的系统自动化任务。"""

    name: str = "run_os_task"
    description: str = (
        "在宿主机操作系统上执行系统自动化任务，例如清理 C 盘垃圾、检查磁盘空间、"
        "整理临时文件。首次调用会进入只读扫描模式，得到 approval_token 和影响计划；"
        "扫描完成后不要直接执行清理，必须先向用户展示可清理项和预估释放空间，"
        "并反问用户希望清理的具体范围（例如回收站、临时文件、缓存目录）。"
        "只有用户在下一条消息中明确指定清理范围后，才能用同一个 approval_token "
        "以 mode=apply 执行；不要替用户自行决定清理范围。"
    )
    args_schema: type[BaseModel] = RunOsTaskInput
    requester: str = ""

    def _run(self, **kwargs: Any) -> str:
        payload = {
            "task": _normalize_text(kwargs.get("task")),
            "mode": _normalize_text(kwargs.get("mode") or "preview").lower(),
            "approval_token": _normalize_text(kwargs.get("approval_token")),
            "working_dir": _normalize_text(kwargs.get("working_dir")),
            "timeout": int(kwargs.get("timeout") or 180),
            "requester": _normalize_text(kwargs.get("requester") or self.requester),
        }
        result = _call_worker(payload)
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)


def run_os_task(**kwargs: Any) -> BaseTool:
    """工厂函数：返回 Codex OS 自动化 LangChain 工具。"""
    return RunOsTaskTool(requester=_normalize_text(kwargs.get("requester")))
