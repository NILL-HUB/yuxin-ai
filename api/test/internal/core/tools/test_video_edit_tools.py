"""视频编辑工具：参数解析、派发、错误可读化。

工具不向 Agent 抛异常，一律返回 {"ok": bool, ...} JSON。
"""
import json

import pytest

from internal.core.tools.builtin_tools.providers.video_edit_tools import (
    video_concat,
    video_subtitle,
    video_trim,
)


def _capture_delay(monkeypatch, module):
    captured = {}

    class _Task:
        @staticmethod
        def delay(*args, **kwargs):
            captured["args"] = args
            return __import__("types").SimpleNamespace(id="task-1")

    monkeypatch.setattr(module, "_load_task", lambda: _Task)
    return captured


def test_trim_tool_requires_account():
    tool = video_trim.video_trim()
    payload = json.loads(tool._run(knowledge_base_id="kb", document_id="d", start_sec=0, end_sec=1))
    assert payload["ok"] is False
    assert "账号" in payload["error"]


def test_trim_tool_requires_kb_and_document():
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(tool._run(document_id="d", start_sec=0, end_sec=1))
    assert payload["ok"] is False
    assert "知识库" in payload["error"] or "素材" in payload["error"]


def test_trim_tool_rejects_negative_start():
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb", document_id="d", start_sec=-1, end_sec=1)
    )
    assert payload["ok"] is False
    assert "开始时间" in payload["error"]


def test_trim_tool_rejects_end_not_after_start():
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb", document_id="d", start_sec=2, end_sec=2)
    )
    assert payload["ok"] is False


def test_trim_tool_dispatches_celery_task(monkeypatch):
    captured = _capture_delay(monkeypatch, video_trim)
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb-1", document_id="doc-1",
                  start_sec=1.0, end_sec=3.0, name="裁剪")
    )
    assert payload["ok"] is True
    assert payload["task_id"] == "task-1"
    assert captured["args"][0] == "kb-1"
    assert captured["args"][1] == "doc-1"
    assert captured["args"][4] == "裁剪"


def test_trim_tool_reports_dispatch_failure_readably(monkeypatch):
    class _Boom:
        @staticmethod
        def delay(*a, **k):
            raise RuntimeError("broker down")

    monkeypatch.setattr(video_trim, "_load_task", lambda: _Boom)
    tool = video_trim.video_trim(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb", document_id="d", start_sec=0, end_sec=1)
    )
    assert payload["ok"] is False
    assert "提交" in payload["error"]


def test_concat_tool_requires_two_documents():
    tool = video_concat.video_concat(account_id="acc")
    payload = json.loads(tool._run(knowledge_base_id="kb", document_ids=["d1"]))
    assert payload["ok"] is False
    assert "两段" in payload["error"]


def test_concat_tool_dispatches_in_order(monkeypatch):
    captured = _capture_delay(monkeypatch, video_concat)
    tool = video_concat.video_concat(account_id="acc")
    json.loads(tool._run(knowledge_base_id="kb", document_ids=["d3", "d1"], name="合片"))
    assert captured["args"][1] == ["d3", "d1"]


def test_subtitle_tool_requires_cues():
    tool = video_subtitle.video_subtitle(account_id="acc")
    payload = json.loads(tool._run(knowledge_base_id="kb", document_id="d", cues=[]))
    assert payload["ok"] is False
    assert "字幕" in payload["error"]


def test_subtitle_tool_rejects_malformed_cue():
    tool = video_subtitle.video_subtitle(account_id="acc")
    payload = json.loads(
        tool._run(knowledge_base_id="kb", document_id="d",
                  cues=[{"start": "abc", "end": 2, "text": "x"}])
    )
    assert payload["ok"] is False
    assert "时间" in payload["error"]


def test_subtitle_tool_dispatches_cues(monkeypatch):
    captured = _capture_delay(monkeypatch, video_subtitle)
    tool = video_subtitle.video_subtitle(account_id="acc")
    cues = [{"start": 0.0, "end": 1.0, "text": "hi"}]
    json.loads(
        tool._run(knowledge_base_id="kb", document_id="d", cues=cues, name="字幕")
    )
    assert captured["args"][2] == cues


def test_tool_yamls_declare_expected_shape():
    from pathlib import Path

    import yaml

    base = Path(video_trim.__file__).parent
    for stem in ("video_trim", "video_concat", "video_subtitle"):
        data = yaml.safe_load((base / f"{stem}.yaml").read_text(encoding="utf-8"))
        assert data["name"] == stem
        assert data["label"]
        assert isinstance(data["params"], list) and data["params"]
        assert isinstance(data["task_keywords"], list) and data["task_keywords"]


def test_positions_yaml_lists_all_three_tools():
    from pathlib import Path

    import yaml

    base = Path(video_trim.__file__).parent
    names = yaml.safe_load((base / "positions.yaml").read_text(encoding="utf-8"))
    assert set(names) == {"video_trim", "video_concat", "video_subtitle"}
