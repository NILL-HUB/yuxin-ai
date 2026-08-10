from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.documents import Document as LCDocument

from internal.entity.dataset_entity import DocumentStatus, SegmentStatus
from internal.model import KnowledgeDocument, KnowledgeSegment, UploadFile
from internal.service.knowledge_indexing_service import KnowledgeIndexingService


@contextmanager
def _auto_commit():
    yield


class _ScalarQuery:
    def __init__(self, value=0):
        self._value = value

    def filter(self, *_args, **_kwargs):
        return self

    def scalar(self):
        return self._value


class _OneOrNoneQuery:
    def __init__(self, result=None):
        self._result = result

    def filter(self, *_args, **_kwargs):
        return self

    def one_or_none(self):
        return self._result


class _UpdateQuery:
    def __init__(self):
        self.payloads = []

    def filter(self, *_args, **_kwargs):
        return self

    def update(self, payload):
        self.payloads.append(payload)
        return 1


class _Session:
    def __init__(self, upload_file=None, segment=None):
        self._upload_file = upload_file
        self._segment = segment
        self._scalar_value = 0
        self._update_query = _UpdateQuery()

    def query(self, model):
        if model is UploadFile:
            return _OneOrNoneQuery(self._upload_file)
        if model is KnowledgeSegment:
            return self._update_query
        return _OneOrNoneQuery()

    @property
    def update_query(self):
        return self._update_query


class _Db:
    def __init__(self, session):
        self.session = session

    def auto_commit(self):
        return _auto_commit()


def _build_service(db=None, file_extractor=None,
                   embeddings_service=None, jieba_service=None,
                   knowledge_vector_service=None):
    return KnowledgeIndexingService(
        db=db or SimpleNamespace(session=SimpleNamespace()),
        file_extractor=file_extractor or SimpleNamespace(),
        embeddings_service=embeddings_service or SimpleNamespace(calculate_token_count=lambda _t: 1),
        jieba_service=jieba_service or SimpleNamespace(extract_keywords=lambda _t, _k: ["kw"]),
        knowledge_vector_service=knowledge_vector_service or SimpleNamespace(
            index_segment=lambda _seg, _kb: str(_seg.id)
        ),
    )


def _make_document(doc_id=None, upload_file_id=None):
    return SimpleNamespace(
        id=doc_id or uuid4(),
        knowledge_base_id=uuid4(),
        owner_account_id=uuid4(),
        name="demo.txt",
        upload_file_id=upload_file_id or uuid4(),
        character_count=0,
        token_count=0,
        status=DocumentStatus.WAITING.value,
        error="",
        knowledge_base=SimpleNamespace(
            id=uuid4(),
            knowledge_scope="user_content",
            owner_account_id=uuid4(),
        ),
    )


