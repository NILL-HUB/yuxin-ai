import logging
import os.path
from typing import Any
import yaml
from injector import inject, singleton
from pydantic import BaseModel, Field
from internal.core.tools.builtin_tools.entities import ProviderEntity, Provider

logger = logging.getLogger(__name__)


@inject
@singleton
class BuiltinProviderManager(BaseModel):
    """服务提供商工厂类

    优先从 DB（builtin_tool_provider + builtin_tool 镜像表）读取元数据；
    DB 不可用时回退到 YAML 加载（保证系统可用性）。
    Python 执行代码始终通过 dynamic_import 从本地文件加载，不存 DB。
    """
    provider_map: dict[str, Provider] = Field(default_factory=dict)

    def __init__(self, **kwargs):
        """构造函数，初始化对应的provider_tool_map"""
        super().__init__(**kwargs)
        self._get_provider_tool_map()

    def get_provider(self, provider_name: str) -> Provider:
        """根据传递的名字来获取服务提供商"""
        return self.provider_map.get(provider_name)

    def get_providers(self) -> list[Provider]:
        """获取所有服务提供商列表"""
        return list(self.provider_map.values())

    def get_tool(self, provider_name: str, tool_name: str) -> Any:
        """根据服务提供商的名字+工具名字，来获取特定的工具实体"""
        provider = self.get_provider(provider_name)
        if provider is None:
            return None
        return provider.get_tool(tool_name)

    def _get_provider_tool_map(self):
        """项目初始化的时候获取服务提供商、工具的映射关系并填充provider_tool_map"""
        # 1.检测provider_tool_map是否为空
        if self.provider_map:
            return

        # 2.优先从 DB 加载（启动时 BuiltinToolSyncService 已同步 YAML→DB）
        try:
            self._load_from_db()
            if self.provider_map:
                logger.info(
                    "BuiltinProviderManager 从 DB 加载 %d 个 provider",
                    len(self.provider_map),
                )
                return
        except Exception:
            logger.exception("BuiltinProviderManager 从 DB 加载失败，回退到 YAML")

        # 3.回退：从 YAML 加载（原逻辑）
        self._load_from_yaml()

    def _load_from_db(self):
        """从 DB 镜像表读取 provider/tool 元数据。

        Python 执行代码仍用 dynamic_import 从本地加载。
        若 DB 表不存在或为空，抛出异常或返回让调用方回退。
        """
        from internal.extension.database_extension import db
        from internal.model.builtin_tool import BuiltinTool, BuiltinToolProvider

        providers = (
            db.session.query(BuiltinToolProvider)
            .order_by(BuiltinToolProvider.created_at)
            .all()
        )
        if not providers:
            # DB 中没有数据，让调用方回退到 YAML
            raise RuntimeError("DB 中无 builtin_tool_provider 记录，回退到 YAML 加载")

        for idx, provider in enumerate(providers):
            # 构造 ProviderEntity（与 YAML 结构一致）
            provider_entity = ProviderEntity(
                name=provider.name,
                label=provider.label,
                description=provider.description,
                icon=provider.icon,
                background=provider.background,
                category=provider.category,
                created_at=_to_timestamp(provider.created_at),
            )
            provider_obj = Provider(
                name=provider.name,
                position=idx + 1,
                provider_entity=provider_entity,
            )

            # 加载该 provider 下所有工具
            tools = (
                db.session.query(BuiltinTool)
                .filter_by(provider_id=provider.id)
                .order_by(BuiltinTool.created_at)
                .all()
            )
            for tool in tools:
                if not tool.enabled:
                    continue
                # 从 DB 元数据构造 ToolEntity
                tool_entity_data = {
                    "name": tool.name,
                    "label": tool.label,
                    "description": tool.description,
                    "params": tool.params or [],
                    "task_keywords": tool.task_keywords or [],
                }
                from internal.core.tools.builtin_tools.entities import ToolEntity
                tool_entity = ToolEntity(**tool_entity_data)
                provider_obj.tool_entity_map[tool.name] = tool_entity

                # Python 执行代码仍从本地 dynamic_import 加载
                try:
                    from internal.lib.helper import dynamic_import
                    module_path = tool.python_module or (
                        f"internal.core.tools.builtin_tools.providers.{provider.name}"
                    )
                    provider_obj.tool_func_map[tool.name] = dynamic_import(
                        module_path,
                        tool.name,
                    )
                except Exception:
                    logger.exception(
                        "dynamic_import 失败 provider=%s tool=%s",
                        provider.name,
                        tool.name,
                    )

            self.provider_map[provider.name] = provider_obj

    def _load_from_yaml(self):
        """从 YAML 文件加载 provider/tool 元数据（原逻辑，作为 DB 不可用时的 fallback）"""
        # 1.获取当前文件/类所在的文件夹路径
        current_path = os.path.abspath(__file__)
        providers_path = os.path.dirname(current_path)
        providers_yaml_path = os.path.join(providers_path, "providers.yaml")

        # 2.读取providers.yaml的数据
        with open(providers_yaml_path, encoding="utf-8") as f:
            providers_yaml_data = yaml.safe_load(f)

        # 3.循环遍历providers.yaml的数据
        for idx, provider_data in enumerate(providers_yaml_data):
            provider_entity = ProviderEntity(**provider_data)
            self.provider_map[provider_entity.name] = Provider(
                name=provider_entity.name,
                position=idx + 1,
                provider_entity=provider_entity
            )


def _to_timestamp(dt) -> int:
    """将 datetime 转换为秒级时间戳（兼容 None）"""
    if dt is None:
        return 0
    import datetime as _dt
    if isinstance(dt, _dt.datetime):
        if dt.tzinfo is None:
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    return int(dt)
