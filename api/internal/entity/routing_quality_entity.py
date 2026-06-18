from dataclasses import dataclass, field


ROUTING_QUALITY_FEEDBACK_SOURCES = ["admin", "system", "user_signal"]
ROUTING_QUALITY_DIMENSIONS = [
    "completeness",
    "accuracy",
    "latency",
    "cost",
    "safety",
]
ROUTING_OPTIMIZATION_SUGGESTION_STATUSES = ["open", "accepted", "dismissed", "applied"]


@dataclass
class RoutingQualityFeedback:
    routing_log_id: str
    source: str
    rating: int
    dimension_scores: dict = field(default_factory=dict)
    comment: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.source not in ROUTING_QUALITY_FEEDBACK_SOURCES:
            raise ValueError(
                "Unsupported routing quality feedback source: "
                f"{self.source}"
            )
        if self.rating < 1 or self.rating > 5:
            raise ValueError("Routing quality feedback rating must be between 1 and 5")
        unknown_dimensions = set(self.dimension_scores) - set(
            ROUTING_QUALITY_DIMENSIONS
        )
        if unknown_dimensions:
            raise ValueError(
                "Unsupported routing quality dimensions: "
                f"{sorted(unknown_dimensions)}"
            )

    def to_dict(self) -> dict:
        return {
            "routing_log_id": self.routing_log_id,
            "source": self.source,
            "rating": self.rating,
            "dimension_scores": self.dimension_scores,
            "comment": self.comment,
            "metadata": self.metadata,
        }


@dataclass
class RoutingOptimizationSuggestion:
    target_type: str
    target_id: str
    suggestion_type: str
    severity: str
    reason: str
    evidence: dict = field(default_factory=dict)
    status: str = "open"

    def __post_init__(self):
        if self.status not in ROUTING_OPTIMIZATION_SUGGESTION_STATUSES:
            raise ValueError(
                "Unsupported routing optimization suggestion status: "
                f"{self.status}"
            )

    def to_dict(self) -> dict:
        return {
            "target_type": self.target_type,
            "target_id": self.target_id,
            "suggestion_type": self.suggestion_type,
            "severity": self.severity,
            "reason": self.reason,
            "evidence": self.evidence,
            "status": self.status,
        }


@dataclass
class RoutingQualityScore:
    dimension: str
    score: float

    def __post_init__(self):
        if self.dimension not in ROUTING_QUALITY_DIMENSIONS:
            raise ValueError(
                "Unsupported routing quality dimension: "
                f"{self.dimension}"
            )

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "score": self.score,
        }
