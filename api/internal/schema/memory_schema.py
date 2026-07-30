from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import IntegerField, StringField
from wtforms.validators import DataRequired, Length, NumberRange, Optional


class MemoryWriteReq(FlaskForm):
    """记忆写入请求表单。"""

    content = StringField("content", validators=[DataRequired(), Length(max=8000)])
    memory_type = StringField(
        "memory_type",
        default="user_message",
        validators=[Optional(), Length(max=64)],
    )


class MemoryWriteResp(Schema):
    """记忆写入响应。"""

    status = fields.String()
    memory_id = fields.String(allow_none=True)
    created_at = fields.String()
    score = fields.Float()
    entity_count = fields.Integer(allow_none=True)
    edge_count = fields.Integer(allow_none=True)
    vector_id = fields.String(allow_none=True)


class MemoryRetrieveReq(FlaskForm):
    """记忆检索请求表单。"""

    query = StringField("query", validators=[DataRequired(), Length(max=4000)])
    top_k = IntegerField("top_k", default=20, validators=[Optional(), NumberRange(min=1, max=100)])
    time_range_days = IntegerField(
        "time_range_days", default=None, validators=[Optional(), NumberRange(min=1)]
    )
    budget_tokens = IntegerField(
        "budget_tokens", default=2000, validators=[Optional(), NumberRange(min=100, max=8000)]
    )


class MemoryRetrieveResp(Schema):
    """记忆检索响应。"""

    results = fields.List(fields.Dict())
    summary = fields.String(allow_none=True)
    intent = fields.String(allow_none=True)
    retrieval_path = fields.String()
    latency_ms = fields.Float()


class MemoryDigestResp(Schema):
    """记忆 Digest 响应。"""

    user_id = fields.String()
    digest = fields.String()
    cached = fields.Boolean()


class ConsolidationResp(Schema):
    """巩固执行响应。"""

    user_id = fields.String()
    success = fields.Boolean()
    total_items = fields.Integer()
    phase_results = fields.Dict()
    errors = fields.List(fields.String())
    task_id = fields.String(allow_none=True)


# =========================================================
# D4 图谱 API + 记忆 CRUD API schemas
# =========================================================


class EditMemoryReq(FlaskForm):
    """编辑记忆请求表单。"""

    new_content = StringField(
        "new_content",
        validators=[DataRequired(), Length(min=1, max=10000)],
    )


class DecayReq(FlaskForm):
    """手动降权请求表单。"""

    decay_factor = StringField(
        "decay_factor",
        default="0.5",
        validators=[Optional()],
    )
    reason = StringField("reason", validators=[Optional(), Length(max=500)])


class GraphResp(Schema):
    """记忆图谱聚类视图响应。"""

    user_id = fields.String()
    clusters = fields.List(fields.Dict())
    total_nodes = fields.Integer()


class ClusterSubgraphResp(Schema):
    """聚类子图响应。"""

    nodes = fields.List(fields.Dict())
    edges = fields.List(fields.Dict())
    truncated = fields.Boolean()


class MemoryDetailResp(Schema):
    """单条记忆详情响应。"""

    memory_id = fields.String()
    content = fields.String()
    memory_type = fields.String(allow_none=True)
    confidence = fields.Integer(allow_none=True)
    source_conversation_id = fields.String(allow_none=True)
    created_at = fields.String(allow_none=True)
    last_accessed_at = fields.String(allow_none=True)
    related = fields.List(fields.Dict())


# =========================================================
# E2 技能列表 API schemas
# =========================================================


class SkillListResp(Schema):
    """技能列表响应。"""

    user_id = fields.String()
    skills = fields.List(fields.Dict())
    total = fields.Integer()
