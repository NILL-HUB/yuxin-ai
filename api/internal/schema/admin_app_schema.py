from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import BooleanField, IntegerField, StringField
from wtforms.validators import Length, NumberRange, Optional


class GetAdminAppsReq(FlaskForm):
    search = StringField("search", default="", validators=[Optional(), Length(max=255)])
    status = StringField("status", default="all", validators=[Optional(), Length(max=255)])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=50)])


class UpdateAdminAppReq(FlaskForm):
    status = StringField("status", validators=[Optional(), Length(max=255)])
    is_public = BooleanField("is_public", validators=[Optional()])


class AdminAppResp(Schema):
    id = fields.String()
    name = fields.String()
    icon = fields.String()
    description = fields.String()
    status = fields.String()
    is_public = fields.Boolean()
    created_at = fields.Integer()
    updated_at = fields.Integer()


class AdminAppPageResp(Schema):
    list = fields.List(fields.Nested(AdminAppResp))
    paginator = fields.Dict()
