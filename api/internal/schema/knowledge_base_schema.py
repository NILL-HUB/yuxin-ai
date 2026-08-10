from wtforms import Form
from marshmallow import Schema, fields, pre_dump
from wtforms import StringField, IntegerField, FloatField, BooleanField
from wtforms.validators import (
    DataRequired,
    Length,
    URL,
    Optional,
    AnyOf,
    NumberRange,
)

from internal.entity.dataset_entity import RetrievalStrategy
from internal.lib.helper import datetime_to_timestamp
from internal.model import KnowledgeBase, KnowledgeDocument, KnowledgeSegment
from pkg.paginator import PaginatorReq


def _get_icon(data) -> str:
    """从知识库的 settings JSONB 字段中读取图标 URL"""
    settings = getattr(data, "settings", None) or {}
    if isinstance(settings, dict):
        return settings.get("icon", "") or ""
    return ""


class CreateKnowledgeBaseReq(Form):
    """创建知识库请求"""
    name = StringField("name", validators=[
        DataRequired("知识库名称不能为空"),
        Length(max=100, message="知识库名称长度不能超过100字符"),
    ])
    # icon 非必填：生产环境使用 OSS 存储，未配置时允许为空，由前端显示默认占位图标
    icon = StringField("icon", default="", validators=[
        Optional(),
        URL("知识库图标必须是图片URL地址"),
    ])
    description = StringField("description", default="", validators=[
        Optional(),
        Length(max=2000, message="知识库描述长度不能超过2000字符"),
    ])
    # embedding_model_id 由后端自动选择（维度优先+健康度），用户不能自选
    # 避免维度错位导致整个知识库向量失效


class UpdateKnowledgeBaseReq(Form):
    """更新知识库请求"""
    name = StringField("name", validators=[
        DataRequired("知识库名称不能为空"),
        Length(max=100, message="知识库名称长度不能超过100字符"),
    ])
    # icon 非必填：生产环境使用 OSS 存储，未配置时允许为空
    icon = StringField("icon", default="", validators=[
        Optional(),
        URL("知识库图标必须是图片URL地址"),
    ])
    description = StringField("description", default="", validators=[
        Optional(),
        Length(max=2000, message="知识库描述长度不能超过2000字符"),
    ])
    # embedding_model_id 不允许用户端修改，避免维度错位导致整个知识库向量失效
    # 如需切换 embedding 模型，需 admin 端通过同维度切换接口操作


class GetKnowledgeBasesWithPageReq(PaginatorReq):
    """获取知识库分页列表请求数据"""
    search_word = StringField("search_word", default="", validators=[
        Optional(),
    ])


class GetKnowledgeBaseResp(Schema):
    """获取知识库详情响应结构"""
    id = fields.UUID(dump_default="")
    name = fields.String(dump_default="")
    icon = fields.String(dump_default="")
    description = fields.String(dump_default="")
    document_count = fields.Integer(dump_default=0)
    character_count = fields.Integer(dump_default=0)
    embedding_model_id = fields.String(dump_default="")
    updated_at = fields.Integer(dump_default=0)
    created_at = fields.Integer(dump_default=0)

    @pre_dump
    def process_data(self, data: KnowledgeBase, **kwargs):
        return {
            "id": data.id,
            "name": data.name,
            "icon": _get_icon(data),
            "description": data.description,
            "document_count": getattr(data, "document_count", 0) or 0,
            "character_count": getattr(data, "character_count", 0) or 0,
            "embedding_model_id": str(getattr(data, "embedding_model_id", "") or "") or "",
            "updated_at": datetime_to_timestamp(data.updated_at),
            "created_at": datetime_to_timestamp(data.created_at),
        }


class GetKnowledgeBasesWithPageResp(Schema):
    """获取知识库分页列表响应数据"""
    id = fields.UUID(dump_default="")
    name = fields.String(dump_default="")
    icon = fields.String(dump_default="")
    description = fields.String(dump_default="")
    document_count = fields.Integer(dump_default=0)
    character_count = fields.Integer(dump_default=0)
    creator_name = fields.String(dump_default="")
    creator_avatar = fields.String(dump_default="")
    embedding_model_id = fields.String(dump_default="")
    updated_at = fields.Integer(dump_default=0)
    created_at = fields.Integer(dump_default=0)

    @pre_dump
    def process_data(self, data: KnowledgeBase, **kwargs):
        owner_account = getattr(data, "owner_account", None)
        return {
            "id": data.id,
            "name": data.name,
            "icon": _get_icon(data),
            "description": data.description,
            "document_count": getattr(data, "document_count", 0) or 0,
            "character_count": getattr(data, "character_count", 0) or 0,
            "creator_name": owner_account.name if owner_account else "",
            "creator_avatar": owner_account.avatar if owner_account else "",
            "embedding_model_id": str(getattr(data, "embedding_model_id", "") or "") or "",
            "updated_at": datetime_to_timestamp(data.updated_at),
            "created_at": datetime_to_timestamp(data.created_at),
        }


