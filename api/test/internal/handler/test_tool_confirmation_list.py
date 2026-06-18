from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from pkg.response import HttpCode

_SERVICE_PATH = "internal.service.tool_confirmation_service.ToolConfirmationService"


def _mock_current_user(monkeypatch, account_id=None):
    account_id = account_id or uuid4()
    fake_user = SimpleNamespace(id=account_id, is_authenticated=True, is_active=True)
    monkeypatch.setattr("flask_login.current_user", fake_user, raising=False)
    return account_id


def _make_confirmation(**overrides):
    defaults = {
        "id": uuid4(),
        "tool_name": "send_email",
        "risk_level": "high",
        "tool_input": {"to": "user@example.com"},
        "status": "pending",
        "spent_credits": 5,
        "reason": "发送邮件给客户",
        "created_at": datetime(2025, 1, 1),
        "updated_at": datetime(2025, 1, 1),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestToolConfirmationListHandler:
    def test_list_should_return_current_user_confirmations(self, client, monkeypatch):
        account_id = _mock_current_user(monkeypatch)
        confirmation = _make_confirmation()

        def _list_confirmations(self, account, status=""):
            return [confirmation]

        monkeypatch.setattr(f"{_SERVICE_PATH}.list_confirmations", _list_confirmations)

        resp = client.get("/tool-confirmations")
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["total"] == 1

    def test_list_should_filter_by_status(self, client, monkeypatch):
        account_id = _mock_current_user(monkeypatch)

        def _list_confirmations(self, account, status=""):
            assert status == "pending"
            return []

        monkeypatch.setattr(f"{_SERVICE_PATH}.list_confirmations", _list_confirmations)

        resp = client.get("/tool-confirmations?status=pending")
        assert resp.json["code"] == HttpCode.SUCCESS

    def test_get_should_return_confirmation_detail(self, client, monkeypatch):
        account_id = _mock_current_user(monkeypatch)
        confirmation_id = uuid4()
        confirmation = _make_confirmation(id=confirmation_id)

        def _get_confirmation(self, cid, account):
            return confirmation

        monkeypatch.setattr(f"{_SERVICE_PATH}.get_confirmation", _get_confirmation)

        resp = client.get(f"/tool-confirmations/{confirmation_id}")
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["tool_name"] == "send_email"
