from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
from wtforms.validators import AnyOf, InputRequired, Length, NumberRange, Optional

from internal.schema import DictField, ListField

MODEL_STATUSES = ["active", "disabled"]
KEY_STATUSES = ["active", "disabled", "circuit_open"]
MODEL_TIERS = ["cheap", "standard", "strong"]
BILLING_MODES = ["token", "request", "credit"]


class GetAdminModelsReq(FlaskForm):
    search = StringField("search", default="", validators=[Optional(), Length(max=255)])
    provider = StringField("provider", default="", validators=[Optional(), Length(max=128)])
    tier = StringField("tier", default="", validators=[Optional(), AnyOf(["", *MODEL_TIERS])])
    status = StringField("status", default="", validators=[Optional(), AnyOf(["", *MODEL_STATUSES])])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=100)])


class CreateAdminModelReq(FlaskForm):
    provider = StringField("provider", validators=[InputRequired(), Length(max=128)])
    model_name = StringField("model_name", validators=[InputRequired(), Length(max=255)])
    display_name = StringField("display_name", default="", validators=[Optional(), Length(max=255)])
    tier = StringField("tier", default="standard", validators=[Optional(), AnyOf(MODEL_TIERS)])
    capabilities = ListField("capabilities", default=[])
    price_per_1k_tokens = StringField("price_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    max_tokens = IntegerField("max_tokens", default=0, validators=[Optional(), NumberRange(min=0, max=10_000_000)])
    status = StringField("status", default="active", validators=[Optional(), AnyOf(MODEL_STATUSES)])
    base_url = StringField("base_url", default="", validators=[Optional(), Length(max=512)])


class UpdateAdminModelReq(FlaskForm):
    provider = StringField("provider", validators=[Optional(), Length(max=128)])
    model_name = StringField("model_name", validators=[Optional(), Length(max=255)])
    display_name = StringField("display_name", validators=[Optional(), Length(max=255)])
    tier = StringField("tier", validators=[Optional(), AnyOf(MODEL_TIERS)])
    capabilities = ListField("capabilities", default=[])
    price_per_1k_tokens = StringField("price_per_1k_tokens", validators=[Optional(), Length(max=32)])
    max_tokens = IntegerField("max_tokens", validators=[Optional(), NumberRange(min=0, max=10_000_000)])
    status = StringField("status", validators=[Optional(), AnyOf(MODEL_STATUSES)])
    base_url = StringField("base_url", default="", validators=[Optional(), Length(max=512)])


class SetAdminModelStatusReq(FlaskForm):
    status = StringField("status", validators=[InputRequired(), AnyOf(MODEL_STATUSES)])


class GetAdminModelKeysReq(FlaskForm):
    provider = StringField("provider", default="", validators=[Optional(), Length(max=128)])
    status = StringField("status", default="", validators=[Optional(), AnyOf(["", *KEY_STATUSES])])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=100)])


class CreateAdminModelKeyReq(FlaskForm):
    provider = StringField("provider", validators=[InputRequired(), Length(max=128)])
    key_alias = StringField("key_alias", validators=[InputRequired(), Length(max=255)])
    key_value = StringField("key_value", validators=[InputRequired(), Length(min=1, max=4096)])
    tenant_quota = StringField("tenant_quota", default="0.0000", validators=[Optional(), Length(max=32)])
    status = StringField("status", default="active", validators=[Optional(), AnyOf(KEY_STATUSES)])


class UpdateAdminModelKeyReq(FlaskForm):
    key_alias = StringField("key_alias", validators=[Optional(), Length(max=255)])
    key_value = StringField("key_value", validators=[Optional(), Length(min=1, max=4096)])
    tenant_quota = StringField("tenant_quota", validators=[Optional(), Length(max=32)])
    status = StringField("status", validators=[Optional(), AnyOf(KEY_STATUSES)])


class SetAdminModelKeyStatusReq(FlaskForm):
    status = StringField("status", validators=[InputRequired(), AnyOf(KEY_STATUSES)])


class UpdateAdminModelTierReq(FlaskForm):
    allowed_models = ListField("allowed_models", default=[])
    default_model = StringField("default_model", default="", validators=[Optional(), Length(max=255)])
    routing_rules = DictField("routing_rules", default=None)


class UpdateAdminCostPolicyReq(FlaskForm):
    model_tier = StringField("model_tier", validators=[Optional(), AnyOf(MODEL_TIERS)])
    max_cost_per_request = StringField("max_cost_per_request", validators=[Optional(), Length(max=32)])
    billing_mode = StringField("billing_mode", validators=[Optional(), AnyOf(BILLING_MODES)])
    upgrade_threshold = StringField("upgrade_threshold", validators=[Optional(), Length(max=32)])


class AdminModelResp(Schema):
    id = fields.String()
    provider = fields.String()
    model_name = fields.String()
    display_name = fields.String()
    tier = fields.String()
    capabilities = fields.List(fields.String())
    price_per_1k_tokens = fields.String()
    max_tokens = fields.Integer()
    status = fields.String()
    base_url = fields.String(allow_none=True)
    created_at = fields.Integer(allow_none=True)
    updated_at = fields.Integer(allow_none=True)


class AdminModelPageResp(Schema):
    list = fields.List(fields.Nested(AdminModelResp))
    paginator = fields.Dict()


class AdminModelKeyResp(Schema):
    id = fields.String()
    provider = fields.String()
    key_alias = fields.String()
    key_mask = fields.String()
    tenant_quota = fields.String()
    status = fields.String()
    failure_count = fields.Integer()
    created_at = fields.Integer(allow_none=True)
    updated_at = fields.Integer(allow_none=True)


class AdminModelKeyPageResp(Schema):
    list = fields.List(fields.Nested(AdminModelKeyResp))
    paginator = fields.Dict()


class AdminModelTierResp(Schema):
    id = fields.String()
    tier_code = fields.String()
    allowed_models = fields.List(fields.String())
    default_model = fields.String()
    routing_rules = fields.Dict()
    created_at = fields.Integer(allow_none=True)
    updated_at = fields.Integer(allow_none=True)


class AdminModelTierListResp(Schema):
    list = fields.List(fields.Nested(AdminModelTierResp))


class AdminCostPolicyResp(Schema):
    id = fields.String()
    policy_name = fields.String()
    model_tier = fields.String()
    max_cost_per_request = fields.String()
    billing_mode = fields.String()
    upgrade_threshold = fields.String()
    created_at = fields.Integer(allow_none=True)
    updated_at = fields.Integer(allow_none=True)


class AdminCostPolicyListResp(Schema):
    list = fields.List(fields.Nested(AdminCostPolicyResp))
