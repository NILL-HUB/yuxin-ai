"""宿主机文件操作工具。

通过 OS automation worker 在宿主机安全目录内执行文件读取与 V4A 补丁。
写操作无需逐次人工确认：worker 每次真实写文件前自动捕获写前快照（删除类
操作移入本机回收站），改错可经 os_snapshot 一键回滚；mode=preview 仍可做
只读 dry-run 预检查补丁可应用性与影响范围。走统一桌面桥时请求经
DESKTOP_BRIDGE_URL/TOKEN 转发到 worker /file。
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


class OsFileTaskInput(BaseModel):
    """宿主机文件操作输入。"""

    op: Literal["read", "search", "patch"] = Field(
        ...,
        description="read=读取文件内容（支持分页）；search=在目录内用 ripgrep 搜索文件内容；patch=应用 V4A 补丁修改文件",
    )
    path: str = Field(
        "",
        description="目标文件/目录路径；op=read 时必填，op=patch 时可省略（路径写在补丁内），op=search 时可选（限定搜索范围）",
    )
    patch: str = Field(
        "",
        description="V4A 补丁内容；op=patch 时必填，格式见系统提示",
    )
    mode: Literal["preview", "apply"] = Field(
        "apply",
        description="preview=只读 dry-run 校验补丁可应用性与影响（不落盘）；apply=直接执行修改（默认，写前自动快照，可经 os_snapshot 回滚）",
    )
    approval_token: str = Field(
        "",
        description="历史兼容字段：apply 已无需审批令牌（写前快照兜底），可省略；preview 响应仍返回 token 仅为旧客户端兼容",
    )
    working_dir: str = Field(
        "",
        description="宿主机工作目录；留空表示安全根目录（默认用户主目录）",
    )
    requester: str = Field(
        "",
        description="调用方账号 ID，用于审计",
    )
    session_id: str = Field(
        "",
        description="平台会话 ID（conversation_id），随写前快照写入 manifest 便于按会话追溯/回滚",
    )
    conversation_turn: str = Field(
        "",
        description="平台消息轮次 ID（用户消息边界），写前快照据此分组；os_snapshot rollback_turn 用同一 ID 批量回滚该轮全部修改",
    )
    pattern: str = Field(
        "",
        description="op=search 时的搜索关键词（正则），如 'TODO\\|FIXME'",
    )
    offset: int = Field(
        0,
        ge=0,
        description="op=read 时的起始行号（0 基线），配合 limit 分页读取大文件",
    )
    limit: int = Field(
        0,
        ge=0,
        description="op=read 时读取的最大行数；0 表示走默认字符上限，配合 offset 使用",
    )


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _call_worker(payload: dict[str, Any]) -> dict[str, Any]:
    bridge_url = _normalize_text(os.getenv("DESKTOP_BRIDGE_URL"))
    bridge_token = _normalize_text(os.getenv("DESKTOP_BRIDGE_TOKEN"))
    if bridge_url and bridge_token:
        endpoint = bridge_url.rstrip("/") + "/file"
        token = bridge_token
    else:
        # OS_AUTOMATION_URL 指向 worker 根地址，需补 /file 路径
        endpoint = _normalize_text(os.getenv("OS_AUTOMATION_URL"))
        token = _normalize_text(os.getenv("OS_AUTOMATION_TOKEN"))
    if not endpoint or not token:
        return {
            "ok": False,
            "error": "DESKTOP_BRIDGE_URL/TOKEN 或 OS_AUTOMATION_URL/TOKEN 未配置，无法调用宿主机文件操作",
        }
    url = endpoint if bridge_url and bridge_token else endpoint.rstrip("/") + "/file"
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
        return {"ok": False, "error": f"调用宿主机文件操作失败: {exc}"}


class OsFileTaskTool(BaseTool):
    """在宿主机安全目录内读取文件或应用 V4A 补丁。"""

    name: str = "os_file_task"
    description: str = (
        "在宿主机操作系统上读取/搜索文件，或应用 V4A 补丁修改文件。"
        "read 模式直接返回文件内容（可带 offset/limit 分页）；search 模式在目录内"
        "用 ripgrep 搜索文件内容并返回命中的行；patch 模式默认 mode=apply 直接执行"
        "修改——worker 会在写前自动为受影响文件捕获快照、删除类操作移入回收站，"
        "改错可用 os_snapshot 工具回滚，无需逐次用户确认；如需先预检查，可用 "
        "mode=preview 做只读 dry-run 校验（不落盘）。注意：敏感文件（如 ~/.ssh 私钥、"
        ".env 密钥、浏览器凭据库、系统凭据目录）不可读，read/search 命中会被 worker 拒绝。"
        "补丁格式：*** Begin Patch / "
        "*** Add File: 路径 / +内容行 / *** Update File: 路径 / @@ 上下文 / "
        "-删除行 / +新增行 / *** Delete File: 路径 / *** Move File: 旧路径 -> 新路径 "
        "/ *** End Patch。"
    )
    args_schema: type[BaseModel] = OsFileTaskInput
    requester: str = ""
    session_id: str = ""
    conversation_turn: str = ""

    def _run(self, **kwargs: Any) -> str:
        payload = {
            "op": _normalize_text(kwargs.get("op") or "read").lower(),
            "path": _normalize_text(kwargs.get("path")),
            "patch": str(kwargs.get("patch") or ""),
            "mode": _normalize_text(kwargs.get("mode") or "apply").lower(),
            "approval_token": _normalize_text(kwargs.get("approval_token")),
            "working_dir": _normalize_text(kwargs.get("working_dir")),
            "requester": _normalize_text(kwargs.get("requester") or self.requester),
            "session_id": _normalize_text(kwargs.get("session_id") or self.session_id),
            "conversation_turn": _normalize_text(
                kwargs.get("conversation_turn") or self.conversation_turn
            ),
            "pattern": _normalize_text(kwargs.get("pattern")),
            "offset": int(kwargs.get("offset") or 0),
            "limit": int(kwargs.get("limit") or 0),
        }
        result = _call_worker(payload)
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)


def os_file_task(**kwargs: Any) -> BaseTool:
    """工厂函数：返回宿主机文件操作 LangChain 工具。"""
    return OsFileTaskTool(
        requester=_normalize_text(kwargs.get("requester")),
        session_id=_normalize_text(kwargs.get("session_id")),
        conversation_turn=_normalize_text(kwargs.get("conversation_turn")),
    )
