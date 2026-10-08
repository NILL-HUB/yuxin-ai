"""沙箱代码执行工具。

复用深思考链路的 Baidu CFC / E2B / 阿里云沙箱后端，让普通 Agent 也能执行受隔离的
Python/Shell 命令。默认不启用：需要 `ENABLE_CODE_EXECUTION_TOOL=1` 且
`code_interpreter` 能力域的沙箱已在 admin 端启用（后端与凭证由沙箱配置中心解析）。

产物回收：每次调用是**独立沙箱**，执行完即销毁；执行期间新生成的文件经
`sandbox_artifact_collector`（与深思考共用同一实现）扫描、下载并存入文件中心，
以 `artifacts` 字段随返回值回给模型与前端。

工具 RPC 桥：调用方可通过 `tool_calls` 声明需要预取的平台工具结果，平台先按
已挂载工具执行，再把结果 JSON 以 `TOOL_RESULTS_JSON` 环境变量注入沙箱，脚本
读取后继续编排，避免多步 pipeline 反复占用模型上下文。
"""

from __future__ import annotations

import json
import logging
import shlex
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from internal.core.agent.backends import build_sandbox_backend
from internal.core.agent.entities.sandbox_policy_entity import SandboxPolicy
from internal.core.agent.entities.sandbox_runtime_entity import CAPABILITY_CODE_INTERPRETER
from internal.core.agent.sandbox_artifact_collector import (
    download_and_persist_artifacts,
    prepare_artifact_markers,
    scan_artifacts,
)
from internal.core.agent.sandbox_runtime_registry import get_sandbox_runtime
from internal.service.tool_credential_resolver import get_tool_setting

logger = logging.getLogger(__name__)

_ARTIFACT_FOLDER = "artifacts"


def _enabled() -> bool:
    flag = get_tool_setting("ENABLE_CODE_EXECUTION_TOOL").lower()
    if flag not in {"1", "true", "yes", "on"}:
        return False
    # 沙箱可用性以 admin 沙箱配置中心的运行时快照为准（唯一权威入口）
    return get_sandbox_runtime(CAPABILITY_CODE_INTERPRETER).enabled


def _supports_artifact_collection(backend: Any) -> bool:
    """产物收集要求后端同时具备 shell 执行与文件下载能力（远端执行句柄没有）。"""
    return callable(getattr(backend, "execute", None)) and callable(
        getattr(backend, "download_files", None)
    )


def _close_backend(backend: Any) -> None:
    """执行完即销毁沙箱：每次调用创建独立沙箱，不关闭会一直挂到沙箱超时。"""
    close_method = getattr(backend, "close", None)
    if not callable(close_method):
        return
    try:
        close_method()
    except Exception:
        logger.debug("关闭沙箱后端时发生异常", exc_info=True)


class ExecuteCodeInput(BaseModel):
    command: str = Field(..., description="要在沙箱内执行的 Shell/Python 命令，例如 python3 -c 'print(1+1)'")
    tool_calls: list[dict] = Field(
        default_factory=list,
        description="执行前由平台预取的平台工具调用，格式 [{\"name\": \"web_search\", \"arguments\": {...}}]。"
        "结果会以 TOOL_RESULTS_JSON 环境变量注入沙箱，脚本读取后继续编排。",
    )


