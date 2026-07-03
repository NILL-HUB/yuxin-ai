from dataclasses import dataclass
from uuid import UUID

from flask import g, request
from injector import inject

from internal.extension.database_extension import db
from internal.middleware import admin_login_required, permission_required
from internal.model import Account
from internal.schema.api_tool_schema import (
    CreateApiToolReq,
    GetApiToolProviderResp,
    GetApiToolProvidersWithPageReq,
    GetApiToolProvidersWithPageResp,
    UpdateApiToolProviderReq,
)
from internal.service import ApiToolService
from pkg.paginator import PageModel
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class AdminApiToolHandler:
    """管理员自定义API插件处理器"""

    api_tool_service: ApiToolService

    @admin_login_required
    @permission_required("tool:read")
    def list(self):
        """获取API工具提供者列表（管理员视角，不过滤账号）"""
        req = GetApiToolProvidersWithPageReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)

        api_tool_providers, paginator = self.api_tool_service.get_api_tool_providers_with_page_for_admin(req)
        resp = GetApiToolProvidersWithPageResp(many=True)
        return success_json(PageModel(list=resp.dump(api_tool_providers), paginator=paginator))

    @admin_login_required
    @permission_required("tool:create")
    def create(self):
        """创建自定义API工具（归属到管理员绑定的空间账号）"""
        req = CreateApiToolReq()
        if not req.validate():
            return validate_error_json(req.errors)

        account = self._get_admin_account()
        self.api_tool_service.create_api_tool(req, account)
        return success_message("创建自定义API插件成功")

    @admin_login_required
    @permission_required("tool:read")
    def get(self, provider_id: UUID):
        """获取API工具提供者详情（管理员视角，不校验账号）"""
        api_tool_provider = self.api_tool_service.get_api_tool_provider_for_admin(provider_id)
        resp = GetApiToolProviderResp()
        return success_json(resp.dump(api_tool_provider))

    @admin_login_required
    @permission_required("tool:update")
    def update(self, provider_id: UUID):
        """更新API工具提供者（管理员视角，不校验账号）"""
        req = UpdateApiToolProviderReq()
        if not req.validate():
            return validate_error_json(req.errors)

        self.api_tool_service.update_api_tool_provider_for_admin(provider_id, req)
        return success_message("更新自定义API插件成功")

    @admin_login_required
    @permission_required("tool:delete")
    def delete(self, provider_id: UUID):
        """删除API工具提供者（管理员视角，不校验账号）"""
        self.api_tool_service.delete_api_tool_provider_for_admin(provider_id)
        return success_message("删除自定义API插件成功")

    def _get_admin_account(self) -> Account:
        """获取管理员绑定的空间账号，作为资源的归属账号"""
        account_id = g.current_admin_user.get("account_id")
        if not account_id:
            raise ValueError("管理员账号未关联空间账号，请先在 RBAC 管理中绑定")
        account = db.session.get(Account, account_id)
        if not account:
            raise ValueError("管理员关联的空间账号不存在")
        return account
