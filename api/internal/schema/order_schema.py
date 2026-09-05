from marshmallow import Schema, fields
from wtforms import Form, StringField
from wtforms.validators import DataRequired, Length


class OrderCreateReq(Form):
    plan_id = StringField("plan_id", validators=[DataRequired()])
    pay_method = StringField("pay_method", validators=[DataRequired()])


class OrderResp(Schema):
    order_no = fields.String()
    plan_id = fields.String()
    plan_type = fields.String()
    amount = fields.Float()
    pay_method = fields.String()
    order_source = fields.String()
    status = fields.String()
    transaction_id = fields.String(allow_none=True)
    paid_at = fields.Integer(allow_none=True)
    created_at = fields.Integer(allow_none=True)


class OrderCreateResultResp(Schema):
    order = fields.Nested(OrderResp)
    payment_params = fields.Dict(allow_none=True)


class OrderListResp(Schema):
    list = fields.List(fields.Nested(OrderResp))
    paginator = fields.Dict()


class RefundCreateReq(Form):
    order_no = StringField("order_no", validators=[DataRequired()])
    reason = StringField("reason", validators=[Length(max=1024)])


class RefundResp(Schema):
    id = fields.String()
    order_no = fields.String()
    amount = fields.Float()
    reason = fields.String()
    status = fields.String()
    created_at = fields.Integer(allow_none=True)


class RefundListResp(Schema):
    list = fields.List(fields.Nested(RefundResp))
    paginator = fields.Dict()