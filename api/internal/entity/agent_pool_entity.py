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
        "task_keywords": ["写代码", "改代码", "部署", "排错", "前端", "后端"],
    },
    {
        "name": "office",
        "label": "办公",
        "visible_to_user": True,
        "description": "文档、PPT、表格、图片基础处理",
        "default_capabilities": ["document", "spreadsheet", "presentation"],
        "task_keywords": ["文档", "PPT", "表格", "Excel", "图片"],
    },
    {
        "name": "data",
        "label": "数据",
        "visible_to_user": True,
        "description": "数据分析、SQL、报表、可视化",
        "default_capabilities": ["data_analysis", "sql", "visualization"],
        "task_keywords": ["数据分析", "SQL", "报表", "可视化", "统计"],
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


class AgentSubPoolRegistry:
    def __init__(self, pools=None):
        self._pools = pools or BUILTIN_AGENT_SUB_POOLS
        self._pool_map = {pool["name"]: pool for pool in self._pools}

    def list_pools(self):
        return deepcopy(self._pools)

    def get_pool(self, name):
        return deepcopy(self._pool_map.get(name) or self._pool_map["general"])

    def normalize_pool_name(self, name):
        return name if name in self._pool_map else "general"
