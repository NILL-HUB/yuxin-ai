from wtforms import Form
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
from wtforms.validators import AnyOf, InputRequired, Length, NumberRange, Optional

from internal.schema import ListField

RISK_LEVELS = ["low", "medium", "high", "critical"]
SOURCE_TYPES = ["api_tool", "mcp", "skill", "builtin", "knowledge", "workflow", "agent_binding"]
VISIBILITIES = ["private", "tenant", "public"]
INVOCATION_STATUSES = ["success", "failed", "blocked", "timeout"]


class GetAdminToolGovernancePoliciesReq(Form):
    source_type = StringField("source_type", default="", validators=[Optional(), AnyOf(["", *SOURCE_TYPES])])
    risk_level = StringField("risk_level", default="", validators=[Optional(), AnyOf(["", *RISK_LEVELS])])
    visibility = StringField("visibility", default="", validators=[Optional(), AnyOf(["", *VISIBILITIES])])
    enabled = StringField("enabled", default="", validators=[Optional(), AnyOf(["", "true", "false"])])
    keyword = StringField("keyword", default="", validators=[Optional(), Length(max=255)])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=100)])


class BatchUpdateToolGovernanceRiskReq(Form):
    policy_ids = ListField("policy_ids", validators=[InputRequired()])
    risk_level = StringField("risk_level", validators=[InputRequired(), AnyOf(RISK_LEVELS)])


class GetAdminToolGovernanceAuditReq(Form):
    tool_id = StringField("tool_id", default="", validators=[Optional(), Length(max=128)])
    status = StringField("status", default="", validators=[Optional(), AnyOf(["", *INVOCATION_STATUSES])])
    start_date = StringField("start_date", default="", validators=[Optional(), Length(max=32)])
    end_date = StringField("end_date", default="", validators=[Optional(), Length(max=32)])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=100)])


class AdminToolGovernancePolicyResp(Schema):
    id = fields.String()
    tool_id = fields.String()
    tool_name = fields.String()
    source_type = fields.String()
    provider_id = fields.String()
    risk_level = fields.String()
    visibility = fields.String()
    allowed_pools = fields.List(fields.String())
    enabled = fields.Boolean()
    max_invocations_per_request = fields.Integer()
    cooldown_seconds = fields.Integer()
    require_confirmation = fields.Boolean()
    description = fields.String()
    created_at = fields.Integer(allow_none=True)
    updated_at = fields.Integer(allow_none=True)


class AdminToolGovernancePolicyPageResp(Schema):
    list = fields.List(fields.Nested(AdminToolGovernancePolicyResp))
    paginator = fields.Dict()


class AdminToolGovernanceAuditResp(Schema):
    id = fields.String()
    tool_id = fields.String()
    tool_name = fields.String()
    account_id = fields.String()
    conversation_id = fields.String()
    invocation_status = fields.String()
    duration_ms = fields.Integer(allow_none=True)
    error_message = fields.String()
    created_at = fields.Integer(allow_none=True)


class AdminToolGovernanceAuditPageResp(Schema):
    list = fields.List(fields.Nested(AdminToolGovernanceAuditResp))
    paginator = fields.Dict()


class AdminToolGovernanceStatsResp(Schema):
    total = fields.Integer()
    enabled = fields.Integer()
    disabled = fields.Integer()
    enabled_rate = fields.Float()
    risk_distribution = fields.Dict()
    source_distribution = fields.Dict()
    visibility_distribution = fields.Dict()


class AdminToolGovernanceBatchRiskResp(Schema):
    updated = fields.Integer()
    risk_level = fields.String()
