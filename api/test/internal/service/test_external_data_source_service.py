from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import NotFoundException
from internal.model import ExternalDataSource, KnowledgeDocument, KnowledgeSegment
from internal.service.external_data_source_service import ExternalDataSourceService, MockExternalConnector


class _QueryStub:
    def __init__(self, *, one_or_none_result=None):
        self._one_or_none_result = one_or_none_result

    def filter(self, *_args, **_kwargs):
        return self

    def filter_by(self, **_kwargs):
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


@contextmanager
def _auto_commit():
    yield


def _fake_db(session):
    return SimpleNamespace(session=session, auto_commit=lambda: _auto_commit())


def test_create_connection_should_bind_current_user_and_user_content_base(monkeypatch):
    account_id = uuid4()
    knowledge_base_id = uuid4()
    service = ExternalDataSourceService(db=_fake_db(_SessionStub()))
    created = []
    monkeypatch.setattr(
        service,
        "create",
        lambda model, **kwargs: created.append((model, kwargs)) or SimpleNamespace(**kwargs),
    )

    result = service.create_connection(
        account=SimpleNamespace(id=account_id),
        knowledge_base=SimpleNamespace(id=knowledge_base_id, owner_account_id=account_id, knowledge_scope="user_content"),
        source_type="github",
        source_name="GitHub Docs",
        config={"path": "docs"},
    )

    assert created[0][0] is ExternalDataSource
    assert result.owner_account_id == account_id
    assert result.knowledge_base_id == knowledge_base_id
    assert result.authorization_status == "pending"
    assert result.sync_status == "idle"


def test_create_connection_should_reject_other_user_base():
    service = ExternalDataSourceService(db=_fake_db(_SessionStub()))

    with pytest.raises(NotFoundException):
        service.create_connection(
            account=SimpleNamespace(id=uuid4()),
            knowledge_base=SimpleNamespace(id=uuid4(), owner_account_id=uuid4(), knowledge_scope="user_content"),
            source_type="notion",
            source_name="Notion",
            config={},
        )


def test_manual_sync_should_write_documents_and_update_status(monkeypatch):
    account_id = uuid4()
    data_source = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        knowledge_base_id=uuid4(),
        source_type="mock",
        source_name="Mock",
        sync_status="idle",
        authorization_status="granted",
        sync_cursor="",
        config={},
    )
    service = ExternalDataSourceService(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=data_source)])),
        connector=MockExternalConnector([{"name": "doc.md", "content": "hello", "cursor": "cursor-1"}]),
    )
    created = []
    def _mock_create(model, **kwargs):
        obj = SimpleNamespace(**kwargs)
        if not hasattr(obj, "id"):
            obj.id = uuid4()
        created.append((model, kwargs))
        return obj

    monkeypatch.setattr(
        service,
        "create",
        _mock_create,
    )

    result = service.manual_sync(data_source.id, SimpleNamespace(id=account_id))

    assert created[0][0] is KnowledgeDocument
    assert data_source.sync_status == "success"
    assert data_source.sync_cursor == "cursor-1"
    assert result["sync_status"] == "success"
    assert result["document_count"] == 1
    assert result["segment_count"] >= 1


class _FailingExternalConnector:
    def sync(self, data_source, config=None):
        raise RuntimeError("connector unavailable")


def test_manual_sync_should_record_failed_status_and_last_error(monkeypatch):
    account_id = uuid4()
    data_source = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        knowledge_base_id=uuid4(),
        source_type="mock",
        source_name="Mock",
        sync_status="idle",
        authorization_status="granted",
        sync_cursor="",
        last_error="",
        config={},
    )
    service = ExternalDataSourceService(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=data_source)])),
        connector=_FailingExternalConnector(),
    )
    created = []
    monkeypatch.setattr(
        service,
        "create",
        lambda model, **kwargs: created.append((model, kwargs)) or SimpleNamespace(**kwargs),
    )

    result = service.manual_sync(data_source.id, SimpleNamespace(id=account_id))

    assert created == []
    assert data_source.sync_status == "failed"
    assert data_source.last_error == "connector unavailable"
    assert result == {
        "sync_status": "failed",
        "document_count": 0,
        "last_error": "connector unavailable",
    }


def test_manual_sync_should_hide_other_user_data_source():
    data_source = SimpleNamespace(id=uuid4(), owner_account_id=uuid4())
    service = ExternalDataSourceService(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=data_source)])),
        connector=MockExternalConnector([]),
    )

    with pytest.raises(NotFoundException):
        service.manual_sync(data_source.id, SimpleNamespace(id=uuid4()))


def test_create_connection_should_persist_operation_context_in_config(monkeypatch):
    account_id = uuid4()
    service = ExternalDataSourceService(db=_fake_db(_SessionStub()))
    created = []
    monkeypatch.setattr(
        service,
        "create",
        lambda model, **kwargs: created.append((model, kwargs)) or SimpleNamespace(**kwargs),
    )

    service.create_connection(
        account=SimpleNamespace(id=account_id),
        knowledge_base=SimpleNamespace(id=uuid4(), owner_account_id=account_id, knowledge_scope="user_content"),
        source_type="github",
        source_name="GitHub",
        config={"path": "docs"},
    )

    config = created[0][1]["config"]
    assert config["operation_context"] == "user"
    assert config["path"] == "docs"


