from dataclasses import dataclass, field
from typing import Any


@dataclass
class DAGNode:
    id: str
    agent_id: str | None
    title: str
    description: str
    depends_on: list[str] = field(default_factory=list)

    agent_instance: Any | None = None
    status: str = "pending"
    answer: str | None = None
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    token_usage: dict | None = None
    tool_calls: list[dict] | None = None


@dataclass
class DAGGraph:
    nodes: dict[str, DAGNode]
    original_query: str = ""
    aggregation_strategy: str = "concat"


@dataclass
class AgentInstanceSpec:
    agent_id: str
    agent_class: type
    llm: Any
    tools: list = field(default_factory=list)
    system_prompt: str | None = None
    max_iterations: int = 15
