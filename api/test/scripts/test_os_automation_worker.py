import io
import json
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace

import pytest

from scripts.os_automation_worker import (
    _approvals,
    _build_codex_command,
    _build_prompt,
    _create_approval,
    _file_operation,
    _guard_delete_in_task,
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


class TestGuardDeleteInTask:
    """worker /run 删除护栏纯函数：仅 apply + 含终端删除命令时返回阻断结果。"""

    def test_apply_with_remove_item_returns_blocked(self):
        result = _guard_delete_in_task(
            "清理过期文件\nRemove-Item C:\\tmp\\a.txt", "apply"
        )

        assert result is not None
        assert result["ok"] is False
        assert result["blocked"] == "delete_command"
        assert "回收站" in result["error"]
        assert "os_recycle_bin" in result["error"]
        assert "Remove-Item" in result["detail"]

    def test_apply_with_rm_returns_blocked(self):
        result = _guard_delete_in_task(
            "清理构建缓存\nrm -rf /home/user/tmp", "apply"
        )

        assert result is not None
        assert result["blocked"] == "delete_command"
        assert "rm -rf" in result["detail"]

    def test_apply_with_del_returns_blocked(self):
        result = _guard_delete_in_task(
            "清理下载目录\n del /f /q C:\\temp\\x.txt", "apply"
        )

        assert result is not None
        assert result["blocked"] == "delete_command"

    def test_preview_with_delete_command_returns_none(self):
        assert _guard_delete_in_task("删除文件：del a.txt", "preview") is None

    def test_apply_safe_task_returns_none(self):
        assert _guard_delete_in_task("列出 C:\\temp 的文件", "apply") is None

    def test_empty_task_returns_none(self):
        assert _guard_delete_in_task("", "apply") is None


class TestApplyPromptDeleteConstraint:
    def test_apply_prompt_forbids_terminal_delete(self):
        prompt = _build_prompt("清理 C 盘临时文件", "apply")

        assert "回收站" in prompt
        assert "os_recycle_bin" in prompt
        assert "Remove-Item" in prompt
        assert "禁止" in prompt

    def test_apply_prompt_mentions_delete_command_names(self):
        prompt = _build_prompt("清理 C 盘临时文件", "apply")

        for name in ("del", "rm", "rmdir", "rd", "unlink"):
            assert name in prompt


class TestRunHandlerGuardWiring:
    """do_POST /run 的 apply 删除护栏接线（handler 级、不依赖真实 socket）。

    do_POST 依赖 BaseHTTPRequestHandler 的 socket 流，无法直接实例化，
    因此用 __new__ 构造最小 handler：伪造 headers/rfile/wfile，
    并把 _guard_delete_in_task 打桩为固定返回 dict，验证：
    1) apply 命中时 _send_json 收到 (200, blocked payload)；
    2) 命中时不会继续走到 _run_codex_task。
    """

    @staticmethod
    def _build_handler() -> BaseHTTPRequestHandler:
        import scripts.os_automation_worker as mod

        handler = BaseHTTPRequestHandler.__new__(mod.OsAutomationHandler)
        handler.client_address = ("127.0.0.1", 0)
        handler.server = SimpleNamespace()
        handler.command = "POST"
        handler.path = "/run"
        handler.request_version = "HTTP/1.1"
        handler.headers = {"Content-Length": "0"}
        handler.rfile = io.BytesIO(b"")
        handler.wfile = io.BytesIO()
        handler.close_connection = True
        handler.sent = {}
        return handler

    @staticmethod
    def _body(task: str) -> bytes:
        payload = {
            "task": task,
            "mode": "apply",
            "approval_token": "x",
            "working_dir": "",
            "timeout": 30,
        }
        return json.dumps(payload).encode("utf-8")

    def test_apply_guard_blocked_sends_200_blocked_and_skips_run(
        self, monkeypatch
    ):
        import scripts.os_automation_worker as mod

        sent = {}

        def _fake_send_json(self, status, payload):
            sent["status"] = status
            sent["payload"] = payload

        def _fake_authorized(self):
            return True

        def _boom(*_args, **_kwargs):
            raise AssertionError("命中删除护栏后不应继续执行 _run_codex_task")

        body = self._body("清理过期文件\nRemove-Item C:\\tmp\\a.txt")

        monkeypatch.setattr(mod, "_guard_delete_in_task", lambda *_a, **_k: {
            "ok": False,
            "blocked": "delete_command",
            "error": "任务包含物理删除命令，禁止绕过回收站删除本机文件。"
            "Agent 删除必须使用 os_recycle_bin 工具（delete 移入回收站，可恢复）。",
            "detail": "Remove-Item C:\\tmp\\a.txt",
        })
        monkeypatch.setattr(mod.OsAutomationHandler, "_send_json", _fake_send_json)
        monkeypatch.setattr(mod.OsAutomationHandler, "_authorized", _fake_authorized)
        monkeypatch.setattr(mod, "_run_codex_task", _boom)

        handler = self._build_handler()
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)

        handler.do_POST()

        assert sent["status"] == 200
        assert sent["payload"]["ok"] is False
        assert sent["payload"]["blocked"] == "delete_command"

    def test_apply_guard_clear_path_reaches_run(self, monkeypatch):
        import scripts.os_automation_worker as mod

        sent = {}

        def _fake_send_json(self, status, payload):
            sent["status"] = status
            sent["payload"] = payload

        def _fake_authorized(self):
            return True

        def _fake_run_codex_task(**kwargs):
            return {"ok": True, "mode": kwargs["mode"], "summary": "ok"}

        body = self._body("列出 C:\\temp 的文件")

        monkeypatch.setattr(mod, "_guard_delete_in_task", lambda *_a, **_k: None)
        monkeypatch.setattr(mod.OsAutomationHandler, "_send_json", _fake_send_json)
        monkeypatch.setattr(mod.OsAutomationHandler, "_authorized", _fake_authorized)
        monkeypatch.setattr(mod, "_run_codex_task", _fake_run_codex_task)

        handler = self._build_handler()
        handler.headers = {"Content-Length": str(len(body))}
        handler.rfile = io.BytesIO(body)

        handler.do_POST()

        assert sent["status"] == 200
        assert sent["payload"]["ok"] is True


