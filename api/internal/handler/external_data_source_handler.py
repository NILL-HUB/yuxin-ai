from dataclasses import dataclass
from uuid import UUID

from flask import request
from flask_login import current_user, login_required
from injector import inject

from internal.schema.external_data_source_schema import (
    AuthorizeExternalDataSourceReq,
    CreateExternalDataSourceReq,
    ExternalDataSourceListResp,
    ExternalDataSourceResp,
    ExternalDataSourceSyncResp,
    ListExternalDataSourceReq,
)
from internal.service.external_data_source_service import ExternalDataSourceService
from internal.service.knowledge_base_service import KnowledgeBaseService
from pkg.response import success_json, validate_error_json


@inject
@dataclass
class ExternalDataSourceHandler:
    external_data_source_service: ExternalDataSourceService
    knowledge_base_service: KnowledgeBaseService

    @login_required
    def list(self):
        req = ListExternalDataSourceReq(request.args)
        if not req.validate():
            return validate_error_json(req.errors)
        data_sources = self.external_data_source_service.list_data_sources(
            account=current_user,
            status=req.status.data or "",
        )
        return success_json(
            ExternalDataSourceListResp().dump(
                {"items": data_sources, "total": len(data_sources)}
            )
        )

    @login_required
    def get(self, data_source_id: UUID):
        data_source = self.external_data_source_service.get_data_source(
            data_source_id,
            current_user,
        )
        return success_json(ExternalDataSourceResp().dump(data_source))

    @login_required
    def create(self):
        req = CreateExternalDataSourceReq()
        if not req.validate():
            return validate_error_json(req.errors)
        knowledge_base = self.knowledge_base_service.get_user_content_base(
            UUID(req.knowledge_base_id.data),
            current_user,
        )
        data_source = self.external_data_source_service.create_connection(
            account=current_user,
            knowledge_base=knowledge_base,
            source_type=req.source_type.data,
            source_name=req.source_name.data,
            config=req.config.data,
        )
        return success_json(ExternalDataSourceResp().dump(data_source))

    @login_required
    def authorize(self, data_source_id: UUID):
        req = AuthorizeExternalDataSourceReq()
        if not req.validate():
            return validate_error_json(req.errors)
        data_source = self.external_data_source_service.authorize_data_source(
            data_source_id,
            current_user,
            req.auth_config.data or {},
        )
        return success_json(ExternalDataSourceResp().dump(data_source))

    @login_required
    def sync(self, data_source_id: UUID):
        result = self.external_data_source_service.manual_sync(
            data_source_id,
            current_user,
        )
        return success_json(ExternalDataSourceSyncResp().dump(result))

    @login_required
    def delete(self, data_source_id: UUID):
        self.external_data_source_service.delete_data_source(
            data_source_id,
            current_user,
        )
        return success_json({"deleted": True})
