from marshmallow import Schema, fields
from wtforms import Form, StringField
from wtforms.validators import DataRequired, Length


class WithdrawCreateReq(Form):
    amount = StringField("amount", validators=[DataRequired()])


class WithdrawResp(Schema):
    id = fields.String()
    account_id = fields.String()
    amount = fields.Float()
    status = fields.String()
    review_note = fields.String()
    created_at = fields.Integer(allow_none=True)


class WithdrawListResp(Schema):
    list = fields.List(fields.Nested(WithdrawResp))
    paginator = fields.Dict()


class WithdrawReviewReq(Form):
    note = StringField("note", validators=[Length(max=1024)])