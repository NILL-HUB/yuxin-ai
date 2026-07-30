# api/internal/schema/admin_public_ai_feature_schema.py
from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import BooleanField, StringField
from wtforms.validators import AnyOf, Length, Optional

FEATURE_CATEGORIES = ["icon", "memory", "routing", "assistant", "conversation", "general"]


class GetPublicAIFeaturesReq(FlaskForm):
    category = StringField("category", default="", validators=[Optional(), AnyOf(["", *FEATURE_CATEGORIES])])
    enabled = StringField("enabled", default="", validators=[Optional(), AnyOf(["", "true", "false"])])
    model_type = StringField("model_type", default="", validators=[Optional(), Length(max=32)])
    billable = StringField("billable", default="", validators=[Optional()])
    deprecated = StringField("deprecated", default="", validators=[Optional(), AnyOf(["", "true", "false"])])


class UpdatePublicAIFeatureReq(FlaskForm):
    """更新公共 AI 功能配置（只允许编辑绑定模型/开关/降级档位）。"""
    model_config_id = StringField("model_config_id", default="", validators=[Optional(), Length(max=36)])
    enabled = BooleanField("enabled", default=True)
    fallback_tier = StringField("fallback_tier", default="1", validators=[Optional(), Length(max=64)])


class PublicAIFeatureItemSchema(Schema):
    feature_key = fields.String()
    feature_name = fields.String()
    feature_category = fields.String()
    feature_description = fields.String(allow_none=True)
    model_config_id = fields.String(allow_none=True)
    enabled = fields.Boolean()
    fallback_tier = fields.String()
    model_type = fields.String()
    billable = fields.Boolean()
    deprecated = fields.Boolean()
    extra_config = fields.Dict()
    updated_at = fields.DateTime()
    created_at = fields.DateTime()


class PublicAIFeatureListSchema(Schema):
    items = fields.List(fields.Nested(PublicAIFeatureItemSchema))
    total = fields.Integer()
