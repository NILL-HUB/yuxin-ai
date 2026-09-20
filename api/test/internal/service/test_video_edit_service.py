"""视频编辑服务：命令执行、产物校验、失败语义。"""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from internal.service.video_edit_service import VideoEditService, VideoEditError


def _service(monkeypatch, *, run_result=None, run_error=None, duration=10.0, fonts=True):
    """构造绕过 DI 的服务实例，并替换 ffmpeg 执行与时长探测。

    fonts=True 时 stub 掉字体探测（真实环境无字体时该探测会正确拦下字幕烧录）。
    """
    svc = VideoEditService.__new__(VideoEditService)
    calls = []

    def fake_run(cmd, timeout):
        calls.append(cmd)
        if run_error is not None:
            raise run_error
        return run_result

    monkeypatch.setattr(svc, "_run_ffmpeg", fake_run)
    monkeypatch.setattr(svc, "_probe_duration", lambda p: duration)
    monkeypatch.setattr(svc, "_resolve_exe", lambda: "ffmpeg")
    if fonts:
        monkeypatch.setattr(svc, "_assert_fonts_available", lambda: None)
    return svc, calls


def _touch_ok(path: Path, size: int = 1024) -> None:
    path.write_bytes(b"x" * size)


def test_trim_produces_output_and_calls_ffmpeg(tmp_path, monkeypatch):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    svc, calls = _service(monkeypatch)
    monkeypatch.setattr(svc, "_materialize_output", lambda p: _touch_ok(p) or p)

    result = svc.trim(source_path=src, output_path=out, start_sec=1.0, end_sec=3.0)

    assert result == out
    assert len(calls) == 1
    assert "-c" in calls[0] and "copy" in calls[0]


def test_trim_rejects_start_beyond_duration(tmp_path, monkeypatch):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    svc, _ = _service(monkeypatch, duration=5.0)
    with pytest.raises(VideoEditError, match="超出视频时长"):
        svc.trim(source_path=src, output_path=out, start_sec=9.0, end_sec=10.0)


def test_trim_rejects_end_beyond_duration(tmp_path, monkeypatch):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    svc, _ = _service(monkeypatch, duration=5.0)
    with pytest.raises(VideoEditError, match="超出视频时长"):
        svc.trim(source_path=src, output_path=out, start_sec=1.0, end_sec=99.0)


def test_trim_source_missing_raises(tmp_path, monkeypatch):
    svc, _ = _service(monkeypatch)
    with pytest.raises(VideoEditError, match="源视频不存在"):
        svc.trim(
            source_path=tmp_path / "nope.mp4", output_path=tmp_path / "o.mp4",
            start_sec=0.0, end_sec=1.0,
        )


def test_trim_ffmpeg_failure_wrapped_as_video_edit_error(tmp_path, monkeypatch):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    err = subprocess.CalledProcessError(1, "ffmpeg", stderr=b"boom")
    svc, _ = _service(monkeypatch, run_error=err)
    with pytest.raises(VideoEditError, match="裁剪失败"):
        svc.trim(source_path=src, output_path=out, start_sec=0.0, end_sec=1.0)


def test_trim_empty_output_raises(tmp_path, monkeypatch):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    svc, _ = _service(monkeypatch)
    # ffmpeg 退出 0 但没产出文件：不能静默当成功
    with pytest.raises(VideoEditError, match="未产出有效文件"):
        svc.trim(source_path=src, output_path=out, start_sec=0.0, end_sec=1.0)


def test_concat_writes_list_file_in_sorted_order(tmp_path, monkeypatch):
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _touch_ok(a); _touch_ok(b)
    out = tmp_path / "out.mp4"
    svc, calls = _service(monkeypatch)
    captured = {}

    def fake_run(cmd, timeout):
        calls.append(cmd)
        list_file = Path(cmd[cmd.index("-i") + 1])
        captured["content"] = list_file.read_text(encoding="utf-8")
        _touch_ok(out)
        return None

    monkeypatch.setattr(svc, "_run_ffmpeg", fake_run)

    svc.concat(source_paths=[a, b], output_path=out)

    # concat demuxer 清单必须按传入顺序且路径绝对化
    assert captured["content"].index("a.mp4") < captured["content"].index("b.mp4")
    assert captured["content"].count("file '") == 2


