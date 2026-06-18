import json
from types import SimpleNamespace
from uuid import uuid4

from internal.entity.policy_change_entity import POLICY_CHANGE_DRAFT_STATUSES, POLICY_CHANGE_TYPES
from internal.service.routing_policy_change_service import RoutingPolicyChangeService


class TestPolicyChangeEntity:
    def test_status_enum_should_include_applied_and_rolled_back(self):
        assert "pending" in POLICY_CHANGE_DRAFT_STATUSES
        assert "applied" in POLICY_CHANGE_DRAFT_STATUSES
        assert "rolled_back" in POLICY_CHANGE_DRAFT_STATUSES

    def test_policy_type_enum_should_include_all_types(self):
        assert "model_routing" in POLICY_CHANGE_TYPES
        assert "tool_policy" in POLICY_CHANGE_TYPES
        assert "agent_policy" in POLICY_CHANGE_TYPES

    def test_suggestion_status_should_include_applied(self):
        from internal.entity.routing_quality_entity import ROUTING_OPTIMIZATION_SUGGESTION_STATUSES
        assert "applied" in ROUTING_OPTIMIZATION_SUGGESTION_STATUSES
        assert "open" in ROUTING_OPTIMIZATION_SUGGESTION_STATUSES
        assert "accepted" in ROUTING_OPTIMIZATION_SUGGESTION_STATUSES
        assert "dismissed" in ROUTING_OPTIMIZATION_SUGGESTION_STATUSES


class TestRoutingPolicyChangeService:
    def _make_service(self, suggestion=None, draft=None):
        service = RoutingPolicyChangeService.__new__(RoutingPolicyChangeService)
        service._audit_log_service = SimpleNamespace(record=lambda **kwargs: None)

        class _QueryStub:
            def __init__(self, result):
                self._result = result
                self._filter_result = result

            def filter_by(self, **kwargs):
                if kwargs.get("id") is not None:
                    return self
                return _QueryStub(None)

            def filter(self, *args, **kwargs):
                return self

            def order_by(self, *args, **kwargs):
                return self

            def one_or_none(self):
                return self._filter_result

            def all(self):
                return [self._result] if self._result else []

        class _SessionStub:
            def __init__(self, suggestion, draft):
                self._suggestion = suggestion
                self._draft = draft
                self._added = []

            def query(self, model):
                if model.__name__ == "RoutingOptimizationSuggestionModel":
                    return _QueryStub(self._suggestion)
                return _QueryStub(self._draft)

            def add(self, obj):
                obj.id = uuid4()
                self._added.append(obj)

            def flush(self):
                pass

            def commit(self):
                pass

            def rollback(self):
                pass

        class _DbStub:
            session = _SessionStub(suggestion, draft)

        service.db = _DbStub()
        return service

    def _make_suggestion(self, **overrides):
        defaults = {
            "id": uuid4(),
            "target_type": "model",
            "target_id": "gpt-4",
            "suggestion_type": "review_model_cost",
            "severity": "high",
            "reason": "Model has high cost with low quality rating",
            "evidence": {"avg_rating": 2.5, "avg_cost_credits": 10},
            "status": "accepted",
            "dismiss_reason": "",
            "applied_by": None,
            "applied_at": None,
            "policy_change_draft_id": None,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_generate_preview_should_return_draft_dict(self):
        suggestion = self._make_suggestion()
        service = self._make_service(suggestion=suggestion)

        preview = service.generate_preview(suggestion.id)

        assert preview["policy_type"] == "model_routing"
        assert preview["target_id"] == "gpt-4"
        assert "before_config" in preview
        assert "after_config" in preview
        assert "diff" in preview
        assert "impact" in preview
        assert preview["status"] == "pending"
        assert preview["impact"]["risk_level"] == "high"

    def test_generate_preview_should_map_tool_health_to_tool_policy(self):
        suggestion = self._make_suggestion(
            suggestion_type="review_tool_health",
            target_type="tool_pool",
            target_id="web_search",
        )
        service = self._make_service(suggestion=suggestion)

        preview = service.generate_preview(suggestion.id)

        assert preview["policy_type"] == "tool_policy"

    def test_apply_draft_should_update_suggestion_to_applied(self):
        suggestion = self._make_suggestion(status="accepted")
        service = self._make_service(suggestion=suggestion)

        preview_data = {
            "policy_type": "model_routing",
            "target_id": "gpt-4",
            "before_config": {"enabled": True},
            "after_config": {"enabled": False},
            "diff": {"changes": [{"field": "enabled", "before": True, "after": False}]},
            "impact": {"risk_level": "high"},
        }

        result = service.apply_draft(suggestion.id, uuid4(), preview_data)

        assert result["status"] == "applied"
        assert result["suggestion_status"] == "applied"
        assert suggestion.status == "applied"
        assert suggestion.applied_by is not None
        assert suggestion.policy_change_draft_id is not None

    def test_apply_draft_should_reject_non_accepted_suggestion(self):
        suggestion = self._make_suggestion(status="open")
        service = self._make_service(suggestion=suggestion)

        try:
            service.apply_draft(suggestion.id, uuid4(), {})
            assert False, "应抛出 ValueError"
        except ValueError as e:
            assert "需先采纳后才能应用" in str(e)

    def test_apply_draft_should_rollback_on_exception(self):
        suggestion = self._make_suggestion(status="accepted")
        service = self._make_service(suggestion=suggestion)

        class _FailingSession:
            def __init__(self):
                self.rolled_back = False

            def query(self, model):
                class _Q:
                    def filter_by(self, **kw):
                        return self

                    def one_or_none(self):
                        return suggestion

                return _Q()

            def add(self, obj):
                obj.id = uuid4()

            def flush(self):
                pass

            def commit(self):
                raise Exception("commit failed")

            def rollback(self):
                self.rolled_back = True

        class _FailingDb:
            session = _FailingSession()

        service.db = _FailingDb()

        try:
            service.apply_draft(suggestion.id, uuid4(), {})
            assert False, "应抛出异常"
        except Exception:
            pass

        assert service.db.session.rolled_back is True

    def test_rollback_draft_should_restore_status(self):
        draft = SimpleNamespace(
            id=uuid4(),
            suggestion_id=uuid4(),
            policy_type="model_routing",
            target_id="gpt-4",
            before_config={"enabled": True},
            after_config={"enabled": False},
            diff={},
            impact={},
            status="applied",
            applied_by=uuid4(),
            applied_at=None,
            rolled_back_at=None,
            rollback_reason="",
        )
        suggestion = self._make_suggestion(status="applied")
        service = self._make_service(suggestion=suggestion, draft=draft)

        result = service.rollback_draft(draft.id, uuid4(), reason="配置回滚")

        assert result["status"] == "rolled_back"
        assert draft.status == "rolled_back"
        assert draft.rollback_reason == "配置回滚"
        assert suggestion.status == "accepted"

    def test_rollback_draft_should_reject_non_applied(self):
        draft = SimpleNamespace(
            id=uuid4(),
            suggestion_id=uuid4(),
            status="pending",
            rolled_back_at=None,
            rollback_reason="",
        )
        service = self._make_service(draft=draft)

        try:
            service.rollback_draft(draft.id, uuid4())
            assert False, "应抛出 ValueError"
        except ValueError as e:
            assert "仅 applied 状态可回滚" in str(e)
