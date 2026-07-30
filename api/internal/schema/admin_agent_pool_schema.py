from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
from wtforms.validators import AnyOf, InputRequired, Length, NumberRange, Optional, UUID

from internal.schema import DictField

HEALTH_STATUSES = ["healthy", "degraded", "offline", "unknown"]
ENABLED_VALUES = ["true", "false"]


class GetAdminAgentPoolConfigsReq(FlaskForm):
    keyword = StringField("keyword", default="", validators=[Optional(), Length(max=255)])
    enabled = StringField("enabled", default="", validators=[Optional(), AnyOf(["", *ENABLED_VALUES])])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=100)])


class CreateAdminAgentPoolConfigReq(FlaskForm):
    app_id = StringField("app_id", validators=[InputRequired(), UUID(message="app_id必须为UUID格式")])
    enabled = StringField("enabled", default="true", validators=[Optional(), AnyOf(ENABLED_VALUES)])
    metadata_ = DictField("metadata_", default=None)


class UpdateAdminAgentPoolConfigReq(FlaskForm):
    enabled = StringField("enabled", validators=[Optional(), AnyOf(ENABLED_VALUES)])
    metadata_ = DictField("metadata_", default=None)


class SetAdminAgentPoolConfigStatusReq(FlaskForm):
    enabled = StringField("enabled", validators=[InputRequired(), AnyOf(ENABLED_VALUES)])


class AdminAgentPoolConfigResp(Schema):
    id = fields.String()
    app_id = fields.String()
    enabled = fields.Boolean()
    health_status = fields.String()
    last_health_check_at = fields.Integer(allow_none=True)
    metadata = fields.Dict()
    preset_prompt_summary = fields.String(allow_none=True)
    created_at = fields.Integer(allow_none=True)
    updated_at = fields.Integer(allow_none=True)


class AdminAgentPoolConfigPageResp(Schema):
    list = fields.List(fields.Nested(AdminAgentPoolConfigResp))
    paginator = fields.Dict()


class AdminAgentPoolStatsItemResp(Schema):
    total = fields.Integer()
    enabled = fields.Integer()
    healthy = fields.Integer()


class AdminAgentPoolStatsResp(Schema):
    list = fields.List(fields.Nested(AdminAgentPoolStatsItemResp))
