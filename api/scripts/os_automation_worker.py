"""宿主机 OS 自动化 worker。

运行在真实 Windows/Linux 主机上，通过受保护的本机 HTTP 接口接收平台请求，
执行文件操作（读/搜/V4A 补丁）、回收站删除/恢复/清理、文件写前快照/回滚，
以及终端命令执行（Windows: CMD / GitBash），不依赖外部 CLI。

安全模型：
- 仅接受 Authorization: Bearer <OS_AUTOMATION_TOKEN> 的请求。
- /file 的 patch apply 直接执行（不要求用户逐次确认）：每次真实写文件前自动
  捕获写前快照，Agent 可经 /snapshot 端点或 os_snapshot 工具一键回滚；删除类
  补丁移入本机回收站（可恢复）。mode=preview 仍可做只读 dry-run 校验。
- 每次真实写文件（UPDATE/DELETE/MOVE）前先做内容快照（写前快照，fail-closed），
  Agent 可通过 /snapshot 端点或 os_snapshot 工具一键回滚。快照全存本机隐藏目录，
  默认留存 7 天后由 GC 清理。
- /exec 的终端命令在执行前经删除命令守卫（fail-closed）扫描：物理删除类命令
  （rm/del/rd/Remove-Item/…、含内联代码、脚本文件、管道到解释器等形态）一律拒绝
  并引导改用 os_recycle_bin——终端不得绕过"删除只进回收站"的治理。工作目录必须
  落在安全根内；子进程环境剥离 worker 自身 token；超时杀进程树、输出限长。
- 默认只监听本机回环地址（127.0.0.1）；若需容器/跨机访问，显式以
  `--host 0.0.0.0` 或 `OS_AUTOMATION_HOST` 覆盖，并必须配置强 token。
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import locale
import logging
import os
import re
import shutil
import subprocess
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

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
APPROVAL_TTL_SECONDS = 1800
DEFAULT_SAFE_ROOT = ""
RECYCLE_DIR_NAME = ".yujianwo_recycle"
SNAPSHOT_DIR_NAME = ".yujianwo_snapshots"
SNAPSHOT_FILES_DIR_NAME = "files"
MANIFEST_FILENAME = "manifest.jsonl"
DEFAULT_RECYCLE_RETENTION_DAYS = 30
DEFAULT_SNAPSHOT_RETENTION_DAYS = 7
DEFAULT_SNAPSHOT_MAX_BYTES = 50 * 1024 * 1024

_approvals: dict[str, dict[str, Any]] = {}
_approval_lock = threading.Lock()
# 可重入锁：_delete_into_recycle 持有锁后调用 _append_recycle_manifest（内部再次加锁）
_recycle_lock = threading.RLock()
# 快照全局锁：保护快照 manifest 的追加/重写与快照文件写（内容寻址，幂等可重入）
_snapshot_lock = threading.RLock()
# 每路径锁：进程内按 resolved path 互斥“快照→写”与“回滚→写回”，避免并发写同一文件。
# 与 Hermes file_state 思路一致：快照与写落在同一临界区。
_file_locks: dict[str, threading.RLock] = {}
_file_locks_guard = threading.Lock()


def _file_path_lock(resolved_path: str) -> threading.RLock:
    """返回按规范化路径共享的可重入锁（进程内，防止并发写同一文件）。"""
    with _file_locks_guard:
        return _file_locks.setdefault(resolved_path, threading.RLock())


class _locked_paths:
    """按规范化路径排序获取一组可重入路径锁，退出上下文时逆序释放。

    用于把“写前快照 → 真实写”与“回滚读/写回”放进同一临界区，保证并发请求
    不会交错修改同一文件（借鉴 Hermes file_state 的每文件锁思路）。
    """

    def __init__(self, paths: list[str]) -> None:
        unique = sorted({p for p in paths if p})
        self._locks = [_file_path_lock(p) for p in unique]

    def __enter__(self) -> "_locked_paths":
        for lock in self._locks:
            lock.acquire()
        return self

    def __exit__(self, *_exc: Any) -> bool:
        for lock in reversed(self._locks):
            lock.release()
        return False


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


# ---------------------------------------------------------------------------
# 敏感路径读黑名单：os_file_task 免确认放开写删后，读取面由本黑名单兜底。
# 命中敏感路径（凭据/密钥/浏览器数据/回收站快照）的 read/search 直接拒绝，
# 借鉴 Hermes file_safety 思路：路径段/文件名命中即不可读，不读取任何内容。
# ---------------------------------------------------------------------------
# 路径任意层级命中即视为敏感的目录段（小写、含 .yujianwo 自管目录）
_SENSITIVE_READ_DIR_SEGMENTS: frozenset[str] = frozenset(
    {
        ".ssh",
        ".aws",
        ".azure",
        ".gcloud",
        ".gnupg",
        ".kube",
        ".docker",
        ".npm",
        ".m2",
        ".gradle",
        ".mozilla",
        "firefox",
        "google-chrome",
        "chromium",
        "microsoft-edge",
        "bravesoftware",
        "user data",
        "keychain",
        "vault",
        ".yujianwo_recycle",
        ".yujianwo_snapshots",
        "system volume information",
        "$recycle.bin",
    }
)
# 文件名（小写）命中即视为敏感：SSH/私钥、.env 密钥文件、浏览器凭据库等
_SENSITIVE_READ_FILE_NAMES: frozenset[str] = frozenset(
    {
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_25519",
        "private_key.pem",
        "key.pem",
        "credentials",
        "credentials.json",
        "serviceaccount.json",
        "service-account.json",
        ".netrc",
        "_netrc",
        "logins.json",
        "key4.db",
        "cert9.db",
        "login data",
        "cookies",
        "web data",
    }
)


def _sensitive_read_hit(raw_path: str) -> str:
    """判定路径是否命中敏感读黑名单；未命中返回空字符串，命中返回说明。"""
    try:
        resolved = str(Path(raw_path).expanduser().resolve())
    except OSError:
        resolved = raw_path
    parts = [part for part in resolved.split(os.sep) if part]
    lowered = [part.lower() for part in parts]
    for part in lowered:
        if part in _SENSITIVE_READ_DIR_SEGMENTS:
            return f"路径命中敏感目录（{part}），凭据/密钥/系统数据不可读取"
    if not lowered:
        return ""
    filename = lowered[-1]
    if filename in _SENSITIVE_READ_FILE_NAMES:
        return f"路径命中敏感文件（{filename}），凭据/密钥/系统数据不可读取"
    if filename.startswith(".env") and not filename.startswith(".env.example") and not filename.startswith(".env.sample"):
        return "路径命中敏感文件（.env*），环境变量/密钥不可读取"
    if filename.endswith(".pem") or filename.endswith(".pfx") or filename.endswith(".p12"):
        return f"路径命中敏感文件（{filename}），私钥/证书密钥不可读取"
    return ""


def _sensitive_search_globs() -> list[str]:
    """rg 排除 glob：搜索内容时跳过敏感目录段与敏感文件名。"""
    globs: list[str] = []
    for segment in _SENSITIVE_READ_DIR_SEGMENTS:
        if segment in (".yujianwo_recycle", ".yujianwo_snapshots"):
            globs.append(f"!**/{segment}/**")
        else:
            globs.append(f"!**/{segment}/**")
            globs.append(f"!**/{segment}")
    for name in _SENSITIVE_READ_FILE_NAMES:
        globs.append(f"!**/{name}")
    globs.append("!**/.env")
    globs.append("!**/.env.*")
    return globs


def _file_list_dir(path: str, root: str, limit: int = 0) -> dict[str, Any]:
    """枚举目录内的直接子项（名称/类型/大小/修改时间），敏感项跳过。

    仅列一层（不做递归），便于 Agent 与用户逐级浏览；越界与敏感路径拒绝。
    """
    try:
        resolved = str(Path(path).expanduser().resolve()) if path else root
    except OSError:
        return {"ok": False, "error": f"路径无法解析: {path}"}
    if not _is_path_within(root, resolved):
        return {"ok": False, "error": f"目录越界（安全根 {root}）"}
    if not os.path.isdir(resolved):
        return {"ok": False, "error": "目标不是目录或不存在"}
    entries: list[dict[str, Any]] = []
    try:
        with os.scandir(resolved) as scan:
            for item in scan:
                if _sensitive_read_hit(item.path):
                    continue
                try:
                    stat = item.stat()
                except OSError:
                    continue
                entries.append(
                    {
                        "name": item.name,
                        "is_dir": item.is_dir(),
                        "size": stat.st_size,
                        "modified_at": int(stat.st_mtime),
                    }
                )
    except PermissionError as exc:
        return {"ok": False, "error": f"无权限访问: {exc}"}
    entries.sort(key=lambda entry: (not entry["is_dir"], str(entry["name"]).lower()))
    truncated = False
    if limit and limit > 0 and len(entries) > limit:
        entries = entries[:limit]
        truncated = True
    return {"ok": True, "path": resolved, "entries": entries, "truncated": truncated}


def _file_safe_read(path: str, root: str, offset: int = 0, limit: int = 0) -> dict[str, Any]:
    if not _is_path_within(root, path):
        return {"ok": False, "error": "路径超出允许目录", "path": path}
    sensitive = _sensitive_read_hit(path)
    if sensitive:
        return {"ok": False, "error": f"{sensitive}（读取已拒绝）", "path": path}
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

    # 分页：offset 为行号（0 基线），limit>0 时只返回该窗口的若干行。
    try:
        offset = max(int(offset or 0), 0)
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = max(int(limit or 0), 0)
    except (TypeError, ValueError):
        limit = 0
    if offset > 0 or limit > 0:
        lines = content.splitlines()
        if offset >= len(lines):
            return {
                "ok": True,
                "path": str(target),
                "content": "",
                "truncated": False,
                "total_chars": len(content),
                "total_lines": len(lines),
                "offset": offset,
                "limit": limit,
            }
        window = lines[offset : offset + limit if limit else offset + 200]
        return {
            "ok": True,
            "path": str(target),
            "content": "\n".join(window),
            "truncated": len(window) < len(lines) - offset,
            "total_chars": len(content),
            "total_lines": len(lines),
            "offset": offset,
            "limit": limit,
            "read_lines": len(window),
        }

    max_chars = int(_env("OS_AUTOMATION_FILE_READ_MAX_CHARS", "100000"))
    truncated = len(content) > max_chars
    return {
        "ok": True,
        "path": str(target),
        "content": content[:max_chars],
        "truncated": truncated,
        "total_chars": len(content),
    }


def _file_search(pattern: str, root: str, working_dir: str, path: str = "") -> dict[str, Any]:
    """在允许目录内递归搜索文件与内容（对齐 Hermes search_files 的 rg 语义）。

    敏感路径不参与搜索：搜索目标自身命中黑名单时直接拒绝；普通目录内搜索时
    用 rg 排除 glob 跳过敏感目录段与敏感文件名（.ssh/.env/浏览器凭据等）。
    """
    scope = working_dir or root
    if path:
        candidate = str(Path(path).expanduser())
        if not Path(candidate).is_absolute():
            candidate = str(Path(scope) / candidate)
        if not _is_path_within(scope, candidate):
            return {"ok": False, "error": f"路径超出允许目录: {candidate}"}
        sensitive = _sensitive_read_hit(candidate)
        if sensitive:
            return {"ok": False, "error": f"{sensitive}（搜索已拒绝）", "path": candidate}
        if Path(candidate).is_file():
            scope = str(Path(candidate).parent)
        else:
            scope = candidate
    else:
        sensitive = _sensitive_read_hit(scope)
        if sensitive:
            return {"ok": False, "error": f"{sensitive}（搜索已拒绝）", "path": scope}
    if not _is_path_within(root, scope):
        return {"ok": False, "error": "搜索范围超出允许目录"}
    if not pattern:
        return {"ok": False, "error": "pattern 不能为空"}

    try:
        import subprocess

        cmd = ["rg", "--no-heading", "--line-number", "--color", "never"]
        if _env("OS_AUTOMATION_SEARCH_MAX_RESULTS", "100"):
            try:
                cmd += ["-m", str(max(int(_env("OS_AUTOMATION_SEARCH_MAX_RESULTS", "100")), 1))]
            except ValueError:
                pass
        cmd += [pattern, scope, "-g", "!.git/**", "-g", "!node_modules/**", "-g", "!__pycache__/**"]
        cmd += _sensitive_search_globs()
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        output = result.stdout.decode("utf-8", errors="replace")
        lines = [line for line in output.splitlines() if line.strip()]
        return {
            "ok": True,
            "pattern": pattern,
            "scope": scope,
            "count": len(lines),
            "matches": lines,
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "error": "宿主环境未安装 ripgrep（rg），请先安装后启用 search_files",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "搜索超时（30 秒）"}
    except Exception as exc:
        return {"ok": False, "error": f"搜索失败: {exc}"}


def _file_apply_patch(
    patch: str,
    root: str,
    working_dir: str,
    dry_run: bool = False,
    snapshot_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """在宿主机执行 V4A 补丁，并验证所有目标路径都落在允许目录内。

    dry_run=True（preview）时把补丁整体模拟到临时副本目录上：ADD/UPDATE/
    DELETE/MOVE 全部操作逻辑复用 apply_v4a_operations，但读到的永远是副本
    状态、写的也是副本，delete 只是从副本移除（绝不真移入回收站）。返回结构
    与 apply 一致并附 dry_run 标记，真实文件不会被触碰。

    真实 apply 前对补丁将修改/删除/移动的已存在文件做写前快照（fail-closed：
    快照失败则拒绝本次 patch，保证“没有快照就没有修改”）。快照上下文
    （session_id/conversation_turn/source）经 snapshot_meta 传入。
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

    # 写前快照：对本次 patch 将触碰的已存在文件先捕获内容，失败则拒绝本次写。
    # 锁顺序：先取路径锁（快照与写落在同一临界区），manifest 追加只在各自函数
    # 内短持 _snapshot_lock；回滚路径同样先取路径锁，避免与写交错/死锁。
    meta = snapshot_meta or {}
    try:
        touched = [
            str(Path(_normalize_op_path(working_dir, raw)).expanduser().resolve())
            for op in operations
            for raw in (op.file_path, op.new_path if op.operation == "move" else None)
            if raw
        ]
    except OSError:
        touched = []
    with _locked_paths(touched):
        try:
            _snap_entries, snap_skipped = _snapshot_entries_before_patch(
                operations,
                root,
                working_dir,
                source=str(meta.get("source") or "os_file_task"),
                session_id=str(meta.get("session_id") or ""),
                conversation_turn=str(meta.get("conversation_turn") or ""),
            )
        except OSError as exc:
            return {"ok": False, "error": f"写前快照失败，已拒绝本次修改: {exc}"}

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

        warnings: list[str] = []
        for skipped in snap_skipped:
            if skipped.get("reason") == "too_large":
                warnings.append(
                    f"跳过超大文件快照（{skipped.get('size')} 字节，上限 "
                    f"{skipped.get('max_bytes')}）: {skipped.get('path')}"
                )
        results: list[str] = []
        try:
            results = apply_v4a_operations(operations, _RootedFileOps(root, working_dir))
        except PermissionError as exc:
            return {"ok": False, "error": str(exc), "results": results, "warnings": warnings}
        except Exception as exc:
            return {"ok": False, "error": f"补丁应用失败: {exc}", "warnings": warnings}
        errors = [r for r in results if r.startswith("ERROR:")]
        response: dict[str, Any] = {"ok": not errors, "results": results, "errors": errors}
        if warnings:
            response["warnings"] = warnings
        if _snap_entries:
            response["snapshot_batch_id"] = _snap_entries[0].get("batch_id")
        return response


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
    """执行文件操作：read/search 只读；patch 分 preview 与 apply。

    preview 为只读 dry-run：在临时副本上模拟补丁校验可应用性与影响范围，
    不修改/删除任何真实文件、不写回收站清单（可用于变更前的预检查）。
    apply 直接执行真实修改——每次写文件前自动捕获写前快照（快照失败拒绝
    本次写），删除类操作移入本机回收站；改错可经 /snapshot 或 os_snapshot
    回滚，因此不再要求 approval_token 逐次确认。
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
        result = _file_safe_read(
            path,
            working_dir,
            offset=payload.get("offset", 0),
            limit=payload.get("limit", 0),
        )
        return result

    if op == "list":
        path = str(payload.get("path") or "").strip() or working_dir
        result = _file_list_dir(path, working_dir, limit=int(payload.get("limit") or 0))
        return result

    if op == "search":
        pattern = str(payload.get("pattern") or "").strip()
        path = str(payload.get("path") or "").strip()
        result = _file_search(pattern, root, working_dir, path=path)
        return result

    if op == "patch":
        mode = str(payload.get("mode") or "preview").strip().lower()
        patch = str(payload.get("patch") or "").strip()
        if not patch:
            return {"ok": False, "error": "patch 不能为空"}
        if mode == "apply":
            # 写前快照已兜底（改错可回滚、删除入回收站可恢复）：apply 直接执行，
            # 不再要求用户逐次确认/approval_token。root（安全根）作为路径校验与
            # 快照存储的基点，working_dir 仅作操作基准：两者都归一 resolve 后，
            # root 总为 working_dir 的祖先，快照目录落在 <root>/.yujianwo_snapshots，
            # 与回滚侧 _resolve_safe_root 读取 manifest 的基点一致。
            result = _file_apply_patch(
                patch,
                root,
                working_dir,
                snapshot_meta={
                    "source": "os_file_task",
                    "session_id": str(payload.get("session_id") or "").strip(),
                    "conversation_turn": str(payload.get("conversation_turn") or "").strip(),
                },
            )
            return result
        if mode == "preview":
            # 只读 dry-run：在临时副本上模拟补丁，只做路径/格式/可应用性校验并返回
            # 影响结果；不修改真实文件、不删除文件、不移入回收站（B1 回归）。
            # 仍签发 approval_token 仅为兼容旧客户端响应结构；apply 已不校验它。
            validation = _file_apply_patch(
                patch, root, working_dir, dry_run=True
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

    return {"ok": False, "error": "op 必须为 read、search 或 patch"}


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
            "recycle_root": str(recycle),
            "safe_root": root,
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


def _snapshot_root(safe_root: str) -> Path:
    """快照根目录：OS_AUTOMATION_SNAPSHOT_DIR 覆盖，缺省 <safe_root>/.yujianwo_snapshots。"""
    override = _env("OS_AUTOMATION_SNAPSHOT_DIR")
    if override:
        try:
            return Path(override).expanduser().resolve()
        except OSError:
            return Path(override).expanduser()
    return Path(safe_root) / SNAPSHOT_DIR_NAME


def _snapshot_manifest_path(safe_root: str) -> Path:
    root = _snapshot_root(safe_root)
    root.mkdir(parents=True, exist_ok=True)
    return root / MANIFEST_FILENAME


def _read_snapshot_manifest(safe_root: str) -> list[dict[str, Any]]:
    manifest_path = _snapshot_manifest_path(safe_root)
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


def _append_snapshot_manifest(safe_root: str, entry: dict[str, Any]) -> None:
    manifest_path = _snapshot_manifest_path(safe_root)
    with _snapshot_lock:
        with manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _rewrite_snapshot_manifest(safe_root: str, entries: list[dict[str, Any]]) -> None:
    manifest_path = _snapshot_manifest_path(safe_root)
    with _snapshot_lock:
        manifest_path.write_text(
            "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries),
            encoding="utf-8",
        )


def _snapshot_max_bytes() -> int:
    try:
        return max(int(_env("OS_AUTOMATION_SNAPSHOT_MAX_BYTES", str(DEFAULT_SNAPSHOT_MAX_BYTES))), 0)
    except ValueError:
        return DEFAULT_SNAPSHOT_MAX_BYTES


def _file_sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _capture_single_file_snapshot(
    resolved_path: str,
    safe_root: str,
    *,
    source: str,
    session_id: str,
    conversation_turn: str,
    batch_id: str,
    taken_before: str,
    move_target: str = "",
) -> dict[str, Any]:
    """对单个已存在文件捕获内容快照并追加 manifest，返回条目。

    fail-closed：快照写入失败（磁盘满/权限等）抛 OSError，由调用方拒绝本次写操作；
    文件体积超过 OS_AUTOMATION_SNAPSHOT_MAX_BYTES 时跳过快照，返回带 skipped 标记
    的条目（不阻断写，由调用方转成 warning）。
    """
    target = Path(resolved_path)
    if not target.is_file():
        return {"skipped": True, "reason": "missing", "path": resolved_path}
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise OSError(f"快照读取文件状态失败: {resolved_path}: {exc}") from exc
    max_bytes = _snapshot_max_bytes()
    if max_bytes > 0 and size > max_bytes:
        logger.warning(
            "跳过超大文件快照（%d 字节 > 上限 %d）: %s", size, max_bytes, resolved_path
        )
        return {
            "skipped": True,
            "reason": "too_large",
            "size": size,
            "max_bytes": max_bytes,
            "path": resolved_path,
        }

    try:
        content_sha256 = _file_sha256_path(target)
    except OSError as exc:
        raise OSError(f"快照计算文件哈希失败: {resolved_path}: {exc}") from exc

    root = Path(safe_root)
    snapshot_files_dir = _snapshot_root(safe_root) / SNAPSHOT_FILES_DIR_NAME
    snap_file = snapshot_files_dir / f"{content_sha256}.snap"
    if not snap_file.is_file():
        try:
            snapshot_files_dir.mkdir(parents=True, exist_ok=True)
            with snap_file.open("xb") as handle:
                handle.write(target.read_bytes())
        except FileExistsError:
            pass
        except OSError as exc:
            raise OSError(f"快照内容写入失败: {snap_file}: {exc}") from exc

    try:
        relative = target.relative_to(root)
        relative_path = str(relative)
    except ValueError:
        relative_path = str(target)
    try:
        stat = target.stat()
        mode = "file"
        size = stat.st_size
    except OSError:
        mode = "file"
        size = 0
    now = time.time()
    entry = {
        "snapshot_id": f"{content_sha256[:16]}-{int(now * 1000)}",
        "path": str(target),
        "relative_path": relative_path,
        "content_sha256": content_sha256,
        "mode": mode,
        "source": source,
        "session_id": session_id,
        "conversation_turn": conversation_turn,
        "batch_id": batch_id,
        "taken_before": taken_before,
        "created_at": now,
        "size": size,
        "rolled_back": False,
    }
    if move_target:
        entry["move_target"] = move_target
    _append_snapshot_manifest(safe_root, entry)
    return entry


def _match_snapshot_path(entry: dict[str, Any], target: str) -> bool:
    """manifest 条目与回滚目标路径匹配（绝对路径或相对路径任一命中）。"""
    if not entry.get("path") or not target:
        return False
    target = str(Path(target).expanduser())
    if not Path(target).is_absolute():
        target = str(Path(target).expanduser().resolve())
    candidate = str(Path(str(entry["path"])).expanduser())
    if not Path(candidate).is_absolute():
        try:
            candidate = str(Path(candidate).resolve())
        except OSError:
            pass
    return candidate == target or str(entry.get("relative_path") or "") == target


def _normalize_resolved_path(path: str, working_dir: str) -> str:
    """把用户输入路径规范成绝对路径（相对路径拼 working_dir 再 resolve）。"""
    expanded = str(Path(path).expanduser())
    if not Path(expanded).is_absolute():
        expanded = str(Path(working_dir) / expanded)
    try:
        return str(Path(expanded).resolve())
    except OSError:
        return expanded


def _snapshot_entries_before_patch(
    patch_operations: list[Any],
    root: str,
    working_dir: str,
    *,
    source: str,
    session_id: str,
    conversation_turn: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """apply 前对补丁将修改/删除/移动的已存在文件批量快照。

    返回 (快照条目, 跳过条目)。ADD 新文件无需回滚（本批不做 ADD 撤销语义）；
    UPDATE/DELETE/MOVE 的源文件只要存在就快照其当前内容。全部写操作共享同一
    batch_id，供按 batch 审计/回滚。
    """
    try:
        from internal.core.agent.adapters.hermes.v4a_patch import OperationType
    except Exception:
        OperationType = None

    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    batch_id = uuid.uuid4().hex
    # 同一补丁内对同一文件的多次操作只保留最早一份快照（apply 前状态）。
    seen: set[str] = set()
    for op in patch_operations:
        op_type = getattr(op, "operation", None)
        if OperationType is not None and op_type == OperationType.ADD:
            continue
        raw_path = str(getattr(op, "file_path", "") or "").strip()
        if not raw_path:
            continue
        resolved = _normalize_resolved_path(raw_path, working_dir)
        if not _is_path_within(root, resolved):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        move_target = ""
        if OperationType is not None and op_type == OperationType.MOVE:
            raw_new = str(getattr(op, "new_path", "") or "").strip()
            if raw_new:
                move_target = _normalize_resolved_path(raw_new, working_dir)
        captured = _capture_single_file_snapshot(
            resolved,
            root,
            source=source,
            session_id=session_id,
            conversation_turn=conversation_turn,
            batch_id=batch_id,
            taken_before="patch",
            move_target=move_target,
        )
        if captured.get("skipped"):
            skipped.append(captured)
        else:
            entries.append(captured)
    return entries, skipped


def _snapshot_file_content(safe_root: str, content_sha256: str) -> bytes | None:
    """按内容哈希读取 .snap 文件内容；缺失返回 None。"""
    snap_file = _snapshot_root(safe_root) / SNAPSHOT_FILES_DIR_NAME / f"{content_sha256}.snap"
    try:
        return snap_file.read_bytes()
    except OSError:
        return None


def _do_rollback_entry(
    entry: dict[str, Any],
    safe_root: str,
    *,
    guard_source: str = "os_snapshot",
) -> tuple[bool, dict[str, Any], str]:
    """回滚单条快照条目：把快照内容写回原路径（MOVE 时额外收回目标副本）。

    返回 (ok, result/error_dict, restored_path)。回滚前若原路径当前有内容，先对当前
    内容再做一次快照（rollback_guard），防止回滚本身出错导致二次丢失。
    """
    path = str(entry.get("path") or "").strip()
    if not path:
        return False, {"snapshot_id": entry.get("snapshot_id"), "error": "快照条目缺少 path"}, ""
    if not _is_path_within(safe_root, path):
        return False, {"snapshot_id": entry.get("snapshot_id"), "error": "回滚目标超出允许目录"}, ""
    content_sha256 = str(entry.get("content_sha256") or "").strip()
    if not content_sha256:
        return False, {"snapshot_id": entry.get("snapshot_id"), "error": "快照条目缺少 content_sha256"}, ""
    content = _snapshot_file_content(safe_root, content_sha256)
    if content is None:
        return False, {
            "snapshot_id": entry.get("snapshot_id"),
            "error": f"快照内容缺失: files/{content_sha256}.snap",
        }, ""

    target = Path(path)
    guard_batch = uuid.uuid4().hex
    # 回滚前 guard：目标当前存在则保留一份当前内容快照（防回滚出错二次丢失）。
    if target.is_file():
        try:
            _capture_single_file_snapshot(
                str(target),
                safe_root,
                source=guard_source,
                session_id=str(entry.get("session_id") or ""),
                conversation_turn=str(entry.get("conversation_turn") or ""),
                batch_id=guard_batch,
                taken_before="rollback_guard",
            )
        except OSError as exc:
            return False, {
                "snapshot_id": entry.get("snapshot_id"),
                "error": f"回滚前保护性快照失败，已中止回滚: {exc}",
            }, ""

    # MOVE 撤销：若目标副本仍停留在 move 落点且未被二次修改，收回以避免双副本。
    move_target = str(entry.get("move_target") or "").strip()
    if move_target:
        moved = Path(move_target)
        if moved.is_file() and _is_path_within(safe_root, str(moved)):
            try:
                if _file_sha256_path(moved) == content_sha256:
                    moved.unlink()
            except OSError:
                pass

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            handle.write(content)
    except OSError as exc:
        return False, {"snapshot_id": entry.get("snapshot_id"), "error": f"回滚写回失败: {exc}"}, ""
    return True, entry, str(target)


def _rollback_file(payload: dict[str, Any]) -> dict[str, Any]:
    """按路径回滚单文件（可选 snapshot_id 精确回滚到指定版本）。"""
    root = _resolve_safe_root(str(payload.get("safe_root") or "").strip())
    working_dir = str(payload.get("working_dir") or "").strip() or root
    working_dir = _resolve_safe_root(working_dir)
    path = str(payload.get("path") or "").strip()
    snapshot_id = str(payload.get("snapshot_id") or "").strip()
    if not path:
        return {"ok": False, "error": "path 不能为空"}
    resolved = _normalize_resolved_path(path, working_dir)
    if not _is_path_within(root, resolved):
        return {"ok": False, "error": "路径超出允许目录"}

    # 先取目标路径锁，再短持快照 manifest 锁：与 apply（路径锁外层）保持同一
    # 锁顺序，避免死锁；manifest 读写 + 内容写回落在同一临界区。
    with _file_path_lock(resolved):
        with _snapshot_lock:
            entries = _read_snapshot_manifest(root)
            candidates = [e for e in entries if _match_snapshot_path(e, resolved)]
            target_entry = None
            if snapshot_id:
                for e in candidates:
                    if str(e.get("snapshot_id") or "") == snapshot_id and not e.get("rolled_back"):
                        target_entry = e
                        break
                if target_entry is None:
                    return {"ok": False, "error": f"未找到可回滚快照 snapshot_id={snapshot_id}"}
            else:
                # 默认取该文件最新一次未回滚“写前快照”（排除回滚 guard：guard 是
                # 回滚动作自身的副产物，不参与“内容已一致后无限回滚”的默认语义，
                # 仍可通过显式 snapshot_id 精确回滚）。
                active = [
                    e
                    for e in candidates
                    if not e.get("rolled_back")
                    and str(e.get("taken_before") or "") != "rollback_guard"
                ]
                if not active:
                    return {"ok": False, "error": "该文件无可用快照（可能已全部回滚）"}
                target_entry = max(active, key=lambda e: float(e.get("created_at") or 0))
            target_id = str(target_entry.get("snapshot_id") or "")

            ok, result, restored_path = _do_rollback_entry(target_entry, root)
            if not ok:
                return {"ok": False, **result}
            # _do_rollback_entry 可能追加 rollback_guard 条目，重读后按 id 标记回滚，
            # 避免用陈旧列表重写时把 guard 快照丢回滚掉。
            fresh = _read_snapshot_manifest(root)
            for e in fresh:
                if str(e.get("snapshot_id") or "") == target_id and not e.get("rolled_back"):
                    e["rolled_back"] = True
                    e["rolled_back_at"] = time.time()
                    break
            _rewrite_snapshot_manifest(root, fresh)
    return {
        "ok": True,
        "restored": restored_path,
        "snapshot_id": target_id,
        "content_sha256": target_entry.get("content_sha256"),
    }


def _rollback_turn(payload: dict[str, Any]) -> dict[str, Any]:
    """按 conversation_turn 批量回滚该 turn 涉及的全部文件。

    语义 = 回到用户消息发出前：取该 turn 内各文件最早的快照（即该 turn 第一个
    写操作发生前的状态）逐一写回。逐文件持路径锁再短持 manifest 锁，锁序与
    _rollback_file / apply 一致。
    """
    root = _resolve_safe_root(str(payload.get("safe_root") or "").strip())
    turn = str(payload.get("conversation_turn") or "").strip()
    if not turn:
        return {"ok": False, "error": "conversation_turn 不能为空"}

    with _snapshot_lock:
        entries = _read_snapshot_manifest(root)
        turn_entries = [e for e in entries if str(e.get("conversation_turn") or "") == turn]
        if not turn_entries:
            return {"ok": False, "error": f"未找到 conversation_turn={turn} 的快照"}
        # 每个文件取该 turn 内最早的“写前快照”作为恢复目标（排除 rollback_guard）。
        by_path: dict[str, dict[str, Any]] = {}
        for e in turn_entries:
            p = str(e.get("path") or "")
            if not p:
                continue
            if str(e.get("taken_before") or "") == "rollback_guard":
                continue
            if p not in by_path or float(e.get("created_at") or 0) < float(
                by_path[p].get("created_at") or 0
            ):
                by_path[p] = e
        if not by_path:
            return {"ok": False, "error": f"conversation_turn={turn} 无可用快照"}

    restored: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for _path, entry in by_path.items():
        resolved = str(entry.get("path") or "")
        if not _is_path_within(root, resolved):
            errors.append({"path": resolved, "error": "路径超出允许目录"})
            continue
        with _file_path_lock(resolved):
            with _snapshot_lock:
                entries = _read_snapshot_manifest(root)
                target_entry = None
                for e in entries:
                    if (
                        str(e.get("snapshot_id") or "") == str(entry.get("snapshot_id") or "")
                        and not e.get("rolled_back")
                    ):
                        target_entry = e
                        break
                if target_entry is None:
                    errors.append(
                        {
                            "path": resolved,
                            "snapshot_id": entry.get("snapshot_id"),
                            "error": "该文件该 turn 快照已回滚或不存在",
                        }
                    )
                    continue
                ok, result, restored_path = _do_rollback_entry(target_entry, root)
                if ok:
                    # _do_rollback_entry 可能追加 rollback_guard 条目，重读后按 id
                    # 标记回滚，避免陈旧列表重写丢掉 guard 快照。
                    fresh = _read_snapshot_manifest(root)
                    for e in fresh:
                        if (
                            str(e.get("snapshot_id") or "") == str(target_entry.get("snapshot_id") or "")
                            and not e.get("rolled_back")
                        ):
                            e["rolled_back"] = True
                            e["rolled_back_at"] = time.time()
                            break
                    _rewrite_snapshot_manifest(root, fresh)
                    restored.append(
                        {
                            "path": restored_path,
                            "snapshot_id": target_entry.get("snapshot_id"),
                            "content_sha256": target_entry.get("content_sha256"),
                        }
                    )
                else:
                    errors.append(result)
    return {
        "ok": not errors or bool(restored),
        "restored": restored,
        "errors": errors,
        "count": len(restored),
    }


def _list_snapshots(payload: dict[str, Any]) -> dict[str, Any]:
    root = _resolve_safe_root(str(payload.get("safe_root") or "").strip())
    working_dir = str(payload.get("working_dir") or "").strip() or root
    working_dir = _resolve_safe_root(working_dir)
    path = str(payload.get("path") or "").strip()
    turn = str(payload.get("conversation_turn") or "").strip()
    try:
        limit = max(int(payload.get("limit") or 0), 0)
    except (TypeError, ValueError):
        limit = 0
    entries = _read_snapshot_manifest(root)
    if path:
        resolved = _normalize_resolved_path(path, working_dir)
        entries = [e for e in entries if _match_snapshot_path(e, resolved)]
    if turn:
        entries = [e for e in entries if str(e.get("conversation_turn") or "") == turn]
    entries = sorted(entries, key=lambda e: float(e.get("created_at") or 0), reverse=True)
    if limit > 0:
        entries = entries[:limit]
    metadata = []
    for e in entries:
        metadata.append(
            {
                "snapshot_id": e.get("snapshot_id"),
                "path": e.get("path"),
                "relative_path": e.get("relative_path"),
                "content_sha256": e.get("content_sha256"),
                "mode": e.get("mode"),
                "source": e.get("source"),
                "session_id": e.get("session_id"),
                "conversation_turn": e.get("conversation_turn"),
                "batch_id": e.get("batch_id"),
                "taken_before": e.get("taken_before"),
                "created_at": e.get("created_at"),
                "size": e.get("size"),
                "rolled_back": bool(e.get("rolled_back")),
            }
        )
    return {"ok": True, "entries": metadata, "count": len(metadata)}


def _snapshot_retention_seconds() -> int:
    try:
        return max(int(_env("OS_AUTOMATION_SNAPSHOT_RETENTION_DAYS", str(DEFAULT_SNAPSHOT_RETENTION_DAYS))), 1) * 86400
    except ValueError:
        return DEFAULT_SNAPSHOT_RETENTION_DAYS * 86400


def _gc_snapshots(safe_root: str) -> dict[str, Any]:
    """清理超过留存期的快照条目与对应 .snap 文件。

    内容寻址：.snap 被清理前检查是否仍被其它（未过期）条目引用，是则保留。
    """
    with _snapshot_lock:
        entries = _read_snapshot_manifest(safe_root)
        if not entries:
            return {"ok": True, "purged": [], "removed_files": []}
        now = time.time()
        retention = _snapshot_retention_seconds()
        remaining: list[dict[str, Any]] = []
        purged: list[dict[str, Any]] = []
        expired_shas: set[str] = set()
        for e in entries:
            created_at = float(e.get("created_at") or 0)
            if created_at and now - created_at > retention:
                purged.append(e)
                sha = str(e.get("content_sha256") or "")
                if sha:
                    expired_shas.add(sha)
            else:
                remaining.append(e)
        if not purged:
            return {"ok": True, "purged": [], "removed_files": []}

        live_shas = {str(e.get("content_sha256") or "") for e in remaining if e.get("content_sha256")}
        removed_files: list[str] = []
        files_dir = _snapshot_root(safe_root) / SNAPSHOT_FILES_DIR_NAME
        for sha in expired_shas:
            if sha in live_shas:
                continue
            snap_file = files_dir / f"{sha}.snap"
            try:
                if snap_file.is_file():
                    snap_file.unlink()
                    removed_files.append(str(snap_file))
            except OSError as exc:
                logger.warning("清理快照文件失败: %s: %s", snap_file, exc)
        _rewrite_snapshot_manifest(safe_root, remaining)
    return {"ok": True, "purged": purged, "removed_files": removed_files}


def _snapshot_operation(payload: dict[str, Any]) -> dict[str, Any]:
    """/snapshot 端点调度：rollback_file / rollback_turn / list_snapshots。"""
    root = _resolve_safe_root(str(payload.get("safe_root") or "").strip())
    op = str(payload.get("op") or "").strip().lower()
    if op in {"rollback_file", "rollback_turn"}:
        try:
            _gc_snapshots(root)
        except Exception as exc:
            logger.warning("快照 GC 失败（不影响回滚）: %s", exc)
    if op == "rollback_file":
        return _rollback_file(payload)
    if op == "rollback_turn":
        return _rollback_turn(payload)
    if op == "list_snapshots":
        return _list_snapshots(payload)
    return {"ok": False, "error": "op 必须为 rollback_file/rollback_turn/list_snapshots"}


# ---------------------------------------------------------------------------
# 终端执行（Windows: CMD / GitBash）与删除命令守卫
#
# 治理约束：本机删除只能走回收站通道（os_recycle_bin / V4A Delete File）。
# 终端是任意命令通道，物理删除命令（rm/del/rd/Remove-Item…）一旦放行即可绕过
# 回收站，因此 /exec 在执行**前**做 fail-closed 扫描：命中即拒绝并引导改用
# os_recycle_bin，而不是"执行后再补救"。守卫是对抗性文本解析，定位为护栏而非
# 形式化沙箱保证（已知绕过面见 docs/prd/modules/08-os-automation.md）。
# ---------------------------------------------------------------------------
TERMINAL_DEFAULT_TIMEOUT_SECONDS = 60
TERMINAL_MAX_TIMEOUT_SECONDS = 300
TERMINAL_MAX_COMMAND_CHARS = 8000
TERMINAL_MAX_OUTPUT_CHARS = 200_000
TERMINAL_SCRIPT_SCAN_MAX_BYTES = 256 * 1024
_GUARD_MAX_DEPTH = 3

# 终端命令不得读到 worker 自身凭证：否则一条 echo %OS_AUTOMATION_TOKEN% 即可
# 拿到直接调用本机 worker 全部端点的能力，绕过所有平台侧治理。
_CHILD_ENV_STRIPPED_KEYS = (
    "OS_AUTOMATION_TOKEN",
    "DESKTOP_BRIDGE_TOKEN",
    "BROWSER_AUTOMATION_TOKEN",
    "COMPUTER_CONTROL_TOKEN",
    "RENDER_WORKER_TOKEN",
    "WAKE_WORD_TOKEN",
)

# 物理删除语义的命令名（归一化后小写）→ 中文说明
_DELETE_COMMAND_NAMES: dict[str, str] = {
    "rm": "rm 物理删除（未经回收站）",
    "del": "del 物理删除（未经回收站）",
    "erase": "erase 物理删除（del 别名）",
    "rmdir": "rmdir 物理删除目录",
    "rd": "rd 物理删除目录（rmdir 别名）",
    "unlink": "unlink 物理删除文件",
    "remove-item": "PowerShell Remove-Item 物理删除",
    "ri": "PowerShell Remove-Item 别名（物理删除）",
    "shred": "shred 覆写删除（不可恢复）",
    "sdelete": "sdelete 安全删除（不可恢复）",
    "trash": "trash 第三方删除命令（不进平台回收站）",
    "format": "format 磁盘格式化（不可恢复）",
    "diskpart": "diskpart 分区/卷操作（不可恢复）",
}
_DELETE_NAME_SET: frozenset[str] = frozenset(_DELETE_COMMAND_NAMES)

# 删除语义的代码 API（仅在内联代码/脚本内容上扫描，避免 echo "rm -rf" 误伤）
_DELETE_CODE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"shutil\s*\.\s*rmtree\s*\(", re.IGNORECASE), "shutil.rmtree（Python 递归删除）"),
    (
        re.compile(r"os\s*\.\s*(?:remove|removedirs)\s*\(", re.IGNORECASE),
        "os.remove/removedirs（Python 删除）",
    ),
    (re.compile(r"os\s*\.\s*unlink\s*\(", re.IGNORECASE), "os.unlink（Python 删除文件）"),
    (re.compile(r"os\s*\.\s*rmdir\s*\(", re.IGNORECASE), "os.rmdir（Python 删除目录）"),
    (re.compile(r"\.\s*unlink\s*\(\s*\)", re.IGNORECASE), ".unlink()（Python 删除文件）"),
    (
        re.compile(r"\b(?:rmSync|unlinkSync|rmdirSync)\s*\(", re.IGNORECASE),
        "Node.js fs 同步删除 API",
    ),
    (
        re.compile(
            r"fs\s*\.\s*(?:promises\s*\.\s*)?(?:rm|rmSync|unlink|unlinkSync|rmdir|rmdirSync)\s*\(",
            re.IGNORECASE,
        ),
        "Node.js fs 删除 API",
    ),
    (
        re.compile(
            r"\[\s*(?:System\s*\.\s*)?IO\s*\.\s*(?:File|Directory)\s*\]\s*::\s*Delete",
            re.IGNORECASE,
        ),
        ".NET IO 删除 API",
    ),
)

# 可执行内联代码的解释器（其内联参数会被递归扫描）
_SHELL_INTERPRETERS = frozenset(
    {
        "cmd",
        "bash",
        "sh",
        "zsh",
        "dash",
        "powershell",
        "pwsh",
        "python",
        "python3",
        "py",
        "node",
        "perl",
        "ruby",
        "forfiles",
    }
)

# 解释器的内联代码开关 → 其后的剩余 token 视为代码文本再扫描
_INLINE_CODE_FLAGS: dict[str, tuple[str, ...]] = {
    "cmd": ("/c", "/k", "//c", "//k"),
    "powershell": ("-command", "-c", "-encodedcommand"),
    "pwsh": ("-command", "-c", "-encodedcommand"),
    "bash": ("-c",),
    "sh": ("-c",),
    "zsh": ("-c",),
    "dash": ("-c",),
    "python": ("-c",),
    "python3": ("-c",),
    "py": ("-c",),
    "node": ("-e", "--eval", "-p", "--print"),
    "perl": ("-e",),
    "ruby": ("-e",),
    "forfiles": ("/c",),
}

# 命令包装器：跳过它们（及其选项/数字/赋值参数）后再判定真实命令名（sudo rm / timeout 30 rm）
_COMMAND_WRAPPERS = frozenset(
    {"sudo", "doas", "env", "nohup", "exec", "command", "wsl", "busybox", "nice", "timeout", "start"}
)

_QUOTE_CHARS_RE = re.compile(r"['\"`]")
_EXEC_SUFFIX_RE = re.compile(r"\.(exe|cmd|bat|com|ps1)$", re.IGNORECASE)
_NUMERIC_ARG_RE = re.compile(r"\d+[smhd]?")
_INLINE_B64_RE = re.compile(r"(?:b64decode|atob)\s*\(\s*['\"]([A-Za-z0-9+/=]{16,})['\"]")


def _guard_block_reason(detail: str) -> str:
    """删除守卫的统一拒绝文案（含 Agent 可执行的替代路径）。"""
    return (
        f"终端删除命令已被系统阻断（{detail}）。本机删除只能走删除工具，"
        "请调用 os_recycle_bin(op=delete, paths=[...]) 移入回收站（可恢复、平台可见）；"
        "在补丁中删除文件请改用 os_file_task 的 V4A `*** Delete File`（同样进回收站）。"
    )


def _command_token_names(token: str) -> set[str]:
    """把单个 token 归一化为候选命令名集合。

    - 去引号（含 r''m 这类空引号拼接）与路径前缀、去 .exe/.cmd/.bat 等后缀；
    - 兼容 r\\m 形态（去掉反斜杠后再取一次），Windows 路径参数不受影响；
    - 仅按逗号切分（引号串内的空格是参数语义：`print('rm -rf')` 里的 `rm -rf`
      是一个字符串参数，不得拆成命令名 `rm`；`['rm','-f']` 才按逗号还原为命令名）。
    """
    names: set[str] = set()
    for variant in (token, token.replace("\\", "")):
        cleaned = _QUOTE_CHARS_RE.sub("", variant).strip()
        for piece in cleaned.split(","):
            piece = piece.split("/")[-1].split("\\")[-1]
            piece = _EXEC_SUFFIX_RE.sub("", piece).strip().lower()
            if piece:
                names.add(piece)
    return names


def _split_shell_tokens(text: str) -> list[str]:
    """引号感知分词：引号内空格不切分，引号符本身不入 token（r''m → rm）。"""
    tokens: list[str] = []
    current: list[str] = []
    quote = ""
    for ch in text:
        if quote:
            if ch == quote:
                quote = ""
            else:
                current.append(ch)
        elif ch in "'\"`":
            quote = ch
        elif ch.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def _iter_command_segments(text: str) -> list[tuple[str, bool]]:
    """按 shell 分隔符切分命令，返回 [(段文本, 是否管道下游)]。

    引号感知：引号内的 `;` `|` `(` 等是数据而非分隔符（`python -c "a; b()"` 必须
    整体作为一段，否则内联代码会被切碎、绕过删除扫描）。
    """
    segments: list[tuple[str, bool]] = []
    buf: list[str] = []
    pipe_target = False
    quote = ""
    idx = 0
    length = len(text)
    while idx < length:
        ch = text[idx]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ""
            idx += 1
            continue
        if ch in "'\"`":
            quote = ch
            buf.append(ch)
            idx += 1
            continue
        two = text[idx: idx + 2]
        if two in ("||", "&&"):
            _flush_segment(segments, buf, pipe_target)
            pipe_target = False
            idx += 2
            continue
        if ch == "|":
            _flush_segment(segments, buf, pipe_target)
            pipe_target = True
            idx += 1
            continue
        if ch in ";&\r\n(){}":
            _flush_segment(segments, buf, pipe_target)
            pipe_target = False
            idx += 1
            continue
        buf.append(ch)
        idx += 1
    _flush_segment(segments, buf, pipe_target)
    return segments


def _flush_segment(
    segments: list[tuple[str, bool]], buf: list[str], pipe_target: bool
) -> None:
    text = "".join(buf).strip()
    buf.clear()
    if text:
        segments.append((text, pipe_target))


def _skip_command_wrappers(tokens: list[str]) -> list[str]:
    """跳过 sudo/env/timeout 等命令包装器与选项，返回用于判定的有效 token 序列。"""
    idx = 0
    for _ in range(8):
        if idx >= len(tokens):
            break
        if not (_command_token_names(tokens[idx]) & _COMMAND_WRAPPERS):
            break
        idx += 1
        while idx < len(tokens):
            tok = tokens[idx]
            if tok.startswith("-") or "=" in tok or _NUMERIC_ARG_RE.fullmatch(tok):
                idx += 1
                continue
            break
    return tokens[idx:]


def _extract_inline_code(tokens: list[str]) -> list[tuple[str, str]]:
    """提取解释器内联代码，返回 [(代码文本, "inline"|"encoded")]。"""
    flags: set[str] = set()
    for name in _command_token_names(tokens[0]):
        flags.update(_INLINE_CODE_FLAGS.get(name, ()))
    if not flags:
        return []
    for idx in range(1, len(tokens)):
        low = tokens[idx].lower()
        if low in flags:
            code = " ".join(tokens[idx + 1:]).strip()
            if not code:
                return []
            kind = "encoded" if low == "-encodedcommand" else "inline"
            return [(code, kind)]
    return []


def _script_file_candidates(tokens: list[str], cwd: str) -> list[str]:
    """段内指向真实存在文件的参数（用于读脚本内容递归扫描）。"""
    out: list[str] = []
    base = cwd or os.getcwd()
    for tok in tokens[1:]:
        if not tok or tok.startswith("-") or tok.startswith("/") or len(tok) > 512:
            continue
        path = tok if os.path.isabs(tok) else os.path.join(base, tok)
        try:
            if os.path.isfile(path):
                out.append(path)
        except OSError:
            continue
    return out


def _read_script_text(path: str) -> str | None:
    """读取脚本内容用于扫描；二进制文件返回 None（不误报）。"""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(TERMINAL_SCRIPT_SCAN_MAX_BYTES)
    except OSError:
        return None
    if b"\x00" in raw[:4096]:
        return None
    # GBK/UTF-8 混用时按 UTF-8 忽略错误解码：删除命令均为 ASCII，不受影响
    return raw.decode("utf-8", errors="ignore")


def _decode_encoded_payload(payload: str) -> str:
    """解码 base64 载荷（UTF-8 或 UTF-16LE）；无法解码返回空串。"""
    import base64 as _b64

    text = str(payload or "").strip().strip("'\"")
    if not text or len(text) > 65536:
        return ""
    try:
        raw = _b64.b64decode(text + "=" * (-len(text) % 4))
    except Exception:
        return ""
    for encoding in ("utf-8", "utf-16-le"):
        try:
            decoded = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if "\x00" in decoded:
            continue
        if decoded.strip():
            return decoded
    return ""


def _match_dangerous_code(code: str) -> str | None:
    """在内联代码/脚本内容上匹配删除 API 模式。"""
    for pattern, label in _DELETE_CODE_PATTERNS:
        if pattern.search(code):
            return label
    return None


def _find_blocked_delete(
    command: str,
    *,
    cwd: str = "",
    _depth: int = 0,
) -> dict[str, str] | None:
    """扫描命令文本，命中删除语义返回 {command, reason}；未命中返回 None（fail-closed）。

    多层解析：分段 → 跳过包装器 → 段首命令名 → 组合形态（git rm / xargs / find /
    robocopy / rsync / 管道到解释器）→ 内联代码递归（含 base64 载荷与删除 API 模式）
    → 脚本文件内容递归。嵌套超过深度上限时拒绝执行（无法完成核验的命令不放行）。
    """
    if _depth > _GUARD_MAX_DEPTH:
        return {
            "command": str(command or "")[:200],
            "reason": _guard_block_reason("命令嵌套层级过深，无法完成删除风险核验"),
        }

    for seg_text, pipe_target in _iter_command_segments(str(command or "")):
        tokens = _split_shell_tokens(seg_text)
        if not tokens:
            continue
        head_tokens = _skip_command_wrappers(tokens)
        if not head_tokens:
            continue
        names = _command_token_names(head_tokens[0])

        # 1) 段首即删除命令
        for name in sorted(names):
            if name in _DELETE_NAME_SET:
                return {
                    "command": seg_text[:200],
                    "reason": _guard_block_reason(f"{name}：{_DELETE_COMMAND_NAMES[name]}"),
                }

        # 2) git rm / git clean（会移除工作区文件）
        if "git" in names:
            for tok in tokens[1:6]:
                if tok.lower() in {"rm", "clean"}:
                    return {
                        "command": seg_text[:200],
                        "reason": _guard_block_reason(f"git {tok.lower()}（移除工作区文件）"),
                    }

        # 3) xargs 后接删除命令
        if "xargs" in names:
            for tok in tokens[1:]:
                if _command_token_names(tok) & _DELETE_NAME_SET:
                    return {
                        "command": seg_text[:200],
                        "reason": _guard_block_reason("xargs 后接删除命令"),
                    }

        # 4) find -delete / find -exec rm
        if "find" in names:
            lowered = [tok.lower() for tok in tokens[1:]]
            if "-delete" in lowered:
                return {
                    "command": seg_text[:200],
                    "reason": _guard_block_reason("find -delete"),
                }
            for idx, tok in enumerate(lowered):
                if tok == "-exec":
                    for follow in tokens[idx + 1: idx + 3]:
                        if _command_token_names(follow) & _DELETE_NAME_SET:
                            return {
                                "command": seg_text[:200],
                                "reason": _guard_block_reason("find -exec 删除命令"),
                            }

        # 5) robocopy /MIR 与 rsync --delete（镜像/同步会删除目标端多余文件）
        if "robocopy" in names and any(tok.lower() == "/mir" for tok in tokens[1:]):
            return {
                "command": seg_text[:200],
                "reason": _guard_block_reason("robocopy /MIR 镜像删除"),
            }
        if "rsync" in names and any(tok.lower() == "--delete" for tok in tokens[1:]):
            return {
                "command": seg_text[:200],
                "reason": _guard_block_reason("rsync --delete"),
            }

        interpreter_names = names & _SHELL_INTERPRETERS
        inline_codes = _extract_inline_code(head_tokens) if interpreter_names else []
        script_files = _script_file_candidates(head_tokens, cwd) if interpreter_names else []

        # 6) 管道内容直接交给解释器（内容不可审计）
        if pipe_target and interpreter_names and not inline_codes and not script_files:
            return {
                "command": seg_text[:200],
                "reason": _guard_block_reason("管道内容直接交给解释器执行，无法审计"),
            }

        # 7) 内联代码递归（编码载荷先解码，再做文本与 API 模式扫描）
        for code, kind in inline_codes:
            if kind == "encoded":
                decoded = _decode_encoded_payload(code)
                if decoded:
                    hit = _find_blocked_delete(decoded, cwd=cwd, _depth=_depth + 1)
                    if hit:
                        return hit
                continue
            hit = _find_blocked_delete(code, cwd=cwd, _depth=_depth + 1)
            if hit:
                return hit
            label = _match_dangerous_code(code)
            if label:
                return {"command": seg_text[:200], "reason": _guard_block_reason(label)}
            for payload in _INLINE_B64_RE.findall(code):
                decoded = _decode_encoded_payload(payload)
                if decoded:
                    hit = _find_blocked_delete(decoded, cwd=cwd, _depth=_depth + 1)
                    if hit:
                        return hit

        # 8) 脚本文件内容递归
        for path in script_files:
            content = _read_script_text(path)
            if not content:
                continue
            hit = _find_blocked_delete(content, cwd=cwd, _depth=_depth + 1)
            if hit:
                return hit
            label = _match_dangerous_code(content)
            if label:
                return {
                    "command": os.path.basename(path),
                    "reason": _guard_block_reason(f"{label}（脚本 {os.path.basename(path)}）"),
                }

    return None


def _git_bash_candidates() -> list[str]:
    """GitBash 的 bash.exe 候选路径（显式配置优先，其次常见安装位置）。"""
    candidates: list[str] = []
    configured = _env("GIT_BASH_PATH")
    if configured:
        candidates.append(configured)
    for base in (
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramW6432"),
    ):
        if base:
            candidates.append(os.path.join(base, "Git", "bin", "bash.exe"))
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(os.path.join(local_appdata, "Programs", "Git", "bin", "bash.exe"))
    candidates.append(os.path.expanduser("~/scoop/apps/git/current/bin/bash.exe"))
    return candidates


def _resolve_terminal_shell(shell: str) -> tuple[str | None, str]:
    """解析 shell 可执行文件；返回 (可执行路径, 错误文案)。"""
    name = str(shell or "").strip().lower()
    if os.name == "nt":
        if name == "cmd":
            comspec = _env("COMSPEC") or os.path.join(
                os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe"
            )
            if os.path.isfile(comspec):
                return comspec, ""
            return None, "未找到 cmd.exe（COMSPEC 与 System32 均不可用）"
        if name in {"gitbash", "bash"}:
            for candidate in _git_bash_candidates():
                try:
                    if candidate and os.path.isfile(candidate):
                        return candidate, ""
                except OSError:
                    continue
            found = shutil.which("bash")
            # System32 下的 bash.exe 是 WSL 入口，不是 GitBash，不能当作 gitbash 使用
            if found and "system32" not in found.lower():
                return found, ""
            return None, (
                "未找到 GitBash（bash.exe）：请安装 Git for Windows，"
                "或设置 GIT_BASH_PATH 指向 bash.exe；shell=cmd 仍可用。"
            )
        return None, f"不支持的 shell：{shell}（Windows 支持 cmd / gitbash）"
    # 非 Windows：cmd/gitbash 统一映射到 sh，保持工具接口跨平台一致
    if name in {"cmd", "gitbash", "bash", "sh"}:
        found = shutil.which("sh") or shutil.which("bash")
        if found:
            return found, ""
        return None, "未找到 /bin/sh 或 bash"
    return None, f"不支持的 shell：{shell}"


def _build_child_env() -> dict[str, str]:
    """终端子进程环境：剥离 worker 自身凭证，避免命令直接读走平台 token。"""
    env = dict(os.environ)
    for key in _CHILD_ENV_STRIPPED_KEYS:
        env.pop(key, None)
    return env


def _truncate_output(
    text: str, limit: int = TERMINAL_MAX_OUTPUT_CHARS
) -> tuple[str, bool]:
    """输出限长（防止超长输出撑爆工具结果与上下文）。"""
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n...（输出超过 {limit} 字符上限，已截断）", True


def _decode_console_output(raw: bytes) -> str:
    """控制台输出解码：UTF-8 优先，回退系统 ANSI 代码页（中文 Windows 为 cp936）。"""
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for encoding in (locale.getpreferredencoding(False), "mbcs"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _kill_process_tree(proc: "subprocess.Popen[bytes]") -> None:
    """终止进程树（Windows: taskkill /T；POSIX: killpg），避免孙进程残留。"""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
            return
        except OSError:
            pass
    else:
        import signal as _signal

        try:
            os.killpg(os.getpgid(proc.pid), _signal.SIGKILL)
            return
        except (OSError, ProcessLookupError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _exec_operation(payload: dict[str, Any]) -> dict[str, Any]:
    """/exec 端点：在本机以 cmd / GitBash 执行单条命令（删除命令硬阻断）。"""
    command = str(payload.get("command") or "").strip()
    # 默认 gitbash（Unix 语法对模型更友好）；不可用时返回可读错误并提示改用 cmd
    shell = str(payload.get("shell") or "gitbash").strip().lower() or "gitbash"
    root = _resolve_safe_root(str(payload.get("working_dir") or "").strip())
    try:
        timeout_seconds = int(
            payload.get("timeout_seconds") or TERMINAL_DEFAULT_TIMEOUT_SECONDS
        )
    except (TypeError, ValueError):
        timeout_seconds = TERMINAL_DEFAULT_TIMEOUT_SECONDS
    timeout_seconds = max(1, min(timeout_seconds, TERMINAL_MAX_TIMEOUT_SECONDS))

    if not command:
        return {"ok": False, "error": "命令不能为空"}
    if len(command) > TERMINAL_MAX_COMMAND_CHARS:
        return {"ok": False, "error": f"命令过长（上限 {TERMINAL_MAX_COMMAND_CHARS} 字符）"}

    blocked = _find_blocked_delete(command, cwd=root)
    if blocked:
        return {
            "ok": False,
            "blocked": True,
            "command": blocked["command"],
            "reason": blocked["reason"],
            "error": blocked["reason"],
        }

    executable, error = _resolve_terminal_shell(shell)
    if executable is None:
        return {"ok": False, "error": error, "shell": shell}

    if os.name == "nt":
        args = (
            [executable, "/d", "/s", "/c", command]
            if shell == "cmd"
            else [executable, "-c", command]
        )
        popen_kwargs: dict[str, Any] = {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
        }
    else:
        args = [executable, "-c", command]
        popen_kwargs = {"start_new_session": True}

    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            args,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_build_child_env(),
            **popen_kwargs,
        )
    except OSError as exc:
        return {"ok": False, "error": f"启动命令失败: {exc}", "shell": shell}

    timed_out = False
    try:
        raw_out, raw_err = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_tree(proc)
        try:
            raw_out, raw_err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            raw_out, raw_err = b"", b""

    duration_ms = int((time.monotonic() - started) * 1000)
    stdout, out_truncated = _truncate_output(_decode_console_output(raw_out or b""))
    stderr, err_truncated = _truncate_output(_decode_console_output(raw_err or b""))
    exit_code = proc.returncode

    result: dict[str, Any] = {
        "ok": (not timed_out) and exit_code == 0,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "shell": shell,
        "cwd": root,
        "duration_ms": duration_ms,
        "truncated": out_truncated or err_truncated,
    }
    if timed_out:
        result["timed_out"] = True
        result["error"] = f"命令执行超时（{timeout_seconds}s），已终止进程树"
    elif exit_code != 0:
        result["error"] = f"命令退出码 {exit_code}"
    return result


class OsAutomationHandler(BaseHTTPRequestHandler):
    server_version = "YujianwoOSAutomation/0.1"

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
        shells = {
            name: os.path.isfile(exe) if exe else False
            for name in ("cmd", "gitbash")
            for exe, _err in [_resolve_terminal_shell(name)]
        }
        self._send_json(
            200,
            {
                "ok": True,
                "status": "ready",
                "os": os.name,
                "pid": os.getpid(),
                "token_configured": bool(_env("OS_AUTOMATION_TOKEN")),
                "terminal_shells": shells,
            },
        )

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/file", "/recycle", "/snapshot", "/exec"}:
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
            if parsed.path == "/snapshot":
                result = _snapshot_operation(payload)
                self._send_json(200, result)
                return
            if parsed.path == "/exec":
                result = _exec_operation(payload)
                self._send_json(200, result)
                return
        except Exception as exc:
            logger.exception("OS 自动化任务执行异常")
            self._send_json(
                500,
                {"ok": False, "error": str(exc), "traceback": traceback.format_exc()},
            )


def _gc_snapshots_on_startup() -> None:
    """worker 启动时惰性清理过期快照（失败仅记录日志，不阻断启动）。"""
    try:
        _gc_snapshots(_resolve_safe_root(""))
    except Exception as exc:
        logger.warning("启动时快照 GC 失败: %s", exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Yujianwo OS automation worker")
    parser.add_argument("--host", default=_env("OS_AUTOMATION_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(_env("OS_AUTOMATION_PORT", DEFAULT_PORT)))
    args = parser.parse_args()

    if not _env("OS_AUTOMATION_TOKEN"):
        print("OS_AUTOMATION_TOKEN 未配置，拒绝启动", file=__import__("sys").stderr)
        return 2

    _gc_snapshots_on_startup()
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
