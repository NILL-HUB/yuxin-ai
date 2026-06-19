from internal.entity.execution_orchestration_entity import OrchestratedAgentResult


class AgentResultNormalizer:
    def normalize(self, result) -> OrchestratedAgentResult:
        try:
            if isinstance(result, OrchestratedAgentResult):
                return self._normalize_from_entity(result)
            if isinstance(result, dict):
                return self._normalize_from_dict(result)
            return self._default()
        except Exception:
            return self._default()

    @staticmethod
    def _normalize_from_entity(result: OrchestratedAgentResult) -> OrchestratedAgentResult:
        confidence = result.confidence
        if not isinstance(confidence, (int, float)):
            confidence = 0.0
        return OrchestratedAgentResult(
            agent_id=result.agent_id or "",
            task_id=result.task_id or "",
            answer=result.answer or "",
            confidence=confidence,
            sources=list(result.sources or []),
            tool_calls=list(result.tool_calls or []),
            warnings=list(result.warnings or []),
            errors=list(result.errors or []),
            cost=dict(result.cost or {}),
            metadata=dict(result.metadata or {}),
        )

    @staticmethod
    def _normalize_from_dict(data: dict) -> OrchestratedAgentResult:
        return OrchestratedAgentResult.from_dict(data)

    @staticmethod
    def _default() -> OrchestratedAgentResult:
        return OrchestratedAgentResult(
            agent_id="",
            task_id="",
            answer="",
            confidence=0.0,
            sources=[],
            tool_calls=[],
            warnings=[],
            errors=[],
            cost={},
            metadata={},
        )
