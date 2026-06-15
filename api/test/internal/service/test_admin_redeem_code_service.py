from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from internal.exception import FailException, NotFoundException
from internal.model.billing import Plan, RedeemCode, RedeemCodeBatch
from internal.service.admin_redeem_code_service import AdminRedeemCodeService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None, all_result=None, count_result=None):
        self._one_or_none_result = one_or_none_result
        self._all_result = [] if all_result is None else all_result
        self._count_result = len(self._all_result) if count_result is None else count_result
        self.filters = []
        self.order_by_args = []
        self.offset_value = None
        self.limit_value = None

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
        "duration_days": 30,
        "grant_token_credits": 100000,
        "status": "active",
    }
    defaults.update(kwargs)
    return Plan(**defaults)


def _batch(**kwargs):
    defaults = {
        "id": uuid4(),
        "name": "Batch",
        "plan_id": uuid4(),
        "quantity": 2,
        "expires_at": datetime(2030, 1, 1, 0, 0, 0),
        "created_by": uuid4(),
        "created_at": datetime(2029, 1, 1, 0, 0, 0),
    }
    defaults.update(kwargs)
    return RedeemCodeBatch(**defaults)


def _code(**kwargs):
    defaults = {
        "id": uuid4(),
        "batch_id": uuid4(),
        "plan_id": uuid4(),
        "code_hash": "sha256:hash",
        "code_mask": "ABCD****WXYZ",
        "status": "unused",
        "redeemed_by": None,
        "redeemed_at": None,
        "expires_at": datetime(2030, 1, 1, 0, 0, 0),
        "disabled_at": None,
        "created_at": datetime(2029, 1, 1, 0, 0, 0),
    }
    defaults.update(kwargs)
    return RedeemCode(**defaults)


class TestAdminRedeemCodeService:
    def test_generate_codes_should_store_hash_and_mask_and_return_plain_codes_once(self):
        operator_id = uuid4()
        plan = _plan()
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([_QueryStub(one_or_none_result=plan)])
        service = AdminRedeemCodeService(session=session, audit_log_service=audit_log_service)

        result = service.generate_codes(
            {
                "name": "Pro Batch",
                "plan_id": plan.id,
                "quantity": 2,
                "expires_at": datetime(2030, 1, 1, 0, 0, 0),
            },
            operator_id=operator_id,
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["batch"]["name"] == "Pro Batch"
        assert len(result["codes"]) == 2
        assert all(code["plain_code"].startswith("OA-") for code in result["codes"])
        assert len(session.added) == 3
        stored_codes = [item for item in session.added if isinstance(item, RedeemCode)]
        assert all(stored_code.code_hash.startswith("sha256:") for stored_code in stored_codes)
        assert all(not hasattr(stored_code, "plain_code") for stored_code in stored_codes)
        assert all("****" in stored_code.code_mask for stored_code in stored_codes)
        assert session.commits == 1
        assert audit_log_service.records[0]["action"] == "generate"
        assert audit_log_service.records[0]["resource_type"] == "redeem_code_batch"

    def test_generate_codes_should_reject_inactive_plan(self):
        plan = _plan(status="disabled")
        service = AdminRedeemCodeService(session=_SessionStub([_QueryStub(one_or_none_result=plan)]))

        with pytest.raises(FailException):
            service.generate_codes({"name": "Batch", "plan_id": plan.id, "quantity": 1})

    def test_list_batches_should_return_paginated_batches(self):
        batch = _batch(name="Pro Batch")
        query = _QueryStub(all_result=[batch], count_result=1)
        service = AdminRedeemCodeService(session=_SessionStub([query]))

        result = service.list_batches(keyword="Pro", current_page=2, page_size=10)

        assert query.offset_value == 10
        assert query.limit_value == 10
        assert len(query.filters) == 1
        assert result["list"][0]["name"] == "Pro Batch"
        assert result["paginator"] == {"total_record": 1, "total_page": 1, "current_page": 2, "page_size": 10}

    def test_list_codes_should_return_masked_codes_only(self):
        redeem_code = _code(code_hash="sha256:secret", code_mask="OA12****7890")
        query = _QueryStub(all_result=[redeem_code], count_result=1)
        service = AdminRedeemCodeService(session=_SessionStub([query]))

        result = service.list_codes(batch_id=redeem_code.batch_id, status="unused", current_page=1, page_size=20)

        assert result["list"][0]["code_mask"] == "OA12****7890"
        assert "plain_code" not in result["list"][0]
        assert "code_hash" not in result["list"][0]

    def test_list_codes_should_filter_by_code_keyword(self):
        redeem_code = _code(code_mask="OA12****7890")
        query = _QueryStub(all_result=[redeem_code], count_result=1)
        service = AdminRedeemCodeService(session=_SessionStub([query]))

        result = service.list_codes(code_keyword="7890", current_page=1, page_size=20)

        assert len(query.filters) == 1
        assert result["list"][0]["code_mask"] == "OA12****7890"

    def test_list_codes_should_treat_expired_codes_as_expired_status(self):
        redeem_code = _code(status="unused", expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1))
        query = _QueryStub(all_result=[redeem_code], count_result=1)
        service = AdminRedeemCodeService(session=_SessionStub([query]))

        result = service.list_codes(status="expired", current_page=1, page_size=20)

        assert len(query.filters) == 1
        assert result["list"][0]["status"] == "expired"

    def test_disable_code_should_update_status_and_record_audit(self):
        operator_id = uuid4()
        redeem_code = _code(status="unused")
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([_QueryStub(one_or_none_result=redeem_code)])
        service = AdminRedeemCodeService(session=session, audit_log_service=audit_log_service)

        result = service.disable_code(redeem_code.id, operator_id=operator_id, ip="127.0.0.1", user_agent="pytest")

        assert result["status"] == "disabled"
        assert redeem_code.status == "disabled"
        assert redeem_code.disabled_at is not None
        assert session.commits == 1
        assert audit_log_service.records[0]["action"] == "disable"
        assert audit_log_service.records[0]["before_data"] == {"status": "unused"}
        assert audit_log_service.records[0]["after_data"] == {"status": "disabled"}

    def test_disable_code_should_raise_not_found_when_missing(self):
        service = AdminRedeemCodeService(session=_SessionStub([_QueryStub(one_or_none_result=None)]))

        with pytest.raises(NotFoundException):
            service.disable_code(uuid4())

    def test_disable_batch_should_update_status_and_record_audit(self):
        operator_id = uuid4()
        batch = _batch(status="active")
        audit_log_service = _AuditLogServiceStub()
        session = _SessionStub([_QueryStub(one_or_none_result=batch)])
        service = AdminRedeemCodeService(session=session, audit_log_service=audit_log_service)

        result = service.disable_batch(batch.id, operator_id=operator_id, ip="127.0.0.1", user_agent="pytest")

        assert result["status"] == "disabled"
        assert batch.status == "disabled"
        assert batch.disabled_at is not None
        assert session.commits == 1
        assert audit_log_service.records[0]["action"] == "disable"
        assert audit_log_service.records[0]["resource_type"] == "redeem_code_batch"
        assert audit_log_service.records[0]["before_data"] == {"status": "active"}
        assert audit_log_service.records[0]["after_data"] == {"status": "disabled"}

    def test_disable_batch_should_raise_not_found_when_missing(self):
        service = AdminRedeemCodeService(session=_SessionStub([_QueryStub(one_or_none_result=None)]))

        with pytest.raises(NotFoundException):
            service.disable_batch(uuid4())
