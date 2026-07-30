from flask_wtf import FlaskForm
from marshmallow import Schema, fields, pre_dump
from wtforms import StringField
from wtforms.validators import AnyOf, DataRequired, Length, Optional

from internal.entity.knowledge_entity import (
    ExternalAuthorizationStatus,
    ExternalSourceType,
    ExternalSyncStatus,
    KnowledgeCreatedFrom,
    KnowledgeScope,
    OperationContext,
    VisibilityScope,
)
from internal.lib.helper import datetime_to_timestamp
from internal.model import KnowledgeBase


class CreateKnowledgeBaseReq(FlaskForm):
    name = StringField("name", validators=[DataRequired("知识库名称不能为空"), Length(max=100)])
    description = StringField("description", default="", validators=[Optional(), Length(max=2000)])
    knowledge_scope = StringField("knowledge_scope", validators=[
        DataRequired("知识库作用域不能为空"),
        AnyOf([item.value for item in KnowledgeScope], message="知识库作用域格式错误"),
    ])
    operation_context = StringField("operation_context", default=OperationContext.USER.value, validators=[
        AnyOf([item.value for item in OperationContext], message="操作上下文格式错误"),
    ])
    visibility_scope = StringField("visibility_scope", default=VisibilityScope.PRIVATE.value, validators=[
        AnyOf([item.value for item in VisibilityScope], message="可见范围格式错误"),
    ])
    created_from = StringField("created_from", default=KnowledgeCreatedFrom.MANUAL_UPLOAD.value, validators=[
        AnyOf([item.value for item in KnowledgeCreatedFrom], message="创建来源格式错误"),
    ])


class CreateExternalDataSourceReq(FlaskForm):
    source_type = StringField("source_type", validators=[
        DataRequired("外部数据源类型不能为空"),
        AnyOf([item.value for item in ExternalSourceType], message="外部数据源类型格式错误"),
    ])
    source_name = StringField("source_name", default="", validators=[Optional(), Length(max=255)])
    authorization_status = StringField("authorization_status", default=ExternalAuthorizationStatus.PENDING.value, validators=[
        AnyOf([item.value for item in ExternalAuthorizationStatus], message="授权状态格式错误"),
    ])
    sync_status = StringField("sync_status", default=ExternalSyncStatus.IDLE.value, validators=[
        AnyOf([item.value for item in ExternalSyncStatus], message="同步状态格式错误"),
    ])


class KnowledgeBaseResp(Schema):
    id = fields.UUID(dump_default="")
    name = fields.String(dump_default="")
    description = fields.String(dump_default="")
    knowledge_scope = fields.String(dump_default="")
    owner_account_id = fields.UUID(allow_none=True)
    owner_admin_user_id = fields.UUID(allow_none=True)
    operation_context = fields.String(dump_default="")
    visibility_scope = fields.String(dump_default="")
    target_tenant_id = fields.UUID(allow_none=True)
    target_project_id = fields.UUID(allow_none=True)
    created_from = fields.String(dump_default="")
    updated_at = fields.Integer(dump_default=0)
    created_at = fields.Integer(dump_default=0)

    @pre_dump
    def process_data(self, data: KnowledgeBase, **kwargs):
        return {
            "id": data.id,
            "name": data.name,
            "description": data.description,
            "knowledge_scope": data.knowledge_scope,
            "owner_account_id": data.owner_account_id,
            "owner_admin_user_id": data.owner_admin_user_id,
            "operation_context": data.operation_context,
            "visibility_scope": data.visibility_scope,
            "target_tenant_id": data.target_tenant_id,
            "target_project_id": data.target_project_id,
            "created_from": data.created_from,
            "updated_at": datetime_to_timestamp(data.updated_at),
            "created_at": datetime_to_timestamp(data.created_at),
        }


class UserMemoryResp(Schema):
    id = fields.UUID(dump_default="")
    owner_account_id = fields.UUID(dump_default="")
    memory_type = fields.String(dump_default="")
    content = fields.String(dump_default="")
    confidence = fields.Integer(dump_default=0)
    status = fields.String(dump_default="")
    created_from = fields.String(dump_default="")


class ExternalDataSourceResp(Schema):
    id = fields.UUID(dump_default="")
    owner_account_id = fields.UUID(allow_none=True)
    owner_admin_user_id = fields.UUID(allow_none=True)
    knowledge_base_id = fields.UUID(allow_none=True)
    source_type = fields.String(dump_default="")
    source_name = fields.String(dump_default="")
    authorization_status = fields.String(dump_default="")
    sync_status = fields.String(dump_default="")
