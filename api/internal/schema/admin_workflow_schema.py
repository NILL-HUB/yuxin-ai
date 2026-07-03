from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import BooleanField, IntegerField, StringField
from wtforms.validators import Length, NumberRange, Optional
from internal.schema import DictField


class GetAdminWorkflowsReq(FlaskForm):
    search = StringField("search", default="", validators=[Optional(), Length(max=255)])
    status = StringField("status", default="all", validators=[Optional(), Length(max=255)])
    current_page = IntegerField("current_page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=100)])


class UpdateAdminWorkflowReq(FlaskForm):
    status = StringField("status", validators=[Optional(), Length(max=255)])
    is_public = BooleanField("is_public", validators=[Optional()])


class PublishAdminWorkflowReq(FlaskForm):
    summary = StringField("summary", default="", validators=[Optional(), Length(max=500)])


class RollbackWorkflowVersionReq(FlaskForm):
    summary = StringField("summary", default="", validators=[Optional(), Length(max=500)])


class BatchPublishWorkflowsReq(FlaskForm):
    workflow_ids = DictField("workflow_ids", default=None)


class BatchOfflineWorkflowsReq(FlaskForm):
    workflow_ids = DictField("workflow_ids", default=None)


class AdminWorkflowResp(Schema):
    id = fields.String()
    name = fields.String()
    tool_call_name = fields.String()
    icon = fields.String()
    description = fields.String()
    status = fields.String()
    is_public = fields.Boolean()
    created_at = fields.Integer()
    updated_at = fields.Integer()


class AdminWorkflowPageResp(Schema):
    list = fields.List(fields.Nested(AdminWorkflowResp))
    paginator = fields.Dict()


class WorkflowVersionResp(Schema):
    id = fields.String()
    workflow_id = fields.String()
    version = fields.Integer()
    is_current_published = fields.Boolean()
    summary = fields.String()
    created_at = fields.Integer()
    updated_at = fields.Integer()


class WorkflowVersionListResp(Schema):
    list = fields.List(fields.Nested(WorkflowVersionResp))


class BatchOperationResp(Schema):
    succeeded = fields.List(fields.String())
    failed = fields.List(fields.Dict())

