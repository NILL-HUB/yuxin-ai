from types import SimpleNamespace
from uuid import uuid4

from pkg.response import HttpCode


class TestRedeemCodeHandler:
    def test_redeem_should_delegate_to_service_with_current_user(self, client, monkeypatch):
        account_id = uuid4()
        captured = {}
        monkeypatch.setattr("internal.handler.redeem_code_handler.current_user", SimpleNamespace(id=account_id, is_authenticated=True))

        def _redeem(self, account_id_arg, plain_code):
            captured.update({"account_id": account_id_arg, "plain_code": plain_code})
            return {
                "plan": {"id": "plan-1", "code": "pro", "name": "Pro", "duration_days": 30, "grant_token_credits": 100000},
                "membership": {"id": "membership-1", "status": "active", "started_at": 1893456000, "expires_at": 1896048000, "source": "redeem_code", "source_id": "code-1", "plan": None},
                "credit_account": {"account_id": str(account_id_arg), "balance": 100000, "total_granted": 100000, "total_consumed": 0},
                "redeem_code": {"id": "code-1", "code_mask": "OAAB****C", "redeemed_at": 1893456000},
            }

        monkeypatch.setattr("internal.service.redeem_code_service.RedeemCodeService.redeem", _redeem, raising=False)

        resp = client.post("/redeem-codes/redeem", json={"code": "OA-TEST-CODE"})

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["credit_account"]["balance"] == 100000
        assert captured == {"account_id": account_id, "plain_code": "OA-TEST-CODE"}

    def test_membership_summary_should_delegate_to_service_with_current_user(self, client, monkeypatch):
        account_id = uuid4()
        captured = {}
        monkeypatch.setattr("internal.handler.redeem_code_handler.current_user", SimpleNamespace(id=account_id, is_authenticated=True))

        def _summary(self, account_id_arg):
            captured["account_id"] = account_id_arg
            return {
                "membership": None,
                "credit_account": {"account_id": str(account_id_arg), "balance": 0, "total_granted": 0, "total_consumed": 0},
                "recent_transactions": [],
            }

        monkeypatch.setattr("internal.service.redeem_code_service.RedeemCodeService.get_membership_summary", _summary, raising=False)

        resp = client.get("/membership/summary")

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["credit_account"]["balance"] == 0
        assert captured == {"account_id": account_id}

    def test_redeem_records_should_delegate_to_service_with_current_user(self, client, monkeypatch):
        account_id = uuid4()
        captured = {}
        monkeypatch.setattr("internal.handler.redeem_code_handler.current_user", SimpleNamespace(id=account_id, is_authenticated=True))

        def _records(self, account_id_arg):
            captured["account_id"] = account_id_arg
            return {
                "list": [{"id": "code-1", "code_mask": "OAAB****C", "redeemed_at": 1893456000, "plan": {"id": "plan-1", "code": "pro", "name": "Pro", "duration_days": 30, "grant_token_credits": 100000}, "grant_token_credits": 100000, "membership_expires_at": 1896048000}]
            }

        monkeypatch.setattr("internal.service.redeem_code_service.RedeemCodeService.list_redeem_records", _records, raising=False)

        resp = client.get("/membership/redeem-records")

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["code_mask"] == "OAAB****C"
        assert captured == {"account_id": account_id}
