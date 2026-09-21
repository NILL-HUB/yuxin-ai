"""fetch_media 运行时门控挂载单测（KB-P6 Task 6）。

真实挂载点位于 `assistant_agent_service._build_assistant_runtime_tools`：当
ENABLE_MEDIA_FETCH_TOOL 开启时，依 `_enabled()` 调 `builtin_provider_manager.get_tool`
取工厂并注入 fetch_media 工具。

本仓 `api/tests/` 没有构造 AssistantAgentService 的既有测试范式（其 __init__ 依赖
大量服务且无现成 mock 手法可复刻），故不在本单测里硬造服务实例测真实挂载；
改用对门控真源 `_enabled()` 的行为断言 + 接线自检（Select-String 逐项核对六处、
celery 两处、service 委托、metadata 写读对）覆盖真实挂载可运行性。
"""
from internal.core.tools.builtin_tools.providers.media_fetch_tools.fetch_media import _enabled


def test_media_fetch_enabled_flag_behavior(monkeypatch):
    # ENABLE=1 时门控开启
    monkeypatch.setenv("ENABLE_MEDIA_FETCH_TOOL", "1")
    assert _enabled() is True
    # 未设置时门控关闭（默认不挂载）
    monkeypatch.delenv("ENABLE_MEDIA_FETCH_TOOL")
    assert _enabled() is False


def test_enabled_accepts_true_variants(monkeypatch):
    for token in ("true", "yes", "on"):
        monkeypatch.setenv("ENABLE_MEDIA_FETCH_TOOL", token)
        assert _enabled() is True


def test_enabled_rejects_falsy_values(monkeypatch):
    for token in ("0", "off", "", "no"):
        monkeypatch.setenv("ENABLE_MEDIA_FETCH_TOOL", token)
        assert _enabled() is False