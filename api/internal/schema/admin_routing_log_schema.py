from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import Form, IntegerField, StringField
from wtforms.validators import Length, NumberRange, Optional


class GetRoutingLogsReq(FlaskForm):
    current_page = IntegerField(
        "current_page",
        default=1,
        validators=[Optional(), NumberRange(min=1, max=9999)],
    )
    page_size = IntegerField(
        "page_size",
        default=20,
        validators=[Optional(), NumberRange(min=1, max=100)],
    )
    account_id = StringField(
        "account_id", default="", validators=[Optional(), Length(max=64)]
    )
    status = StringField(
        "status", default="", validators=[Optional(), Length(max=64)]
    )
    agent_id = StringField(
        "agent_id", default="", validators=[Optional(), Length(max=128)]
    )
    agent_pool = StringField(
        "agent_pool", default="", validators=[Optional(), Length(max=128)]
    )
    tool_name = StringField(
        "tool_name", default="", validators=[Optional(), Length(max=128)]
    )
    tool_pool = StringField(
        "tool_pool", default="", validators=[Optional(), Length(max=128)]
    )
    model_id = StringField(
        "model_id", default="", validators=[Optional(), Length(max=128)]
    )
    key_id = StringField(
        "key_id", default="", validators=[Optional(), Length(max=128)]
    )
    start_at = StringField(
        "start_at", default="", validators=[Optional(), Length(max=64)]
    )
    end_at = StringField(
        "end_at", default="", validators=[Optional(), Length(max=64)]
    )


class RoutingLogResp(Schema):
    id = fields.String()
    account_id = fields.String()
    message_id = fields.String()
    routing_decision = fields.Dict()
    agent_candidates = fields.List(fields.Dict())
    filtered_out_agents = fields.List(fields.Dict())
    tool_candidates = fields.List(fields.Dict())
    filtered_out_tools = fields.List(fields.Dict())
    knowledge_hits = fields.List(fields.Dict())
    billing_events = fields.List(fields.Dict())
    user_query = fields.String(allow_none=True)
    task_classification = fields.Dict()
    model_selection = fields.Dict()
    agent_pool_hits = fields.List(fields.Dict())
    tool_pool_hits = fields.List(fields.Dict())
    key_usage = fields.Dict()
    cost_summary = fields.Dict()
    latency_ms = fields.Integer()
    fallback_reason = fields.String()
    redaction_enabled = fields.Boolean()
    retention_expires_at = fields.Integer(allow_none=True)
    status = fields.String()
    created_at = fields.Integer()


class RoutingLogPageResp(Schema):
    list = fields.List(fields.Nested(RoutingLogResp))
    paginator = fields.Dict()
    summary = fields.Dict()


class SetRoutingLogRetentionReq(Form):
    retention_days = IntegerField(
        "retention_days",
        validators=[NumberRange(min=1, max=3650)],
    )


class RoutingLogRetentionResp(Schema):
    retention_days = fields.Integer()
    default_retention_days = fields.Integer()
    min_retention_days = fields.Integer()
    max_retention_days = fields.Integer()
    code = fields.String()
