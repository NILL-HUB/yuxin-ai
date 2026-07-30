from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
from wtforms.validators import Length, NumberRange, Optional


class GetAuditLogsReq(FlaskForm):
    action = StringField("action", default="", validators=[Optional(), Length(max=255)])
    resource_type = StringField("resource_type", default="", validators=[Optional(), Length(max=255)])
    admin_user_id = StringField("admin_user_id", default="", validators=[Optional(), Length(max=64)])
    start_time = IntegerField("start_time", default=0, validators=[Optional(), NumberRange(min=0, max=21474836470)])
    end_time = IntegerField("end_time", default=0, validators=[Optional(), NumberRange(min=0, max=21474836470)])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=50)])


class AuditLogResp(Schema):
    id = fields.String()
    admin_user_id = fields.String(allow_none=True)
    admin_user_name = fields.String(allow_none=True)
    account_id = fields.String(allow_none=True)
    account_name = fields.String(allow_none=True)
    action = fields.String()
    resource_type = fields.String()
    resource_id = fields.String()
    ip = fields.String()
    user_agent = fields.String()
    before_data = fields.Dict()
    after_data = fields.Dict()
    created_at = fields.Integer()


class AuditLogPageResp(Schema):
    list = fields.List(fields.Nested(AuditLogResp))
    paginator = fields.Dict()
