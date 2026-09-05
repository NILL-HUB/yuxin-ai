from marshmallow import Schema, fields
from wtforms import Form, StringField
from wtforms.validators import DataRequired, Length


class InviteInfoResp(Schema):
    valid = fields.Boolean()
    required = fields.Boolean()
    inviter_name = fields.String()


class ReferralCodeReq(Form):
    code = StringField("code", validators=[DataRequired(), Length(min=4, max=32)])


class SuperiorResp(Schema):
    id = fields.String()
    name = fields.String()


class MyDistributionResp(Schema):
    referral_code = fields.String()
    share_url = fields.String()
    superior = fields.Nested(SuperiorResp, allow_none=True)
    subordinate_count = fields.Integer()
    high_rate_locked = fields.Boolean()
    commission_rate = fields.String()


class SubordinateResp(Schema):
    id = fields.String()
    name = fields.String()
    bound_at = fields.Integer(allow_none=True)
    source = fields.String()


class SubordinateListResp(Schema):
    list = fields.List(fields.Nested(SubordinateResp))
    paginator = fields.Dict()


class CommissionResp(Schema):
    id = fields.String()
    amount = fields.Float()
    rate = fields.Float(allow_none=True)
    source = fields.String()
    source_id = fields.String(allow_none=True)
    description = fields.String()
    created_at = fields.Integer(allow_none=True)


class CommissionListResp(Schema):
    list = fields.List(fields.Nested(CommissionResp))
    paginator = fields.Dict()