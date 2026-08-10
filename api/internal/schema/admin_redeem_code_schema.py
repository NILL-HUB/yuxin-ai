from wtforms import Form
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
from wtforms.validators import AnyOf, InputRequired, Length, NumberRange, Optional


class GenerateRedeemCodesReq(Form):
    name = StringField("name", validators=[InputRequired(), Length(max=255)])
    plan_id = StringField("plan_id", validators=[InputRequired(), Length(max=64)])
    quantity = IntegerField("quantity", validators=[InputRequired(), NumberRange(min=1, max=1000)])
    expires_at = IntegerField("expires_at", validators=[Optional(), NumberRange(min=1)])


class GetRedeemCodeBatchesReq(Form):
    keyword = StringField("keyword", default="", validators=[Optional(), Length(max=255)])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=50)])


class GetRedeemCodesReq(Form):
    batch_id = StringField("batch_id", default="", validators=[Optional(), Length(max=64)])
    status = StringField("status", default="", validators=[Optional(), AnyOf(["", "unused", "used", "disabled", "expired"])])
    code_keyword = StringField("code_keyword", default="", validators=[Optional(), Length(max=64)])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=50)])


class RedeemCodeBatchResp(Schema):
    id = fields.String()
    name = fields.String()
    plan_id = fields.String()
    quantity = fields.Integer()
    status = fields.String()
    expires_at = fields.Integer(allow_none=True)
    disabled_at = fields.Integer(allow_none=True)
    created_by = fields.String(allow_none=True)
    created_at = fields.Integer(allow_none=True)


class RedeemCodeResp(Schema):
    id = fields.String()
    batch_id = fields.String(allow_none=True)
    plan_id = fields.String()
    code_mask = fields.String()
    status = fields.String()
    redeemed_by = fields.String(allow_none=True)
    redeemed_at = fields.Integer(allow_none=True)
    expires_at = fields.Integer(allow_none=True)
    disabled_at = fields.Integer(allow_none=True)
    created_at = fields.Integer(allow_none=True)


class GeneratedRedeemCodeResp(Schema):
    plain_code = fields.String()
    code_mask = fields.String()


class GenerateRedeemCodesResp(Schema):
    batch = fields.Nested(RedeemCodeBatchResp)
    codes = fields.List(fields.Nested(GeneratedRedeemCodeResp))


class RedeemCodeBatchPageResp(Schema):
    list = fields.List(fields.Nested(RedeemCodeBatchResp))
    paginator = fields.Dict()


class RedeemCodePageResp(Schema):
    list = fields.List(fields.Nested(RedeemCodeResp))
    paginator = fields.Dict()
