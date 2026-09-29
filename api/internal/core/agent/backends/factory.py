"""沙箱后端工厂与注册表（core 层）。

**接入新沙箱后端的唯一扩展点** —— 三步即可，无需改动任何消费方：

1. 在 `sandbox_runtime_entity.py` 的 `BACKENDS` 加一个后端名常量；
2. 在 `CAPABILITY_BACKENDS` 里把它挂到对应能力域；
3. 在本文件写一个 `builder(runtime) -> 句柄 | None` 并 `register_sandbox_backend(名字, builder)`。

约束（重要）：本模块属 `internal/core/**`，是**框架无关层**——
不得读 DB、不得读 env。所有配置来自传入的 `SandboxRuntime`
（由 `SandboxConfigService.resolve_runtime()` 解析，service 层注入）。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

import requests

from internal.core.agent.entities.sandbox_runtime_entity import (
    BACKEND_BAIDU_CFC,
    BACKEND_DISABLED,
    BACKEND_E2B_CLOUD,
    BACKEND_HTTP_SANDBOX,
    SandboxRuntime,
)
from internal.exception import FailException

logger = logging.getLogger(__name__)

SandboxBuilder = Callable[[SandboxRuntime], Any]

_HTTP_DEFAULT_TIMEOUT = 60


def _normalize_timeout(value: Any, default: int) -> int:
    """把超时规整为正整数；非正/非法回退默认值。"""
    try:
        normalized = int(value or 0)
    except (TypeError, ValueError):
        normalized = 0
    return normalized if normalized > 0 else default


def _unwrap_scf_body(data: Any) -> Any:
    """解开云函数网关的 `body` 包裹（HTTP 触发型返回 `{"body": "<json 串>"}`）。

    非包裹结构原样返回。这是 HTTP 后端的**公共协议细节**，收在传输层，
    避免各消费方各写一份。
    """
    if not isinstance(data, dict) or "body" not in data:
        return data
    body = data.get("body")
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except Exception:
            return data
        return parsed if isinstance(parsed, dict) else data
    if isinstance(body, dict):
        return body
    return data


@dataclass(frozen=True)
class HttpSandboxHandle:
    """HTTP 远端执行句柄 —— **HTTP 后端的唯一传输入口**。

    与 `BaseSandbox`（E2B）的本质差异（重要）：

    - E2B 后端有 **shell + 文件系统** 语义（`execute(command)` / `upload_files` /
      `download_files`），是一个**有状态沙箱实例**；
    - HTTP 后端**没有**这些语义，`execute(payload)` = 向 endpoint 发**一次**请求、
      拿回结果（无状态）。请求体由各消费方按自己的 action 约定构造。

    因此本类**不是** `BaseSandbox` 子类，也不提供 `upload_files` 等方法——
    强行对齐只会造出远端并不支持的假契约。

    消费方：`SkillScfClient`（`skill_exec`）、`CodeNode`（`workflow_code`）。
    """

    endpoint: str
    timeout_seconds: int = _HTTP_DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoint", str(self.endpoint or "").strip().rstrip("/"))
        object.__setattr__(
            self, "timeout_seconds", _normalize_timeout(self.timeout_seconds, _HTTP_DEFAULT_TIMEOUT)
        )

    @property
    def id(self) -> str:
        """句柄标识（仅用于日志；不是远端沙箱实例 id）。"""
        return f"http-sandbox:{self.endpoint}"

    def execute(self, payload: dict[str, Any], *, timeout: int | None = None) -> Any:
        """向远端执行服务发起一次请求，返回解析后的 JSON（已完成 `body` 解包）。

        统一在此收敛：endpoint 校验、超时、状态码、非 JSON、网络异常。
        **不**解释 `error` / `result`——那是各消费方的业务契约，不塞进传输层。

        Args:
            payload: 请求体（JSON 可序列化）。
            timeout: 本次超时（秒），None 时用句柄默认值。

        Raises:
            FailException: endpoint 为空 / 超时 / 网络失败 / 非 200 / 响应非 JSON。
        """
        if not self.endpoint:
            raise FailException("HTTP 沙箱未配置：endpoint 为空")

        effective_timeout = _normalize_timeout(timeout, self.timeout_seconds)
        try:
            response = requests.post(
                self.endpoint,
                json=payload,
                timeout=effective_timeout,
            )
        except requests.exceptions.Timeout:
            raise FailException("云函数执行超时")
        except requests.exceptions.RequestException as exc:
            raise FailException(f"网络请求失败: {str(exc)}")

        if response.status_code != 200:
            try:
                error_body = response.json()
            except Exception:
                error_body = {"raw_text": response.text}
            raise FailException(
                f"云函数执行失败，状态码: {response.status_code}，响应: {error_body}"
            )

        try:
            response_data = response.json()
        except Exception as exc:
            raise FailException(f"云函数返回非JSON内容: {str(exc)}，原文: {response.text}")

        return _unwrap_scf_body(response_data)


def _e2b_credentials(runtime: SandboxRuntime) -> tuple[str, str]:
    """E2B 协议后端的凭证来源。

    **密钥由 service 层解析后注入**（`SandboxConfigService.resolve_runtime`：
    DB 加密值解密优先 → env 兜底），core 不读 env、不读 DB。
    """
    return (
        str(runtime.get_credential("E2B_API_KEY")).strip(),
        str(runtime.get_credential("E2B_DOMAIN")).strip(),
    )


def _build_e2b_protocol(runtime: SandboxRuntime) -> Any | None:
    """构造 E2B 协议沙箱后端（百度 CFC 与官方 E2B 共用同一实现，差异仅在凭证/域名）。"""
    if not runtime.enabled:
        logger.info(
            "沙箱未启用，跳过后端构造: capability=%s backend=%s reason=%s",
            runtime.capability,
            runtime.backend,
            runtime.reason,
        )
        return None

    from internal.core.agent.backends.baidu_cfc_sandbox_backend import (
        BaiduCfcSandboxBackend,
    )

    api_key, domain = _e2b_credentials(runtime)
    if not api_key or not domain:
        # 正常情况下 runtime.enabled 已保证凭证齐备；此处是防御性兜底
        logger.warning("沙箱后端凭证缺失（capability=%s）", runtime.capability)
        return None

    return BaiduCfcSandboxBackend(
        api_key=api_key,
        domain=domain,
        template_alias=runtime.get("template_alias") or None,
        fallback_template_alias=runtime.get("fallback_template_alias") or None,
        timeout=runtime.get_int("execute_timeout_seconds", 600),
        sandbox_timeout=runtime.get_int("sandbox_timeout_seconds", 1800),
    )


def _build_http_sandbox(runtime: SandboxRuntime) -> Any | None:
    """构造 HTTP 远端执行句柄（endpoint 来自该能力域的配置，不再共用同一 env 变量）。"""
    if not runtime.enabled:
        logger.info(
            "HTTP 沙箱未启用: capability=%s backend=%s reason=%s",
            runtime.capability,
            runtime.backend,
            runtime.reason,
        )
        return None
    endpoint = str(runtime.get("endpoint") or "").strip()
    if not endpoint:
        return None
    return HttpSandboxHandle(
        endpoint=endpoint,
        timeout_seconds=runtime.get_int("timeout_seconds", 60),
    )


def _build_disabled(_runtime: SandboxRuntime) -> None:
    """显式未开通：返回 None，调用方须走「未开通」分支（禁止静默降级）。"""
    return None


_REGISTRY: dict[str, SandboxBuilder] = {
    BACKEND_BAIDU_CFC: _build_e2b_protocol,
    BACKEND_E2B_CLOUD: _build_e2b_protocol,
    BACKEND_HTTP_SANDBOX: _build_http_sandbox,
    BACKEND_DISABLED: _build_disabled,
}


def register_sandbox_backend(name: str, builder: SandboxBuilder) -> None:
    """注册沙箱后端构造器（接入新沙箱的唯一入口）。"""
    normalized = str(name or "").strip()
    if not normalized:
        raise ValueError("沙箱后端名不能为空")
    _REGISTRY[normalized] = builder
    logger.info("已注册沙箱后端: %s", normalized)


def available_backends() -> tuple[str, ...]:
    """已注册的后端名（供 Admin 展示/校验）。"""
    return tuple(_REGISTRY.keys())


def build_sandbox_backend(runtime: SandboxRuntime) -> Any | None:
    """按运行时快照构造后端句柄。

    Returns:
        - E2B 协议后端：`BaiduCfcSandboxBackend` 实例
        - HTTP 远端执行：`HttpSandboxHandle`
        - 未启用 / disabled：`None`

    Raises:
        ValueError: 后端名未注册（配置与代码不一致，属开发期错误，必须暴露）
    """
    builder = _REGISTRY.get(runtime.backend)
    if builder is None:
        raise ValueError(
            f"未注册的沙箱后端: {runtime.backend}（已注册: {'/'.join(_REGISTRY)}）"
        )
    return builder(runtime)
