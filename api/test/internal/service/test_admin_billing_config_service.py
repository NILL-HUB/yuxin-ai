from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import FailException
from internal.model.billing import BillingConfig
from internal.schema.admin_billing_config_schema import BILLING_CONFIG_CREDITS_PER_YUAN
from internal.service.admin_billing_config_service import AdminBillingConfigService


class _QueryStub:
    def __init__(self, *, one_or_none_result=None):
        self._one_or_none_result = one_or_none_result

    def filter(self, *args, **kwargs):
        return self

    def one_or_none(self):
        return self._one_or_none_result


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])
        self.added = []
        self.commits = 0

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1


class _AuditLogServiceStub:
    def __init__(self):
        self.records = []

    def record_for_write(self, **kwargs):
        self.records.append(kwargs)


def _config(value=1, description="每 1000 token 消耗的算力值"):
    return BillingConfig(code="credits_per_1k_tokens", value_numeric=value, description=description)


class TestAdminBillingConfigService:
    def test_get_config_should_return_default_when_missing(self):
        service = AdminBillingConfigService(session=_SessionStub([_QueryStub(one_or_none_result=None)]))

        result = service.get_config()

        assert result["code"] == "credits_per_1k_tokens"
        assert result["value_numeric"] == 1

    def test_get_config_should_return_stored_value(self):
        service = AdminBillingConfigService(session=_SessionStub([_QueryStub(one_or_none_result=_config(2))]))

        result = service.get_config()

        assert result["value_numeric"] == 2

    def test_get_credits_per_yuan_default_when_missing(self):
        service = AdminBillingConfigService(session=_SessionStub([_QueryStub(one_or_none_result=None)]))

        result = service.get_config(BILLING_CONFIG_CREDITS_PER_YUAN)

        assert result["code"] == BILLING_CONFIG_CREDITS_PER_YUAN
        assert result["value_numeric"] == 100

    def test_upsert_should_create_when_missing(self):
        audit = _AuditLogServiceStub()
        session = _SessionStub([_QueryStub(one_or_none_result=None)])
        service = AdminBillingConfigService(session=session, audit_log_service=audit)

        result = service.upsert_config(
            {"value_numeric": "3", "description": "上调汇率"},
            operator_id=uuid4(),
            ip="127.0.0.1",
            user_agent="pytest",
        )

        assert result["value_numeric"] == 3
        assert session.added[0].value_numeric == 3
        assert audit.records[0]["action"] == "upsert"

    def test_upsert_should_update_when_exists(self):
        existing = _config(1)
        audit = _AuditLogServiceStub()
        session = _SessionStub([_QueryStub(one_or_none_result=existing)])
        service = AdminBillingConfigService(session=session, audit_log_service=audit)

        result = service.upsert_config({"value_numeric": "2", "description": "下调汇率"})

        assert existing.value_numeric == 2
        assert existing.description == "下调汇率"
        assert result["value_numeric"] == 2
        assert audit.records[0]["before_data"]["value_numeric"] == 1
        assert audit.records[0]["after_data"]["value_numeric"] == 2

    def test_upsert_should_reject_invalid_value(self):
        service = AdminBillingConfigService(session=_SessionStub())

        with pytest.raises(FailException):
            service.upsert_config({"value_numeric": "0"})

    @pytest.mark.parametrize("raw", ["", "abc", "-3", "1000001"])
    def test_upsert_should_reject_bad_inputs(self, raw):
        service = AdminBillingConfigService(session=_SessionStub())

        with pytest.raises(FailException):
            service.upsert_config({"value_numeric": raw})