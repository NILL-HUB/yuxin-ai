"""沙箱配置服务（**沙箱配置的唯一权威入口**）。

对标 `StorageConfigService`：把沙箱从「14 处散读 env」收敛为「admin 可配 +
多后端热切换」。设计要点：

- 配置入库 `sandbox_config`（按能力域分组，同域内单 active），**密钥不入库、走 env**
- 运行时唯一读取入口 `resolve_runtime(capability)` 返回纯数据 `SandboxRuntime`，
  由 service 层注入 core（core 不读 DB / 不读 env）
- 无 DB 记录时回退 env 判定，保证升级瞬间**行为零变化**
- `ensure_default_config()` 启动幂等补齐（挂在 app.py 的 ensure_* 序列里）
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from injector import inject
from sqlalchemy import true

from internal.core.agent.backends.endpoint_utils import is_placeholder_endpoint
from internal.core.agent.entities.sandbox_runtime_entity import (
    BACKEND_ALIYUN_SANDBOX,
    BACKEND_BAIDU_CFC,
    BACKEND_DISABLED,
    BACKEND_E2B_CLOUD,
    BACKEND_HTTP_SANDBOX,
    BACKEND_TENCENT_SCF,
    BACKENDS,
    CAPABILITY_BACKENDS,
    CAPABILITY_CODE_INTERPRETER,
    CAPABILITY_SKILL_EXEC,
    CAPABILITY_WORKFLOW_CODE,
    CAPABILITIES,
    SandboxRuntime,
)
from internal.core.agent.sandbox_runtime_registry import invalidate_sandbox_runtime_cache
from internal.exception import ValidateErrorException
from internal.model import SandboxConfig
from internal.service.tool_credential_encryptor import (
    decrypt_env,
    encrypt_env,
    is_encrypted,
    is_placeholder_secret,
    mask_env,
)
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

SUPPORTED_CAPABILITIES = CAPABILITIES
SUPPORTED_BACKENDS = BACKENDS

# 各后端允许持久化的配置键（其余键不入库，避免密钥泄露；与 storage 同口径）
_ALLOWED_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    BACKEND_BAIDU_CFC: (
        "template_alias",
        "fallback_template_alias",
        "profile",
        "execute_timeout_seconds",
        "sandbox_timeout_seconds",
        "allow_local_exec",
    ),
    BACKEND_E2B_CLOUD: (
        "template_alias",
        "execute_timeout_seconds",
        "sandbox_timeout_seconds",
    ),
    BACKEND_ALIYUN_SANDBOX: (
        "template_alias",
        "fallback_template_alias",
        "execute_timeout_seconds",
        "sandbox_timeout_seconds",
    ),
    BACKEND_HTTP_SANDBOX: ("endpoint", "timeout_seconds", "allow_local_exec"),
    BACKEND_TENCENT_SCF: (
        "function_name",
        "region",
        "namespace",
        "qualifier",
        "timeout_seconds",
        "allow_local_exec",
    ),
    BACKEND_DISABLED: (),
}

# 各后端允许持久化的**凭证键**（键=env 名，便于 env 兜底与消费方零改动）。
# 值经 `tool_credential_encryptor` 加密入库（与工具凭证/模型 Key 同口径）；读写接口只回掩码。
_ALLOWED_CREDENTIAL_KEYS: dict[str, tuple[str, ...]] = {
    # 百度 CFC 与官方 E2B 同走 E2B 协议，凭证相同（差异仅在域名取值）
    BACKEND_BAIDU_CFC: ("E2B_API_KEY", "E2B_DOMAIN"),
    BACKEND_E2B_CLOUD: ("E2B_API_KEY", "E2B_DOMAIN"),
    # 阿里云智能体沙箱：API Key 为 e2b_ 前缀（AgentBay 控制台/OpenAPI 创建），域名为 cn-<region>.sandbox.aliyuncs.com
    BACKEND_ALIYUN_SANDBOX: ("E2B_API_KEY", "E2B_DOMAIN"),
    BACKEND_HTTP_SANDBOX: (),
    # 腾讯云 SDK 直调：IAM 长期密钥 + 函数侧共享 token（纵深防御，函数已 fail-closed 校验）
    BACKEND_TENCENT_SCF: ("TENCENTCLOUD_SECRET_ID", "TENCENTCLOUD_SECRET_KEY", "SANDBOX_TOKEN"),
    BACKEND_DISABLED: (),
}

# 后端展示名（Admin 界面兜底；前端亦可覆盖）
_BACKEND_LABELS: dict[str, str] = {
    BACKEND_BAIDU_CFC: "百度 CFC 沙箱（E2B 协议）",
    BACKEND_E2B_CLOUD: "E2B 云沙箱",
    BACKEND_ALIYUN_SANDBOX: "阿里云智能体沙箱（AgentBay）",
    BACKEND_HTTP_SANDBOX: "HTTP 远端执行服务",
    BACKEND_TENCENT_SCF: "腾讯云函数（SDK 直调）",
    BACKEND_DISABLED: "未开通",
}

# 各能力域 × 后端的默认配置（迁移自 SandboxPolicy 的硬编码默认值）
_DEFAULT_CONFIGS: dict[tuple[str, str], dict] = {
    (CAPABILITY_CODE_INTERPRETER, BACKEND_BAIDU_CFC): {
        "profile": "lite",
        "template_alias": "llmops-code-interpreter-lite",
        "fallback_template_alias": "code-interpreter-v1",
        "execute_timeout_seconds": 3600,
        "sandbox_timeout_seconds": 86400,
    },
    (CAPABILITY_CODE_INTERPRETER, BACKEND_E2B_CLOUD): {
        "template_alias": "code-interpreter-v1",
        "execute_timeout_seconds": 3600,
        "sandbox_timeout_seconds": 86400,
    },
    (CAPABILITY_CODE_INTERPRETER, BACKEND_ALIYUN_SANDBOX): {
        "template_alias": "base",
        "execute_timeout_seconds": 3600,
        "sandbox_timeout_seconds": 86400,
    },
    (CAPABILITY_SKILL_EXEC, BACKEND_ALIYUN_SANDBOX): {
        "template_alias": "base",
        "execute_timeout_seconds": 60,
        "sandbox_timeout_seconds": 300,
        "allow_local_exec": False,
    },
    (CAPABILITY_SKILL_EXEC, BACKEND_HTTP_SANDBOX): {
        "timeout_seconds": 60,
        "allow_local_exec": False,
    },
    (CAPABILITY_SKILL_EXEC, BACKEND_BAIDU_CFC): {
        "execute_timeout_seconds": 60,
        "sandbox_timeout_seconds": 300,
        "allow_local_exec": False,
    },
    (CAPABILITY_SKILL_EXEC, BACKEND_TENCENT_SCF): {
        "region": "ap-guangzhou",
        "namespace": "default",
        "qualifier": "$LATEST",
        "timeout_seconds": 60,
        "allow_local_exec": False,
    },
    (CAPABILITY_WORKFLOW_CODE, BACKEND_HTTP_SANDBOX): {"timeout_seconds": 60},
    (CAPABILITY_WORKFLOW_CODE, BACKEND_TENCENT_SCF): {
        "region": "ap-guangzhou",
        "namespace": "default",
        "qualifier": "$LATEST",
        "timeout_seconds": 60,
    },
}

# 历史保护下限：深思考代码沙箱的超时曾被 `read_positive_int_env(..., minimum=default)`
# 抬升到默认值；迁移到配置中心后保留该下限，避免误配过小值导致任务早夭。
_TIMEOUT_FLOORS: dict[str, dict[str, int]] = {
    CAPABILITY_CODE_INTERPRETER: {
        "execute_timeout_seconds": 3600,
        "sandbox_timeout_seconds": 86400,
    },
}

# 缺凭据时的人类可读原因（如实展示，禁止静默降级）
_REASON_E2B_MISSING = "E2B_API_KEY / E2B_DOMAIN 未配置"
_REASON_ENDPOINT_MISSING = "远端 endpoint 未配置或为占位符"
_REASON_TENCENT_MISSING = "腾讯云 SecretId / SecretKey 或函数名未配置"
_REASON_DISABLED = "该能力域已显式关闭（未开通）"


def _sanitize_configs(backend: str, configs: dict | None) -> dict:
    """仅保留后端允许的配置键，剔除密钥类字段。"""
    if not isinstance(configs, dict):
        return {}
    allowed = _ALLOWED_CONFIG_KEYS.get(backend, ())
    return {k: v for k, v in configs.items() if k in allowed}


@inject
@dataclass
class SandboxConfigService:
    """沙箱配置服务。"""

    db: SQLAlchemy

    # ------------------------------------------------------------------ #
    #  查询
    # ------------------------------------------------------------------ #
    def get_active_backend(self, capability: str) -> str:
        """获取某能力域当前激活的后端。

        优先级：`sandbox_config.is_active` → env 推断 → `disabled`。
        若库内记录的后端不在该能力域允许集合内，视为无效并回退 env 推断。
        """
        capability = self._validate_capability(capability)
        active = (
            self.db.session.query(SandboxConfig)
            .filter(SandboxConfig.capability == capability)
            .filter(SandboxConfig.is_active == true())
            .order_by(SandboxConfig.updated_at.desc())
            .first()
        )
        allowed = CAPABILITY_BACKENDS.get(capability, ())
        if active is not None and active.backend in allowed:
            return active.backend
        fallback = self._infer_backend_from_env(capability)
        return fallback if fallback in allowed else BACKEND_DISABLED

    def list_configs(self, capability: str | None = None) -> list[SandboxConfig]:
        """列出配置（可按能力域过滤）。"""
        query = self.db.session.query(SandboxConfig)
        if capability:
            query = query.filter(SandboxConfig.capability == self._validate_capability(capability))
        return query.order_by(
            SandboxConfig.capability.asc(), SandboxConfig.created_at.asc()
        ).all()

    def get_config(self, capability: str, backend: str) -> SandboxConfig | None:
        """按（能力域, 后端）获取配置记录。"""
        return (
            self.db.session.query(SandboxConfig)
            .filter(SandboxConfig.capability == capability)
            .filter(SandboxConfig.backend == backend)
            .first()
        )

    def overview(self) -> list[dict]:
        """供 Admin 展示：各能力域的激活后端、可用性、凭证齐备情况与配置。"""
        result: list[dict] = []
        for capability in SUPPORTED_CAPABILITIES:
            runtime = self.resolve_runtime(capability)
            active_row = self.get_config(capability, runtime.backend)
            masked_credentials = (
                self.serialize_config(active_row)["credentials"] if active_row is not None else {}
            )
            result.append(
                {
                    "capability": capability,
                    "active_backend": runtime.backend,
                    "enabled": runtime.enabled,
                    "reason": runtime.reason,
                    "configs": dict(runtime.configs),
                    # 凭证只回掩码；凭证键清单供前端渲染表单
                    "credentials": masked_credentials,
                    "credential_keys": list(_ALLOWED_CREDENTIAL_KEYS.get(runtime.backend, ())),
                    "backends": [
                        {
                            "backend": backend,
                            "label": _BACKEND_LABELS.get(backend, backend),
                            "is_active": backend == runtime.backend,
                        }
                        for backend in CAPABILITY_BACKENDS.get(capability, ())
                    ],
                }
            )
        return result

    def list_configs_view(self, capability: str | None = None) -> list[dict]:
        """列出配置（序列化为纯 dict，不透出 SQLAlchemy 模型）。"""
        return [self.serialize_config(row) for row in self.list_configs(capability)]

    @staticmethod
    def serialize_config(row: SandboxConfig) -> dict:
        """把配置行序列化为 Admin 可见结构。

        `configs` 为白名单键，可直接回显；`credentials` **只回掩码**（绝不回明文）；
        `credential_keys` 声明该后端可配置哪些凭证键（供前端渲染表单）。
        """
        raw_credentials = row.credentials if isinstance(row.credentials, dict) else {}
        masked_credentials: dict[str, str] = {}
        for key, token in raw_credentials.items():
            if not isinstance(token, str) or not token:
                continue
            try:
                masked_credentials[key] = str(mask_env({key: token}).get(key, "") or "")
            except Exception:
                logger.exception("沙箱凭证掩码失败 backend=%s key=%s", row.backend, key)
                masked_credentials[key] = ""
        return {
            "capability": row.capability,
            "backend": row.backend,
            "label": row.label,
            "configs": dict(row.configs or {}),
            "is_active": bool(row.is_active),
            "credentials": masked_credentials,
            "credential_keys": list(_ALLOWED_CREDENTIAL_KEYS.get(row.backend, ())),
        }

    # ------------------------------------------------------------------ #
    #  唯一权威读取入口
    # ------------------------------------------------------------------ #
    def resolve_credentials(self, capability: str, backend: str, row: SandboxConfig | None = None) -> dict:
        """解析后端凭证（**明文**）：DB 加密值解密优先 → env 兜底（占位符视为缺失）。

        **凭证进入 core 的唯一通道**；core 只消费 `SandboxRuntime.credentials`，不读 env/DB。
        """
        allowed = _ALLOWED_CREDENTIAL_KEYS.get(backend, ())
        if not allowed:
            return {}
        if row is None:
            row = self.get_config(capability, backend)
        stored = (
            dict(row.credentials or {})
            if row is not None and isinstance(row.credentials, dict)
            else {}
        )
        resolved: dict[str, str] = {}
        for key in allowed:
            value = ""
            token = stored.get(key)
            if isinstance(token, str) and token:
                try:
                    value = str(decrypt_env({key: token}).get(key, "") or "").strip()
                except Exception:
                    logger.exception(
                        "沙箱凭证解密失败 capability=%s backend=%s key=%s", capability, backend, key
                    )
                    value = ""
            if not value:
                env_value = str(os.getenv(key) or "").strip()
                value = "" if is_placeholder_secret(env_value) else env_value
            if value:
                resolved[key] = value
        return resolved

    def resolve_runtime(self, capability: str) -> SandboxRuntime:
        """解析某能力域的沙箱运行时快照（纯数据，供注入 core）。

        **沙箱配置的唯一权威读取入口。** 任何需要"沙箱能不能用 / 用哪个后端 /
        什么配置 / 什么凭证"的代码，都必须经此方法，不得再读 env 或直查表。
        """
        capability = self._validate_capability(capability)
        backend = self.get_active_backend(capability)
        row = self.get_config(capability, backend)
        configs = dict(_DEFAULT_CONFIGS.get((capability, backend), {}))
        if row is not None and isinstance(row.configs, dict):
            configs.update(_sanitize_configs(backend, row.configs))
        configs = self._clamp_timeouts(capability, configs)
        credentials = self.resolve_credentials(capability, backend, row)

        enabled, reason = self._evaluate(capability, backend, configs, credentials)
        return SandboxRuntime(
            capability=capability,
            backend=backend,
            configs=configs,
            credentials=credentials,
            enabled=enabled,
            reason=reason,
        )

    def probe(self, capability: str) -> dict:
        """连通性探测（不含密钥的轻量判定 + 结果原因）。

        真正的网络探测在 S3 由工厂构造客户端后执行；此处先给出"配置层"判定，
        保证 Admin 在未接后端实现时也能看到**为什么不可用**。
        """
        runtime = self.resolve_runtime(capability)
        return {
            "capability": capability,
            "backend": runtime.backend,
            "ok": runtime.enabled,
            "reason": runtime.reason,
        }

    # ------------------------------------------------------------------ #
    #  写入
    # ------------------------------------------------------------------ #
    def upsert_config(
        self,
        capability: str,
        backend: str,
        configs: dict | None = None,
        credentials: dict | None = None,
    ) -> SandboxConfig:
        """新增或更新（能力域, 后端）配置。

        - `configs`：仅保存白名单键；
        - `credentials`：白名单内的**凭证键**（键=env 名），值**加密入库**；空值表示清除；
          未传入（None）则该后端既有凭证保持不变。
        """
        self._validate_capability(capability)
        self._validate_backend(capability, backend)
        sanitized = _sanitize_configs(backend, configs)
        config = self.get_config(capability, backend)

        merged_credentials = (
            dict(config.credentials or {})
            if config is not None and isinstance(config.credentials, dict)
            else {}
        )
        allowed_credential_keys = _ALLOWED_CREDENTIAL_KEYS.get(backend, ())
        for key, value in (credentials or {}).items():
            if key not in allowed_credential_keys:
                raise ValidateErrorException(f"后端 {backend} 不支持凭证键: {key}")
            text = str(value if value is not None else "").strip()
            if text:
                # 幂等：已是密文则原样保留（避免二次加密）
                merged_credentials[key] = (
                    text if is_encrypted(text) else encrypt_env({key: text})[key]
                )
            else:
                merged_credentials.pop(key, None)

        if config is None:
            config = SandboxConfig(
                capability=capability,
                backend=backend,
                label=_BACKEND_LABELS.get(backend, backend),
                configs=sanitized,
                credentials=merged_credentials,
            )
            with self.db.auto_commit():
                self.db.session.add(config)
        else:
            with self.db.auto_commit():
                config.configs = sanitized
                config.credentials = merged_credentials
        logger.info(
            "sandbox config upsert capability=%s backend=%s keys=%s credential_keys=%s",
            capability,
            backend,
            list(sanitized.keys()),
            # 只记键名，绝不记录凭证值
            sorted(merged_credentials.keys()),
        )
        # 本进程立即失效运行时缓存；其他 worker 靠 TTL 自动跟进（热切换）
        invalidate_sandbox_runtime_cache()
        return config

    def set_active_backend(self, capability: str, backend: str) -> SandboxConfig:
        """激活某能力域的后端：**同能力域内**同一时间仅一个后端激活。

        热切换仅影响**新会话**；运行中会话绑定自身后端直到结束。
        """
        self._validate_capability(capability)
        self._validate_backend(capability, backend)
        with self.db.auto_commit():
            for config in self.list_configs(capability):
                config.is_active = config.backend == backend
        active = self.get_config(capability, backend)
        if active is None:
            active = SandboxConfig(
                capability=capability,
                backend=backend,
                label=_BACKEND_LABELS.get(backend, backend),
                configs={},
                is_active=True,
            )
            with self.db.auto_commit():
                self.db.session.add(active)
        elif not active.is_active:
            with self.db.auto_commit():
                active.is_active = True
        logger.info("sandbox backend switched capability=%s backend=%s", capability, backend)
        # 热切换：本进程立即生效，其他 worker TTL 内跟进
        invalidate_sandbox_runtime_cache()
        return active

    def ensure_default_config(self) -> None:
        """确保每个能力域的每个允许后端都有记录，且各能力域恰有一个激活项（幂等）。

        无激活记录时，按**当前 env** 推断激活后端，使库内状态与升级前的运行时一致
        ——这是"迁移期行为零变化"的关键。
        """
        existing = {(c.capability, c.backend) for c in self.list_configs()}
        for capability in SUPPORTED_CAPABILITIES:
            for backend in CAPABILITY_BACKENDS.get(capability, ()):
                if (capability, backend) in existing:
                    continue
                with self.db.auto_commit():
                    self.db.session.add(
                        SandboxConfig(
                            capability=capability,
                            backend=backend,
                            label=_BACKEND_LABELS.get(backend, backend),
                            configs=dict(_DEFAULT_CONFIGS.get((capability, backend), {})),
                        )
                    )
        # 展示名校正：label 由代码定义（Admin 无自定义入口）；历史行若落成裸 backend 名
        # （如常量补充前创建的记录），在此收敛回 `_BACKEND_LABELS`。
        for config in self.list_configs():
            expected = _BACKEND_LABELS.get(config.backend)
            if expected and config.label != expected:
                with self.db.auto_commit():
                    config.label = expected
        for capability in SUPPORTED_CAPABILITIES:
            has_active = any(c.is_active for c in self.list_configs(capability))
            if has_active:
                continue
            backend = self._infer_backend_from_env(capability)
            if backend not in CAPABILITY_BACKENDS.get(capability, ()):
                backend = BACKEND_DISABLED
            target = self.get_config(capability, backend)
            if target is None:
                target = SandboxConfig(
                    capability=capability,
                    backend=backend,
                    label=_BACKEND_LABELS.get(backend, backend),
                    configs=dict(_DEFAULT_CONFIGS.get((capability, backend), {})),
                )
                with self.db.auto_commit():
                    self.db.session.add(target)
            if not target.is_active:
                with self.db.auto_commit():
                    target.is_active = True

    # ------------------------------------------------------------------ #
    #  内部
    # ------------------------------------------------------------------ #
    @staticmethod
    def _evaluate(capability: str, backend: str, configs: dict, credentials: dict) -> tuple[bool, str]:
        """判定该（能力域, 后端）当前是否真的可用，并给出不可用原因。

        凭证来源：`credentials`（已由 `resolve_credentials` 解析为 DB 优先 → env 兜底）。
        本方法**不直接读 env**，确保"后台配置即时生效"。
        """
        if backend == BACKEND_DISABLED:
            return False, _REASON_DISABLED
        if backend in (BACKEND_BAIDU_CFC, BACKEND_E2B_CLOUD, BACKEND_ALIYUN_SANDBOX):
            has_credentials = bool(
                str(credentials.get("E2B_API_KEY") or "").strip()
                and str(credentials.get("E2B_DOMAIN") or "").strip()
            )
            return (True, "") if has_credentials else (False, _REASON_E2B_MISSING)
        if backend == BACKEND_HTTP_SANDBOX:
            endpoint = str(configs.get("endpoint") or "").strip()
            if is_placeholder_endpoint(endpoint):
                return False, _REASON_ENDPOINT_MISSING
            return True, ""
        if backend == BACKEND_TENCENT_SCF:
            has_secret = bool(
                str(credentials.get("TENCENTCLOUD_SECRET_ID") or "").strip()
                and str(credentials.get("TENCENTCLOUD_SECRET_KEY") or "").strip()
            )
            has_function = bool(str(configs.get("function_name") or "").strip())
            if not (has_secret and has_function):
                return False, _REASON_TENCENT_MISSING
            return True, ""
        return False, f"未知沙箱后端: {backend}"

    @staticmethod
    def _clamp_timeouts(capability: str, configs: dict) -> dict:
        """把超时类配置抬升到历史保护下限（见 `_TIMEOUT_FLOORS`）。"""
        floors = _TIMEOUT_FLOORS.get(capability)
        if not floors:
            return configs
        for key, floor in floors.items():
            if key not in configs:
                continue
            try:
                value = int(configs[key])
            except (TypeError, ValueError):
                continue
            configs[key] = max(value, floor)
        return configs

    @staticmethod
    def _env_endpoint(capability: str) -> str:
        """该能力域在 env 中的端点来源（迁移期兜底）。"""
        if capability == CAPABILITY_SKILL_EXEC:
            return str(os.getenv("SKILL_SCF_URL") or os.getenv("SANDBOX_URL") or "").strip()
        if capability == CAPABILITY_WORKFLOW_CODE:
            return str(os.getenv("SANDBOX_URL") or "").strip()
        return ""

    def _infer_backend_from_env(self, capability: str) -> str:
        """按当前 env 推断该能力域的激活后端（无 DB 记录时的兜底）。"""
        if capability == CAPABILITY_CODE_INTERPRETER:
            has_credentials = bool(
                str(os.getenv("E2B_API_KEY") or "").strip()
                and str(os.getenv("E2B_DOMAIN") or "").strip()
            )
            return BACKEND_BAIDU_CFC if has_credentials else BACKEND_DISABLED
        endpoint = self._env_endpoint(capability)
        return BACKEND_DISABLED if is_placeholder_endpoint(endpoint) else BACKEND_HTTP_SANDBOX

    @staticmethod
    def _validate_capability(capability: str) -> str:
        normalized = str(capability or "").strip()
        if normalized not in SUPPORTED_CAPABILITIES:
            raise ValidateErrorException(
                f"不支持的沙箱能力域: {capability}（可选值: {'/'.join(SUPPORTED_CAPABILITIES)}）"
            )
        return normalized

    @staticmethod
    def _validate_backend(capability: str, backend: str) -> None:
        normalized = str(backend or "").strip()
        allowed = CAPABILITY_BACKENDS.get(capability, ())
        if normalized not in allowed:
            raise ValidateErrorException(
                f"能力域 {capability} 不支持后端 {backend}（可选值: {'/'.join(allowed)}）"
            )
