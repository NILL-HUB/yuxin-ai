"""用户文件中心响应 schema。"""
from marshmallow import Schema, fields, pre_dump


def _field(data, key, default=None):
    """兼容 ORM 对象与 dict 两种入参的取值。"""
    if isinstance(data, dict):
        return data.get(key, default)
    return getattr(data, key, default)


class FileCenterEntrySchema(Schema):
    id = fields.String()
    parent_id = fields.String(allow_none=True)
    name = fields.String()
    is_folder = fields.Boolean()
    upload_file_id = fields.String(allow_none=True)
    source = fields.String()
    origin = fields.String(allow_none=True)
    url = fields.String(allow_none=True)

    @pre_dump
    def process_data(self, data, **kwargs):
        entry_id = _field(data, "id")
        parent_id = _field(data, "parent_id")
        upload_file_id = _field(data, "upload_file_id")
        return {
            "id": str(entry_id) if entry_id else None,
            "parent_id": str(parent_id) if parent_id else None,
            "name": _field(data, "name") or "",
            "is_folder": bool(_field(data, "is_folder", False)),
            "upload_file_id": str(upload_file_id) if upload_file_id else None,
            "source": _field(data, "source") or "upload",
            "origin": _field(data, "origin"),
            "url": _field(data, "url"),
        }


class FileCenterChildrenSchema(Schema):
    items = fields.List(fields.Nested(FileCenterEntrySchema))
    parent_id = fields.String(allow_none=True)