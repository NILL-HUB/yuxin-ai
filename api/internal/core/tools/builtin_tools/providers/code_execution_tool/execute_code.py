"""沙箱代码执行工具。

复用深思考链路的 Baidu CFC / E2B 沙箱后端，让普通 Agent 也能执行受隔离的
Python/Shell 命令。默认不启用：需要 `ENABLE_CODE_EXECUTION_TOOL=1` 且
配置 `E2B_API_KEY` / `E2B_DOMAIN`。

工具 RPC 桥：调用方可通过 `tool_calls` 声明需要预取的平台工具结果，平台先按
已挂载工具执行，再把结果 JSON 以 `TOOL_RESULTS_JSON` 环境变量注入沙箱，脚本
读取后继续编排，避免多步 pipeline 反复占用模型上下文。
"""

from __future__ import annotations

import json
import logging
import os
import shlex
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    flag = str(os.getenv("ENABLE_CODE_EXECUTION_TOOL", "")).strip().lower()
    if flag not in {"1", "true", "yes", "on"}:
        return False
    return bool(os.getenv("E2B_API_KEY", "").strip() and os.getenv("E2B_DOMAIN", "").strip())


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
        "可通过 tool_calls 预取平台工具结果，脚本读取 TOOL_RESULTS_JSON 后继续编排，"
        "避免多步 pipeline 反复占用模型上下文。默认未启用时需要管理员开启。"
    )
    args_schema: type[BaseModel] = ExecuteCodeInput
    tool_registry: dict[str, Any] | None = None

    def _run(self, command: str, tool_calls: list[dict] | None = None, **kwargs: Any) -> str:
        normalized = str(command or "").strip()
        if not normalized:
            return json.dumps({"ok": False, "error": "命令不能为空"}, ensure_ascii=False)
        if not _enabled():
            return json.dumps(
                {
                    "ok": False,
                    "error": "代码执行工具未启用：需要 ENABLE_CODE_EXECUTION_TOOL=1 且配置 E2B_API_KEY/E2B_DOMAIN",
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
        try:
            from internal.core.agent.backends import BaiduCfcSandboxBackend

            backend_cls = globals().get("_BACKEND_CLS") or BaiduCfcSandboxBackend
            backend = backend_cls(
                api_key=os.environ.get("E2B_API_KEY"),
                domain=os.environ.get("E2B_DOMAIN"),
                template_alias=os.environ.get("SANDBOX_TEMPLATE_ALIAS") or None,
                fallback_template_alias=os.environ.get("SANDBOX_FALLBACK_TEMPLATE_ALIAS") or None,
            )
            result = backend.execute(env_prefix + normalized)
            return json.dumps(
                {
                    "ok": getattr(result, "exit_code", 1) == 0,
                    "exit_code": getattr(result, "exit_code", 1),
                    "output": str(getattr(result, "output", "") or ""),
                    "truncated": bool(getattr(result, "truncated", False)),
                    "error": getattr(result, "error", None),
                    "tool_results": tool_results,
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            logger.warning("代码执行失败", exc_info=True)
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

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