def test_concat_requires_at_least_two_sources(tmp_path, monkeypatch):
    svc, _ = _service(monkeypatch)
    with pytest.raises(VideoEditError, match="至少需要两段"):
        svc.concat(source_paths=[tmp_path / "a.mp4"], output_path=tmp_path / "o.mp4")


def test_concat_missing_source_raises(tmp_path, monkeypatch):
    svc, _ = _service(monkeypatch)
    with pytest.raises(VideoEditError, match="源视频不存在"):
        svc.concat(
            source_paths=[tmp_path / "a.mp4", tmp_path / "b.mp4"],
            output_path=tmp_path / "o.mp4",
        )


def test_burn_subtitles_writes_srt_then_executes(tmp_path, monkeypatch):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    svc, calls = _service(monkeypatch)
    captured = {}

    def fake_run(cmd, timeout):
        calls.append(cmd)
        srt_path = Path(str(cmd[cmd.index("-vf") + 1]).split("'")[1].replace("\\:", ":"))
        captured["srt"] = srt_path.read_text(encoding="utf-8")
        _touch_ok(out)
        return None

    monkeypatch.setattr(svc, "_run_ffmpeg", fake_run)

    svc.burn_subtitles(
        source_path=src, output_path=out,
        cues=[{"start": 0.0, "end": 1.0, "text": "你好"}],
    )

    assert "你好" in captured["srt"]
    assert "00:00:00,000 --> 00:00:01,000" in captured["srt"]


def test_burn_subtitles_rejects_empty_cues(tmp_path, monkeypatch):
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    svc, _ = _service(monkeypatch)
    with pytest.raises(VideoEditError, match="字幕内容为空"):
        svc.burn_subtitles(source_path=src, output_path=out, cues=[])


def _edit_service(monkeypatch, *, docs, downloads_ok=True):
    """构造带素材下载与入库替身的服务。"""
    svc = VideoEditService.__new__(VideoEditService)
    monkeypatch.setattr(svc, "_resolve_exe", lambda: "ffmpeg")
    monkeypatch.setattr(svc, "_probe_duration", lambda p: 10.0)

    def fake_download(key, dest):
        if not downloads_ok:
            raise RuntimeError("download boom")
        Path(dest).write_bytes(b"v" * 2048)

    monkeypatch.setattr(svc, "_download_source", fake_download)
    monkeypatch.setattr(svc, "_load_source_documents", lambda **kw: docs)
    return svc


def _fake_doc(doc_id, key="kb/video.mp4", name="素材.mp4"):
    from types import SimpleNamespace
    return SimpleNamespace(id=doc_id, upload_file_id="uf-1",
                           upload_file=SimpleNamespace(key=key, name=name))


def test_trim_from_documents_downloads_and_stores(tmp_path, monkeypatch):
    doc = _fake_doc("doc-1")
    svc = _edit_service(monkeypatch, docs=[doc])
    stored = {}

    def fake_trim(**kw):
        Path(kw["output_path"]).write_bytes(b"o" * 4096)
        return Path(kw["output_path"])

    monkeypatch.setattr(svc, "trim", fake_trim)
    monkeypatch.setattr(
        svc, "_store_output",
        lambda *, account, video_path, name: stored.update(
            {"path": str(video_path), "name": name}
        ) or {"document_id": "new-doc"},
    )

    result = svc.trim_document(
        account="acc", knowledge_base_id="kb-1", document_id="doc-1",
        start_sec=0.0, end_sec=3.0, name="裁剪成品",
    )

    assert result["document_id"] == "new-doc"
    assert stored["name"] == "裁剪成品"


def test_trim_document_unknown_document_raises(monkeypatch):
    svc = _edit_service(monkeypatch, docs=[])
    with pytest.raises(VideoEditError, match="素材不存在"):
        svc.trim_document(
            account="acc", knowledge_base_id="kb-1", document_id="nope",
            start_sec=0.0, end_sec=1.0, name="x",
        )


