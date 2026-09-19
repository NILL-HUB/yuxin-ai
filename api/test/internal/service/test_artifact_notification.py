"""产物提取与回填：让成片在对话里可见的两条通道。

覆盖两件事：
1. 从工具返回体（observation）提取 artifact —— 同步就绪产物的入口；
2. `notify_artifact_ready` 的持久化 + 推送 —— 异步产物完成后回填。
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from internal.lib.helper import extract_output_artifacts
from internal.service import artifact_notification_service as ans


# ── 通道 1：从 observation 提取（同步就绪产物） ─────────────────────────────


def _thought(*, observation="", tool_input=None):
    return SimpleNamespace(
        event="agent_action",
        thought="",
        observation=observation,
        tool="render_video",
        tool_input=tool_input or {},
    )


def test_extracts_artifact_from_tool_observation():
    observation = (
        '{"ok": true, "mode": "local", "document_id": "d1", '
        '"artifact": {"name": "成片", "url": "https://cdn.example.com/a.mp4", '
        '"mime_type": "video/mp4", "extension": "mp4"}}'
    )

    artifacts = extract_output_artifacts([_thought(observation=observation)])

    assert len(artifacts) == 1
    assert artifacts[0]["url"] == "https://cdn.example.com/a.mp4"
    assert artifacts[0]["name"] == "成片"


def test_ignores_observation_without_artifact_field():
    """工具成功但无产物（如仅派发）不得凭空造出附件。"""
    observation = '{"ok": true, "dispatched": true, "task_id": "t1"}'

    assert extract_output_artifacts([_thought(observation=observation)]) == []


def test_ignores_failed_tool_observation():
    observation = '{"ok": false, "error": "渲染失败", "artifact": {"url": "https://x/a.mp4"}}'

    assert extract_output_artifacts([_thought(observation=observation)]) == []


def test_ignores_non_json_observation():
    """普通文本回答里就算有 mp4 链接也不得误判成产物。"""
    assert extract_output_artifacts(
        [_thought(observation="视频已生成：https://cdn.example.com/a.mp4")]
    ) == []


def test_tool_input_artifact_still_takes_precedence():
    """既有 deep_artifact_created 路径不受影响（回归保护）。"""
    thought = _thought(
        tool_input={"artifact": {"name": "旧路径", "url": "https://cdn.example.com/old.png"}}
    )

    artifacts = extract_output_artifacts([thought])

    assert artifacts[0]["url"] == "https://cdn.example.com/old.png"


# ── 通道 2：notify_artifact_ready 的两条腿 ─────────────────────────────────


def test_notify_returns_false_when_artifact_has_no_url():
    assert ans.notify_artifact_ready(
        account_id="acc", message_id="m1", conversation_id="c1", artifact={"name": "x"},
    ) is False


def test_notify_persists_and_pushes(monkeypatch):
    calls = {}

    def _persist(**kw):
        calls["persist"] = kw
        return True

    def _push(**kw):
        calls["push"] = kw
        return True

    monkeypatch.setattr(ans, "_persist_artifact_thought", _persist)
    monkeypatch.setattr(ans, "_push_artifact_ready", _push)

    result = ans.notify_artifact_ready(
        account_id="acc", message_id="m1", conversation_id="c1",
        artifact={"url": "https://cdn.example.com/a.mp4", "name": "成片"},
        tool="video_trim",
    )

    assert result is True
    assert calls["persist"]["message_id"] == "m1"
    assert calls["push"]["account_id"] == "acc"


def test_notify_succeeds_when_only_push_works(monkeypatch):
    """推送成功但落库失败仍算成功——用户在线的当下已能看到。"""
    monkeypatch.setattr(ans, "_persist_artifact_thought", lambda **kw: False)
    monkeypatch.setattr(ans, "_push_artifact_ready", lambda **kw: True)

    assert ans.notify_artifact_ready(
        account_id="acc", message_id="m1", conversation_id="c1",
        artifact={"url": "https://cdn.example.com/a.mp4"},
    ) is True


def test_persist_skips_when_message_id_missing(monkeypatch):
    """无 message_id 时没有可挂载对象，直接跳过落库（不抛错）。"""
    assert ans._persist_artifact_thought(
        account_id="acc", message_id="", conversation_id="c1",
        artifact={"url": "https://x/a.mp4"}, tool="t", title="",
    ) is False


def test_push_sends_to_artifact_room(monkeypatch):
    """房间名必须是 artifact:<account_id>，与订阅处理器一致。

    推错 room 前端收不到——这是「代码全对但功能不可见」的典型断链，
    故用断言锁死房间名。
    """
    captured = {}

    class _Manager:
        def emit(self, event, data, room=None):
            captured["event"] = event
            captured["data"] = data
            captured["room"] = room

    monkeypatch.setattr(
        "internal.extension.socketio_extension.get_redis_manager", lambda: _Manager()
    )

    ok = ans._push_artifact_ready(
        account_id="acc-1", message_id="m1", conversation_id="c1",
        artifact={"url": "https://cdn.example.com/a.mp4"}, tool="video_trim", title="",
    )

    assert ok is True
    assert captured["event"] == ans.ARTIFACT_READY_EVENT
    assert captured["room"] == "artifact:acc-1"
    assert captured["data"]["message_id"] == "m1"
    assert captured["data"]["artifact"]["url"] == "https://cdn.example.com/a.mp4"


def test_push_failure_is_swallowed(monkeypatch):
    """推送失败不得把已成功的任务带崩。"""

    def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(
        "internal.extension.socketio_extension.get_redis_manager", _boom
    )

    assert ans._push_artifact_ready(
        account_id="acc", message_id="m1", conversation_id="c1",
        artifact={"url": "https://x/a.mp4"}, tool="t", title="",
    ) is False
