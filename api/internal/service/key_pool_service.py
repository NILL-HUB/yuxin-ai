from dataclasses import dataclass, field

from internal.entity.billing_runtime_entity import ModelKeyItem


@dataclass
class KeyPoolService:
    keys: list[ModelKeyItem] = field(default_factory=list)
    failure_threshold: int = 3

    def select_key(self, provider: str) -> ModelKeyItem | None:
        candidates = [
            key
            for key in self.keys
            if key.provider == provider
            and key.status == "active"
            and key.remaining_credits > 0
        ]
        if not candidates:
            return None
        return sorted(
            candidates, key=lambda key: key.remaining_credits, reverse=True
        )[0]

    def record_failure(self, key_id: str) -> None:
        key = self._find_key(key_id)
        if key is None:
            return
        key.failure_count += 1
        if key.failure_count >= self.failure_threshold:
            key.status = "circuit_open"

    def _find_key(self, key_id: str) -> ModelKeyItem | None:
        for key in self.keys:
            if key.key_id == key_id:
                return key
        return None