class TestSandboxIsolation:
    """Codex 沙箱强制隔离：preview→read-only、apply→workspace-write、禁止 bypass。

    明文护栏（_guard_delete_in_task + 提示词）在 Task 3/4 已锁住"任务明文含删除
    命令"，但模型自主生成的删除命令不在任务明文中。Task 5 把防线下沉到 OS 层：
    沙箱是 Codex 调用本机 OS 机制（Windows AppContainer）强制的，模型想删都删不掉。
    """

    def test_preview_uses_read_only_sandbox(self):
        """preview 必须用 read-only 沙箱（OS 层禁止任何写/删命令）。"""
        cmd = _build_codex_command("codex.exe", "preview", ".", 30)

        assert "--sandbox" in cmd
        idx = cmd.index("--sandbox")
        assert cmd[idx + 1] == "read-only"

    def test_apply_uses_workspace_write_sandbox(self):
        """apply 必须用 workspace-write 沙箱（只能写 -C 工作区，无法删工作区外文件）。"""
        cmd = _build_codex_command("codex.exe", "apply", ".", 30)

        assert "--sandbox" in cmd
        idx = cmd.index("--sandbox")
        assert cmd[idx + 1] == "workspace-write"

    def test_apply_does_not_bypass_sandbox(self):
        """apply 绝不再用 --dangerously-bypass-approvals-and-sandbox。"""
        cmd = _build_codex_command("codex.exe", "apply", ".", 30)

        assert "--dangerously-bypass-approvals-and-sandbox" not in cmd

    def test_preview_does_not_bypass_sandbox(self):
        """preview 同样不得携带 bypass 逃生口。"""
        cmd = _build_codex_command("codex.exe", "preview", ".", 30)

        assert "--dangerously-bypass-approvals-and-sandbox" not in cmd

    def test_apply_prompt_mentions_workspace_write_sandbox(self):
        """apply 提示词须告知 Codex 运行在 workspace-write 沙箱（只能改工作区）。"""
        prompt = _build_prompt("清理 C 盘临时文件", "apply")

        assert "workspace-write" in prompt
        assert "工作区" in prompt
        assert "回收站" in prompt
        assert "os_recycle_bin" in prompt

    def test_preview_prompt_mentions_read_only_sandbox(self):
        """preview 提示词须告知 Codex 运行在 read-only 沙箱（写/删会被 OS 拒绝）。"""
        prompt = _build_prompt("清理 C 盘临时文件", "preview")

        assert "read-only" in prompt
        assert "read_only" in prompt or "只读" in prompt

