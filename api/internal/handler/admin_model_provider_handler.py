# api/internal/handler/admin_model_provider_handler.py
from dataclasses import dataclass
from uuid import UUID

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_model_provider_schema import (
    AdminModelProviderOptionResp,
    AdminModelProviderOptionsResp,
    AdminModelProviderPageResp,
    AdminModelProviderResp,
    GetAdminModelProvidersReq,
)
from internal.service.admin_model_provider_service import AdminModelProviderService
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class AdminModelProviderHandler:
    admin_model_provider_service: AdminModelProviderService

    @admin_login_required
    @permission_required("model_provider:read")
    def list_providers(self):
        req = GetAdminModelProvidersReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_model_provider_service.list_providers(
            search=req.search.data,
            status=req.status.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = AdminModelProviderPageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_provider:read")
    def get_provider(self, provider_id: UUID):
        resp = AdminModelProviderResp()
        return success_json(resp.dump(self.admin_model_provider_service.get_provider(provider_id)))

    @admin_login_required
    @permission_required("model_provider:create")
    def create_provider(self):
        payload = request.get_json(silent=True) or {}
        # 必填字段校验
        errors = {}
        if not payload.get("name"):
            errors["name"] = ["This field is required."]
        if not payload.get("label"):
            errors["label"] = ["This field is required."]
        if not payload.get("default_base_url"):
            errors["default_base_url"] = ["This field is required."]
        if errors:
            return validate_error_json(errors)
        # 填充默认值
        payload.setdefault("description", "")
        payload.setdefault("icon", "")
        payload.setdefault("background", "#FFFFFF")
        payload.setdefault("supported_model_types", ["chat"])
        payload.setdefault("status", "active")
        result = self.admin_model_provider_service.create_provider(payload)
        resp = AdminModelProviderResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_provider:update")
    def update_provider(self, provider_id: UUID):
        payload = request.get_json(silent=True) or {}
        # 仅保留允许更新的字段
        allowed_fields = ["label", "description", "icon", "background", "default_base_url", "supported_model_types", "status"]
        update_data = {k: v for k, v in payload.items() if k in allowed_fields}
        if not update_data:
            return validate_error_json({"_": ["No valid fields to update."]})
        result = self.admin_model_provider_service.update_provider(provider_id, update_data)
        resp = AdminModelProviderResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_provider:delete")
    def delete_provider(self, provider_id: UUID):
        self.admin_model_provider_service.delete_provider(provider_id)
        return success_message("删除成功")

    @admin_login_required
    @permission_required("model_provider:update")
    def set_provider_status(self, provider_id: UUID):
        payload = request.get_json(silent=True) or {}
        status = payload.get("status")
        if not status:
            return validate_error_json({"status": ["This field is required."]})
        result = self.admin_model_provider_service.set_provider_status(provider_id, status)
        resp = AdminModelProviderResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_provider:read")
    def list_provider_options(self):
        result = self.admin_model_provider_service.list_provider_options()
        resp = AdminModelProviderOptionsResp()
        return success_json(resp.dump(result))
