import logging

from injector import inject

from internal.entity.execution_orchestration_entity import (
    OrchestratedAgentResult,
)
from internal.entity.knowledge_entity import KnowledgeScope
from internal.service.result.agent_result_normalizer import AgentResultNormalizer
from internal.service.result.conflict_resolver import ConflictResolver
from internal.service.result.evidence_merger import EvidenceMerger
from internal.service.result.final_answer_composer import FinalAnswerComposer
from internal.service.result_quality_checker_service import ResultQualityCheckerService


logger = logging.getLogger(__name__)


_CONFLICT_PAIRS = [
    ("应该", "不应该"),
    ("推荐", "不推荐"),
    ("可以", "不可以"),
    ("正确", "错误"),
    ("安全", "不安全"),
    ("是", "不是"),
    ("需要", "不需要"),
    ("使用", "不使用"),
    ("启用", "禁用"),
]


class SystemRulePriorityResolver:
    """系统规则优先级解析器：区分系统规则与用户偏好，冲突时系统规则优先。

    架构文档 11.4 第 6 点：
    - 系统规则（system/tenant/project scope）用更高优先级指令包装，不可被用户偏好覆盖
    - 用户偏好（user_memory/user_content scope）用软性建议包装，与系统规则冲突时忽略
    - 表达风格类偏好允许用户偏好生效（不视为冲突）
    - 通过 memory_type 区分事实性记忆与偏好类记忆
    """

    # 系统规则作用域：system/tenant/project（组织级规则，必须遵守）
    SYSTEM_RULE_SCOPES = {
        KnowledgeScope.SYSTEM.value,
        KnowledgeScope.TENANT.value,
        KnowledgeScope.PROJECT.value,
    }
    # 用户偏好作用域：user_memory/user_content
    USER_PREFERENCE_SCOPES = {
        KnowledgeScope.USER_MEMORY.value,
        KnowledgeScope.USER_CONTENT.value,
    }
    # 事实性记忆类型：不视为偏好，不参与规则冲突检测
    FACTUAL_MEMORY_TYPES = {"secret", "event", "project"}

    def resolve(self, retrieval_context: list[dict] | None) -> dict:
        """将检索上下文按作用域分类为系统规则区与用户偏好区，并构建 prompt 区段。

        :param retrieval_context: 检索结果列表，每项含 knowledge_scope/content/memory_type 等
        :return: {
            "system_rules": list[dict],      # 系统规则片段
            "user_preferences": list[dict],  # 用户偏好片段
            "neutral_facts": list[dict],     # 事实性用户记忆（不参与冲突）
            "context_sections": str,         # 拼接好的 prompt 区段（供 FinalAnswerComposer 注入）
            "has_conflict_risk": bool,       # 是否存在规则性冲突风险（简化检测）
        }
        """
        if not retrieval_context:
            return {
                "system_rules": [],
                "user_preferences": [],
                "neutral_facts": [],
                "context_sections": "",
                "has_conflict_risk": False,
            }

        system_rules: list[dict] = []
        user_preferences: list[dict] = []
        neutral_facts: list[dict] = []

        for item in retrieval_context or []:
            if not isinstance(item, dict):
                continue
            scope = str(item.get("knowledge_scope", "") or "")
            memory_type = str(item.get("memory_type", "") or "")
            content = str(item.get("content", "") or "").strip()
            if not content:
                continue

            if scope in self.SYSTEM_RULE_SCOPES:
                # system/tenant/project 作用域视为系统规则
                system_rules.append(item)
            elif scope == KnowledgeScope.USER_MEMORY.value:
                # user_memory 通过 memory_type 区分事实性记忆与偏好
                if memory_type == "preference":
                    user_preferences.append(item)
                else:
                    # secret/event/project 类记忆为事实性，不参与规则冲突
                    neutral_facts.append(item)
            elif scope in self.USER_PREFERENCE_SCOPES:
                # user_content 视为软性参考
                user_preferences.append(item)
            else:
                # 未知作用域，归入中性事实
                neutral_facts.append(item)

        context_sections = self._build_context_sections(
            system_rules, user_preferences, neutral_facts
        )
        # 简化冲突风险检测：同时存在系统规则与用户偏好时标记风险
        has_conflict_risk = bool(system_rules and user_preferences)

        return {
            "system_rules": system_rules,
            "user_preferences": user_preferences,
            "neutral_facts": neutral_facts,
            "context_sections": context_sections,
            "has_conflict_risk": has_conflict_risk,
        }

    @staticmethod
    def _build_context_sections(
        system_rules: list[dict],
        user_preferences: list[dict],
        neutral_facts: list[dict],
    ) -> str:
        """按架构文档 11.4 第 6 点构建 prompt 区段：
        - 系统规则区：高优先级指令包装
        - 用户偏好区：软性建议包装
        - 用户事实记忆区：中性参考
        """
        sections: list[str] = []

        if system_rules:
            rules_text = "\n".join(
                f"- {str(item.get('content', '')).strip()}"
                for item in system_rules
                if str(item.get("content", "")).strip()
            )
            if rules_text:
                sections.append(
                    "【系统规则（必须遵守，不可被用户偏好覆盖）】\n" + rules_text
                )

        if user_preferences:
            prefs_text = "\n".join(
                f"- {str(item.get('content', '')).strip()}"
                for item in user_preferences
                if str(item.get("content", "")).strip()
            )
            if prefs_text:
                sections.append(
                    "【用户偏好（参考，如与系统规则冲突则忽略）】\n" + prefs_text
                )

        if neutral_facts:
            facts_text = "\n".join(
                f"- {str(item.get('content', '')).strip()}"
                for item in neutral_facts
                if str(item.get("content", "")).strip()
            )
            if facts_text:
                sections.append("【用户事实记忆（仅供参考）】\n" + facts_text)

        return "\n\n".join(sections)


