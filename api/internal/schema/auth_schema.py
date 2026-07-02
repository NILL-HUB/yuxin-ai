from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired, Email, Length, Optional, regexp
from pkg.password import password_pattern
from marshmallow import Schema, fields

USERNAME_PATTERN = r"^[A-Za-z0-9]{3,32}$"
PASSWORD_RULE_MESSAGE = "密码需包含字母和数字，可使用下划线、点等常规字符，长度6~32位"

class PasswordLoginReq(FlaskForm):
    """账号密码登陆请求结构"""
    identifier = StringField('identifier', validators=[
        Optional(),
        Length(min=3, max=254, message="登录账号长度在3~254之间")
    ])
    email = StringField('email', validators=[
        Optional(),
        Email("登陆邮箱格式错误"),
        Length(min=3, max=254, message="登录账号长度在3~254之间")
    ])
    password = StringField('password', validators=[
        DataRequired("密码不能为空"),
    ])

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False
        if not (self.identifier.data or self.email.data):
            self.identifier.errors.append("登录账号不能为空")
            return False
        return True

class PasswordLoginResp(Schema):
    """账号密码授权认证响应结构"""
    access_token = fields.String(allow_none=True)
    expire_at = fields.Integer(allow_none=True)
    challenge_required = fields.Boolean()
    challenge_id = fields.String(allow_none=True)
    challenge_type = fields.String(allow_none=True)
    masked_email = fields.String(allow_none=True)
    risk_reason = fields.String(allow_none=True)

class PrepareRegisterReq(FlaskForm):
    """准备注册请求结构"""
    username = StringField('username', validators=[
        Optional(),
        regexp(regex=USERNAME_PATTERN, message="用户名仅支持大小写字母和数字，长度3~32位")
    ])
    email = StringField('email', validators=[
        DataRequired("邮箱不能为空"),
        Email("邮箱格式错误"),
        Length(min=3, max=254, message="邮箱长度在3~254之间")
    ])
    password = StringField('password', validators=[
        DataRequired("密码不能为空"),
        regexp(regex=password_pattern, message=PASSWORD_RULE_MESSAGE)
    ])


class DirectRegisterReq(FlaskForm):
    """直接注册请求结构（无需邮箱验证码）"""
    username = StringField('username', validators=[
        DataRequired("用户名不能为空"),
        regexp(regex=USERNAME_PATTERN, message="用户名仅支持大小写字母和数字，长度3~32位")
    ])
    password = StringField('password', validators=[
        DataRequired("密码不能为空"),
        regexp(regex=password_pattern, message=PASSWORD_RULE_MESSAGE)
    ])


class VerifyRegisterReq(FlaskForm):
    """验证码注册请求结构"""
    username = StringField('username', validators=[
        Optional(),
        regexp(regex=USERNAME_PATTERN, message="用户名仅支持大小写字母和数字，长度3~32位")
    ])
    email = StringField('email', validators=[
        DataRequired("邮箱不能为空"),
        Email("邮箱格式错误"),
        Length(min=3, max=254, message="邮箱长度在3~254之间")
    ])
    password = StringField('password', validators=[
        DataRequired("密码不能为空"),
        regexp(regex=password_pattern, message=PASSWORD_RULE_MESSAGE)
    ])
    code = StringField('code', validators=[
        DataRequired("验证码不能为空"),
        Length(min=6, max=6, message="验证码必须是6位数字")
    ])

class SendResetCodeReq(FlaskForm):
    """发送重置验证码请求结构"""
    email = StringField('email', validators=[
        DataRequired("邮箱不能为空"),
        Email("邮箱格式错误"),
        Length(min=3, max=254, message="邮箱长度在3~254之间")
    ])

class ResetPasswordReq(FlaskForm):
    """重置密码请求结构"""
    email = StringField('email', validators=[
        DataRequired("邮箱不能为空"),
        Email("邮箱格式错误"),
    ])
    code = StringField('code', validators=[
        DataRequired("验证码不能为空"),
        Length(min=6, max=6, message="验证码必须是6位数字")
    ])
    new_password = StringField('new_password', validators=[
        DataRequired("新密码不能为空"),
        regexp(regex=password_pattern, message=PASSWORD_RULE_MESSAGE)
    ])


class VerifyLoginChallengeReq(FlaskForm):
    """登录二次验证请求结构"""
    challenge_id = StringField('challenge_id', validators=[
        DataRequired("challenge_id 不能为空"),
        Length(min=1, max=128, message="challenge_id 参数错误"),
    ])
    code = StringField('code', validators=[
        DataRequired("验证码不能为空"),
        Length(min=6, max=6, message="验证码必须是6位数字")
    ])


class ResendLoginChallengeReq(FlaskForm):
    """重发登录二次验证验证码请求结构"""
    challenge_id = StringField('challenge_id', validators=[
        DataRequired("challenge_id 不能为空"),
        Length(min=1, max=128, message="challenge_id 参数错误"),
    ])
