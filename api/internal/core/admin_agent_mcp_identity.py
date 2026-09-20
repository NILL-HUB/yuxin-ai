"""管理端 Agent MCP 动态身份注入（设计 §7.2，ADMIN-P5）。

机理：admin 对话链路装配 MCP 工具时，为每个 runtime binding **副本**注入
``_principal_token``（JWT HS256，复用 ``JwtService`` 与 ``JWT_SECRET_KEY``），
``McpToolFactory._jsonrpc_request`` 将其作为 ``X-Admin-Agent-Principal``
header 发送给 MCP server；``McpToolFactory._binding_hash`` 计算前剥离
下划线开头的内部字段，保证动态签名不破坏快照复用。

为什么 token 只放身份标识、不放权限快照：权限是三重交集**运行时实时重算**
（设计 §4.1），放进 token 会过期——撤销权限后旧 token 仍带旧权限。MCP
server 侧应凭 ``admin_user_id`` + ``agent_id`` 从 DB 重算 principal（与
L1 执行层同一入口），再做与 L1 完全相同的权限与自动化级别校验。

为什么内部字段不进 ``headers`` 列表：``headers`` 在库中存的是**加密后的
静态凭证**（``decrypt_headers`` 对非空 value 强制解密，失败抛
``ValueError``）；混入动态明文会破坏该不变量并触发抛错路径。独立内部字段
只存在于装配期的运行时副本，不落库、不参与 hash、不触发解密。
"""
from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from internal.entity.admin_agent_entity import AdminAgentPrincipal
from internal.service.jwt_service import JwtService

# binding 内部字段名（下划线开头 = hash 剥离依据，见 McpToolFactory._binding_hash）
PRINCIPAL_TOKEN_FIELD = "_principal_token"
# 注入 MCP 请求的 header 名
PRINCIPAL_HEADER = "X-Admin-Agent-Principal"
# token 有效期：单轮对话工具循环 ≤6 次迭代，5 分钟足够；过期即失效（fail closed）
PRINCIPAL_TOKEN_TTL_SECONDS = 300


def sign_principal_token(principal: AdminAgentPrincipal) -> str:
    """为 principal 签发短时身份签名（JWT HS256）。

    Payload 只承载身份标识：``admin_user_id`` / ``agent_id`` /
    ``agent_name`` / ``iat`` / ``exp``。**不含权限与自动化策略**——保持
    运行时实时重算约束（设计 §4.1），撤销权限后旧 token 无法带着旧权限使用。
    """
    now = int(time.time())
    payload: dict[str, Any] = {
        "admin_user_id": str(principal.admin_user_id),
        "agent_id": str(principal.agent_id),
        "agent_name": principal.agent_name or "",
        "iat": now,
        "exp": now + PRINCIPAL_TOKEN_TTL_SECONDS,
    }
    return JwtService.generate_token(payload)


def verify_principal_token(token: str) -> dict[str, Any]:
    """验证签名并还原 payload（供未来进程内 MCP server 侧使用）。

    本系统当前**无进程内 MCP server 实现**：该函数提供能力、验证可用，
    但暂无生产消费方（已提供、未接入）。
    """
    return JwtService.parse_token(token)


def build_runtime_bindings_with_identity(
    mcp_bindings: list[dict[str, Any]], principal: AdminAgentPrincipal
) -> list[dict[str, Any]]:
    """为每个 binding 构造**副本**并注入 ``_principal_token``。

    为什么必须副本：原 binding 可能来自 ``app_config`` / ``ASSISTANT_MCP_BINDINGS``
    配置，直接改会污染 DB 序列化与快照持久化（签名明文落库风险，设计 §7.2）。
    内部字段只存在于装配期的运行时副本。
    """
    if not isinstance(mcp_bindings, list):
        return []
    token = sign_principal_token(principal)
    runtime_bindings: list[dict[str, Any]] = []
    for binding in mcp_bindings:
        if not isinstance(binding, dict):
            continue
        runtime = dict(binding)
        runtime[PRINCIPAL_TOKEN_FIELD] = token
        runtime_bindings.append(runtime)
    return runtime_bindings


def principal_from_token(token: str) -> dict[str, UUID | str]:
    """从签名还原 (admin_user_id, agent_id) 归属标识。

    供 MCP server 侧凭 ``agent_id`` 走 ``AdminAgentService.get_principal``
    实时重算授权（与 L1 同一入口）。当前无消费方（已提供、未接入）。
    """
    payload = verify_principal_token(token)
    return {
        "admin_user_id": UUID(payload["admin_user_id"]),
        "agent_id": UUID(payload["agent_id"]),
    }
