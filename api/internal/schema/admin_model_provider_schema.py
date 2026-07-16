# api/internal/schema/admin_model_provider_schema.py
from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
from wtforms.validators import AnyOf, InputRequired, Length, Optional, URL

from internal.schema import DictField, ListField

PROVIDER_STATUSES = ["active", "disabled"]
MODEL_TYPES = [
    "chat", "completion", "embedding", "multimodal",
    "image_generation", "video_generation", "ocr", "tts", "asr", "rerank",
]
COMPATIBLE_APIS = ["openai", "claude"]


class GetAdminModelProvidersReq(FlaskForm):
    search = StringField("search", default="", validators=[Optional(), Length(max=255)])
    status = StringField("status", default="", validators=[Optional(), AnyOf(["", *PROVIDER_STATUSES])])
    current_page = IntegerField("current_page", default=1, validators=[Optional()])
    page_size = IntegerField("page_size", default=20, validators=[Optional()])


class CreateAdminModelProviderReq(FlaskForm):
    name = StringField("name", validators=[InputRequired(), Length(min=1, max=128)])
    label = StringField("label", validators=[InputRequired(), Length(min=1, max=255)])
    description = StringField("description", default="", validators=[Optional(), Length(max=2000)])
    icon = StringField("icon", default="", validators=[Optional(), Length(max=512)])
    background = StringField("background", default="#FFFFFF", validators=[Optional(), Length(max=32)])
    default_base_url = StringField("default_base_url", validators=[InputRequired(), Length(min=1, max=512)])
    supported_model_types = ListField(
        StringField("supported_model_types", validators=[Optional(), AnyOf(MODEL_TYPES)])
    )
    status = StringField("status", default="active", validators=[Optional(), AnyOf(PROVIDER_STATUSES)])


class UpdateAdminModelProviderReq(FlaskForm):
    label = StringField("label", validators=[Optional(), Length(min=1, max=255)])
    description = StringField("description", validators=[Optional(), Length(max=2000)])
    icon = StringField("icon", validators=[Optional(), Length(max=512)])
    background = StringField("background", validators=[Optional(), Length(max=32)])
    default_base_url = StringField("default_base_url", validators=[Optional(), Length(min=1, max=512)])
    supported_model_types = ListField(
        StringField("supported_model_types", validators=[Optional(), AnyOf(MODEL_TYPES)])
    )
    status = StringField("status", validators=[Optional(), AnyOf(PROVIDER_STATUSES)])


class SetAdminModelProviderStatusReq(FlaskForm):
    status = StringField("status", validators=[InputRequired(), AnyOf(PROVIDER_STATUSES)])


class AdminModelProviderResp(Schema):
    id = fields.String()
    name = fields.String()
    label = fields.String()
    description = fields.String()
    icon = fields.String()
    background = fields.String()
    default_base_url = fields.String()
    supported_model_types = fields.List(fields.String())
    status = fields.String()
    model_count = fields.Integer()
    created_at = fields.Integer()
    updated_at = fields.Integer()


class AdminModelProviderPageResp(Schema):
    list = fields.List(fields.Nested(AdminModelProviderResp))
    paginator = fields.Dict()


class AdminModelProviderOptionResp(Schema):
    id = fields.String()
    name = fields.String()
    label = fields.String()
    default_base_url = fields.String()
    supported_model_types = fields.List(fields.String())


class AdminModelProviderOptionsResp(Schema):
    options = fields.List(fields.Nested(AdminModelProviderOptionResp))
