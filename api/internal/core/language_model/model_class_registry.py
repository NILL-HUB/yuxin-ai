# api/internal/core/language_model/model_class_registry.py
"""(compatible_api, model_type) → model_class 二元组映射注册表"""

from typing import Optional, Type

from internal.exception import NotFoundException

from .entities.model_entity import BaseLanguageModel


def _import_class(module_path: str, class_name: str) -> Optional[Type[BaseLanguageModel]]:
    """动态导入模型类，导入失败时返回 None"""
    try:
        from internal.lib.helper import dynamic_import
        return dynamic_import(module_path, class_name)
    except Exception:
        return None


class ModelClassRegistry:
    """(compatible_api, model_type) → model_class 映射表

    替代原 Provider 中硬编码的 model_class_map，支持通过
    compatible_api + model_type 二元组查找对应的 LangChain 模型类。
    """

    _REGISTRY: dict[tuple[str, str], Optional[Type[BaseLanguageModel]]] = {
        # OpenAI 兼容协议 — 使用 langchain_openai
        ("openai", "chat"): _import_class("langchain_openai", "ChatOpenAI"),
        ("openai", "multimodal"): _import_class("langchain_openai", "ChatOpenAI"),
        ("openai", "embedding"): _import_class("langchain_openai", "OpenAIEmbeddings"),
        # Claude 兼容协议 — 使用 langchain_anthropic
        ("claude", "chat"): _import_class("langchain_anthropic", "ChatAnthropic"),
        ("claude", "multimodal"): _import_class("langchain_anthropic", "ChatAnthropic"),
    }

    @classmethod
    def resolve(cls, compatible_api: str, model_type: str) -> Type[BaseLanguageModel]:
        """根据兼容协议和模型类型查找模型类

        Args:
            compatible_api: 兼容协议标识，如 'openai' / 'claude'
            model_type: 模型类型，如 'chat' / 'embedding' / 'multimodal'

        Returns:
            对应的 LangChain 模型类

        Raises:
            NotFoundException: 不支持的组合
        """
        key = (compatible_api, model_type)
        model_class = cls._REGISTRY.get(key)
        if model_class is None:
            raise NotFoundException(
                f"不支持的模型类型组合: compatible_api={compatible_api}, model_type={model_type}"
            )
        return model_class

    @classmethod
    def is_supported(cls, compatible_api: str, model_type: str) -> bool:
        """检查组合是否支持"""
        return (compatible_api, model_type) in cls._REGISTRY and cls._REGISTRY[(compatible_api, model_type)] is not None

    @classmethod
    def get_supported_combinations(cls) -> list[tuple[str, str]]:
        """获取所有支持的组合列表"""
        return [k for k, v in cls._REGISTRY.items() if v is not None]
