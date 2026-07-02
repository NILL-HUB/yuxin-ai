from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.entity.agent_entity import normalize_agent_metadata
from internal.entity.app_entity import AppStatus
from internal.extension.database_extension import db
from internal.model.agent_pool_entity import AgentPoolConfig
from internal.model.app import App, AppAssignment


# AgentPoolConfig 不存在时的降级默认值，保证无配置记录的 App 也能被收集
_DEFAULT_POOL_CONFIG = {
    "primary_pool": "general",
    "secondary_pools": [],
    "risk_level": "safe",
    "model_tier": "standard",
    "routing_priority": 100,
}


BUILTIN_AGENT_CANDIDATES = [
    {
        "agent_id": "builtin:lightweight",
        "name": "轻量 Agent",
        "description": "适合快速处理通用任务",
        "source_scope": "builtin",
        "source_type": "builtin",
        "app_id": "",
        "metadata": {"primary_pool": "general", "routing_priority": 10},
        "visibility": "public",
        "status": AppStatus.PUBLISHED.value,
    },
    {
        "agent_id": "builtin:strong_reasoning",
        "name": "强推理 Agent",
        "description": "适合复杂推理和多步骤分析",
        "source_scope": "builtin",
        "source_type": "builtin",
        "app_id": "",
        "metadata": {"primary_pool": "research", "routing_priority": 20},
        "visibility": "public",
        "status": AppStatus.PUBLISHED.value,
    },
    {
        "agent_id": "builtin:deep_thinking",
        "name": "深度思考 Agent",
        "description": "适合深度规划和复杂问题拆解",
        "source_scope": "builtin",
        "source_type": "builtin",
        "app_id": "",
        "metadata": {"primary_pool": "general", "routing_priority": 30},
        "visibility": "public",
        "status": AppStatus.PUBLISHED.value,
    },
]


