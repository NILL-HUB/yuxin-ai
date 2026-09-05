from marshmallow import Schema, fields
from wtforms import Form, StringField, validators

BILLING_CONFIG_GLOBAL_RATE = "credits_per_1k_tokens"
BILLING_CONFIG_CREDITS_PER_YUAN = "credits_per_yuan"


class UpsertBillingConfigReq(Form):
    value_numeric = StringField(
        "value_numeric",
        validators=[validators.InputRequired(), validators.Length(max=32)],
    )
    description = StringField("description", default="", validators=[validators.Optional(), validators.Length(max=255)])


class BillingConfigResp(Schema):
    code = fields.String()
    value_numeric = fields.Integer()
    description = fields.String()