@inject
class ResultSynthesizerService:
    def __init__(self, event_logger=None, digest_manager=None):
        self.event_logger = event_logger
        self.digest_manager = digest_manager

    def synthesize(
        self,
        results: list[OrchestratedAgentResult],
        *,
        original_query: str = "",
        task_plan: dict | None = None,
        errors: list[str] | None = None,
        cost_summary: dict | None = None,
        routing_log_id=None,
        retrieval_context: list[dict] | None = None,
        user_id: str = "",
    ) -> dict:
        self._emit("synthesis_started", routing_log_id, {"result_count": len(results)})
        internal_notes = self._build_internal_notes(
            original_query, task_plan, errors or [], cost_summary or {}, results
        )

        # 解析检索上下文：区分系统规则与用户偏好，冲突时系统规则优先（架构文档 11.4 第 6 点）
        scope_resolver = SystemRulePriorityResolver()
        scope_result = scope_resolver.resolve(retrieval_context)
        context_sections = scope_result["context_sections"]

        # 注入 Memory Digest 区段（B8 集成 DigestManager）
        # 与系统规则/用户偏好区段并列，互不覆盖；异常时不阻断合成
        # digest_manager 懒加载：@inject 未标注类型时不自动注入，从 injector 获取
        digest_manager = self.digest_manager
        if digest_manager is None:
            digest_manager = self._get_digest_manager()
        if digest_manager is not None and user_id:
            try:
                memory_digest = digest_manager.get_digest(user_id)
                if memory_digest:
                    digest_section = f"【用户记忆摘要】\n{memory_digest}"
                    if context_sections:
                        context_sections = context_sections + "\n\n" + digest_section
                    else:
                        context_sections = digest_section
            except Exception:
                logger.warning(
                    "synthesize: 获取 Memory Digest 失败 user=%s，跳过记忆注入",
                    user_id,
                    exc_info=True,
                )

        normalizer = AgentResultNormalizer()
        evidence_merger = EvidenceMerger()
        conflict_resolver = ConflictResolver()
        composer = FinalAnswerComposer()

        normalized_results = [normalizer.normalize(result) for result in results]
        valid_results = [
            result
            for result in normalized_results
            if result.answer and not result.errors
        ]
        if not valid_results:
            synthesis = {
                "final_answer": "当前任务暂时无法完成，请稍后重试或缩小任务范围。",
                "summary": "没有可用的 Agent 结果。",
                "confidence": 0,
                "visible_sources": [],
                "user_warnings": ["fallback:no_valid_agent_result"],
                "internal_notes": internal_notes,
            }
            self._emit(
                "synthesis_completed",
                routing_log_id,
                {"confidence": 0, "visible_sources_count": 0},
            )
            return synthesis
        quality_warnings = ResultQualityCheckerService().check(valid_results)
        merged = evidence_merger.merge(valid_results)
        conflict_result = conflict_resolver.resolve(
            {"results": valid_results, **merged}
        )
        conflicts = conflict_result.get("conflicts", [])
        # 注入检索上下文区段（系统规则/用户偏好）到 FinalAnswerComposer
        composed = composer.compose(
            merged, conflict_result, valid_results,
            context_sections=context_sections,
        )
        all_warnings = self._unique(
            [*self._warnings_from(normalized_results), *quality_warnings, *conflicts]
        )
        synthesis = {
            "final_answer": composed["final_answer"],
            "summary": self._build_summary(valid_results, original_query),
            "confidence": composed["confidence"],
            "visible_sources": merged.get("merged_sources", []),
            "user_warnings": all_warnings,
            "internal_notes": internal_notes,
        }
        self._emit(
            "synthesis_completed",
            routing_log_id,
            {
                "confidence": synthesis["confidence"],
                "visible_sources_count": len(synthesis["visible_sources"]),
            },
        )
        return synthesis

    def _emit(self, event_type: str, routing_log_id, detail: dict) -> None:
        if self.event_logger is None or routing_log_id is None:
            return
        try:
            self.event_logger.log_event(event_type, routing_log_id, detail)
        except Exception:
            logger.warning("记录合成阶段事件失败: %s", event_type, exc_info=True)

    @staticmethod
    def _get_digest_manager():
        """懒加载 DigestManager 实例，不可用时返回 None。"""
        try:
            from internal.context import current_app

            injector = getattr(current_app, "injector", None)
            if injector is not None:
                from internal.service.memory.digest_manager import DigestManager

                return injector.get(DigestManager)
        except Exception:
            logger.warning("_get_digest_manager: 获取 DigestManager 失败", exc_info=True)
        return None

    @staticmethod
    def _merge_answers(results: list[OrchestratedAgentResult]) -> str:
        parts = []
        for r in results:
            answer = (r.answer or "").strip()
            if answer and answer not in parts:
                parts.append(answer)
        return "\n\n".join(parts)

    @staticmethod
    def _build_summary(results: list[OrchestratedAgentResult], original_query: str) -> str:
        if len(results) == 1:
            return f"基于单个智能体的回答，针对问题「{original_query}」"
        agent_ids = [r.agent_id for r in results if r.agent_id]
        if agent_ids:
            return f"已整合 {len(results)} 个 Agent 结果（{', '.join(agent_ids[:3])}）。"
        return f"已整合 {len(results)} 个 Agent 结果。"

    @staticmethod
    def _final_confidence(
        results: list[OrchestratedAgentResult],
        quality_warnings: list[str],
        conflicts: list[str],
    ) -> float:
        value = sum(result.confidence for result in results) / len(results)
        if "quality:low_confidence" in quality_warnings:
            value -= 0.1
        if conflicts:
            value -= 0.05 * len(conflicts)
        return round(max(value, 0), 2)

    @staticmethod
    def _merge_sources(results: list[OrchestratedAgentResult]) -> list[str]:
        sources = []
        for result in results:
            for source in result.sources:
                if source not in sources:
                    sources.append(source)
        return sources

    @staticmethod
    def _warnings_from(results: list[OrchestratedAgentResult]) -> list[str]:
        warnings = []
        for result in results:
            if result.errors:
                warnings.extend(result.warnings)
        return ResultSynthesizerService._unique(warnings)

    @staticmethod
    def _detect_conflicts(results: list[OrchestratedAgentResult]) -> list[str]:
        if len(results) < 2:
            return []
        conflicts = []
        answers = [(r.agent_id, r.answer or "") for r in results]
        for i in range(len(answers)):
            for j in range(i + 1, len(answers)):
                agent_a, answer_a = answers[i]
                agent_b, answer_b = answers[j]
                for positive, negative in _CONFLICT_PAIRS:
                    if (positive in answer_a and negative in answer_b) or (
                        negative in answer_a and positive in answer_b
                    ):
                        conflicts.append(
                            f"conflict:{agent_a}_vs_{agent_b}:{positive}/{negative}"
                        )
                        break
        return conflicts

    @staticmethod
    def _build_internal_notes(
        original_query: str,
        task_plan: dict | None,
        errors: list[str],
        cost_summary: dict,
        results: list[OrchestratedAgentResult],
    ) -> dict:
        return {
            "original_query": original_query,
            "task_plan": task_plan,
            "errors": errors,
            "cost_summary": cost_summary,
            "agent_outputs": [
                {
                    "agent_id": r.agent_id,
                    "answer_length": len(r.answer or ""),
                    "confidence": r.confidence,
                    "tool_calls_count": len(r.tool_calls or []),
                    "has_errors": bool(r.errors),
                }
                for r in results
            ],
        }

    @staticmethod
    def _unique(items: list[str]) -> list[str]:
        result = []
        for item in items:
            if item not in result:
                result.append(item)
        return result
