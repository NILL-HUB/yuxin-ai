from wtforms import Form
from marshmallow import Schema, fields, pre_dump
from wtforms import IntegerField, StringField
from wtforms.validators import Length, NumberRange, Optional

from internal.lib.helper import datetime_to_timestamp


class GetRecycleBinListReq(Form):
    page = IntegerField("page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=100)])
    # 资源类型筛选：knowledge_base/system_prompt/app/workflow/skill/mcp/api_tool
    resource_type = StringField("resource_type", default="", validators=[Optional(), Length(max=64)])
    # 删除来源筛选：admin=管理员内容 / user=用户内容（空=全部）
    deleted_by_type = StringField("deleted_by_type", default="", validators=[Optional(), Length(max=16)])
    # 状态：pending=待销毁 / restored=已恢复 / expired=已销毁
    status = StringField("status", default="pending", validators=[Optional(), Length(max=32)])
    search_word = StringField("search_word", default="", validators=[Optional(), Length(max=255)])


class RecycleBinItemSchema(Schema):
    id = fields.Integer()
    resource_type = fields.String()
    resource_id = fields.String()
    resource_key = fields.String()
    resource_name = fields.String()
    deleted_by = fields.String(allow_none=True)
    deleted_by_name = fields.String(allow_none=True)
    deleted_by_type = fields.String(allow_none=True)
    deleted_at = fields.Integer(allow_none=True)
    retention_days = fields.Integer()
    expire_at = fields.Integer(allow_none=True)
    status = fields.String()
    remark = fields.String()
    # 本机文件（os_file）删除时的设备信息（IP + 系统用户名），用于跨设备恢复提示
    device_info = fields.Dict(allow_none=True)

    @pre_dump
    def process_data(self, data, **kwargs):
        snapshot = data.snapshot if isinstance(getattr(data, "snapshot", None), dict) else {}
        return {
            "id": data.id,
            "resource_type": data.resource_type,
            "resource_id": data.resource_id,
            "resource_key": data.resource_key,
            "resource_name": data.resource_name,
            "deleted_by": data.deleted_by,
            "deleted_by_name": getattr(data, "deleted_by_name", None),
            "deleted_by_type": data.deleted_by_type,
            "deleted_at": datetime_to_timestamp(data.deleted_at),
            "retention_days": data.retention_days,
            "expire_at": datetime_to_timestamp(data.expire_at),
            "status": data.status,
            "remark": data.remark,
            "device_info": snapshot.get("device_info"),
        }


class RecycleBinDetailSchema(RecycleBinItemSchema):
    snapshot = fields.Dict()


class RecycleBinListSchema(Schema):
    items = fields.List(fields.Nested(RecycleBinItemSchema))
    total = fields.Integer(dump_default=0)
    page = fields.Integer(dump_default=1)
    page_size = fields.Integer(dump_default=20)
    total_pages = fields.Integer(dump_default=0)
    total_record = fields.Integer(dump_default=0)
