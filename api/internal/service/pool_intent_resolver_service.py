from internal.entity.agent_pool_entity import AgentSubPoolRegistry


POOL_KEYWORDS = [
    (
        "office",
        ["P 图", "P图", "PPT", "Word", "文档", "Excel", "表格", "图片处理", "图片"],
    ),
    (
        "coding",
        ["前端", "后端", "写代码", "修 bug", "bug", "部署", "测试", "Docker"],
    ),
    ("data", ["数据", "数据分析", "SQL", "报表", "可视化", "统计"]),
    ("research", ["调研", "搜索", "竞品", "行业", "报告"]),
    ("customer_service", ["客服", "售后", "退款", "工单", "FAQ"]),
    ("internal_admin", ["审计", "权限", "系统管理", "运维"]),
]


class PoolIntentResolver:
    def __init__(self, registry=None):
        self.registry = registry or AgentSubPoolRegistry()

    def resolve(self, query: str, classifier_result: dict | None = None) -> dict:
        matched_pools = []
        pool_reasons = []
        text = query or ""
        for pool, keywords in POOL_KEYWORDS:
            keyword = self._first_keyword(text, keywords)
            if keyword is None:
                continue
            pool_name = self.registry.normalize_pool_name(pool)
            if pool_name in matched_pools:
                continue
            matched_pools.append(pool_name)
            pool_reasons.append({"pool": pool_name, "reason": f"keyword:{keyword}"})
        if not matched_pools:
            matched_pools = ["general"]
            pool_reasons = [{"pool": "general", "reason": "fallback:general"}]
        return {"matched_pools": matched_pools, "pool_reasons": pool_reasons}

    @staticmethod
    def _first_keyword(text: str, keywords: list[str]) -> str | None:
        lowered = text.lower()
        for keyword in keywords:
            if keyword.lower() in lowered:
                return keyword
        return None
