from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
from wtforms.validators import AnyOf, InputRequired, Length, NumberRange, Optional

from internal.schema import DictField, ListField

PRIMARY_POOLS = ["tenant", "system", "global"]
RISK_LEVELS = ["low", "medium", "high"]
MODEL_TIERS = ["cheap", "balanced", "strong"]
HEALTH_STATUSES = ["healthy", "degraded", "offline", "unknown"]
ENABLED_VALUES = ["true", "false"]


class GetAdminAgentPoolConfigsReq(FlaskForm):
    keyword = StringField("keyword", default="", validators=[Optional(), Length(max=255)])
    pool = StringField("pool", default="", validators=[Optional(), AnyOf(["", *PRIMARY_POOLS])])
    enabled = StringField("enabled", default="", validators=[Optional(), AnyOf(["", *ENABLED_VALUES])])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=50)])


class CreateAdminAgentPoolConfigReq(FlaskForm):
    app_id = StringField("app_id", validators=[InputRequired(), Length(max=128)])
    primary_pool = StringField("primary_pool", default="tenant", validators=[Optional(), AnyOf(PRIMARY_POOLS)])
    secondary_pools = ListField("secondary_pools", default=[])
    risk_level = StringField("risk_level", default="medium", validators=[Optional(), AnyOf(RISK_LEVELS)])
    model_tier = StringField("model_tier", default="balanced", validators=[Optional(), AnyOf(MODEL_TIERS)])
    model_id = StringField("model_id", default="", validators=[Optional(), Length(max=128)])
    routing_priority = IntegerField("routing_priority", default=100, validators=[Optional(), NumberRange(min=0, max=9999)])
    enabled = StringField("enabled", default="true", validators=[Optional(), AnyOf(ENABLED_VALUES)])
    metadata_ = DictField("metadata_", default=None)


class UpdateAdminAgentPoolConfigReq(FlaskForm):
    primary_pool = StringField("primary_pool", validators=[Optional(), AnyOf(PRIMARY_POOLS)])
    secondary_pools = ListField("secondary_pools", default=[])
    risk_level = StringField("risk_level", validators=[Optional(), AnyOf(RISK_LEVELS)])
    model_tier = StringField("model_tier", validators=[Optional(), AnyOf(MODEL_TIERS)])
    model_id = StringField("model_id", validators=[Optional(), Length(max=128)])
    routing_priority = IntegerField("routing_priority", validators=[Optional(), NumberRange(min=0, max=9999)])
    enabled = StringField("enabled", validators=[Optional(), AnyOf(ENABLED_VALUES)])
    metadata_ = DictField("metadata_", default=None)


class SetAdminAgentPoolConfigStatusReq(FlaskForm):
    enabled = StringField("enabled", validators=[InputRequired(), AnyOf(ENABLED_VALUES)])


class AdminAgentPoolConfigResp(Schema):
    id = fields.String()
    app_id = fields.String()
    primary_pool = fields.String()
    secondary_pools = fields.List(fields.String())
    risk_level = fields.String()
    model_tier = fields.String()
    model_id = fields.String(allow_none=True)
    routing_priority = fields.Integer()
    enabled = fields.Boolean()
    health_status = fields.String()
    last_health_check_at = fields.Integer(allow_none=True)
    metadata = fields.Dict()
    created_at = fields.Integer(allow_none=True)
    updated_at = fields.Integer(allow_none=True)


class AdminAgentPoolConfigPageResp(Schema):
    list = fields.List(fields.Nested(AdminAgentPoolConfigResp))
    paginator = fields.Dict()


class AdminAgentPoolStatsItemResp(Schema):
    pool = fields.String()
    total = fields.Integer()
    enabled = fields.Integer()
    healthy = fields.Integer()


class AdminAgentPoolStatsResp(Schema):
    list = fields.List(fields.Nested(AdminAgentPoolStatsItemResp))
