from dataclasses import dataclass
from uuid import UUID

from flask import g, request
from injector import inject

from internal.middleware import admin_login_required, permission_required
from internal.schema.admin_routing_quality_schema import (
    DismissSuggestionReq,
    PolicyChangeDraftResp,
    PolicyChangeListResp,
    PolicyChangePreviewResp,
    RollbackPolicyChangeReq,
    RoutingOptimizationSuggestionResp,
    SuggestionActionResp,
    RoutingQualityFeedbackResp,
    RoutingQualityMetricsResp,
)
from internal.service.routing_optimization_suggestion_service import (
    RoutingOptimizationSuggestionService,
)
from internal.service.routing_policy_change_service import (
    RoutingPolicyChangeService,
)
from internal.service.routing_quality_feedback_service import (
    RoutingQualityFeedbackService,
)
from internal.service.routing_quality_metrics_service import (
    RoutingQualityMetricsService,
)
from pkg.response import fail_message, success_json, validate_error_json


@inject
@dataclass
class AdminRoutingQualityHandler:
    routing_quality_feedback_service: RoutingQualityFeedbackService
    routing_quality_metrics_service: RoutingQualityMetricsService
    routing_optimization_suggestion_service: RoutingOptimizationSuggestionService
    routing_policy_change_service: RoutingPolicyChangeService

    @admin_login_required
    @permission_required("routing_quality:feedback")
    def create_feedback(self):
        data = request.get_json(silent=True) or {}
        required_fields = ["routing_log_id", "rating"]
        if any(field not in data for field in required_fields):
            return validate_error_json({"routing_log_id": ["Missing required data"]})
        current_admin = getattr(g, "current_admin_user", {}) or {}
        try:
            result = self.routing_quality_feedback_service.create_feedback(
                routing_log_id=UUID(data["routing_log_id"]),
                source="admin",
                rating=int(data["rating"]),
                dimension_scores=data.get("dimension_scores") or {},
                comment=data.get("comment") or "",
                metadata=data.get("metadata") or {},
                created_by=UUID(current_admin.get("id")),
            )
        except (TypeError, ValueError) as exc:
            return fail_message(str(exc))
        return success_json(RoutingQualityFeedbackResp().dump(result))

    @admin_login_required
    @permission_required("routing_quality:read")
    def list_feedback(self):
        routing_log_id = request.args.get("routing_log_id")
        result = self.routing_quality_feedback_service.list_feedback(
            routing_log_id=UUID(routing_log_id) if routing_log_id else None,
            source=request.args.get("source"),
            page=int(request.args.get("page", 1)),
            page_size=int(request.args.get("page_size", 20)),
        )
        return success_json(RoutingQualityFeedbackResp(many=True).dump(result))

    @admin_login_required
    @permission_required("routing_quality:read")
    def metrics(self):
        metrics = self.routing_quality_metrics_service.build_metrics()
        return success_json(RoutingQualityMetricsResp().dump(metrics))

    @admin_login_required
    @permission_required("routing_quality:read")
    def suggestions(self):
        status = request.args.get("status", "")
        if status:
            suggestions = self.routing_optimization_suggestion_service.list_suggestions(
                status=status
            )
        else:
            metrics = self.routing_quality_metrics_service.build_metrics()
            suggestions = self.routing_optimization_suggestion_service.generate_suggestions(
                metrics
            )
        return success_json(
            RoutingOptimizationSuggestionResp(many=True).dump(suggestions)
        )

    @admin_login_required
    @permission_required("routing_quality:accept")
    def accept_suggestion(self, suggestion_id: UUID):
        current_admin = getattr(g, "current_admin_user", {}) or {}
        try:
            result = self.routing_optimization_suggestion_service.accept_suggestion(
                suggestion_id,
                UUID(current_admin.get("id")) if current_admin.get("id") else None,
            )
        except (ValueError, Exception) as exc:
            return fail_message(str(exc))
        return success_json(SuggestionActionResp().dump(result))

    @admin_login_required
    @permission_required("routing_quality:dismiss")
    def dismiss_suggestion(self, suggestion_id: UUID):
        req = DismissSuggestionReq(request.form)
        if not req.validate():
            return validate_error_json(req.errors)
        current_admin = getattr(g, "current_admin_user", {}) or {}
        reason = request.get_json(silent=True) or {}
        try:
            result = self.routing_optimization_suggestion_service.dismiss_suggestion(
                suggestion_id,
                UUID(current_admin.get("id")) if current_admin.get("id") else None,
                reason.get("reason", ""),
            )
        except (ValueError, Exception) as exc:
            return fail_message(str(exc))
        return success_json(SuggestionActionResp().dump(result))

    @admin_login_required
    @permission_required("routing_quality:read")
    def preview_policy_change(self, suggestion_id: UUID):
        try:
            preview = self.routing_policy_change_service.generate_preview(
                suggestion_id
            )
        except (ValueError, Exception) as exc:
            return fail_message(str(exc))
        return success_json(PolicyChangePreviewResp().dump(preview))

    @admin_login_required
    @permission_required("routing_quality:apply")
    def apply_policy_change(self, suggestion_id: UUID):
        data = request.get_json(silent=True) or {}
        current_admin = getattr(g, "current_admin_user", {}) or {}
        try:
            result = self.routing_policy_change_service.apply_draft(
                suggestion_id,
                UUID(current_admin.get("id")) if current_admin.get("id") else None,
                data,
            )
        except (ValueError, Exception) as exc:
            return fail_message(str(exc))
        return success_json(result)

    @admin_login_required
    @permission_required("routing_quality:rollback")
    def rollback_policy_change(self, draft_id: UUID):
        data = request.get_json(silent=True) or {}
        current_admin = getattr(g, "current_admin_user", {}) or {}
        try:
            result = self.routing_policy_change_service.rollback_draft(
                draft_id,
                UUID(current_admin.get("id")) if current_admin.get("id") else None,
                data.get("reason", ""),
            )
        except (ValueError, Exception) as exc:
            return fail_message(str(exc))
        return success_json(result)

    @admin_login_required
    @permission_required("routing_quality:read")
    def list_policy_changes(self):
        status = request.args.get("status", "")
        drafts = self.routing_policy_change_service.list_drafts(status=status)
        return success_json(
            PolicyChangeListResp().dump(
                {"items": drafts, "total": len(drafts)}
            )
        )
