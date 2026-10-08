"""百炼视频生成服务单测：凭证/参数校验与 CLI 命令构造。

隔离真实 `bl` 调用与成品库写入：subprocess 与 injector 均以替身注入，
只验证服务自身的契约（命令拼装、env 注入、入库调用与返回结构）。
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from internal.service.bailian_video_service import BailianVideoError, BailianVideoService


def test_generate_video_rejects_empty_prompt():
    service = BailianVideoService()

    with pytest.raises(BailianVideoError):
        service.generate_video(account=object(), prompt="   ")


def test_generate_video_requires_credential(monkeypatch):
    service = BailianVideoService()
    monkeypatch.setattr(service, "_resolve_api_key", lambda: "")

    with pytest.raises(BailianVideoError) as exc:
        service.generate_video(account=object(), prompt="太阳升起")

    assert "DASHSCOPE_API_KEY" in str(exc.value)


def test_generate_video_builds_cli_command_and_stores_output(monkeypatch):
    service = BailianVideoService()
    calls: dict = {}
    stored: dict = {}

    class _FakeProc:
        returncode = 0
        stdout = '{"task_id": "task-abc"}'
        stderr = ""

    def _fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["env"] = kwargs.get("env") or {}
        # 模拟 bl --download 产出文件（体积需过最小校验）
        idx = cmd.index("--download")
        Path(cmd[idx + 1]).write_bytes(b"x" * 4096)
        return _FakeProc()

    class _FakeKB:
        def store_render_output(self, *, account, video_path, name):
            stored["video_path"] = str(video_path)
            stored["name"] = name
            return SimpleNamespace(id="doc-1", knowledge_base_id="kb-1", name=name)

        def build_output_artifact(self, document):
            return {"url": "/storage/fake.mp4"}

    import app.http.module as module

    monkeypatch.setattr("subprocess.run", _fake_run)
    monkeypatch.setattr(service, "_resolve_api_key", lambda: "sk-test")
    monkeypatch.setattr(module.injector, "get", lambda cls: _FakeKB())

    result = service.generate_video(
        account=object(),
        prompt="夕阳下的麦田",
        name="测试成片",
        model="wan2.7-t2v",
        duration=3,
        resolution="720P",
        ratio="16:9",
    )

    cmd = calls["cmd"]
    assert cmd[:3] == ["bl", "video", "generate"]
    assert "--prompt" in cmd and cmd[cmd.index("--prompt") + 1] == "夕阳下的麦田"
    assert cmd[cmd.index("--model") + 1] == "wan2.7-t2v"
    assert cmd[cmd.index("--duration") + 1] == "3"
    assert cmd[cmd.index("--resolution") + 1] == "720P"
    assert cmd[cmd.index("--ratio") + 1] == "16:9"
    # 凭证经 env 注入子进程（bl 读 DASHSCOPE_API_KEY）
    assert calls["env"]["DASHSCOPE_API_KEY"] == "sk-test"
    # 产物入库并返回可播放 artifact
    assert stored["name"] == "测试成片"
    assert Path(stored["video_path"]).name == "output.mp4" or stored["video_path"].endswith(".mp4")
    assert result["document_id"] == "doc-1"
    assert result["artifact"] == {"url": "/storage/fake.mp4"}


def test_generate_video_raises_when_cli_outputs_no_file(monkeypatch):
    service = BailianVideoService()

    class _FakeProc:
        returncode = 1
        stdout = ""
        stderr = "boom: model unavailable"

    monkeypatch.setattr("subprocess.run", lambda cmd, **kwargs: _FakeProc())
    monkeypatch.setattr(service, "_resolve_api_key", lambda: "sk-test")

    with pytest.raises(BailianVideoError) as exc:
        service.generate_video(account=object(), prompt="测试")

    assert "视频生成失败" in str(exc.value)
