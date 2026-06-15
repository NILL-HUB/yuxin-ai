from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
from wtforms.validators import AnyOf, DataRequired, Length, NumberRange, Optional

from internal.schema import DictField


class CreateToolConfirmationReq(FlaskForm):
    tool_name = StringField(
        "tool_name",
        validators=[DataRequired(), Length(min=1, max=255)],
    )
    risk_level = StringField(
        "risk_level",
        validators=[DataRequired(), AnyOf(["medium", "high"])],
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


class ToolConfirmationResp(Schema):
    id = fields.String()
    tool_name = fields.String()
    risk_level = fields.String()
    tool_input = fields.Dict()
    status = fields.String()
    spent_credits = fields.Integer()
    reason = fields.String()
