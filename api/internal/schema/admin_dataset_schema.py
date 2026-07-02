from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
from wtforms.validators import Length, NumberRange, Optional


class GetAdminDatasetsReq(FlaskForm):
    """校验后台数据集分页查询参数。"""

    search_word = StringField("search_word", default="", validators=[Optional(), Length(max=255)])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=50)])


class AdminDatasetResp(Schema):
    """约束后台数据集列表项的响应结构。"""

    id = fields.String()
    name = fields.String()
    icon = fields.String()
    description = fields.String()
    document_count = fields.Integer()
    related_app_count = fields.Integer()
    character_count = fields.Integer()
    creator_name = fields.String()
    creator_avatar = fields.String()
    upload_at = fields.Integer(allow_none=True)
    updated_at = fields.Integer(allow_none=True)
    created_at = fields.Integer(allow_none=True)


class AdminDatasetPageResp(Schema):
    """约束后台数据集分页列表响应结构。"""

    list = fields.List(fields.Nested(AdminDatasetResp))
    paginator = fields.Dict()
