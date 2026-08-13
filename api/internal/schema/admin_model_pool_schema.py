from wtforms import Form
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
from wtforms.validators import AnyOf, InputRequired, Length, NumberRange, Optional

from internal.schema import DictField, ListField

MODEL_STATUSES = ["active", "disabled"]
KEY_STATUSES = ["active", "disabled", "circuit_open"]
# 档位改为数据库动态管理，不再硬编码 MODEL_TIERS
BILLING_MODES = ["token", "request", "credit"]
MODEL_TYPES = [
    "chat", "embedding", "multimodal",
    "image_generation", "video_generation", "ocr", "tts", "asr", "rerank",
]
COMPATIBLE_APIS = ["openai", "claude"]

# embedding 模型可选维度（与 EmbeddingTableRouter.SUPPORTED_DIMENSIONS 对齐）
EMBEDDING_DIMENSIONS = [512, 768, 1024, 1280, 1536, 2048, 2560, 3072, 4096, 8192]


class GetAdminModelsReq(Form):
    search = StringField("search", default="", validators=[Optional(), Length(max=255)])
    provider = StringField("provider", default="", validators=[Optional(), Length(max=128)])
    tier = StringField("tier", default="", validators=[Optional(), Length(max=64)])
    status = StringField("status", default="", validators=[Optional(), AnyOf(["", *MODEL_STATUSES])])
    model_type = StringField("model_type", default="", validators=[Optional(), AnyOf(["", *MODEL_TYPES])])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=100)])


class CreateAdminModelReq(Form):
    provider = StringField("provider", validators=[InputRequired(), Length(max=128)])
    model_name = StringField("model_name", validators=[InputRequired(), Length(max=255)])
    display_name = StringField("display_name", default="", validators=[Optional(), Length(max=255)])
    tier = StringField("tier", default="2", validators=[Optional(), Length(max=64)])
    capabilities = ListField("capabilities", default=[])
    price_per_1k_tokens = StringField("price_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    max_tokens = IntegerField("max_tokens", default=0, validators=[Optional(), NumberRange(min=0, max=10_000_000)])
    max_input_tokens = IntegerField("max_input_tokens", default=0, validators=[Optional(), NumberRange(min=0, max=10_000_000)])
    max_output_tokens = IntegerField("max_output_tokens", default=0, validators=[Optional(), NumberRange(min=0, max=10_000_000)])
    status = StringField("status", default="active", validators=[Optional(), AnyOf(MODEL_STATUSES)])
    model_type = StringField("model_type", default="chat", validators=[Optional(), AnyOf(MODEL_TYPES)])
    compatible_api = StringField("compatible_api", default="openai", validators=[Optional(), AnyOf(COMPATIBLE_APIS)])
    # embedding_dimension 由后端自动探测（调用 API 探测实际维度），不接受前端传入


class UpdateAdminModelReq(Form):
    provider = StringField("provider", validators=[Optional(), Length(max=128)])
    model_name = StringField("model_name", validators=[Optional(), Length(max=255)])
    display_name = StringField("display_name", validators=[Optional(), Length(max=255)])
    tier = StringField("tier", validators=[Optional(), Length(max=64)])
    capabilities = ListField("capabilities", default=[])
    price_per_1k_tokens = StringField("price_per_1k_tokens", default="0.000000", validators=[Optional(), Length(max=32)])
    max_tokens = IntegerField("max_tokens", default=0, validators=[Optional(), NumberRange(min=0, max=10_000_000)])
    max_input_tokens = IntegerField("max_input_tokens", default=0, validators=[Optional(), NumberRange(min=0, max=10_000_000)])
    max_output_tokens = IntegerField("max_output_tokens", default=0, validators=[Optional(), NumberRange(min=0, max=10_000_000)])
    status = StringField("status", validators=[Optional(), AnyOf(MODEL_STATUSES)])
    model_type = StringField("model_type", validators=[Optional(), AnyOf(MODEL_TYPES)])
    compatible_api = StringField("compatible_api", default="openai", validators=[Optional(), AnyOf(COMPATIBLE_APIS)])
    # embedding_dimension 由后端自动探测，不接受前端传入


class SetAdminModelStatusReq(Form):
    status = StringField("status", validators=[InputRequired(), AnyOf(MODEL_STATUSES)])


class GetAdminModelKeysReq(Form):
    provider = StringField("provider", default="", validators=[Optional(), Length(max=128)])
    status = StringField("status", default="", validators=[Optional(), AnyOf(["", *KEY_STATUSES])])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=100)])


class CreateAdminModelKeyReq(Form):
    provider = StringField("provider", validators=[InputRequired(), Length(max=128)])
    key_alias = StringField("key_alias", validators=[InputRequired(), Length(max=255)])
    key_value = StringField("key_value", validators=[InputRequired(), Length(min=1, max=4096)])
    tenant_quota = StringField("tenant_quota", default="0.0000", validators=[Optional(), Length(max=32)])
    status = StringField("status", default="active", validators=[Optional(), AnyOf(KEY_STATUSES)])


class UpdateAdminModelKeyReq(Form):
    key_alias = StringField("key_alias", validators=[Optional(), Length(max=255)])
    key_value = StringField("key_value", validators=[Optional(), Length(min=1, max=4096)])
    tenant_quota = StringField("tenant_quota", validators=[Optional(), Length(max=32)])
    status = StringField("status", validators=[Optional(), AnyOf(KEY_STATUSES)])


class SetAdminModelKeyStatusReq(Form):
    status = StringField("status", validators=[InputRequired(), AnyOf(KEY_STATUSES)])


class CreateAdminModelTierReq(Form):
    tier_code = StringField("tier_code", validators=[InputRequired(), Length(min=1, max=64)])
    tier_name = StringField("tier_name", validators=[InputRequired(), Length(min=1, max=128)])
    sort_order = IntegerField("sort_order", default=0, validators=[Optional(), NumberRange(min=0, max=9999)])
    allowed_models = ListField("allowed_models", default=[])
    default_model = StringField("default_model", default="", validators=[Optional(), Length(max=255)])
    routing_rules = DictField("routing_rules", default=None)


class UpdateAdminModelTierReq(Form):
    tier_name = StringField("tier_name", validators=[Optional(), Length(min=1, max=128)])
    sort_order = IntegerField("sort_order", validators=[Optional(), NumberRange(min=0, max=9999)])
    allowed_models = ListField("allowed_models", default=[])
    default_model = StringField("default_model", default="", validators=[Optional(), Length(max=255)])
    routing_rules = DictField("routing_rules", default=None)


class UpdateAdminCostPolicyReq(Form):
    model_tier = StringField("model_tier", validators=[Optional(), Length(max=64)])
    max_cost_per_request = StringField("max_cost_per_request", default="", validators=[Optional(), Length(max=32)])
    billing_mode = StringField("billing_mode", validators=[Optional(), AnyOf(BILLING_MODES)])
    upgrade_threshold = StringField("upgrade_threshold", default="", validators=[Optional(), Length(max=32)])


class AdminModelResp(Schema):
    id = fields.String()
    provider = fields.String()
    model_name = fields.String()
    display_name = fields.String()
    description = fields.String(allow_none=True)
    tier = fields.String()
    capabilities = fields.List(fields.String())
    price_per_1k_tokens = fields.String()
    max_tokens = fields.Integer()
    max_input_tokens = fields.Integer()
    max_output_tokens = fields.Integer()
    status = fields.String()
    model_type = fields.String()
    compatible_api = fields.String()
    embedding_dimension = fields.Integer(allow_none=True)
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
    tier_name = fields.String()
    sort_order = fields.Integer()
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
