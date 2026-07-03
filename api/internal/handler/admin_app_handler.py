from dataclasses import dataclass
from uuid import UUID

from flask import g, request
from injector import inject

from internal.extension.database_extension import db
from internal.middleware import admin_login_required, permission_required
from internal.model import Account
from internal.schema.admin_app_schema import (
    AdminAppPageResp,
    AdminAppResp,
    BatchDeleteAppsReq,
    BatchOfflineAppsReq,
    BatchOperationResp,
    GetAdminAppsReq,
    UpdateAdminAppReq,
)
from internal.schema.app_schema import CreateAppReq
from internal.service import AppService
from internal.service.admin_app_service import AdminAppService
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class AdminAppHandler:
    admin_app_service: AdminAppService
    app_service: AppService

    @admin_login_required
    @permission_required("app:read")
    def list(self):
        req = GetAdminAppsReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_app_service.list_apps(
            search=req.search.data,
            status=req.status.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = AdminAppPageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("app:read")
    def get(self, app_id: UUID):
        resp = AdminAppResp()
        return success_json(resp.dump(self.admin_app_service.get_app(app_id)))

    @admin_login_required
    @permission_required("app:create")
    def create(self):
        """创建应用（归属到管理员绑定的空间账号，复用空间端服务）"""
        req = CreateAppReq()
        if not req.validate():
            return validate_error_json(req.errors)

        account = self._get_admin_account()
        app = self.app_service.create_app(req, account)
        return success_json({"id": str(app.id)})

    @admin_login_required
    @permission_required("app:update")
    def update(self, app_id: UUID):
        req = UpdateAdminAppReq()
        if not req.validate():
            return validate_error_json(req.errors)
        payload = request.get_json(silent=True) or {}
        result = self.admin_app_service.update_app(
            app_id,
            status=req.status.data,
            is_public=payload.get("is_public") if "is_public" in payload else None,
            agent_metadata=payload.get("agent_metadata") if "agent_metadata" in payload else None,
        )
        resp = AdminAppResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("app:delete")
    def delete(self, app_id: UUID):
        """删除应用（管理员视角，不校验账号归属）"""
        self.app_service.delete_app_for_admin(app_id)
        return success_message("删除Agent智能体应用成功")

    @admin_login_required
    @permission_required("app:read")
    def get_draft_app_config(self, app_id: UUID):
        """获取应用草稿配置（管理员视角，复用空间端服务）"""
        draft_app_config = self.app_service.get_draft_app_config_for_admin(app_id)
        return success_json(draft_app_config)

    @admin_login_required
    @permission_required("app:update")
    def update_draft_app_config(self, app_id: UUID):
        """保存应用草稿配置（管理员视角，复用空间端服务）"""
        draft_app_config = request.get_json(force=True, silent=True) or {}
        self.app_service.update_draft_app_config_for_admin(app_id, draft_app_config)
        return success_message("更新应用草稿配置成功")

    @admin_login_required
    @permission_required("app:update")
    def offline(self, app_id: UUID):
        self.admin_app_service.offline_app(app_id)
        return success_message("下架应用成功")

    @admin_login_required
    @permission_required("app:update")
    def batch_offline(self):
        """批量下架应用"""
        req = BatchOfflineAppsReq()
        if not req.validate():
            return validate_error_json(req.errors)
        app_ids = req.app_ids.data or []
        if not isinstance(app_ids, list) or len(app_ids) == 0:
            return validate_error_json({"app_ids": ["应用ID列表不能为空"]})
        result = self.admin_app_service.batch_offline_apps([UUID(aid) for aid in app_ids])
        resp = BatchOperationResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("app:delete")
    def batch_delete(self):
        """批量删除应用"""
        req = BatchDeleteAppsReq()
        if not req.validate():
            return validate_error_json(req.errors)
        app_ids = req.app_ids.data or []
        if not isinstance(app_ids, list) or len(app_ids) == 0:
            return validate_error_json({"app_ids": ["应用ID列表不能为空"]})
        result = self.admin_app_service.batch_delete_apps([UUID(aid) for aid in app_ids])
        resp = BatchOperationResp()
        return success_json(resp.dump(result))

    def _get_admin_account(self) -> Account:
        """获取管理员绑定的空间账号，作为资源的归属账号"""
        account_id = g.current_admin_user.get("account_id")
        if not account_id:
            raise ValueError("管理员账号未关联空间账号，请先在 RBAC 管理中绑定")
        account = db.session.get(Account, account_id)
        if not account:
            raise ValueError("管理员关联的空间账号不存在")
        return account
