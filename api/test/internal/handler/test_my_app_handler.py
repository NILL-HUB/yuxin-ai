from types import SimpleNamespace
from uuid import uuid4

from pkg.response import HttpCode


class TestMyAppHandler:
    def test_list_my_apps_should_delegate_to_service_with_current_user(self, client, monkeypatch):
        account_id = uuid4()
        captured = {}
        monkeypatch.setattr("internal.handler.my_app_handler.current_user", SimpleNamespace(id=account_id, is_authenticated=True))

        def _list(self, account_id_arg):
            captured["account_id"] = account_id_arg
            return {"list": [{"id": "app-1", "assignment_id": "assignment-1", "name": "Contract AI", "icon": "", "description": "", "assigned_at": 1893456000}]}

        monkeypatch.setattr("internal.service.my_app_service.MyAppService.list_my_apps", _list, raising=False)

        resp = client.get("/my/apps")

        assert resp.status_code == 200
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["list"][0]["name"] == "Contract AI"
        assert captured == {"account_id": account_id}

    def test_chat_should_verify_assignment_and_delegate_to_app_service_with_current_user(self, client, monkeypatch):
        account_id = uuid4()
        app_id = uuid4()
        captured = {}
        monkeypatch.setattr("internal.handler.my_app_handler.current_user", SimpleNamespace(id=account_id, is_authenticated=True))

        def _get_assigned_app(self, account_id_arg, app_id_arg):
            captured["assignment_check"] = {"account_id": account_id_arg, "app_id": app_id_arg}
            return SimpleNamespace(id=app_id_arg)

        def _debug_chat(self, app_id_arg, req, user):
            captured["chat"] = {"app_id": app_id_arg, "query": req.query.data, "account_id": user.id}
            yield "data: ok\n\n"

        monkeypatch.setattr("internal.service.my_app_service.MyAppService.get_assigned_app", _get_assigned_app, raising=False)
        monkeypatch.setattr("internal.service.app_debug_service.AppDebugService.debug_chat", _debug_chat, raising=False)

        resp = client.post(f"/my/apps/{app_id}/chat", json={"query": "hello"})

        assert resp.status_code == 200
        assert b"data: ok" in resp.data
        assert captured["assignment_check"] == {"account_id": account_id, "app_id": app_id}
        assert captured["chat"] == {"app_id": app_id, "query": "hello", "account_id": account_id}
