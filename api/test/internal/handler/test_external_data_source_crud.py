from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from pkg.response import HttpCode

_SERVICE_PATH = "internal.service.external_data_source_service.ExternalDataSourceService"
_KB_SERVICE_PATH = "internal.service.knowledge_base_service.KnowledgeBaseService"


def _mock_current_user(monkeypatch, account_id=None):
    account_id = account_id or uuid4()
    fake_user = SimpleNamespace(id=account_id, is_authenticated=True, is_active=True)
    monkeypatch.setattr("flask_login.current_user", fake_user, raising=False)
    return account_id


def _make_data_source(**overrides):
    defaults = {
        "id": uuid4(),
        "knowledge_base_id": uuid4(),
        "source_type": "lark",
        "source_name": "飞书知识库",
        "authorization_status": "granted",
        "sync_status": "idle",
        "sync_cursor": "",
        "last_synced_at": None,
        "last_error": "",
        "config": {"app_id": "cli_test"},
        "created_at": datetime(2025, 1, 1),
        "updated_at": datetime(2025, 1, 1),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestExternalDataSourceCrudHandler:
    def test_list_should_return_data_sources(self, client, monkeypatch):
        _mock_current_user(monkeypatch)
        ds = _make_data_source()

        def _list_data_sources(self, account, status=""):
            return [ds]

        monkeypatch.setattr(f"{_SERVICE_PATH}.list_data_sources", _list_data_sources)

        resp = client.get("/external-data-sources")
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["total"] == 1

    def test_get_should_return_detail(self, client, monkeypatch):
        _mock_current_user(monkeypatch)
        ds_id = uuid4()
        ds = _make_data_source(id=ds_id)

        def _get_data_source(self, did, account):
            return ds

        monkeypatch.setattr(f"{_SERVICE_PATH}.get_data_source", _get_data_source)

        resp = client.get(f"/external-data-sources/{ds_id}")
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["source_name"] == "飞书知识库"

    def test_delete_should_return_deleted_true(self, client, monkeypatch):
        _mock_current_user(monkeypatch)
        ds_id = uuid4()

        deleted = {"flag": False}

        def _delete_data_source(self, did, account):
            deleted["flag"] = True

        monkeypatch.setattr(f"{_SERVICE_PATH}.delete_data_source", _delete_data_source)

        resp = client.delete(f"/external-data-sources/{ds_id}")
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["deleted"] is True
        assert deleted["flag"] is True

    def test_authorize_should_update_status(self, client, monkeypatch):
        _mock_current_user(monkeypatch)
        ds_id = uuid4()
        ds = _make_data_source(id=ds_id, authorization_status="granted")

        def _authorize_data_source(self, did, account, auth_config):
            return ds

        monkeypatch.setattr(
            f"{_SERVICE_PATH}.authorize_data_source", _authorize_data_source
        )

        resp = client.post(
            f"/external-data-sources/{ds_id}/authorize",
            json={"auth_config": {"app_id": "cli_test", "app_secret": "secret"}},
        )
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["authorization_status"] == "granted"

    def test_sync_should_return_sync_result(self, client, monkeypatch):
        _mock_current_user(monkeypatch)
        ds_id = uuid4()

        def _manual_sync(self, did, account):
            return {
                "sync_status": "success",
                "document_count": 3,
                "segment_count": 10,
                "last_error": "",
            }

        monkeypatch.setattr(f"{_SERVICE_PATH}.manual_sync", _manual_sync)

        resp = client.post(f"/external-data-sources/{ds_id}/sync")
        assert resp.json["code"] == HttpCode.SUCCESS
        assert resp.json["data"]["document_count"] == 3
        assert resp.json["data"]["segment_count"] == 10
