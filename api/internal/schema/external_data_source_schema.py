from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import StringField
from wtforms.validators import DataRequired, Length, Optional

from internal.schema import DictField


class CreateExternalDataSourceReq(FlaskForm):
    knowledge_base_id = StringField(
        "knowledge_base_id",
        validators=[Optional(), Length(min=1, max=64)],
    )
    source_type = StringField(
        "source_type",
        validators=[DataRequired(), Length(min=1, max=64)],
    )
    source_name = StringField(
        "source_name",
        validators=[DataRequired(), Length(min=1, max=255)],
    )
    config = DictField("config", default={}, validators=[Optional()])


class AuthorizeExternalDataSourceReq(FlaskForm):
    auth_config = DictField("auth_config", default={}, validators=[Optional()])


class ListExternalDataSourceReq(FlaskForm):
    status = StringField(
        "status",
        default="",
        validators=[Optional(), Length(max=64)],
    )


class ExternalDataSourceResp(Schema):
    id = fields.String()
    knowledge_base_id = fields.String()
    source_type = fields.String()
    source_name = fields.String()
    authorization_status = fields.String()
    sync_status = fields.String()
    sync_cursor = fields.String()
    last_synced_at = fields.DateTime()
    last_error = fields.String()
    config = fields.Dict()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()


class ExternalDataSourceListResp(Schema):
    items = fields.List(fields.Nested(ExternalDataSourceResp))
    total = fields.Integer()


class ExternalDataSourceSyncResp(Schema):
    sync_status = fields.String()
    document_count = fields.Integer()
    segment_count = fields.Integer()
    last_error = fields.String()