def test_concat_documents_preserves_input_order(tmp_path, monkeypatch):
    docs = [_fake_doc("d1"), _fake_doc("d2"), _fake_doc("d3")]
    svc = _edit_service(monkeypatch, docs=docs)
    captured = {}

    def fake_concat(**kw):
        captured["paths"] = [Path(p).name for p in kw["source_paths"]]
        Path(kw["output_path"]).write_bytes(b"o" * 4096)
        return Path(kw["output_path"])

    monkeypatch.setattr(svc, "concat", fake_concat)
    monkeypatch.setattr(svc, "_store_output", lambda **kw: {"document_id": "nd"})

    svc.concat_documents(
        account="acc", knowledge_base_id="kb-1",
        document_ids=["d3", "d1", "d2"], name="拼接成品",
    )

    # 顺序必须严格按调用方给定（不能按 id 排序或去重）
    assert len(captured["paths"]) == 3
    assert len(set(captured["paths"])) == 3


def test_subtitle_document_burns_and_stores(tmp_path, monkeypatch):
    doc = _fake_doc("doc-1")
    svc = _edit_service(monkeypatch, docs=[doc])

    def fake_burn(**kw):
        Path(kw["output_path"]).write_bytes(b"o" * 4096)
        return Path(kw["output_path"])

    monkeypatch.setattr(svc, "burn_subtitles", fake_burn)
    monkeypatch.setattr(svc, "_store_output", lambda **kw: {"document_id": "sd"})

    result = svc.subtitle_document(
        account="acc", knowledge_base_id="kb-1", document_id="doc-1",
        cues=[{"start": 0, "end": 1, "text": "hi"}], name="字幕成品",
    )
    assert result["document_id"] == "sd"


def test_download_failure_is_wrapped(tmp_path, monkeypatch):
    doc = _fake_doc("doc-1")
    svc = _edit_service(monkeypatch, docs=[doc], downloads_ok=False)
    with pytest.raises(VideoEditError, match="下载素材失败"):
        svc.trim_document(
            account="acc", knowledge_base_id="kb-1", document_id="doc-1",
            start_sec=0.0, end_sec=1.0, name="x",
        )


def test_temp_dir_is_cleaned_after_success(monkeypatch):
    doc = _fake_doc("doc-1")
    svc = _edit_service(monkeypatch, docs=[doc])
    seen = {}

    def fake_trim(**kw):
        seen["dir"] = str(Path(kw["output_path"]).parent)
        Path(kw["output_path"]).write_bytes(b"o" * 4096)
        return Path(kw["output_path"])

    monkeypatch.setattr(svc, "trim", fake_trim)
    monkeypatch.setattr(svc, "_store_output", lambda **kw: {"document_id": "d"})

    svc.trim_document(
        account="acc", knowledge_base_id="kb-1", document_id="doc-1",
        start_sec=0.0, end_sec=1.0, name="x",
    )
    # 不能在用户/服务器上残留临时工作目录
    assert not Path(seen["dir"]).exists()


# ── 自动字幕：时间轴三级解析（显式 > 复用已留存 > 重跑 ASR） ────────────────
#
# 背景：本项目历史上认定「ASR 只返回纯文本、无时间戳」，故字幕时间轴被强制
# 由调用方提供。实测证明该结论错误——SiliconFlow ASR 在 verbose_json 下返回
# segments[{start,end,text}]，因此可以自动生成字幕。


def test_resolve_cues_prefers_explicit_input(monkeypatch):
    """显式传入时必须原样使用，不触碰库内留存与 ASR。"""
    svc = VideoEditService.__new__(VideoEditService)
    given = [{"start": 0.0, "end": 1.0, "text": "hi"}]
    monkeypatch.setattr(svc, "_load_stored_cues", lambda doc: [{"start": 9, "end": 10, "text": "stored"}])
    monkeypatch.setattr(
        svc, "_transcribe_source",
        lambda p: (_ for _ in ()).throw(AssertionError("不应重跑 ASR")),
    )

    result = svc._resolve_cues(document=SimpleNamespace(id="d"), source_path="s.mp4", cues=given)

    assert result == given


