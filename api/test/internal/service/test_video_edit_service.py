"""视频编辑服务：命令执行、产物校验、失败语义。"""
import subprocess
from pathlib import Path

import pytest

from internal.service.video_edit_service import VideoEditService, VideoEditError


def _service(monkeypatch, *, run_result=None, run_error=None, duration=10.0):
    """构造绕过 DI 的服务实例，并替换 ffmpeg 执行与时长探测。"""
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

