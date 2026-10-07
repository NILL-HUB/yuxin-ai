"""沙箱运行时契约（跨层，core 归属）。

为什么放在 core：`internal/core/**` 是框架无关层（无 injector、无 DB），
但沙箱后端构造发生在 core（深度思考 / execute_code / 技能执行）。
因此配置必须由 service 层解析成一个**纯数据对象**注入 core，core 不读 DB、不读 env。

- 解析入口（唯一权威）：`SandboxConfigService.resolve_runtime(capability)`
- 消费方：`internal/core/agent/backends/factory.build_sandbox_backend(runtime)`

本模块同时定义能力域与后端名的**字符串常量**，供 service 层与 factory 共享，
避免两处各写一份魔法字符串。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
#  能力域：同一能力域内同一时间只有一个激活后端
# --------------------------------------------------------------------------- #
CAPABILITY_CODE_INTERPRETER = "code_interpreter"
CAPABILITY_SKILL_EXEC = "skill_exec"
CAPABILITY_WORKFLOW_CODE = "workflow_code"

CAPABILITIES: tuple[str, ...] = (
    CAPABILITY_CODE_INTERPRETER,
    CAPABILITY_SKILL_EXEC,
    CAPABILITY_WORKFLOW_CODE,
)

# --------------------------------------------------------------------------- #
#  后端名：新增沙箱后端时在此加一个常量 + 在 factory 注册一个 builder 即可
# --------------------------------------------------------------------------- #
BACKEND_BAIDU_CFC = "baidu_cfc"      # 百度 CFC（E2B 协议）
BACKEND_E2B_CLOUD = "e2b_cloud"      # 官方 E2B 云沙箱（E2B 协议）
BACKEND_HTTP_SANDBOX = "http_sandbox"  # 通用 HTTP 远端执行（技能 SCF / 工作流代码节点共用，按能力域各自持 endpoint）
BACKEND_TENCENT_SCF = "tencent_scf"  # 腾讯云函数 SDK 直调（InvokeFunction，IAM 鉴权、无需公网端点）
BACKEND_DISABLED = "disabled"        # 显式未开通（不再静默降级）

BACKENDS: tuple[str, ...] = (
    BACKEND_BAIDU_CFC,
    BACKEND_E2B_CLOUD,
    BACKEND_HTTP_SANDBOX,
    BACKEND_TENCENT_SCF,
    BACKEND_DISABLED,
)

# 每个能力域允许的后端（校验用；`disabled` 一律允许，用于「诚实下线」）
# 为什么 tencent_scf 不挂 code_interpreter：深思考需要 shell + 文件系统语义，
# SDK 直调是「一次调用、一次结果」的无状态执行，语义不匹配（同 http_sandbox）。
CAPABILITY_BACKENDS: dict[str, tuple[str, ...]] = {
    CAPABILITY_CODE_INTERPRETER: (BACKEND_BAIDU_CFC, BACKEND_E2B_CLOUD, BACKEND_DISABLED),
    CAPABILITY_SKILL_EXEC: (
        BACKEND_HTTP_SANDBOX,
        BACKEND_TENCENT_SCF,
        BACKEND_BAIDU_CFC,
        BACKEND_DISABLED,
    ),
    CAPABILITY_WORKFLOW_CODE: (BACKEND_HTTP_SANDBOX, BACKEND_TENCENT_SCF, BACKEND_DISABLED),
}


@dataclass(frozen=True)
class SandboxRuntime:
    """沙箱运行时快照（纯数据，可安全传入 core）。

    Args:
        capability: 能力域（见 CAPABILITIES）
        backend:    激活的后端名（见 BACKENDS），可能为 `disabled`
        configs:    白名单后的配置项（模板名 / 超时 / endpoint 等），**不含密钥**
        credentials: 后端凭证（**明文**，仅供 core 构造后端句柄；由 service 层
                     `SandboxConfigService.resolve_runtime` 解析——DB 加密值解密优先 → env 兜底）。
                     本对象不落库、不回显给前端（前端只看掩码）。
        enabled:    是否可用（backend != disabled 且凭证/端点齐备）
        reason:     enabled=False 时的人类可读原因（供前端与日志如实展示）
    """

    capability: str
    backend: str = BACKEND_DISABLED
    configs: dict = field(default_factory=dict)
    credentials: dict = field(default_factory=dict)
    enabled: bool = False
    reason: str = ""

    def get(self, key: str, default=""):
        """读取配置项（便捷方法，避免消费方到处 .configs.get）。"""
        value = (self.configs or {}).get(key)
        return default if value in (None, "") else value

    def get_credential(self, key: str, default: str = "") -> str:
        """读取后端凭证（明文）；缺失返回 default。core 只经此取密钥，不读 env。"""
        value = (self.credentials or {}).get(key)
        return default if value in (None, "") else str(value)

    def get_int(self, key: str, default: int) -> int:
        """读取整型配置项；非法值回退 default。"""
        try:
            value = int(self.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """读取布尔配置项；接受 1/true/yes/on（大小写不敏感）。"""
        value = (self.configs or {}).get(key)
        if value is None or value == "":
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
