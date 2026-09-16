"""render_video 工具测试：参数校验与错误可读化。

工具不抛异常到 Agent 层，一律返回 {"ok": false, "error": ...}。
"""
import json

import pytest

from internal.core.tools.builtin_tools.providers.video_render_tools.render_video import (
    render_video,
)


def test_missing_account_returns_readable_error():
    tool = render_video()
    payload = json.loads(
        tool._run(
            composition={"composition_id": "main", "duration": 1.0, "segments": [{"start": 0, "duration": 1, "text": "x"}]}
        )
    )

    assert payload["ok"] is False
    assert "账号" in payload["error"]


def test_missing_composition_returns_readable_error():
    tool = render_video(account_id="11111111-1111-1111-1111-111111111111")
    payload = json.loads(tool._run(composition={}))

    assert payload["ok"] is False
    assert "脚本" in payload["error"] or "composition" in payload["error"]


def test_empty_segments_returns_readable_error():
    tool = render_video(account_id="11111111-1111-1111-1111-111111111111")
    payload = json.loads(tool._run(composition={"composition_id": "main", "duration": 1.0, "segments": []}))

    assert payload["ok"] is False


def test_factory_binds_account_id():
    tool = render_video(account_id="abc")

    assert tool.account_id == "abc"


def test_dispatch_prefers_celery(monkeypatch):
    """Celery 可用时必须走后台渲染，不能同步阻塞对话请求。"""
    import importlib
    import sys
    from types import ModuleType, SimpleNamespace

    # 注意：provider 包 __init__ 会把工厂函数 render_video 挂到包属性上
    # （dynamic_import 依赖该属性加载工具），因此不能用
    # `import ...render_video as module`（会取到函数而非模块）。
    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.video_render_tools.render_video"
    )

    dispatched = {}

    class _Task:
        def delay(self, composition, account_id, name):
            dispatched["args"] = (composition, account_id, name)
            return SimpleNamespace(id="task-1")

    fake = ModuleType("internal.task.render_tasks")
    fake.render_composition_task = _Task()
    monkeypatch.setitem(sys.modules, "internal.task.render_tasks", fake)

    def _boom(*args, **kwargs):
        raise AssertionError("Celery 可用时不得走同步执行")

    monkeypatch.setattr(module, "_load_render_service", _boom)

    tool = render_video(account_id="11111111-1111-1111-1111-111111111111")
    composition = {
        "composition_id": "main",
        "duration": 1.0,
        "segments": [{"start": 0, "duration": 1, "text": "x"}],
    }
    payload = json.loads(tool._run(composition=composition, name="片"))

    assert payload["ok"] is True
    assert payload["dispatched"] is True
    assert payload["task_id"] == "task-1"
    assert dispatched["args"][0] is composition, "脚本必须原样透传给任务"


def test_dispatch_falls_back_to_sync_when_celery_unavailable(monkeypatch):
    """派发失败必须回退同步执行，不能把请求丢掉（与 L2 触发同口径）。"""
    import importlib
    import sys
    from types import ModuleType

    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.video_render_tools.render_video"
    )

    class _Task:
        def delay(self, *args, **kwargs):
            raise RuntimeError("broker down")

    fake = ModuleType("internal.task.render_tasks")
    fake.render_composition_task = _Task()
    monkeypatch.setitem(sys.modules, "internal.task.render_tasks", fake)

    called = {}

    class _Service:
        def render_to_render_output_base(self, *, composition_spec, account_id, name):
            called["name"] = name
            return {"document_id": "d1", "knowledge_base_id": "k1", "name": name}

    monkeypatch.setattr(module, "_load_render_service", lambda: _Service())

    tool = render_video(account_id="11111111-1111-1111-1111-111111111111")
    composition = {
        "composition_id": "main",
        "duration": 1.0,
        "segments": [{"start": 0, "duration": 1, "text": "x"}],
    }
    payload = json.loads(tool._run(composition=composition, name="片"))

    assert payload["ok"] is True
    assert payload["dispatched"] is False
    assert payload["document_id"] == "d1"
    assert called["name"] == "片"
