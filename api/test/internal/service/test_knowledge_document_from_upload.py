from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.exception import ValidateErrorException
from internal.service.knowledge_base_service import KnowledgeBaseService


def _service():
    created = []
    indexed = []
    service = KnowledgeBaseService(
        db=SimpleNamespace(),
        retrieval_service=SimpleNamespace(),
        icon_generator_service=SimpleNamespace(),
    )
    service.get_accessible_base = lambda _id, _account: SimpleNamespace(id=_id)
    service.create = lambda model, **kwargs: created.append(kwargs) or SimpleNamespace(
        id=uuid4(), **kwargs
    )
    service._get_knowledge_indexing_service = lambda: SimpleNamespace(
        build_document=lambda doc_id, account: indexed.append(doc_id)
    )
    return service, created, indexed


def test_create_document_from_upload_file_records_media_type():
    service, created, indexed = _service()
    account = SimpleNamespace(id=uuid4())
    knowledge_base_id = uuid4()
    upload_file = SimpleNamespace(id=uuid4(), name="promo.mp4", extension="mp4", size=2048)

    document = service.create_document_from_upload_file(
        knowledge_base_id=knowledge_base_id,
        upload_file=upload_file,
        account=account,
    )

    assert created[0]["media_type"] == "video"
    assert created[0]["upload_file_id"] == upload_file.id
    assert created[0]["parse_profile"] == {}
    assert indexed == [document.id]


def test_create_document_from_upload_file_enforces_base_type():
    service, created, indexed = _service()
    service.get_accessible_base = lambda _id, _account: SimpleNamespace(id=_id, base_type="video")
    account = SimpleNamespace(id=uuid4())
    upload_file = SimpleNamespace(id=uuid4(), name="doc.pdf", extension="pdf", size=10)

    with pytest.raises(ValidateErrorException):
        service.create_document_from_upload_file(
            knowledge_base_id=uuid4(), upload_file=upload_file, account=account
        )

    assert created == []
    assert indexed == []


def test_create_document_from_upload_file_accepts_partition_id():
    service, created, _indexed = _service()
    account = SimpleNamespace(id=uuid4())
    partition_id = uuid4()
    upload_file = SimpleNamespace(id=uuid4(), name="a.png", extension="png", size=10)

    service.create_document_from_upload_file(
        knowledge_base_id=uuid4(), upload_file=upload_file,
        account=account, partition_id=partition_id,
    )

    assert created[0]["partition_id"] == partition_id


def test_assert_upload_allowed_returns_base_when_valid():
    service, _created, _indexed = _service()
    account = SimpleNamespace(id=uuid4())
    knowledge_base_id = uuid4()

    base = service.assert_upload_allowed(knowledge_base_id, "mp4", account)

    assert base.id == knowledge_base_id


def test_assert_upload_allowed_rejects_mismatched_type():
    service, _created, _indexed = _service()
    service.get_accessible_base = lambda _id, _account: SimpleNamespace(id=_id, base_type="video")
    account = SimpleNamespace(id=uuid4())

    with pytest.raises(ValidateErrorException):
        service.assert_upload_allowed(uuid4(), "pdf", account)
