from __future__ import annotations

from wtforms import Form
from marshmallow import Schema, fields
from wtforms import BooleanField, IntegerField, StringField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, URL, ValidationError

from internal.entity.mcp_entity import MCP_CATEGORY_OPTIONS
from internal.schema import DictField, ListField
from pkg.paginator import PaginatorReq


_SUPPORTED_TRANSPORTS = {"http", "sse", "streamable_http", "streamable-http", "stdio"}


class GetMcpProvidersWithPageReq(PaginatorReq):
    """获取 MCP 列表请求。"""

    search_word = StringField("search_word", default="", validators=[Optional()])
    category = StringField("category", default="", validators=[Optional(), Length(max=64)])


class CreateMcpProviderReq(Form):
    """创建 MCP 提供者请求。"""

    name = StringField(
        "name",
        validators=[
            DataRequired("MCP 名称不能为空"),
            Length(max=255, message="MCP 名称长度不能超过255个字符"),
        ],
    )
    label = StringField(
        "label",
        validators=[
            Optional(),
            Length(max=255, message="MCP 标题长度不能超过255个字符"),
        ],
    )
    icon = StringField(
        "icon",
        validators=[
            Optional(),
            URL(message="MCP 图标必须是有效的URL链接"),
        ],
    )
    description = StringField(
        "description",
        validators=[
            DataRequired("MCP 描述不能为空"),
            Length(max=1000, message="MCP 描述长度不能超过1000个字符"),
        ],
    )
    category = StringField("category", default="other", validators=[Optional(), Length(max=64)])
    transport = StringField("transport", default="streamable_http", validators=[Optional()])
    url = StringField("url", default="", validators=[Optional(), Length(max=1024)])
    command = StringField("command", default="", validators=[Optional(), Length(max=1024)])
    headers = ListField("headers", default=[])
    tool_names = ListField("tool_names", default=[])
    args = ListField("args", default=[])
    env = DictField("env", default={})
    timeout_seconds = IntegerField(
        "timeout_seconds",
        default=30,
        validators=[Optional(), NumberRange(min=1, max=600, message="超时时间范围必须在1~600秒之间")],
    )
    task_keywords = ListField("task_keywords", default=[])

    def validate_transport(self, field: StringField) -> None:
        normalized = str(field.data or "").strip()
        if not normalized:
            return
        if normalized.lower() not in _SUPPORTED_TRANSPORTS:
            raise ValidationError("transport 仅支持 http、sse、streamable_http 或 stdio")

    def validate_command(self, field: StringField) -> None:
        """stdio 模式下 command 必填。"""
        transport = str(self.transport.data or "").strip().lower()
        command = str(field.data or "").strip()
        if transport == "stdio" and not command:
            raise ValidationError("stdio 模式下 command 不能为空")

    def validate_headers(self, field: ListField) -> None:
        if field.data in (None, []):
            return
        if not isinstance(field.data, list):
            raise ValidationError("headers 必须是数组")
        for header in field.data:
            if not isinstance(header, dict):
                raise ValidationError("headers 里的每个元素都必须是对象")
            if set(header.keys()) != {"key", "value"}:
                raise ValidationError("headers 里的每个元素都必须只包含 key 和 value")

    def validate_tool_names(self, field: ListField) -> None:
        if field.data in (None, []):
            return
        if not isinstance(field.data, list):
            raise ValidationError("tool_names 必须是数组")

    def validate_args(self, field: ListField) -> None:
        if field.data in (None, []):
            return
        if not isinstance(field.data, list):
            raise ValidationError("args 必须是数组")

    def validate_env(self, field: DictField) -> None:
        if field.data in (None, {}):
            return
        if not isinstance(field.data, dict):
            raise ValidationError("env 必须是对象")

    def validate_task_keywords(self, field: ListField) -> None:
        if field.data in (None, []):
            return
        if not isinstance(field.data, list):
            raise ValidationError("task_keywords 必须是数组")
        for kw in field.data:
            if not isinstance(kw, str):
                raise ValidationError("task_keywords 里的每个元素都必须是字符串")


class UpdateMcpProviderReq(CreateMcpProviderReq):
    """更新 MCP 提供者请求。"""


class ImportMcpJsonReq(Form):
    """标准 mcp.json 批量导入请求。

    请求格式：application/json
        - config_json: 标准 mcp.json 文本（必需）
        - overwrite: 是否覆盖已存在的同名 server（可选，默认 false）
    """

    config_json = StringField(
        "config_json",
        validators=[
            DataRequired("config_json 不能为空"),
            Length(min=1, message="config_json 不能为空"),
        ],
    )
    overwrite = BooleanField("overwrite", default=False)


class ImportMcpJsonConfigReq(Form):
    """单个 MCP server JSON 配置导入请求（非标准 mcp.json 格式）。

    请求格式：application/json
        - config_json: 单个 MCP server 的 JSON 配置文本（必需）
        - overwrite: 是否覆盖已存在的同名 provider（可选，默认 false）
    """

    config_json = StringField(
        "config_json",
        validators=[
            DataRequired("config_json 不能为空"),
            Length(min=1, message="config_json 不能为空"),
        ],
    )
    overwrite = BooleanField("overwrite", default=False)