class AgentCandidateCollector:
    def __init__(self, session=None):
        self.session = session or db.session

    def collect(self, account_id: UUID) -> list[dict[str, object]]:
        candidates = []
        seen_app_ids = set()
        public_rows = (
            self.session.query(App, AgentPoolConfig)
            .outerjoin(AgentPoolConfig, AgentPoolConfig.app_id == App.id)
            .filter(App.is_public == True, App.status == AppStatus.PUBLISHED.value)
            .order_by(App.created_at.desc())
            .all()
        )
        for row in public_rows:
            app, pool_config = self._unpack_app_row(row)
            self._append_app_candidate(candidates, seen_app_ids, app, "public", pool_config)
        assignments = (
            self.session.query(AppAssignment)
            .filter(AppAssignment.account_id == account_id, AppAssignment.status == "active")
            .order_by(AppAssignment.assigned_at.desc())
            .all()
        )
        for assignment in assignments:
            app = getattr(assignment, "app", None)
            self._append_app_candidate(candidates, seen_app_ids, app, "assigned", None)
        own_rows = (
            self.session.query(App, AgentPoolConfig)
            .outerjoin(AgentPoolConfig, AgentPoolConfig.app_id == App.id)
            .filter(App.account_id == account_id, App.status == AppStatus.PUBLISHED.value)
            .order_by(App.created_at.desc())
            .all()
        )
        for row in own_rows:
            app, pool_config = self._unpack_app_row(row)
            self._append_app_candidate(candidates, seen_app_ids, app, "own", pool_config)
        serialized = [self._serialize_candidate(candidate) for candidate in candidates]
        serialized.extend(self._builtin_candidates())
        return serialized

    @staticmethod
    def _unpack_app_row(row) -> tuple[App, AgentPoolConfig | None]:
        """从 query(App, AgentPoolConfig).outerjoin(...).all() 的结果中拆出 App 和 AgentPoolConfig。

        真实查询返回 Row/tuple；测试 stub 可能直接返回 App 对象，此时降级为 (app, None)。
        """
        if isinstance(row, tuple):
            app = row[0]
            pool_config = row[1] if len(row) > 1 else None
            return app, pool_config
        return row, None

    @staticmethod
    def _normalize_pool_config(config: AgentPoolConfig | None) -> dict[str, object]:
        """把 AgentPoolConfig ORM 对象归一化为 dict；记录不存在时降级为默认值。"""
        if config is None:
            return dict(_DEFAULT_POOL_CONFIG)
        return {
            "primary_pool": config.primary_pool,
            "secondary_pools": config.secondary_pools or [],
            "risk_level": config.risk_level,
            "model_tier": config.model_tier,
            "routing_priority": config.routing_priority,
        }

    def collect_raw(self, account_id: UUID) -> list[dict[str, object]]:
        serialized = self.collect(account_id)
        raw_candidates = []
        for item in serialized:
            raw_candidates.append(item)
        return raw_candidates

    def collect_by_pools(
        self, account_id: UUID, pools: list[str], *, query: str = ""
    ) -> list[dict[str, object]]:
        candidates = self.collect(account_id)
        matched = {}
        backups = {}
        for candidate in candidates:
            match = self._match_candidate(candidate, pools, query)
            if match is None:
                continue
            target = backups if match["match_reason"] == "backup_pool:general" else matched
            agent_id = candidate["agent_id"]
            item = dict(candidate)
            item.update(match)
            current = target.get(agent_id)
            if current is None or item["semantic_score"] > current["semantic_score"]:
                target[agent_id] = item
        if matched:
            result = list(matched.values())
        else:
            app_backups = [
                item for item in backups.values() if item.get("source_type") == "app"
            ]
            result = app_backups or list(backups.values())
        return sorted(result, key=lambda item: item["semantic_score"], reverse=True)

    def _match_candidate(
        self, candidate: dict[str, object], pools: list[str], query: str
    ) -> dict[str, object] | None:
        metadata = normalize_agent_metadata(candidate.get("metadata"))
        primary_pool = metadata.get("primary_pool")
        secondary_pools = metadata.get("secondary_pools", [])
        capabilities = metadata.get("capabilities", [])
        task_types = metadata.get("task_types", [])
        if primary_pool in pools:
            return {
                "pool": primary_pool,
                "match_reason": f"primary_pool:{primary_pool}",
                "semantic_score": 1.0,
            }
        query_lowered = query.lower()
        capability = self._first_query_match(query_lowered, capabilities)
        if capability:
            return {
                "pool": primary_pool,
                "match_reason": f"capability:{capability}",
                "semantic_score": 0.85,
            }
        task_type = self._first_query_match(query_lowered, task_types)
        if task_type:
            return {
                "pool": primary_pool,
                "match_reason": f"task_type:{task_type}",
                "semantic_score": 0.75,
            }
        for pool in secondary_pools:
            if pool in pools:
                return {
                    "pool": pool,
                    "match_reason": f"secondary_pool:{pool}",
                    "semantic_score": 0.7,
                }
        text = f"{candidate.get('name', '')} {candidate.get('description', '')}".lower()
        for pool in pools:
            if pool and pool.lower() in text:
                return {
                    "pool": pool,
                    "match_reason": f"text:{pool}",
                    "semantic_score": 0.5,
                }
        if primary_pool == "general":
            return {
                "pool": "general",
                "match_reason": "backup_pool:general",
                "semantic_score": 0.2,
            }
        from internal.entity.agent_pool_entity import AgentSubPoolRegistry
        if AgentSubPoolRegistry().normalize_pool_name(primary_pool) == "general" and primary_pool != "general":
            return {
                "pool": "general",
                "match_reason": f"fallback_unknown_pool:{primary_pool}",
                "semantic_score": 0.1,
            }
        return None

    @staticmethod
    def _first_query_match(query_lowered: str, values: list[str]) -> str | None:
        aliases = {"frontend": ["frontend", "前端"]}
        for value in values:
            if not isinstance(value, str):
                continue
            keywords = aliases.get(value.lower(), [value])
            for keyword in keywords:
                if keyword.lower() in query_lowered:
                    return value
        return None

    def _append_app_candidate(
        self,
        candidates: list[dict[str, object]],
        seen_app_ids: set,
        app: App | None,
        source_scope: str,
        pool_config: AgentPoolConfig | None = None,
    ) -> None:
        if app is None or app.id in seen_app_ids:
            return
        if app.status != AppStatus.PUBLISHED.value:
            return
        metadata = app.normalized_agent_metadata
        if metadata.get("enabled") is False:
            return
        candidates.append(self._candidate(app, source_scope, metadata, pool_config))
        seen_app_ids.add(app.id)

    def _candidate(
        self,
        app: App,
        source_scope: str,
        metadata: dict[str, object],
        pool_config: AgentPoolConfig | None = None,
    ) -> dict[str, object]:
        return {
            "app": app,
            "source_scope": source_scope,
            "metadata": metadata,
            "pool_config": self._normalize_pool_config(pool_config),
        }

    @staticmethod
    def _serialize_candidate(candidate: dict[str, object]) -> dict[str, object]:
        app = candidate["app"]
        source_scope = candidate["source_scope"]
        pool_config = candidate.get("pool_config") or {}
        return {
            "id": str(app.id),
            "agent_id": str(app.id),
            "name": app.name,
            "icon": app.icon,
            "description": app.description,
            "status": app.status,
            "is_public": app.is_public,
            "source_scope": source_scope,
            "source_type": "app",
            "app_id": str(app.id),
            "visibility": "public" if app.is_public else "private",
            "metadata": candidate["metadata"],
            "primary_pool": pool_config.get("primary_pool", _DEFAULT_POOL_CONFIG["primary_pool"]),
            "secondary_pools": pool_config.get("secondary_pools", _DEFAULT_POOL_CONFIG["secondary_pools"]),
            "risk_level": pool_config.get("risk_level", _DEFAULT_POOL_CONFIG["risk_level"]),
            "model_tier": pool_config.get("model_tier", _DEFAULT_POOL_CONFIG["model_tier"]),
            "routing_priority": pool_config.get("routing_priority", _DEFAULT_POOL_CONFIG["routing_priority"]),
        }

    @staticmethod
    def _builtin_candidates() -> list[dict[str, object]]:
        candidates = []
        for candidate in BUILTIN_AGENT_CANDIDATES:
            item = dict(candidate)
            item["id"] = candidate["agent_id"]
            item["metadata"] = normalize_agent_metadata(candidate.get("metadata"))
            candidates.append(item)
        return candidates


