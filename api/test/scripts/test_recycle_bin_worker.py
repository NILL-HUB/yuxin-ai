import os

from scripts.os_automation_worker import (
    _file_operation,
    _list_recycle,
    _purge_recycle,
    _read_recycle_manifest,
    _restore_recycle,
    _rewrite_recycle_manifest,
    _safe_delete,
)


def _delete_payload(root, paths, **kwargs):
    payload = {"paths": paths, "safe_root": str(root)}
    payload.update(kwargs)
    return payload


def test_safe_delete_moves_to_recycle_and_restores(tmp_path, monkeypatch):
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    target = tmp_path / "notes.txt"
    target.write_text("hello", encoding="utf-8")

    deleted = _safe_delete(_delete_payload(tmp_path, [str(target)], task_id="task-1", reason="清理"))

    assert deleted["ok"] is True
    assert len(deleted["entries"]) == 1
    entry = deleted["entries"][0]
    assert entry["original_path"] == str(target)
    assert entry["task_id"] == "task-1"
    assert entry["recycle_root"] == str(tmp_path / ".yujianwo_recycle")
    assert entry["safe_root"] == str(tmp_path)
    assert target.exists() is False
    assert os.path.exists(entry["moved_to"]) is True

    listed = _list_recycle({"safe_root": str(tmp_path), "keyword": "notes"})
    assert listed["count"] == 1

    restored = _restore_recycle({"safe_root": str(tmp_path), "entry_id": entry["entry_id"]})
    assert restored["ok"] is True
    assert target.read_text(encoding="utf-8") == "hello"
    assert _list_recycle({"safe_root": str(tmp_path)})["count"] == 0


def test_safe_delete_rejects_path_outside_root(tmp_path, monkeypatch):
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    result = _safe_delete(_delete_payload(tmp_path, [str(outside)]))

    assert result["ok"] is False
    assert result["errors"]
    assert outside.exists() is True


def test_restore_adds_suffix_when_destination_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    target = tmp_path / "report.md"
    target.write_text("old", encoding="utf-8")
    deleted = _safe_delete(_delete_payload(tmp_path, [str(target)]))
    entry = deleted["entries"][0]
    target.write_text("new", encoding="utf-8")

    restored = _restore_recycle({"safe_root": str(tmp_path), "entry_id": entry["entry_id"]})

    assert restored["ok"] is True
    assert restored["restored_to"] != str(target)
    assert target.read_text(encoding="utf-8") == "new"
    assert os.path.exists(restored["restored_to"]) is True


def test_restore_all_by_task_id(tmp_path, monkeypatch):
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    deleted = _safe_delete(
        _delete_payload(tmp_path, [str(first), str(second)], task_id="task-batch")
    )
    assert deleted["ok"] is True

    restored = _restore_recycle({"safe_root": str(tmp_path), "task_id": "task-batch"})

    assert restored["ok"] is True
    assert len(restored["restored"]) == 2
    assert restored["errors"] == []
    assert first.read_text(encoding="utf-8") == "a"
    assert second.read_text(encoding="utf-8") == "b"
    assert _list_recycle({"safe_root": str(tmp_path)})["count"] == 0


def test_restore_all_by_task_id_reports_partial_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    good = tmp_path / "good.txt"
    bad = tmp_path / "bad.txt"
    good.write_text("g", encoding="utf-8")
    bad.write_text("b", encoding="utf-8")

    deleted = _safe_delete(
        _delete_payload(tmp_path, [str(good), str(bad)], task_id="task-partial")
    )
    entries = {entry["original_path"]: entry for entry in deleted["entries"]}
    os.remove(entries[str(bad)]["moved_to"])

    restored = _restore_recycle({"safe_root": str(tmp_path), "task_id": "task-partial"})

    assert restored["ok"] is False
    assert len(restored["restored"]) == 1
    assert len(restored["errors"]) == 1
    assert good.read_text(encoding="utf-8") == "g"


