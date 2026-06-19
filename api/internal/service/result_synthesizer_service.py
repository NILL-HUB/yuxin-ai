import logging

from injector import inject

from internal.entity.execution_orchestration_entity import (
    OrchestratedAgentResult,
)
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


@inject
class ResultSynthesizerService:
    def __init__(self, event_logger=None):
        self.event_logger = event_logger

    def synthesize(
        self,
        results: list[OrchestratedAgentResult],
        *,
        original_query: str = "",
        task_plan: dict | None = None,
        errors: list[str] | None = None,
        cost_summary: dict | None = None,
        routing_log_id=None,
    ) -> dict:
        self._emit("synthesis_started", routing_log_id, {"result_count": len(results)})
        valid_results = [
            result for result in results if result.answer and not result.errors
        ]
        internal_notes = self._build_internal_notes(
            original_query, task_plan, errors or [], cost_summary or {}, results
        )
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
        conflicts = self._detect_conflicts(valid_results)
        all_warnings = self._unique(
            [*self._warnings_from(results), *quality_warnings, *conflicts]
        )
        synthesis = {
            "final_answer": self._merge_answers(valid_results),
            "summary": self._build_summary(valid_results, original_query),
            "confidence": self._final_confidence(valid_results, quality_warnings, conflicts),
            "visible_sources": self._merge_sources(valid_results),
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
