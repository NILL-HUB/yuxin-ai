from __future__ import annotations

from flask_wtf import FlaskForm
from marshmallow import Schema, fields, pre_dump
from wtforms import BooleanField, IntegerField, StringField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError

from internal.lib.helper import datetime_to_timestamp
from internal.schema import DictField, ListField
from pkg.paginator import PaginatorReq


class CreateSkillPackageReq(FlaskForm):
    """管理员创建技能包请求。"""

    source_key = StringField(
        "source_key",
        validators=[
            DataRequired("source_key 不能为空"),
            Length(min=1, max=255, message="source_key 长度范围在1-255"),
        ],
    )
    name = StringField("name", validators=[Optional(), Length(max=255)])
    label = StringField("label", validators=[Optional(), Length(max=255)])
    description = StringField("description", validators=[Optional()])
    category = StringField("category", validators=[Optional(), Length(max=64)])
    icon = StringField("icon", validators=[Optional(), Length(max=1024)])
    executor_type = StringField(
        "executor_type",
        default="prompt",
        validators=[Optional(), Length(max=64)],
    )
    enabled = BooleanField("enabled", default=True)
    readme = StringField("readme", validators=[Optional()])
    skill_code = StringField("skill_code", validators=[Optional()])
    capabilities = DictField("capabilities", validators=[Optional()])


class UpdateSkillPackageReq(FlaskForm):
    """管理员更新技能包请求。source_key 不可修改。"""

    name = StringField("name", validators=[Optional(), Length(max=255)])
    label = StringField("label", validators=[Optional(), Length(max=255)])
    description = StringField("description", validators=[Optional()])
    category = StringField("category", validators=[Optional(), Length(max=64)])
    icon = StringField("icon", validators=[Optional(), Length(max=1024)])
    executor_type = StringField(
        "executor_type",
        validators=[Optional(), Length(max=64)],
    )
    enabled = BooleanField("enabled", validators=[Optional()])
    readme = StringField("readme", validators=[Optional()])
    skill_code = StringField("skill_code", validators=[Optional()])
    capabilities = DictField("capabilities", validators=[Optional()])


class ImportCatalogSkillReq(FlaskForm):
    """从 catalog 导入技能包请求。"""

    source_key = StringField(
        "source_key",
        validators=[
            DataRequired("source_key 不能为空"),
            Length(min=1, max=255, message="source_key 长度范围在1-255"),
        ],
    )


class CatalogPackageResp(Schema):
    """catalog 技能包摘要（用于导入选择器）。"""

    source_key = fields.String(dump_default="")
    name = fields.String(dump_default="")
    label = fields.String(dump_default="")
    description = fields.String(dump_default="")
    category = fields.String(dump_default="")
    executor_type = fields.String(dump_default="prompt")
    version = fields.Integer(dump_default=1)
    tool_count = fields.Integer(dump_default=0)
    imported = fields.Boolean(dump_default=False)


class GetSkillsWithPageReq(PaginatorReq):
    """获取技能包分页列表请求。"""

    page_size = IntegerField(
        "page_size",
        default=20,
        validators=[Optional(), NumberRange(min=1, max=100, message="每页数据的条数范围在1-100")],
    )
    search_word = StringField("search_word", default="", validators=[Optional()])
    category = StringField("category", default="", validators=[Optional(), Length(max=64)])


class RollbackSkillPackageReq(FlaskForm):
    """技能包回滚请求。"""

    version = IntegerField(
        "version",
        validators=[
            DataRequired("技能版本不能为空"),
            NumberRange(min=1, message="技能版本必须大于0"),
        ],
    )


class SkillToolInputResp(Schema):
    name = fields.String()
    type = fields.String()
    required = fields.Boolean()
    description = fields.String()


class SkillToolResp(Schema):
    name = fields.String()
    label = fields.String()
    description = fields.String()
    entrypoint = fields.String()
    inputs = fields.List(fields.Nested(SkillToolInputResp), dump_default=[])


class SkillVersionResp(Schema):
    id = fields.UUID(dump_default="")
    skill_package_id = fields.UUID(dump_default="")
    version = fields.Integer(dump_default=0)
    checksum = fields.String(dump_default="")
    sync_status = fields.String(dump_default="")
    sync_error = fields.String(dump_default="")
    is_current_version = fields.Boolean(dump_default=False)
    summary = fields.String(dump_default="")
    tool_count = fields.Integer(dump_default=0)
    created_at = fields.Integer(dump_default=0)
    updated_at = fields.Integer(dump_default=0)


class SkillPackageResp(Schema):
    id = fields.UUID(dump_default="")
    source_key = fields.String(dump_default="")
    source_path = fields.String(dump_default="")
    name = fields.String(dump_default="")
    label = fields.String(dump_default="")
    icon = fields.String(dump_default="")
    description = fields.String(dump_default="")
    readme = fields.String(dump_default="")
    category = fields.String(dump_default="")
    tags = fields.List(fields.String(), dump_default=[])
    capabilities = fields.Dict(dump_default={})
    executor_type = fields.String(dump_default="scf")
    tool_count = fields.Integer(dump_default=0)
    tools = fields.List(fields.Nested(SkillToolResp), dump_default=[])
    enabled = fields.Boolean(dump_default=True)
    current_version = fields.Integer(dump_default=1)
    sync_status = fields.String(dump_default="pending")
    sync_error = fields.String(dump_default="")
    skill_code = fields.String(dump_default="")
    created_at = fields.Integer(dump_default=0)
    updated_at = fields.Integer(dump_default=0)

    @pre_dump
    def process_data(self, data, **kwargs):
        if isinstance(data, dict):
            return data
        # 从版本记录中提取 skill_code（仅 scf 类型）
        skill_code = ""
        try:
            executor_type = str(getattr(data, "executor_type", "") or "")
            if executor_type == "scf" and hasattr(data, "versions") and data.versions:
                current_version_record = None
                for ver in data.versions:
                    if ver.version == data.current_version:
                        current_version_record = ver
                        break
                if current_version_record and isinstance(current_version_record.bundle, dict):
                    skill_code = str(current_version_record.bundle.get("skill.py", "") or "")
        except Exception:
            skill_code = ""
        return {
            "id": data.id,
            "source_key": data.source_key,
            "source_path": data.source_path,
            "name": data.name,
            "label": data.label,
            "icon": data.icon,
            "description": data.description,
            "readme": getattr(data, "readme", ""),
            "category": data.category,
            "tags": data.tags or [],
            "capabilities": data.capabilities or {},
            "executor_type": data.executor_type,
            "tool_count": getattr(data, "tool_count", 0),
            "tools": getattr(data, "tools", []),
            "enabled": getattr(data, "enabled", True),
            "current_version": getattr(data, "current_version", 1),
            "sync_status": getattr(data, "sync_status", "pending"),
            "sync_error": getattr(data, "sync_error", ""),
            "skill_code": skill_code,
            "created_at": datetime_to_timestamp(data.created_at),
            "updated_at": datetime_to_timestamp(data.updated_at),
        }


class GetSkillsCategoriesResp(Schema):
    categories = fields.List(fields.Dict())

    class Meta:
        strict = True

    def dump(self, obj, **kwargs):
        return {"categories": obj.get("categories", []) if isinstance(obj, dict) else []}
