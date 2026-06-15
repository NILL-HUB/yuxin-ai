from types import SimpleNamespace
from uuid import uuid4

from pkg.response import HttpCode


def _mock_current_admin(monkeypatch, permissions):
    def _get_current_admin_from_token(self, token):
        return {
            "id": "admin-1",
            "email": "root@example.com",
            "name": "Root",
            "avatar": "",
            "status": "active",
            "roles": ["super_admin"],
            "permissions": permissions,
        }

    monkeypatch.setattr(
        "internal.service.admin_user_service.AdminUserService.get_current_admin_from_token",
        _get_current_admin_from_token,
    )


class TestMemoryCandidateApi:
    def test_confirm_should_delegate_to_service_with_current_user(self, client, monkeypatch):
        account_id = uuid4()
        candidate_id = uuid4()
        captured = {}
        monkeypatch.setattr(
            "internal.handler.memory_candidate_handler.current_user",
            SimpleNamespace(id=account_id, is_authenticated=True),
        )

        def _confirm(self, candidate_id_arg, account, *, policy="manual_confirm"):
            captured.update({
                "candidate_id": candidate_id_arg,
                "account_id": account.id,
                "policy": policy,
            })
            return {
                "id": "memory-1",
                "memory_type": "preference",
                "content": "用户偏好使用中文回答",
                "confidence": 3,
                "status": "active",
                "created_from": "conversation_memory",
                "metadata": {"policy": policy},
            }

        monkeypatch.setattr(
            "internal.service.long_term_memory_service.UserMemoryConfirmationService.confirm",
            _confirm,
            raising=False,
        )

        resp = client.post(
            f"/memory-candidates/{candidate_id}/confirm",
            json={"policy": "manual_confirm"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["content"] == "用户偏好使用中文回答"
        assert captured == {
            "candidate_id": candidate_id,
            "account_id": account_id,
            "policy": "manual_confirm",
        }

    def test_ignore_should_delegate_to_service_with_current_user(
        self, client, monkeypatch
    ):
        account_id = uuid4()
        candidate_id = uuid4()
        captured = {}
        monkeypatch.setattr(
            "internal.handler.memory_candidate_handler.current_user",
            SimpleNamespace(id=account_id, is_authenticated=True),
        )

        def _ignore(self, candidate_id_arg, account, *, never_remind=False):
            captured.update({
                "candidate_id": candidate_id_arg,
                "account_id": account.id,
                "never_remind": never_remind,
            })
            return {
                "id": str(candidate_id_arg),
                "content": "用户偏好使用中文回答",
                "confidence": 3,
                "occurrences": 3,
                "status": "ignored",
                "metadata": {"never_remind": never_remind},
            }

        monkeypatch.setattr(
            "internal.service.long_term_memory_service.UserMemoryConfirmationService.ignore",
            _ignore,
            raising=False,
        )

        resp = client.post(
            f"/memory-candidates/{candidate_id}/ignore",
            json={"never_remind": True},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["status"] == "ignored"
        assert captured == {
            "candidate_id": candidate_id,
            "account_id": account_id,
            "never_remind": True,
        }


class TestExternalDataSourceApi:
    def test_create_should_delegate_to_service_and_hide_config(self, client, monkeypatch):
        account_id = uuid4()
        knowledge_base_id = uuid4()
        captured = {}
        monkeypatch.setattr(
            "internal.handler.external_data_source_handler.current_user",
            SimpleNamespace(id=account_id, is_authenticated=True),
        )

        def _get_base(self, knowledge_base_id_arg, account):
            captured["knowledge_base_id"] = knowledge_base_id_arg
            captured["base_account_id"] = account.id
            return SimpleNamespace(
                id=knowledge_base_id_arg,
                owner_account_id=account.id,
                knowledge_scope="user_content",
            )

        def _create(self, *, account, knowledge_base, source_type, source_name, config):
            captured.update({
                "account_id": account.id,
                "source_type": source_type,
                "source_name": source_name,
                "config": config,
            })
            return SimpleNamespace(
                id=uuid4(),
                knowledge_base_id=knowledge_base.id,
                source_type=source_type,
                source_name=source_name,
                authorization_status="pending",
                sync_status="idle",
            )

        monkeypatch.setattr(
            "internal.service.knowledge_base_service.KnowledgeBaseService.get_user_content_base",
            _get_base,
            raising=False,
        )
        monkeypatch.setattr(
            "internal.service.external_data_source_service.ExternalDataSourceService.create_connection",
            _create,
            raising=False,
        )

        resp = client.post(
            "/external-data-sources",
            json={
                "knowledge_base_id": str(knowledge_base_id),
                "source_type": "mock",
                "source_name": "Mock Docs",
                "config": {"token": "secret"},
            },
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["source_name"] == "Mock Docs"
        assert "config" not in resp.json["data"]
        assert captured["config"] == {"token": "secret"}

    def test_sync_should_delegate_to_service_with_current_user(self, client, monkeypatch):
        account_id = uuid4()
        data_source_id = uuid4()
        captured = {}
        monkeypatch.setattr(
            "internal.handler.external_data_source_handler.current_user",
            SimpleNamespace(id=account_id, is_authenticated=True),
        )

        def _manual_sync(self, data_source_id_arg, account):
            captured.update({"data_source_id": data_source_id_arg, "account_id": account.id})
            return {"sync_status": "success", "document_count": 1}

        monkeypatch.setattr(
            "internal.service.external_data_source_service.ExternalDataSourceService.manual_sync",
            _manual_sync,
            raising=False,
        )

        resp = client.post(f"/external-data-sources/{data_source_id}/sync")

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["document_count"] == 1
        assert captured == {"data_source_id": data_source_id, "account_id": account_id}


class TestToolConfirmationApi:
    def test_create_confirm_and_cancel_should_delegate_to_service(self, client, monkeypatch):
        account_id = uuid4()
        confirmation_id = uuid4()
        calls = []
        monkeypatch.setattr(
            "internal.handler.tool_confirmation_handler.current_user",
            SimpleNamespace(id=account_id, is_authenticated=True),
        )

        def _create(
            self,
            *,
            account,
            tool_name,
            risk_level,
            tool_input,
            spent_credits=0,
            reason="",
        ):
            calls.append((
                "create",
                account.id,
                tool_name,
                risk_level,
                tool_input,
                spent_credits,
                reason,
            ))
            return SimpleNamespace(
                id=confirmation_id,
                tool_name=tool_name,
                risk_level=risk_level,
                tool_input=tool_input,
                status="pending",
                spent_credits=spent_credits,
                reason=reason,
            )

        def _confirm(self, confirmation_id_arg, account):
            calls.append(("confirm", confirmation_id_arg, account.id))
            return SimpleNamespace(
                id=confirmation_id_arg,
                tool_name="delete_user",
                risk_level="high",
                tool_input={"user_id": "u1"},
                status="confirmed",
                spent_credits=12,
                reason="dangerous operation",
            )

        def _cancel(self, confirmation_id_arg, account):
            calls.append(("cancel", confirmation_id_arg, account.id))
            return SimpleNamespace(
                id=confirmation_id_arg,
                tool_name="delete_user",
                risk_level="high",
                tool_input={"user_id": "u1"},
                status="cancelled",
                spent_credits=12,
                reason="dangerous operation",
            )

        monkeypatch.setattr(
            "internal.service.tool_confirmation_service."
            "ToolConfirmationService.create_confirmation",
            _create,
            raising=False,
        )
        monkeypatch.setattr(
            "internal.service.tool_confirmation_service.ToolConfirmationService.confirm",
            _confirm,
            raising=False,
        )
        monkeypatch.setattr(
            "internal.service.tool_confirmation_service.ToolConfirmationService.cancel",
            _cancel,
            raising=False,
        )

        create_resp = client.post(
            "/tool-confirmations",
            json={
                "tool_name": "delete_user",
                "risk_level": "high",
                "tool_input": {"user_id": "u1"},
                "spent_credits": 12,
                "reason": "dangerous operation",
            },
        )
        confirm_resp = client.post(f"/tool-confirmations/{confirmation_id}/confirm")
        cancel_resp = client.post(f"/tool-confirmations/{confirmation_id}/cancel")

        assert create_resp.status_code == 200
        assert confirm_resp.json["data"]["status"] == "confirmed"
        assert cancel_resp.json["data"]["status"] == "cancelled"
        assert calls[0] == (
            "create",
            account_id,
            "delete_user",
            "high",
            {"user_id": "u1"},
            12,
            "dangerous operation",
        )


class TestAdminRoutingLogApi:
    def test_list_should_delegate_to_service(self, client, monkeypatch):
        account_id = uuid4()
        captured = {}
        _mock_current_admin(monkeypatch, ["routing_log:read"])

        def _page(self, *, page=1, page_size=20, account_id=None, status=None):
            captured.update({
                "page": page,
                "page_size": page_size,
                "account_id": account_id,
                "status": status,
            })
            return {
                "list": [{
                    "id": "log-1",
                    "account_id": str(account_id),
                    "message_id": "message-1",
                    "routing_decision": {"intent": "tool_task"},
                    "agent_candidates": [],
                    "filtered_out_agents": [],
                    "tool_candidates": [],
                    "filtered_out_tools": [
                        {"name": "delete", "reason": "high_risk_requires_confirmation"}
                    ],
                    "knowledge_hits": [],
                    "billing_events": [],
                    "status": "success",
                    "created_at": 1893456000,
                }],
                "paginator": {
                    "total_record": 1,
                    "total_page": 1,
                    "current_page": 1,
                    "page_size": 20,
                },
            }

        monkeypatch.setattr(
            "internal.service.routing_log_service.RoutingLogService.page",
            _page,
            raising=False,
        )

        resp = client.get(
            f"/admin/routing-logs?account_id={account_id}&status=success&current_page=1&page_size=20",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert (
            resp.json["data"]["list"][0]["filtered_out_tools"][0]["reason"]
            == "high_risk_requires_confirmation"
        )
        assert captured == {
            "page": 1,
            "page_size": 20,
            "account_id": account_id,
            "status": "success",
        }

    def test_list_should_reject_missing_permission(self, client, monkeypatch):
        _mock_current_admin(monkeypatch, ["admin:access"])

        resp = client.get(
            "/admin/routing-logs",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.FORBIDDEN
