"""Admin Prompt 模板管理 handler。

提供 prompt 模板的只读列表、详情、编辑、重置功能。
- 列表/详情：只读，展示 YAML 同步和 admin 自定义的 prompt
- 编辑：source=catalog 时 fork 为 custom 副本，不覆盖 YAML 来源
- 重置：删除 custom 副本，恢复 catalog 版本
"""
from dataclasses import dataclass

from flask import request
from injector import inject

from internal.middleware import admin_login_required
from internal.service.prompt_sync_service import PromptSyncService
from pkg.response import success_json, validate_error_json

from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField
from wtforms.validators import Optional, Length
from marshmallow import Schema, fields


class GetPromptTemplatesReq(FlaskForm):
    category = StringField("category", default="", validators=[Optional(), Length(max=64)])


class UpdatePromptTemplateReq(FlaskForm):
    content = StringField("content", default="", validators=[Optional()])
    description = StringField("description", default="", validators=[Optional(), Length(max=512)])
    enabled = BooleanField("enabled", default=True)


class PromptTemplateItemSchema(Schema):
    prompt_key = fields.String()
    name = fields.String()
    category = fields.String()
    description = fields.String()
    content = fields.String()
    variables = fields.Dict()
    source = fields.String()
    version = fields.Integer()
    updated_at = fields.Integer(allow_none=True)


class PromptTemplateDetailSchema(Schema):
    prompt_key = fields.String()
    name = fields.String()
    category = fields.String()
    description = fields.String()
    content = fields.String()
    variables = fields.Dict()
    source = fields.String()
    source_path = fields.String(allow_none=True)
    content_hash = fields.String()
    enabled = fields.Boolean()
    version = fields.Integer()
    updated_at = fields.Integer(allow_none=True)
    created_at = fields.Integer(allow_none=True)


class PromptTemplateListSchema(Schema):
    items = fields.List(fields.Nested(PromptTemplateItemSchema))


@inject
@dataclass
class AdminPromptTemplateHandler:
    """Prompt 模板管理 handler。"""

    prompt_sync_service: PromptSyncService

    @admin_login_required
    def list_templates(self):
        """GET /admin/prompt-templates 列出所有 prompt 模板。"""
        form = GetPromptTemplatesReq(request.args)
        if not form.validate():
            return validate_error_json(form.errors)
        category = (form.category.data or "").strip() or None
        items = self.prompt_sync_service.list_prompts(category=category)
        resp = PromptTemplateListSchema()
        return success_json(resp.dump({"items": items}))

    @admin_login_required
    def get_template(self, prompt_key: str):
        """GET /admin/prompt-templates/<prompt_key> 获取详情。"""
        detail = self.prompt_sync_service.get_prompt_detail(prompt_key)
        if detail is None:
            from internal.exception import NotFoundException
            raise NotFoundException("Prompt 模板不存在")
        resp = PromptTemplateDetailSchema()
        return success_json(resp.dump(detail))

    @admin_login_required
    def update_template(self, prompt_key: str):
        """PATCH /admin/prompt-templates/<prompt_key> 更新 prompt。

        source=catalog 时自动 fork 为 custom 副本，不覆盖 YAML 来源。
        source=custom 时直接更新。
        """
        form = UpdatePromptTemplateReq()
        if not form.validate():
            return validate_error_json(form.errors)
        payload = request.get_json(silent=True) or {}
        content = payload.get("content")
        description = payload.get("description")
        enabled = payload.get("enabled")
        result = self.prompt_sync_service.update_prompt(
            prompt_key,
            content=content,
            description=description,
            enabled=enabled,
        )
        if result is None:
            from internal.exception import NotFoundException
            raise NotFoundException("Prompt 模板不存在")
        resp = PromptTemplateDetailSchema()
        return success_json(resp.dump(result))

    @admin_login_required
    def reset_template(self, prompt_key: str):
        """POST /admin/prompt-templates/<prompt_key>/reset 重置为 YAML 版本。"""
        result = self.prompt_sync_service.reset_prompt(prompt_key)
        if result is None:
            from internal.exception import NotFoundException
            raise NotFoundException("Prompt 模板不存在")
        resp = PromptTemplateDetailSchema()
        return success_json(resp.dump(result))
