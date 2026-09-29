"""沙箱运行时注册表（core 层，进程内缓存 + TTL 加载）。

问题：`internal/core/**` 是框架无关层（无 injector、无 DB），但沙箱后端构造
发生在 core。配置又必须来自 admin（DB）。

解法：service 层在启动时**注册一个加载器**（`register_sandbox_runtime_loader`），
core 通过 `get_sandbox_runtime(capability)` 读取；缓存带 TTL（默认 10s），
因此 admin 端"热切换"后各 worker 会在 TTL 内自动生效，无需重启。

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
