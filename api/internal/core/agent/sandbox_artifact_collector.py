"""沙箱产物收集（深思考 / execute_code 共用的唯一实现）。

链路：准备标记 → 执行后扫描新增文件 → 下载 → 存入文件中心。

为什么必须唯一：深思考（DeepThinkingAgent）与 execute_code 工具都要把沙箱内
生成的文件接回平台文件中心；扫描/入库机制若各写一套，修正一处必漏另一处
（呼应「单一权威入口」）。本模块只承载**机制**（扫什么、怎么存），
时间线事件等编排留在各消费方。

约定（与 SandboxPolicy 同源）：
- 产物目录：`{base}/artifacts[/{task_id}]`（base ∈ /workspace、/home/user、/tmp、/mnt/data）
  以及代码解释器数据目录 `/mnt/data`；
- 标记文件：执行前在各候选目录创建 `.yujianwo_artifact_marker_*`，
  扫描时用 `find -newer` 过滤，保证只收集本次执行**新增**的文件
  （未成功打标记的目录不会被扫描，避免把目录里的旧文件误收成产物）。
"""
from __future__ import annotations

import logging
import mimetypes
import os
import shlex
from dataclasses import dataclass, field
from typing import Any

from internal.core.agent.entities.sandbox_policy_entity import SandboxPolicy

logger = logging.getLogger(__name__)

__all__ = [
    "ArtifactPersistResult",
    "ArtifactScanResult",
    "download_and_persist_artifacts",
    "extract_artifact_paths",
    "resolve_artifact_root",
    "prepare_artifact_markers",
    "scan_artifacts",
    "persist_sandbox_file",
]

# 单个产物的体积上限与单次收集的数量上限：超出即跳过并计入 failures。
# execute_code 的沙箱里可能出现数据集/依赖包等大文件，无限量下载会把 API 进程内存打爆。
MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
MAX_ARTIFACT_COUNT = 20


@dataclass(frozen=True)
class ArtifactScanResult:
    """一次产物扫描的结果：区分「扫描失败」与「确实没有新文件」。

    消费方据此如实出事件：失败（云函数/网络异常）应报错，
    没有新文件则是正常空结果（深思考据此提示"本次未生成可下载产物"）。
    """

    paths: list[str] = field(default_factory=list)
    failed: bool = False
    error: str = ""


@dataclass(frozen=True)
class ArtifactPersistResult:
    """下载 + 入库的结果：成功产物与逐条失败原因。

    机制层不抛异常（单文件失败不该让整批产物丢失）；
    调用方决定怎么呈现 failures（深思考出时间线错误事件，execute_code 回给模型）。
    """

    artifacts: list[dict[str, Any]] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)


def _read_response_field(response: Any, name: str, default: Any = None) -> Any:
    if isinstance(response, dict):
        return response.get(name, default)
    return getattr(response, name, default)


def extract_artifact_paths(output: Any) -> list[str]:
    """从 `find` 输出解析绝对路径（跳过 stderr 行与空行）。"""
    return [
        line.strip()
        for line in str(output or "").splitlines()
        if line.strip() and not line.startswith("[stderr]") and line.startswith("/")
    ]


def resolve_artifact_root(backend: Any, *, task_id: Any) -> str:
    """探测沙箱内第一个可写的产物根目录（`{base}/artifacts/{task_id}`）。

    全部不可写时回退 `SandboxPolicy.build_default_artifact_root(task_id)`。
    """
    default_root = SandboxPolicy.build_default_artifact_root(task_id)
    execute_method = getattr(backend, "execute", None)
    if not callable(execute_method):
        return default_root

    task_id_text = str(task_id)
    probe_command = (
        "for base in /workspace \"$HOME\" /home/user /tmp /mnt/data; do "
        f"if [ -n \"$base\" ] && mkdir -p \"$base/artifacts/{task_id_text}\" 2>/dev/null; then "
        f"printf '%s/artifacts/{task_id_text}' \"$base\"; "
        "exit 0; "
        "fi; "
        "done; "
        "exit 1"
    )
    result = execute_method(probe_command, timeout=15)
    if getattr(result, "exit_code", 1) != 0:
        logger.warning("探测沙箱产物目录失败，回退默认目录: %s", getattr(result, "output", ""))
        return default_root

    detected_root = str(getattr(result, "output", "")).strip()
    return detected_root if detected_root.startswith("/") else default_root


def prepare_artifact_markers(
    backend: Any,
    *,
    roots: list[str],
    marker_name: str,
) -> dict[str, str]:
    """执行前在候选目录打标记文件；返回 `{root: marker_path}`（仅成功创建的）。"""
    execute_method = getattr(backend, "execute", None)
    if not callable(execute_method) or not roots:
        return {}

    command_segments = []
    for root in roots:
        marker_path = f"{root}/{marker_name}"
        command_segments.append(
            f"if mkdir -p {shlex.quote(root)} 2>/dev/null; then "
            f": > {shlex.quote(marker_path)} && printf '%s\\n' {shlex.quote(marker_path)}; "
            "fi"
        )

    result = execute_method(" ; ".join(command_segments), timeout=15)
    if getattr(result, "exit_code", 1) != 0:
        logger.warning("准备沙箱产物标记失败，继续使用常规扫描: %s", getattr(result, "output", ""))
        return {}

    marked_roots: dict[str, str] = {}
    for marker_path in extract_artifact_paths(getattr(result, "output", "")):
        marked_roots[os.path.dirname(marker_path)] = marker_path
    return marked_roots


