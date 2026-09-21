"""KB-P6 Task5：视频解析「平台字幕优先，无则回退 ASR」单测。

平台字幕（T2 写入 document.metadata_["subtitle_upload_file_id"]）优先级高于
音轨 ASR：有字幕时不走 _transcribe_video_track，cues 由字幕解析产出；无字幕
则回退 ASR。cues 字段与 ASR 对齐（text/start/end，秒），可无损喂给
build_timeline_plan。
"""
from unittest.mock import MagicMock

from internal.service.knowledge_media_extractor_service import (
    KnowledgeMediaExtractorService,
    parse_subtitle_cues_from_text,
)


def _make_svc():
    svc = KnowledgeMediaExtractorService(
        db=MagicMock(),
        cos_service=MagicMock(),
        audio_service=MagicMock(),
        upload_file_service=MagicMock(),
    )
    return svc


def test_video_subtitle_first_consumes_subtitle_cues(monkeypatch):
    """document 带 subtitle_upload_file_id 时：ASR 不被调用，cues 来自字幕。"""
    import internal.service.knowledge_media_extractor_service as mod

    svc = _make_svc()
    # 字幕 UploadFile 记录（id 非空即可，transport 下载/解析被 mock）
    svc.db.session.get.return_value = MagicMock()
    # 下载字幕文件到本地路径，供 _parse_subtitle_cues 读取（被 mock）
    monkeypatch.setattr(svc, "_download_to", lambda record, temp_dir: "/t/sub.vtt")
    # 字幕解析被 mock：返回与 ASR 同构的 cues
    monkeypatch.setattr(
        svc, "_parse_subtitle_cues",
        lambda record, path: [{"text": "你好", "start": 0.0, "end": 1.0}],
    )

    asr_called = {"n": 0}

    def _fake_asr(path, upload_file):
        asr_called["n"] += 1
        return "ASR TEXT", []

    monkeypatch.setattr(svc, "_transcribe_video_track", _fake_asr)
    monkeypatch.setattr(svc, "_extract_frames_with_offsets", lambda p, d: [MagicMock()])
    monkeypatch.setattr(svc, "_process_timeline_batch", lambda *a, **kw: [MagicMock()])
    # 屏蔽后续纯函数（真实实现需可调用的 ExtractedFrame.time_offset）
    monkeypatch.setattr(mod, "build_timeline_plan", lambda cues, frames: ("B", [MagicMock()]))
    monkeypatch.setattr(mod, "chunk_anchors", lambda anchors: [anchors])

    doc = MagicMock()
    doc.media_type = "video"  # extract 据此分派到 _extract_video
    doc.metadata_ = {"subtitle_upload_file_id": "sub1"}
    upload_file = MagicMock()
    upload_file.key = "x.mp4"
    segments = svc.extract(doc, upload_file, account_id=None, document_id="d1")
    assert asr_called["n"] == 0  # 字幕优先，ASR 未被调用
    assert segments and str(segments[0].content).strip() == "你好"
    assert segments[0].metadata["source"] == "platform_subtitle"  # 明确来源为字幕


def test_video_without_subtitle_falls_back_to_asr(monkeypatch):
    """document 无 subtitle_upload_file_id 时回退 ASR。"""
    import internal.service.knowledge_media_extractor_service as mod

    svc = _make_svc()
    asr_called = {"n": 0}

    def _fake_asr(path, upload_file):
        asr_called["n"] += 1
        return "ASR TEXT", []

    monkeypatch.setattr(svc, "_transcribe_video_track", _fake_asr)
    monkeypatch.setattr(svc, "_extract_frames_with_offsets", lambda p, d: [MagicMock()])
    monkeypatch.setattr(svc, "_process_timeline_batch", lambda *a, **kw: [MagicMock()])
    monkeypatch.setattr(mod, "build_timeline_plan", lambda cues, frames: ("A", [MagicMock()]))
    monkeypatch.setattr(mod, "chunk_anchors", lambda anchors: [anchors])

    doc = MagicMock()
    doc.media_type = "video"  # extract 据此分派到 _extract_video
    doc.metadata_ = {}  # 无字幕
    upload_file = MagicMock()
    upload_file.key = "x.mp4"
    segments = svc.extract(doc, upload_file, account_id=None, document_id="d1")
    assert asr_called["n"] == 1  # 无字幕回退 ASR
    assert segments and str(segments[0].content).strip() == "ASR TEXT"
    assert segments[0].metadata["source"] == "audio_transcript"  # 回退 ASR 来源标识


