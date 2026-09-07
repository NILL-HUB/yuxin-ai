import pytest

from scripts.os_automation_worker import (
    _approvals,
    _create_approval,
    _file_apply_patch,
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


def test_file_patch_preview_does_not_modify_files(tmp_path, monkeypatch):
    """preview 必须真只读：不写盘、不删文件、不移入回收站（B1 安全回归）。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    target = tmp_path / "code.py"
    original = "def old():\n    pass\n"
    target.write_text(original, encoding="utf-8")
    update_patch = (
        "*** Begin Patch\n"
        f"*** Update File: {target}\n@@\n"
        "-def old():\n+def new():\n     pass\n"
        "*** End Patch\n"
    )

    preview = _file_operation(
        {
            "op": "patch",
            "mode": "preview",
            "patch": update_patch,
            "working_dir": str(tmp_path),
        }
    )

    assert preview["ok"] is True
    assert preview["validation"]["dry_run"] is True
    # 关键断言：preview 后目标文件内容必须原封不动
    assert target.read_text(encoding="utf-8") == original

    delete_target = tmp_path / "victim.txt"
    delete_target.write_text("doomed", encoding="utf-8")
    delete_patch = (
        "*** Begin Patch\n"
        f"*** Delete File: {delete_target}\n"
        "*** End Patch\n"
    )

    delete_preview = _file_operation(
        {
            "op": "patch",
            "mode": "preview",
            "patch": delete_patch,
            "working_dir": str(tmp_path),
        }
    )

    assert delete_preview["ok"] is True
    # 关键断言：preview 一个 DELETE 后，文件仍在（不得移入回收站）
    assert delete_target.exists() is True
    assert delete_target.read_text(encoding="utf-8") == "doomed"
    recycle_dir = tmp_path / ".yuxin_ai_recycle"
    assert not recycle_dir.exists() or not any(recycle_dir.rglob("victim.txt"))


def test_file_apply_patch_dry_run_is_read_only(tmp_path):
    """_file_apply_patch(dry_run=True) 模拟 ADD/UPDATE/MOVE/DELETE 但完全不触碰真实文件。"""
    target = tmp_path / "code.py"
    original = "def old():\n    pass\n"
    target.write_text(original, encoding="utf-8")
    to_delete = tmp_path / "junk.txt"
    to_delete.write_text("trash", encoding="utf-8")
    patch = (
        "*** Begin Patch\n"
        f"*** Update File: {target}\n@@\n"
        "-def old():\n+def new():\n     pass\n"
        f"*** Delete File: {to_delete}\n"
        f"*** Add File: {tmp_path / 'created.txt'}\n+hello\n"
        f"*** Move File: {tmp_path / 'a.txt'} -> {tmp_path / 'sub' / 'b.txt'}\n"
        "*** End Patch\n"
    )
    moved_src = tmp_path / "a.txt"
    moved_src.write_text("mv", encoding="utf-8")

    result = _file_apply_patch(patch, str(tmp_path), str(tmp_path), dry_run=True)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert target.read_text(encoding="utf-8") == original
    assert to_delete.exists() is True
    assert not (tmp_path / "created.txt").exists()
    assert moved_src.exists() is True
    assert not (tmp_path / "sub" / "b.txt").exists()
    recycle_dir = tmp_path / ".yuxin_ai_recycle"
    assert not recycle_dir.exists() or not any(recycle_dir.rglob("junk.txt"))


def test_file_apply_patch_dry_run_rejects_escaping_path(tmp_path):
    """dry_run 也做路径逃逸校验，越界路径在预览阶段即被拒绝且不落盘。"""
    outside = tmp_path.parent / "evil_dry_run.txt"
    patch = (
        "*** Begin Patch\n"
        f"*** Add File: {outside}\n+evil\n"
        "*** End Patch\n"
    )

    result = _file_apply_patch(patch, str(tmp_path), str(tmp_path), dry_run=True)

    assert result["ok"] is False
    assert "超出允许目录" in result["error"]
    assert outside.exists() is False


def test_file_patch_dry_run_rejects_parent_traversal(tmp_path):
    """dry-run 与 apply 口径一致：含 .. 段的越界路径在 preview 阶段即被拒绝。

    镜像复制/映射若用词法 relative_to 归一化，会把 root/../sibling/... 错当
    树内路径：UPDATE 静默读越界文件进副本、MOVE 假报“源不存在”，而真实
    apply 一律 resolve 后拒绝。此处要求 dry-run 对 UPDATE/DELETE/MOVE 的
    越界源路径全部返回 ok:False，绝不复制越界内容进副本。
    """
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    victim = sibling / "victim.txt"
    victim.write_text("OLD outside\n", encoding="utf-8")

    traversal = f"{tmp_path / 'root'}/../sibling/victim.txt"
    update_patch = (
        "*** Begin Patch\n"
        f"*** Update File: {traversal}\n@@\n"
        "-OLD outside\n+NEW outside\n"
        "*** End Patch\n"
    )
    update_dry = _file_apply_patch(update_patch, str(tmp_path / "root"), str(tmp_path / "root"), dry_run=True)
    assert update_dry["ok"] is False
    assert "超出允许目录" in update_dry["error"]

    delete_patch = (
        "*** Begin Patch\n"
        f"*** Delete File: {traversal}\n"
        "*** End Patch\n"
    )
    delete_dry = _file_apply_patch(delete_patch, str(tmp_path / "root"), str(tmp_path / "root"), dry_run=True)
    assert delete_dry["ok"] is False
    assert "超出允许目录" in delete_dry["error"]

    move_patch = (
        "*** Begin Patch\n"
        f"*** Move File: {traversal} -> {tmp_path / 'root' / 'moved.txt'}\n"
        "*** End Patch\n"
    )
    move_dry = _file_apply_patch(move_patch, str(tmp_path / "root"), str(tmp_path / "root"), dry_run=True)
    assert move_dry["ok"] is False
    assert "超出允许目录" in move_dry["error"]

    assert victim.read_text(encoding="utf-8") == "OLD outside\n"
    assert not (tmp_path / "root" / "moved.txt").exists()


def test_file_patch_apply_pure_delete_still_moves_to_recycle(tmp_path, monkeypatch):
    """纯删除豁免保留：apply DELETE 不需要 token 且真实移入回收站（preview 则不动）。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    target = tmp_path / "victim.txt"
    target.write_text("doomed", encoding="utf-8")
    delete_patch = (
        "*** Begin Patch\n"
        f"*** Delete File: {target}\n"
        "*** End Patch\n"
    )

    preview = _file_operation(
        {
            "op": "patch",
            "mode": "preview",
            "patch": delete_patch,
            "working_dir": str(tmp_path),
        }
    )

    assert preview["ok"] is True
    assert target.exists() is True

    applied = _file_operation(
        {
            "op": "patch",
            "mode": "apply",
            "patch": delete_patch,
            "working_dir": str(tmp_path),
        }
    )

    assert applied["ok"] is True
    assert target.exists() is False
    recycle_dir = tmp_path / ".yuxin_ai_recycle"
    assert any(recycle_dir.rglob("victim.txt"))


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

