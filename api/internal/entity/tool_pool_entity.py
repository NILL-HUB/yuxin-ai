import time
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

_POOL_TYPE = "tool"
_cache: dict = {}
_CACHE_TTL = 60


def _load_pools_from_db():
    try:
        from internal.extension.database_extension import db
        from internal.model.sub_pool_definition import SubPoolDefinition

        rows = (
            db.session.query(SubPoolDefinition)
            .filter(
                SubPoolDefinition.pool_type == _POOL_TYPE,
                SubPoolDefinition.enabled.is_(True),
            )
            .order_by(SubPoolDefinition.sort_order)
            .all()
        )
        if not rows:
            return None
        return [
            {
                "name": r.name,
                "label": r.label,
                "description": r.description or "",
                "visible_to_user": r.visible_to_user,
                "default_enabled": r.default_enabled,
            }
            for r in rows
        ]
    except Exception:
        return None


def _get_pools():
    now = time.time()
    cached = _cache.get(_POOL_TYPE)
    if cached and (now - cached["ts"]) < _CACHE_TTL:
        return cached["pools"]
    db_pools = _load_pools_from_db()
    pools = db_pools if db_pools is not None else BUILTIN_TOOL_SUB_POOLS
    _cache[_POOL_TYPE] = {"pools": pools, "ts": now}
    return pools


def refresh_cache():
    _cache.pop(_POOL_TYPE, None)


class ToolSubPoolRegistry:
    def __init__(self, pools=None):
        self._override = pools

    @property
    def _pools(self):
        return self._override if self._override is not None else _get_pools()

    @property
    def _pool_map(self):
        return {pool["name"]: deepcopy(pool) for pool in self._pools}

    def list_pools(self) -> list[dict]:
        return [deepcopy(pool) for pool in self._pools]

    def get_pool(self, name: str | None) -> dict:
        return deepcopy(self._pool_map.get(name or "", self._pool_map.get("general") or self._pools[0]))

    def normalize_pool_name(self, name: str | None) -> str:
        return self.get_pool(name)["name"]
