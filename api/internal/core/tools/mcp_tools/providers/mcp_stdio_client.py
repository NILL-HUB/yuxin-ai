"""MCP stdio 传输客户端。

基于官方 mcp Python SDK 的 stdio_client + ClientSession 实现 MCP stdio 协议的同步桥接。

设计要点：
- Flask 是同步 WSGI，但 mcp SDK 是异步的，使用 asyncio.run 在同步上下文里执行协程
- 短连接模式：每次调用重新 spawn 子进程，握手后执行一次请求即关闭
- 调用前必须 decrypt_env(binding.get("env")) 解密环境变量
- 超时控制：用 binding.get("timeout_seconds") 限制子进程执行时间
- 进程清理：无论成功失败都要 terminate 子进程
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MCP_STDIO_TIMEOUT_SECONDS = 30


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


class McpStdioClient:
    """MCP stdio 客户端：同步桥接官方 mcp SDK 的异步 API。"""

    def list_tools_sync(self, binding: dict[str, Any]) -> list[dict[str, Any]]:
        """启动 stdio 子进程 → initialize 握手 → tools/list → 关闭。

        返回 [{name, description, inputSchema, ...}] 工具定义列表。
        """
        return self._run_async(self._list_tools_async(binding))

    def call_tool_sync(
        self,
        binding: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """启动 stdio 子进程 → initialize → tools/call → 关闭。

        返回 dict 形式的 CallToolResult：{"content": [...], "isError": bool, ...}
        """
        return self._run_async(self._call_tool_async(binding, tool_name, arguments))

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #

    def _run_async(self, coro):
        """在同步上下文里运行协程；兼容已有事件循环场景（fallback 到线程）。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is None:
            return asyncio.run(coro)

        # 已有事件循环（如被异步框架意外调用）：在新线程里跑新事件循环
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(coro)).result()

    def _build_stdio_params(self, binding: dict[str, Any]) -> tuple[str, list[str], dict[str, str], int]:
        """从 binding 解析 stdio 子进程参数：command, args, env, timeout。"""
        command = _normalize_text(binding.get("command"))
        if not command:
            raise ValueError("stdio 绑定缺少 command")

        # 解析 args 列表
        raw_args = binding.get("args") or []
        if not isinstance(raw_args, list):
            raw_args = []
        args = [str(arg) for arg in raw_args if str(arg) != ""]

        # 解密 env（落库为加密值）
        env = self._build_subprocess_env(binding)

        timeout = int(binding.get("timeout_seconds") or DEFAULT_MCP_STDIO_TIMEOUT_SECONDS)
        if timeout <= 0:
            timeout = DEFAULT_MCP_STDIO_TIMEOUT_SECONDS
        return command, args, env, timeout

    def _build_subprocess_env(self, binding: dict[str, Any]) -> dict[str, str]:
        """构造子进程环境变量：先继承当前进程 env，再 merge 解密后的 binding.env。"""
        env: dict[str, str] = {}
        for key, value in os.environ.items():
            env[str(key)] = str(value)

        encrypted_env = binding.get("env") or {}
        if isinstance(encrypted_env, dict):
            from internal.service.tool_credential_encryptor import decrypt_env

            decrypted = decrypt_env(encrypted_env)
            for key, value in decrypted.items():
                if value is None:
                    continue
                env[str(key)] = str(value)
        return env

    def _split_command(self, command: str, args: list[str]) -> tuple[str, list[str]]:
        """对 command 做基础解析：如果是单一可执行文件路径，原样返回；
        如果 command 自身包含空格且 args 为空，用 shlex 拆分。
        """
        if args:
            return command, list(args)
        if " " in command:
            tokens = shlex.split(command)
            if len(tokens) > 1:
                return tokens[0], tokens[1:]
        return command, []

    async def _list_tools_async(self, binding: dict[str, Any]) -> list[dict[str, Any]]:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        command, args, env, timeout = self._build_stdio_params(binding)
        executable, extra_args = self._split_command(command, args)
        server_params = StdioServerParameters(
            command=executable,
            args=extra_args,
            env=env,
        )

        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await asyncio.wait_for(session.initialize(), timeout=timeout)
                    result = await asyncio.wait_for(session.list_tools(), timeout=timeout)
                    return [self._tool_to_dict(tool) for tool in (result.tools or [])]
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"MCP stdio list_tools 超时（{timeout}s）") from exc
        except Exception:
            logger.exception("MCP stdio list_tools 调用失败")
            raise

    async def _call_tool_async(
        self,
        binding: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        command, args, env, timeout = self._build_stdio_params(binding)
        executable, extra_args = self._split_command(command, args)
        server_params = StdioServerParameters(
            command=executable,
            args=extra_args,
            env=env,
        )

        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await asyncio.wait_for(session.initialize(), timeout=timeout)
                    result = await asyncio.wait_for(
                        session.call_tool(tool_name, arguments=arguments or {}),
                        timeout=timeout,
                    )
                    return self._call_result_to_dict(result)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"MCP stdio call_tool 超时（{timeout}s）") from exc
        except Exception:
            logger.exception("MCP stdio call_tool 调用失败")
            raise

    @staticmethod
    def _tool_to_dict(tool: Any) -> dict[str, Any]:
        """将 mcp SDK 的 Tool 对象转为 dict（与 HTTP 通道的 tools/list 输出对齐）。"""
        if isinstance(tool, dict):
            return tool
        if hasattr(tool, "model_dump"):
            data = tool.model_dump(by_alias=True, exclude_none=False)
        elif hasattr(tool, "dict"):
            data = tool.dict(by_alias=True)
        else:
            data = {
                "name": getattr(tool, "name", ""),
                "description": getattr(tool, "description", ""),
                "inputSchema": getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None),
                "outputSchema": getattr(tool, "outputSchema", None) or getattr(tool, "output_schema", None),
                "annotations": getattr(tool, "annotations", None),
                "title": getattr(tool, "title", ""),
            }
        # 统一字段名为下划线风格（与 mcp_tool_factory._list_remote_tools 输出对齐）
        normalized: dict[str, Any] = {}
        for key in ("name", "description", "title", "annotations"):
            if key in data:
                normalized[key] = data[key]
        for key in ("inputSchema", "input_schema"):
            if key in data and data[key] is not None:
                normalized["inputSchema"] = data[key]
                normalized["input_schema"] = data[key]
        for key in ("outputSchema", "output_schema"):
            if key in data and data[key] is not None:
                normalized["outputSchema"] = data[key]
                normalized["output_schema"] = data[key]
        return normalized

    @staticmethod
    def _call_result_to_dict(result: Any) -> dict[str, Any]:
        """将 mcp SDK 的 CallToolResult 转为 dict（与 HTTP 通道的 tools/call 输出对齐）。"""
        if isinstance(result, dict):
            return result
        if hasattr(result, "model_dump"):
            data = result.model_dump(by_alias=True, exclude_none=False)
        elif hasattr(result, "dict"):
            data = result.dict(by_alias=True)
        else:
            data = {
                "content": getattr(result, "content", []),
                "isError": getattr(result, "isError", False),
            }
        # 保证关键字段存在
        data.setdefault("content", [])
        data.setdefault("isError", False)
        if "structuredContent" not in data and "structured_content" in data:
            data["structuredContent"] = data["structured_content"]
        return data
