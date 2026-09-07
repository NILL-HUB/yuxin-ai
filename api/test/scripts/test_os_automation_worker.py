import pytest

from scripts.os_automation_worker import (
    _approvals,
    _create_approval,
    _file_operation,
    _resolve_safe_root,
)


@pytest.fixture(autouse=True)
def _clear_approvals():
    _approvals.clear()
    yield
    _approvals.clear()


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

