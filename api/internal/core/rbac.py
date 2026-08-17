"""RBAC 单一事实源。

权限 code 是外部稳定标识（如 ``app:read``），UUID 仅作为数据库内部主键。
默认角色模板和权限目录集中在这里，服务层、迁移和鉴权层统一引用。
"""

from __future__ import annotations

from dataclasses import dataclass


SUPER_ADMIN_ROLE_CODE = "super_admin"


@dataclass(frozen=True)
class PermissionSpec:
    code: str
    name: str
    resource: str
    action: str
    description: str = ""


@dataclass(frozen=True)
class RoleSpec:
    code: str
    name: str
    description: str = ""
    permission_codes: tuple[str, ...] = ()


PERMISSION_CATALOG = [
    PermissionSpec("admin:access", "访问管理后台", "admin", "access", "允许进入管理后台"),
    PermissionSpec("admin_user:read", "查看管理员", "admin_user", "read", "查看管理员账号"),
    PermissionSpec("admin_user:create", "创建管理员", "admin_user", "create", "创建管理员账号"),
    PermissionSpec("admin_user:update", "更新管理员", "admin_user", "update", "更新管理员账号"),
    PermissionSpec("admin_user:disable", "禁用管理员", "admin_user", "disable", "禁用、启用、重置管理员账号"),
    PermissionSpec("role:read", "查看角色", "role", "read", "查看角色"),
    PermissionSpec("role:create", "创建角色", "role", "create", "创建角色"),
    PermissionSpec("role:update", "更新角色", "role", "update", "更新角色"),
    PermissionSpec("role:delete", "删除角色", "role", "delete", "删除角色"),
    PermissionSpec("permission:read", "查看权限", "permission", "read", "查看权限点"),
    PermissionSpec("audit_log:read", "查看审计日志", "audit_log", "read", "查看审计日志"),
    PermissionSpec("app:read", "查看应用", "app", "read", "查看 Agent 智能体应用"),
    PermissionSpec("app:create", "创建应用", "app", "create", "创建 Agent 智能体应用"),
    PermissionSpec("app:update", "更新应用", "app", "update", "更新应用及执行上线、调试等管理操作"),
    PermissionSpec("app:delete", "删除应用", "app", "delete", "删除 Agent 智能体应用"),
    PermissionSpec("workflow:read", "查看工作流", "workflow", "read", "查看工作流"),
    PermissionSpec("workflow:create", "创建工作流", "workflow", "create", "创建工作流"),
    PermissionSpec("workflow:update", "更新工作流", "workflow", "update", "更新、发布和下线工作流"),
    PermissionSpec("workflow:delete", "删除工作流", "workflow", "delete", "删除工作流"),
    PermissionSpec("dataset:read", "查看知识库", "dataset", "read", "查看知识库"),
    PermissionSpec("dataset:update", "更新知识库", "dataset", "update", "更新知识库"),
    PermissionSpec("tool:read", "查看工具", "tool", "read", "查看自定义 API 工具"),
    PermissionSpec("tool:create", "创建工具", "tool", "create", "创建自定义 API 工具"),
    PermissionSpec("tool:update", "更新工具", "tool", "update", "更新自定义 API 工具"),
    PermissionSpec("tool:delete", "删除工具", "tool", "delete", "删除自定义 API 工具"),
    PermissionSpec("mcp:read", "查看 MCP", "mcp", "read", "查看 MCP Provider"),
    PermissionSpec("mcp:create", "创建 MCP", "mcp", "create", "创建 MCP Provider"),
    PermissionSpec("mcp:update", "更新 MCP", "mcp", "update", "更新 MCP Provider"),
    PermissionSpec("mcp:delete", "删除 MCP", "mcp", "delete", "删除 MCP Provider"),
    PermissionSpec("skill:read", "查看技能", "skill", "read", "查看技能包"),
    PermissionSpec("skill:create", "创建技能", "skill", "create", "创建或导入技能包"),
    PermissionSpec("skill:update", "更新技能", "skill", "update", "更新、启停和同步技能包"),
    PermissionSpec("skill:delete", "删除技能", "skill", "delete", "删除技能包"),
    PermissionSpec("user:read", "查看用户", "user", "read", "查看用户"),
    PermissionSpec("user:update", "更新用户", "user", "update", "更新用户状态和会话"),
    PermissionSpec("user:disable", "禁用用户", "user", "disable", "禁用用户账号"),
    PermissionSpec("plan:read", "查看套餐", "plan", "read", "查看套餐和权益配置"),
    PermissionSpec("plan:update", "管理套餐", "plan", "update", "创建、更新和启停套餐"),
    PermissionSpec("redeem_code:read", "查看卡密", "redeem_code", "read", "查看卡密批次和卡密状态"),
    PermissionSpec("redeem_code:update", "管理卡密", "redeem_code", "update", "生成和禁用卡密"),
    PermissionSpec("app_assignment:read", "查看应用分配", "app_assignment", "read", "查看用户已分配应用"),
    PermissionSpec("app_assignment:update", "管理应用分配", "app_assignment", "update", "分配和撤销用户应用"),
    PermissionSpec("setting:read", "查看设置", "setting", "read", "查看系统设置"),
    PermissionSpec("schedule_task:read", "查看定时任务", "schedule_task", "read", "查看平台定时任务"),
    PermissionSpec("schedule_task:create", "创建定时任务", "schedule_task", "create", "创建平台定时任务"),
    PermissionSpec("schedule_task:update", "管理定时任务", "schedule_task", "update", "更新、启停和执行定时任务"),
    PermissionSpec("schedule_task:delete", "删除定时任务", "schedule_task", "delete", "删除平台定时任务"),
    PermissionSpec("prompt_template:read", "查看提示词模板", "prompt_template", "read", "查看系统提示词模板"),
    PermissionSpec("prompt_template:update", "管理提示词模板", "prompt_template", "update", "更新、重置系统提示词模板"),
    PermissionSpec("prompt_template:delete", "删除提示词模板", "prompt_template", "delete", "删除系统提示词模板"),
    PermissionSpec("builtin_tool:read", "查看内置工具", "builtin_tool", "read", "查看内置工具"),
    PermissionSpec("builtin_tool:update", "管理内置工具", "builtin_tool", "update", "启停内置工具"),
    PermissionSpec("public_ai_feature:read", "查看公开 AI 能力", "public_ai_feature", "read", "查看公开 AI 能力配置"),
    PermissionSpec("public_ai_feature:update", "管理公开 AI 能力", "public_ai_feature", "update", "更新公开 AI 能力配置"),
    PermissionSpec("storage:read", "查看存储配置", "storage", "read", "查看内容存储配置"),
    PermissionSpec("storage:update", "管理存储配置", "storage", "update", "管理内容存储配置与文件"),
    PermissionSpec("agent_pool:read", "查看智能体池", "agent_pool", "read", "查看智能体池"),
    PermissionSpec("agent_pool:manage", "管理智能体池", "agent_pool", "manage", "管理智能体池和子池"),
    PermissionSpec("model_provider:read", "查看模型供应商", "model_provider", "read", "查看模型供应商配置"),
    PermissionSpec("model_provider:create", "创建模型供应商", "model_provider", "create", "创建模型供应商"),
    PermissionSpec("model_provider:update", "更新模型供应商", "model_provider", "update", "更新模型供应商配置"),
    PermissionSpec("model_provider:delete", "删除模型供应商", "model_provider", "delete", "删除模型供应商"),
    PermissionSpec("model_pool:read", "查看模型池", "model_pool", "read", "查看模型池配置"),
    PermissionSpec("model_pool:create", "创建模型", "model_pool", "create", "创建模型配置"),
    PermissionSpec("model_pool:update", "更新模型", "model_pool", "update", "更新模型配置"),
    PermissionSpec("model_pool:delete", "删除模型", "model_pool", "delete", "删除模型配置"),
    PermissionSpec("model_pool:manage", "管理模型运行资源", "model_pool", "manage", "管理模型 Key、分层和成本策略"),
    PermissionSpec("tool_governance:read", "查看工具治理", "tool_governance", "read", "查看工具治理策略"),
    PermissionSpec("tool_governance:manage", "管理工具治理", "tool_governance", "manage", "管理工具治理策略"),
    PermissionSpec("orchestration_flag:read", "查看调度开关", "orchestration_flag", "read", "查看调度平台发布开关"),
    PermissionSpec("orchestration_flag:update", "管理调度开关", "orchestration_flag", "update", "启停调度平台发布开关"),
    PermissionSpec("orchestration_release:read", "查看调度上线验收", "orchestration_release", "read", "查看调度平台上线验收报告"),
    PermissionSpec("routing_log:read", "查看路由日志", "routing_log", "read", "查看路由日志"),
    PermissionSpec("routing_log:update", "管理路由日志", "routing_log", "update", "管理路由日志留存策略"),
    PermissionSpec("routing_quality:read", "查看路由质量", "routing_quality", "read", "查看路由质量指标与调优建议"),
    PermissionSpec("routing_quality:feedback", "提交路由反馈", "routing_quality", "feedback", "提交路由质量反馈"),
    PermissionSpec("routing_quality:accept", "采纳调优建议", "routing_quality", "accept", "采纳半自动调优建议"),
    PermissionSpec("routing_quality:dismiss", "驳回调优建议", "routing_quality", "dismiss", "驳回不适用调优建议并记录原因"),
    PermissionSpec("routing_quality:apply", "应用策略变更", "routing_quality", "apply", "应用策略变更草稿到路由策略"),
    PermissionSpec("routing_quality:rollback", "回滚策略变更", "routing_quality", "rollback", "回滚已应用的策略变更"),
    PermissionSpec("recycle_bin:read", "查看系统资源回收站", "recycle_bin", "read", "查看系统资源回收站"),
    PermissionSpec("recycle_bin:write", "恢复回收站条目", "recycle_bin", "write", "恢复系统资源回收站条目"),
    PermissionSpec("cost_stats:read", "查看成本统计", "cost_stats", "read", "查看成本统计"),
    PermissionSpec("openapi:read", "查看开放 API", "openapi", "read", "查看开放 API 密钥"),
    PermissionSpec("openapi:create", "创建开放 API 密钥", "openapi", "create", "创建开放 API 密钥"),
    PermissionSpec("openapi:update", "更新开放 API 密钥", "openapi", "update", "启停开放 API 密钥"),
    PermissionSpec("openapi:delete", "删除开放 API 密钥", "openapi", "delete", "删除开放 API 密钥"),
    PermissionSpec("system_knowledge:read", "查看系统知识库", "system_knowledge", "read", "查看系统级知识库"),
    PermissionSpec("system_knowledge:write", "管理系统知识库", "system_knowledge", "write", "创建、编辑、删除系统级知识库"),
]