def test_purge_recycle_removes_expired_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    expired = tmp_path / "expired.txt"
    kept = tmp_path / "kept.txt"
    expired.write_text("e", encoding="utf-8")
    kept.write_text("k", encoding="utf-8")

    deleted = _safe_delete(
        _delete_payload(tmp_path, [str(expired), str(kept)], retention_days=30)
    )
    entries = _read_recycle_manifest(str(tmp_path))
    for entry in entries:
        if entry["original_path"] == str(expired):
            entry["expire_at"] = -1
    _rewrite_recycle_manifest(str(tmp_path), entries)

    purged = _purge_recycle({"safe_root": str(tmp_path)})

    assert purged["ok"] is True
    assert len(purged["purged"]) == 1
    assert purged["purged"][0]["original_path"] == str(expired)
    assert expired.exists() is False
    assert (tmp_path / ".yujianwo_recycle" / "kept.txt").exists() is True
    assert _list_recycle({"safe_root": str(tmp_path)})["count"] == 1


def test_purge_recycle_precise_by_entry_id(tmp_path, monkeypatch):
    """平台回收站到期销毁应能按 entry_id 精确清理，不影响其他条目（含未到期）。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")

    deleted = _safe_delete(_delete_payload(tmp_path, [str(first), str(second)], retention_days=30))
    entries = _read_recycle_manifest(str(tmp_path))
    target_entry = next(e for e in entries if e["original_path"] == str(first))

    purged = _purge_recycle(
        {"safe_root": str(tmp_path), "entry_id": target_entry["entry_id"]}
    )

    assert purged["ok"] is True
    assert len(purged["purged"]) == 1
    assert purged["purged"][0]["original_path"] == str(first)
    assert first.exists() is False
    # 未指定条目的文件仍在（即使未到期也保留）
    assert second.exists() is False
    recycle_file = list((tmp_path / ".yujianwo_recycle").rglob("b.txt"))
    assert len(recycle_file) == 1
    assert _list_recycle({"safe_root": str(tmp_path)})["count"] == 1


def test_purge_by_recorded_safe_root_clears_subdir_file(tmp_path, monkeypatch):
    """端到端 delete→记录→purge：purge 必须用记录里的 safe_root 作为清单基点。

    场景 = working_dir 为 <safe_root>/project 子目录的 V4A Delete：文件移入
    <safe_root>/.yujianwo_recycle（manifest 在 safe_root 级）。平台到期销毁时
    若误把 recycle_root（回收站目录本身）当 safe_root 传给 worker，会在
    <recycle_root>/.yujianwo_recycle 下找清单而定位失败（潜伏 bug 回归）；
    修复后 purge 携带删除时记录的 safe_root，能精确清掉本机回收站文件。
    """
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.delenv("OS_AUTOMATION_SNAPSHOT_DIR", raising=False)
    project = tmp_path / "project"
    project.mkdir()
    victim = project / "victim.txt"
    victim.write_text("doomed", encoding="utf-8")
    delete_patch = (
        "*** Begin Patch\n"
        f"*** Delete File: {victim}\n"
        "*** End Patch\n"
    )

    applied = _file_operation(
        {
            "op": "patch",
            "mode": "apply",
            "patch": delete_patch,
            "working_dir": str(project),
        }
    )
    assert applied["ok"] is True
    assert victim.exists() is False

    entries = _read_recycle_manifest(str(tmp_path))
    assert len(entries) == 1
    entry = entries[0]
    # manifest 落在 safe_root 级；entry 记录真实回收站根与清单基点
    assert entry["original_path"] == str(victim)
    assert entry["recycle_root"] == str(tmp_path / ".yujianwo_recycle")
    assert entry["safe_root"] == str(tmp_path)
    assert not (project / ".yujianwo_recycle").exists()

    # 回归：把 recycle_root 当 safe_root 传给 purge 找不到清单（条目仍在）
    wrong_root = _purge_recycle(
        {"safe_root": entry["recycle_root"], "entry_id": entry["entry_id"]}
    )
    assert wrong_root["ok"] is True
    assert wrong_root["purged"] == []
    assert (tmp_path / ".yujianwo_recycle" / "project" / "victim.txt").exists()

    # 修复路径：传记录中的原始 safe_root → 精确清理成功
    purged = _purge_recycle(
        {"safe_root": entry["safe_root"], "entry_id": entry["entry_id"]}
    )
    assert purged["ok"] is True
    assert len(purged["purged"]) == 1
    assert purged["purged"][0]["entry_id"] == entry["entry_id"]
    assert not (tmp_path / ".yujianwo_recycle" / "project" / "victim.txt").exists()
    assert _list_recycle({"safe_root": str(tmp_path)})["count"] == 0


def test_delete_records_device_info(tmp_path, monkeypatch):
    """删除清单条目应记录设备信息（名称取系统用户名，IP 支持环境变量覆盖）。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.setenv("OS_AUTOMATION_DEVICE_NAME", "alice")
    monkeypatch.setenv("OS_AUTOMATION_DEVICE_IP", "192.168.1.10")
    target = tmp_path / "secret.txt"
    target.write_text("s", encoding="utf-8")

    deleted = _safe_delete(_delete_payload(tmp_path, [str(target)]))

    assert deleted["ok"] is True
    assert deleted["entries"][0]["device_info"] == {"ip": "192.168.1.10", "name": "alice"}


