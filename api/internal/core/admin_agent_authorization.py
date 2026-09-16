"""管理端 Agent 授权内核。

与 ``rbac.py`` 的分工：
- ``rbac.py``：权限点**目录**（纯声明，零逻辑）。
- 本模块：**授权计算**（有行为的安全边界），含 fail-closed 规则。

设计依据：docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md §4。
"""
from __future__ import annotations

from internal.core.rbac import PERMISSION_BY_CODE, PERMISSION_CATALOG


# 完全封禁：身份与权限体系。
# 下放等于 Agent 能自我提权、改角色、改他人账号，安全模型自我解体。
BANNED_PERMISSION_CODES = frozenset({
    "admin:access",
    "admin_user:read",
    "admin_user:create",
    "admin_user:update",
    "admin_user:disable",
    "admin_user:delete",
    "role:read",
    "role:create",
    "role:update",
    "role:delete",
    "permission:read",
})

# 仅只读可下放：写操作影响真实用户，归为禁区。
READ_ONLY_ASSIGNABLE_RESOURCES = frozenset({"user"})

# 可下放白名单（显式登记制，见下方 fail-closed 说明）。
ASSIGNABLE_RESOURCES = frozenset({
    "agent_pool", "app", "audit_log", "builtin_tool", "cost_stats", "dataset",
    "mcp", "model_pool", "model_provider", "openapi", "orchestration_flag",
    "orchestration_release", "order", "payment_config", "plan", "prompt_template",
    "public_ai_feature", "recycle_bin", "redeem_code", "refund", "routing_log",
    "routing_quality", "schedule_task", "setting", "skill", "storage",
    "system_config", "system_knowledge", "tool", "tool_governance", "user",
    "withdraw", "workflow",
})


def is_assignable(permission_code: str) -> bool:
    """判断单个权限点是否可下放给管理端 Agent。

    fail closed：**显式登记制**——只有 resource 在 ``ASSIGNABLE_RESOURCES``
    中（且不在封禁项、且满足只读约束）才返回 True。未来新增权限点若其
    resource 为全新前缀，默认**不可下放**，必须显式登记才放开，避免被静默
    暴露给 Agent。
    """
    if permission_code in BANNED_PERMISSION_CODES:
        return False
    spec = PERMISSION_BY_CODE.get(permission_code)
    if spec is None:
        return False
    if spec.resource not in ASSIGNABLE_RESOURCES:
        return False
    if (
        spec.resource in READ_ONLY_ASSIGNABLE_RESOURCES
        and spec.action != "read"
    ):
        return False
    return True


ASSIGNABLE_PERMISSIONS = frozenset(
    spec.code for spec in PERMISSION_CATALOG if is_assignable(spec.code)
)


def compute_effective_permissions(
    *,
    admin_permissions,
    granted_permissions,
) -> frozenset[str]:
    """计算 Agent 的最终生效权限：``admin ∩ granted ∩ assignable``。

    设计 §4.1：三者缺一不可。任一维度收紧，Agent 能力立即随之收紧。
    每次请求实时重算（与 docs/rbac.md §3.5 的既有原则一致，不依赖静态快照）。
    """
    return (
        frozenset(admin_permissions)
        & frozenset(granted_permissions)
        & ASSIGNABLE_PERMISSIONS
    )


def assert_grantable(*, requested, admin_permissions) -> None:
    """保存授权时的独立校验（设计 §4.3 第二层）。

    UI 过滤只是体验，**不是安全边界**；此处必须拒绝越界请求。

    Raises:
        ValueError: 请求包含"管理员自己没有"或"系统不允许下放"的权限点。
    """
    admin_set = frozenset(admin_permissions)
    beyond_admin = sorted(set(requested) - admin_set)
    if beyond_admin:
        raise ValueError(
            f"无权下放以下权限（管理员不具备）: {', '.join(beyond_admin)}"
        )
    not_assignable = sorted(c for c in requested if not is_assignable(c))
    if not_assignable:
        raise ValueError(
            f"以下权限不可下放给 Agent: {', '.join(not_assignable)}"
        )
