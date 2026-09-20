"""成片编辑器服务层：reassemble_document 的编排解析、逐段合成与落库。"""
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.service.video_edit_service import VideoEditError, VideoEditService


def _svc(monkeypatch):
    """构造绕过 DI 的服务实例，替换编排依赖的方法，`_resolve_trim_range` 走真实逻辑。"""
    svc = VideoEditService.__new__(VideoEditService)
    calls = {"trim": [], "concat": [], "store": None}
    docs = {}
    timeline = [
        {"start_sec": 0.0, "end_sec": 5.0, "anchor_type": "speech_sentence",
         "anchor_text": "第一句", "speech_text": "第一句台词"},
        {"start_sec": 5.0, "end_sec": 10.0, "anchor_type": "speech_sentence",
         "anchor_text": "第二句", "speech_text": "第二句台词"},
    ]

    def fake_load(*, account, knowledge_base_id, document_ids):
        return [docs[d] for d in document_ids if d in docs]

    def fake_prepare(doc, work_dir):
        path = Path(work_dir) / f"{doc.id}.mp4"
        path.write_bytes(b"x" * 1024)
        return path

    def fake_trim(*, source_path, output_path, start_sec, end_sec, reencode=False):
        Path(output_path).write_bytes(b"x" * 1024)
        calls["trim"].append((float(start_sec), None if end_sec is None else float(end_sec)))
        return Path(output_path)

    def fake_concat(*, source_paths, output_path):
        Path(output_path).write_bytes(b"x" * 1024)
        calls["concat"].append(len(source_paths))
        return Path(output_path)

    def fake_store(*, account, video_path, name):
        calls["store"] = (video_path, name)
        return {"document_id": str(uuid4()), "artifact": {"name": name, "url": "https://cos/x.mp4"}}

    monkeypatch.setattr(svc, "_load_source_documents", fake_load)
    monkeypatch.setattr(svc, "_prepare_source_file", fake_prepare)
    monkeypatch.setattr(svc, "trim", fake_trim)
    monkeypatch.setattr(svc, "concat", fake_concat)
    monkeypatch.setattr(svc, "_store_output", fake_store)
    monkeypatch.setattr(svc, "_load_timeline_segments", lambda document: list(timeline))
    return svc, calls, docs, timeline


def _doc(doc_id=None):
    return SimpleNamespace(id=doc_id or uuid4(), upload_file=SimpleNamespace(key="cos/key.mp4"))


def test_reassemble_single_clip_trims_and_skips_concat(monkeypatch):
    svc, calls, docs, _ = _svc(monkeypatch)
    main_id = uuid4()
    docs[str(main_id)] = _doc(main_id)

    result = svc.reassemble_document(
        account="acc", knowledge_base_id="kb", document_id=str(main_id),
        clips=[{"document_id": str(main_id), "segment_index": 1}], name="单段成片",
    )

    assert result["document_id"]
    assert calls["trim"] == [(0.0, 5.0)], "第 1 段应取 0~5s"
    assert calls["concat"] == [], "单段编排不应触发 concat"
    assert calls["store"][1] == "单段成片"


def test_reassemble_multi_clips_reorders_and_concats(monkeypatch):
    svc, calls, docs, _ = _svc(monkeypatch)
    main_id = uuid4()
    docs[str(main_id)] = _doc(main_id)

    svc.reassemble_document(
        account="acc", knowledge_base_id="kb", document_id=str(main_id),
        clips=[
            {"document_id": str(main_id), "segment_index": 2},
            {"document_id": str(main_id), "segment_index": 1},
        ],
        name="重排",
    )

    assert calls["trim"] == [(5.0, 10.0), (0.0, 5.0)], "应严格按 clips 顺序逐段裁剪"
    assert calls["concat"] == [2], "多段编排应触发一次 concat（2 段）"


def test_reassemble_whole_clip_uses_full_range(monkeypatch):
    svc, calls, docs, _ = _svc(monkeypatch)
    main_id = uuid4()
    docs[str(main_id)] = _doc(main_id)

    svc.reassemble_document(
        account="acc", knowledge_base_id="kb", document_id=str(main_id),
        clips=[{"document_id": str(main_id), "segment_index": 0}], name="整段",
    )

    assert calls["trim"] == [(0.0, None)], "segment_index=0 表示取整段（首尾全量）"


def test_reassemble_requires_at_least_one_clip(monkeypatch):
    svc, _, _, _ = _svc(monkeypatch)
    with pytest.raises(VideoEditError, match="至少需要一个片段"):
        svc.reassemble_document(
            account="acc", knowledge_base_id="kb", document_id=str(uuid4()),
            clips=[], name="",
        )


def test_reassemble_rejects_clip_without_document_id(monkeypatch):
    svc, _, _, _ = _svc(monkeypatch)
    with pytest.raises(VideoEditError, match="document_id"):
        svc.reassemble_document(
            account="acc", knowledge_base_id="kb", document_id=str(uuid4()),
            clips=[{"segment_index": 1}], name="",
        )


def test_reassemble_rejects_negative_segment_index(monkeypatch):
    svc, _, _, _ = _svc(monkeypatch)
    with pytest.raises(VideoEditError, match="不能为负"):
        svc.reassemble_document(
            account="acc", knowledge_base_id="kb", document_id=str(uuid4()),
            clips=[{"document_id": str(uuid4()), "segment_index": -1}], name="",
        )


def test_reassemble_rejects_segment_index_out_of_range(monkeypatch):
    svc, _, docs, _ = _svc(monkeypatch)
    main_id = uuid4()
    docs[str(main_id)] = _doc(main_id)

    with pytest.raises(VideoEditError, match="越界"):
        svc.reassemble_document(
            account="acc", knowledge_base_id="kb", document_id=str(main_id),
            clips=[{"document_id": str(main_id), "segment_index": 5}], name="",
        )


def test_reassemble_supports_cross_document_replacement(monkeypatch):
    """替换段落：不同素材的时间线段落也能进入编排，归属校验随 _load_source_documents。"""
    svc, calls, docs, _ = _svc(monkeypatch)
    main_id, repl_id = uuid4(), uuid4()
    docs[str(main_id)] = _doc(main_id)
    docs[str(repl_id)] = _doc(repl_id)

    svc.reassemble_document(
        account="acc", knowledge_base_id="kb", document_id=str(main_id),
        clips=[
            {"document_id": str(main_id), "segment_index": 1},
            {"document_id": str(repl_id), "segment_index": 2},
        ],
        name="替换成片",
    )

    assert calls["trim"] == [(0.0, 5.0), (5.0, 10.0)]
    assert calls["concat"] == [2]


def test_reassemble_requires_main_document_exists(monkeypatch):
    svc, _, docs, _ = _svc(monkeypatch)
    main_id, other_id = uuid4(), uuid4()
    docs[str(other_id)] = _doc(other_id)

    with pytest.raises(VideoEditError, match="素材不存在"):
        svc.reassemble_document(
            account="acc", knowledge_base_id="kb", document_id=str(main_id),
            clips=[{"document_id": str(other_id), "segment_index": 1}], name="",
        )
