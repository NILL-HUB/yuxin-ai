from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from internal.entity.orchestration_feature_flag_entity import (
    ORCHESTRATION_FEATURE_FLAG_CODES,
)
from internal.model.orchestration_feature_flag import (
    OrchestrationFeatureFlagModel,
)
from internal.service.orchestration_feature_flag_service import (
    OrchestrationFeatureFlagService,
)


class _QueryStub:
    def __init__(self, *, first_result=None, all_result=None):
        self._first_result = first_result
        self._all_result = [] if all_result is None else all_result

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._first_result

    def all(self):
        return self._all_result


class _SessionStub:
    def __init__(self, queries=None):
        self._queries = list(queries or [])

    def query(self, *_args, **_kwargs):
        if self._queries:
            return self._queries.pop(0)
        return _QueryStub()

    def add(self, _value):
        return None


@contextmanager
def _auto_commit():
    yield


def _fake_db(session):
    return SimpleNamespace(session=session, auto_commit=lambda: _auto_commit())


def _flag(code="ENABLE_ORCHESTRATOR", enabled=True):
    return SimpleNamespace(
        code=code,
        name="flag",
        description="desc",
        enabled=enabled,
        risk_level="medium",
        fallback_behavior="direct_answer",
        updated_by=None,
    )


def test_ensure_defaults_should_create_missing_flags_idempotently(monkeypatch):
    service = OrchestrationFeatureFlagService(db=_fake_db(_SessionStub()))
    created = []
    monkeypatch.setattr(
        service,
        "create",
        lambda model, **kwargs: created.append((model, kwargs))
        or SimpleNamespace(**kwargs),
    )

    service.ensure_defaults()

    assert len(created) == len(ORCHESTRATION_FEATURE_FLAG_CODES)
    assert created[0][0] is OrchestrationFeatureFlagModel
    assert created[0][1]["code"] == "ENABLE_ORCHESTRATOR"


def test_ensure_defaults_should_update_metadata_without_overriding_enabled():
    flag = SimpleNamespace(
        code="ENABLE_ORCHESTRATOR",
        name="Old name",
        description="Old description",
        enabled=False,
        risk_level="old",
        fallback_behavior="old",
        updated_by=None,
    )
    service = OrchestrationFeatureFlagService(
        db=_fake_db(_SessionStub([_QueryStub(first_result=flag)])),
    )

    service.ensure_defaults()

    assert flag.name == "Orchestrator"
    assert flag.description == "Enable orchestration router for assistant intent handling"
    assert flag.enabled is False
    assert flag.risk_level == "medium"
    assert flag.fallback_behavior == "direct_answer"


def test_list_flags_should_return_known_flags():
    service = OrchestrationFeatureFlagService(
        db=_fake_db(_SessionStub([_QueryStub(all_result=[_flag()])]))
    )

    codes = {flag["code"] for flag in service.list_flags()}
    assert "ENABLE_ORCHESTRATOR" in codes


def test_list_flags_should_backfill_conductor_and_other_missing_codes():
    service = OrchestrationFeatureFlagService(db=_fake_db(_SessionStub()))

    flags = service.list_flags()

    codes = {flag["code"] for flag in flags}
    assert "ENABLE_CONDUCTOR" in codes
    assert len(codes) == len(ORCHESTRATION_FEATURE_FLAG_CODES)


def test_is_enabled_should_return_false_for_unknown_code():
    service = OrchestrationFeatureFlagService(db=_fake_db(_SessionStub()))

    assert service.is_enabled("UNKNOWN_FLAG") is False


def test_update_flag_should_update_flag_and_operator():
    operator_id = uuid4()
    flag = _flag(enabled=False)
    service = OrchestrationFeatureFlagService(
        db=_fake_db(_SessionStub([_QueryStub(first_result=flag)]))
    )

    result = service.update_flag(
        code="ENABLE_ORCHESTRATOR",
        enabled=True,
        operator_id=operator_id,
    )

    assert flag.enabled is True
    assert flag.updated_by == operator_id
    assert result["enabled"] is True
