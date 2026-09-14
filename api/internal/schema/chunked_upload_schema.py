"""分片上传请求/响应 schema。"""
from marshmallow import Schema, fields


class ChunkedInitReq(Schema):
    """初始化分片会话。"""

    filename = fields.String(required=True)
    total_size = fields.Integer(required=True)
    chunk_size = fields.Integer(required=True)
    total_chunks = fields.Integer(required=True)
    fingerprint = fields.String(load_default="")
    knowledge_base_id = fields.String(load_default="")


class ChunkedCompleteReq(Schema):
    """完成分片上传。"""

    session_id = fields.String(required=True)
    knowledge_base_id = fields.String(load_default="")
