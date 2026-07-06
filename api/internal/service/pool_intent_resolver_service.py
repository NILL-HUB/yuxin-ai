import logging

from injector import inject
from pydantic import BaseModel, Field

from internal.entity.agent_pool_entity import AgentSubPoolRegistry
from internal.service.language_model_service import LanguageModelService


logger = logging.getLogger(__name__)


INTENT_TO_POOL = {
    "deep_thinking_task": "general",
    "vertical_agent_task": "general",
    "multi_agent_task": "general",
    "tool_task": "general",
    "general_qa": "general",
    "high_risk_operation": "internal_admin",
}


class PoolMatchResult(BaseModel):
    """LLM 子池匹配结构化输出。"""

    matched_pools: list[str] = Field(
        description="匹配的子池标识名列表，按相关度从高到低排列"
    )
    reason: str = Field(default="", description="简短匹配理由")


@inject
class PoolIntentResolver:
    def __init__(self, registry=None, language_model_service: LanguageModelService = None):
        self.registry = registry or AgentSubPoolRegistry()
        self.language_model_service = language_model_service

    def resolve(self, query: str, classifier_result: dict | None = None) -> dict:
        matched_pools: list[str] = []
        pool_reasons: list[dict] = []

        # 第 0 步：基于 TaskClassifier 的 intent 做初步映射
        if classifier_result and classifier_result.get("intent"):
            intent = classifier_result["intent"]
            intent_pool = INTENT_TO_POOL.get(intent)
            if intent_pool and intent_pool not in matched_pools:
                normalized = self.registry.normalize_pool_name(intent_pool)
                if normalized not in matched_pools:
                    matched_pools.append(normalized)
                    pool_reasons.append(
                        {"pool": normalized, "reason": f"intent:{intent}"}
                    )

        # 第 1 步：关键词匹配优先（命中即返回，速度快、零成本）
        text = query or ""
        for pool in self.registry.list_pools():
            pool_name = pool["name"]
            if pool_name in matched_pools:
                continue
            keywords = pool.get("task_keywords") or []
            keyword = self._first_keyword(text, keywords)
            if keyword is None:
                continue
            matched_pools.append(pool_name)
            pool_reasons.append({"pool": pool_name, "reason": f"keyword:{keyword}"})

        # 第 2 步：LLM 语义匹配兜底（仅在关键词零命中时调用，处理模糊 query）
        # 注意：关键词已命中任何池时跳过 LLM，避免冗余调用
        has_keyword_hit = any(
            r.get("reason", "").startswith("keyword:") for r in pool_reasons
        )
        if not has_keyword_hit and self.language_model_service is not None:
            try:
                llm_pools = self._resolve_with_llm(query)
                if llm_pools:
                    for pool_name in llm_pools:
                        if pool_name not in matched_pools:
                            normalized = self.registry.normalize_pool_name(pool_name)
                            if normalized not in matched_pools:
                                matched_pools.append(normalized)
                                pool_reasons.append(
                                    {"pool": normalized, "reason": "llm:semantic"}
                                )
            except Exception:
                logger.warning("LLM 子池匹配失败，降级到关键词匹配结果", exc_info=True)

        if not matched_pools:
            matched_pools = ["general"]
            pool_reasons = [{"pool": "general", "reason": "fallback:general"}]
        return {"matched_pools": matched_pools, "pool_reasons": pool_reasons}

    def _resolve_with_llm(self, query: str) -> list[str]:
        """用 LLM 判断用户消息应归入哪些子池。"""
        pools = self.registry.list_pools()
        visible_pools = [p for p in pools if p.get("visible_to_user", True)]
        if not visible_pools:
            return []

        pool_descriptions = "\n".join(
            f"- {p['name']}：{p.get('label', p['name'])}，{p.get('description', '')}"
            f"（能力：{', '.join(p.get('default_capabilities') or [])}）"
            for p in visible_pools
        )

        llm = self.language_model_service.get_cheap_chat_model()
        structured = llm.with_structured_output(PoolMatchResult)
        result = structured.invoke(self._build_prompt(query, pool_descriptions, visible_pools))
        valid_names = {p["name"] for p in visible_pools}
        return [name for name in result.matched_pools if name in valid_names]

    @staticmethod
    def _build_prompt(query: str, pool_descriptions: str, pools: list[dict]) -> str:
        pool_names = "、".join(p["name"] for p in pools)
        return (
            "你是一名任务路由专家，负责将用户消息匹配到最合适的子池。\n\n"
            f"可用的子池列表：\n{pool_descriptions}\n\n"
            f"用户消息：{query}\n\n"
            f"请从以下子池中选择与用户消息最相关的：{pool_names}\n"
            "规则：\n"
            "1. 可选择 1-3 个子池，按相关度从高到低排列\n"
            "2. 如果没有明确匹配，返回 [\"general\"]\n"
            "3. 只能从上述子池列表中选择，不要编造不存在的子池名\n"
        )

    @staticmethod
    def _first_keyword(text: str, keywords: list[str]) -> str | None:
        lowered = text.lower()
        for keyword in keywords:
            if keyword.lower() in lowered:
                return keyword
        return None
