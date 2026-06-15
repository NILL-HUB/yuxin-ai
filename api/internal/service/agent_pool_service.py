from dataclasses import dataclass
from uuid import UUID

from injector import inject

from internal.entity.agent_entity import normalize_agent_metadata
from internal.entity.app_entity import AppStatus
from internal.extension.database_extension import db
from internal.model.app import App, AppAssignment


class AgentCandidateCollector:
    def __init__(self, session=None):
        self.session = session or db.session

    def collect(self, account_id: UUID) -> list[dict[str, object]]:
        candidates = []
        seen_app_ids = set()
        public_apps = (
            self.session.query(App)
            .filter(App.is_public == True, App.status == AppStatus.PUBLISHED.value)
            .order_by(App.created_at.desc())
            .all()
        )
        for app in public_apps:
            candidates.append(self._candidate(app, "public"))
            seen_app_ids.add(app.id)
        assignments = (
            self.session.query(AppAssignment)
            .filter(AppAssignment.account_id == account_id, AppAssignment.status == "active")
            .order_by(AppAssignment.assigned_at.desc())
            .all()
        )
        for assignment in assignments:
            app = getattr(assignment, "app", None)
            if app is None or app.id in seen_app_ids:
                continue
            candidates.append(self._candidate(app, "assigned"))
            seen_app_ids.add(app.id)
        return [self._serialize_candidate(candidate) for candidate in candidates]

    def collect_raw(self, account_id: UUID) -> list[dict[str, object]]:
        serialized = self.collect(account_id)
        raw_candidates = []
        for item in serialized:
            raw_candidates.append(item)
        return raw_candidates

    def _candidate(self, app: App, source_scope: str) -> dict[str, object]:
        return {
            "app": app,
            "source_scope": source_scope,
            "metadata": app.normalized_agent_metadata,
        }

    @staticmethod
    def _serialize_candidate(candidate: dict[str, object]) -> dict[str, object]:
        app = candidate["app"]
        return {
            "id": str(app.id),
            "name": app.name,
            "icon": app.icon,
            "description": app.description,
            "status": app.status,
            "is_public": app.is_public,
            "source_scope": candidate["source_scope"],
            "metadata": candidate["metadata"],
        }


@inject
@dataclass
class AgentPolicyFilter:
    def filter(self, candidates: list[dict[str, object]]) -> dict[str, object]:
        accepted = []
        filtered_out = []
        for candidate in candidates:
            app = candidate.get("app")
            if app is None:
                accepted.append(candidate)
                continue
            if app.status != AppStatus.PUBLISHED.value:
                filtered_out.append(self._filtered(app, "app_not_published"))
                continue
            if candidate.get("source_scope") not in {"public", "assigned", "own"}:
                filtered_out.append(self._filtered(app, "app_not_authorized"))
                continue
            accepted.append(self._serialize_candidate(candidate))
        return {"candidates": accepted, "filtered_out_agents": filtered_out}

    @staticmethod
    def _filtered(app: App, reason: str) -> dict[str, str]:
        return {"id": str(app.id), "name": app.name, "reason": reason}

    @staticmethod
    def _serialize_candidate(candidate: dict[str, object]) -> dict[str, object]:
        app = candidate["app"]
        return {
            "id": str(app.id),
            "name": app.name,
            "icon": app.icon,
            "description": app.description,
            "source_scope": candidate["source_scope"],
            "metadata": normalize_agent_metadata(candidate.get("metadata")),
        }


@inject
@dataclass
class CrossPoolAgentSubsetBuilder:
    collector: AgentCandidateCollector
    policy_filter: AgentPolicyFilter

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
