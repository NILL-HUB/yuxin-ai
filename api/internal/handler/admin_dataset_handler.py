from dataclasses import dataclass

from flask import request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_dataset_schema import AdminDatasetPageResp, GetAdminDatasetsReq
from internal.service.admin_dataset_service import AdminDatasetService
from pkg.response import success_json, validate_error_json


@inject
@dataclass
class AdminDatasetHandler:
    """处理后台数据集列表请求。"""

    admin_dataset_service: AdminDatasetService

    @admin_login_required
    @permission_required("dataset:read")
    def list(self):
        """返回后台真实数据集分页列表。"""
        req = GetAdminDatasetsReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        result = self.admin_dataset_service.list_datasets(
            search_word=req.search_word.data,
            current_page=req.current_page.data,
            page_size=req.page_size.data,
        )
        resp = AdminDatasetPageResp()
        return success_json(resp.dump(result))
