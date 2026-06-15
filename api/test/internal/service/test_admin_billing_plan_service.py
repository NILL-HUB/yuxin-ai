from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from internal.exception import NotFoundException
from internal.model.billing import Plan, PlanEntitlement
from internal.service.admin_billing_plan_service import AdminBillingPlanService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None, count_result=None):
        self._one_or_none_result = one_or_none_result
        self._all_result = [] if all_result is None else all_result
        self._count_result = len(self._all_result) if count_result is None else count_result
        self.filters = []
        self.order_by_args = []
        self.offset_value = None
        self.limit_value = None
        self.deleted = 0

    def filter(self, *args, **kwargs):
        self.filters.append((args, kwargs))
        return self

    def order_by(self, *args):
        self.order_by_args.append(args)
        return self

    def offset(self, value):
        self.offset_value = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def count(self):
        return self._count_result

    def one_or_none(self):
        return self._one_or_none_result

    def all(self):
        return self._all_result

    def delete(self):
        self.deleted += 1
        return self.deleted


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])
        self.added = []
        self.commits = 0
        self.flushes = 0

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def flush(self):
        self.flushes += 1


class _AuditLogServiceStub:
    def __init__(self):
        self.records = []

    def record_for_write(self, **kwargs):
        self.records.append(kwargs)


def _plan(**kwargs):
    defaults = {
        "id": uuid4(),
        "code": "pro",
        "name": "Pro",
        "description": "Pro plan",
        "duration_days": 30,
        "grant_token_credits": 100000,
        "price": Decimal("99.00"),
        "status": "active",
        "sort_order": 10,
        "created_at": datetime(2030, 1, 1, 0, 0, 0),
        "updated_at": datetime(2030, 1, 2, 0, 0, 0),
    }
    defaults.update(kwargs)
    return Plan(**defaults)


def _entitlement(**kwargs):
    defaults = {
        "id": uuid4(),
        "plan_id": uuid4(),
        "feature_key": "max_agents",
        "feature_value": "10",
        "value_type": "number",
        "created_at": datetime(2030, 1, 1, 0, 0, 0),
        "updated_at": datetime(2030, 1, 2, 0, 0, 0),
    }
    defaults.update(kwargs)
    return PlanEntitlement(**defaults)


class TestAdminBillingPlanService:
    def test_list_plans_should_return_paginated_serialized_plans(self):
        plan = _plan()
        query = _QueryStub(all_result=[plan], count_result=1)
        service = AdminBillingPlanService(session=_SessionStub([query]))

        result = service.list_plans(keyword="pro", status="active", current_page=2, page_size=10)

        assert query.offset_value == 10
        assert query.limit_value == 10
        assert len(query.filters) == 2
        assert result["list"][0]["code"] == "pro"
        assert result["list"][0]["grant_token_credits"] == 100000
        assert result["list"][0]["price"] == "99.00"
        assert result["paginator"] == {"total_record": 1, "total_page": 1, "current_page": 2, "page_size": 10}

    def test_get_plan_should_include_entitlements(self):
        plan = _plan()
        entitlement = _entitlement(plan_id=plan.id)
        service = AdminBillingPlanService(session=_SessionStub([
            _QueryStub(one_or_none_result=plan),
            _QueryStub(all_result=[entitlement]),
        ]))

        result = service.get_plan(plan.id)

        assert result["id"] == str(plan.id)
        assert result["entitlements"] == [{
            "id": str(entitlement.id),
            "feature_key": "max_agents",
            "feature_value": "10",
            "value_type": "number",
            "parsed_value": 10,
        }]

    def test_create_plan_should_create_plan_entitlements_and_record_audit(self):
        operator_id = uuid4()
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub()
        service = AdminBillingPlanService(session=session, audit_log_service=audit_log_service)

        result = service.create_plan(
            {
                "code": "team",
                "name": "Team",
                "description": "Team plan",
                "duration_days": 90,
                "grant_token_credits": 300000,
                "price": "199.00",
                "status": "active",
                "sort_order": 20,
                "entitlements": [
                    {"feature_key": "max_agents", "feature_value": "20", "value_type": "number"},
                    {"feature_key": "allow_mcp_tools", "feature_value": "true", "value_type": "boolean"},
                ],
            },
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["code"] == "team"
        assert len(session.added) == 3
        assert isinstance(session.added[0], Plan)
        assert isinstance(session.added[1], PlanEntitlement)
        assert session.commits == 1
        assert audit_log_service.records[0]["action"] == "create"
        assert audit_log_service.records[0]["resource_type"] == "plan"

    def test_update_plan_should_replace_entitlements_and_record_audit(self):
        operator_id = uuid4()
        plan = _plan(status="active")
        entitlements_query = _QueryStub()
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([_QueryStub(one_or_none_result=plan), entitlements_query])
        service = AdminBillingPlanService(session=session, audit_log_service=audit_log_service)

        result = service.update_plan(
            plan.id,
            {
                "name": "Pro Plus",
                "description": "Plus",
                "duration_days": 60,
                "grant_token_credits": 200000,
                "price": "149.00",
                "status": "disabled",
                "sort_order": 30,
                "entitlements": [{"feature_key": "max_agents", "feature_value": "30", "value_type": "number"}],
            },
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["name"] == "Pro Plus"
        assert plan.duration_days == 60
        assert plan.grant_token_credits == 200000
        assert entitlements_query.deleted == 1
        assert len(session.added) == 1
        assert session.commits == 1
        assert audit_log_service.records[0]["action"] == "update"

    def test_set_plan_status_should_update_status_and_record_audit(self):
        operator_id = uuid4()
        plan = _plan(status="active")
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([_QueryStub(one_or_none_result=plan)])
        service = AdminBillingPlanService(session=session, audit_log_service=audit_log_service)

        result = service.set_plan_status(plan.id, "disabled", operator_id=operator_id, ip="127.0.0.1", user_agent="pytest")

        assert result["status"] == "disabled"
        assert plan.status == "disabled"
        assert session.commits == 1
        assert audit_log_service.records[0]["before_data"] == {"status": "active"}
        assert audit_log_service.records[0]["after_data"] == {"status": "disabled"}

    def test_get_plan_should_raise_not_found_when_missing(self):
        service = AdminBillingPlanService(session=_SessionStub([_QueryStub(one_or_none_result=None)]))

        with pytest.raises(NotFoundException):
            service.get_plan(uuid4())
