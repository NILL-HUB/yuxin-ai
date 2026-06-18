from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from internal.service.routing_log_retention_service import (
    DEFAULT_ROUTING_LOG_RETENTION_DAYS,
    ROUTING_LOG_RETENTION_FLAG_CODE,
    RoutingLogRetentionService,
)


class TestRoutingLogRetentionService:
    @pytest.fixture
    def service(self):
        return RoutingLogRetentionService(db=MagicMock())

    def test_get_retention_days_returns_default_when_no_flag(self, service):
        service.db.session.query.return_value.filter.return_value.first.return_value = None

        assert service.get_retention_days() == DEFAULT_ROUTING_LOG_RETENTION_DAYS

    def test_get_retention_days_reads_value_from_flag(self, service):
        flag = Mock()
        flag.fallback_behavior = "45"
        service.db.session.query.return_value.filter.return_value.first.return_value = flag

        assert service.get_retention_days() == 45

    def test_get_retention_days_falls_back_on_invalid_value(self, service):
        flag = Mock()
        flag.fallback_behavior = "not-a-number"
        service.db.session.query.return_value.filter.return_value.first.return_value = flag

        assert service.get_retention_days() == DEFAULT_ROUTING_LOG_RETENTION_DAYS

    def test_set_retention_days_creates_flag_when_missing(self, service):
        service.db.session.query.return_value.filter.return_value.first.return_value = None
        admin_id = uuid4()

        days = service.set_retention_days(60, admin_id)

        assert days == 60
        service.db.session.add.assert_called_once()
        added = service.db.session.add.call_args[0][0]
        assert added.code == ROUTING_LOG_RETENTION_FLAG_CODE
        assert added.fallback_behavior == "60"
        assert added.enabled is True

    def test_set_retention_days_updates_existing_flag(self, service):
        flag = Mock()
        flag.fallback_behavior = "30"
        service.db.session.query.return_value.filter.return_value.first.return_value = flag
        admin_id = uuid4()

        days = service.set_retention_days(90, admin_id)

        assert days == 90
        assert flag.fallback_behavior == "90"
        assert flag.enabled is True
        assert flag.updated_by == admin_id
        service.db.session.add.assert_not_called()

    def test_set_retention_days_rejects_zero(self, service):
        with pytest.raises(ValueError):
            service.set_retention_days(0, uuid4())

    def test_set_retention_days_rejects_out_of_range(self, service):
        with pytest.raises(ValueError):
            service.set_retention_days(5000, uuid4())

    def test_set_retention_days_rejects_non_integer(self, service):
        with pytest.raises(ValueError):
            service.set_retention_days("abc", uuid4())

    def test_describe_returns_metadata(self, service):
        service.db.session.query.return_value.filter.return_value.first.return_value = None

        desc = service.describe()

        assert desc["retention_days"] == DEFAULT_ROUTING_LOG_RETENTION_DAYS
        assert desc["default_retention_days"] == DEFAULT_ROUTING_LOG_RETENTION_DAYS
        assert desc["code"] == ROUTING_LOG_RETENTION_FLAG_CODE
