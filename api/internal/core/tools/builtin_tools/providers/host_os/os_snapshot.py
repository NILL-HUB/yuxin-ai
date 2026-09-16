"""本机文件快照回滚工具。

每次 os_file_task 真实写文件前，worker 会先捕获“写前快照”（内容寻址存于本机
隐藏目录）。用户反馈改错/写坏时，Agent 用本工具回滚：

- rollback_file：按路径回滚单文件（可指定 snapshot_id 精确回滚到历史版本）
- rollback_turn：按 conversation_turn 把该轮 Agent 写过的全部文件批量恢复
  到“用户消息发出前”的状态
- list_snapshots：只读列出快照元数据（不含内容），便于排查历史版本

快照全存宿主机本机、按留存期自动清理（默认 7 天），回滚不依赖任何外部服务。
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


class OsSnapshotInput(BaseModel):
    """本机文件快照回滚操作输入。"""

    op: Literal["rollback_file", "rollback_turn", "list_snapshots"] = Field(
        ...,
        description="rollback_file=按路径回滚单文件；rollback_turn=把某轮用户消息（conversation_turn）期间修改的全部文件批量回滚；list_snapshots=列出快照元数据",
    )
    path: str = Field(
        "",
        description="op=rollback_file 时要回滚的文件路径（也可配合 list_snapshots 过滤）",
    )
    snapshot_id: str = Field(
        "",
        description="op=rollback_file 时指定精确回滚到该快照 ID；留空默认回滚到该文件最新一次可用快照",
    )
    conversation_turn: str = Field(
        "",
        description="op=rollback_turn 时必填：要回滚的用户消息轮次 ID；配合 list_snapshots 可过滤该轮快照",
    )
    limit: int = Field(
        0,
        ge=0,
        description="op=list_snapshots 时最多返回条数；0 表示不限制",
    )
    working_dir: str = Field(
        "",
        description="宿主机工作目录；留空表示安全根目录（默认用户主目录）",
    )
    session_id: str = Field(
        "",
        description="平台会话 ID（conversation_id），便于按会话过滤快照/回滚",
    )
    requester: str = Field(
        "",
        description="调用方账号 ID，用于审计",
    )


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _call_worker(payload: dict[str, Any]) -> dict[str, Any]:
    # 1.优先按账号动态解析已注册的桌面设备 bridge（解决随机 token 无法静态配置的断链）
    from internal.service.desktop_bridge_resolver import resolve_desktop_bridge

    resolved = resolve_desktop_bridge(payload.get("requester"), purpose="/snapshot")
    if resolved:
        bridge_url, bridge_token = resolved
        endpoint = bridge_url.rstrip("/") + "/snapshot"
        token = bridge_token
    else:
        # 2.回退静态配置
        bridge_url = _normalize_text(os.getenv("DESKTOP_BRIDGE_URL"))
        bridge_token = _normalize_text(os.getenv("DESKTOP_BRIDGE_TOKEN"))
        if bridge_url and bridge_token:
            endpoint = bridge_url.rstrip("/") + "/snapshot"
            token = bridge_token
        else:
            endpoint = _normalize_text(os.getenv("OS_AUTOMATION_URL"))
            token = _normalize_text(os.getenv("OS_AUTOMATION_TOKEN"))
    if not endpoint or not token:
        return {
            "ok": False,
            "error": "未找到可用的桌面设备连接（当前账号未注册在线设备），"
                     "且 DESKTOP_BRIDGE_URL/TOKEN、OS_AUTOMATION_URL/TOKEN 均未配置",
        }
    url = endpoint if endpoint.rstrip("/").endswith("/snapshot") else endpoint.rstrip("/") + "/snapshot"
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
        return {"ok": False, "error": f"调用本机快照回滚失败: {exc}"}


class OsSnapshotTool(BaseTool):
    """本机文件写前快照与回滚工具。"""

    name: str = "os_snapshot"
    description: str = (
        "管理本机文件写前快照并回滚文件修改：rollback_file 把单个文件恢复为最近一次"
        "写前快照内容（改错了自愈当前文件）；rollback_turn 把某轮用户消息期间修改的"
        "全部文件批量恢复（大面积返工）；list_snapshots 列出历史快照元数据。"
        "用户反馈文件被改错/改坏时，优先用本工具回滚而不是手工重写文件。"
    )
    args_schema: type[BaseModel] = OsSnapshotInput
    requester: str = ""
    session_id: str = ""
    conversation_turn: str = ""

    def _run(self, **kwargs: Any) -> str:
        op = _normalize_text(kwargs.get("op") or "").lower()
        payload = {
            "op": op,
            "path": _normalize_text(kwargs.get("path")),
            "snapshot_id": _normalize_text(kwargs.get("snapshot_id")),
            "conversation_turn": _normalize_text(
                kwargs.get("conversation_turn") or self.conversation_turn
            ),
            "session_id": _normalize_text(kwargs.get("session_id") or self.session_id),
            "limit": int(kwargs.get("limit") or 0),
            "working_dir": _normalize_text(kwargs.get("working_dir")),
            "requester": _normalize_text(kwargs.get("requester") or self.requester),
        }
        result = _call_worker(payload)
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)


def os_snapshot(**kwargs: Any) -> BaseTool:
    """工厂函数：返回本机文件快照回滚工具。"""
    return OsSnapshotTool(
        requester=_normalize_text(kwargs.get("requester")),
        session_id=_normalize_text(kwargs.get("session_id")),
        conversation_turn=_normalize_text(kwargs.get("conversation_turn")),
    )
