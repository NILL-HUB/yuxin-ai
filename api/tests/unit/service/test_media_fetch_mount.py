"""fetch_media 运行时挂载单测（KB-P6 Task 6）。

挂载点位于 `assistant_agent_service._build_assistant_runtime_tools`，其决策逻辑抽为
模块级 `_build_media_fetch_tool`：按 admin 全局控制配置 `media_fetch` 开关（经
`GlobalControlConfigService.get_config("media_fetch")` 在挂载点读取）决定是否从
`builtin_provider_manager` 取工厂并注入 fetch_media 工具实例；未开启时连工厂都不查。

本仓 `api/tests/` 没有构造 AssistantAgentService 的既有测试范式（其 __init__ 依赖
大量服务且无现成 mock 手法可复刻），故对抽出的挂载决策函数做行为断言，覆盖唯一事实源
（feature_enabled 布尔）到工具注入（enabled=True）这一接线闭环。
"""
from internal.service.assistant_agent_service import _build_media_fetch_tool


def _fake_provider_manager(factory):
    class PM:
        def __init__(self):
            self.called = []

        def get_tool(self, provider, name):
            self.called.append((provider, name))
            return factory
    return PM()


def test_disabled_feature_not_mounted():
    pm = _fake_provider_manager(object())
    out = _build_media_fetch_tool(pm, feature_enabled=False, account_id="u1")
    assert out is None
    assert pm.called == []  # 未启用时连工厂都不查（不存在拿到工具的路径）


def test_enabled_mounts_tool_with_enabled_flag():
    captured = {}

    class FakeFactory:
        def __call__(self, **kwargs):
            captured["kwargs"] = kwargs
            return object()

    pm = _fake_provider_manager(FakeFactory())
    out = _build_media_fetch_tool(
        pm, feature_enabled=True,
        account_id="u1", message_id="m1", conversation_id="c1",
    )
    assert out is not None
    assert pm.called == [("media_fetch_tools", "fetch_media")]
    assert captured["kwargs"]["enabled"] is True
    assert captured["kwargs"]["account_id"] == "u1"
    assert captured["kwargs"]["message_id"] == "m1"
    assert captured["kwargs"]["conversation_id"] == "c1"


def test_enabled_but_missing_factory_returns_none():
    pm = _fake_provider_manager(None)
    out = _build_media_fetch_tool(pm, feature_enabled=True, account_id="u1")
    assert out is None
    assert pm.called == [("media_fetch_tools", "fetch_media")]