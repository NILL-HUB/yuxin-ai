"""任务清单工具。

对齐 Hermes `todo_tool`：让 Agent 在多步任务中维护待办列表，跨工具调用
共享同一份状态。优先存 Redis（TTL 一天），Redis 不可用时进程内兜底。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_MEMORY_STORE: dict[str, list[dict]] = {}
_TTL_SECONDS = 86400


def _store():
    try:
        from app.http.module import injector
        from redis import Redis

        return injector.get(Redis)
    except Exception:
        return None


def _key(board_id: str) -> str:
    return f"agent:todo:{board_id}"


def _read(board_id: str) -> list[dict]:
    client = _store()
    if client is not None:
        try:
            raw = client.get(_key(board_id))
            if raw:
                return json.loads(raw)
        except Exception:
            logger.warning("读取 todo 失败，回退内存", exc_info=True)
    return list(_MEMORY_STORE.get(board_id, []))


def _write(board_id: str, items: list[dict]) -> None:
    client = _store()
    if client is not None:
        try:
            client.setex(_key(board_id), _TTL_SECONDS, json.dumps(items, ensure_ascii=False))
            return
        except Exception:
            logger.warning("写入 todo 失败，回退内存", exc_info=True)
    _MEMORY_STORE[board_id] = items


class TodoInput(BaseModel):
    action: str = Field(..., description="create/list/update/complete/delete")
    board_id: str = Field(..., description="任务清单标识，建议使用当前会话/任务 ID")
    task: str = Field("", description="任务描述；create/update 时必填")
    task_id: str = Field("", description="任务 ID；update/complete/delete 时必填")
    status: str = Field("pending", description="状态：pending/in_progress/completed/cancelled")


class TodoTool(BaseTool):
    name: str = "todo"
    description: str = (
        "维护多步任务的待办清单：create 创建、list 查看、update 修改、complete 完成、"
        "delete 删除。用同一 board_id 在多次调用间共享状态。"
    )
    args_schema: type[BaseModel] = TodoInput

    def _run(self, action: str, board_id: str, task: str = "", task_id: str = "", status: str = "pending", **kwargs: Any) -> str:
        normalized_action = str(action or "").strip().lower()
        normalized_board = str(board_id or "").strip()
        if not normalized_board:
            return json.dumps({"ok": False, "error": "board_id 不能为空"}, ensure_ascii=False)
        items = _read(normalized_board)

        if normalized_action == "create":
            normalized_task = str(task or "").strip()
            if not normalized_task:
                return json.dumps({"ok": False, "error": "task 不能为空"}, ensure_ascii=False)
            item = {
                "id": "t-" + uuid.uuid4().hex[:12],
                "task": normalized_task,
                "status": "pending",
                "created_at": int(time.time()),
            }
            items.append(item)
            _write(normalized_board, items)
            return json.dumps({"ok": True, "item": item}, ensure_ascii=False)

        if normalized_action == "list":
            return json.dumps({"ok": True, "items": items, "count": len(items)}, ensure_ascii=False)

        if normalized_action in {"update", "complete", "delete"}:
            normalized_id = str(task_id or "").strip()
            target = next((item for item in items if item.get("id") == normalized_id), None)
            if target is None:
                return json.dumps({"ok": False, "error": f"任务不存在: {normalized_id}"}, ensure_ascii=False)
            if normalized_action == "delete":
                items = [item for item in items if item.get("id") != normalized_id]
                _write(normalized_board, items)
                return json.dumps({"ok": True, "deleted": normalized_id}, ensure_ascii=False)
            if normalized_action == "complete":
                target["status"] = "completed"
            else:
                target["status"] = str(status or "pending")
                if str(task or "").strip():
                    target["task"] = str(task).strip()
            _write(normalized_board, items)
            return json.dumps({"ok": True, "item": target}, ensure_ascii=False)

        return json.dumps({"ok": False, "error": f"未知操作: {normalized_action}"}, ensure_ascii=False)

    async def _arun(self, action: str, board_id: str, task: str = "", task_id: str = "", status: str = "pending", **kwargs: Any) -> str:
        return self._run(action=action, board_id=board_id, task=task, task_id=task_id, status=status, **kwargs)


def todo(**kwargs: Any) -> BaseTool:
    return TodoTool()
