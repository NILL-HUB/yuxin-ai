from internal.entity.execution_orchestration_entity import (
    OrchestratedAgentResult,
)
from internal.service.result_quality_checker_service import ResultQualityCheckerService


class ResultSynthesizerService:
    def synthesize(self, results: list[OrchestratedAgentResult]) -> dict:
        valid_results = [
            result for result in results if result.answer and not result.errors
        ]
        if not valid_results:
            return {
                "final_answer": "当前任务暂时无法完成，请稍后重试或缩小任务范围。",
                "summary": "没有可用的 Agent 结果。",
                "confidence": 0,
                "visible_sources": [],
                "user_warnings": ["fallback:no_valid_agent_result"],
            }
        quality_warnings = ResultQualityCheckerService().check(valid_results)
        return {
            "final_answer": "\n\n".join(result.answer for result in valid_results),
            "summary": f"已整合 {len(valid_results)} 个 Agent 结果。",
            "confidence": self._final_confidence(valid_results, quality_warnings),
            "visible_sources": self._merge_sources(valid_results),
            "user_warnings": self._unique(
                [*self._warnings_from(results), *quality_warnings]
            ),
        }

    @staticmethod
    def _final_confidence(
        results: list[OrchestratedAgentResult], quality_warnings: list[str]
    ) -> float:
        value = sum(result.confidence for result in results) / len(results)
        if "quality:low_confidence" in quality_warnings:
            value -= 0.1
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
    def _unique(items: list[str]) -> list[str]:
        result = []
        for item in items:
            if item not in result:
                result.append(item)
        return result
