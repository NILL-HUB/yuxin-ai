"""render_video 工具测试：参数校验、闸门准入与错误可读化。

工具不抛异常到 Agent 层，一律返回 {"ok": false, "error": ...}。
"""
import importlib
import json

import pytest

from internal.core.tools.builtin_tools.providers.video_render_tools.render_video import (
    render_video,
)


def _render_video_module():
    """取 render_video 子模块本体。

    包 ``video_render_tools/__init__.py`` 把 ``render_video`` 重绑定为工厂函数，
    故 ``from ...video_render_tools import render_video`` 拿到的是函数而非模块，
    必须用 importlib 显式取子模块才能 monkeypatch 模块级私有函数。
    """
    return importlib.import_module(
        "internal.core.tools.builtin_tools.providers.video_render_tools.render_video"
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


def _install_fakes(monkeypatch, *, delay, admission_allowed=True, admission_reason=""):
    """装配 render_tasks 与闸门的替身，返回 (module, guard 记录)。"""
    import importlib
    import sys
    from types import ModuleType, SimpleNamespace

    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.video_render_tools.render_video"
    )

    # 既有用例聚焦云端链路：显式关掉本机渲染，避免命中本机分支
    monkeypatch.setattr(module, "_local_enabled", lambda: False)
    monkeypatch.setattr(module, "_cloud_fallback_enabled", lambda: True)

    class _Task:
        pass

    _Task.delay = staticmethod(delay)
    fake = ModuleType("internal.task.render_tasks")
    fake.render_composition_task = _Task()
    monkeypatch.setitem(sys.modules, "internal.task.render_tasks", fake)

    calls = {"admitted": [], "released": [], "enqueued": 0}

    class _Admission:
        allowed = admission_allowed
        reason = admission_reason
        existing_task_id = ""

    class _Guard:
        def admit(self, *, account_id, fingerprint):
            calls["admitted"].append((account_id, fingerprint))
            return _Admission()

        def release(self, *, account_id, fingerprint=""):
            calls["released"].append((account_id, fingerprint))

        def mark_enqueued(self):
            calls["enqueued"] += 1

    monkeypatch.setattr(module, "_load_render_guard", lambda: _Guard())
    return module, calls


def test_dispatch_prefers_celery(monkeypatch):
    """Celery 可用时必须走后台渲染，不能同步阻塞对话请求。"""
    dispatched = {}

    def _delay(composition, account_id, name, **kwargs):
        dispatched["args"] = (composition, account_id, name)
        dispatched["context"] = kwargs
        return __import__("types").SimpleNamespace(id="task-1")

    module, calls = _install_fakes(monkeypatch, delay=_delay)

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
    # 通过闸门后必须登记队列计数
    assert calls["enqueued"] == 1


def test_dispatch_passes_chat_context_to_celery(monkeypatch):
    """会话上下文必须透传到任务：否则云端渲染完成后无法回填到原消息。"""
    dispatched = {}

    def _delay(composition, account_id, name, **kwargs):
        dispatched["context"] = kwargs
        return __import__("types").SimpleNamespace(id="task-1")

    module, _calls = _install_fakes(monkeypatch, delay=_delay)
    tool = render_video(
        account_id="11111111-1111-1111-1111-111111111111",
        message_id="msg-1",
        conversation_id="conv-1",
    )
    composition = {
        "composition_id": "main",
        "duration": 1.0,
        "segments": [{"start": 0, "duration": 1, "text": "x"}],
    }

    json.loads(tool._run(composition=composition, name="片"))

    assert dispatched["context"]["message_id"] == "msg-1"
    assert dispatched["context"]["conversation_id"] == "conv-1"


def test_factory_passes_chat_context_onto_tool():
    """工厂漏传则任务永远拿不到 message_id，回填静默失效（无任何报错）。"""
    tool = render_video(
        account_id="11111111-1111-1111-1111-111111111111",
        message_id="msg-1",
        conversation_id="conv-1",
    )

    assert tool.message_id == "msg-1"
    assert tool.conversation_id == "conv-1"


def test_dispatch_does_not_fall_back_to_sync_when_celery_unavailable(monkeypatch):
    """派发失败必须直接报错，不得回退同步——同步渲染会吃爆 4C4G 内存并挂住对话。"""

    def _boom(*args, **kwargs):
        raise RuntimeError("broker down")

    module, calls = _install_fakes(monkeypatch, delay=_boom)

    tool = render_video(account_id="11111111-1111-1111-1111-111111111111")
    composition = {
        "composition_id": "main",
        "duration": 1.0,
        "segments": [{"start": 0, "duration": 1, "text": "x"}],
    }
    payload = json.loads(tool._run(composition=composition, name="片"))

    assert payload["ok"] is False
    assert "渲染" in payload["error"]
    # 派发失败必须归还占用的槽位与防重锁，避免额度泄漏
    assert calls["released"], "派发失败必须释放闸门资源"


