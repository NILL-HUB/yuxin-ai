"""本机终端工具（Windows: CMD / GitBash）。

在用户本机的安全根目录内执行单条命令（一次性、非交互、有超时与输出上限）。
经统一桌面桥转发到 worker /exec 端点。

治理约束（重要）：终端不得成为绕过删除治理的出口。worker 在执行前做
fail-closed 删除命令守卫——物理删除类命令（rm/del/rd/Remove-Item/…）、
内联解释器代码（python -c / bash -c / powershell -Command）、脚本文件内容、
管道到解释器（curl | bash）等形态一律拒绝，并引导改用 os_recycle_bin
（移入回收站、可恢复、平台可见）。工具描述中已向模型声明该约束。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from ..worker_client import call_host_worker


logger = logging.getLogger(__name__)


class OsTerminalInput(BaseModel):
    """本机终端命令输入。"""

    command: str = Field(
        ...,
        description="要执行的命令（单条；可用 && / ; / | 组合多条，遵循所选 shell 的语法）",
    )
    shell: Literal["cmd", "gitbash"] = Field(
        "gitbash",
        description=(
            "gitbash=Git Bash（默认；Unix 风格命令与 Git：ls/cat/grep/sed/awk/find/git/"
            "npm/pip/python/curl，需本机安装 Git for Windows）；"
            "cmd=Windows 原生命令行（dir/type/findstr/tasklist/where/批处理等）"
        ),
    )
    working_dir: str = Field(
        "",
        description="工作目录（必须位于安全根目录内，越界会回退到安全根）；留空表示安全根目录",
    )
    timeout_seconds: int = Field(
        60,
        ge=1,
        le=300,
        description="命令超时秒数（默认 60，上限 300）；超时会终止整个进程树",
    )
    requester: str = Field(
        "",
        description="调用方账号 ID，用于审计",
    )


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _call_worker(payload: dict[str, Any], *, timeout: int = 60) -> dict[str, Any]:
    return call_host_worker(
        payload,
        purpose="/exec",
        error_prefix="调用本机终端失败",
        timeout=timeout,
    )


class OsTerminalTool(BaseTool):
    """在用户本机执行命令行（CMD / GitBash）。"""

    name: str = "os_terminal"
    description: str = (
        "在用户本机执行真实命令行——**本机任务的主力执行手段**，不是可选补充："
        "查看目录与文件（ls/cat/head/wc）、Git 操作（status/diff/log/add/commit/branch）、"
        "安装依赖（npm/pip/uv）、构建与编译、运行测试与脚本、查看系统与进程信息"
        "（tasklist/ps/where/which）、批量处理文件等，都应当用本工具执行真实命令来完成，"
        "而不是靠逐个手工操作。默认 shell=gitbash（Unix 语法；需本机安装 Git for Windows）；"
        "Windows 原生命令（dir/type/findstr/tasklist/where/批处理）用 shell=cmd。"
        "一次性执行、非交互，返回 stdout/stderr 与退出码；工作目录限于安全根目录内，"
        "超时默认 60 秒（上限 300），超长输出会截断。"
        "工具分工：执行命令用本工具；**改写文件内容**（编辑/新建/打补丁）优先用 "
        "os_file_task（有写前快照、可回滚）；**删除**只能走 os_recycle_bin。"
        "执行前会自动对工作目录做**增量写前快照**（内容寻址，排除 node_modules/.git "
        "等可再生目录）：命令若改坏文件，可用 os_snapshot 回滚——rollback_file 恢复单个"
        "文件、rollback_turn 按本轮（同一 conversation_turn）批量恢复；结果里的 changes "
        "字段列出本次被改动的文件。工作目录过大或快照失败会在结果中明确提示（后者拒绝"
        "执行）。建议 working_dir 指向具体项目目录，快照更快、覆盖更准。"
        "⚠️ 删除类命令被系统硬阻断：rm/del/rd/Remove-Item 等物理删除、"
        "内联解释器代码（python -c、bash -c、powershell -Command）、脚本文件内容、"
        "管道到解释器（curl | bash）等形态一律拒绝并报错——"
        "需要删除文件时直接调用 os_recycle_bin，不要尝试用终端删除。"
    )
    args_schema: type[BaseModel] = OsTerminalInput
    requester: str = ""
    session_id: str = ""
    conversation_turn: str = ""

    def _run(self, **kwargs: Any) -> str:
        try:
            timeout_seconds = int(kwargs.get("timeout_seconds") or 60)
        except (TypeError, ValueError):
            timeout_seconds = 60
        timeout_seconds = max(1, min(timeout_seconds, 300))
        payload = {
            "command": str(kwargs.get("command") or ""),
            "shell": _normalize_text(kwargs.get("shell") or "gitbash").lower() or "gitbash",
            "working_dir": _normalize_text(kwargs.get("working_dir")),
            "timeout_seconds": timeout_seconds,
            "requester": _normalize_text(kwargs.get("requester") or self.requester),
            # 写前快照按会话/轮次分组：os_snapshot rollback_turn 可回滚本轮全部终端改动
            "session_id": _normalize_text(kwargs.get("session_id") or self.session_id),
            "conversation_turn": _normalize_text(
                kwargs.get("conversation_turn") or self.conversation_turn
            ),
        }
        # urllib 超时需大于命令自身超时，否则超时结果在回传前被客户端掐断
        result = _call_worker(payload, timeout=max(60, timeout_seconds + 30))
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)


def os_terminal(**kwargs: Any) -> BaseTool:
    """工厂函数：返回本机终端工具。"""
    return OsTerminalTool(
        requester=_normalize_text(kwargs.get("requester")),
        session_id=_normalize_text(kwargs.get("session_id")),
        conversation_turn=_normalize_text(kwargs.get("conversation_turn")),
    )
