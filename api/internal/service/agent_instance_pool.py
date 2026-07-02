from typing import Any
from dataclasses import dataclass, field


@dataclass
class AgentInstancePool:
    _instances: dict[str, Any] = field(default_factory=dict)

    def create_instance(self, agent_id: str, agent_class: type, llm: Any,
                        tools: list | None = None,
                        system_prompt: str | None = None,
                        max_iterations: int = 15) -> Any:
        instance = agent_class(
            llm=llm,
            system_prompt=system_prompt or "",
            max_iterations=max_iterations,
        )
        if tools:
            setattr(instance, "tools", tools)
        if hasattr(instance, "reset"):
            instance.reset()
        self._instances[agent_id] = instance
        return instance

    def get_instance(self, agent_id: str) -> Any | None:
        return self._instances.get(agent_id)

    def clear(self) -> None:
        self._instances.clear()
