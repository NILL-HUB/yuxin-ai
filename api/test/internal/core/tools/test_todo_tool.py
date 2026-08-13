import json
import importlib

from internal.core.tools.builtin_tools.providers.todo_tool.todo import TodoTool


def _patch_store(monkeypatch):
    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.todo_tool.todo"
    )
    monkeypatch.setattr(module, "_store", lambda: None)


def test_todo_create_list_complete(monkeypatch):
    _patch_store(monkeypatch)
    tool = TodoTool()
    created = json.loads(tool._run(action="create", board_id="task-1", task="写报告"))
    assert created["ok"] is True
    task_id = created["item"]["id"]

    completed = json.loads(
        tool._run(action="complete", board_id="task-1", task_id=task_id)
    )
    assert completed["ok"] is True
    assert completed["item"]["status"] == "completed"

    listing = json.loads(tool._run(action="list", board_id="task-1"))
    assert listing["count"] == 1
    assert listing["items"][0]["task"] == "写报告"


def test_todo_update_and_delete(monkeypatch):
    _patch_store(monkeypatch)
    tool = TodoTool()
    created = json.loads(tool._run(action="create", board_id="task-2", task="旧标题"))
    task_id = created["item"]["id"]

    updated = json.loads(
        tool._run(action="update", board_id="task-2", task_id=task_id, task="新标题", status="in_progress")
    )
    assert updated["item"]["task"] == "新标题"
    assert updated["item"]["status"] == "in_progress"

    deleted = json.loads(tool._run(action="delete", board_id="task-2", task_id=task_id))
    assert deleted["deleted"] == task_id
    assert json.loads(tool._run(action="list", board_id="task-2"))["count"] == 0


def test_todo_errors(monkeypatch):
    _patch_store(monkeypatch)
    tool = TodoTool()
    assert json.loads(tool._run(action="create", board_id="", task="x"))["ok"] is False
    assert json.loads(tool._run(action="create", board_id="b", task=""))["ok"] is False
    assert json.loads(tool._run(action="complete", board_id="b", task_id="missing"))["ok"] is False
    assert json.loads(tool._run(action="bad", board_id="b"))["ok"] is False


def test_todo_is_persisted_across_calls(monkeypatch):
    _patch_store(monkeypatch)
    tool = TodoTool()
    created = json.loads(tool._run(action="create", board_id="task-3", task="第一项"))
    listing = json.loads(tool._run(action="list", board_id="task-3"))
    assert listing["items"][0]["id"] == created["item"]["id"]
