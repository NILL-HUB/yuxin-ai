# api/internal/core/language_model/entities/provider_entity.py
from pydantic import BaseModel, Field


class ProviderEntity(BaseModel):
    """模型提供商实体信息 — 从数据库动态加载

    新架构下供应商配置存储于 ModelProviderConfig 表，由 LanguageModelManager
    懒加载后构建为此实体。旧的 Provider 包装类与静态 yaml 加载已废弃。
    """
    name: str = ""
    label: str = ""
    description: str = ""
    icon: str = ""
    background: str = "#FFFFFF"
    default_base_url: str = ""
    supported_model_types: list[str] = Field(default_factory=list)
