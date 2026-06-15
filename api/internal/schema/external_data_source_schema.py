from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import StringField
from wtforms.validators import DataRequired, Length, Optional

from internal.schema import DictField


class CreateExternalDataSourceReq(FlaskForm):
    knowledge_base_id = StringField(
        "knowledge_base_id",
        validators=[DataRequired(), Length(min=1, max=64)],
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


class ExternalDataSourceResp(Schema):
    id = fields.String()
    knowledge_base_id = fields.String()
    source_type = fields.String()
    source_name = fields.String()
    authorization_status = fields.String()
    sync_status = fields.String()


class ExternalDataSourceSyncResp(Schema):
    sync_status = fields.String()
    document_count = fields.Integer()
