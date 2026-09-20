"""管理端 Agent MCP 动态身份注入单测（ADMIN-P5）。

覆盖设计 §7.2：签名只承载身份标识（不放权限快照，保持运行时实时重算），
运行时 binding 副本注入内部字段，验证函数可供未来 MCP server 侧使用。
"""
import uuid

import pytest

from internal.core.admin_agent_mcp_identity import (
    PRINCIPAL_HEADER,
    PRINCIPAL_TOKEN_FIELD,
    build_runtime_bindings_with_identity,
    sign_principal_token,
    verify_principal_token,
)
from internal.entity.admin_agent_entity import AdminAgentPrincipal, AutomationLevel
from internal.service.jwt_service import JwtService

JWT_SECRET = "test-secret-key-with-32-bytes-min-123456"


def _make_principal() -> AdminAgentPrincipal:
    return AdminAgentPrincipal(
        admin_user_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        agent_name="ops-agent",
        effective_permissions=frozenset({"builtin_tool:read", "builtin_tool:update"}),
        automation_policy={"builtin_tool": AutomationLevel.AUTONOMOUS},
    )


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", JWT_SECRET)


class TestSignPrincipalToken:
    def test_token_roundtrip_contains_identity_only(self):
        """签名可还原，且只含身份标识（admin_user_id/agent_id/agent_name/iat/exp）。

        为什么断言"不含权限快照"：权限是三重交集实时重算（设计 §4.1），
        放进 token 会过期——撤销权限后旧 token 仍带旧权限，破坏实时重算约束。
        """
        principal = _make_principal()
        token = sign_principal_token(principal)
        payload = JwtService.parse_token(token)

        assert payload["admin_user_id"] == str(principal.admin_user_id)
        assert payload["agent_id"] == str(principal.agent_id)
        assert payload["agent_name"] == "ops-agent"
        assert isinstance(payload["iat"], int)
        assert isinstance(payload["exp"], int)

        for permission_code in principal.effective_permissions:
            assert permission_code not in payload, (
                "权限快照不应进入签名，必须由 MCP server 侧实时重算"
            )
        assert "automation_policy" not in payload

    def test_verify_principal_token_returns_payload(self):
        principal = _make_principal()
        token = sign_principal_token(principal)
        payload = verify_principal_token(token)
        assert payload["agent_id"] == str(principal.agent_id)

    def test_verify_rejects_tampered_token(self):
        principal = _make_principal()
        token = sign_principal_token(principal)
        from internal.exception import UnauthorizedException

        with pytest.raises(UnauthorizedException):
            verify_principal_token(token[:-4] + "xxxx")


class TestBuildRuntimeBindingsWithIdentity:
    def test_injects_principal_token_field(self):
        """运行时 binding 副本注入内部字段，且不修改原 binding。"""
        original = [
            {
                "name": "global-mcp",
                "transport": "streamable_http",
                "url": "https://mcp.example.com",
                "enabled": True,
            }
        ]
        runtime_bindings = build_runtime_bindings_with_identity(
            original, _make_principal()
        )

        assert PRINCIPAL_TOKEN_FIELD in runtime_bindings[0]
        assert runtime_bindings[0][PRINCIPAL_TOKEN_FIELD]

        # 原 binding 不被污染（内部字段只存在于装配期运行时副本）
        assert PRINCIPAL_TOKEN_FIELD not in original[0]

    def test_empty_bindings_return_empty(self):
        assert build_runtime_bindings_with_identity([], _make_principal()) == []


class TestConstants:
    def test_header_and_field_names(self):
        assert PRINCIPAL_HEADER == "X-Admin-Agent-Principal"
        assert PRINCIPAL_TOKEN_FIELD == "_principal_token"
