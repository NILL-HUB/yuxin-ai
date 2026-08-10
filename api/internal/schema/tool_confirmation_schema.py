from wtforms import Form
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
from wtforms.validators import AnyOf, DataRequired, Length, NumberRange, Optional

from internal.schema import DictField


class CreateToolConfirmationReq(Form):
    tool_name = StringField(
        "tool_name",
        validators=[DataRequired(), Length(min=1, max=255)],
    )
    risk_level = StringField(
        "risk_level",
        validators=[DataRequired(), AnyOf(["medium", "high", "sensitive"])],
    )
    tool_input = DictField("tool_input", default={}, validators=[Optional()])
    spent_credits = IntegerField(
        "spent_credits",
        default=0,
        validators=[Optional(), NumberRange(min=0)],
    )
    reason = StringField(
        "reason", default="", validators=[Optional(), Length(max=2000)]
    )
    target_system = StringField(
        "target_system", default="", validators=[Optional(), Length(max=255)]
    )
    target_environment = StringField(
        "target_environment", default="", validators=[Optional(), Length(max=64)]
    )
    execution_summary = StringField(
        "execution_summary", default="", validators=[Optional(), Length(max=4000)]
    )
    impact_scope = StringField(
        "impact_scope", default="", validators=[Optional(), Length(max=4000)]
    )
    rollback_strategy = StringField(
        "rollback_strategy", default="", validators=[Optional(), Length(max=4000)]
    )
    audit_hint = StringField(
        "audit_hint", default="", validators=[Optional(), Length(max=4000)]
    )


class ListToolConfirmationReq(Form):
    status = StringField(
        "status",
        default="",
        validators=[Optional(), AnyOf(["", "pending", "confirmed", "cancelled"])],
    )


class ToolConfirmationResp(Schema):
    id = fields.String()
    tool_name = fields.String()
    risk_level = fields.String()
    tool_input = fields.Dict()
    status = fields.String()
    spent_credits = fields.Integer()
    reason = fields.String()
    target_system = fields.String()
    target_environment = fields.String()
    execution_summary = fields.String()
    impact_scope = fields.String()
    rollback_strategy = fields.String()
    audit_hint = fields.String()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()


class ToolConfirmationListResp(Schema):
    items = fields.List(fields.Nested(ToolConfirmationResp))
    total = fields.Integer()