def test_video_subtitle_failure_falls_back_to_asr(monkeypatch):
    """document 带 subtitle_upload_file_id 但解析/取文件异常时，回退 ASR。"""
    import internal.service.knowledge_media_extractor_service as mod

    svc = _make_svc()
    # 字幕 UploadFile 记录存在，但下载/解析环节抛异常 → 触发防御性回退
    # 注意：_download_to 也会用于下载视频主体（key="x.mp4"），仅让字幕文件抛错
    svc.db.session.get.return_value = MagicMock()
    monkeypatch.setattr(
        svc, "_download_to",
        lambda record, temp_dir: (
            "/t/video.mp4" if getattr(record, "key", None) == "x.mp4"
            else (_ for _ in ()).throw(RuntimeError("字幕下载失败"))
        ),
    )

    asr_called = {"n": 0}

    def _fake_asr(path, upload_file):
        asr_called["n"] += 1
        return "ASR TEXT", []

    monkeypatch.setattr(svc, "_transcribe_video_track", _fake_asr)
    monkeypatch.setattr(svc, "_extract_frames_with_offsets", lambda p, d: [MagicMock()])
    monkeypatch.setattr(svc, "_process_timeline_batch", lambda *a, **kw: [MagicMock()])
    monkeypatch.setattr(mod, "build_timeline_plan", lambda cues, frames: ("A", [MagicMock()]))
    monkeypatch.setattr(mod, "chunk_anchors", lambda anchors: [anchors])

    doc = MagicMock()
    doc.media_type = "video"  # extract 据此分派到 _extract_video
    doc.metadata_ = {"subtitle_upload_file_id": "sub1"}  # 有字幕 id，但解析失败
    upload_file = MagicMock()
    upload_file.key = "x.mp4"
    segments = svc.extract(doc, upload_file, account_id=None, document_id="d1")
    assert asr_called["n"] == 1  # 字幕解析失败回退 ASR
    assert segments and str(segments[0].content).strip() == "ASR TEXT"
    assert segments[0].metadata["source"] == "audio_transcript"  # 回退后来源为 ASR


def test_parse_subtitle_cues_from_text_vtt():
    """轻量 VTT 解析：剥头部/内嵌标签，时间转秒，字段对齐 ASR cues。"""
    content = (
        "WEBVTT\n\n"
        "NOTE intro\n\n"
        "00:00:01.000 --> 00:00:02.000 align:start\n"
        "<i>你好</i>\n\n"
        "00:00:03.500 --> 00:00:05.000\n"
        "世界"
    )
    cues = parse_subtitle_cues_from_text(content)
    assert [c["text"] for c in cues] == ["你好", "世界"]
    assert cues[0]["start"] == 1.0
    assert cues[0]["end"] == 2.0
    assert cues[1]["start"] == 3.5


def test_parse_subtitle_cues_from_text_srt():
    """轻量 SRT 解析：跳过序号行，时间转秒。"""
    content = (
        "1\n"
        "00:00:01,500 --> 00:00:02,500\n"
        "hello\n\n"
        "2\n"
        "00:00:05,000 --> 00:00:06,000\n"
        "world"
    )
    cues = parse_subtitle_cues_from_text(content)
    assert [c["text"] for c in cues] == ["hello", "world"]
    assert cues[0]["start"] == 1.5
    assert cues[0]["end"] == 2.5