import json
import time
from pathlib import Path

import pytest

from scripts.os_automation_worker import (
    _approvals,
    _create_approval,
    _file_apply_patch,
    _file_operation,
    _file_search,
    _gc_snapshots,
    _list_snapshots,
    _read_snapshot_manifest,
    _resolve_safe_root,
    _rollback_file,
    _rollback_turn,
    _snapshot_root,
)


def _update_patch(path, old_line, new_line):
    return (
        "*** Begin Patch\n"
        f"*** Update File: {path}\n@@\n"
        f"-{old_line}\n+{new_line}\n"
        "*** End Patch\n"
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


def test_file_patch_preview_then_apply(tmp_path, monkeypatch):
    """preview 只读校验后可选择 dry-run 预检查；apply 直接执行无需 approval_token。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.delenv("OS_AUTOMATION_SNAPSHOT_DIR", raising=False)
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
    assert preview["validation"]["dry_run"] is True
    # preview 不落盘
    assert target.read_text(encoding="utf-8") == "def old():\n    pass\n"

    applied = _file_operation(
        {
            "op": "patch",
            "mode": "apply",
            "patch": patch,
            "working_dir": str(tmp_path),
        }
    )

    assert applied["ok"] is True
    assert target.read_text(encoding="utf-8") == "def new():\n    pass\n"
    # apply 前自动生成写前快照（回滚兜底）
    assert applied.get("snapshot_batch_id")


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
    recycle_dir = tmp_path / ".yujianwo_recycle"
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
    recycle_dir = tmp_path / ".yujianwo_recycle"
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
    """apply DELETE 全自动执行：无需 token，真实移入回收站（preview 则不动）。"""
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
    recycle_dir = tmp_path / ".yujianwo_recycle"
    assert any(recycle_dir.rglob("victim.txt"))


def test_file_patch_apply_without_token_executes_directly(tmp_path, monkeypatch):
    """apply 不再要求 approval_token：直接执行成功，且写前自动生成快照。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.delenv("OS_AUTOMATION_SNAPSHOT_DIR", raising=False)
    target = tmp_path / "code.py"
    target.write_text("def old():\n    pass\n", encoding="utf-8")
    patch = (
        "*** Begin Patch\n"
        f"*** Update File: {target}\n@@\n"
        "-def old():\n+def new():\n     pass\n"
        "*** End Patch\n"
    )

    result = _file_operation(
        {
            "op": "patch",
            "mode": "apply",
            "patch": patch,
            "working_dir": str(tmp_path),
        }
    )

    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == "def new():\n    pass\n"
    # apply 直接执行，且写前自动生成快照（改错可回滚）
    assert result.get("snapshot_batch_id")
    entries = _read_snapshot_manifest(str(tmp_path))
    assert any(e["path"] == str(target) for e in entries)


def test_file_patch_blocks_path_escape(tmp_path, monkeypatch):
    """越界 ADD 路径必须被拒绝；SAFE_ROOT 显式限定在 tmp_path 内。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
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


def _snapshot_dir_of(tmp_path):
    return _snapshot_root(str(tmp_path))


def _apply_patch(tmp_path, target, old_line, new_line):
    patch = _update_patch(target, old_line, new_line)
    return _file_apply_patch(
        patch,
        str(tmp_path),
        str(tmp_path),
        snapshot_meta={
            "source": "os_file_task",
            "session_id": "sess-1",
            "conversation_turn": "turn-1",
        },
    )


def test_snapshot_before_update_patch(tmp_path, monkeypatch):
    """UPDATE patch 前自动捕获原内容：manifest 有条目且 .snap 内容=原内容。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.delenv("OS_AUTOMATION_SNAPSHOT_DIR", raising=False)
    target = tmp_path / "code.py"
    original = "def old():\n    pass\n"
    target.write_bytes(original.encode("utf-8"))
    original_bytes = target.read_bytes()

    result = _apply_patch(tmp_path, target, "def old():", "def new():")

    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == "def new():\n    pass\n"

    entries = _read_snapshot_manifest(str(tmp_path))
    matches = [e for e in entries if str(e.get("path")) == str(target)]
    assert len(matches) == 1
    entry = matches[0]
    assert entry["conversation_turn"] == "turn-1"
    assert entry["taken_before"] == "patch"
    snap_file = _snapshot_dir_of(tmp_path) / "files" / f"{entry['content_sha256']}.snap"
    assert snap_file.is_file()
    assert snap_file.read_bytes() == original_bytes
    assert entry["rolled_back"] is False


def test_rollback_file_restores_content(tmp_path, monkeypatch):
    """patch 修改后 rollback_file(path) 恢复原内容；再 rollback 报无可用快照。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.delenv("OS_AUTOMATION_SNAPSHOT_DIR", raising=False)
    target = tmp_path / "code.py"
    target.write_text("def old():\n    pass\n", encoding="utf-8")

    _apply_patch(tmp_path, target, "def old():", "def new():")
    assert target.read_text(encoding="utf-8") == "def new():\n    pass\n"

    rb = _rollback_file({"path": str(target), "working_dir": str(tmp_path)})
    assert rb["ok"] is True
    assert target.read_text(encoding="utf-8") == "def old():\n    pass\n"
    entries = _read_snapshot_manifest(str(tmp_path))
    assert any(
        e.get("rolled_back") and str(e.get("path")) == str(target) for e in entries
    )

    rb2 = _rollback_file({"path": str(target), "working_dir": str(tmp_path)})
    assert rb2["ok"] is False
    assert "无可用快照" in rb2["error"]


def test_rollback_turn_restores_all_files(tmp_path, monkeypatch):
    """同一 turn 内 patch 两个文件后 rollback_turn 同时恢复两者。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.delenv("OS_AUTOMATION_SNAPSHOT_DIR", raising=False)
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("aaa old\n", encoding="utf-8")
    b.write_text("bbb old\n", encoding="utf-8")

    patch = (
        "*** Begin Patch\n"
        f"*** Update File: {a}\n@@\n-aaa old\n+aaa new\n"
        f"*** Update File: {b}\n@@\n-bbb old\n+bbb new\n"
        "*** End Patch\n"
    )
    result = _file_apply_patch(
        patch,
        str(tmp_path),
        str(tmp_path),
        snapshot_meta={"conversation_turn": "turn-x"},
    )
    assert result["ok"] is True
    assert a.read_text(encoding="utf-8") == "aaa new\n"
    assert b.read_text(encoding="utf-8") == "bbb new\n"

    rb = _rollback_turn({"conversation_turn": "turn-x", "working_dir": str(tmp_path)})
    assert rb["ok"] is True
    assert rb["count"] == 2
    assert a.read_text(encoding="utf-8") == "aaa old\n"
    assert b.read_text(encoding="utf-8") == "bbb old\n"


def test_rollback_file_specific_snapshot_id(tmp_path, monkeypatch):
    """多次 patch 后可精确回滚到指定 snapshot_id 的历史版本。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.delenv("OS_AUTOMATION_SNAPSHOT_DIR", raising=False)
    target = tmp_path / "code.py"
    target.write_text("v0\n", encoding="utf-8")

    _apply_patch(tmp_path, target, "v0", "v1")
    _apply_patch(tmp_path, target, "v1", "v2")
    assert target.read_text(encoding="utf-8") == "v2\n"

    entries = [e for e in _read_snapshot_manifest(str(tmp_path)) if str(e.get("path")) == str(target)]
    assert len(entries) == 2
    first_id = entries[0]["snapshot_id"]

    rb = _rollback_file(
        {"path": str(target), "snapshot_id": first_id, "working_dir": str(tmp_path)}
    )
    assert rb["ok"] is True
    assert target.read_text(encoding="utf-8") == "v0\n"


def test_list_snapshots_returns_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.delenv("OS_AUTOMATION_SNAPSHOT_DIR", raising=False)
    target = tmp_path / "code.py"
    target.write_text("old\n", encoding="utf-8")
    _apply_patch(tmp_path, target, "old", "new")

    listing = _list_snapshots({"working_dir": str(tmp_path)})
    assert listing["ok"] is True
    assert listing["count"] == 1
    entry = listing["entries"][0]
    assert entry["path"] == str(target)
    assert entry["conversation_turn"] == "turn-1"
    assert entry["rolled_back"] is False
    # 元数据不返回内容
    assert "content" not in entry


def test_snapshot_before_delete_and_rollback(tmp_path, monkeypatch):
    """DELETE 前快照源文件，回滚后文件恢复到原路径原内容。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.delenv("OS_AUTOMATION_SNAPSHOT_DIR", raising=False)
    target = tmp_path / "victim.txt"
    original = "doomed content\n"
    target.write_text(original, encoding="utf-8")
    delete_patch = (
        "*** Begin Patch\n"
        f"*** Delete File: {target}\n"
        "*** End Patch\n"
    )

    result = _file_apply_patch(
        delete_patch,
        str(tmp_path),
        str(tmp_path),
        snapshot_meta={"conversation_turn": "turn-del"},
    )
    assert result["ok"] is True
    assert target.exists() is False

    rb = _rollback_file({"path": str(target), "working_dir": str(tmp_path)})
    assert rb["ok"] is True
    assert target.exists() is True
    assert target.read_text(encoding="utf-8") == original


def test_gc_snapshots_purges_expired(tmp_path, monkeypatch):
    """把条目 created_at 改旧后触发 GC，条目与 .snap 文件都被清理。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.delenv("OS_AUTOMATION_SNAPSHOT_DIR", raising=False)
    monkeypatch.setenv("OS_AUTOMATION_SNAPSHOT_RETENTION_DAYS", "7")
    target = tmp_path / "code.py"
    target.write_text("old\n", encoding="utf-8")
    _apply_patch(tmp_path, target, "old", "new")

    entries = _read_snapshot_manifest(str(tmp_path))
    assert entries
    snap_file = _snapshot_dir_of(tmp_path) / "files" / f"{entries[0]['content_sha256']}.snap"
    assert snap_file.is_file()

    # 改写 created_at 为 8 天前
    manifest_path = _snapshot_dir_of(tmp_path) / "manifest.jsonl"
    old_ts = time.time() - 8 * 86400
    with manifest_path.open("r", encoding="utf-8") as handle:
        lines = handle.readlines()
    rewritten = []
    for line in lines:
        obj = json.loads(line)
        obj["created_at"] = old_ts
        rewritten.append(json.dumps(obj, ensure_ascii=False))
    manifest_path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")

    result = _gc_snapshots(str(tmp_path))
    assert result["ok"] is True
    assert len(result["purged"]) == 1
    assert _read_snapshot_manifest(str(tmp_path)) == []
    assert snap_file.exists() is False


def test_oversized_file_snapshot_skipped_with_warning(tmp_path, monkeypatch):
    """超过 OS_AUTOMATION_SNAPSHOT_MAX_BYTES 的文件跳过内容快照但 patch 不被阻断。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.delenv("OS_AUTOMATION_SNAPSHOT_DIR", raising=False)
    monkeypatch.setenv("OS_AUTOMATION_SNAPSHOT_MAX_BYTES", "10")
    target = tmp_path / "big.txt"
    target.write_text("0123456789abcdef", encoding="utf-8")

    patch = _update_patch(target, "0123456789abcdef", "fedcba9876543210")
    result = _file_apply_patch(
        patch,
        str(tmp_path),
        str(tmp_path),
        snapshot_meta={"conversation_turn": "turn-big"},
    )
    assert result["ok"] is True
    assert target.read_text(encoding="utf-8") == "fedcba9876543210"
    assert result.get("warnings"), "应返回超限 warning"
    assert any("超大文件快照" in w for w in result["warnings"])
    assert _read_snapshot_manifest(str(tmp_path)) == []


def test_patch_snapshot_and_rollback_use_safe_root_when_working_dir_is_subdir(tmp_path, monkeypatch):
    """快照基点统一回归：safe_root 与 working_dir 不同时，快照写与回滚读都落在 safe_root。

    working_dir 为 <safe_root>/project 子目录，_file_operation 的 patch apply 曾把
    working_dir 当 root 传给 _file_apply_patch，导致快照 manifest 写到
    <working_dir>/.yujianwo_snapshots，而 rollback_file 用 _resolve_safe_root 读
    <safe_root>/.yujianwo_snapshots——基点错位，回滚永远找不到快照。修复后两处一致。
    """
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.delenv("OS_AUTOMATION_SNAPSHOT_DIR", raising=False)
    project = tmp_path / "project"
    project.mkdir()
    target = project / "code.py"
    original = "def old():\n    pass\n"
    target.write_text(original, encoding="utf-8")
    patch = (
        "*** Begin Patch\n"
        f"*** Update File: {target}\n@@\n"
        "-def old():\n+def new():\n     pass\n"
        "*** End Patch\n"
    )

    # SAFE_ROOT=tmp_path、working_dir=project 子目录；apply 直接执行无需 token。
    applied = _file_operation(
        {
            "op": "patch",
            "mode": "apply",
            "patch": patch,
            "working_dir": str(project),
            "session_id": "sess-root",
            "conversation_turn": "turn-root",
        }
    )
    assert applied["ok"] is True
    assert applied.get("snapshot_batch_id")
    assert target.read_text(encoding="utf-8") == "def new():\n    pass\n"

    # 快照 manifest 必须落在 safe_root 级，而不是 working_dir 子目录
    safe_entries = _read_snapshot_manifest(str(tmp_path))
    assert len(safe_entries) == 1
    assert safe_entries[0]["session_id"] == "sess-root"
    assert safe_entries[0]["conversation_turn"] == "turn-root"
    assert not (project / ".yujianwo_snapshots").exists()

    rb = _rollback_file({"path": str(target), "working_dir": str(project)})
    assert rb["ok"] is True
    assert target.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# 敏感路径读黑名单：read/search 命中敏感路径（凭据/密钥/浏览器数据）直接拒绝
# ---------------------------------------------------------------------------
def test_file_read_rejects_sensitive_env_file(tmp_path, monkeypatch):
    """读取 .env 密钥文件必须被拒绝（免确认放开写删后读敏感面由黑名单兜底）。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    target = tmp_path / ".env"
    target.write_text("OPENAI_API_KEY=sk-xxx\n", encoding="utf-8")

    result = _file_operation(
        {
            "op": "read",
            "path": str(target),
            "working_dir": str(tmp_path),
        }
    )

    assert result["ok"] is False
    assert "敏感" in result["error"]
    assert ".env" in result["error"]


def test_file_read_rejects_env_example_allowed(tmp_path, monkeypatch):
    """.env.example 属公开模板，不拦；真 .env 仍拒。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    example = tmp_path / ".env.example"
    example.write_text("OPENAI_API_KEY=your-key\n", encoding="utf-8")

    ok = _file_operation(
        {"op": "read", "path": str(example), "working_dir": str(tmp_path)}
    )
    assert ok["ok"] is True

    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-xxx\n", encoding="utf-8")
    blocked = _file_operation(
        {"op": "read", "path": str(env), "working_dir": str(tmp_path)}
    )
    assert blocked["ok"] is False


def test_file_read_rejects_ssh_key_path(tmp_path, monkeypatch):
    """读取 ~/.ssh/id_rsa 形态路径必须被拒（按路径段+文件名双重命中）。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    key = ssh_dir / "id_rsa"
    key.write_text("PRIVATE KEY MATERIAL\n", encoding="utf-8")

    result = _file_operation(
        {
            "op": "read",
            "path": str(key),
            "working_dir": str(tmp_path),
        }
    )

    assert result["ok"] is False
    assert "敏感" in result["error"]


def test_file_read_rejects_browser_credential_path(tmp_path, monkeypatch):
    """读取浏览器凭据目录（user data/login data）必须被拒。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    profile = tmp_path / "Chrome" / "User Data" / "Default"
    profile.mkdir(parents=True)
    cred = profile / "Login Data"
    cred.write_text("sqlite-binary", encoding="utf-8")

    result = _file_operation(
        {
            "op": "read",
            "path": str(cred),
            "working_dir": str(tmp_path),
        }
    )

    assert result["ok"] is False
    assert "敏感" in result["error"]


def test_file_read_rejects_recycle_and_snapshot_managed_dirs(tmp_path, monkeypatch):
    """回收站/快照自管目录不可读：防止绕过恢复链路直接读被删/历史内容。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    recycle = tmp_path / ".yujianwo_recycle"
    recycle.mkdir()
    victim = recycle / "notes.txt"
    victim.write_text("old content", encoding="utf-8")

    blocked = _file_operation(
        {"op": "read", "path": str(victim), "working_dir": str(tmp_path)}
    )
    assert blocked["ok"] is False
    assert "敏感" in blocked["error"]


def test_file_read_normal_file_unaffected_by_blacklist(tmp_path, monkeypatch):
    """非敏感普通源码/配置读取不受影响。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    normal = tmp_path / "project" / "config.py"
    normal.parent.mkdir()
    normal.write_text("API_HOST = 'localhost'\n", encoding="utf-8")

    result = _file_operation(
        {"op": "read", "path": str(normal), "working_dir": str(tmp_path)}
    )

    assert result["ok"] is True
    assert "API_HOST" in result["content"]


def test_file_search_rejects_sensitive_scope(tmp_path, monkeypatch):
    """search 搜索目标自身位于敏感目录时直接拒绝（无需 rg 也可回归）。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    key = ssh_dir / "id_rsa"
    key.write_text("PRIVATE KEY\n", encoding="utf-8")

    by_file = _file_search("KEY", str(tmp_path), str(tmp_path), path=str(key))
    assert by_file["ok"] is False
    assert "敏感" in by_file["error"]

    by_dir = _file_search("KEY", str(tmp_path), str(tmp_path), path=str(ssh_dir))
    assert by_dir["ok"] is False
    assert "敏感" in by_dir["error"]


def test_file_search_adds_sensitive_exclusion_globs(tmp_path, monkeypatch):
    """search 的 rg 命令必须携带敏感排除 glob（.ssh/.env 等不参与内容搜索）。"""
    import subprocess

    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    called = {}

    class _FakeCompleted:
        stdout = b""

    def _fake_run(cmd, capture_output, timeout):
        called["cmd"] = cmd
        return _FakeCompleted()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    result = _file_operation({"op": "search", "pattern": "TODO", "working_dir": str(tmp_path)})

    assert result["ok"] is True
    cmd = called["cmd"]
    joined = " ".join(cmd)
    assert "!**/.ssh/**" in joined
    assert "!**/.env" in joined
    assert "!**/id_rsa" in joined


