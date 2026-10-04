"""沙箱运行时注册表单测：进程内注册、TTL 缓存与「漏注册」可观测性。

覆盖接线：`register_sandbox_runtime_loader` → `get_sandbox_runtime`（core 侧唯一读取入口）。
回归要点（历史断链）：Celery worker 曾漏注册加载器，运行时恒返回「未开通」且无任何日志线索；
本测试锁定：未注册时必须显式返回 disabled、带原因、并留下**一次** WARNING。
"""
import logging

import pytest

from internal.core.agent import sandbox_runtime_registry as registry
from internal.core.agent.entities.sandbox_runtime_entity import (
    BACKEND_BAIDU_CFC,
    BACKEND_DISABLED,
    CAPABILITY_CODE_INTERPRETER,
    CAPABILITY_SKILL_EXEC,
    SandboxRuntime,
)


@pytest.fixture(autouse=True)
def _restore_registry_state():
    """隔离全局注册表状态（loader / TTL / 缓存 / 告警记录）。"""
    saved_loader = registry._loader
    saved_ttl = registry._ttl_seconds
    saved_cache = dict(registry._cache)
    saved_warned = set(registry._unregistered_warned)
    yield
    registry._loader = saved_loader
    registry._ttl_seconds = saved_ttl
    registry._cache.clear()
    registry._cache.update(saved_cache)
    registry._unregistered_warned.clear()
    registry._unregistered_warned.update(saved_warned)


def _reset_registry() -> None:
    registry._loader = None
    registry._cache.clear()
    registry._unregistered_warned.clear()


def test_unregistered_loader_returns_disabled_with_reason_and_warns(caplog):
    _reset_registry()
    with caplog.at_level(logging.WARNING, logger=registry.__name__):
        runtime = registry.get_sandbox_runtime(CAPABILITY_SKILL_EXEC)

    assert runtime.backend == BACKEND_DISABLED
    assert runtime.enabled is False
    assert runtime.reason == "沙箱运行时加载器未注册"
    messages = [record.getMessage() for record in caplog.records]
    assert any("未注册" in message for message in messages)


def test_unregistered_warning_is_emitted_once_per_capability(caplog):
    _reset_registry()
    with caplog.at_level(logging.WARNING, logger=registry.__name__):
        registry.get_sandbox_runtime(CAPABILITY_SKILL_EXEC)
        registry.get_sandbox_runtime(CAPABILITY_SKILL_EXEC)

    assert len(caplog.records) == 1


def test_registered_loader_result_used_and_cached_within_ttl():
    _reset_registry()
    calls: list[str] = []

    def _loader(capability: str) -> SandboxRuntime:
        calls.append(capability)
        return SandboxRuntime(capability=capability, backend=BACKEND_BAIDU_CFC, enabled=True)

    registry.register_sandbox_runtime_loader(_loader)
    first = registry.get_sandbox_runtime(CAPABILITY_CODE_INTERPRETER)
    second = registry.get_sandbox_runtime(CAPABILITY_CODE_INTERPRETER)

    assert first.backend == BACKEND_BAIDU_CFC
    assert first.enabled is True
    assert second is first
    assert calls == [CAPABILITY_CODE_INTERPRETER], "TTL 内应只解析一次"


def test_invalidate_forces_reload():
    _reset_registry()
    calls: list[str] = []

    def _loader(capability: str) -> SandboxRuntime:
        calls.append(capability)
        return SandboxRuntime(capability=capability, backend=BACKEND_BAIDU_CFC, enabled=True)

    registry.register_sandbox_runtime_loader(_loader)
    registry.get_sandbox_runtime(CAPABILITY_CODE_INTERPRETER)
    registry.invalidate_sandbox_runtime_cache()
    registry.get_sandbox_runtime(CAPABILITY_CODE_INTERPRETER)

    assert len(calls) == 2, "缓存失效后应重新解析"


def test_reregistration_resets_warning_state():
    _reset_registry()
    registry.get_sandbox_runtime(CAPABILITY_SKILL_EXEC)  # 触发一次「未注册」告警
    registry.register_sandbox_runtime_loader(
        lambda capability: SandboxRuntime(capability=capability, backend=BACKEND_DISABLED)
    )
    assert registry._unregistered_warned == set(), "重新注册后应重置告警去重状态"
