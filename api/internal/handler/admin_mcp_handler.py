from dataclasses import dataclass
from uuid import UUID

from flask import g, request
from injector import inject

from internal.extension.database_extension import db
from internal.middleware import admin_login_required, permission_required
from internal.model import Account
from internal.schema.mcp_schema import (
    CreateMcpProviderReq,
    ImportMcpJsonConfigReq,
    ImportMcpJsonReq,
    ImportMcpUrlReq,
    McpProviderResp,
    PreviewMcpUrlReq,
    UpdateMcpProviderReq,
)
from internal.service.mcp_import_service import McpImportService
from internal.service.mcp_service import McpService
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class AdminMcpHandler:
    """管理员 MCP 处理器"""

    mcp_service: McpService
    mcp_import_service: McpImportService

    @admin_login_required
    @permission_required("mcp:read")
    def get_mcp_categories(self):
        """获取 MCP 分类列表。"""
        categories = self.mcp_service.get_mcp_categories()
        return success_json({"categories": categories})

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
    @permission_required("mcp:update")
    def publish(self, provider_id: UUID):
        """发布 MCP 到广场（管理员视角，不校验账号归属）"""
        self.mcp_service.publish_mcp_provider_for_admin(provider_id)
        return success_message("发布MCP成功")

    @admin_login_required
    @permission_required("mcp:update")
    def unpublish(self, provider_id: UUID):
        """取消发布 MCP / 强制下架（管理员视角，不校验账号归属）"""
        self.mcp_service.unpublish_mcp_provider_for_admin(provider_id)
        return success_message("取消发布MCP成功")

    @admin_login_required
    @permission_required("mcp:delete")
    def delete(self, provider_id: UUID):
        """删除 MCP（管理员视角，不校验账号归属）"""
        self.mcp_service.delete_mcp_provider_for_admin(provider_id)
        return success_message("删除MCP成功")

    # ------------------------------------------------------------------ #
    #  导入接口：mcp.json / URL 预览 / URL 导入 / JSON 配置导入              #
    # ------------------------------------------------------------------ #

    @admin_login_required
    @permission_required("mcp:create")
    def import_mcp_json(self):
        """标准 mcp.json 批量导入。

        请求格式：application/json
            - config_json: 标准 mcp.json 文本（必需）
            - overwrite: 是否覆盖已存在的同名 server（可选，默认 false）
        """
        data = request.get_json(force=True, silent=True) or {}
        req = ImportMcpJsonReq(data=data)
        if not req.validate():
            return validate_error_json(req.errors)

        account = self._get_admin_account()
        result = self.mcp_import_service.import_from_mcp_json(
            req.config_json.data,
            account.id,
            overwrite=bool(req.overwrite.data),
        )
        return success_json(result)

    @admin_login_required
    @permission_required("mcp:read")
    def preview_mcp_url(self):
        """URL 预览：调用 tools/list 预览远端工具列表，不写 DB。

        请求格式：application/json
            - url: MCP 服务 URL（必需）
            - transport: 传输方式（可选，默认 http）
            - headers: 请求头列表（可选）
        """
        data = request.get_json(force=True, silent=True) or {}
        req = PreviewMcpUrlReq(data=data)
        if not req.validate():
            return validate_error_json(req.errors)

        result = self.mcp_import_service.preview_tools_from_url(
            req.url.data,
            headers=req.headers.data or [],
            transport=req.transport.data or "http",
        )
        return success_json(result)

    @admin_login_required
    @permission_required("mcp:create")
    def import_mcp_url(self):
        """URL 一键导入：先预览校验可达，再创建 DB 记录。

        请求格式：application/json
            - url: MCP 服务 URL（必需）
            - name: MCP 名称（必需）
            - description: 描述（可选）
            - transport: 传输方式（可选，默认 http）
            - headers: 请求头列表（可选）
            - category: 分类（可选）
            - icon: 图标 URL（可选）
        """
        data = request.get_json(force=True, silent=True) or {}
        req = ImportMcpUrlReq(data=data)
        if not req.validate():
            return validate_error_json(req.errors)

        account = self._get_admin_account()
        provider = self.mcp_import_service.import_from_url(
            req.url.data,
            req.name.data,
            req.description.data or "",
            req.headers.data or [],
            account.id,
            transport=req.transport.data or "http",
            category=req.category.data or "other",
            icon=req.icon.data or "",
        )
        return success_json({"id": str(provider.id)})

    @admin_login_required
    @permission_required("mcp:create")
    def import_mcp_json_config(self):
        """单个 MCP server JSON 配置导入（非标准 mcp.json 格式）。

        请求格式：application/json
            - config_json: 单个 MCP server 的 JSON 配置文本（必需）
            - overwrite: 是否覆盖已存在的同名 provider（可选，默认 false）
        """
        data = request.get_json(force=True, silent=True) or {}
        req = ImportMcpJsonConfigReq(data=data)
        if not req.validate():
            return validate_error_json(req.errors)

        account = self._get_admin_account()
        result = self.mcp_import_service.import_from_json(
            req.config_json.data,
            account.id,
            overwrite=bool(req.overwrite.data),
        )
        return success_json(result)

    def _get_admin_account(self) -> Account:
        """获取管理员绑定的空间账号，作为资源的归属账号"""
        account_id = g.current_admin_user.get("account_id")
        if not account_id:
            raise ValueError("管理员账号未关联空间账号，请先在 RBAC 管理中绑定")
        account = db.session.get(Account, account_id)
        if not account:
            raise ValueError("管理员关联的空间账号不存在")
        return account
