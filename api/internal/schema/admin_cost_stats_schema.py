from wtforms import Form, IntegerField, StringField
from wtforms.validators import Optional, NumberRange
from marshmallow import Schema, fields


class GetCostStatsOverviewReq(Form):
    start_at = IntegerField("start_at", validators=[Optional(), NumberRange(min=0)])
    end_at = IntegerField("end_at", validators=[Optional(), NumberRange(min=0)])


class GetCostStatsByDimensionReq(Form):
    dimension = StringField(
        "dimension",
        default="user",
        validators=[Optional()],
    )
    start_at = IntegerField("start_at", validators=[Optional(), NumberRange(min=0)])
    end_at = IntegerField("end_at", validators=[Optional(), NumberRange(min=0)])
    limit = IntegerField(
        "limit", default=10, validators=[Optional(), NumberRange(min=1, max=100)]
    )


class GetCostStatsTimeseriesReq(Form):
    granularity = StringField(
        "granularity",
        default="day",
        validators=[Optional()],
    )
    start_at = IntegerField("start_at", validators=[Optional(), NumberRange(min=0)])
    end_at = IntegerField("end_at", validators=[Optional(), NumberRange(min=0)])


class CostStatsOverviewResp(Schema):
    total_credits = fields.Integer()
    total_requests = fields.Integer()
    avg_cost_per_request = fields.Float()
    total_input_tokens = fields.Integer()
    total_output_tokens = fields.Integer()


class CostStatsDimensionItemResp(Schema):
    name = fields.String()
    total_credits = fields.Integer()
    request_count = fields.Integer()
    avg_credits = fields.Float()
    percentage = fields.Float()


class CostStatsByDimensionResp(Schema):
    dimension = fields.String()
    items = fields.List(fields.Nested(CostStatsDimensionItemResp))
    total_credits = fields.Integer()


class CostStatsTimeseriesPointResp(Schema):
    timestamp = fields.Integer()
    total_credits = fields.Integer()
    request_count = fields.Integer()


class CostStatsTimeseriesResp(Schema):
    granularity = fields.String()
    points = fields.List(fields.Nested(CostStatsTimeseriesPointResp))
