"""Builtin 工具 YAML→DB 同步服务。

职责：
- 启动时遍历 providers.yaml + 所有工具 YAML，upsert 到 DB
- 使用 source="catalog" 标记，admin 自定义的 source="custom" 不会被覆盖
- 计算 python_module 路径（如 internal.core.tools.builtin_tools.providers.time.current_time）
- 不修改 YAML 文件本身（同步是单向的：YAML→DB）

注意：本服务只负责元数据同步，Python 执行代码仍在本地文件，
由 BuiltinProviderManager 通过 dynamic_import 加载。
"""
import logging
import os.path
from typing import Any

import yaml
from sqlalchemy.exc import SQLAlchemyError

from internal.extension.database_extension import db
from internal.model.builtin_tool import BuiltinTool, BuiltinToolProvider

logger = logging.getLogger(__name__)


class BuiltinToolSyncService:
    """Builtin 工具元数据 YAML→DB 同步服务"""

    def __init__(self):
        # 无 DI 依赖：db 直接 import；作用域由 module.py 的 binder.bind(..., scope=singleton) 控制
        pass

    # providers 目录相对本文件的位置：
    # 本文件: internal/service/builtin_tool_sync_service.py
    # 目标  : internal/core/tools/builtin_tools/providers/
    # 即：dirname(__file__)/../core/tools/builtin_tools/providers
    _PROVIDERS_DIR = os.path.abspath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "core", "tools", "builtin_tools", "providers",
        )
    )
    PROVIDERS_YAML_PATH = os.path.join(_PROVIDERS_DIR, "providers.yaml")
    PYTHON_MODULE_PREFIX = "internal.core.tools.builtin_tools.providers"

    def sync_yaml_to_db(self) -> dict:
        """从 YAML 同步 builtin 工具元数据到 DB。

        Returns:
            dict: 同步统计信息，如 {"providers": 25, "tools": 51, "skipped": 3}
        """
        stats = {"providers": 0, "tools": 0, "skipped": 0, "errors": 0}

        try:
            providers_data = self._load_providers_yaml()
        except Exception:
            logger.exception("读取 providers.yaml 失败，跳过 builtin 工具同步")
            stats["errors"] += 1
            return stats

        providers_yaml_path = self.PROVIDERS_YAML_PATH
        providers_dir = self._PROVIDERS_DIR

        for provider_data in providers_data:
            provider_name = provider_data.get("name")
            if not provider_name:
                stats["skipped"] += 1
                continue

            try:
                provider = self._upsert_provider(
                    provider_data,
                    source_path=providers_yaml_path,
                )
                stats["providers"] += 1

                # 读取 positions.yaml 获取该 provider 下所有工具名
                positions_path = os.path.join(providers_dir, provider_name, "positions.yaml")
                if not os.path.exists(positions_path):
                    logger.warning("provider %s 缺少 positions.yaml，跳过工具同步", provider_name)
                    continue

                with open(positions_path, encoding="utf-8") as f:
                    tool_names = yaml.safe_load(f) or []

                for tool_name in tool_names:
                    tool_yaml_path = os.path.join(
                        providers_dir, provider_name, f"{tool_name}.yaml"
                    )
                    if not os.path.exists(tool_yaml_path):
                        logger.warning(
                            "工具 YAML 不存在: %s/%s.yaml，跳过", provider_name, tool_name
                        )
                        stats["skipped"] += 1
                        continue

                    try:
                        with open(tool_yaml_path, encoding="utf-8") as f:
                            tool_yaml_data = yaml.safe_load(f) or {}

                        self._upsert_tool(
                            provider,
                            tool_name,
                            tool_yaml_data,
                            source_path=tool_yaml_path,
                        )
                        stats["tools"] += 1
                    except Exception:
                        logger.exception(
                            "同步工具失败 provider=%s tool=%s", provider_name, tool_name
                        )
                        stats["errors"] += 1
            except SQLAlchemyError:
                logger.exception("DB 错误，provider=%s 同步失败", provider_name)
                stats["errors"] += 1
                db.session.rollback()
            except Exception:
                logger.exception("未知错误，provider=%s 同步失败", provider_name)
                stats["errors"] += 1

        try:
            db.session.commit()
        except Exception:
            logger.exception("提交 builtin 工具同步事务失败")
            db.session.rollback()
            stats["errors"] += 1

        logger.info(
            "builtin 工具 YAML→DB 同步完成: %s", stats
        )
        return stats

    def _load_providers_yaml(self) -> list[dict]:
        """加载 providers.yaml 数据"""
        with open(self.PROVIDERS_YAML_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or []

    def _upsert_provider(
        self,
        provider_data: dict,
        source_path: str,
    ) -> BuiltinToolProvider:
        """upsert 一个 provider 记录。

        - 已存在且 source="catalog"：更新元数据字段
        - 已存在且 source="custom"：跳过（admin 自定义不被覆盖）
        - 不存在：新建
        """
        name = provider_data["name"]

        provider = (
            db.session.query(BuiltinToolProvider)
            .filter_by(name=name)
            .first()
        )

        if provider is None:
            provider = BuiltinToolProvider(
                name=name,
                label=provider_data.get("label", ""),
                description=provider_data.get("description", ""),
                icon=provider_data.get("icon", ""),
                background=provider_data.get("background", ""),
                category=provider_data.get("category", ""),
                source="catalog",
                source_path=source_path,
            )
            db.session.add(provider)
            db.session.flush()
            return provider

        # 已存在：只更新 source="catalog" 的记录
        if provider.source == "catalog":
            provider.label = provider_data.get("label", "")
            provider.description = provider_data.get("description", "")
            provider.icon = provider_data.get("icon", "")
            provider.background = provider_data.get("background", "")
            provider.category = provider_data.get("category", "")
            provider.source_path = source_path

        return provider

    def _upsert_tool(
        self,
        provider: BuiltinToolProvider,
        tool_name: str,
        tool_yaml_data: dict,
        source_path: str,
    ) -> BuiltinTool:
        """upsert 一个工具记录。

        - 已存在且 source="catalog"：更新元数据
        - 已存在且 source="custom"：跳过
        - 不存在：新建
        """
        tool = (
            db.session.query(BuiltinTool)
            .filter_by(provider_id=provider.id, name=tool_name)
            .first()
        )

        params = tool_yaml_data.get("params") or []
        task_keywords = tool_yaml_data.get("task_keywords") or []
        python_module = f"{self.PYTHON_MODULE_PREFIX}.{provider.name}"

        if tool is None:
            tool = BuiltinTool(
                provider_id=provider.id,
                name=tool_name,
                label=tool_yaml_data.get("label", ""),
                description=tool_yaml_data.get("description", ""),
                params=params,
                task_keywords=task_keywords,
                python_module=python_module,
                source="catalog",
                enabled=True,
            )
            db.session.add(tool)
            return tool

        if tool.source == "catalog":
            tool.label = tool_yaml_data.get("label", "")
            tool.description = tool_yaml_data.get("description", "")
            tool.params = params
            tool.task_keywords = task_keywords
            tool.python_module = python_module

        return tool

    def list_providers_with_tools(self) -> list[dict]:
        """从 DB 读取所有 provider 及其工具，按 providers.yaml 顺序返回。

        若 DB 中没有数据，返回空列表（调用方应回退到 YAML）。
        """
        providers = (
            db.session.query(BuiltinToolProvider)
            .order_by(BuiltinToolProvider.created_at)
            .all()
        )
        result: list[dict] = []
        for provider in providers:
            tools = (
                db.session.query(BuiltinTool)
                .filter_by(provider_id=provider.id)
                .order_by(BuiltinTool.created_at)
                .all()
            )
            result.append({
                "name": provider.name,
                "label": provider.label,
                "description": provider.description,
                "icon": provider.icon,
                "background": provider.background,
                "category": provider.category,
                "created_at": _to_timestamp(provider.created_at),
                "tools": [self._tool_to_dict(t) for t in tools],
            })
        return result

    def get_provider_with_tools(self, provider_name: str) -> dict | None:
        """从 DB 读取指定 provider 及其工具。"""
        provider = (
            db.session.query(BuiltinToolProvider)
            .filter_by(name=provider_name)
            .first()
        )
        if provider is None:
            return None
        tools = (
            db.session.query(BuiltinTool)
            .filter_by(provider_id=provider.id)
            .order_by(BuiltinTool.created_at)
            .all()
        )
        return {
            "name": provider.name,
            "label": provider.label,
            "description": provider.description,
            "icon": provider.icon,
            "background": provider.background,
            "category": provider.category,
            "created_at": _to_timestamp(provider.created_at),
            "tools": [self._tool_to_dict(t) for t in tools],
        }

    def _tool_to_dict(self, tool: BuiltinTool) -> dict[str, Any]:
        return {
            "name": tool.name,
            "label": tool.label,
            "description": tool.description,
            "params": tool.params or [],
            "task_keywords": tool.task_keywords or [],
            "python_module": tool.python_module,
            "source": tool.source,
            "enabled": tool.enabled,
        }


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