def scan_artifacts(
    backend: Any,
    *,
    roots: list[str],
    marker_paths_by_root: dict[str, str] | None = None,
    max_depth: int | None = None,
) -> ArtifactScanResult:
    """扫描 roots 下的产物文件。

    - 传 `marker_paths_by_root` 时：**只扫描有标记的目录**，并用
      `find -newer <marker>` 只取标记之后的新文件；
    - 未传时：按目录全量扫描（调用方须确保目录为本次任务专属，否则会收进旧文件）。
    """
    execute_method = getattr(backend, "execute", None)
    if not callable(execute_method) or not roots:
        return ArtifactScanResult()

    scan_roots = list(roots)
    if marker_paths_by_root is not None:
        scan_roots = [root for root in scan_roots if root in marker_paths_by_root]
        if not scan_roots:
            return ArtifactScanResult()

    command = SandboxPolicy.build_find_command(
        scan_roots,
        max_depth=max_depth,
        marker_paths_by_root=marker_paths_by_root,
    )
    result = execute_method(command, timeout=15)
    if getattr(result, "exit_code", 1) != 0:
        detail = str(getattr(result, "output", ""))
        logger.warning("扫描沙箱产物失败: %s", detail)
        return ArtifactScanResult(failed=True, error=detail)
    return ArtifactScanResult(paths=extract_artifact_paths(getattr(result, "output", "")))


def persist_sandbox_file(
    *,
    account_id: Any,
    path: str,
    content: bytes,
    folder: str = "artifacts",
) -> dict[str, Any]:
    """把单个沙箱文件存入文件中心（「产物」文件夹），返回用户侧 artifact 结构。

    **沙箱产物入库的唯一实现**：文件名取沙箱内 basename，MIME 按扩展名推断。

    Raises:
        Exception: 存储或建记录失败（由调用方决定发事件还是计入失败列表）。
    """
    from app.http.module import injector  # noqa: PLC0415
    from internal.service.file_center_service import FileCenterService  # noqa: PLC0415

    artifact_path = str(path)
    artifact_name = os.path.basename(artifact_path)
    mime_type = mimetypes.guess_type(artifact_name)[0] or "application/octet-stream"

    saved = injector.get(FileCenterService).save_generated_asset(
        account_id,
        filename=artifact_name,
        content=content,
        mime_type=mime_type,
        folder=folder,
    )
    upload_file = saved["upload_file"]
    return {
        "id": str(upload_file.id),
        "name": upload_file.name,
        "path": artifact_path,
        "size": upload_file.size,
        "extension": upload_file.extension,
        "mime_type": upload_file.mime_type,
        "url": saved["url"],
    }


def download_and_persist_artifacts(
    backend: Any,
    *,
    account_id: Any,
    paths: list[str],
    folder: str = "artifacts",
    max_files: int = MAX_ARTIFACT_COUNT,
    max_file_bytes: int = MAX_ARTIFACT_BYTES,
) -> ArtifactPersistResult:
    """逐个下载沙箱文件并存入文件中心（**沙箱产物下载 + 入库的唯一实现**）。

    逐文件下载而非一次传整批：单文件体积受控，避免大文件把进程内存打爆；
    超限文件与入库失败都记入 failures，不中断整批。

    调用方须自行保证应用上下文与会话作用域（Flask 请求内或 `session_scope()` 中）。
    """
    result = ArtifactPersistResult()
    download_method = getattr(backend, "download_files", None)
    if not callable(download_method):
        return result
    if not account_id:
        result.failures.extend((str(path), "缺少账号上下文，无法入库") for path in paths)
        return result

    for path in list(paths)[: max(0, max_files)]:
        artifact_path = str(path)
        responses = download_method([artifact_path]) or []
        response = responses[0] if responses else None
        if response is None:
            result.failures.append((artifact_path, "沙箱未返回下载结果"))
            continue

        content = _read_response_field(response, "content")
        error = _read_response_field(response, "error")
        if error or content is None:
            result.failures.append((artifact_path, str(error or "下载内容为空")))
            continue
        if len(content) > max_file_bytes:
            result.failures.append(
                (artifact_path, f"文件超过 {max_file_bytes // (1024 * 1024)}MB 上限，未入库"),
            )
            continue

        try:
            result.artifacts.append(
                persist_sandbox_file(
                    account_id=account_id,
                    path=artifact_path,
                    content=content,
                    folder=folder,
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("沙箱产物入库失败: %s", artifact_path, exc_info=True)
            result.failures.append((artifact_path, f"{type(e).__name__}: {e}"))

    for skipped in list(paths)[max(0, max_files):]:
        result.failures.append((str(skipped), f"超过单次 {max_files} 个产物上限，未入库"))

    return result