@inject
@dataclass
class AgentPolicyFilter:
    def filter(
        self,
        candidates: list[dict[str, object]],
        *,
        account_id: UUID | None = None,
        requested_pool: str | None = None,
        input_modalities: list[str] | None = None,
        budget_level: str = "medium",
        required_tool_categories: list[str] | None = None,
    ) -> dict[str, object]:
        accepted = []
        filtered_out = []
        for candidate in candidates:
            app = candidate.get("app")
            if app is None:
                accepted.append(candidate)
                continue
            metadata = normalize_agent_metadata(candidate.get("metadata"))
            reason = self._reject_reason(
                app,
                candidate,
                metadata,
                requested_pool=requested_pool,
                input_modalities=input_modalities or [],
                budget_level=budget_level,
                required_tool_categories=required_tool_categories or [],
            )
            if reason:
                filtered_out.append(self._filtered(app, reason))
                continue
            accepted.append(self._serialize_candidate(candidate, metadata))
        return {"candidates": accepted, "filtered_out_agents": filtered_out}

    def _reject_reason(
        self,
        app: App,
        candidate: dict[str, object],
        metadata: dict[str, object],
        *,
        requested_pool: str | None,
        input_modalities: list[str],
        budget_level: str,
        required_tool_categories: list[str],
    ) -> str | None:
        if app.status != AppStatus.PUBLISHED.value:
            return "app_not_published"
        if candidate.get("source_scope") not in {"public", "assigned", "own"}:
            return "app_not_authorized"
        if metadata.get("primary_pool") == "internal_admin":
            return "pool_not_visible"
        if metadata.get("enabled") is False:
            return "agent_disabled"
        if metadata.get("risk_level") == "high":
            return "risk_level_requires_confirmation"
        if not self._cost_allowed(str(metadata.get("cost_level")), budget_level):
            return "cost_level_exceeds_budget"
        supported_modalities = set(metadata.get("input_modalities") or [])
        if any(modality not in supported_modalities for modality in input_modalities):
            return "input_modality_not_supported"
        allowed_tools = set(metadata.get("allowed_tool_categories") or [])
        if allowed_tools and any(
            category not in allowed_tools for category in required_tool_categories
        ):
            return "tool_category_not_allowed"
        return None

    @staticmethod
    def _cost_allowed(cost_level: str, budget_level: str) -> bool:
        order = {"low": 1, "medium": 2, "high": 3}
        return order.get(cost_level, 2) <= order.get(budget_level, 2)

    @staticmethod
    def _filtered(app: App, reason: str) -> dict[str, str]:
        return {"id": str(app.id), "name": app.name, "reason": reason}

    @staticmethod
    def _serialize_candidate(
        candidate: dict[str, object], metadata: dict[str, object]
    ) -> dict[str, object]:
        app = candidate["app"]
        return {
            "id": str(app.id),
            "agent_id": str(app.id),
            "name": app.name,
            "icon": app.icon,
            "description": app.description,
            "source_scope": candidate["source_scope"],
            "source_type": "app",
            "app_id": str(app.id),
            "metadata": metadata,
        }


