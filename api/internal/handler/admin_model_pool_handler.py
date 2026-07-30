from dataclasses import dataclass
from uuid import UUID

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_model_pool_schema import (
    AdminCostPolicyListResp,
    AdminCostPolicyResp,
    AdminModelKeyPageResp,
    AdminModelKeyResp,
    AdminModelPageResp,
    AdminModelResp,
    AdminModelTierListResp,
    AdminModelTierResp,
    GetAdminModelKeysReq,
    GetAdminModelsReq,
    SetAdminModelKeyStatusReq,
    SetAdminModelStatusReq,
)
from internal.service.admin_model_pool_service import AdminModelPoolService
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class AdminModelPoolHandler:
    admin_model_pool_service: AdminModelPoolService

    @admin_login_required
    @permission_required("model_pool:read")
    def list_models(self):
        req = GetAdminModelsReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_model_pool_service.list_models(
            search=req.search.data,
            provider=req.provider.data,
            tier=req.tier.data,
            status=req.status.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = AdminModelPageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_pool:manage")
    def create_model(self):
        payload = request.get_json(silent=True) or {}
        result = self.admin_model_pool_service.create_model(payload)
        resp = AdminModelResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_pool:read")
    def get_model(self, model_id: UUID):
        resp = AdminModelResp()
        return success_json(resp.dump(self.admin_model_pool_service.get_model(model_id)))

    @admin_login_required
    @permission_required("model_pool:manage")
    def update_model(self, model_id: UUID):
        payload = request.get_json(silent=True) or {}
        result = self.admin_model_pool_service.update_model(model_id, payload)
        resp = AdminModelResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_pool:manage")
    def delete_model(self, model_id: UUID):
        self.admin_model_pool_service.delete_model(model_id)
        return success_message("删除模型配置成功")

    @admin_login_required
    @permission_required("model_pool:manage")
    def set_model_status(self, model_id: UUID):
        req = SetAdminModelStatusReq()
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_model_pool_service.set_model_status(model_id, req.status.data)
        resp = AdminModelResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_pool:read")
    def list_keys(self):
        req = GetAdminModelKeysReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_model_pool_service.list_keys(
            provider=req.provider.data,
            status=req.status.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = AdminModelKeyPageResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_pool:manage")
    def create_key(self):
        payload = request.get_json(silent=True) or {}
        result = self.admin_model_pool_service.create_key(payload)
        resp = AdminModelKeyResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_pool:manage")
    def update_key(self, key_id: UUID):
        payload = request.get_json(silent=True) or {}
        result = self.admin_model_pool_service.update_key(key_id, payload)
        resp = AdminModelKeyResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_pool:manage")
    def delete_key(self, key_id: UUID):
        self.admin_model_pool_service.delete_key(key_id)
        return success_message("删除模型Key成功")

    @admin_login_required
    @permission_required("model_pool:manage")
    def set_key_status(self, key_id: UUID):
        req = SetAdminModelKeyStatusReq()
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_model_pool_service.set_key_status(key_id, req.status.data)
        resp = AdminModelKeyResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_pool:read")
    def list_tier_policies(self):
        result = self.admin_model_pool_service.list_tier_policies()
        resp = AdminModelTierListResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_pool:manage")
    def create_tier_policy(self):
        payload = request.get_json(silent=True) or {}
        result = self.admin_model_pool_service.create_tier_policy(payload)
        resp = AdminModelTierResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_pool:manage")
    def update_tier_policy(self, tier_code: str):
        payload = request.get_json(silent=True) or {}
        result = self.admin_model_pool_service.update_tier_policy(tier_code, payload)
        resp = AdminModelTierResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_pool:manage")
    def delete_tier_policy(self, tier_code: str):
        self.admin_model_pool_service.delete_tier_policy(tier_code)
        return success_message("删除档位策略成功")

    @admin_login_required
    @permission_required("model_pool:read")
    def list_cost_policies(self):
        result = self.admin_model_pool_service.list_cost_policies()
        resp = AdminCostPolicyListResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_pool:manage")
    def create_cost_policy(self):
        payload = request.get_json(silent=True) or {}
        result = self.admin_model_pool_service.create_cost_policy(payload)
        resp = AdminCostPolicyResp()
        return success_json(resp.dump(result))

    @admin_login_required
    @permission_required("model_pool:manage")
    def update_cost_policy(self, policy_id: UUID):
        payload = request.get_json(silent=True) or {}
        result = self.admin_model_pool_service.update_cost_policy(policy_id, payload)
        resp = AdminCostPolicyResp()
        return success_json(resp.dump(result))
