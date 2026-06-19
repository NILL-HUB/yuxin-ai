from internal.entity.execution_orchestration_entity import OrchestratedAgentResult


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


class ConflictResolver:
    def resolve(self, merged_sources: dict) -> dict:
        try:
            results = self._extract_results(merged_sources)
            conflicts = self._detect_conflicts(results)
            if conflicts:
                return {
                    "conflicts": conflicts,
                    "resolved": False,
                    "resolution_strategy": "requires_manual_review",
                }
            return {
                "conflicts": [],
                "resolved": True,
                "resolution_strategy": "none",
            }
        except Exception:
            return {
                "conflicts": [],
                "resolved": True,
                "resolution_strategy": "none",
            }

    @staticmethod
    def _extract_results(merged_sources) -> list:
        if not isinstance(merged_sources, dict):
            return []
        results = merged_sources.get("results")
        if isinstance(results, list):
            return results
        return []

    @staticmethod
    def _detect_conflicts(results) -> list:
        if not results or len(results) < 2:
            return []
        conflicts = []
        answers = []
        for r in results:
            if isinstance(r, OrchestratedAgentResult):
                answers.append((r.agent_id, r.answer or ""))
            elif isinstance(r, dict):
                answers.append((r.get("agent_id", "") or "", r.get("answer", "") or ""))
            else:
                answers.append(("", str(r)))
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
