from dataclasses import dataclass

from flask import request
from injector import inject

from internal.exception import UnauthorizedException
from internal.schema.admin_auth_schema import AdminChangePasswordReq, AdminPasswordLoginReq, AdminPasswordLoginResp
from internal.service.admin_user_service import AdminUserService
from pkg.response import success_json, success_message, validate_error_json


@inject
@dataclass
class AdminAuthHandler:
    admin_user_service: AdminUserService

    def login(self):
        req = AdminPasswordLoginReq()
        if not req.validate():
            return validate_error_json(req.errors)
        identifier = req.identifier.data or req.email.data
        if not identifier:
            return validate_error_json({"identifier": ["账号不能为空"]})
        credential = self.admin_user_service.password_login(identifier, req.password.data)
        resp = AdminPasswordLoginResp()
        return success_json(resp.dump(credential))

    def me(self):
        token = self._extract_bearer_token()
        return success_json(self.admin_user_service.get_current_admin_from_token(token))

    def logout(self):
        token = self._extract_bearer_token()
        self.admin_user_service.logout(token)
        return success_message("退出登录成功")

    def change_password(self):
        token = self._extract_bearer_token()
        current_admin = self.admin_user_service.get_current_admin_from_token(token)
        req = AdminChangePasswordReq()
        if not req.validate():
            return validate_error_json(req.errors)
        return success_json(self.admin_user_service.change_own_password(
            current_admin["id"],
            current_password=req.current_password.data,
            new_password=req.new_password.data,
        ))

    @staticmethod
    def _extract_bearer_token() -> str:
        auth_header = request.headers.get("Authorization", "")
        if " " not in auth_header:
            raise UnauthorizedException("管理员接口需要授权才能访问")
        token_type, token = auth_header.split(None, 1)
        if token_type.lower() != "bearer" or not token:
            raise UnauthorizedException("管理员接口需要授权才能访问")
        return token