class TestKnowledgeIndexingService:
    def test_build_document_should_run_full_pipeline_and_mark_completed(self, monkeypatch):
        document = _make_document()
        service = _build_service()
        monkeypatch.setattr(service, "get", lambda _model, _pk: document)

        pipeline = []

        def _fake_update(target, **kwargs):
            pipeline.append((target, kwargs))

        monkeypatch.setattr(service, "update", _fake_update)
        monkeypatch.setattr(
            service,
            "_parsing",
            lambda doc: pipeline.append(("parsing", doc.id)) or [LCDocument(page_content="text")],
        )
        monkeypatch.setattr(
            service,
            "_splitting",
            lambda doc, lc_docs: pipeline.append(("splitting", doc.id, len(lc_docs))) or [
                LCDocument(page_content="seg", metadata={"segment_id": "seg-1"}),
            ],
        )
        monkeypatch.setattr(
            service,
            "_indexing",
            lambda doc, lc_segs: pipeline.append(("indexing", doc.id, len(lc_segs))),
        )
        monkeypatch.setattr(
            service,
            "_completed",
            lambda doc, lc_segs: pipeline.append(("completed", doc.id, len(lc_segs))) or _fake_update(
                doc, status=DocumentStatus.COMPLETED.value
            ),
        )

        service.build_document(document.id, SimpleNamespace(id=uuid4()))

        steps = [item[0] for item in pipeline if isinstance(item[0], str)]
        assert steps == ["parsing", "splitting", "indexing", "completed"]
        update_calls = [
            item for item in pipeline
            if len(item) == 2 and isinstance(item[0], SimpleNamespace) and isinstance(item[1], dict)
        ]
        status_updates = [kwargs.get("status") for _, kwargs in update_calls]
        assert DocumentStatus.PARSING.value in status_updates
        assert any(
            target is document and kwargs.get("status") == DocumentStatus.COMPLETED.value
            for target, kwargs in update_calls
        )

    def test_build_document_should_mark_error_when_pipeline_fails(self, monkeypatch):
        document = _make_document()
        service = _build_service()
        monkeypatch.setattr(service, "get", lambda _model, _pk: document)

        updates = []
        monkeypatch.setattr(service, "update", lambda target, **kwargs: updates.append((target, kwargs)))
        monkeypatch.setattr(
            service,
            "_parsing",
            lambda _doc: (_ for _ in ()).throw(RuntimeError("parse-boom")),
        )

        service.build_document(document.id, SimpleNamespace(id=uuid4()))

        error_update = next(
            (kwargs for target, kwargs in updates
             if target is document and kwargs.get("status") == DocumentStatus.ERROR.value),
            None,
        )
        assert error_update is not None
        assert "parse-boom" in error_update.get("error", "")

    def test_build_documents_should_continue_when_single_document_fails(self, monkeypatch):
        doc_ok = _make_document()
        doc_error = _make_document()
        service = _build_service()

        get_map = {doc_ok.id: doc_ok, doc_error.id: doc_error}
        monkeypatch.setattr(service, "get", lambda _model, pk: get_map.get(pk))

        steps_by_doc = {doc_ok.id: [], doc_error.id: []}

        def _fake_parsing(document):
            steps_by_doc[document.id].append("parsing")
            if document is doc_error:
                raise RuntimeError("single-fail")
            return [LCDocument(page_content="text")]

        monkeypatch.setattr(service, "_parsing", _fake_parsing)
        monkeypatch.setattr(
            service,
            "_splitting",
            lambda doc, _lc_docs: steps_by_doc[doc.id].append("splitting") or [
                LCDocument(page_content="seg", metadata={"segment_id": "s1"}),
            ],
        )
        monkeypatch.setattr(
            service,
            "_indexing",
            lambda doc, _segs: steps_by_doc[doc.id].append("indexing"),
        )
        monkeypatch.setattr(
            service,
            "_completed",
            lambda doc, _segs: steps_by_doc[doc.id].append("completed"),
        )

        error_updates = []
        monkeypatch.setattr(
            service,
            "update",
            lambda target, **kwargs: error_updates.append((target, kwargs)) if kwargs.get("status") == DocumentStatus.ERROR.value else None,
        )

        service.build_documents([doc_ok.id, doc_error.id], SimpleNamespace(id=uuid4()))

        assert steps_by_doc[doc_ok.id] == ["parsing", "splitting", "indexing", "completed"]
        assert steps_by_doc[doc_error.id] == ["parsing"]
        assert any(target is doc_error for target, _ in error_updates)

    def test_clean_extra_text_should_remove_control_characters(self):
        service = _build_service()

        result = service._clean_extra_text("hello\x00<|world|>\uFFFE")

        assert "\x00" not in result
        assert "<world>" in result
        assert "\uFFFE" not in result

    def test_completed_should_update_segments_and_document(self, monkeypatch):
        document = _make_document()
        session = _Session()
        db = _Db(session)
        service = _build_service(db=db)

        updates = []
        monkeypatch.setattr(service, "update", lambda target, **kwargs: updates.append((target, kwargs)))

        lc_segments = [
            LCDocument(page_content="seg-1", metadata={"segment_id": "seg-1"}),
            LCDocument(page_content="seg-2", metadata={"segment_id": "seg-2"}),
        ]

        service._completed(document, lc_segments)

        assert len(session.update_query.payloads) == 1
        payload = session.update_query.payloads[0]
        assert payload["status"] == SegmentStatus.COMPLETED.value
        assert payload["enabled"] is True
        assert any(
            target is document and kwargs.get("status") == DocumentStatus.COMPLETED.value
            for target, kwargs in updates
        )
