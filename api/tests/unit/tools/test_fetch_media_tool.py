"""fetch_media 外部素材获取工具单测（KB-P6 Task 4）。

开关迁移后的行为：不再依赖环境变量 ENABLE_MEDIA_FETCH_TOOL。
启用与否由工具实例字段 `enabled` 决定，由挂载点在构造时注入
（`fetch_media(**kwargs)` 工厂传 `enabled=`），其单一事实源是
admin 公共 AI 配置的 `media_fetch` 开关。
"""
import json
from types import SimpleNamespace

from internal.core.tools.builtin_tools.providers.media_fetch_tools.fetch_media import (
    fetch_media, FetchMediaTool,
)


def test_missing_url_or_kb_rejected():
    tool = FetchMediaTool(account_id="u1")
    out = json.loads(tool._run(url="", knowledge_base_id="kb1"))
    assert out["ok"] is False


def test_disabled_instance_blocks():
    tool = FetchMediaTool(account_id="u1", enabled=False)
    out = json.loads(tool._run(url="https://youtu.be/x", knowledge_base_id="kb1"))
    assert out["ok"] is False  # 未开启时不派发
    # 错误文案指向 admin 公共 AI 配置，且不得残留环境变量名
    assert "公共 AI 配置" in out["error"]
    assert "ENABLE_MEDIA_FETCH_TOOL" not in out["error"]


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
    tool = FetchMediaTool(account_id="u1", message_id="m1", conversation_id="c1", enabled=True)
    out = json.loads(tool._run(url="https://www.youtube.com/watch?v=x", knowledge_base_id="kb1", max_bytes=0))
    assert out["ok"] is True and out["dispatched"] is True
    # 位置参数顺序：url, knowledge_base_id, account_id
    assert captured["args"][0] == "https://www.youtube.com/watch?v=x"
    assert captured["args"][1] == "kb1"
    assert captured["args"][2] == "u1"
    # 会话上下文 kwarg 必须透传
    assert captured["kwargs"]["message_id"] == "m1"
    assert captured["kwargs"]["conversation_id"] == "c1"


def test_factory_passes_enabled_flag():
    # 工厂从 kwargs 注入 enabled（挂载点把 GlobalControlConfigService media_fetch 开关结果传进来）
    assert fetch_media(enabled=True).enabled is True
    assert fetch_media(enabled=False).enabled is False
    assert fetch_media().enabled is True  # 未显式传入时默认开启