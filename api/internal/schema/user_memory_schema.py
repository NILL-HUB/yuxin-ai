from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import BooleanField, StringField
from wtforms.validators import DataRequired, Length, Optional


class CreateUserMemoryReq(FlaskForm):
    content = StringField("content", validators=[DataRequired(), Length(max=2000)])
    memory_type = StringField("memory_type", default="preference", validators=[Optional(), Length(max=64)])
    confidence = StringField("confidence", default="3", validators=[Optional()])
    created_from = StringField("created_from", default="manual_input", validators=[Optional(), Length(max=64)])


class UpdateUserMemoryReq(FlaskForm):
    content = StringField("content", validators=[Optional(), Length(max=2000)])
    memory_type = StringField("memory_type", validators=[Optional(), Length(max=64)])
    enabled = BooleanField("enabled", default=True, validators=[Optional()])


class UserMemoryResp(Schema):
    id = fields.String()
    owner_account_id = fields.String()
    memory_type = fields.String()
    content = fields.String()
    confidence = fields.Integer()
    status = fields.String()
    created_from = fields.String()
    metadata = fields.Dict(attribute="metadata_")
    created_at = fields.DateTime()
    updated_at = fields.DateTime()


class UserMemoryListResp(Schema):
    items = fields.List(fields.Nested(UserMemoryResp))
    total = fields.Integer()
