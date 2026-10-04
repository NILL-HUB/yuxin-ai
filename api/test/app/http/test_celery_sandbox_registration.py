"""Celery 侧沙箱运行时加载器注册单测（历史断链回归）。

背景：`register_sandbox_runtime_loader` 曾只发生在 API 进程（`app.py` 启动初始化），
且与 `ensure_default_config` 一起被 `MODE != "celery"` 限定；Celery worker 从未注册，
`get_sandbox_runtime()` 恒返回「未开通」→ 定时任务/后台 Agent 里技能与代码执行全部失败，
admin 保存与切换看似成功却始终不生效（生产日志 2026-10-02/03 可复现）。

本测试锁定接线：`app.http.celery_app._register_sandbox_runtime_loader` 必须把
`SandboxConfigService.resolve_runtime` 注册进 core 注册表，且注册失败为 best-effort 不抛出。
"""
import pytest

from internal.core.agent import sandbox_runtime_registry as registry
from internal.core.agent.entities.sandbox_runtime_entity import (
    BACKEND_BAIDU_CFC,
    CAPABILITY_SKILL_EXEC,
    SandboxRuntime,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    saved_loader = registry._loader
    saved_cache = dict(registry._cache)
    saved_warned = set(registry._unregistered_warned)
    yield
    registry._loader = saved_loader
    registry._cache.clear()
    registry._cache.update(saved_cache)
    registry._unregistered_warned.clear()
    registry._unregistered_warned.update(saved_warned)


class _FakeService:
    def resolve_runtime(self, capability: str) -> SandboxRuntime:
        return SandboxRuntime(capability=capability, backend=BACKEND_BAIDU_CFC, enabled=True)


class _FakeInjector:
    def __init__(self, service):
        self._service = service

    def get(self, _cls):
        return self._service


def test_register_sandbox_runtime_loader_wires_service_into_registry():
    from app.http.celery_app import _register_sandbox_runtime_loader

    registry._loader = None
    registry._cache.clear()
    registry._unregistered_warned.clear()

    _register_sandbox_runtime_loader(_FakeInjector(_FakeService()))

    runtime = registry.get_sandbox_runtime(CAPABILITY_SKILL_EXEC)
    assert registry._loader is not None
    assert runtime.backend == BACKEND_BAIDU_CFC
    assert runtime.enabled is True


def test_register_sandbox_runtime_loader_is_best_effort_when_injector_fails(caplog):
    from app.http.celery_app import _register_sandbox_runtime_loader

    class _BrokenInjector:
        def get(self, _cls):
            raise RuntimeError("injector 不可用")

    registry._loader = None
    # 不抛出：注册失败只留日志，沙箱按「未开通」显式报错
    _register_sandbox_runtime_loader(_BrokenInjector())
    assert registry._loader is None
