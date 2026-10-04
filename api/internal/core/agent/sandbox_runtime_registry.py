"""沙箱运行时注册表（core 层，进程内缓存 + TTL 加载）。

问题：`internal/core/**` 是框架无关层（无 injector、无 DB），但沙箱后端构造
发生在 core。配置又必须来自 admin（DB）。

解法：service 层在**每个执行进程的入口**注册一个加载器
（`register_sandbox_runtime_loader`），core 通过 `get_sandbox_runtime(capability)`
读取；缓存带 TTL（默认 10s），因此 admin 端"热切换"后各 worker 会在 TTL 内
自动生效，无需重启。

注册入口（新增执行进程必须补注册，否则沙箱恒为「未开通」并打 WARNING）：
- API/ASGI 进程：`app.http.app` 的 `run_startup_sync_initialization()`
- Celery worker：`app.http.celery_app._ensure_runtime()`

- 单一权威仍是 `SandboxConfigService.resolve_runtime()`（加载器内部调用它）
- core 侧不读 DB、不读 env —— 只读注册表
- 未注册加载器时返回 `disabled` 运行时（显式"未开通"，不静默降级）
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from internal.core.agent.entities.sandbox_runtime_entity import (
    BACKEND_DISABLED,
    SandboxRuntime,
)

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 10.0

_loader: Callable[[str], SandboxRuntime] | None = None
_cache: dict[str, tuple[float, SandboxRuntime]] = {}
_ttl_seconds: float = DEFAULT_TTL_SECONDS
# 已告警过的能力域：未注册时只告警一次，避免高频调用刷屏（重注册后重置）
_unregistered_warned: set[str] = set()


def register_sandbox_runtime_loader(
    loader: Callable[[str], SandboxRuntime],
    *,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
) -> None:
    """由 service 层在启动时注册运行时加载器（幂等，可重复注册以替换实现）。"""
    global _loader, _ttl_seconds
    _loader = loader
    _ttl_seconds = float(ttl_seconds) if ttl_seconds and ttl_seconds > 0 else DEFAULT_TTL_SECONDS
    _cache.clear()
    _unregistered_warned.clear()
    logger.info("已注册沙箱运行时加载器（TTL=%ss）", _ttl_seconds)


def invalidate_sandbox_runtime_cache() -> None:
    """清空缓存：admin 切换/保存沙箱配置后由 service 层调用，令本进程立即生效。"""
    _cache.clear()


def get_sandbox_runtime(capability: str) -> SandboxRuntime:
    """读取某能力域的沙箱运行时（带 TTL 缓存）。

    未注册加载器（如单测 / 脚本环境）时返回 `disabled`，调用方据此走
    「未开通」分支，而非静默降级。
    """
    if _loader is None:
        # 显式暴露「漏注册」：历史断链（Celery worker 未注册加载器）曾表现为
        # admin 保存/切换全部成功但运行时恒不可用，且无任何日志线索
        if capability not in _unregistered_warned:
            _unregistered_warned.add(capability)
            logger.warning(
                "沙箱运行时加载器未注册：capability=%s 按「未开通」处理。"
                "该进程入口需调用 register_sandbox_runtime_loader"
                "（API: app.http.app 启动初始化；Celery: celery_app._ensure_runtime）",
                capability,
            )
        return SandboxRuntime(
            capability=capability,
            backend=BACKEND_DISABLED,
            enabled=False,
            reason="沙箱运行时加载器未注册",
        )

    now = time.monotonic()
    cached = _cache.get(capability)
    if cached is not None and now - cached[0] < _ttl_seconds:
        return cached[1]

    try:
        runtime = _loader(capability)
    except Exception:
        logger.exception("解析沙箱运行时失败，按未开通处理: capability=%s", capability)
        runtime = SandboxRuntime(
            capability=capability,
            backend=BACKEND_DISABLED,
            enabled=False,
            reason="沙箱运行时解析失败",
        )

    _cache[capability] = (now, runtime)
    return runtime
