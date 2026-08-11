from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[4]
        / "internal/core/skills/catalog/system_access/skill.py"
    )
    spec = importlib.util.spec_from_file_location("system_access_skill", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_system_access_skill_should_write_read_and_list_files(monkeypatch, tmp_path):
    module = _load_module()
    monkeypatch.setenv("SYSTEM_ACCESS_WORKSPACE", str(tmp_path))

    write_result = module.write_file(
        {"path": "notes/hello.txt", "content": "hello yuxin", "overwrite": True}
    )
    assert write_result["ok"] is True

    read_result = module.read_file({"path": "notes/hello.txt"})
    assert read_result["ok"] is True
    assert read_result["content"] == "hello yuxin"

    listing = module.list_directory({"path": ".", "recursive": True})
    assert listing["ok"] is True
    assert any(entry["name"] == "hello.txt" for entry in listing["entries"])


def test_system_access_skill_should_run_shell(monkeypatch, tmp_path):
    module = _load_module()
    monkeypatch.setenv("SYSTEM_ACCESS_WORKSPACE", str(tmp_path))

    result = module.execute_shell({"command": "echo hello", "timeout": 10})
    assert result["ok"] is True
    assert result["stdout"].strip() == "hello"


def test_system_access_skill_should_block_path_escape(monkeypatch, tmp_path):
    module = _load_module()
    monkeypatch.setenv("SYSTEM_ACCESS_WORKSPACE", str(tmp_path))

    result = module.read_file({"path": "../outside.txt"})
    assert result["ok"] is False
    assert "超出工作区" in result["error"]
