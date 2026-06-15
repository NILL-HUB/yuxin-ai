from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import FieldList, IntegerField, StringField
from wtforms.validators import AnyOf, DataRequired, Length, NumberRange, Optional, regexp

from pkg.password import password_pattern


class GetAdminUsersReq(FlaskForm):
    search = StringField("search", default="", validators=[Optional(), Length(max=255)])
    status = StringField("status", default="all", validators=[Optional(), AnyOf(["all", "active", "disabled", "pending"])])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=50)])


class CreateAdminUserReq(FlaskForm):
    username = StringField("username", validators=[Optional(), Length(min=3, max=64)])
    email = StringField("email", validators=[Optional(), Length(max=255)])
    name = StringField("name", validators=[DataRequired("名称不能为空"), Length(min=1, max=255)])
    password = StringField("password", validators=[DataRequired("密码不能为空"), regexp(regex=password_pattern, message="密码需包含字母和数字，可使用下划线、点等常规字符，长度6~32位")])
    role_ids = FieldList(StringField("role_id"), default=[])


class UpdateAdminUserReq(FlaskForm):
    name = StringField("name", validators=[Optional(), Length(min=1, max=255)])
    status = StringField("status", validators=[Optional(), AnyOf(["active", "disabled", "pending"])])
    role_ids = FieldList(StringField("role_id"), default=[])


class AdminUserResp(Schema):
    id = fields.String()
    username = fields.String()
    email = fields.String()
    name = fields.String()
    avatar = fields.String()
    status = fields.String()
    roles = fields.List(fields.String())


class AdminUserPageResp(Schema):
    list = fields.List(fields.Nested(AdminUserResp))
    paginator = fields.Dict()
