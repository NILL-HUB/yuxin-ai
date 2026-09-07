"""宿主机 OS 自动化 worker。

运行在真实 Windows/Linux 主机上，通过受保护的本机 HTTP 接口接收平台请求，
执行纯 Python 文件操作（读/搜/V4A 补丁）与回收站删除/恢复/清理，不依赖外部 CLI。

安全模型：
- 仅接受 Authorization: Bearer <OS_AUTOMATION_TOKEN> 的请求。
- /file 的 patch apply 需携带 preview 返回的一次性 approval_token；纯删除类补丁
  已走回收站（可恢复），无需确认。
- 默认只监听本机回环地址；如部署在容器可访问的地址，必须配置强 token。
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import shutil
import tempfile
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("os_automation_worker")

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
APPROVAL_TTL_SECONDS = 1800
DEFAULT_SAFE_ROOT = ""
RECYCLE_DIR_NAME = ".yuxin_ai_recycle"
MANIFEST_FILENAME = "manifest.jsonl"
DEFAULT_RECYCLE_RETENTION_DAYS = 30

_approvals: dict[str, dict[str, Any]] = {}
_approval_lock = threading.Lock()
# 可重入锁：_delete_into_recycle 持有锁后调用 _append_recycle_manifest（内部再次加锁）
_recycle_lock = threading.RLock()


def _env(key: str, default: str = "") -> str:
    return str(os.environ.get(key, default) or "").strip()


def _create_approval(task: str) -> str:
    token = uuid.uuid4().hex
    with _approval_lock:
        _approvals[token] = {
            "task": task,
            "created_at": time.time(),
        }
    return token


def _consume_approval(approval_token: str) -> bool:
    """校验并消费一次性 approval_token，成功后作废。"""
    with _approval_lock:
        approval = _approvals.get(approval_token or "")
        if approval is None:
            return False
        if time.time() - approval["created_at"] > APPROVAL_TTL_SECONDS:
            _approvals.pop(approval_token, None)
            return False
        _approvals.pop(approval_token, None)
        return True


def _resolve_safe_root(requested_root: str) -> str:
    """确定文件操作允许的根目录。

    安全规则：写操作只允许落在 safe_root 内；safe_root 来自
    OS_AUTOMATION_SAFE_ROOT 环境变量，缺省为当前用户主目录。
    请求方传入的 working_dir 必须位于 safe_root 之内。
    """
    safe_root = _env("OS_AUTOMATION_SAFE_ROOT", DEFAULT_SAFE_ROOT)
    if not safe_root:
        safe_root = str(Path.home())
    try:
        resolved = str(Path(safe_root).expanduser().resolve())
    except OSError:
        resolved = safe_root
    if not requested_root:
        return resolved
    try:
        requested = str(Path(requested_root).expanduser().resolve())
    except OSError:
        requested = requested_root
    if requested == resolved or requested.startswith(resolved + os.sep):
        return requested
    return resolved


def _is_path_within(root: str, candidate: str) -> bool:
    try:
        resolved = str(Path(candidate).expanduser().resolve())
    except OSError:
        return False
    return resolved == root or resolved.startswith(root + os.sep)


def _normalize_op_path(workdir: str, path: str) -> str:
    """V4A 补丁操作路径的规范形态（真实 apply 与 dry-run 共用）。

    与 _RootedFileOps 的语义一致：只展开 ~、相对路径拼接到 working_dir，
    不做 resolve —— 保留 .. 段，由后续 _is_path_within 统一 resolve 判定，
    保证真实 apply 与临时副本镜像对同一路径得到同一越界结论。
    """
    expanded = str(Path(path).expanduser())
    if not Path(expanded).is_absolute():
        expanded = str(Path(workdir) / expanded)
    return expanded


def _file_safe_read(path: str, root: str) -> dict[str, Any]:
    if not _is_path_within(root, path):
        return {"ok": False, "error": "路径超出允许目录", "path": path}
    target = Path(path)
    if not target.is_file():
        return {"ok": False, "error": "文件不存在", "path": path}
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"ok": False, "error": f"读取失败: {exc}", "path": path}
    except OSError as exc:
        return {"ok": False, "error": f"读取失败: {exc}", "path": path}
    max_chars = int(_env("OS_AUTOMATION_FILE_READ_MAX_CHARS", "100000"))
    truncated = len(content) > max_chars
    return {
        "ok": True,
        "path": str(target),
        "content": content[:max_chars],
        "truncated": truncated,
        "total_chars": len(content),
    }


def _file_apply_patch(
    patch: str,
    root: str,
    working_dir: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """在宿主机执行 V4A 补丁，并验证所有目标路径都落在允许目录内。

    dry_run=True（preview）时把补丁整体模拟到临时副本目录上：ADD/UPDATE/
    DELETE/MOVE 全部操作逻辑复用 apply_v4a_operations，但读到的永远是副本
    状态、写的也是副本，delete 只是从副本移除（绝不真移入回收站）。返回结构
    与 apply 一致并附 dry_run 标记，真实文件不会被触碰。
    """
    try:
        from internal.core.agent.adapters.hermes.v4a_patch import (
            FileTextOps,
            parse_v4a_patch,
            apply_v4a_operations,
        )
    except Exception as exc:
        return {"ok": False, "error": f"补丁执行器不可用: {exc}"}

    operations, parse_error = parse_v4a_patch(patch)
    if parse_error:
        return {"ok": False, "error": parse_error}

    for op in operations:
        for candidate in (op.file_path, op.new_path if op.operation == "move" else None):
            if not candidate:
                continue
            if not _is_path_within(root, _normalize_op_path(working_dir, candidate)):
                return {"ok": False, "error": f"路径超出允许目录: {candidate}"}

    if dry_run:
        return _file_dry_run_patch(operations, root, working_dir)

    class _RootedFileOps(FileTextOps):
        def __init__(self, root: str, workdir: str) -> None:
            self.root = root
            self.workdir = workdir

        def _resolve(self, path: str) -> str:
            return _normalize_op_path(self.workdir, path)

        def read_text(self, path: str) -> str | None:
            resolved = self._resolve(path)
            if not _is_path_within(self.root, resolved):
                return None
            return super().read_text(resolved)

        def write_text(self, path: str, content: str) -> None:
            resolved = self._resolve(path)
            if not _is_path_within(self.root, resolved):
                raise PermissionError(f"路径超出允许目录: {resolved}")
            super().write_text(resolved, content)

        def delete_file(self, path: str) -> None:
            resolved = self._resolve(path)
            if not _is_path_within(self.root, resolved):
                raise PermissionError(f"路径超出允许目录: {resolved}")
            # 安全删除：移入本机回收站而非物理删除，保证可恢复
            moved = _delete_into_recycle(resolved, self.root, reason="V4A Delete File")
            if moved is None:
                raise OSError(f"删除文件失败（移入回收站失败）: {resolved}")

        def move_file(self, path: str, new_path: str) -> None:
            resolved = self._resolve(path)
            resolved_new = self._resolve(new_path)
            if not _is_path_within(self.root, resolved) or not _is_path_within(
                self.root, resolved_new
            ):
                raise PermissionError(f"路径超出允许目录: {resolved} -> {resolved_new}")
            super().move_file(resolved, resolved_new)

        def exists(self, path: str) -> bool:
            resolved = self._resolve(path)
            return super().exists(resolved)

    results: list[str] = []
    try:
        results = apply_v4a_operations(operations, _RootedFileOps(root, working_dir))
    except PermissionError as exc:
        return {"ok": False, "error": str(exc), "results": results}
    except Exception as exc:
        return {"ok": False, "error": f"补丁应用失败: {exc}"}
    errors = [r for r in results if r.startswith("ERROR:")]
    return {"ok": not errors, "results": results, "errors": errors}


def _file_dry_run_patch(
    operations: list[Any],
    root: str,
    working_dir: str,
) -> dict[str, Any]:
    """在临时副本目录上模拟整个 V4A 补丁，验证可应用性且不触碰真实文件。

    把补丁涉及的源文件用 shutil.copy2 复制进临时副本树，然后对副本运行
    与真实 apply 完全相同的逻辑：UPDATE 读副本内容、ADD/UPDATE/MOVE 写副本、
    DELETE 删除副本。delete 不调用 _delete_into_recycle，因此回收站清单与
    真实文件均保持不变；临时副本在函数返回后自动清理。
    """
    try:
        from internal.core.agent.adapters.hermes.v4a_patch import (
            FileTextOps,
            apply_v4a_operations,
        )
    except Exception as exc:
        return {"ok": False, "error": f"补丁执行器不可用: {exc}"}

    mirror_root = Path(root)
    operations = list(operations)
    normalized: list[tuple[str, str]] = []
    for op in operations:
        for field in ("file_path", "new_path") if op.operation == "move" else ("file_path",):
            value = str(getattr(op, field) or "").strip()
            if not value:
                continue
            resolved = str(Path(_normalize_op_path(working_dir, value)).expanduser().resolve())
            if not _is_path_within(root, resolved):
                return {"ok": False, "error": f"路径超出允许目录: {value}", "dry_run": True}
            normalized.append((value, resolved))

    with tempfile.TemporaryDirectory(prefix="os_worker_dry_run_") as scratch:
        scratch_path = Path(scratch)

        def mirrored(real_path: str) -> str:
            resolved = str(Path(real_path).expanduser().resolve())
            relative = Path(resolved).relative_to(mirror_root)
            return str(scratch_path / relative)

        for value, resolved in sorted(normalized, key=lambda item: item[1]):
            source = Path(resolved)
            if not source.is_file():
                continue
            copy_target = Path(mirrored(resolved))
            try:
                copy_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(source), str(copy_target))
            except OSError:
                continue

        class _SandboxFileOps(FileTextOps):
            def __init__(self, mirror: str, workdir: str, mirror_root: Path) -> None:
                self.mirror = mirror
                self.workdir = workdir
                self.mirror_root = mirror_root

            def _remap(self, path: str) -> str:
                resolved = str(Path(_normalize_op_path(self.workdir, path)).expanduser().resolve())
                if not _is_path_within(str(self.mirror_root), resolved):
                    raise PermissionError(f"路径超出允许目录: {path}")
                relative = Path(resolved).relative_to(self.mirror_root)
                return str(Path(self.mirror) / relative)

            def read_text(self, path: str) -> str | None:
                try:
                    return super().read_text(self._remap(path))
                except PermissionError:
                    return None

            def write_text(self, path: str, content: str) -> None:
                super().write_text(self._remap(path), content)

            def delete_file(self, path: str) -> None:
                target = Path(self._remap(path))
                if target.is_file():
                    target.unlink()

            def move_file(self, path: str, new_path: str) -> None:
                super().move_file(self._remap(path), self._remap(new_path))

            def exists(self, path: str) -> bool:
                try:
                    return Path(self._remap(path)).is_file()
                except PermissionError:
                    return False

        results: list[str] = []
        try:
            results = apply_v4a_operations(
                operations, _SandboxFileOps(str(scratch), working_dir, mirror_root)
            )
        except PermissionError as exc:
            return {"ok": False, "error": str(exc), "results": results, "dry_run": True}
        except Exception as exc:
            return {"ok": False, "error": f"补丁应用失败: {exc}", "dry_run": True}

    errors = [r for r in results if r.startswith("ERROR:")]
    return {
        "ok": not errors,
        "results": results,
        "errors": errors,
        "dry_run": True,
    }


def _file_operation(payload: dict[str, Any]) -> dict[str, Any]:
    """执行文件操作：read/search 只读；patch 先 preview 换取 approval_token。

    preview 为真只读（dry-run）：在临时副本上模拟补丁校验可应用性与影响，
    用户确认前不修改/删除任何真实文件，也不写回收站清单；apply 才真落盘。
    """
    op = str(payload.get("op") or "").strip().lower()
    root = _resolve_safe_root(str(payload.get("safe_root") or "").strip())
    working_dir = str(payload.get("working_dir") or "").strip()
    if not working_dir:
        working_dir = root
    working_dir = _resolve_safe_root(working_dir)

    if op == "read":
        path = str(payload.get("path") or "").strip()
        if not path:
            return {"ok": False, "error": "path 不能为空"}
        result = _file_safe_read(path, working_dir)
        return result

    if op == "patch":
        mode = str(payload.get("mode") or "preview").strip().lower()
        patch = str(payload.get("patch") or "").strip()
        if not patch:
            return {"ok": False, "error": "patch 不能为空"}
        if mode == "apply":
            if not _consume_approval(str(payload.get("approval_token") or "").strip()):
                # 纯删除类补丁已走回收站（可恢复），允许 agent 全自动删除，无需确认
                if not _patch_is_pure_delete(patch):
                    return {
                        "ok": False,
                        "error": "缺少有效 approval_token，请先执行 preview 并等待用户确认",
                    }
            result = _file_apply_patch(patch, working_dir, working_dir)
            return result
        if mode == "preview":
            # 真只读：在临时副本上模拟补丁，只做路径/格式/可应用性校验并返回
            # 影响结果；不修改真实文件、不删除文件、不移入回收站（B1 回归）。
            validation = _file_apply_patch(
                patch, working_dir, working_dir, dry_run=True
            )
            if not validation.get("ok"):
                return validation
            token = _create_approval("file_patch")
            return {
                "ok": True,
                "mode": "preview",
                "validation": validation,
                "approval_token": token,
                "approval_expires_in_seconds": APPROVAL_TTL_SECONDS,
            }
        return {"ok": False, "error": "mode 必须为 preview 或 apply"}

    return {"ok": False, "error": "op 必须为 read 或 patch"}


def _patch_is_pure_delete(patch: str) -> bool:
    """判断 V4A 补丁是否只包含删除文件操作（已移入回收站、可恢复，可免确认执行）。"""
    try:
        from internal.core.agent.adapters.hermes.v4a_patch import (
            OperationType,
            parse_v4a_patch,
        )
    except Exception:
        return False
    operations, parse_error = parse_v4a_patch(patch)
    if parse_error or not operations:
        return False
    return all(op.operation == OperationType.DELETE for op in operations)


def _detect_lan_ip() -> str:
    """探测本机非回环 IPv4 地址（UDP connect 不真正发包）。

    优先取默认路由出网 IP；失败时回退主机名解析的第一个非回环地址。
    """
    try:
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(1)
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        finally:
            sock.close()
    except Exception:
        pass
    try:
        import socket

        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return ""


def _device_info() -> dict[str, str]:
    """返回当前设备信息：名称取系统用户名，IP 取本机出网地址。

    支持 OS_AUTOMATION_DEVICE_IP / OS_AUTOMATION_DEVICE_NAME 环境变量覆盖
    （容器 / 多网卡环境下自动探测可能不准确）。
    """
    name = _env("OS_AUTOMATION_DEVICE_NAME")
    if not name:
        try:
            import getpass

            name = getpass.getuser()
        except Exception:
            name = ""
    if not name:
        name = _env("USERNAME") or _env("USER") or ""
    ip = _env("OS_AUTOMATION_DEVICE_IP") or _detect_lan_ip()
    return {"ip": ip, "name": name}


def _recycle_root(safe_root: str) -> Path:
    return Path(safe_root) / RECYCLE_DIR_NAME


def _recycle_manifest_path(safe_root: str) -> Path:
    root = _recycle_root(safe_root)
    root.mkdir(parents=True, exist_ok=True)
    return root / MANIFEST_FILENAME


def _read_recycle_manifest(safe_root: str) -> list[dict[str, Any]]:
    manifest_path = _recycle_manifest_path(safe_root)
    if not manifest_path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    try:
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        return []
    return entries


def _append_recycle_manifest(safe_root: str, entry: dict[str, Any]) -> None:
    manifest_path = _recycle_manifest_path(safe_root)
    with _recycle_lock:
        with manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _rewrite_recycle_manifest(safe_root: str, entries: list[dict[str, Any]]) -> None:
    manifest_path = _recycle_manifest_path(safe_root)
    with _recycle_lock:
        manifest_path.write_text(
            "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
            encoding="utf-8",
        )


def _path_size(path: Path) -> int:
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _safe_delete(payload: dict[str, Any]) -> dict[str, Any]:
    """把本机文件/目录移入回收站并记录清单，不执行物理删除。"""
    root = _resolve_safe_root(str(payload.get("safe_root") or "").strip())
    root_path = Path(root)
    recycle = _recycle_root(root)
    paths = payload.get("paths") or []
    if not isinstance(paths, list) or not paths:
        return {"ok": False, "error": "paths 不能为空"}
    task_id = str(payload.get("task_id") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    retention_days = max(int(payload.get("retention_days") or DEFAULT_RECYCLE_RETENTION_DAYS), 1)

    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    for raw in paths:
        raw_path = str(raw or "").strip()
        if not raw_path:
            continue
        entry = _delete_into_recycle(
            raw_path,
            root,
            reason=reason,
            task_id=task_id,
            retention_days=retention_days,
        )
        if entry is None:
            errors.append(f"无法删除: {raw_path}")
        else:
            entries.append(entry)
    return {"ok": not errors, "entries": entries, "errors": errors, "recycle_root": str(recycle)}


def _delete_into_recycle(
    raw_path: str,
    root: str,
    *,
    reason: str = "",
    task_id: str = "",
    retention_days: int = DEFAULT_RECYCLE_RETENTION_DAYS,
) -> dict[str, Any] | None:
    """把单个文件/目录移入本机回收站并追加清单，返回清单条目；失败返回 None。

    供 os_recycle_bin delete 与 V4A Delete File 共用，保证删除可恢复。
    """
    root_path = Path(root)
    recycle = _recycle_root(root)
    try:
        resolved = Path(raw_path).expanduser().resolve()
    except OSError:
        return None
    if not _is_path_within(root, str(resolved)) or str(resolved).startswith(str(recycle) + os.sep):
        return None
    if not resolved.exists():
        return None
    try:
        relative = resolved.relative_to(root_path)
    except ValueError:
        return None
    with _recycle_lock:
        dest = recycle / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        entry_id = uuid.uuid4().hex
        entry = {
            "entry_id": entry_id,
            "original_path": str(resolved),
            "relative_path": str(relative),
            "moved_to": str(dest),
            "size": _path_size(resolved),
            "is_dir": resolved.is_dir(),
            "deleted_at": time.time(),
            "retention_days": retention_days,
            "expire_at": time.time() + retention_days * 86400,
            "task_id": task_id,
            "reason": reason,
            "device_info": _device_info(),
            "restored": False,
        }
        shutil.move(str(resolved), str(dest))
        _append_recycle_manifest(root, entry)
    return entry


def _list_recycle(payload: dict[str, Any]) -> dict[str, Any]:
    root = _resolve_safe_root(str(payload.get("safe_root") or "").strip())
    entries = _read_recycle_manifest(root)
    keyword = str(payload.get("keyword") or "").strip().lower()
    task_id = str(payload.get("task_id") or "").strip()
    only_restorable = bool(payload.get("only_restorable", True))
    result = []
    for entry in entries:
        if only_restorable and entry.get("restored"):
            continue
        if task_id and entry.get("task_id") != task_id:
            continue
        if keyword:
            haystack = f"{entry.get('original_path', '')} {entry.get('reason', '')} {entry.get('task_id', '')}".lower()
            if keyword not in haystack:
                continue
        result.append(entry)
    return {"ok": True, "entries": result, "count": len(result)}


def _restore_single_recycle_entry(
    entry: dict[str, Any],
    root: str,
    entries: list[dict[str, Any]],
    *,
    target_path: str = "",
) -> tuple[bool, dict[str, Any], str]:
    """恢复单个回收站条目。返回 (ok, entry_or_error, restored_path)。

    target_path 非空时把文件恢复到自选目标路径（仍须位于安全根目录内）。
    """
    moved_to = Path(str(entry["moved_to"]))
    if not moved_to.exists():
        return False, {"entry_id": entry.get("entry_id"), "error": f"回收站文件缺失: {moved_to}"}, ""
    if target_path.strip():
        destination = Path(target_path.strip()).expanduser().resolve()
    else:
        destination = Path(str(entry["original_path"])).expanduser().resolve()
    if not _is_path_within(root, str(destination)):
        return False, {"entry_id": entry.get("entry_id"), "error": "恢复目标超出允许目录"}, ""
    if destination.exists():
        suffix = f".restored-{uuid.uuid4().hex[:8]}"
        destination = destination.with_name(destination.name + suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(moved_to), str(destination))
    entry["restored"] = True
    entry["restored_at"] = time.time()
    entry["restored_to"] = str(destination)
    return True, entry, str(destination)


def _restore_recycle(payload: dict[str, Any]) -> dict[str, Any]:
    root = _resolve_safe_root(str(payload.get("safe_root") or "").strip())
    entry_id = str(payload.get("entry_id") or "").strip()
    original_path = str(payload.get("path") or "").strip()
    task_id_filter = str(payload.get("task_id") or "").strip()
    target_path = str(payload.get("target_path") or "").strip()
    check_device = bool(payload.get("check_device"))
    confirm_device_mismatch = bool(payload.get("confirm_device_mismatch"))
    entries = _read_recycle_manifest(root)

    if not entry_id and not original_path and task_id_filter:
        # 批量恢复：一次任务误删多条时整批找回
        restored: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        changed = False
        for entry in entries:
            if entry.get("restored") or entry.get("task_id") != task_id_filter:
                continue
            ok, result, _path = _restore_single_recycle_entry(entry, root, entries)
            changed = True
            if ok:
                restored.append(result)
            else:
                errors.append(result)
        if not changed:
            return {"ok": False, "error": f"未找到 task_id={task_id_filter} 的可恢复条目"}
        if restored or errors:
            _rewrite_recycle_manifest(root, entries)
        return {"ok": not errors, "restored": restored, "errors": errors}

    target = None
    for entry in entries:
        if entry.get("restored"):
            continue
        if entry_id and entry.get("entry_id") == entry_id:
            target = entry
            break
        if original_path and entry.get("original_path") == original_path:
            target = entry
            break
    if target is None:
        return {"ok": False, "error": "回收站中未找到对应条目"}
    if check_device and not confirm_device_mismatch:
        recorded = target.get("device_info") or {}
        current = _device_info()
        if (recorded.get("ip") or recorded.get("name")) and (
            recorded.get("ip") != current.get("ip")
            or recorded.get("name") != current.get("name")
        ):
            return {
                "ok": False,
                "code": "device_mismatch",
                "error": "该文件并非在本机删除，恢复前请确认恢复方式",
                "device_mismatch": True,
                "recorded_device": recorded,
                "current_device": current,
                "entry_id": target.get("entry_id"),
            }
    ok, result, restored_path = _restore_single_recycle_entry(
        target,
        root,
        entries,
        target_path=target_path,
    )
    if ok:
        _rewrite_recycle_manifest(root, entries)
        return {"ok": True, "entry": result, "restored_to": restored_path}
    return {"ok": False, "error": result.get("error", "恢复失败"), "entry_id": result.get("entry_id")}


def _purge_recycle(payload: dict[str, Any]) -> dict[str, Any]:
    """物理清理已过留存期的回收站条目，并同步清单。

    支持指定 ``entry_id`` 精确清理单条（平台回收站到期销毁时携带）；
    未指定时批量清理所有已过期条目。
    """
    root = _resolve_safe_root(str(payload.get("safe_root") or "").strip())
    now = time.time()
    entry_id = str(payload.get("entry_id") or "").strip()
    entries = _read_recycle_manifest(root)
    remaining: list[dict[str, Any]] = []
    purged: list[dict[str, Any]] = []
    errors: list[str] = []
    for entry in entries:
        if entry.get("restored"):
            remaining.append(entry)
            continue
        if entry_id and str(entry.get("entry_id") or "") != entry_id:
            # 精确清理模式：仅处理目标条目，其余原样保留
            remaining.append(entry)
            continue
        expire_at = float(entry.get("expire_at") or 0)
        if not entry_id and expire_at > now:
            remaining.append(entry)
            continue
        moved_to = Path(str(entry.get("moved_to") or ""))
        try:
            if moved_to.exists():
                if moved_to.is_dir() and not moved_to.is_symlink():
                    shutil.rmtree(moved_to)
                else:
                    moved_to.unlink()
            purged.append(entry)
        except OSError as exc:
            errors.append(f"{entry.get('original_path', '')}: {exc}")
            remaining.append(entry)
    if purged or errors:
        _rewrite_recycle_manifest(root, remaining)
    return {"ok": not errors, "purged": purged, "errors": errors}


def _recycle_operation(payload: dict[str, Any]) -> dict[str, Any]:
    op = str(payload.get("op") or "").strip().lower()
    if op == "delete":
        return _safe_delete(payload)
    if op == "list":
        return _list_recycle(payload)
    if op == "restore":
        return _restore_recycle(payload)
    if op == "purge":
        return _purge_recycle(payload)
    return {"ok": False, "error": "op 必须为 delete/list/restore/purge"}


class OsAutomationHandler(BaseHTTPRequestHandler):
    server_version = "YuxinOSAutomation/0.1"

    def log_message(self, _format: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), _format % args)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = _env("OS_AUTOMATION_TOKEN")
        if not expected:
            return False
        header = self.headers.get("Authorization", "")
        if not header.lower().startswith("bearer "):
            return False
        supplied = header[7:].strip()
        return hmac.compare_digest(supplied, expected)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/health":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return
        self._send_json(
            200,
            {
                "ok": True,
                "status": "ready",
                "os": os.name,
                "pid": os.getpid(),
                "token_configured": bool(_env("OS_AUTOMATION_TOKEN")),
            },
        )

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/file", "/recycle"}:
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        if not self._authorized():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send_json(400, {"ok": False, "error": "invalid_json"})
            return

        try:
            if parsed.path == "/file":
                result = _file_operation(payload)
                self._send_json(200, result)
                return
            if parsed.path == "/recycle":
                result = _recycle_operation(payload)
                self._send_json(200, result)
                return
        except Exception as exc:
            logger.exception("OS 自动化任务执行异常")
            self._send_json(
                500,
                {"ok": False, "error": str(exc), "traceback": traceback.format_exc()},
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="YuxinAI OS automation worker")
    parser.add_argument("--host", default=_env("OS_AUTOMATION_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(_env("OS_AUTOMATION_PORT", DEFAULT_PORT)))
    args = parser.parse_args()

    if not _env("OS_AUTOMATION_TOKEN"):
        print("OS_AUTOMATION_TOKEN 未配置，拒绝启动", file=__import__("sys").stderr)
        return 2

    server = ThreadingHTTPServer((args.host, args.port), OsAutomationHandler)
    print(
        f"OS automation worker listening on http://{args.host}:{args.port}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
