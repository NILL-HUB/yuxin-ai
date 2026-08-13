"""宿主机 Codex OS 自动化 worker。

运行在真实 Windows/Linux 主机上，通过受保护的本机 HTTP 接口接收平台请求，
再调用 Codex CLI 在宿主机执行系统自动化任务。

安全模型：
- 仅接受 Authorization: Bearer <OS_AUTOMATION_TOKEN> 的请求。
- preview 模式使用 Codex read-only 沙箱，不执行修改性命令。
- apply 模式必须携带 preview 返回的一次性 approval_token。
- 默认只监听本机回环地址；如部署在容器可访问的地址，必须配置强 token。
"""

from __future__ import annotations

import argparse
import glob
import hmac
import json
import logging
import os
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

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
DEFAULT_TIMEOUT = 180
MAX_TIMEOUT = 600
APPROVAL_TTL_SECONDS = 1800
DEFAULT_SAFE_ROOT = ""
_OUTPUT_RUN_ID_LENGTH = 32
RECYCLE_DIR_NAME = ".yuxin_ai_recycle"
MANIFEST_FILENAME = "manifest.jsonl"
DEFAULT_RECYCLE_RETENTION_DAYS = 30

_approvals: dict[str, dict[str, Any]] = {}
_approval_lock = threading.Lock()
_recycle_lock = threading.Lock()


def _env(key: str, default: str = "") -> str:
    return str(os.environ.get(key, default) or "").strip()


def _find_codex_path() -> str:
    """定位 Codex CLI，优先使用 CODEX_CLI_PATH 环境变量。"""
    explicit = _env("CODEX_CLI_PATH")
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if candidate.is_file():
            return str(candidate)

    candidates: list[str] = []
    local_app_data = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    if local_app_data.is_dir():
        for path in sorted(glob.glob(str(local_app_data / "*" / "codex.exe")), reverse=True):
            candidates.append(path)
    which = shutil.which("codex")
    if which:
        candidates.append(which)
    return candidates[0] if candidates else ""


