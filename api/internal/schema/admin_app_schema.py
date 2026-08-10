from wtforms import Form
from marshmallow import Schema, fields
from wtforms import BooleanField, IntegerField, StringField
from wtforms.validators import Length, NumberRange, Optional
from internal.schema import DictField


class GetAdminAppsReq(Form):
    search = StringField("search", default="", validators=[Optional(), Length(max=255)])
    status = StringField("status", default="all", validators=[Optional(), Length(max=255)])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=100)])


class UpdateAdminAppReq(Form):
    status = StringField("status", validators=[Optional(), Length(max=255)])
    is_public = BooleanField("is_public", validators=[Optional()])
    agent_metadata = DictField("agent_metadata", default=None)


class BatchOfflineAppsReq(Form):
    app_ids = DictField("app_ids", default=None)


class BatchDeleteAppsReq(Form):
    app_ids = DictField("app_ids", default=None)


class AdminAppResp(Schema):
    id = fields.String()
    name = fields.String()
    icon = fields.String()
    description = fields.String()
    status = fields.String()
    app_type = fields.String()
    is_public = fields.Boolean()
    agent_metadata = fields.Dict()
    debug_conversation_id = fields.String(allow_none=True)
    creator_name = fields.String(dump_default="")
    created_at = fields.Integer()
    updated_at = fields.Integer()


class AdminAppPageResp(Schema):
    list = fields.List(fields.Nested(AdminAppResp))
    paginator = fields.Dict()


class BatchOperationResp(Schema):
    succeeded = fields.List(fields.String())
    failed = fields.List(fields.Dict())
