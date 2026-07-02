import time
from copy import deepcopy


BUILTIN_AGENT_SUB_POOLS = [
    {
        "name": "general",
        "label": "通用",
        "visible_to_user": True,
        "description": "默认兜底 Agent",
        "default_capabilities": [],
        "task_keywords": [],
    },
    {
        "name": "coding",
        "label": "编程",
        "visible_to_user": True,
        "description": "写代码、改代码、部署、排错",
        "default_capabilities": ["coding"],
        "task_keywords": ["写代码", "改代码", "部署", "排错", "前端", "后端", "测试", "Docker", "bug"],
    },
    {
        "name": "office",
        "label": "办公",
        "visible_to_user": True,
        "description": "文档、PPT、表格、图片基础处理",
        "default_capabilities": ["document", "spreadsheet", "presentation"],
        "task_keywords": ["P 图", "P图", "PPT", "Word", "文档", "Excel", "表格", "图片处理", "图片"],
    },
    {
        "name": "data",
        "label": "数据",
        "visible_to_user": True,
        "description": "数据分析、SQL、报表、可视化",
        "default_capabilities": ["data_analysis", "sql", "visualization"],
        "task_keywords": ["数据", "数据分析", "SQL", "报表", "可视化", "统计"],
    },
    {
        "name": "research",
        "label": "研究",
        "visible_to_user": True,
        "description": "搜索、行业研究、竞品分析",
        "default_capabilities": ["research", "search"],
        "task_keywords": ["调研", "搜索", "竞品", "行业", "报告"],
    },
    {
        "name": "customer_service",
        "label": "客服",
        "visible_to_user": True,
        "description": "工单、FAQ、售后",
        "default_capabilities": ["customer_service"],
        "task_keywords": ["客服", "售后", "退款", "工单", "FAQ"],
    },
    {
        "name": "internal_admin",
        "label": "内部管理",
        "visible_to_user": False,
        "description": "运维、审计、系统管理",
        "default_capabilities": ["audit", "ops", "admin"],
        "task_keywords": ["审计", "权限", "系统管理", "运维"],
    },
]

_POOL_TYPE = "agent"
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
                "visible_to_user": r.visible_to_user,
                "description": r.description or "",
                "default_capabilities": list(r.default_capabilities or []),
                "task_keywords": list(r.task_keywords or []),
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
    pools = db_pools if db_pools is not None else BUILTIN_AGENT_SUB_POOLS
    _cache[_POOL_TYPE] = {"pools": pools, "ts": now}
    return pools


def refresh_cache():
    _cache.pop(_POOL_TYPE, None)


class AgentSubPoolRegistry:
    def __init__(self, pools=None):
        self._override = pools

    @property
    def _pools(self):
        return self._override if self._override is not None else _get_pools()

    @property
    def _pool_map(self):
        return {pool["name"]: pool for pool in self._pools}

    def list_pools(self):
        return deepcopy(self._pools)

    def get_pool(self, name):
        return deepcopy(self._pool_map.get(name) or self._pool_map.get("general") or self._pools[0])

    def normalize_pool_name(self, name):
        return name if name in self._pool_map else "general"

    def get_task_keywords(self):
        result = []
        for pool in self._pools:
            for kw in pool.get("task_keywords") or []:
                if kw not in result:
                    result.append(kw)
        return result
