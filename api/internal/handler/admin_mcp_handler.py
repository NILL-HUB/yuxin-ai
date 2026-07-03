from dataclasses import dataclass
from uuid import UUID

from flask import g
from injector import inject

from internal.extension.database_extension import db
from internal.middleware import admin_login_required, permission_required
from internal.model import Account
from internal.schema.mcp_schema import CreateMcpProviderReq, McpProviderResp, UpdateMcpProviderReq
from internal.service.mcp_service import McpService
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class AdminMcpHandler:
    """管理员 MCP 处理器"""

    mcp_service: McpService

    @admin_login_required
    @permission_required("mcp:create")
    def create(self):
        """创建 MCP（归属到管理员绑定的空间账号）"""
        req = CreateMcpProviderReq()
        if not req.validate():
            return validate_error_json(req.errors)

        account = self._get_admin_account()
        provider = self.mcp_service.create_mcp_provider(req, account)
        return success_json({"id": str(provider.id)})

    @admin_login_required
    @permission_required("mcp:read")
    def get(self, provider_id: UUID):
        """获取 MCP 详情（管理员视角，不校验账号归属）"""
        provider = self.mcp_service.get_mcp_provider_for_admin(provider_id)
        resp = McpProviderResp()
        return success_json(resp.dump(provider))

    @admin_login_required
    @permission_required("mcp:update")
    def update(self, provider_id: UUID):
        """更新 MCP（管理员视角，不校验账号归属）"""
        req = UpdateMcpProviderReq()
        if not req.validate():
            return validate_error_json(req.errors)
        self.mcp_service.update_mcp_provider_for_admin(provider_id, req)
        return success_message("更新MCP成功")

    @admin_login_required
    @permission_required("mcp:update")
    def regenerate_icon(self, provider_id: UUID):
        """重新生成 MCP 图标（管理员视角，不校验账号归属）"""
        icon = self.mcp_service.regenerate_icon_for_admin(provider_id)
        return success_json({"icon": icon})

    @admin_login_required
    @permission_required("mcp:delete")
    def delete(self, provider_id: UUID):
        """删除 MCP（管理员视角，不校验账号归属）"""
        self.mcp_service.delete_mcp_provider_for_admin(provider_id)
        return success_message("删除MCP成功")

    def _get_admin_account(self) -> Account:
        """获取管理员绑定的空间账号，作为资源的归属账号"""
        account_id = g.current_admin_user.get("account_id")
        if not account_id:
            raise ValueError("管理员账号未关联空间账号，请先在 RBAC 管理中绑定")
        account = db.session.get(Account, account_id)
        if not account:
            raise ValueError("管理员关联的空间账号不存在")
        return account
