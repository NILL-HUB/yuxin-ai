from wtforms import Form
from marshmallow import Schema, fields
from wtforms import StringField
from wtforms.validators import DataRequired, Length


class RedeemCodeReq(Form):
    code = StringField("code", validators=[DataRequired(), Length(min=6, max=128)])


class PlanResp(Schema):
    id = fields.String()
    code = fields.String()
    name = fields.String()
    duration_days = fields.Integer()
    grant_token_credits = fields.Integer()


class MembershipResp(Schema):
    id = fields.String()
    status = fields.String()
    started_at = fields.Integer(allow_none=True)
    expires_at = fields.Integer(allow_none=True)
    source = fields.String()
    source_id = fields.String(allow_none=True)
    plan = fields.Nested(PlanResp, allow_none=True)


class CreditAccountResp(Schema):
    account_id = fields.String()
    balance = fields.Integer()
    total_granted = fields.Integer()
    total_consumed = fields.Integer()


class RedeemedCodeResp(Schema):
    id = fields.String()
    code_mask = fields.String()
    redeemed_at = fields.Integer(allow_none=True)


class CreditTransactionResp(Schema):
    id = fields.String()
    amount = fields.Integer()
    balance_after = fields.Integer()
    transaction_type = fields.String()
    source = fields.String()
    source_id = fields.String(allow_none=True)
    description = fields.String()
    created_at = fields.Integer(allow_none=True)


class RedeemCodeResp(Schema):
    plan = fields.Nested(PlanResp)
    membership = fields.Nested(MembershipResp)
    credit_account = fields.Nested(CreditAccountResp)
    redeem_code = fields.Nested(RedeemedCodeResp)


class MembershipSummaryResp(Schema):
    membership = fields.Nested(MembershipResp, allow_none=True)
    credit_account = fields.Nested(CreditAccountResp)
    recent_transactions = fields.List(fields.Nested(CreditTransactionResp))


class RedeemRecordResp(Schema):
    id = fields.String()
    code_mask = fields.String()
    redeemed_at = fields.Integer(allow_none=True)
    plan = fields.Nested(PlanResp, allow_none=True)
    grant_token_credits = fields.Integer()
    membership_expires_at = fields.Integer(allow_none=True)


class RedeemRecordListResp(Schema):
    list = fields.List(fields.Nested(RedeemRecordResp))
