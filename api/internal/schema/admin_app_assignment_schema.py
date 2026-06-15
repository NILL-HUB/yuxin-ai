from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import FieldList, StringField
from wtforms.validators import DataRequired, Length


class AssignAppsReq(FlaskForm):
    app_ids = FieldList(StringField("app_id", validators=[DataRequired(), Length(min=1, max=64)]), min_entries=1)


class AssignedAppResp(Schema):
    id = fields.String()
    name = fields.String()
    icon = fields.String()
    description = fields.String()
    status = fields.String()
    is_public = fields.Boolean()


class AppAssignmentResp(Schema):
    id = fields.String()
    app_id = fields.String()
    account_id = fields.String()
    assigned_by = fields.String(allow_none=True)
    status = fields.String()
    assigned_at = fields.Integer(allow_none=True)
    revoked_at = fields.Integer(allow_none=True)
    app = fields.Nested(AssignedAppResp, allow_none=True)


class AppAssignmentListResp(Schema):
    list = fields.List(fields.Nested(AppAssignmentResp))


class AssignAppsResp(Schema):
    assigned = fields.Integer()
    reactivated = fields.Integer()
    skipped = fields.Integer()
    list = fields.List(fields.Nested(AppAssignmentResp))
