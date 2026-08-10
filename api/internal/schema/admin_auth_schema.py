from wtforms import Form
from marshmallow import Schema, fields
from wtforms import StringField
from wtforms.validators import DataRequired, Length, Optional


class AdminPasswordLoginReq(Form):
    identifier = StringField("identifier", validators=[
        Optional(),
        Length(min=3, max=254, message="登录账号长度在3~254之间"),
    ])
    email = StringField("email", validators=[Optional()])
    password = StringField("password", validators=[
        DataRequired("密码不能为空"),
    ])


class AdminChangePasswordReq(Form):
    current_password = StringField("current_password", validators=[
        DataRequired("当前密码不能为空"),
    ])
    new_password = StringField("new_password", validators=[
        DataRequired("新密码不能为空"),
    ])


class AdminUserResp(Schema):
    id = fields.String()
    username = fields.String()
    email = fields.String()
    name = fields.String()
    avatar = fields.String()
    status = fields.String()
    roles = fields.List(fields.String())
    permissions = fields.List(fields.String())


class AdminPasswordLoginResp(Schema):
    access_token = fields.String()
    admin_access_token = fields.String()
    expire_at = fields.Integer()
    admin_user = fields.Nested(AdminUserResp)