class ExecuteCodeTool(BaseTool):
    name: str = "execute_code"
    description: str = (
        "在隔离沙箱内执行 Shell/Python 命令并返回 stdout/stderr 与退出码。"
        "沙箱每次调用独立创建、执行完即销毁，因此写入与运行要在同一条命令里完成。"
        "需要交付给用户的文件（报告、表格、图片、压缩包等）请写入 ~/artifacts 目录，"
        "其他位置（如 /tmp、/mnt/data）新生成的文件也会被收集：执行结束后它们会自动"
        "存入文件中心并随返回值 artifacts 字段返回，无需把文件内容打印到 stdout。"
        "可通过 tool_calls 预取平台工具结果，脚本读取 TOOL_RESULTS_JSON 后继续编排，"
        "避免多步 pipeline 反复占用模型上下文。默认未启用时需要管理员开启。"
    )
    args_schema: type[BaseModel] = ExecuteCodeInput
    tool_registry: dict[str, Any] | None = None
    account_id: str = ""

    def _run(self, command: str, tool_calls: list[dict] | None = None, **kwargs: Any) -> str:
        normalized = str(command or "").strip()
        if not normalized:
            return json.dumps({"ok": False, "error": "命令不能为空"}, ensure_ascii=False)
        if not _enabled():
            return json.dumps(
                {
                    "ok": False,
                    "error": "代码执行工具未启用：需要 ENABLE_CODE_EXECUTION_TOOL=1 且 code_interpreter 沙箱已在 admin 端启用",
                },
                ensure_ascii=False,
            )
        tool_results = self._resolve_tool_calls(tool_calls or [])
        env_prefix = ""
        if tool_results:
            env_prefix = (
                "export TOOL_RESULTS_JSON="
                + shlex.quote(json.dumps(tool_results, ensure_ascii=False, default=str))
                + "; "
            )
        backend = None
        try:
            runtime = get_sandbox_runtime(CAPABILITY_CODE_INTERPRETER)
            backend_cls = globals().get("_BACKEND_CLS")
            backend = (
                backend_cls(runtime)
                if backend_cls is not None
                else build_sandbox_backend(runtime)
            )
            if backend is None:
                raise RuntimeError(
                    f"沙箱后端不可用：backend={runtime.backend} reason={runtime.reason}"
                )
            artifact_roots = SandboxPolicy.build_fallback_artifact_roots("")
            collect_artifacts = bool(self.account_id) and _supports_artifact_collection(backend)
            marker_paths_by_root: dict[str, str] = {}
            if collect_artifacts:
                # 执行前打标记：扫描时只认标记之后新增的文件，排除模板自带文件
                marker_paths_by_root = prepare_artifact_markers(
                    backend,
                    roots=artifact_roots,
                    marker_name=SandboxPolicy.build_artifact_marker_name(""),
                )
            result = backend.execute(env_prefix + normalized)
            payload: dict[str, Any] = {
                "ok": getattr(result, "exit_code", 1) == 0,
                "exit_code": getattr(result, "exit_code", 1),
                "output": str(getattr(result, "output", "") or ""),
                "truncated": bool(getattr(result, "truncated", False)),
                "error": getattr(result, "error", None),
                "tool_results": tool_results,
            }
            if collect_artifacts:
                artifacts, artifact_failures = self._collect_artifacts(
                    backend=backend,
                    roots=artifact_roots,
                    marker_paths_by_root=marker_paths_by_root,
                )
                if artifacts:
                    payload["artifacts"] = artifacts
                if artifact_failures:
                    payload["artifact_failures"] = artifact_failures
            return json.dumps(payload, ensure_ascii=False)
        except Exception as exc:
            logger.warning("代码执行失败", exc_info=True)
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        finally:
            _close_backend(backend)

    def _collect_artifacts(
        self,
        *,
        backend: Any,
        roots: list[str],
        marker_paths_by_root: dict[str, str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """收集本次执行新生成的沙箱文件并存入文件中心。

        产物收集是**增值能力而非主链路**：任何一步失败都只记入 failures，
        不影响命令本身的执行结果回传。
        """
        try:
            scan_result = scan_artifacts(
                backend,
                roots=roots,
                marker_paths_by_root=marker_paths_by_root,
            )
            if scan_result.failed:
                return [], [{"path": "", "error": f"扫描产物目录失败：{scan_result.error}"}]
            if not scan_result.paths:
                return [], []

            persisted = download_and_persist_artifacts(
                backend,
                account_id=self.account_id,
                paths=scan_result.paths,
                folder=_ARTIFACT_FOLDER,
            )
            failures = [{"path": path, "error": error} for path, error in persisted.failures]
            return persisted.artifacts, failures
        except Exception as exc:  # noqa: BLE001
            logger.warning("沙箱产物收集失败", exc_info=True)
            return [], [{"path": "", "error": f"产物收集失败：{exc}"}]

    def _resolve_tool_calls(self, tool_calls: list[dict]) -> list[dict]:
        results: list[dict] = []
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            name = str(call.get("name") or "").strip()
            arguments = call.get("arguments") or {}
            if not name:
                continue
            tool = (self.tool_registry or {}).get(name)
            if tool is None:
                results.append(
                    {
                        "name": name,
                        "ok": False,
                        "error": "tool_not_available",
                    }
                )
                continue
            try:
                output = tool.invoke(arguments if isinstance(arguments, dict) else {})
                results.append({"name": name, "ok": True, "output": output})
            except Exception as exc:  # noqa: BLE001
                logger.warning("execute_code 预取工具失败: %s", exc, exc_info=True)
                results.append(
                    {
                        "name": name,
                        "ok": False,
                        "error": str(exc),
                    }
                )
        return results

    async def _arun(self, command: str, tool_calls: list[dict] | None = None, **kwargs: Any) -> str:
        return self._run(command=command, tool_calls=tool_calls, **kwargs)


def execute_code(**kwargs: Any) -> BaseTool:
    return ExecuteCodeTool(**kwargs)


# 测试注入点：单元测试可替换真实沙箱后端。
_BACKEND_CLS = None