def test_dispatch_rejects_when_guard_denies(monkeypatch):
    """闸门拒绝（并发/重复/积压）时返回可读提示，且不派发任务。"""
    dispatched = {"called": False}

    def _delay(*args, **kwargs):
        dispatched["called"] = True
        return None

    module, _calls = _install_fakes(
        monkeypatch, delay=_delay, admission_allowed=False,
        admission_reason="你已有渲染任务正在进行，请等它完成后再试",
    )

    tool = render_video(account_id="11111111-1111-1111-1111-111111111111")
    composition = {
        "composition_id": "main",
        "duration": 1.0,
        "segments": [{"start": 0, "duration": 1, "text": "x"}],
    }
    payload = json.loads(tool._run(composition=composition, name="片"))

    assert payload["ok"] is False
    assert "正在进行" in payload["error"]
    assert dispatched["called"] is False, "被拒绝时不得派发任务"


def test_prefers_local_device_over_cloud(monkeypatch):
    """本机可用时不应派发 Celery——这是成本外部化的核心断言。"""
    module = _render_video_module()

    monkeypatch.setattr(module, "_local_enabled", lambda: True)
    monkeypatch.setattr(module, "_cloud_fallback_enabled", lambda: True)
    monkeypatch.setattr(
        module,
        "_run_local_render",
        lambda **kwargs: {"ok": True, "path": "/tmp/x.mp4", "size_bytes": 1},
    )

    def cloud_should_not_run(**kwargs):
        raise AssertionError("本机可用时不应派发云端 Celery")

    monkeypatch.setattr(module, "_dispatch_cloud_render", cloud_should_not_run)

    result = module._dispatch_render({"segments": [{"start": 0, "duration": 1, "text": "a"}]}, "acc-1", "demo")
    assert result["mode"] == "local"


def test_falls_back_to_cloud_when_local_unavailable(monkeypatch):
    module = _render_video_module()

    monkeypatch.setattr(module, "_cloud_fallback_enabled", lambda: True)
    monkeypatch.setattr(
        module,
        "_run_local_render",
        lambda **kwargs: {"ok": False, "unavailable": True, "error": "无设备"},
    )
    monkeypatch.setattr(
        module,
        "_dispatch_cloud_render",
        lambda **kwargs: {"mode": "celery", "result": type("R", (), {"id": "t1"})()},
    )

    result = module._dispatch_render({"segments": [{"start": 0, "duration": 1, "text": "a"}]}, "acc-1", "demo")
    assert result["mode"] == "celery"


def test_local_business_failure_does_not_fall_back(monkeypatch):
    """本机渲染业务失败（非通道问题）应直接报错，不静默回退云端。"""
    import pytest

    module = _render_video_module()

    monkeypatch.setattr(module, "_cloud_fallback_enabled", lambda: True)
    monkeypatch.setattr(
        module,
        "_run_local_render",
        lambda **kwargs: {"ok": False, "error": "渲染环境缺少必需配置"},
    )

    def cloud_should_not_run(**kwargs):
        raise AssertionError("业务失败不应回退云端")

    monkeypatch.setattr(module, "_dispatch_cloud_render", cloud_should_not_run)

    with pytest.raises(module.RenderExecutionError):
        module._dispatch_render(
            {"segments": [{"start": 0, "duration": 1, "text": "a"}]}, "acc-1", "demo"
        )


def test_local_disabled_goes_straight_to_cloud(monkeypatch):
    module = _render_video_module()

    monkeypatch.setattr(module, "_local_enabled", lambda: False)
    monkeypatch.setattr(module, "_cloud_fallback_enabled", lambda: True)
    monkeypatch.setattr(
        module,
        "_dispatch_cloud_render",
        lambda **kwargs: {"mode": "celery", "result": type("R", (), {"id": "t1"})()},
    )

    result = module._dispatch_render({"segments": [{"start": 0, "duration": 1, "text": "a"}]}, "acc-1", "demo")
    assert result["mode"] == "celery"


def test_cloud_disabled_and_no_device_raises_clear_error(monkeypatch):
    import pytest

    module = _render_video_module()

    monkeypatch.setattr(module, "_local_enabled", lambda: True)
    monkeypatch.setattr(module, "_cloud_fallback_enabled", lambda: False)
    monkeypatch.setattr(
        module,
        "_run_local_render",
        lambda **kwargs: {"ok": False, "unavailable": True, "error": "无设备"},
    )

    with pytest.raises(module.RenderExecutionError) as exc:
        module._dispatch_render(
            {"segments": [{"start": 0, "duration": 1, "text": "a"}]}, "acc-1", "demo"
        )
    assert "桌面端" in str(exc.value) or "本机" in str(exc.value)
