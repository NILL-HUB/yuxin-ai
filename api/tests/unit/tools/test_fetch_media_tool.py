"""fetch_media 外部素材获取工具单测（KB-P6 Task 4）。"""
import json
from types import SimpleNamespace

from internal.core.tools.builtin_tools.providers.media_fetch_tools.fetch_media import (
    fetch_media, _enabled, FetchMediaTool,
)


def test_missing_url_or_kb_rejected():
    tool = FetchMediaTool(account_id="u1")
    out = json.loads(tool._run(url="", knowledge_base_id="kb1"))
    assert out["ok"] is False


def test_disabled_env_blocks():
    import os
    os.environ.pop("ENABLE_MEDIA_FETCH_TOOL", None)
    tool = FetchMediaTool(account_id="u1")
    out = json.loads(tool._run(url="https://youtu.be/x", knowledge_base_id="kb1"))
    assert out["ok"] is False  # 未开启时不派发
    assert b"KEY" in str(out["error"]).encode() or "admin" in out["error"].lower() or "enable" in out["error"].lower()


def test_dispatch_uses_kwargs(monkeypatch):
    # 注：`import ...media_fetch_tools.fetch_media as mod` 会因 __init__ 重导出同名工厂函数而绑定到函数，
    # 无法触达子模块；须经 sys.modules 取真实模块对象才能注入 _load_task。
    import sys
    import internal.core.tools.builtin_tools.providers.media_fetch_tools as pkg
    mod_name = f"{pkg.__name__}.fetch_media"
    assert sys.modules[mod_name] is not getattr(pkg, "fetch_media")
    mod = sys.modules[mod_name]
    captured = {}
    class FakeTask:
        @classmethod
        def delay(cls, *a, **kw):
            captured["args"] = a
            captured["kwargs"] = kw
            return SimpleNamespace(id="tid")
    monkeypatch.setattr(mod, "_load_task", lambda: FakeTask)
    monkeypatch.setenv("ENABLE_MEDIA_FETCH_TOOL", "1")
    tool = FetchMediaTool(account_id="u1", message_id="m1", conversation_id="c1")
    out = json.loads(tool._run(url="https://www.youtube.com/watch?v=x", knowledge_base_id="kb1", max_bytes=0))
    assert out["ok"] is True and out["dispatched"] is True
    # 位置参数顺序：url, knowledge_base_id, account_id
    assert captured["args"][0] == "https://www.youtube.com/watch?v=x"
    assert captured["args"][1] == "kb1"
    assert captured["args"][2] == "u1"
    # 会话上下文 kwarg 必须透传
    assert captured["kwargs"]["message_id"] == "m1"
    assert captured["kwargs"]["conversation_id"] == "c1"