def test_restore_same_device_has_no_mismatch_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.setenv("OS_AUTOMATION_DEVICE_NAME", "alice")
    monkeypatch.setenv("OS_AUTOMATION_DEVICE_IP", "192.168.1.10")
    target = tmp_path / "same.txt"
    target.write_text("s", encoding="utf-8")
    deleted = _safe_delete(_delete_payload(tmp_path, [str(target)]))
    entry = deleted["entries"][0]

    restored = _restore_recycle(
        {"safe_root": str(tmp_path), "entry_id": entry["entry_id"], "check_device": True}
    )

    assert restored["ok"] is True
    assert target.read_text(encoding="utf-8") == "s"


def test_restore_rejects_device_mismatch_and_confirms(tmp_path, monkeypatch):
    """设备 A 删除、设备 B 恢复：check_device 时返回 device_mismatch，确认后可恢复。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    monkeypatch.setenv("OS_AUTOMATION_DEVICE_NAME", "alice")
    monkeypatch.setenv("OS_AUTOMATION_DEVICE_IP", "192.168.1.10")
    target = tmp_path / "secret.txt"
    target.write_text("s", encoding="utf-8")
    deleted = _safe_delete(_delete_payload(tmp_path, [str(target)]))
    entry = deleted["entries"][0]

    # 设备 B 恢复 → 拒绝并返回两侧设备信息
    monkeypatch.setenv("OS_AUTOMATION_DEVICE_NAME", "bob")
    monkeypatch.setenv("OS_AUTOMATION_DEVICE_IP", "192.168.1.20")
    blocked = _restore_recycle(
        {"safe_root": str(tmp_path), "entry_id": entry["entry_id"], "check_device": True}
    )
    assert blocked["ok"] is False
    assert blocked["code"] == "device_mismatch"
    assert blocked["recorded_device"] == {"ip": "192.168.1.10", "name": "alice"}
    assert blocked["current_device"] == {"ip": "192.168.1.20", "name": "bob"}
    assert target.exists() is False

    # 用户确认后恢复成功
    restored = _restore_recycle(
        {
            "safe_root": str(tmp_path),
            "entry_id": entry["entry_id"],
            "check_device": True,
            "confirm_device_mismatch": True,
        }
    )
    assert restored["ok"] is True
    assert target.read_text(encoding="utf-8") == "s"


def test_restore_to_custom_path(tmp_path, monkeypatch):
    """自选路径恢复：恢复到用户指定目录，而非原路径。"""
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    target = tmp_path / "a.txt"
    target.write_text("a", encoding="utf-8")
    deleted = _safe_delete(_delete_payload(tmp_path, [str(target)]))
    entry = deleted["entries"][0]

    dest = tmp_path / "custom" / "a.txt"
    restored = _restore_recycle(
        {"safe_root": str(tmp_path), "entry_id": entry["entry_id"], "target_path": str(dest)}
    )

    assert restored["ok"] is True
    assert restored["restored_to"] == str(dest)
    assert dest.read_text(encoding="utf-8") == "a"
    assert target.exists() is False


def test_restore_custom_path_outside_root_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("OS_AUTOMATION_SAFE_ROOT", str(tmp_path))
    target = tmp_path / "a.txt"
    target.write_text("a", encoding="utf-8")
    deleted = _safe_delete(_delete_payload(tmp_path, [str(target)]))
    entry = deleted["entries"][0]

    outside = tmp_path.parent / "outside.txt"
    restored = _restore_recycle(
        {"safe_root": str(tmp_path), "entry_id": entry["entry_id"], "target_path": str(outside)}
    )

    assert restored["ok"] is False
    assert "超出允许目录" in restored["error"]
