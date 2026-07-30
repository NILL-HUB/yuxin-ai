import logging
from dataclasses import dataclass
from uuid import UUID

from flask import request
from injector import inject

from internal.extension.database_extension import db
from internal.middleware import admin_login_required, permission_required
from internal.model.builtin_tool import BuiltinTool, BuiltinToolProvider
from internal.service import BuiltinToolService
from internal.exception import NotFoundException
from pkg.response import success_json, success_message, validate_error_json

logger = logging.getLogger(__name__)


@inject
@dataclass
class AdminBuiltinToolHandler:
    """管理员内置工具处理器

    支持：
    - GET /admin/builtin-tools — 列出所有 builtin 工具
    - GET /admin/builtin-tools/<id> — 详情
    - PATCH /admin/builtin-tools/<id> — 编辑 label/description/task_keywords/icon
    - 不支持 create/delete（builtin 工具由代码定义，不能从 DB 创建）
    """

    builtin_tool_service: BuiltinToolService

    @admin_login_required
    @permission_required("tool:read")
    def get_builtin_tools(self):
        """获取 OpenAgent 所有内置工具信息和提供商信息"""
        builtin_tools = self.builtin_tool_service.get_builtin_tools()
        return success_json(builtin_tools)

    @admin_login_required
    @permission_required("tool:read")
    def get_categories(self):
        """获取所有内置提供商的分类信息"""
        categories = self.builtin_tool_service.get_categories()
        return success_json(categories)

    @admin_login_required
    @permission_required("tool:read")
    def get_tool(self, tool_id: UUID):
        """获取指定 builtin 工具详情（按 DB 主键 id）"""
        tool = db.session.get(BuiltinTool, tool_id)
        if tool is None:
            raise NotFoundException(f"builtin 工具 {tool_id} 不存在")

        provider = db.session.get(BuiltinToolProvider, tool.provider_id)
        return success_json(self._tool_to_dict(tool, provider))

    @admin_login_required
    @permission_required("tool:update")
    def update_tool(self, tool_id: UUID):
        """编辑 builtin 工具元数据（label/description/task_keywords/icon）

        - 只更新 DB 中的元数据，不修改 YAML 文件
        - 同步是单向的：YAML→DB（admin 编辑只改 DB）
        - source 字段不变（catalog 同步的记录仍标记为 catalog，避免下次同步覆盖）
        """
        tool = db.session.get(BuiltinTool, tool_id)
        if tool is None:
            raise NotFoundException(f"builtin 工具 {tool_id} 不存在")

        data = request.get_json(force=True, silent=True) or {}

        # 校验：至少提供一个可编辑字段
        allowed_fields = {"label", "description", "task_keywords", "icon"}
        provided_fields = set(data.keys()) & allowed_fields
        if not provided_fields:
            return validate_error_json({
                "form": ["至少提供 label/description/task_keywords/icon 中的一个字段"],
            })

        # 校验 task_keywords 必须是 list[str]
        if "task_keywords" in data:
            kw = data["task_keywords"]
            if not isinstance(kw, list) or not all(isinstance(x, str) for x in kw):
                return validate_error_json({
                    "task_keywords": ["task_keywords 必须是字符串列表"],
                })

        # 校验 label/description/icon 类型
        if "label" in data and not isinstance(data["label"], str):
            return validate_error_json({"label": ["label 必须是字符串"]})
        if "description" in data and not isinstance(data["description"], str):
            return validate_error_json({"description": ["description 必须是字符串"]})
        if "icon" in data and not isinstance(data["icon"], str):
            return validate_error_json({"icon": ["icon 必须是字符串"]})

        # 应用更新（icon 属于 provider 级别，其他属于 tool 级别）
        if "label" in data:
            tool.label = data["label"]
        if "description" in data:
            tool.description = data["description"]
        if "task_keywords" in data:
            tool.task_keywords = data["task_keywords"]

        if "icon" in data:
            # icon 是 provider 级别字段
            provider = db.session.get(BuiltinToolProvider, tool.provider_id)
            if provider is None:
                raise NotFoundException(f"工具对应的 provider 不存在")
            provider.icon = data["icon"]

        db.session.commit()

        # 重新加载并返回
        db.session.refresh(tool)
        provider = db.session.get(BuiltinToolProvider, tool.provider_id)
        return success_json(self._tool_to_dict(tool, provider))

    @staticmethod
    def _tool_to_dict(tool: BuiltinTool, provider: BuiltinToolProvider | None = None) -> dict:
        """将 BuiltinTool 模型序列化为 dict"""
        result = {
            "id": str(tool.id),
            "provider_id": str(tool.provider_id),
            "name": tool.name,
            "label": tool.label,
            "description": tool.description,
            "params": tool.params or [],
            "task_keywords": tool.task_keywords or [],
            "python_module": tool.python_module,
            "source": tool.source,
            "enabled": tool.enabled,
            "updated_at": _to_timestamp(tool.updated_at),
            "created_at": _to_timestamp(tool.created_at),
        }
        if provider is not None:
            result["provider"] = {
                "id": str(provider.id),
                "name": provider.name,
                "label": provider.label,
                "description": provider.description,
                "icon": provider.icon,
                "background": provider.background,
                "category": provider.category,
            }
        return result


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
