from internal.entity.execution_orchestration_entity import OrchestratedAgentResult


class FinalAnswerComposer:
    def compose(self, merged_sources: dict, conflicts: dict, results: list) -> dict:
        try:
            final_answer = self._merge_answers(results)
            confidence = self._compute_confidence(results, conflicts)
            warnings = self._collect_warnings(conflicts)
            return {
                "final_answer": final_answer,
                "confidence": confidence,
                "warnings": warnings,
            }
        except Exception:
            return {
                "final_answer": "",
                "confidence": 0.0,
                "warnings": [],
            }

    @staticmethod
    def _merge_answers(results: list) -> str:
        parts = []
        for r in results or []:
            if isinstance(r, OrchestratedAgentResult):
                answer = (r.answer or "").strip()
            elif isinstance(r, dict):
                answer = (r.get("answer") or "").strip()
            else:
                answer = ""
            if answer and answer not in parts:
                parts.append(answer)
        return "\n\n".join(parts)

    @staticmethod
    def _compute_confidence(results: list, conflicts) -> float:
        valid = [r for r in (results or []) if isinstance(r, OrchestratedAgentResult)]
        if not valid:
            return 0.0
        value = sum(r.confidence for r in valid) / len(valid)
        if any(r.confidence < 0.5 for r in valid):
            value -= 0.1
        conflict_list = []
        if isinstance(conflicts, dict):
            conflict_list = conflicts.get("conflicts") or []
        elif isinstance(conflicts, list):
            conflict_list = conflicts
        if conflict_list:
            value -= 0.05 * len(conflict_list)
        return round(max(value, 0), 2)

    @staticmethod
    def _collect_warnings(conflicts) -> list:
        if isinstance(conflicts, dict):
            return list(conflicts.get("conflicts") or [])
        if isinstance(conflicts, list):
            return list(conflicts)
        return []
