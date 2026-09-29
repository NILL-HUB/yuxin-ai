"""用户文件中心响应 schema。"""
from marshmallow import Schema, fields, pre_dump


class FileCenterEntrySchema(Schema):
    id = fields.String()
    parent_id = fields.String(allow_none=True)
    name = fields.String()
    is_folder = fields.Boolean()
    upload_file_id = fields.String(allow_none=True)
    source = fields.String()
    origin = fields.String(allow_none=True)

    @pre_dump
    def process_data(self, data, **kwargs):
        return {
            "id": str(data.id),
            "parent_id": str(data.parent_id) if data.parent_id else None,
            "name": data.name,
            "is_folder": bool(data.is_folder),
            "upload_file_id": str(data.upload_file_id) if data.upload_file_id else None,
            "source": data.source,
            "origin": data.origin,
        }


class FileCenterChildrenSchema(Schema):
    items = fields.List(fields.Nested(FileCenterEntrySchema))
    parent_id = fields.String(allow_none=True)