class HitReq(Form):
    """知识库召回测试请求"""
    query = StringField("query", validators=[
        DataRequired("查询语句不能为空"),
        Length(max=200, message="查询语句的最大长度不能超过200"),
    ])
    retrieval_strategy = StringField("retrieval_strategy", validators=[
        DataRequired("检索策略不能为空"),
        AnyOf([item.value for item in RetrievalStrategy], message="检索策略格式错误"),
    ])
    k = IntegerField("k", validators=[
        DataRequired("最大召回数量不能为空"),
        NumberRange(min=1, max=10, message="最大召回数量的范围在1~10"),
    ])
    score = FloatField("score", validators=[
        NumberRange(min=0, max=0.99, message="最小匹配度范围在0~0.99"),
    ])


class GetKnowledgeDocumentsWithPageReq(PaginatorReq):
    """获取知识库文档分页列表请求"""
    search_word = StringField("search_word", default="", validators=[
        Optional(),
    ])


class GetKnowledgeDocumentsWithPageResp(Schema):
    """获取知识库文档分页列表响应结构"""
    id = fields.UUID(dump_default="")
    name = fields.String(dump_default="")
    character_count = fields.Integer(dump_default=0)
    segment_count = fields.Integer(dump_default=0)
    segment_character_count = fields.Integer(dump_default=0)
    status = fields.String(dump_default="")
    error = fields.String(dump_default="")
    updated_at = fields.Integer(dump_default=0)
    created_at = fields.Integer(dump_default=0)

    @pre_dump
    def process_data(self, data: KnowledgeDocument, **kwargs):
        # segment_count/segment_character_count 由 admin 列表实时统计后 setattr 注入，
        # 未注入时回退到文档自身字段（兼容用户端）
        return {
            "id": data.id,
            "name": data.name,
            "character_count": data.character_count,
            "segment_count": getattr(data, "segment_count", 0),
            "segment_character_count": getattr(data, "segment_character_count", data.character_count or 0),
            "status": data.status,
            "error": data.error,
            "updated_at": datetime_to_timestamp(data.updated_at),
            "created_at": datetime_to_timestamp(data.created_at),
        }


class GetKnowledgeDocumentResp(Schema):
    """获取知识库文档详情响应结构"""
    id = fields.UUID(dump_default="")
    knowledge_base_id = fields.UUID(dump_default="")
    name = fields.String(dump_default="")
    character_count = fields.Integer(dump_default=0)
    segment_count = fields.Integer(dump_default=0)
    status = fields.String(dump_default="")
    error = fields.String(dump_default="")
    updated_at = fields.Integer(dump_default=0)
    created_at = fields.Integer(dump_default=0)

    @pre_dump
    def process_data(self, data: KnowledgeDocument, **kwargs):
        return {
            "id": data.id,
            "knowledge_base_id": data.knowledge_base_id,
            "name": data.name,
            "character_count": data.character_count,
            "segment_count": getattr(data, "segment_count", 0) or 0,
            "status": data.status,
            "error": data.error,
            "updated_at": datetime_to_timestamp(data.updated_at),
            "created_at": datetime_to_timestamp(data.created_at),
        }


class GetKnowledgeSegmentsWithPageReq(PaginatorReq):
    """获取文档片段分页列表请求"""
    search_word = StringField("search_word", default="", validators=[
        Optional(),
    ])


class GetKnowledgeSegmentsWithPageResp(Schema):
    """获取文档片段分页列表响应结构"""
    id = fields.UUID(dump_default="")
    knowledge_base_id = fields.UUID(dump_default="")
    knowledge_document_id = fields.UUID(dump_default="")
    position = fields.Integer(dump_default=0)
    content = fields.String(dump_default="")
    keywords = fields.List(fields.String, dump_default=[])
    character_count = fields.Integer(dump_default=0)
    token_count = fields.Integer(dump_default=0)
    hit_count = fields.Integer(dump_default=0)
    enabled = fields.Boolean(dump_default=False)
    status = fields.String(dump_default="")
    updated_at = fields.Integer(dump_default=0)
    created_at = fields.Integer(dump_default=0)

    @pre_dump
    def process_data(self, data: KnowledgeSegment, **kwargs):
        return {
            "id": data.id,
            "knowledge_base_id": data.knowledge_base_id,
            "knowledge_document_id": data.knowledge_document_id,
            "position": data.position,
            "content": data.content,
            "keywords": data.keywords or [],
            "character_count": data.character_count,
            "token_count": data.token_count,
            "hit_count": data.hit_count,
            "enabled": data.enabled,
            "status": data.status,
            "updated_at": datetime_to_timestamp(data.updated_at),
            "created_at": datetime_to_timestamp(data.created_at),
        }


class UpdateKnowledgeSegmentReq(Form):
    """更新文档片段请求"""
    enabled = BooleanField("enabled", validators=[
        Optional(),
    ])
    content = StringField("content", validators=[
        Optional(),
        Length(max=10000, message="片段内容长度不能超过10000字符"),
    ])
