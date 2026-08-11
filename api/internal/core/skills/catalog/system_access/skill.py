"""系统访问技能包的可执行实现。

提供 Codex 风格的沙箱系统访问能力：Shell 执行、文件读写、目录浏览。
所有路径都限制在工作区内，防止沙箱逃逸。
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _normalize_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = _normalize_text(value).lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _workspace_root() -> Path:
    configured = os.getenv("SYSTEM_ACCESS_WORKSPACE", "").strip()
    root = Path(configured).expanduser().resolve() if configured else (
        Path(tempfile.gettempdir()) / "yuxin_system_access"
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_path(relative: str) -> Path:
    root = _workspace_root()
    raw = _normalize_text(relative)
    if not raw or raw in {".", "/"}:
        return root
    candidate = (root / raw).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("路径超出工作区范围")
    return candidate


def _try_resolve(relative: str) -> tuple[Path | None, str | None]:
    try:
        return _resolve_path(relative), None
    except ValueError as exc:
        return None, str(exc)


def execute_shell(params: dict[str, Any]) -> dict[str, Any]:
    command = _normalize_text(params.get("command", ""))
    if not command:
        return {"ok": False, "error": "command 不能为空"}
    root = _workspace_root()
    cwd_raw = _normalize_text(params.get("cwd", ""))
    if cwd_raw:
        cwd, path_error = _try_resolve(cwd_raw)
        if path_error:
            return {"ok": False, "error": path_error}
    else:
        cwd = root
    timeout = _normalize_int(params.get("timeout"), 30)
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "error": f"命令执行超时（{timeout}s）",
            "stdout": str(exc.stdout or ""),
            "stderr": str(exc.stderr or ""),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def read_file(params: dict[str, Any]) -> dict[str, Any]:
    path, path_error = _try_resolve(_normalize_text(params.get("path", "")))
    if path_error:
        return {"ok": False, "error": path_error}
    assert path is not None
    max_chars = _normalize_int(params.get("max_chars"), 200000)
    if not path.is_file():
        return {"ok": False, "error": f"文件不存在: {path}"}
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "error": "文件不是 UTF-8 文本"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    truncated = len(content) > max_chars
    return {
        "ok": True,
        "path": str(path.relative_to(_workspace_root())),
        "content": content[:max_chars],
        "truncated": truncated,
        "total_chars": len(content),
    }


def write_file(params: dict[str, Any]) -> dict[str, Any]:
    path, path_error = _try_resolve(_normalize_text(params.get("path", "")))
    if path_error:
        return {"ok": False, "error": path_error}
    assert path is not None
    content = str(params.get("content", ""))
    overwrite = _normalize_bool(params.get("overwrite"), True)
    if path.exists() and not overwrite:
        return {"ok": False, "error": f"文件已存在，未允许覆盖: {path}"}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "path": str(path.relative_to(_workspace_root())),
        "chars": len(content),
    }


def list_directory(params: dict[str, Any]) -> dict[str, Any]:
    path, path_error = _try_resolve(_normalize_text(params.get("path", "")))
    if path_error:
        return {"ok": False, "error": path_error}
    assert path is not None
    recursive = _normalize_bool(params.get("recursive"), False)
    max_entries = _normalize_int(params.get("max_entries"), 500)
    if not path.exists():
        return {"ok": False, "error": f"目录不存在: {path}"}
    entries: list[dict[str, Any]] = []
    try:
        iterator = path.rglob("*") if recursive else path.iterdir()
        for item in sorted(iterator, key=lambda p: (not p.is_dir(), p.name.lower())):
            try:
                size = item.stat().st_size if item.is_file() else 0
            except OSError:
                size = 0
            entries.append(
                {
                    "name": item.name,
                    "path": str(item.relative_to(_workspace_root())),
                    "type": "dir" if item.is_dir() else "file",
                    "size": size,
                }
            )
            if len(entries) >= max_entries:
                break
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": str(path.relative_to(_workspace_root())), "entries": entries}


def get_workspace_info(params: dict[str, Any]) -> dict[str, Any]:
    root = _workspace_root()
    return {"ok": True, "workspace": str(root), "exists": root.exists()}
