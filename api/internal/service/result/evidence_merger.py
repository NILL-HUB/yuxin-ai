from internal.entity.execution_orchestration_entity import OrchestratedAgentResult


class EvidenceMerger:
    def merge(self, results: list) -> dict:
        try:
            merged_sources = []
            for result in results or []:
                sources = self._extract_sources(result)
                for source in sources:
                    if source not in merged_sources:
                        merged_sources.append(source)
            return {
                "merged_sources": merged_sources,
                "total_count": len(merged_sources),
            }
        except Exception:
            return {"merged_sources": [], "total_count": 0}

    @staticmethod
    def _extract_sources(result) -> list:
        if isinstance(result, OrchestratedAgentResult):
            return list(result.sources or [])
        if isinstance(result, dict):
            sources = result.get("sources")
            return list(sources) if isinstance(sources, list) else []
        return []