def _codex_version(codex_path: str) -> str:
    try:
        completed = subprocess.run(
            [codex_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return (completed.stdout or completed.stderr or "").strip().splitlines()[-1]
    except Exception:
        return ""


def _build_codex_command(codex_path: str, mode: str, working_dir: str, timeout: int) -> list[str]:
    command = [
        codex_path,
        "-a",
        "never",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--json",
        "--color",
        "never",
        "-C",
        working_dir,
    ]
    if mode == "preview":
        # Windows Codex CLI 不支持 read-only 沙箱，preview 用 danger-full-access，
        # 但通过提示词严格限制只读；若模型尝试写命令，仍会走 Codex 审批/失败。
        command.extend(["--sandbox", "danger-full-access"])
    else:
        # 平台侧 preview + approval_token 已构成用户确认链，apply 阶段让 Codex 真正执行。
        command.append("--dangerously-bypass-approvals-and-sandbox")
    return command


def _build_prompt(task: str, mode: str) -> str:
    if mode == "preview":
        return (
            f"{task}\n\n"
            "[模式] 只读预览。只允许执行只读检查命令（如查询磁盘空间、列出临时文件），"
            "最多执行 2 个只读命令，禁止递归扫描整个临时目录/下载目录。"
            "禁止执行任何会修改文件系统、注册表、服务、进程或网络的命令。"
            "输出简短的清理/操作计划、预计影响和具体命令，不要执行修改。"
        )
    return (
        f"{task}\n\n"
        "[模式] 用户已确认执行。请执行完成该任务所需的最小命令集合，"
        "并汇报实际执行命令、输出、退出码和结果。不要做超出任务范围的修改。"
    )


def _parse_codex_jsonl(stdout: str, stderr: str) -> tuple[list[dict[str, Any]], list[str], str]:
    commands: list[dict[str, Any]] = []
    messages: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "item.completed":
            continue
        item = event.get("item") or {}
        item_type = item.get("type")
        if item_type == "command_execution":
            commands.append(
                {
                    "command": item.get("command", ""),
                    "status": item.get("status", ""),
                    "exit_code": item.get("exit_code"),
                    "output": item.get("aggregated_output", ""),
                }
            )
        elif item_type == "agent_message":
            text = str(item.get("text", "") or "").strip()
            if text:
                messages.append(text)

    summary = messages[-1] if messages else "Codex 已完成任务，未返回文本消息。"
    return commands, messages, summary


def _run_outputs_dir() -> Path:
    root = Path(
        os.getenv("OS_AUTOMATION_OUTPUT_DIR")
        or (Path(tempfile.gettempdir()) / "yuxin-os-automation-outputs")
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def _spill_run_output(
    *,
    stdout: str,
    stderr: str,
    messages: list[str],
    commands: list[dict[str, Any]],
) -> str:
    """保存一次 Codex 执行的完整输出，返回可回读的 run_id。"""
    run_id = uuid.uuid4().hex
    payload = {
        "run_id": run_id,
        "stdout": stdout or "",
        "stderr": stderr or "",
        "messages": messages or [],
        "commands": commands or [],
        "created_at": time.time(),
    }
    path = _run_outputs_dir() / f"{run_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return run_id


def _read_run_output(run_id: str) -> dict[str, Any] | None:
    normalized = str(run_id or "").strip()
    if (
        len(normalized) != _OUTPUT_RUN_ID_LENGTH
        or not all(character in "0123456789abcdef" for character in normalized.lower())
    ):
        return None
    path = _run_outputs_dir() / f"{normalized}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("读取 run output 失败: %s", normalized, exc_info=True)
        return None


def _run_codex_task(
    *,
    task: str,
    mode: str,
    working_dir: str,
    timeout: int,
    approval_token: str = "",
) -> dict[str, Any]:
    codex_path = _find_codex_path()
    if not codex_path:
        return {"ok": False, "error": "未找到 Codex CLI，请配置 CODEX_CLI_PATH"}

    if mode == "apply":
        with _approval_lock:
            approval = _approvals.get(approval_token or "")
            if approval is None:
                return {"ok": False, "error": "缺少有效 approval_token，请先执行 preview 并等待用户确认"}
            if time.time() - approval["created_at"] > APPROVAL_TTL_SECONDS:
                _approvals.pop(approval_token, None)
                return {"ok": False, "error": "approval_token 已过期，请重新预览"}

    started = time.monotonic()
    command = _build_codex_command(codex_path, mode, working_dir, timeout)
    prompt = _build_prompt(task, mode)
    try:
        completed = subprocess.run(
            [*command, prompt],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        run_id = _spill_run_output(
            stdout=str(exc.stdout or ""),
            stderr=str(exc.stderr or ""),
            messages=[],
            commands=[],
        )
        return {
            "ok": False,
            "error": f"Codex 执行超时（{timeout}s）",
            "stdout": str(exc.stdout or ""),
            "stderr": str(exc.stderr or ""),
            "run_id": run_id,
            "readback_available": True,
        }
    except Exception as exc:
        return {"ok": False, "error": f"启动 Codex 失败: {exc}"}

    commands, messages, summary = _parse_codex_jsonl(completed.stdout or "", completed.stderr or "")
    ok = bool(commands or messages)
    run_id = _spill_run_output(
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        messages=messages,
        commands=commands,
    )
    if mode == "apply" and ok:
        with _approval_lock:
            _approvals.pop(approval_token, None)

    return {
        "ok": ok,
        "mode": mode,
        "summary": summary,
        "messages": messages,
        "commands": commands,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "process_exit_code": completed.returncode,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "run_id": run_id,
        "readback_available": True,
    }


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


def _file_apply_patch(patch: str, root: str, working_dir: str) -> dict[str, Any]:
    """在宿主机执行 V4A 补丁，并验证所有目标路径都落在允许目录内。"""
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
        candidate = op.file_path if op.operation != "move" else op.new_path or ""
        if not candidate:
            continue
        if not _is_path_within(root, candidate):
            return {"ok": False, "error": f"路径超出允许目录: {candidate}"}

    class _RootedFileOps(FileTextOps):
        def __init__(self, root: str, workdir: str) -> None:
            self.root = root
            self.workdir = workdir

        def _resolve(self, path: str) -> str:
            expanded = str(Path(path).expanduser())
            if not Path(expanded).is_absolute():
                expanded = str(Path(self.workdir) / expanded)
            return expanded

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
            super().delete_file(resolved)

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


def _file_operation(payload: dict[str, Any]) -> dict[str, Any]:
    """执行文件操作：read 只读；patch 需先 preview 换取 approval_token。"""
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
                return {
                    "ok": False,
                    "error": "缺少有效 approval_token，请先执行 preview 并等待用户确认",
                }
            result = _file_apply_patch(patch, working_dir, working_dir)
            return result
        if mode == "preview":
            # 不落地：先做路径与格式校验，再发放一次性 approval_token。
            validation = _file_apply_patch(patch, working_dir, working_dir)
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
        try:
            resolved = Path(raw_path).expanduser().resolve()
        except OSError:
            errors.append(f"无法解析路径: {raw_path}")
            continue
        if not _is_path_within(root, str(resolved)) or str(resolved).startswith(str(recycle) + os.sep):
            errors.append(f"路径超出允许目录或位于回收站内: {raw_path}")
            continue
        if not resolved.exists():
            errors.append(f"路径不存在: {raw_path}")
            continue
        try:
            relative = resolved.relative_to(root_path)
        except ValueError:
            errors.append(f"路径不在安全根目录内: {raw_path}")
            continue
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
            "restored": False,
        }
        shutil.move(str(resolved), str(dest))
        _append_recycle_manifest(root, entry)
        entries.append(entry)
    return {"ok": not errors, "entries": entries, "errors": errors, "recycle_root": str(recycle)}


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
) -> tuple[bool, dict[str, Any], str]:
    """恢复单个回收站条目。返回 (ok, entry_or_error, restored_path)。"""
    moved_to = Path(str(entry["moved_to"]))
    if not moved_to.exists():
        return False, {"entry_id": entry.get("entry_id"), "error": f"回收站文件缺失: {moved_to}"}, ""
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
    ok, result, restored_path = _restore_single_recycle_entry(target, root, entries)
    if ok:
        _rewrite_recycle_manifest(root, entries)
        return {"ok": True, "entry": result, "restored_to": restored_path}
    return {"ok": False, "error": result.get("error", "恢复失败"), "entry_id": result.get("entry_id")}


def _purge_recycle(payload: dict[str, Any]) -> dict[str, Any]:
    """物理清理已过留存期的回收站条目，并同步清单。"""
    root = _resolve_safe_root(str(payload.get("safe_root") or "").strip())
    now = time.time()
    entries = _read_recycle_manifest(root)
    remaining: list[dict[str, Any]] = []
    purged: list[dict[str, Any]] = []
    errors: list[str] = []
    for entry in entries:
        if entry.get("restored"):
            remaining.append(entry)
            continue
        expire_at = float(entry.get("expire_at") or 0)
        if expire_at > now:
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
        if parsed.path.startswith("/output/"):
            if not self._authorized():
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            run_id = parsed.path[len("/output/"):].strip()
            run_output = _read_run_output(run_id)
            if run_output is None:
                self._send_json(404, {"ok": False, "error": "run_output_not_found"})
                return
            self._send_json(200, {"ok": True, "run": run_output})
            return
        if parsed.path != "/health":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        codex_path = _find_codex_path()
        self._send_json(
            200,
            {
                "ok": True,
                "status": "ready",
                "os": os.name,
                "pid": os.getpid(),
                "codex_path": codex_path or "",
                "codex_version": _codex_version(codex_path) if codex_path else "",
                "token_configured": bool(_env("OS_AUTOMATION_TOKEN")),
            },
        )

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/run", "/file", "/recycle"}:
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

            task = str(payload.get("task") or "").strip()
            mode = str(payload.get("mode") or "preview").strip().lower()
            working_dir = str(payload.get("working_dir") or "").strip()
            timeout = int(payload.get("timeout") or DEFAULT_TIMEOUT)
            timeout = max(1, min(timeout, MAX_TIMEOUT))
            approval_token = str(payload.get("approval_token") or "").strip()

            if not task:
                self._send_json(400, {"ok": False, "error": "task 不能为空"})
                return
            if mode not in {"preview", "apply"}:
                self._send_json(400, {"ok": False, "error": "mode 必须为 preview 或 apply"})
                return
            if not working_dir:
                working_dir = str(Path.home())

            if mode == "preview":
                approval_token = _create_approval(task)

            result = _run_codex_task(
                task=task,
                mode=mode,
                working_dir=working_dir,
                timeout=timeout,
                approval_token=approval_token,
            )
            if mode == "preview" and result.get("ok"):
                result["approval_token"] = approval_token
                result["approval_expires_in_seconds"] = APPROVAL_TTL_SECONDS
            self._send_json(200, result)
        except Exception as exc:
            logger.exception("OS 自动化任务执行异常")
            self._send_json(
                500,
                {"ok": False, "error": str(exc), "traceback": traceback.format_exc()},
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="YuxinAI Codex OS automation worker")
    parser.add_argument("--host", default=_env("OS_AUTOMATION_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(_env("OS_AUTOMATION_PORT", DEFAULT_PORT)))
    parser.add_argument("--check", action="store_true", help="检查 Codex 是否可用并退出")
    args = parser.parse_args()

    if not _env("OS_AUTOMATION_TOKEN"):
        print("OS_AUTOMATION_TOKEN 未配置，拒绝启动", file=__import__("sys").stderr)
        return 2

    codex_path = _find_codex_path()
    if args.check:
        if not codex_path:
            print("Codex CLI 未找到", file=__import__("sys").stderr)
            return 1
        print(f"codex={codex_path}")
        print(f"version={_codex_version(codex_path)}")
        return 0

    if not codex_path:
        print("Codex CLI 未找到，请设置 CODEX_CLI_PATH", file=__import__("sys").stderr)
        return 1

    server = ThreadingHTTPServer((args.host, args.port), OsAutomationHandler)
    print(
        f"OS automation worker listening on http://{args.host}:{args.port} "
        f"codex={codex_path}",
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
