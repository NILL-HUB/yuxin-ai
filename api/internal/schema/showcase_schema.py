from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from internal.schema import ListField
from pkg.paginator import PaginatorReq


class CreateShowcaseCaseReq(FlaskForm):
    conversation_id = StringField("conversation_id", validators=[DataRequired("会话id不能为空")])
    title = StringField(
        "title",
        validators=[
            DataRequired("标题不能为空"),
            Length(max=200, message="标题长度不能超过200个字符"),
        ],
    )
    summary = StringField("summary", validators=[DataRequired("摘要不能为空")])
    query = TextAreaField("query", validators=[DataRequired("原始问题不能为空")])
    answer = TextAreaField("answer", validators=[DataRequired("最终回答不能为空")])
    tags = ListField("tags", default=[])
    rating = IntegerField(
        "rating",
        default=5,
        validators=[Optional(), NumberRange(min=1, max=5, message="评分范围在1-5")],
    )


class GetShowcaseCasesReq(PaginatorReq):
    tag = StringField("tag", default="", validators=[Optional(), Length(max=64)])
    keyword = StringField("keyword", default="", validators=[Optional(), Length(max=255)])


class GetAdminShowcaseCasesReq(PaginatorReq):
    status = StringField("status", default="all", validators=[Optional(), Length(max=32)])


class RejectShowcaseCaseReq(FlaskForm):
    reason = StringField("reason", validators=[Optional(), Length(max=500)])


class ShowcaseCaseResp(Schema):
    id = fields.String()
    conversation_id = fields.String()
    account_id = fields.String()
    title = fields.String()
    summary = fields.String()
    query = fields.String()
    answer = fields.String()
    tags = fields.List(fields.String())
    rating = fields.Integer()
    status = fields.String()
    reject_reason = fields.String()
    created_at = fields.Integer()
    approved_at = fields.Integer(allow_none=True)
    approved_by = fields.String(allow_none=True)
    updated_at = fields.Integer()


class ShowcaseCasePageResp(Schema):
    list = fields.List(fields.Nested(ShowcaseCaseResp))
    paginator = fields.Dict()
