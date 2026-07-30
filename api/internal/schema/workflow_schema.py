from flask_wtf import FlaskForm
from marshmallow import Schema, fields, pre_dump
from wtforms import BooleanField, StringField
from wtforms.validators import DataRequired, Length, Regexp, URL, Optional, AnyOf, ValidationError
from internal.core.workflow.entities.workflow_entity import WORKFLOW_CONFIG_NAME_PATTERN
from internal.entity.workflow_entity import WorkflowStatus
from internal.lib.helper import datetime_to_timestamp
from internal.model import Workflow
from internal.schema import DictField, ListField
from pkg.paginator import PaginatorReq


class CreateWorkflowReq(FlaskForm):
    """创建工作流基础请求"""
    name = StringField("name", validators=[
        DataRequired("工作流名称不能为空"),
        Length(max=50, message="工作流名称长度不能超过50"),
    ])
    tool_call_name = StringField("tool_call_name", validators=[
        DataRequired("英文名称不能为空"),
        Length(max=50, message="英文名称不能超过50个字符"),
        Regexp(WORKFLOW_CONFIG_NAME_PATTERN, message="英文名称仅支持字母、数字和下划线，且以字母/下划线为开头")
    ])
    icon = StringField("icon", validators=[
        DataRequired("工作流图标不能为空"),
        URL(message="工作流图标必须是图片URL地址"),
    ])
    description = StringField("description", validators=[
        DataRequired("工作流描述不能为空"),
        Length(max=1024, message="工作流描述不能超过1024个字符")
    ])
    task_keywords = ListField("task_keywords", default=[])

    def validate_task_keywords(self, field):
        """校验 task_keywords 必须是字符串列表。"""
        if field.data in (None, []):
            return
        if not isinstance(field.data, list):
            raise ValidationError("task_keywords 必须是数组")
        for kw in field.data:
            if not isinstance(kw, str):
                raise ValidationError("task_keywords 里的每个元素都必须是字符串")


class UpdateWorkflowReq(FlaskForm):
    """创建工作流基础请求"""
    name = StringField("name", validators=[
        DataRequired("工作流名称不能为空"),
        Length(max=50, message="工作流名称长度不能超过50"),
    ])
    tool_call_name = StringField("tool_call_name", validators=[
        DataRequired("英文名称不能为空"),
        Length(max=50, message="英文名称不能超过50个字符"),
        Regexp(WORKFLOW_CONFIG_NAME_PATTERN, message="英文名称仅支持字母、数字和下划线，且以字母/下划线为开头")
    ])
    icon = StringField("icon", validators=[
        DataRequired("工作流图标不能为空"),
        URL(message="工作流图标必须是图片URL地址"),
    ])
    description = StringField("description", validators=[
        DataRequired("工作流描述不能为空"),
        Length(max=1024, message="工作流描述不能超过1024个字符")
    ])
    task_keywords = ListField("task_keywords", default=[])

    def validate_task_keywords(self, field):
        """校验 task_keywords 必须是字符串列表。"""
        if field.data in (None, []):
            return
        if not isinstance(field.data, list):
            raise ValidationError("task_keywords 必须是数组")
        for kw in field.data:
            if not isinstance(kw, str):
                raise ValidationError("task_keywords 里的每个元素都必须是字符串")


class GetWorkflowResp(Schema):
    """获取工作流详情响应结构"""
    id = fields.UUID(dump_default="")
    name = fields.String(dump_default="")
    tool_call_name = fields.String(dump_default="")
    icon = fields.String(dump_default="")
    description = fields.String(dump_default="")
    status = fields.String(dump_default="")
    is_debug_passed = fields.Boolean(dump_default=False)
    is_public = fields.Boolean(dump_default=False)
    node_count = fields.Integer(dump_default=0)
    task_keywords = fields.List(fields.String(), dump_default=[])
    published_at = fields.Integer(dump_default=0)
    updated_at = fields.Integer(dump_default=0)
    created_at = fields.Integer(dump_default=0)

    @pre_dump
    def process_data(self, data: Workflow, **kwargs):
        return {
            "id": data.id,
            "name": data.name,
            "tool_call_name": data.tool_call_name,
            "icon": data.icon,
            "description": data.description,
            "status": data.status,
            "is_debug_passed": data.is_debug_passed,
            "is_public": data.is_public,
            "node_count": len(data.draft_graph.get("nodes", [])),
            "task_keywords": list(getattr(data, "task_keywords", None) or []),
            "published_at": datetime_to_timestamp(data.published_at),
            "updated_at": datetime_to_timestamp(data.updated_at),
            "created_at": datetime_to_timestamp(data.created_at),
        }


class GetWorkflowsWithPageReq(PaginatorReq):
    """获取工作流分页列表数据请求结构"""
    status = StringField("status", default="", validators=[
        Optional(),
        AnyOf(WorkflowStatus.__members__.values(), message="工作流状态格式错误")
    ])
    search_word = StringField("search_word", default="", validators=[Optional()])


class GetWorkflowsWithPageResp(Schema):
    """获取工作流分页列表数据响应结构"""
    id = fields.UUID(dump_default="")
    name = fields.String(dump_default="")
    tool_call_name = fields.String(dump_default="")
    icon = fields.String(dump_default="")
    description = fields.String(dump_default="")
    status = fields.String(dump_default="")
    is_debug_passed = fields.Boolean(dump_default=False)
    is_public = fields.Boolean(dump_default=False)
    node_count = fields.Integer(dump_default=0)
    task_keywords = fields.List(fields.String(), dump_default=[])
    creator_name = fields.String(dump_default="")
    creator_avatar = fields.String(dump_default="")
    published_at = fields.Integer(dump_default=0)
    updated_at = fields.Integer(dump_default=0)
    created_at = fields.Integer(dump_default=0)

    @pre_dump
    def process_data(self, data: Workflow, **kwargs):
        return {
            "id": data.id,
            "name": data.name,
            "tool_call_name": data.tool_call_name,
            "icon": data.icon,
            "description": data.description,
            "status": data.status,
            "is_debug_passed": data.is_debug_passed,
            "is_public": data.is_public,
            "node_count": len(data.draft_graph.get("nodes", [])),
            "task_keywords": list(getattr(data, "task_keywords", None) or []),
            "creator_name": data.account.name if data.account else "",
            "creator_avatar": data.account.avatar if data.account else "",
            "published_at": datetime_to_timestamp(data.published_at),
            "updated_at": datetime_to_timestamp(data.updated_at),
            "created_at": datetime_to_timestamp(data.created_at),
        }


class ImportWorkflowReq(FlaskForm):
    """导入工作流请求

    支持两种 body 格式：
    1. 信封格式（推荐）：{"json_data": {...}, "overwrite_name": false}
    2. 直接格式：直接 POST 导出的工作流 JSON（format=openagent-workflow），
       此时 overwrite_name 从查询参数 ?overwrite_name=true 读取。
    """
    json_data = DictField("json_data", default=None)
    overwrite_name = BooleanField("overwrite_name", default=False, validators=[Optional()])


class ImportWorkflowResp(Schema):
    """导入工作流响应结构"""
    id = fields.UUID(dump_default="")
    name = fields.String(dump_default="")
    tool_call_name = fields.String(dump_default="")
    status = fields.String(dump_default="")
