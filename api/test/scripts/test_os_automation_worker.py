import json
from types import SimpleNamespace

import pytest

from scripts.os_automation_worker import (
    _approvals,
    _build_prompt,
    _create_approval,
    _file_operation,
    _read_run_output,
    _resolve_safe_root,
    _parse_codex_jsonl,
    _run_codex_task,
    _spill_run_output,
)


@pytest.fixture(autouse=True)
def _clear_approvals():
    _approvals.clear()
    yield
    _approvals.clear()


def test_parse_codex_jsonl_extracts_commands_and_messages():
    stdout = "\n".join(
        [
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "Write-Output hello",
                        "status": "completed",
                        "exit_code": 0,
                        "aggregated_output": "hello",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": "已完成",
                    },
                }
            ),
        ]
    )

    commands, messages, summary = _parse_codex_jsonl(stdout, "")

    assert len(commands) == 1
    assert commands[0]["exit_code"] == 0
    assert messages == ["已完成"]
    assert summary == "已完成"


def test_preview_prompt_forbids_modifying_commands():
    prompt = _build_prompt("清理 C 盘垃圾", "preview")

    assert "只读检查" in prompt
    assert "禁止执行任何会修改" in prompt


def test_apply_requires_valid_approval_token(monkeypatch):
    monkeypatch.setattr(
        "scripts.os_automation_worker._find_codex_path",
        lambda: "codex.exe",
    )

    result = _run_codex_task(
        task="清理 C 盘垃圾",
        mode="apply",
        working_dir=".",
        timeout=30,
    )

    assert result["ok"] is False
    assert "approval_token" in result["error"]


def test_apply_consumes_approval_token_after_success(monkeypatch):
    token = _create_approval("清理 C 盘垃圾")
    monkeypatch.setattr(
        "scripts.os_automation_worker._find_codex_path",
        lambda: "codex.exe",
    )
    fake_completed = SimpleNamespace(
        stdout=json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": "任务完成",
                },
            }
        ),
        stderr="",
        returncode=0,
    )
    monkeypatch.setattr(
        "scripts.os_automation_worker.subprocess.run",
        lambda *_args, **_kwargs: fake_completed,
    )

    result = _run_codex_task(
        task="清理 C 盘垃圾",
        mode="apply",
        working_dir=".",
        timeout=30,
        approval_token=token,
    )

    assert result["ok"] is True
    assert result["summary"] == "任务完成"
    assert token not in _approvals


def test_file_read_returns_content(tmp_path, monkeypatch):
    target = tmp_path / "notes.txt"
    target.write_text("hello hermes\n", encoding="utf-8")

    result = _file_operation(
        {
            "op": "read",
            "path": str(target),
            "working_dir": str(tmp_path),
        }
    )

    assert result["ok"] is True
    assert result["content"] == "hello hermes\n"
    assert result["truncated"] is False


def test_file_read_blocks_outside_safe_root(tmp_path, monkeypatch):
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))

    result = _file_operation(
        {
            "op": "read",
            "path": str(outside),
            "working_dir": str(tmp_path),
        }
    )

    assert result["ok"] is False
    assert "超出允许目录" in result["error"]


def test_file_patch_preview_then_apply(tmp_path):
    target = tmp_path / "code.py"
    target.write_text("def old():\n    pass\n", encoding="utf-8")
    patch = (
        "*** Begin Patch\n"
        f"*** Update File: {target}\n@@\n"
        "-def old():\n+def new():\n     pass\n"
        "*** End Patch\n"
    )

    preview = _file_operation(
        {
            "op": "patch",
            "mode": "preview",
            "patch": patch,
            "working_dir": str(tmp_path),
        }
    )

    assert preview["ok"] is True
    token = preview["approval_token"]
    assert token

    applied = _file_operation(
        {
            "op": "patch",
            "mode": "apply",
            "patch": patch,
            "approval_token": token,
            "working_dir": str(tmp_path),
        }
    )

    assert applied["ok"] is True
    assert target.read_text(encoding="utf-8") == "def new():\n    pass\n"
    assert token not in _approvals


def test_file_patch_apply_requires_token(tmp_path):
    result = _file_operation(
        {
            "op": "patch",
            "mode": "apply",
            "patch": "*** Begin Patch\n*** Add File: x\n+x\n*** End Patch\n",
            "working_dir": str(tmp_path),
        }
    )

    assert result["ok"] is False
    assert "approval_token" in result["error"]


def test_file_patch_blocks_path_escape(tmp_path):
    patch = (
        "*** Begin Patch\n"
        f"*** Add File: {tmp_path.parent / 'evil.txt'}\n+evil\n"
        "*** End Patch\n"
    )

    result = _file_operation(
        {
            "op": "patch",
            "mode": "preview",
            "patch": patch,
            "working_dir": str(tmp_path),
        }
    )

    assert result["ok"] is False
    assert "超出允许目录" in result["error"]


def test_resolve_safe_root_defaults_to_home(tmp_path, monkeypatch):
    monkeypatch.delenv("OS_AUTOMATION_SAFE_ROOT", raising=False)
    assert _resolve_safe_root("") == str(__import__("pathlib").Path.home())


def test_spill_and_read_run_output(tmp_path, monkeypatch):
    monkeypatch.setenv("OS_AUTOMATION_OUTPUT_DIR", str(tmp_path))

    run_id = _spill_run_output(
        stdout="完整 stdout",
        stderr="部分 stderr",
        messages=["已完成"],
        commands=[{"command": "dir", "status": "completed"}],
    )

    run_output = _read_run_output(run_id)

    assert run_output is not None
    assert run_output["run_id"] == run_id
    assert run_output["stdout"] == "完整 stdout"
    assert run_output["messages"] == ["已完成"]
    assert run_output["commands"][0]["command"] == "dir"


def test_read_run_output_rejects_invalid_run_id(tmp_path, monkeypatch):
    monkeypatch.setenv("OS_AUTOMATION_OUTPUT_DIR", str(tmp_path))

    assert _read_run_output("../etc/passwd") is None
    assert _read_run_output("not-a-uuid") is None
