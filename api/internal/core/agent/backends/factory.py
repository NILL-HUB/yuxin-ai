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
    BACKEND_TENCENT_SCF,
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


class RemoteExecHandle:
    """远端执行句柄的**公共协议**：`execute(payload, timeout=None) -> Any`。

    为什么抽出来：两种传输（HTTP POST / 云厂商 SDK 直调）对消费方而言语义相同
    ——「把代码与入参发出去、拿回一次结果」，都没有 shell / 文件系统语义。
    消费方只认本协议（`isinstance(handle, RemoteExecHandle)`），传输差异
    各自收敛在实现内部（超时、鉴权、body 解包）。

    注意：本协议**不是** `BaseSandbox`（E2B）。E2B 是有状态沙箱实例
    （`execute(command)` / `upload_files` / `download_files`），语义不同。
    """

    def execute(self, payload: dict[str, Any], *, timeout: int | None = None) -> Any:
        """向远端发起一次执行请求，返回解析后的 JSON。"""
        raise NotImplementedError


@dataclass(frozen=True)
class HttpSandboxHandle(RemoteExecHandle):
    """HTTP 远端执行句柄 —— **HTTP 后端的唯一传输入口**。

    与 `BaseSandbox`（E2B）的本质差异（重要）：

    - E2B 后端有 **shell + 文件系统** 语义（`execute(command)` / `upload_files` /
      `download_files`），是一个**有状态沙箱实例**；
    - HTTP 后端**没有**这些语义，`execute(payload)` = 向 endpoint 发**一次**请求、
      拿回结果（无状态）。请求体由各消费方按自己的 action 约定构造。

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


# 腾讯云 SDK 直调：区域/命名空间/版本别名等技术参数走 configs，
# 密钥走 credentials（service 层解密后注入），core 不读 env。
_TENCENT_DEFAULT_REGION = "ap-guangzhou"
_TENCENT_DEFAULT_NAMESPACE = "default"
_TENCENT_DEFAULT_QUALIFIER = "$LATEST"

# 这些凭证键名同时是环境变量名（`SandboxConfigService.resolve_credentials` 的 env 兜底约定）
_TENCENT_SECRET_ID_KEY = "TENCENTCLOUD_SECRET_ID"
_TENCENT_SECRET_KEY_KEY = "TENCENTCLOUD_SECRET_KEY"
_TENCENT_SANDBOX_TOKEN_KEY = "SANDBOX_TOKEN"


@dataclass(frozen=True)
class TencentScfHandle(RemoteExecHandle):
    """腾讯云函数 SDK 直调句柄（`InvokeFunction` 同步调用）。

    为什么走 SDK 而不是 HTTP 端点：腾讯云 **API 网关已停止售卖**、
    SCF 亦无「函数 URL」公开接口，函数无法开公网 HTTP 入口。
    IAM 签名直调反而更优——函数零公网暴露面，鉴权由腾讯云签名承担，
    无需在公网挂一个免鉴权端点再用共享 token 兜底。

    与 `HttpSandboxHandle` 的契约对齐：`execute(payload)` 收一份 JSON、
    返回一份 JSON（同样做云函数 `statusCode`/`body` 包裹解包），
    消费方（`SkillScfClient` / `CodeNode`）无需感知传输差异。

    安全：密钥由 service 层加密入库、运行时解密注入（本对象不落库、不回显）。
    函数侧仍保留 `SANDBOX_TOKEN` 校验作为纵深防御（即使有人给函数挂了
    公网触发器，无 token 亦不可用）；token 缺省时由本句柄注入。
    """

    secret_id: str
    secret_key: str
    function_name: str
    region: str = _TENCENT_DEFAULT_REGION
    namespace: str = _TENCENT_DEFAULT_NAMESPACE
    qualifier: str = _TENCENT_DEFAULT_QUALIFIER
    sandbox_token: str = ""
    timeout_seconds: int = _HTTP_DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        for field_name in ("secret_id", "secret_key", "function_name", "region", "namespace", "qualifier", "sandbox_token"):
            object.__setattr__(self, field_name, str(getattr(self, field_name) or "").strip())
        object.__setattr__(
            self, "region", self.region or _TENCENT_DEFAULT_REGION
        )
        object.__setattr__(
            self, "namespace", self.namespace or _TENCENT_DEFAULT_NAMESPACE
        )
        object.__setattr__(
            self, "qualifier", self.qualifier or _TENCENT_DEFAULT_QUALIFIER
        )
        object.__setattr__(
            self, "timeout_seconds", _normalize_timeout(self.timeout_seconds, _HTTP_DEFAULT_TIMEOUT)
        )

    @property
    def id(self) -> str:
        """句柄标识（仅用于日志；不是远端函数实例 id）。"""
        return f"tencent-scf:{self.region}/{self.namespace}/{self.function_name}"

    def execute(self, payload: dict[str, Any], *, timeout: int | None = None) -> Any:
        """同步调用云函数并返回解析后的 JSON（已做 `body` 解包）。

        Args:
            payload: 函数入参（JSON 可序列化），对应函数 `event`。
            timeout: 本次超时（秒）；None 时用句柄默认值。

        Raises:
            FailException: 凭证/函数名缺失、SDK 调用失败、函数返回错误、响应非 JSON。
        """
        if not (self.secret_id and self.secret_key):
            raise FailException("腾讯云函数沙箱未配置：缺少 SecretId / SecretKey")
        if not self.function_name:
            raise FailException("腾讯云函数沙箱未配置：缺少函数名")

        # 延迟导入：SDK 体积不小，且 core 进程（如无沙箱调用的 API/Celery worker）
        # 未安装 SDK 时不应在模块导入期直接崩溃。
        try:
            from tencentcloud.common import credential
            from tencentcloud.common.profile.client_profile import ClientProfile
            from tencentcloud.common.profile.http_profile import HttpProfile
            from tencentcloud.scf.v20180416 import models, scf_client
        except ImportError as exc:  # noqa: BLE001
            raise FailException(f"腾讯云 SDK 未安装：{exc}")

        effective_timeout = _normalize_timeout(timeout, self.timeout_seconds)
        event = dict(payload or {})
        if self.sandbox_token and not event.get("token"):
            event["token"] = self.sandbox_token

        http_profile = HttpProfile()
        http_profile.endpoint = "scf.tencentcloudapi.com"
        http_profile.reqTimeout = effective_timeout
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        client = scf_client.ScfClient(
            credential.Credential(self.secret_id, self.secret_key),
            self.region,
            client_profile,
        )

        request = models.InvokeFunctionRequest()
        request.from_json_string(
            json.dumps(
                {
                    "FunctionName": self.function_name,
                    "Namespace": self.namespace,
                    "Qualifier": self.qualifier,
                    "Event": json.dumps(event, ensure_ascii=False, default=str),
                }
            )
        )

        try:
            response = client.InvokeFunction(request)
        except Exception as exc:  # noqa: BLE001
            raise FailException(f"腾讯云函数调用失败: {str(exc)[:500]}")

        result = getattr(response, "Result", None)
        if result is None:
            raise FailException("腾讯云函数返回为空")
        error_message = str(getattr(result, "ErrMsg", "") or "").strip()
        if error_message:
            raise FailException(f"腾讯云函数执行出错: {error_message}")

        ret_message = str(getattr(result, "RetMsg", "") or "").strip()
        if not ret_message:
            raise FailException("腾讯云函数返回为空（RetMsg 为空）")
        try:
            return _unwrap_scf_body(json.loads(ret_message))
        except Exception as exc:  # noqa: BLE001
            raise FailException(f"腾讯云函数返回非JSON内容: {str(exc)}，原文: {ret_message[:500]}")


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


def _build_tencent_scf(runtime: SandboxRuntime) -> Any | None:
    """构造腾讯云函数 SDK 直调句柄（密钥/函数名/区域均来自该能力域的运行时快照）。"""
    if not runtime.enabled:
        logger.info(
            "腾讯云函数沙箱未启用: capability=%s backend=%s reason=%s",
            runtime.capability,
            runtime.backend,
            runtime.reason,
        )
        return None
    function_name = str(runtime.get("function_name") or "").strip()
    if not function_name:
        return None
    return TencentScfHandle(
        secret_id=runtime.get_credential(_TENCENT_SECRET_ID_KEY),
        secret_key=runtime.get_credential(_TENCENT_SECRET_KEY_KEY),
        function_name=function_name,
        region=str(runtime.get("region") or _TENCENT_DEFAULT_REGION).strip(),
        namespace=str(runtime.get("namespace") or _TENCENT_DEFAULT_NAMESPACE).strip(),
        qualifier=str(runtime.get("qualifier") or _TENCENT_DEFAULT_QUALIFIER).strip(),
        sandbox_token=runtime.get_credential(_TENCENT_SANDBOX_TOKEN_KEY),
        timeout_seconds=runtime.get_int("timeout_seconds", _HTTP_DEFAULT_TIMEOUT),
    )


def _build_disabled(_runtime: SandboxRuntime) -> None:
    """显式未开通：返回 None，调用方须走「未开通」分支（禁止静默降级）。"""
    return None


_REGISTRY: dict[str, SandboxBuilder] = {
    BACKEND_BAIDU_CFC: _build_e2b_protocol,
    BACKEND_E2B_CLOUD: _build_e2b_protocol,
    BACKEND_HTTP_SANDBOX: _build_http_sandbox,
    BACKEND_TENCENT_SCF: _build_tencent_scf,
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
        - 远端执行（HTTP / 腾讯云 SDK 直调）：`RemoteExecHandle` 子类实例
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
