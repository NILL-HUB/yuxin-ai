"""Admin 内容存储管理 schema。"""
from wtforms import Form
from marshmallow import Schema, fields, pre_dump
from wtforms import IntegerField, SelectField, StringField
from wtforms.validators import Length, NumberRange, Optional

from internal.lib.helper import datetime_to_timestamp


class GetStorageMigrationFilesReq(Form):
    source_backend = StringField("source_backend", default="", validators=[Optional(), Length(max=32)])
    page = IntegerField("page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=100)])
    extension = StringField("extension", default="", validators=[Optional(), Length(max=32)])
    search_word = StringField("search_word", default="", validators=[Optional(), Length(max=255)])


class UpdateStorageConfigReq(Form):
    backend = SelectField(
        "backend",
        choices=[("local", "local"), ("cos", "cos"), ("oss", "oss")],
        validators=[Optional()],
    )
    # 后端配置项（JSON 字符串，由 handler 解析）
    configs = StringField("configs", default="", validators=[Optional(), Length(max=8192)])


class ActivateStorageReq(Form):
    backend = SelectField(
        "backend",
        choices=[("local", "local"), ("cos", "cos"), ("oss", "oss")],
        validators=[Optional()],
    )


class StorageConfigItemSchema(Schema):
    id = fields.String()
    backend = fields.String()
    configs = fields.Dict()
    is_active = fields.Boolean()
    created_at = fields.Integer(allow_none=True)
    updated_at = fields.Integer(allow_none=True)

    @pre_dump
    def process_data(self, data, **kwargs):
        return {
            "id": str(data.id),
            "backend": data.backend,
            "configs": data.configs or {},
            "is_active": bool(data.is_active),
            "created_at": datetime_to_timestamp(data.created_at),
            "updated_at": datetime_to_timestamp(data.updated_at),
        }


class StorageConfigListSchema(Schema):
    items = fields.List(fields.Nested(StorageConfigItemSchema))


class StorageOverviewSchema(Schema):
    active_backend = fields.String()
    backend_items = fields.List(fields.Nested(StorageConfigItemSchema))
    stats = fields.Dict()


class StorageMigrationFileSchema(Schema):
    id = fields.String()
    name = fields.String()
    key = fields.String()
    size = fields.Integer()
    extension = fields.String()
    mime_type = fields.String()
    hash = fields.String(dump_default="")
    storage_backend = fields.String(allow_none=True)
    resolved_backend = fields.String(allow_none=True)
    url = fields.String(allow_none=True)
    kkfileview_url = fields.String(allow_none=True)
    source_type = fields.String(dump_default="unknown")
    source_label = fields.String(dump_default="")
    duplicate_count = fields.Integer(dump_default=1)
    is_latest = fields.Boolean(dump_default=True)
    is_valid = fields.Boolean(dump_default=True)
    in_use = fields.Boolean(dump_default=False)
    created_at = fields.Integer(allow_none=True)


class StorageMigrationListSchema(Schema):
    items = fields.List(fields.Nested(StorageMigrationFileSchema))
    total = fields.Integer(dump_default=0)
    page = fields.Integer(dump_default=1)
    page_size = fields.Integer(dump_default=20)
    total_pages = fields.Integer(dump_default=0)
    total_record = fields.Integer(dump_default=0)
    extensions = fields.List(fields.String(), dump_default=[])
    summary = fields.Dict(dump_default={})


class StorageMigrationResultSchema(Schema):
    total = fields.Integer(dump_default=0)
    succeeded = fields.Integer(dump_default=0)
    failed = fields.Integer(dump_default=0)
    failures = fields.List(fields.Dict(), dump_default=[])


class StorageDeleteResultSchema(Schema):
    total = fields.Integer(dump_default=0)
    succeeded = fields.Integer(dump_default=0)
    failed = fields.Integer(dump_default=0)
    in_use = fields.List(fields.Dict(), dump_default=[])
    failures = fields.List(fields.Dict(), dump_default=[])
