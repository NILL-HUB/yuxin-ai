from wtforms import Form
from marshmallow import Schema, fields
from wtforms import FieldList, StringField
from wtforms.validators import DataRequired, Length, Optional, regexp


class CreateRoleReq(Form):
    code = StringField("code", validators=[DataRequired("角色编码不能为空"), regexp(regex=r"^[a-z][a-z0-9_]{1,63}$", message="角色编码格式错误")])
    name = StringField("name", validators=[DataRequired("角色名称不能为空"), Length(min=1, max=255)])
    description = StringField("description", default="", validators=[Optional(), Length(max=1024)])
    permission_codes = FieldList(StringField("permission_code"), default=[])


class UpdateRoleReq(Form):
    name = StringField("name", validators=[Optional(), Length(min=1, max=255)])
    description = StringField("description", validators=[Optional(), Length(max=1024)])
    permission_codes = FieldList(StringField("permission_code"), default=[])


class RoleResp(Schema):
    code = fields.String()
    name = fields.String()
    description = fields.String()
    is_system = fields.Boolean()
    permissions = fields.List(fields.String())


class PermissionResp(Schema):
    code = fields.String()
    name = fields.String()
    resource = fields.String()
    action = fields.String()
    description = fields.String()
