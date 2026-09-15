from __future__ import annotations

from internal.core.language_model.entities.model_entity import ModelType
from internal.schema import admin_model_pool_schema, admin_model_provider_schema
from internal.service.admin_model_pool_service import CONTEXT_LESS_MODEL_TYPES


def test_model_types_should_be_identical_between_pool_and_provider_schema():
    """模型类型白名单在后端存在两份副本，必须完全一致，否则一处能创建、另一处校验失败。"""
    assert admin_model_pool_schema.MODEL_TYPES == admin_model_provider_schema.MODEL_TYPES


def test_model_types_should_match_model_type_enum():
    """模型类型白名单必须与 ModelType 枚举成员集合一致，防止新增类型时漏改列表。"""
    assert set(admin_model_pool_schema.MODEL_TYPES) == {m.value for m in ModelType}


def test_visual_embedding_should_be_registered():
    """视觉编码模型类型必须同时存在于枚举与白名单中。"""
    assert "visual_embedding" in admin_model_pool_schema.MODEL_TYPES
    assert ModelType.VISUAL_EMBEDDING.value == "visual_embedding"


def test_visual_embedding_should_be_context_less():
    """视觉编码模型没有上下文窗口概念，必须归入无上下文类型集合。"""
    assert "visual_embedding" in CONTEXT_LESS_MODEL_TYPES
