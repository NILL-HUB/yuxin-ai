from flask_wtf import FlaskForm
from marshmallow import Schema, fields, pre_dump
from sqlalchemy import func
from wtforms import BooleanField, IntegerField, SelectField, StringField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from internal.extension.database_extension import db
from internal.lib.helper import datetime_to_timestamp
from internal.model import AdminUser, KnowledgeBase, KnowledgeDocument


class GetSystemKnowledgeListReq(FlaskForm):
    # 页码，默认第 1 页
    page = IntegerField("page", default=1, validators=[Optional(), NumberRange(min=1, max=9999)])
    # 每页大小，默认 20，项目硬约束最大 100
    page_size = IntegerField("page_size", default=20, validators=[Optional(), NumberRange(min=1, max=100)])
    # 搜索关键词，按知识库名称模糊匹配
    search_word = StringField("search_word", default="", validators=[Optional(), Length(max=255)])


class CreateSystemKnowledgeReq(FlaskForm):
    name = StringField("name", validators=[DataRequired("知识库名称不能为空"), Length(max=255)])
    description = StringField("description", default="", validators=[Optional(), Length(max=2000)])
    # 可见范围：private/internal/public
    visibility_scope = SelectField(
        "visibility_scope",
        choices=[("private", "private"), ("internal", "internal"), ("public", "public")],
        default="internal",
        validators=[Optional()],
    )


class UpdateSystemKnowledgeReq(FlaskForm):
    name = StringField("name", validators=[Optional(), Length(min=1, max=255)])
    description = StringField("description", default="", validators=[Optional(), Length(max=2000)])
    enabled = BooleanField("enabled", validators=[Optional()])
    # 可见范围：private/internal/public
    visibility_scope = SelectField(
        "visibility_scope",
        choices=[("private", "private"), ("internal", "internal"), ("public", "public")],
        validators=[Optional()],
    )


class SystemKnowledgeResp(Schema):
    id = fields.UUID(dump_default="")
    name = fields.String(dump_default="")
    description = fields.String(dump_default="")
    knowledge_scope = fields.String(dump_default="")
    owner_admin_user_id = fields.UUID(allow_none=True)
    enabled = fields.Boolean(dump_default=True)
    created_at = fields.Integer(dump_default=0)
    updated_at = fields.Integer(dump_default=0)
    # 可见范围
    visibility_scope = fields.String(dump_default="internal")
    # 文档数量
    document_count = fields.Integer(dump_default=0)
    # 字符总数
    character_count = fields.Integer(dump_default=0)
    # 创建者名称
    creator_name = fields.String(dump_default="")

    @pre_dump
    def process_data(self, data: KnowledgeBase, **kwargs):
        # 查询该知识库下的文档数量
        document_count = (
            db.session.query(func.count(KnowledgeDocument.id))
            .filter_by(knowledge_base_id=data.id)
            .scalar()
            or 0
        )
        # 查询该知识库下文档的字符总数（KnowledgeDocument 表有 character_count 字段）
        character_count = (
            db.session.query(func.sum(KnowledgeDocument.character_count))
            .filter_by(knowledge_base_id=data.id)
            .scalar()
            or 0
        )
        # 通过 owner_admin_user_id 查询创建者名称，优先取 name，其次 username，查不到则空字符串
        creator_name = ""
        if data.owner_admin_user_id is not None:
            admin_user = (
                db.session.query(AdminUser)
                .filter_by(id=data.owner_admin_user_id)
                .one_or_none()
            )
            if admin_user is not None:
                # 优先使用 name，若为空则回退到 username
                creator_name = admin_user.name or admin_user.username or ""
        return {
            "id": data.id,
            "name": data.name,
            "description": data.description,
            "knowledge_scope": data.knowledge_scope,
            "owner_admin_user_id": data.owner_admin_user_id,
            "enabled": data.enabled,
            "created_at": datetime_to_timestamp(data.created_at),
            "updated_at": datetime_to_timestamp(data.updated_at),
            "visibility_scope": data.visibility_scope,
            "document_count": document_count,
            "character_count": character_count,
            "creator_name": creator_name,
        }


class SystemKnowledgeListResp(Schema):
    # 兼容旧前端：保留 items 和 total
    items = fields.List(fields.Nested(SystemKnowledgeResp))
    total = fields.Integer(dump_default=0)
    # 分页器字段，对齐项目 paginator 模式
    page = fields.Integer(dump_default=1)
    page_size = fields.Integer(dump_default=20)
    total_pages = fields.Integer(dump_default=0)
    total_record = fields.Integer(dump_default=0)
