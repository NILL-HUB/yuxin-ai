from dataclasses import dataclass

from flask import g
from injector import inject

from internal.extension.database_extension import db
from internal.middleware import admin_login_required, permission_required
from internal.model import Account
from internal.schema.upload_file_schema import UploadImageReq
from internal.service import CosService
from pkg.response import success_json, validate_error_json


@inject
@dataclass
class AdminUploadFileHandler:
    """管理员上传文件处理器"""

    cos_service: CosService

    @admin_login_required
    @permission_required("tool:update")
    def upload_image(self):
        """上传图片"""
        req = UploadImageReq()
        if not req.validate():
            return validate_error_json(req.errors)

        account = self._get_admin_account()
        upload_file = self.cos_service.upload_file(req.file.data, True, account)
        image_url = self.cos_service.get_file_url(upload_file.key)

        return success_json({"image_url": image_url})

    def _get_admin_account(self) -> Account:
        """获取管理员绑定的空间账号，作为资源的归属账号"""
        account_id = g.current_admin_user.get("account_id")
        if not account_id:
            raise ValueError("管理员账号未关联空间账号，请先在 RBAC 管理中绑定")
        account = db.session.get(Account, account_id)
        if not account:
            raise ValueError("管理员关联的空间账号不存在")
        return account
