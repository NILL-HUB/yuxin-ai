import logging
import mimetypes
import os
from typing import Any
from injector import inject
from dataclasses import dataclass
from internal.core.tools.builtin_tools.providers import BuiltinProviderManager
from pydantic import BaseModel
from internal.context import current_app
from internal.exception import NotFoundException
from internal.core.tools.builtin_tools.categories import BuiltinCategoryManager

logger = logging.getLogger(__name__)


@inject
@dataclass
class BuiltinToolService:
    """内置工具服务"""
    builtin_provider_manager: BuiltinProviderManager
    builtin_category_manager: BuiltinCategoryManager

    def get_builtin_tools(self) -> list:
        """获取 钰心AI 项目中的所有内置提供商和工具信息

        优先从 DB 镜像表读取（admin 编辑后的元数据），失败时回退到
        BuiltinProviderManager 内存中的 YAML 数据。
        返回的工具 dict 包含 task_keywords，与现有结构一致。
        """
        try:
            tools = self._get_builtin_tools_from_db()
            if tools:
                return tools
            logger.info("DB 中无 builtin 工具数据，回退到 BuiltinProviderManager 内存数据")
        except Exception:
            logger.exception("从 DB 读取 builtin 工具失败，回退到 BuiltinProviderManager")

        return self._get_builtin_tools_from_manager()

    def _get_builtin_tools_from_db(self) -> list:
        """从 DB 镜像表读取 builtin 工具信息（包含 task_keywords）"""
        from internal.extension.database_extension import db
        from internal.model.builtin_tool import BuiltinTool, BuiltinToolProvider
        from internal.lib.helper import dynamic_import

        providers = (
            db.session.query(BuiltinToolProvider)
            .order_by(BuiltinToolProvider.created_at)
            .all()
        )
        if not providers:
            return []

        builtin_tools: list[dict] = []
        for provider in providers:
            provider_dict = {
                "name": provider.name,
                "label": provider.label,
                "description": provider.description,
                "background": provider.background,
                "category": provider.category,
                "created_at": _to_timestamp(provider.created_at),
                "tools": [],
            }

            tools = (
                db.session.query(BuiltinTool)
                .filter_by(provider_id=provider.id)
                .order_by(BuiltinTool.created_at)
                .all()
            )
            for tool in tools:
                if not tool.enabled:
                    continue
                # Python 执行代码仍从本地 dynamic_import 加载，用于读取 args_schema
                tool_func = None
                try:
                    module_path = tool.python_module or (
                        f"internal.core.tools.builtin_tools.providers.{provider.name}"
                    )
                    tool_func = dynamic_import(module_path, tool.name)
                except Exception:
                    logger.exception(
                        "dynamic_import 失败 provider=%s tool=%s",
                        provider.name,
                        tool.name,
                    )

                tool_dict = {
                    "name": tool.name,
                    "label": tool.label,
                    "description": tool.description,
                    "params": tool.params or [],
                    "task_keywords": tool.task_keywords or [],
                    "inputs": self.get_tool_inputs(tool_func),
                }
                provider_dict["tools"].append(tool_dict)

            builtin_tools.append(provider_dict)
        return builtin_tools

    def _get_builtin_tools_from_manager(self) -> list:
        """从 BuiltinProviderManager 内存数据读取 builtin 工具信息（YAML 回退路径）"""
        # 1.获取所有的提供商
        providers = self.builtin_provider_manager.get_providers()
        # 2.遍历所有的提供商并提取工具信息
        builtin_tools = []
        for provider in providers:
            provider_entity = provider.provider_entity
            builtin_tool = {
                **provider_entity.model_dump(exclude=["icon"]),
                "tools":[]
            }
            # 循环遍历提取提供者的所有工具实体
            for tool_entity in provider.get_tool_entities():
                # 从提供者中获取工具函数
                tool = provider.get_tool(tool_entity.name)
                # 构建工具实体信息
                tool_dict = {
                    **tool_entity.model_dump(),
                    "inputs": self.get_tool_inputs(tool)
                }

                builtin_tool["tools"].append(tool_dict)

            builtin_tools.append(builtin_tool)
        return builtin_tools


    def get_provider_tool(self,provider_name:str,tool_name:str) -> dict:
        """根据传递的提供者名字 + 工具名字获取指定工具信息"""
        # 1. 获取内置的提供商
        provider = self.builtin_provider_manager.get_provider(provider_name)
        if provider is None:
            raise NotFoundException(f"该提供商{provider_name}不存在")

        # 2.获取该提供商下对应的工具
        tool_entity = provider.get_tool_entity(tool_name)
        if tool_entity is None:
            raise NotFoundException(f"该工具{tool_entity}不存在")

        # 3.组装提供商和工具实体信息
        provider_entity = provider.provider_entity
        tool = provider.get_tool(tool_name)

        builtin_tool = {
            "provider": {**provider_entity.model_dump(exclude=["icon","created_at"])},
            **tool_entity.model_dump(),
            "created_at":provider_entity.created_at,
            "inputs": self.get_tool_inputs(tool)
        }

        return builtin_tool

    def get_provider_icon(self,provider_name:str) -> tuple[bytes | None, str | None, str | None]:
        """根据传递的提供者名字获取icon流信息"""
        # 1.获取对应的工具提供者
        provider = self.builtin_provider_manager.get_provider(provider_name)
        if not provider:
            raise NotFoundException(f"该工具提供者{provider_name}不存在")

        icon = provider.provider_entity.icon.strip()
        if icon.startswith(("http://", "https://")):
            return None, None, icon

        # 2. 获取项目的根路径信息(current_app.root_path路径为app/http/)root_path为llmops-api的路径(root)
        root_path = os.path.dirname(os.path.dirname(current_app.root_path))

        # 3.  拼接得到提供者所在的文件夹
        provider_path = os.path.join(
            root_path,
            "internal","core","tools","builtin_tools","providers",provider_name,
        )
        # 4. 拼接得到icon对应的路径
        icon_path = os.path.join(provider_path,"_asset",icon)

        # 5. 检测icon是否存在
        if not os.path.exists(icon_path):
            raise NotFoundException(f"该工具提供者_asset下未提供图标")

        # 6. 读取icon的类型
        mimetype, _ = mimetypes.guess_type(icon_path)
        mimetype = mimetype or "application/octet-stream"

        # 7.读取icon的字节数据
        with open(icon_path,"rb") as f:
            byte_data = f.read()
            return byte_data,mimetype,None

    def get_categories(self) -> list[dict[str, Any]]:
        """获取所有的内置分类信息，涵盖了category、name、icon"""
        category_map = self.builtin_category_manager.get_category_map()
        return [{
            "name": category["entity"].name,
            "category": category["entity"].category,
            "icon": category["icon"],
        } for category in category_map.values()]

    @classmethod
    def get_tool_inputs(cls,tool) -> list:
        """根据传入的工具获取inputs信息"""
        inputs = []
        if hasattr(tool, "args_schema") and issubclass(tool.args_schema, BaseModel):
            for field_name, model_field in tool.args_schema.model_fields.items():
                inputs.append({
                    "name": field_name,
                    "description": model_field.description or "",
                    "required": model_field.is_required(),
                    "type": model_field.annotation.__name__,
                })
        return inputs


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