PERMISSION_BY_CODE = {permission.code: permission for permission in PERMISSION_CATALOG}


def _permission_codes(*codes: str) -> tuple[str, ...]:
    unknown = [code for code in codes if code not in PERMISSION_BY_CODE]
    if unknown:
        raise ValueError(f"未知权限 code: {', '.join(unknown)}")
    return tuple(codes)


DEFAULT_ROLES = [
    RoleSpec(
        SUPER_ADMIN_ROLE_CODE,
        "超级管理员",
        "拥有全部权限，系统保留角色",
    ),
    RoleSpec(
        "operator",
        "运营管理员",
        "管理应用、工作流、知识库、工具、用户和日常运营",
        _permission_codes(
            "app:read",
            "app:create",
            "app:update",
            "app:delete",
            "workflow:read",
            "workflow:create",
            "workflow:update",
            "workflow:delete",
            "dataset:read",
            "dataset:update",
            "system_knowledge:read",
            "system_knowledge:write",
            "tool:read",
            "tool:create",
            "tool:update",
            "tool:delete",
            "mcp:read",
            "mcp:create",
            "mcp:update",
            "mcp:delete",
            "skill:read",
            "skill:create",
            "skill:update",
            "skill:delete",
            "user:read",
            "user:update",
            "user:disable",
            "app_assignment:read",
            "app_assignment:update",
            "schedule_task:read",
            "schedule_task:create",
            "schedule_task:update",
            "schedule_task:delete",
            "routing_log:read",
            "routing_log:update",
            "routing_quality:read",
            "routing_quality:feedback",
            "routing_quality:accept",
            "routing_quality:dismiss",
            "routing_quality:apply",
            "routing_quality:rollback",
            "orchestration_flag:read",
            "orchestration_flag:update",
            "orchestration_release:read",
            "cost_stats:read",
        ),
    ),
    RoleSpec(
        "finance",
        "财务管理员",
        "管理套餐、卡密和收入数据",
        _permission_codes(
            "plan:read",
            "plan:update",
            "redeem_code:read",
            "redeem_code:update",
            "cost_stats:read",
        ),
    ),
    RoleSpec(
        "support",
        "客服人员",
        "查询用户和基础资料",
        _permission_codes(
            "user:read",
            "app:read",
            "workflow:read",
            "routing_log:read",
        ),
    ),
    RoleSpec(
        "auditor",
        "审核人员",
        "审核应用、工作流、插件等内容",
        _permission_codes(
            "user:read",
            "app:read",
            "workflow:read",
            "tool:read",
            "skill:read",
            "mcp:read",
            "audit_log:read",
            "orchestration_release:read",
            "routing_quality:read",
        ),
    ),
    RoleSpec(
        "viewer",
        "只读观察员",
        "只读查看后台数据",
        _permission_codes(
            "app:read",
            "workflow:read",
            "dataset:read",
            "system_knowledge:read",
            "tool:read",
            "mcp:read",
            "skill:read",
            "user:read",
            "plan:read",
            "redeem_code:read",
            "app_assignment:read",
            "setting:read",
            "schedule_task:read",
            "prompt_template:read",
            "builtin_tool:read",
            "public_ai_feature:read",
            "storage:read",
            "agent_pool:read",
            "model_provider:read",
            "model_pool:read",
            "tool_governance:read",
            "orchestration_flag:read",
            "orchestration_release:read",
            "routing_log:read",
            "routing_quality:read",
            "recycle_bin:read",
            "cost_stats:read",
            "openapi:read",
            "audit_log:read",
        ),
    ),
]

DEFAULT_ROLE_BY_CODE = {role.code: role for role in DEFAULT_ROLES}


def all_permission_codes() -> tuple[str, ...]:
    return tuple(permission.code for permission in PERMISSION_CATALOG)
