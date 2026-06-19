from datetime import UTC, datetime
import logging
from uuid import UUID

from injector import inject

from internal.entity.policy_change_entity import PolicyChangeDraft
from internal.exception import NotFoundException
from internal.model import PolicyChangeDraftModel, RoutingOptimizationSuggestionModel
from internal.service.audit_log_service import AuditLogService
from internal.service.orchestration_feature_flag_service import (
    OrchestrationFeatureFlagService,
)
from pkg.sqlalchemy import SQLAlchemy


logger = logging.getLogger(__name__)


_SUGGESTION_TO_POLICY_TYPE = {
    "review_model_cost": "model_routing",
    "review_tool_health": "tool_policy",
    "review_fallback_rate": "model_routing",
    "collect_more_feedback": "model_routing",
}


class RoutingPolicyChangeService:
    @inject
    def __init__(
        self,
        db: SQLAlchemy,
        audit_log_service: AuditLogService,
        orchestration_feature_flag_service: OrchestrationFeatureFlagService,
    ):
        self.db = db
        self.audit_log_service = audit_log_service
        self.orchestration_feature_flag_service = orchestration_feature_flag_service

    def generate_preview(self, suggestion_id: UUID) -> dict:
        suggestion = self._get_suggestion(suggestion_id)
        policy_type = _SUGGESTION_TO_POLICY_TYPE.get(
            suggestion.suggestion_type, "model_routing"
        )
        before_config = self._build_before_config(suggestion, policy_type)
        after_config = self._build_after_config(suggestion, policy_type)
        diff = self._build_diff(before_config, after_config)
        impact = self._build_impact(suggestion, policy_type)
        draft = PolicyChangeDraft(
            suggestion_id=str(suggestion.id),
            policy_type=policy_type,
            target_id=suggestion.target_id,
            before_config=before_config,
            after_config=after_config,
            diff=diff,
            impact=impact,
        )
        return draft.to_dict()

    def apply_draft(
        self,
        suggestion_id: UUID,
        admin_user_id: UUID,
        preview_data: dict,
    ) -> dict:
        suggestion = self._get_suggestion(suggestion_id)
        if suggestion.status != "accepted":
            raise ValueError(f"建议当前状态为 {suggestion.status}，需先采纳后才能应用")
        try:
            draft = PolicyChangeDraftModel(
                suggestion_id=suggestion.id,
                policy_type=preview_data.get("policy_type", "model_routing"),
                target_id=preview_data.get("target_id", suggestion.target_id),
                before_config=preview_data.get("before_config", {}),
                after_config=preview_data.get("after_config", {}),
                diff=preview_data.get("diff", {}),
                impact=preview_data.get("impact", {}),
                status="applied",
                applied_by=admin_user_id,
                applied_at=datetime.now(UTC).replace(tzinfo=None),
            )
            self.db.session.add(draft)
            self.db.session.flush()

            suggestion.status = "applied"
            suggestion.applied_by = admin_user_id
            suggestion.applied_at = datetime.now(UTC).replace(tzinfo=None)
            suggestion.policy_change_draft_id = draft.id

            self._apply_policy_changes(
                draft.policy_type, draft.after_config, admin_user_id
            )

            self._write_audit(
                admin_user_id=admin_user_id,
                action="policy_change_apply",
                target_id=str(draft.id),
                detail={
                    "suggestion_id": str(suggestion.id),
                    "policy_type": draft.policy_type,
                    "target_id": draft.target_id,
                    "before_config": draft.before_config,
                    "after_config": draft.after_config,
                },
            )
            self.db.session.commit()
        except Exception:
            self.db.session.rollback()
            raise
        return {
            "draft_id": str(draft.id),
            "status": draft.status,
            "suggestion_status": suggestion.status,
        }

    def rollback_draft(
        self,
        draft_id: UUID,
        admin_user_id: UUID,
        reason: str = "",
    ) -> dict:
        draft = self._get_draft(draft_id)
        if draft.status != "applied":
            raise ValueError(f"草稿当前状态为 {draft.status}，仅 applied 状态可回滚")
        try:
            draft.status = "rolled_back"
            draft.rolled_back_at = datetime.now(UTC).replace(tzinfo=None)
            draft.rollback_reason = reason or ""

            suggestion = (
                self.db.session.query(RoutingOptimizationSuggestionModel)
                .filter_by(id=draft.suggestion_id)
                .one_or_none()
            )
            if suggestion and suggestion.status == "applied":
                suggestion.status = "accepted"

            self._write_audit(
                admin_user_id=admin_user_id,
                action="policy_change_rollback",
                target_id=str(draft.id),
                detail={
                    "suggestion_id": str(draft.suggestion_id),
                    "reason": reason,
                    "before_config": draft.before_config,
                },
            )
            self.db.session.commit()
        except Exception:
            self.db.session.rollback()
            raise
        return {
            "draft_id": str(draft.id),
            "status": draft.status,
        }

    def list_drafts(self, status: str = "") -> list[dict]:
        query = self.db.session.query(PolicyChangeDraftModel)
        if status:
            query = query.filter(PolicyChangeDraftModel.status == status)
        drafts = query.order_by(PolicyChangeDraftModel.created_at.desc()).all()
        return [self._draft_to_dict(d) for d in drafts]

    def _get_suggestion(self, suggestion_id: UUID) -> RoutingOptimizationSuggestionModel:
        suggestion = (
            self.db.session.query(RoutingOptimizationSuggestionModel)
            .filter_by(id=suggestion_id)
            .one_or_none()
        )
        if suggestion is None:
            raise NotFoundException("调优建议不存在")
        return suggestion

    def _get_draft(self, draft_id: UUID) -> PolicyChangeDraftModel:
        draft = (
            self.db.session.query(PolicyChangeDraftModel)
            .filter_by(id=draft_id)
            .one_or_none()
        )
        if draft is None:
            raise NotFoundException("策略变更草稿不存在")
        return draft

    def _write_audit(
        self,
        admin_user_id: UUID,
        action: str,
        target_id: str,
        detail: dict,
    ) -> None:
        try:
            self.audit_log_service.record(
                admin_user_id=str(admin_user_id),
                action=action,
                resource_type="policy_change_draft",
                resource_id=target_id,
                before_data=detail.get("before_config"),
                after_data=detail.get("after_config") or detail,
            )
        except Exception:
            logger.warning("记录策略变更审计日志失败", exc_info=True)

    def _apply_policy_changes(
        self,
        policy_type: str,
        after_config: dict,
        admin_user_id: UUID,
    ) -> None:
        try:
            if policy_type == "model_routing":
                self._update_feature_flag(
                    "ENABLE_COST_MODEL_ROUTING", True, admin_user_id
                )
            elif policy_type == "tool_policy":
                self._update_feature_flag(
                    "ENABLE_TOOL_POOL_RETRIEVAL", True, admin_user_id
                )
            elif policy_type == "agent_policy":
                self._update_feature_flag(
                    "ENABLE_MULTI_AGENT_EXECUTION", False, admin_user_id
                )
        except Exception:
            logger.warning("应用策略变更到特性开关失败", exc_info=True)

    def _update_feature_flag(
        self,
        code: str,
        enabled: bool,
        admin_user_id: UUID,
    ) -> None:
        flag_service = getattr(self, "orchestration_feature_flag_service", None)
        if flag_service is not None:
            flag_service.update_flag(
                code=code, enabled=enabled, operator_id=admin_user_id
            )
            return
        from internal.model import OrchestrationFeatureFlagModel

        flag = (
            self.db.session.query(OrchestrationFeatureFlagModel)
            .filter(OrchestrationFeatureFlagModel.code == code)
            .first()
        )
        if flag is None:
            return
        flag.enabled = bool(enabled)
        flag.updated_by = admin_user_id

    @staticmethod
    def _build_before_config(suggestion, policy_type: str) -> dict:
        evidence = suggestion.evidence or {}
        if policy_type == "model_routing":
            current_config = {
                "model": suggestion.target_id,
                "tier": evidence.get("current_tier", "default"),
                "avg_cost_credits": evidence.get("avg_cost_credits", 0),
                "avg_rating": evidence.get("avg_rating", 0),
                "sample_count": evidence.get("count", 0),
            }
        elif policy_type == "tool_policy":
            current_config = {
                "tool_pool": suggestion.target_id,
                "risk_level": evidence.get("current_risk_level", "medium"),
                "avg_rating": evidence.get("avg_rating", 0),
                "sample_count": evidence.get("count", 0),
                "enabled": True,
            }
        else:
            current_config = {
                "agent": suggestion.target_id,
                "enabled": True,
                "fallback_rate": evidence.get("fallback_rate", 0),
            }
        return {
            "policy_type": policy_type,
            "target_id": suggestion.target_id,
            "current_config": current_config,
            "evidence": evidence,
        }

    @staticmethod
    def _build_after_config(suggestion, policy_type: str) -> dict:
        evidence = suggestion.evidence or {}
        if policy_type == "model_routing":
            avg_cost = int(evidence.get("avg_cost_credits", 0) or 0)
            proposed_config = {
                "model": suggestion.target_id,
                "tier": "cheap",
                "action": "downgrade_tier",
                "expected_cost_credits": max(avg_cost // 2, 1),
                "reason": "降级到低成本档位以降低开销",
            }
        elif policy_type == "tool_policy":
            avg_rating = evidence.get("avg_rating", 0) or 0
            if avg_rating and avg_rating < 2:
                action = "disable"
                enabled = False
                risk_level = "sensitive"
            else:
                action = "downgrade_risk_level"
                enabled = True
                risk_level = "high"
            proposed_config = {
                "tool_pool": suggestion.target_id,
                "risk_level": risk_level,
                "enabled": enabled,
                "action": action,
                "reason": "工具健康度不达标，建议禁用或降级",
            }
        else:
            proposed_config = {
                "agent": suggestion.target_id,
                "enabled": False,
                "action": "disable",
                "reason": "Agent 故障率过高，建议禁用",
            }
        return {
            "policy_type": policy_type,
            "target_id": suggestion.target_id,
            "proposed_config": proposed_config,
            "suggestion_type": suggestion.suggestion_type,
        }

    @staticmethod
    def _build_diff(before_config: dict, after_config: dict) -> dict:
        changes = []
        for key in set(list(before_config.keys()) + list(after_config.keys())):
            before_val = before_config.get(key)
            after_val = after_config.get(key)
            if before_val != after_val:
                changes.append({
                    "field": key,
                    "before": before_val,
                    "after": after_val,
                })
        return {"changes": changes}

    @staticmethod
    def _build_impact(suggestion, policy_type: str) -> dict:
        return {
            "scope": policy_type,
            "target": suggestion.target_id,
            "affected_entities": [],
            "risk_level": suggestion.severity,
            "description": suggestion.reason,
        }

    @staticmethod
    def _draft_to_dict(draft: PolicyChangeDraftModel) -> dict:
        return {
            "id": str(draft.id),
            "suggestion_id": str(draft.suggestion_id),
            "policy_type": draft.policy_type,
            "target_id": draft.target_id,
            "before_config": draft.before_config or {},
            "after_config": draft.after_config or {},
            "diff": draft.diff or {},
            "impact": draft.impact or {},
            "status": draft.status,
            "applied_by": str(draft.applied_by) if draft.applied_by else None,
            "applied_at": draft.applied_at.isoformat() if draft.applied_at else None,
            "rolled_back_at": draft.rolled_back_at.isoformat() if draft.rolled_back_at else None,
            "rollback_reason": draft.rollback_reason or "",
        }
