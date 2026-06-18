from flask_wtf import FlaskForm
from marshmallow import Schema, fields, pre_dump
from wtforms import BooleanField, StringField
from wtforms.validators import DataRequired, Length, Optional

from internal.lib.helper import datetime_to_timestamp
from internal.model import KnowledgeBase


class CreateSystemKnowledgeReq(FlaskForm):
    name = StringField("name", validators=[DataRequired("知识库名称不能为空"), Length(max=255)])
    description = StringField("description", default="", validators=[Optional(), Length(max=2000)])


class UpdateSystemKnowledgeReq(FlaskForm):
    name = StringField("name", validators=[Optional(), Length(min=1, max=255)])
    description = StringField("description", default="", validators=[Optional(), Length(max=2000)])
    enabled = BooleanField("enabled", validators=[Optional()])


class SystemKnowledgeResp(Schema):
    id = fields.UUID(dump_default="")
    name = fields.String(dump_default="")
    description = fields.String(dump_default="")
    knowledge_scope = fields.String(dump_default="")
    owner_admin_user_id = fields.UUID(allow_none=True)
    enabled = fields.Boolean(dump_default=True)
    created_at = fields.Integer(dump_default=0)
    updated_at = fields.Integer(dump_default=0)

    @pre_dump
    def process_data(self, data: KnowledgeBase, **kwargs):
        return {
            "id": data.id,
            "name": data.name,
            "description": data.description,
            "knowledge_scope": data.knowledge_scope,
            "owner_admin_user_id": data.owner_admin_user_id,
            "enabled": data.enabled,
            "created_at": datetime_to_timestamp(data.created_at),
            "updated_at": datetime_to_timestamp(data.updated_at),
        }


class SystemKnowledgeListResp(Schema):
    items = fields.List(fields.Nested(SystemKnowledgeResp))
    total = fields.Integer(dump_default=0)