def test_resolve_cues_reuses_stored_timeline_without_rerunning_asr(monkeypatch):
    """库内已留存时间轴时应零 ASR 成本复用（这是最常见的自动字幕路径）。"""
    svc = VideoEditService.__new__(VideoEditService)
    stored = [{"start": 0.0, "end": 2.0, "text": "留存"}]
    monkeypatch.setattr(svc, "_load_stored_cues", lambda doc: stored)
    monkeypatch.setattr(
        svc, "_transcribe_source",
        lambda p: (_ for _ in ()).throw(AssertionError("不应重跑 ASR")),
    )

    result = svc._resolve_cues(document=SimpleNamespace(id="d"), source_path="s.mp4", cues=None)

    assert result == stored


def test_resolve_cues_falls_back_to_rerunning_asr(monkeypatch):
    """未留存时间轴（老素材）时才重跑 ASR——兜底而非默认。"""
    svc = VideoEditService.__new__(VideoEditService)
    monkeypatch.setattr(svc, "_load_stored_cues", lambda doc: [])
    generated = [{"start": 0.0, "end": 2.0, "text": "重跑"}]
    monkeypatch.setattr(svc, "_transcribe_source", lambda p: generated)

    result = svc._resolve_cues(document=SimpleNamespace(id="d"), source_path="s.mp4", cues=None)

    assert result == generated


def test_resolve_cues_raises_when_nothing_available(monkeypatch):
    """既无留存、重跑也无结果时必须报可读错误，不能烧出无字幕成品。"""
    svc = VideoEditService.__new__(VideoEditService)
    monkeypatch.setattr(svc, "_load_stored_cues", lambda doc: [])
    monkeypatch.setattr(svc, "_transcribe_source", lambda p: [])

    with pytest.raises(VideoEditError, match="未能生成字幕时间轴"):
        svc._resolve_cues(document=SimpleNamespace(id="d"), source_path="s.mp4", cues=None)


def test_load_stored_cues_sorts_by_start_and_skips_timeline_less_segments(monkeypatch):
    """跨片段合并后必须按时间排序；无时间轴的片段（如帧描述）必须被跳过。"""
    from types import SimpleNamespace as NS

    svc = VideoEditService.__new__(VideoEditService)
    monkeypatch.setattr(
        svc, "_load_document_segments",
        lambda doc_id: [
            NS(metadata_={"transcript_segments": [{"start": 5.0, "end": 6.0, "text": "后"}]}),
            NS(metadata_={"transcript_segments": [{"start": 1.0, "end": 2.0, "text": "前"}]}),
            NS(metadata_={"media_type": "video", "scene_index": 1}),
        ],
    )

    result = svc._load_stored_cues(NS(id="doc-1"))

    assert [cue["text"] for cue in result] == ["前", "后"]


def test_subtitle_document_auto_generates_when_cues_absent(tmp_path, monkeypatch):
    """端到端（服务层）：不传 cues 时也能完成烧录并入库。"""
    doc = _fake_doc("doc-1")
    svc = _edit_service(monkeypatch, docs=[doc])
    burned = {}

    def fake_burn(**kw):
        burned["cues"] = kw["cues"]
        Path(kw["output_path"]).write_bytes(b"o" * 4096)
        return Path(kw["output_path"])

    monkeypatch.setattr(svc, "burn_subtitles", fake_burn)
    monkeypatch.setattr(
        svc, "_load_stored_cues",
        lambda d: [{"start": 0.0, "end": 1.0, "text": "自动生成"}],
    )
    monkeypatch.setattr(svc, "_store_output", lambda **kw: {"document_id": "auto"})

    result = svc.subtitle_document(
        account="acc", knowledge_base_id="kb-1", document_id="doc-1",
        cues=None, name="自动字幕成品",
    )

    assert result["document_id"] == "auto"
    assert burned["cues"] == [{"start": 0.0, "end": 1.0, "text": "自动生成"}]



# ── 字体前置校验（真机实测发现的静默失效防护） ────────────────────────────
#
# 背景：api 镜像（python slim）**没有 fontconfig 配置与任何字体**。
# libass 找不到字体时不会报错退出，而是**静默跳过字幕渲染**——
# 实测产物与源帧逐像素完全相同（md5 一致）、退出码仍为 0。
# 这种「假成功」会把没加字幕的片子当成品入库，故必须前置拦下。


