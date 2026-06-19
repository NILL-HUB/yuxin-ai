from dataclasses import dataclass, field

from internal.entity.billing_runtime_entity import ModelPoolItem


TIER_ORDER = ["cheap", "standard", "strong"]


@dataclass
class ModelPoolService:
    models: list[ModelPoolItem] = field(default_factory=list)

    def select_model(
        self, *, required_capabilities: list[str], preferred_tier: str
    ) -> ModelPoolItem | None:
        candidates = [
            model
            for model in self.models
            if self._is_available(model)
            and self._matches_capabilities(model, required_capabilities)
        ]
        if not candidates:
            return None
        for tier in self._tier_preference(preferred_tier):
            tier_candidates = [model for model in candidates if model.tier == tier]
            if tier_candidates:
                return sorted(
                    tier_candidates,
                    key=lambda model: model.price_per_1k_input_tokens,
                )[0]
        return None

    @staticmethod
    def _is_available(model: ModelPoolItem) -> bool:
        return model.enabled and model.health_status in {"healthy", "degraded"}

    @staticmethod
    def _matches_capabilities(
        model: ModelPoolItem, required_capabilities: list[str]
    ) -> bool:
        return all(item in model.capabilities for item in required_capabilities)

    @staticmethod
    def _tier_preference(preferred_tier: str) -> list[str]:
        if preferred_tier not in TIER_ORDER:
            preferred_tier = "standard"
        index = TIER_ORDER.index(preferred_tier)
        return [preferred_tier, *reversed(TIER_ORDER[:index]), *TIER_ORDER[index + 1 :]]
