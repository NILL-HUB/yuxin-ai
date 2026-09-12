"""任务清单工具（对齐 Hermes `todo_tool` 的 todos 数组 + merge 语义）。

Hermes 的 todo 是“每会话一个 TodoStore”，一次给 todos 数组、可选 merge，
每次都返回完整清单 + 状态计数。本平台为多租户 Web 形态，用 board_id 隔离
（等同“每会话一份状态”），并保留 create/list/update/complete/delete 的
action 协议以兼容既有调用方。

存储：优先 Redis（TTL 一天），Redis 不可用时进程内兜底。
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

VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
MAX_TODO_ITEMS = 256
MAX_TODO_CONTENT_CHARS = 4000
_TRUNCATION_MARKER = "… [truncated]"


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


# ─── Hermes TodoStore 语义（校验/去重/裁剪）────────────────────────────────────

def _cap_content(content: str) -> str:
    if len(content) > MAX_TODO_CONTENT_CHARS:
        keep = MAX_TODO_CONTENT_CHARS - len(_TRUNCATION_MARKER)
        return content[:keep] + _TRUNCATION_MARKER
    return content


def _validate(item: Any) -> dict[str, str]:
    """规范化单个 todo 项：确保 {id, content, status} 且 status 合法。"""
    if not isinstance(item, dict):
        return {"id": "?", "content": "(invalid item)", "status": "pending"}
    item_id = str(item.get("id", "")).strip() or "?"
    content = str(item.get("content", "")).strip()
    if not content:
        content = "(no description)"
    else:
        content = _cap_content(content)
    status = str(item.get("status", "pending")).strip().lower()
    if status not in VALID_STATUSES:
        status = "pending"
    return {"id": item_id, "content": content, "status": status}


def _dedupe_by_id(todos: list[dict | Any]) -> list[dict | Any]:
    """按 id 去重，保留最后一次出现的位置。"""
    last_index: dict[str, int] = {}
    for i, item in enumerate(todos):
        if not isinstance(item, dict):
            last_index[f"__invalid_{i}"] = i
            continue
        item_id = str(item.get("id", "")).strip() or "?"
        last_index[item_id] = i
    return [todos[i] for i in sorted(last_index.values())]


def _write_todos(board_id: str, todos: list[dict | Any], merge: bool) -> list[dict[str, str]]:
    """按 Hermes 语义写入：merge=False 整体替换，merge=True 按 id 更新+追加。"""
    if not merge:
        items = [_validate(t) for t in _dedupe_by_id(todos)]
    else:
        current = _read(board_id)
        existing = {item.get("id"): item for item in current if item.get("id")}
        for t in _dedupe_by_id(todos):
            if not isinstance(t, dict):
                continue
            item_id = str(t.get("id", "")).strip()
            if not item_id:
                continue
            if item_id in existing:
                if t.get("content") is not None and str(t.get("content") or "").strip():
                    existing[item_id]["content"] = _cap_content(str(t["content"]).strip())
                status = str(t.get("status", "")).strip().lower()
                if status in VALID_STATUSES:
                    existing[item_id]["status"] = status
            else:
                validated = _validate(t)
                existing[item_id] = validated
                current.append(validated)
        seen = set()
        rebuilt = []
        for item in current:
            if item.get("id") not in seen:
                rebuilt.append(item)
                seen.add(item.get("id"))
        items = rebuilt
    items = items[:MAX_TODO_ITEMS]
    _write(board_id, items)
    return items


def _summary(items: list[dict]) -> dict[str, int]:
    return {
        "total": len(items),
        "pending": sum(1 for i in items if i.get("status") == "pending"),
        "in_progress": sum(1 for i in items if i.get("status") == "in_progress"),
        "completed": sum(1 for i in items if i.get("status") == "completed"),
        "cancelled": sum(1 for i in items if i.get("status") == "cancelled"),
    }


class TodoInput(BaseModel):
    action: str = Field(
        "list",
        description="create/list/update/complete/delete；提供 todos 批量参数时忽略本字段",
    )
    board_id: str = Field(..., description="任务清单标识，建议使用当前会话/任务 ID")
    task: str = Field("", description="任务描述；create/update 时必填")
    task_id: str = Field("", description="任务 ID；update/complete/delete 时必填")
    status: str = Field("pending", description="状态：pending/in_progress/completed/cancelled")
    todos: list[dict] | None = Field(
        default=None,
        description="批量待办数组：[{id, content, status}]。提供后走批量写入，忽略 action。"
        "merge=false 整体替换；merge=true 按 id 更新已有项并追加新项。",
    )
    merge: bool = Field(
        default=False,
        description="批量写入时：true 按 id 更新+追加，false（默认）整体替换清单。",
    )


class TodoTool(BaseTool):
    name: str = "todo"
    description: str = (
        "维护多步任务的待办清单。批量写法：todos=[{id, content, status}]（merge=false 替换全表，"
        "merge=true 按 id 更新+追加），不带 todos 时用 action（create/list/update/complete/delete）"
        "逐项操作。用同一 board_id 在多次调用间共享状态。"
    )
    args_schema: type[BaseModel] = TodoInput

    def _run(
        self,
        action: str = "list",
        board_id: str = "",
        task: str = "",
        task_id: str = "",
        status: str = "pending",
        todos: list[dict] | None = None,
        merge: bool = False,
        **kwargs: Any,
    ) -> str:
        normalized_board = str(board_id or "").strip()
        if not normalized_board:
            return json.dumps({"ok": False, "error": "board_id 不能为空"}, ensure_ascii=False)

        # 批量路径（Hermes 语义）：提供 todos 数组时优先于 action
        if todos is not None:
            if isinstance(todos, str):
                try:
                    todos = json.loads(todos)
                except (json.JSONDecodeError, TypeError):
                    return json.dumps(
                        {"ok": False, "error": "todos 必须是数组，收到无法解析的字符串"},
                        ensure_ascii=False,
                    )
            if not isinstance(todos, list):
                return json.dumps(
                    {"ok": False, "error": f"todos 必须是数组，收到 {type(todos).__name__}"},
                    ensure_ascii=False,
                )
            items = _write_todos(normalized_board, todos, bool(merge))
            return json.dumps(
                {"ok": True, "todos": items, "summary": _summary(items)},
                ensure_ascii=False,
            )

        normalized_action = str(action or "").strip().lower()
        items = _read(normalized_board)

        if normalized_action == "create":
            normalized_task = str(task or "").strip()
            if not normalized_task:
                return json.dumps({"ok": False, "error": "task 不能为空"}, ensure_ascii=False)
            item = _validate(
                {
                    "id": "t-" + uuid.uuid4().hex[:12],
                    "content": normalized_task,
                    "status": "pending",
                }
            )
            _write(normalized_board, [*items, item])
            item = {**item, "task": item["content"]}
            return json.dumps(
                {"ok": True, "item": item, "summary": _summary([*items, item])},
                ensure_ascii=False,
            )

        if normalized_action == "list":
            display_items = [
                {**item, "task": item.get("content", "")} if isinstance(item, dict) else item
                for item in items
            ]
            return json.dumps(
                {
                    "ok": True,
                    "items": display_items,
                    "count": len(items),
                    "summary": _summary(items),
                },
                ensure_ascii=False,
            )

        if normalized_action in {"update", "complete", "delete"}:
            normalized_id = str(task_id or "").strip()
            target = next((item for item in items if item.get("id") == normalized_id), None)
            if target is None:
                return json.dumps({"ok": False, "error": f"任务不存在: {normalized_id}"}, ensure_ascii=False)
            if normalized_action == "delete":
                _write(normalized_board, [item for item in items if item.get("id") != normalized_id])
                return json.dumps(
                    {"ok": True, "deleted": normalized_id, "summary": _summary(items)},
                    ensure_ascii=False,
                )
            if normalized_action == "complete":
                target["status"] = "completed"
            else:
                if str(status or "").strip().lower() in VALID_STATUSES:
                    target["status"] = str(status).strip().lower()
                if str(task or "").strip():
                    target["content"] = _cap_content(str(task).strip())
            _write(normalized_board, items)
            target_display = {**target, "task": target.get("content", "")}
            return json.dumps(
                {"ok": True, "item": target_display, "summary": _summary(items)},
                ensure_ascii=False,
            )

        return json.dumps({"ok": False, "error": f"未知操作: {normalized_action}"}, ensure_ascii=False)

    async def _arun(
        self,
        action: str = "list",
        board_id: str = "",
        task: str = "",
        task_id: str = "",
        status: str = "pending",
        todos: list[dict] | None = None,
        merge: bool = False,
        **kwargs: Any,
    ) -> str:
        return self._run(
            action=action,
            board_id=board_id,
            task=task,
            task_id=task_id,
            status=status,
            todos=todos,
            merge=merge,
            **kwargs,
        )


def todo(**kwargs: Any) -> BaseTool:
    return TodoTool()