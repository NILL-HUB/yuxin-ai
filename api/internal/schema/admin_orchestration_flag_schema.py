from marshmallow import Schema, fields
from wtforms import BooleanField, Form


class UpdateOrchestrationFlagReq(Form):
    enabled = BooleanField("enabled")


class OrchestrationFlagResp(Schema):
    code = fields.String()
    name = fields.String()
    description = fields.String()
    enabled = fields.Boolean()
    risk_level = fields.String()
    fallback_behavior = fields.String()
    updated_by = fields.String(allow_none=True)