class PreviewMcpUrlReq(Form):
    """URL 预览请求：调用 tools/list 预览远端工具列表，不写 DB。

    请求格式：application/json
        - url: MCP 服务 URL（必需）
        - transport: 传输方式（可选，默认 http）
        - headers: 请求头列表（可选）
    """

    url = StringField(
        "url",
        validators=[
            DataRequired("url 不能为空"),
            Length(min=1, max=2048, message="url 长度范围在1-2048"),
        ],
    )
    transport = StringField("transport", default="http", validators=[Optional()])
    headers = ListField("headers", default=[])

    def validate_transport(self, field: StringField) -> None:
        normalized = str(field.data or "").strip()
        if not normalized:
            return
        if normalized.lower() not in {"http", "sse", "streamable_http", "streamable-http"}:
            raise ValidationError("预览仅支持 http、sse、streamable_http transport")

    def validate_headers(self, field: ListField) -> None:
        if field.data in (None, []):
            return
        if not isinstance(field.data, list):
            raise ValidationError("headers 必须是数组")
        for header in field.data:
            if not isinstance(header, dict):
                raise ValidationError("headers 里的每个元素都必须是对象")
            if set(header.keys()) != {"key", "value"}:
                raise ValidationError("headers 里的每个元素都必须只包含 key 和 value")


class ImportMcpUrlReq(Form):
    """URL 一键导入请求：先预览校验可达，再创建 DB 记录。

    请求格式：application/json
        - url: MCP 服务 URL（必需）
        - name: MCP 名称（必需）
        - description: 描述（可选）
        - transport: 传输方式（可选，默认 http）
        - headers: 请求头列表（可选）
        - category: 分类（可选）
        - icon: 图标 URL（可选）
    """

    url = StringField(
        "url",
        validators=[
            DataRequired("url 不能为空"),
            Length(min=1, max=2048, message="url 长度范围在1-2048"),
        ],
    )
    name = StringField(
        "name",
        validators=[
            DataRequired("MCP 名称不能为空"),
            Length(max=255, message="MCP 名称长度不能超过255个字符"),
        ],
    )
    description = StringField("description", validators=[Optional(), Length(max=1000)])
    transport = StringField("transport", default="http", validators=[Optional()])
    headers = ListField("headers", default=[])
    category = StringField("category", default="other", validators=[Optional(), Length(max=64)])
    icon = StringField("icon", validators=[Optional(), Length(max=1024)])

    def validate_transport(self, field: StringField) -> None:
        normalized = str(field.data or "").strip()
        if not normalized:
            return
        if normalized.lower() not in {"http", "sse", "streamable_http", "streamable-http"}:
            raise ValidationError("URL 导入仅支持 http、sse、streamable_http transport")

    def validate_headers(self, field: ListField) -> None:
        if field.data in (None, []):
            return
        if not isinstance(field.data, list):
            raise ValidationError("headers 必须是数组")
        for header in field.data:
            if not isinstance(header, dict):
                raise ValidationError("headers 里的每个元素都必须是对象")
            if set(header.keys()) != {"key", "value"}:
                raise ValidationError("headers 里的每个元素都必须只包含 key 和 value")


class ImportMcpResultResp(Schema):
    """MCP 批量导入结果响应（mcp.json / JSON 配置导入）。"""

    imported = fields.List(fields.Dict(), dump_default=[])
    skipped = fields.List(fields.Dict(), dump_default=[])
    failed = fields.List(fields.Dict(), dump_default=[])


class PreviewMcpToolResp(Schema):
    """预览返回的单个工具摘要。"""

    name = fields.String(dump_default="")
    label = fields.String(dump_default="")
    description = fields.String(dump_default="")


class PreviewMcpUrlResp(Schema):
    """URL 预览响应。"""

    tools = fields.List(fields.Nested(PreviewMcpToolResp), dump_default=[])
    server_info = fields.Dict(dump_default={})


class McpCategoryResp(Schema):
    id = fields.String()
    name = fields.String()
    priority = fields.Integer()
    background = fields.String()


class McpToolInputResp(Schema):
    name = fields.String()
    type = fields.String()
    required = fields.Boolean()
    description = fields.String()


class McpToolResp(Schema):
    name = fields.String()
    label = fields.String()
    description = fields.String()
    inputs = fields.List(fields.Nested(McpToolInputResp), dump_default=[])


class McpProviderResp(Schema):
    id = fields.String()
    provider_key = fields.String()
    name = fields.String()
    label = fields.String()
    icon = fields.String()
    background = fields.String()
    description = fields.String()
    category = fields.String()
    transport = fields.String()
    url = fields.String()
    command = fields.String()
    headers = fields.List(fields.Dict(), dump_default=[])
    tool_names = fields.List(fields.String(), dump_default=[])
    args = fields.List(fields.String(), dump_default=[])
    env = fields.Dict(dump_default={})
    timeout_seconds = fields.Integer()
    task_keywords = fields.List(fields.String(), dump_default=[])
    source_type = fields.String()
    source_key = fields.String()
    source_url = fields.String()
    creator_name = fields.String()
    creator_avatar = fields.String()
    is_public = fields.Boolean()
    is_bindable = fields.Boolean()
    bind_reason = fields.String()
    published_at = fields.Integer()
    created_at = fields.Integer()
    updated_at = fields.Integer()
    tool_count = fields.Integer()
    tools = fields.List(fields.Nested(McpToolResp), dump_default=[])
    binding = fields.Dict(dump_default={})


class GetMcpCategoriesResp(Schema):
    categories = fields.List(fields.Nested(McpCategoryResp))

    class Meta:
        strict = True

    def dump(self, obj, **kwargs):
        return {"categories": MCP_CATEGORY_OPTIONS}

