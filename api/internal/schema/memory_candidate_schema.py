from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import BooleanField, StringField
from wtforms.validators import AnyOf, Optional


class ConfirmMemoryCandidateReq(FlaskForm):
    policy = StringField(
        "policy",
        default="manual_confirm",
        validators=[Optional(), AnyOf(["manual_confirm", "auto_save"])],
    )


class IgnoreMemoryCandidateReq(FlaskForm):
    never_remind = BooleanField(
        "never_remind", default=False, validators=[Optional()]
    )


class UserMemoryResp(Schema):
    id = fields.String()
    memory_type = fields.String()
    content = fields.String()
    confidence = fields.Integer()
    status = fields.String()
    created_from = fields.String()
    metadata = fields.Dict(attribute="metadata_")


class MemoryCandidateResp(Schema):
    id = fields.String()
    content = fields.String()
    confidence = fields.Integer()
    occurrences = fields.Integer()
    status = fields.String()
    memory_type = fields.String()
    source_conversation_id = fields.String(allow_none=True)
    metadata = fields.Dict(attribute="metadata_")
