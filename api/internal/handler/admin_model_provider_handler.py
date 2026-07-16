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
    CreateAdminModelProviderReq,
    GetAdminModelProvidersReq,
    SetAdminModelProviderStatusReq,
    UpdateAdminModelProviderReq,
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
        req = CreateAdminModelProviderReq(request.form)
        if not req.validate():
            return validate_error_json(req.errors)
        payload = {
            "name": req.name.data,
            "label": req.label.data,
            "description": req.description.data or "",
            "icon": req.icon.data or "",
            "background": req.background.data or "#FFFFFF",
            "default_base_url": req.default_base_url.data,
            "supported_model_types": req.supported_model_types.data or ["chat"],
            "status": req.status.data or "active",
        }
        result = self.admin_model_provider_service.create_provider(payload)
        resp = AdminModelProviderResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_provider:update")
    def update_provider(self, provider_id: UUID):
        req = UpdateAdminModelProviderReq(request.form)
        if not req.validate():
            return validate_error_json(req.errors)
        payload = {}
        for field in ["label", "description", "icon", "background", "default_base_url", "supported_model_types", "status"]:
            if hasattr(req, field) and getattr(req, field).data is not None:
                payload[field] = getattr(req, field).data
        result = self.admin_model_provider_service.update_provider(provider_id, payload)
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
        req = SetAdminModelProviderStatusReq(request.form)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_model_provider_service.set_provider_status(provider_id, req.status.data)
        resp = AdminModelProviderResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_provider:read")
    def list_provider_options(self):
        result = self.admin_model_provider_service.list_provider_options()
        resp = AdminModelProviderOptionsResp()
        return success_json(resp.dump(result))