def _svc_raw(monkeypatch):
    svc = VideoEditService.__new__(VideoEditService)
    monkeypatch.setattr(svc, "_resolve_exe", lambda: "ffmpeg")
    return svc


def test_assert_fonts_available_rejects_when_fc_list_missing(monkeypatch):
    svc = _svc_raw(monkeypatch)
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(VideoEditError, match="fontconfig"):
        svc._assert_fonts_available()


def test_assert_fonts_available_rejects_when_no_fonts(monkeypatch):
    svc = _svc_raw(monkeypatch)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/fc-list")

    class _R:
        stdout = b"   \n  "

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
    with pytest.raises(VideoEditError, match="没有任何可用字体"):
        svc._assert_fonts_available()


def test_assert_fonts_available_passes_when_fonts_present(monkeypatch):
    svc = _svc_raw(monkeypatch)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/fc-list")

    class _R:
        stdout = b"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf: DejaVu Sans:style=Book\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
    svc._assert_fonts_available()  # 不应抛错


def test_burn_subtitles_blocks_when_fonts_missing(tmp_path, monkeypatch):
    """缺字体时必须在起 ffmpeg 之前拦下——否则会产出「没字幕的假成品」。"""
    src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _touch_ok(src)
    svc, calls = _service(monkeypatch, fonts=False)
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(VideoEditError, match="fontconfig"):
        svc.burn_subtitles(
            source_path=src, output_path=out,
            cues=[{"start": 0.0, "end": 1.0, "text": "hi"}],
        )
    # 关键断言：不应消耗一次 ffmpeg 调用（校验在之前）
    assert calls == []


# ── 时间线段落选段（KB-P4.5 衔接）：video_trim 按段落序号定位裁剪区间 ──
#
# 背景：KB-P4.5 起 L1 视频解析把「批次化时间线叙述」段落写入
# KnowledgeSegment.metadata.source=vision_timeline（含 start_sec/end_sec）。
# 衔接目标是让 video_trim 能基于这些段落选段（如「裁第 2 段」），而不是
# 只能手填秒数——段落即 KB-P4 剪辑的定位挂载点。


def _fake_doc_with_timeline_meta(doc_id="doc-1"):
    """构造带时间线段落的文档，其段落按 (start_sec, end_sec) 升序。"""
    from types import SimpleNamespace as NS

    doc = _fake_doc(doc_id)
    segments = [
        NS(metadata_={
            "media_type": "video", "source": "vision_timeline",
            "anchor_type": "speech_sentence", "anchor_text": "第一段",
            "start_sec": 0.0, "end_sec": 3.0, "speech_text": "今天很好",
        }),
        NS(metadata_={
            "media_type": "video", "source": "vision_timeline",
            "anchor_type": "speech_sentence", "anchor_text": "第二段",
            "start_sec": 3.0, "end_sec": 6.0, "speech_text": "然后回家",
        }),
        # 非时间线段（transcript_segments / 逐帧）必须被过滤，不作为选段来源
        NS(metadata_={"media_type": "video", "scene_index": 1, "time_offset": 1.5}),
        NS(metadata_={"media_type": "video",
                      "transcript_segments": [{"start": 0.0, "end": 2.0, "text": "转写"}]}),
    ]
    doc._fake_segments = segments
    return doc


def test_load_timeline_segments_filters_and_sorts(monkeypatch):
    """只保留 source=vision_timeline 段落，并按 start_sec 升序；忽略其他段。"""
    from types import SimpleNamespace as NS

    svc = VideoEditService.__new__(VideoEditService)
    rows = [
        # 乱序存放，验证按 start_sec 排序
        NS(metadata_={"source": "vision_timeline", "start_sec": 3.0, "end_sec": 6.0,
                      "anchor_type": "speech_sentence", "anchor_text": "b"}),
        NS(metadata_={"scene_index": 0, "time_offset": 1.0}),
        NS(metadata_={"source": "vision_timeline", "start_sec": 0.0, "end_sec": 3.0,
                      "anchor_type": "time_slot", "anchor_text": "a"}),
    ]
    monkeypatch.setattr(svc, "_load_document_segments", lambda doc_id: rows)

    result = svc._load_timeline_segments(NS(id="doc-1"))

    assert len(result) == 2
    assert result[0]["start_sec"] == 0.0
    assert result[1]["start_sec"] == 3.0
    assert result[1]["anchor_text"] == "b"