def test_manual_sync_should_persist_operation_context_in_document_and_segment_metadata(monkeypatch):
    account_id = uuid4()
    data_source = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        knowledge_base_id=uuid4(),
        source_type="mock",
        source_name="Mock",
        sync_status="idle",
        authorization_status="granted",
        sync_cursor="",
        config={},
    )
    service = ExternalDataSourceService(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=data_source)])),
        connector=MockExternalConnector([{"name": "doc.md", "content": "hello"}]),
    )
    created = []

    def _mock_create(model, **kwargs):
        obj = SimpleNamespace(**kwargs)
        if not hasattr(obj, "id"):
            obj.id = uuid4()
        created.append((model, kwargs))
        return obj

    monkeypatch.setattr(service, "create", _mock_create)

    service.manual_sync(data_source.id, SimpleNamespace(id=account_id))

    doc_kwargs = next(kwargs for model, kwargs in created if model is KnowledgeDocument)
    assert doc_kwargs["metadata_"]["operation_context"] == "user"
    seg_kwargs = next(kwargs for model, kwargs in created if model is KnowledgeSegment)
    assert seg_kwargs["metadata_"]["operation_context"] == "user"


def test_create_connection_should_encrypt_sensitive_config(monkeypatch):
    account_id = uuid4()
    service = ExternalDataSourceService(db=_fake_db(_SessionStub()))
    created = []
    monkeypatch.setattr(
        service,
        "create",
        lambda model, **kwargs: created.append((model, kwargs)) or SimpleNamespace(**kwargs),
    )

    service.create_connection(
        account=SimpleNamespace(id=account_id),
        knowledge_base=SimpleNamespace(id=uuid4(), owner_account_id=account_id, knowledge_scope="user_content"),
        source_type="lark",
        source_name="Lark",
        config={"app_id": "cli_x", "app_secret": "plain-secret"},
    )

    config = created[0][1]["config"]
    assert config["app_id"] == "cli_x"
    assert config["app_secret"] != "plain-secret"
    assert config["app_secret"].startswith("gAAAAA")


def test_authorize_should_persist_auth_config_encrypted(monkeypatch):
    account_id = uuid4()
    data_source = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        source_type="lark",
        authorization_status="pending",
        config={},
    )
    service = ExternalDataSourceService(db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=data_source)])))

    class _Connector:
        def authorize(self, ds, auth_config, config=None):
            assert config is not None, "连接器必须收到解密后的配置"
            return "granted"

    monkeypatch.setattr(service.connector_factory, "get_connector", lambda _t: _Connector())

    service.authorize_data_source(data_source.id, SimpleNamespace(id=account_id), {"app_secret": "new-secret"})

    assert data_source.authorization_status == "granted"
    assert data_source.config["app_secret"] != "new-secret"
    assert data_source.config["app_secret"].startswith("gAAAAA")


def test_manual_sync_should_pass_decrypted_config_to_connector(monkeypatch):
    account_id = uuid4()
    from internal.service.external_data_source_credentials import encrypt_config

    data_source = SimpleNamespace(
        id=uuid4(),
        owner_account_id=account_id,
        knowledge_base_id=uuid4(),
        source_type="mock",
        source_name="Mock",
        sync_status="idle",
        authorization_status="granted",
        sync_cursor="",
        last_error="",
        config=encrypt_config({"app_secret": "plain-secret"}),
    )
    seen = {}

    class _Connector:
        def sync(self, ds, config=None):
            seen["secret"] = (config or {}).get("app_secret")
            return []

    service = ExternalDataSourceService(
        db=_fake_db(_SessionStub([_QueryStub(one_or_none_result=data_source)])),
        connector=_Connector(),
    )
    monkeypatch.setattr(service, "_get_knowledge_base", lambda _id: None)

    service.manual_sync(data_source.id, SimpleNamespace(id=account_id))

    assert seen["secret"] == "plain-secret"


def test_auto_sync_all_isolates_failures(monkeypatch):
    owner_id = uuid4()
    granted = SimpleNamespace(id=uuid4(), owner_account_id=owner_id, authorization_status="granted", sync_status="idle")

    # Account 查询返回 owner，避免被 auto_sync_all 跳过
    session = _SessionStub([_QueryStub(one_or_none_result=SimpleNamespace(id=owner_id))])
    service = ExternalDataSourceService(db=_fake_db(session))
    monkeypatch.setattr(service, "_list_auto_sync_candidates", lambda: [granted])
    monkeypatch.setattr(
        service,
        "manual_sync",
        lambda ds_id, account, **kw: {"sync_status": "success", "document_count": 1, "segment_count": 2},
    )

    result = service.auto_sync_all()

    assert result == {"scanned": 1, "synced": 1, "failed": 0}


def test_auto_sync_all_counts_failures_without_raising(monkeypatch):
    owner_id = uuid4()
    broken = SimpleNamespace(id=uuid4(), owner_account_id=owner_id, authorization_status="granted", sync_status="idle")

    session = _SessionStub([_QueryStub(one_or_none_result=SimpleNamespace(id=owner_id))])
    service = ExternalDataSourceService(db=_fake_db(session))
    monkeypatch.setattr(service, "_list_auto_sync_candidates", lambda: [broken])

    def _boom(ds_id, account, **kw):
        raise RuntimeError("connector down")

    monkeypatch.setattr(service, "manual_sync", _boom)

    result = service.auto_sync_all()

    assert result == {"scanned": 1, "synced": 0, "failed": 1}
