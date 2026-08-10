from marshmallow import Schema, fields


class PromptTemplateItemSchema(Schema):
    prompt_key = fields.String()
    name = fields.String()
    category = fields.String()
    description = fields.String()
    content = fields.String()
    variables = fields.Dict()
    source = fields.String()
    version = fields.Integer()
    enabled = fields.Boolean(allow_none=True)
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
