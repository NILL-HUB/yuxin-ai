# api/internal/core/language_model/entities/provider_entity.py
from typing import Any, Optional, Type, Union

from pydantic import BaseModel, Field

from .model_entity import BaseLanguageModel, ModelEntity, ModelType


class ProviderEntity(BaseModel):
    """模型提供商实体信息 — 从数据库加载"""
    name: str = ""
    label: str = ""
    description: str = ""
    icon: str = ""
    background: str = "#FFFFFF"
    default_base_url: str = ""
    supported_model_types: list[str] = Field(default_factory=list)
    embedding_models: list[dict[str, Any]] = Field(default_factory=list)


class Provider(BaseModel):
    """大语言模型服务提供商 — 兼容旧接口

    新架构下 Provider 仅作为 ProviderEntity 的薄包装，
    model_entity_map 和 model_class_map 通过 LanguageModelManager 懒加载。
    """
    name: str
    position: int = 0
    provider_entity: ProviderEntity
    model_entity_map: dict[str, ModelEntity] = Field(default_factory=dict)
    model_class_map: dict[str, Union[None, Type[BaseLanguageModel]]] = Field(default_factory=dict)

    def get_model_class(self, model_type: ModelType) -> Optional[Type[BaseLanguageModel]]:
        """根据模型类型获取模型类 — 兼容旧接口

        新架构下 model_class 通过 ModelClassRegistry 解析，
        此方法仅用于向后兼容，不再被主流程调用。
        """
        model_type_str = model_type.value if hasattr(model_type, 'value') else str(model_type)
        model_class = self.model_class_map.get(model_type_str, None)
        if model_class is None:
            from internal.exception import NotFoundException
            raise NotFoundException("该模型类不存在，请核实后重试")
        return model_class

    def get_model_entity(self, model_name: str) -> Optional[ModelEntity]:
        """根据模型名获取模型实体 — 从内存字典查找（兼容旧接口）"""
        model_entity = self.model_entity_map.get(model_name, None)
        return model_entity

    def get_model_entities(self) -> list[ModelEntity]:
        """获取所有模型实体列表"""
        return list(self.model_entity_map.values())
