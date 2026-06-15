from dataclasses import dataclass
from uuid import UUID

from flask_login import current_user, login_required
from injector import inject

from internal.schema.external_data_source_schema import (
    CreateExternalDataSourceReq,
    ExternalDataSourceResp,
    ExternalDataSourceSyncResp,
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
    def sync(self, data_source_id: UUID):
        result = self.external_data_source_service.manual_sync(
            data_source_id,
            current_user,
        )
        return success_json(ExternalDataSourceSyncResp().dump(result))