class AgentRanker:
    def rank(
        self,
        candidates: list[dict[str, object]],
        *,
        required_capabilities: list[str] | None = None,
    ) -> list[dict[str, object]]:
        ranked = []
        for candidate in candidates:
            item = dict(candidate)
            breakdown = self._score_breakdown(
                item, required_capabilities=required_capabilities or []
            )
            item["score_breakdown"] = breakdown
            item["score"] = round(
                breakdown["capability_score"] * 0.35
                + breakdown["semantic_score"] * 0.25
                + breakdown["quality_score"] * 0.20
                + breakdown["cost_score"] * 0.10
                + breakdown["latency_score"] * 0.05
                + breakdown["priority_score"] * 0.05,
                4,
            )
            ranked.append(item)
        return sorted(
            ranked,
            key=lambda item: (
                -item["score"],
                item.get("name", ""),
                item.get("agent_id", ""),
            ),
        )

    def _score_breakdown(
        self, candidate: dict[str, object], *, required_capabilities: list[str]
    ) -> dict[str, float]:
        metadata = normalize_agent_metadata(candidate.get("metadata"))
        return {
            "capability_score": self._capability_score(
                metadata.get("capabilities", []), required_capabilities
            ),
            "semantic_score": float(candidate.get("semantic_score") or 0.0),
            "quality_score": float(metadata.get("quality_score") or 0.0),
            "cost_score": self._cost_score(str(metadata.get("cost_level"))),
            "latency_score": self._latency_score(int(metadata.get("latency_p95") or 0)),
            "priority_score": float(metadata.get("routing_priority") or 0) / 1000,
        }

    @staticmethod
    def _capability_score(capabilities: list[str], required: list[str]) -> float:
        if not required:
            return 0.5
        if all(capability in capabilities for capability in required):
            return 1.0
        if any(capability in capabilities for capability in required):
            return 0.5
        return 0.0

    @staticmethod
    def _cost_score(cost_level: str) -> float:
        return {"low": 1.0, "medium": 0.6, "high": 0.2}.get(cost_level, 0.6)

    @staticmethod
    def _latency_score(latency_p95: int) -> float:
        if latency_p95 <= 0:
            return 0.5
        if latency_p95 <= 500:
            return 1.0
        if latency_p95 <= 1500:
            return 0.6
        return 0.2


class CrossPoolAgentSubsetBuilder:
    @inject
    def __init__(
        self,
        collector: AgentCandidateCollector,
        policy_filter: AgentPolicyFilter,
        ranker=None,
    ):
        self.collector = collector
        self.policy_filter = policy_filter
        self.ranker = ranker or AgentRanker()

    def build(self, account_id: UUID, *, primary_pool: str | None = None) -> dict[str, object]:
        candidates = self.collector.collect(account_id)
        return self._filter_serialized_candidates(candidates, primary_pool=primary_pool)

    def build_subset(
        self,
        candidates: list[dict[str, object]],
        *,
        primary_pool: str | None = None,
    ) -> dict[str, object]:
        filtered = self.policy_filter.filter(candidates)
        return self._filter_serialized_candidates(filtered["candidates"], primary_pool=primary_pool) | {
            "filtered_out_agents": filtered["filtered_out_agents"]
        }

    def build_subset_from_candidates(
        self,
        candidates: list[dict[str, object]],
        *,
        matched_pools: list[str],
        filtered_out_agents: list[dict] | None = None,
        max_agent_count: int = 3,
        per_pool_limit: int = 1,
    ) -> dict[str, object]:
        ranked = self.ranker.rank(candidates)
        selected_agents = []
        backup_agents = []
        selected_per_pool = {}
        for candidate in ranked:
            pool = candidate.get("pool") or candidate.get("metadata", {}).get(
                "primary_pool"
            )
            if pool == "general" or pool not in matched_pools:
                backup_agents.append(candidate)
                continue
            selected_count = selected_per_pool.get(pool, 0)
            if len(selected_agents) < max_agent_count and selected_count < per_pool_limit:
                selected_agents.append(candidate)
                selected_per_pool[pool] = selected_count + 1
            else:
                backup_agents.append(candidate)
        return {
            "matched_agent_pools": matched_pools,
            "max_agent_count": max_agent_count,
            "selected_agents": selected_agents,
            "backup_agents": backup_agents,
            "filtered_out_agents": filtered_out_agents or [],
            "selection_reason": f"matched pools: {','.join(matched_pools)}",
        }

    def _filter_serialized_candidates(
        self,
        candidates: list[dict[str, object]],
        *,
        primary_pool: str | None = None,
    ) -> dict[str, object]:
        if primary_pool:
            candidates = [
                candidate for candidate in candidates
                if candidate.get("metadata", {}).get("primary_pool") == primary_pool
            ]
        candidates = sorted(
            candidates,
            key=lambda candidate: candidate.get("metadata", {}).get("routing_priority", 0),
            reverse=True,
        )
        return {"candidates": candidates, "filtered_out_agents": []}
