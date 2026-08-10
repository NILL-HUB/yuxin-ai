from wtforms import Form
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
from wtforms.validators import AnyOf, Length, NumberRange, Optional


class GetAdminCustomerUsersReq(Form):
    keyword = StringField("keyword", default="", validators=[Optional(), Length(max=255)])
    status = StringField("status", default="", validators=[Optional(), AnyOf(["", "active", "disabled"])])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=50)])


class DisableAdminCustomerUserReq(Form):
    reason = StringField("reason", default="", validators=[Optional(), Length(max=1024)])


class AdminCustomerUserSessionResp(Schema):
    id = fields.String()
    status = fields.String()
    user_agent = fields.String()
    ip = fields.String()
    created_at = fields.Integer(allow_none=True)
    last_active_at = fields.Integer(allow_none=True)
    expires_at = fields.Integer(allow_none=True)
    revoked_at = fields.Integer(allow_none=True)


class AdminCustomerUserResp(Schema):
    id = fields.String()
    email = fields.String()
    name = fields.String()
    avatar = fields.String()
    status = fields.String()
    disabled_at = fields.Integer(allow_none=True)
    disabled_by = fields.String(allow_none=True)
    disabled_reason = fields.String()
    last_login_at = fields.Integer(allow_none=True)
    last_login_ip = fields.String()
    created_at = fields.Integer(allow_none=True)
    sessions = fields.List(fields.Nested(AdminCustomerUserSessionResp))
    is_online = fields.Boolean()


class AdminCustomerUserPageResp(Schema):
    list = fields.List(fields.Nested(AdminCustomerUserResp))
    paginator = fields.Dict()


class RevokeCustomerUserSessionsResp(Schema):
    revoked_sessions = fields.Integer()
