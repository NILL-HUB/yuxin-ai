from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import FieldList, FormField, IntegerField, StringField
from wtforms.validators import AnyOf, InputRequired, Length, NumberRange, Optional


class PlanEntitlementForm(FlaskForm):
    feature_key = StringField("feature_key", validators=[InputRequired(), Length(max=128)])
    feature_value = StringField("feature_value", validators=[InputRequired(), Length(max=1024)])
    value_type = StringField("value_type", default="string", validators=[InputRequired(), AnyOf(["string", "number", "decimal", "boolean", "json"])])


class GetAdminPlansReq(FlaskForm):
    keyword = StringField("keyword", default="", validators=[Optional(), Length(max=255)])
    status = StringField("status", default="", validators=[Optional(), AnyOf(["", "active", "disabled"])])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=50)])


class UpsertAdminPlanReq(FlaskForm):
    code = StringField("code", validators=[Optional(), Length(max=128)])
    name = StringField("name", validators=[Optional(), Length(max=255)])
    description = StringField("description", default="", validators=[Optional(), Length(max=1024)])
    duration_days = IntegerField("duration_days", validators=[Optional(), NumberRange(min=1, max=3650)])
    grant_token_credits = IntegerField("grant_token_credits", validators=[Optional(), NumberRange(min=0, max=10_000_000_000)])
    price = StringField("price", default="0.00", validators=[Optional(), Length(max=32)])
    status = StringField("status", default="active", validators=[Optional(), AnyOf(["active", "disabled"])])
    sort_order = IntegerField("sort_order", default=0, validators=[Optional(), NumberRange(min=0, max=999999)])
    entitlements = FieldList(FormField(PlanEntitlementForm), default=[], validators=[Optional()])


class SetAdminPlanStatusReq(FlaskForm):
    status = StringField("status", validators=[InputRequired(), AnyOf(["active", "disabled"])])


class AdminPlanEntitlementResp(Schema):
    id = fields.String()
    feature_key = fields.String()
    feature_value = fields.String()
    value_type = fields.String()
    parsed_value = fields.Raw()


class AdminPlanResp(Schema):
    id = fields.String()
    code = fields.String()
    name = fields.String()
    description = fields.String()
    duration_days = fields.Integer()
    grant_token_credits = fields.Integer()
    price = fields.String()
    status = fields.String()
    sort_order = fields.Integer()
    created_at = fields.Integer(allow_none=True)
    updated_at = fields.Integer(allow_none=True)
    entitlements = fields.List(fields.Nested(AdminPlanEntitlementResp))


class AdminPlanPageResp(Schema):
    list = fields.List(fields.Nested(AdminPlanResp))
    paginator = fields.Dict()
