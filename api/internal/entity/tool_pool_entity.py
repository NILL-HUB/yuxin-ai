from copy import deepcopy


BUILTIN_TOOL_SUB_POOLS = [
    {
        "name": "general",
        "label": "通用工具",
        "description": "适合通用任务的工具池",
        "visible_to_user": True,
        "default_enabled": True,
    },
    {
        "name": "mcp",
        "label": "MCP 工具",
        "description": "通过 MCP Provider 暴露的工具池",
        "visible_to_user": True,
        "default_enabled": True,
    },
    {
        "name": "api",
        "label": "API 工具",
        "description": "通过 OpenAPI Schema 接入的工具池",
        "visible_to_user": True,
        "default_enabled": True,
    },
    {
        "name": "builtin",
        "label": "内置工具",
        "description": "系统内置工具池",
        "visible_to_user": True,
        "default_enabled": True,
    },
    {
        "name": "knowledge",
        "label": "知识库工具",
        "description": "系统知识、用户资料和知识检索工具池",
        "visible_to_user": True,
        "default_enabled": True,
    },
    {
        "name": "memory",
        "label": "长期记忆",
        "description": "用户长期记忆读取与确认工具池",
        "visible_to_user": True,
        "default_enabled": True,
    },
    {
        "name": "external_data",
        "label": "外部数据源",
        "description": "外部数据源连接和同步工具池",
        "visible_to_user": True,
        "default_enabled": True,
    },
    {
        "name": "system_admin",
        "label": "系统管理",
        "description": "仅管理员可见的高权限工具池",
        "visible_to_user": False,
        "default_enabled": False,
    },
]


class ToolSubPoolRegistry:
    def __init__(self, pools=None):
        self._pools = pools or BUILTIN_TOOL_SUB_POOLS
        self._pool_map = {pool["name"]: deepcopy(pool) for pool in self._pools}

    def list_pools(self) -> list[dict]:
        return [deepcopy(pool) for pool in self._pools]

    def get_pool(self, name: str | None) -> dict:
        return deepcopy(self._pool_map.get(name or "", self._pool_map["general"]))

    def normalize_pool_name(self, name: str | None) -> str:
        return self.get_pool(name)["name"]
