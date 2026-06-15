from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
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
    status = fields.String()
    created_at = fields.Integer()


class RoutingLogPageResp(Schema):
    list = fields.List(fields.Nested(RoutingLogResp))
    paginator = fields.Dict()
