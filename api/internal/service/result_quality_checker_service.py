from internal.entity.execution_orchestration_entity import (
    OrchestratedAgentResult,
)


class ResultQualityCheckerService:
    def check(self, results: list[OrchestratedAgentResult]) -> list[str]:
        warnings = []
        if self._has_conflict(results):
            warnings.append("conflict:contradictory_answers")
        if any(result.confidence < 0.5 for result in results):
            warnings.append("quality:low_confidence")
        for result in results:
            if "high_risk_requires_confirmation" in result.warnings:
                warnings.append("high_risk_requires_confirmation")
        return self._unique(warnings)

    @staticmethod
    def _has_conflict(results: list[OrchestratedAgentResult]) -> bool:
        answers = [result.answer for result in results if result.answer]
        for answer in answers:
            if answer.startswith("不"):
                positive = answer.removeprefix("不")
                if any(positive in item for item in answers if item != answer):
                    return True
            negative = f"不{answer}"
            if any(item.startswith(negative) for item in answers if item != answer):
                return True
        return False

    @staticmethod
    def _unique(items: list[str]) -> list[str]:
        result = []
        for item in items:
            if item not in result:
                result.append(item)
        return result