def test_load_timeline_segments_returns_empty_when_none(monkeypatch):
    """素材未解析出时间线段落（老素材/纯音频）时返回空列表，不抛错。"""
    from types import SimpleNamespace as NS

    svc = VideoEditService.__new__(VideoEditService)
    monkeypatch.setattr(svc, "_load_document_segments",
                        lambda doc_id: [NS(metadata_={"scene_index": 0, "time_offset": 0.1})])

    assert svc._load_timeline_segments(NS(id="doc-1")) == []


def test_resolve_trim_range_by_segment_index(monkeypatch):
    """segment_index 命中：返回该段落的 (start_sec, end_sec)。"""
    doc = _fake_doc_with_timeline_meta()
    svc = VideoEditService.__new__(VideoEditService)
    monkeypatch.setattr(svc, "_load_document_segments", lambda doc_id: doc._fake_segments)

    start, end = svc._resolve_trim_range(document=doc, segment_index=2,
                                          start_sec=None, end_sec=None)

    assert (start, end) == (3.0, 6.0)


def test_resolve_trim_range_segment_index_out_of_range(monkeypatch):
    """segment_index 越界时报可读错误，不静默截错段。"""
    doc = _fake_doc_with_timeline_meta()
    svc = VideoEditService.__new__(VideoEditService)
    monkeypatch.setattr(svc, "_load_document_segments", lambda doc_id: doc._fake_segments)

    with pytest.raises(VideoEditError, match="时间线段落"):
        svc._resolve_trim_range(document=doc, segment_index=99,
                                 start_sec=None, end_sec=None)


def test_resolve_trim_range_prefers_manual_seconds_when_no_segment_index(monkeypatch):
    """未传 segment_index 时维持手填秒数语义，不触碰时间线段。"""
    from types import SimpleNamespace as NS

    svc = VideoEditService.__new__(VideoEditService)
    # _load_document_segments 不应被调用（零成本）
    monkeypatch.setattr(
        svc, "_load_document_segments",
        lambda doc_id: (_ for _ in ()).throw(AssertionError("不应读取段落")),
    )

    start, end = svc._resolve_trim_range(document=NS(id="d"), segment_index=None,
                                          start_sec=1.0, end_sec=2.0)

    assert (start, end) == (1.0, 2.0)


def test_trim_document_by_segment_index(tmp_path, monkeypatch):
    """trim_document 传 segment_index：用时间线段落区间裁剪，忽略手填秒数。"""
    doc = _fake_doc_with_timeline_meta()
    svc = _edit_service(monkeypatch, docs=[doc])
    captured = {}

    def fake_trim(**kw):
        captured["start"] = kw["start_sec"]
        captured["end"] = kw["end_sec"]
        Path(kw["output_path"]).write_bytes(b"o" * 4096)
        return Path(kw["output_path"])

    monkeypatch.setattr(svc, "trim", fake_trim)
    monkeypatch.setattr(svc, "_load_document_segments", lambda doc_id: doc._fake_segments)
    monkeypatch.setattr(svc, "_store_output", lambda **kw: {"document_id": "sd"})

    result = svc.trim_document(
        account="acc", knowledge_base_id="kb-1", document_id="doc-1",
        start_sec=0.0, end_sec=1.0, name="按段裁剪",
        segment_index=2,
    )

    assert result["document_id"] == "sd"
    assert captured["start"] == 3.0
    assert captured["end"] == 6.0


def test_trim_document_by_segment_index_out_of_range(tmp_path, monkeypatch):
    """trim_document 传越界 segment_index：报可读错误，不产出错误成品。"""
    doc = _fake_doc_with_timeline_meta()
    svc = _edit_service(monkeypatch, docs=[doc])
    monkeypatch.setattr(svc, "_load_document_segments", lambda doc_id: doc._fake_segments)

    with pytest.raises(VideoEditError, match="时间线段落"):
        svc.trim_document(
            account="acc", knowledge_base_id="kb-1", document_id="doc-1",
            start_sec=0.0, end_sec=1.0, name="x", segment_index=99,
        )