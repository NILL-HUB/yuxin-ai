"""MCP 导入服务。

支持三种导入方式：
- 阶段 4.1：标准 mcp.json 配置文件批量导入（被 Claude Desktop / Cursor / Codex / VS Code 采用的事实标准）
- 阶段 4.2：URL 一键导入 + tools/list 预览
- 阶段 4.3：单个 MCP server JSON 文本导入 + 格式校验

设计要点：
- 复用 McpService.create_mcp_provider / update_mcp_provider 落库（headers/env 自动加密）
- 复用 McpToolFactory 的远端 tools/list 能力做 URL 预览
- name 冲突通过 overwrite 标志控制（False=跳过，True=覆盖更新）
- 错误处理：JSON 格式错误、URL 不可达、name 冲突等均给出清晰错误信息
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from injector import inject
from sqlalchemy import inspect

from internal.core.tools.mcp_tools.providers import McpToolFactory
from internal.entity.mcp_entity import normalize_mcp_transport
from internal.exception import ValidateErrorException
from internal.model import Account, McpProvider
from internal.schema.mcp_schema import CreateMcpProviderReq, UpdateMcpProviderReq
from internal.service.mcp_service import McpService
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)


# 支持的 transport 集合（与 mcp_schema._SUPPORTED_TRANSPORTS 保持一致）
_SUPPORTED_TRANSPORTS = {"http", "sse", "streamable_http", "streamable-http", "stdio"}
_HTTP_TRANSPORTS = {"http", "sse", "streamable_http", "streamable-http"}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _convert_headers_to_list(headers: Any) -> list[dict[str, str]]:
    """将 mcp.json 的多种 headers 形式统一转为 [{key, value}] 列表。

    支持输入：
    - dict: {"Authorization": "Bearer xxx"}  → [{"key": "Authorization", "value": "Bearer xxx"}]
    - list[dict]: [{"key": "Authorization", "value": "Bearer xxx"}]（原样返回）
    - list[dict]: [{"Authorization": "Bearer xxx"}]（兼容非标准格式）
    """
    if not headers:
        return []
    result: list[dict[str, str]] = []
    if isinstance(headers, dict):
        for key, value in headers.items():
            result.append({"key": str(key), "value": "" if value is None else str(value)})
    elif isinstance(headers, list):
        for item in headers:
            if not isinstance(item, dict):
                continue
            if "key" in item and "value" in item:
                result.append({"key": str(item.get("key")), "value": "" if item.get("value") is None else str(item.get("value"))})
                continue
            # 兼容 {header_name: header_value} 形式的单元素 dict
            for k, v in item.items():
                result.append({"key": str(k), "value": "" if v is None else str(v)})
    return result


def _build_form_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """将导入 payload 转换为 CreateMcpProviderReq/UpdateMcpProviderReq 所需的 form data。"""
    transport = normalize_mcp_transport(payload.get("transport")) or "streamable_http"
    return {
        "name": _normalize_text(payload.get("name")),
        "label": _normalize_text(payload.get("label")) or _normalize_text(payload.get("name")),
        "icon": _normalize_text(payload.get("icon")),
        "description": _normalize_text(payload.get("description")) or f"MCP server {_normalize_text(payload.get('name')) or 'imported'}",
        "category": _normalize_text(payload.get("category")) or "other",
        "transport": transport,
        "url": _normalize_text(payload.get("url")),
        "command": _normalize_text(payload.get("command")),
        "headers": _convert_headers_to_list(payload.get("headers")),
        "tool_names": list(payload.get("tool_names") or []),
        "args": list(payload.get("args") or []),
        "env": dict(payload.get("env") or {}),
        "timeout_seconds": int(payload.get("timeout_seconds") or 30),
    }


@inject
@dataclass
class McpImportService:
    """MCP 导入服务（mcp.json / URL / JSON 配置三种方式）。"""

    db: SQLAlchemy
    mcp_service: McpService
    _tool_factory: McpToolFactory = field(default_factory=McpToolFactory)

    # ------------------------------------------------------------------ #
    #  内部辅助                                                            #
    # ------------------------------------------------------------------ #

    def _resolve_account(self, account_id: UUID | str | None) -> Account:
        if not account_id:
            raise ValidateErrorException("account_id 不能为空")
        account = self.db.session.get(Account, account_id)
        if not account:
            raise ValidateErrorException("账号不存在")
        return account

    def _has_mcp_provider_table(self) -> bool:
        try:
            return inspect(self.db.engine).has_table(McpProvider.__tablename__)
        except Exception:
            return False

    def _find_existing_provider(self, account: Account, name: str) -> McpProvider | None:
        if not self._has_mcp_provider_table() or not name:
            return None
        return (
            self.db.session.query(McpProvider)
            .filter(McpProvider.account_id == account.id, McpProvider.name == name)
            .one_or_none()
        )

    def _validate_transport(self, transport: str, *, url: str, command: str, server_name: str = "") -> None:
        """校验 transport 合法性，以及对应 transport 的必填字段。"""
        if transport not in _SUPPORTED_TRANSPORTS:
            raise ValidateErrorException(
                f"server '{server_name}' transport 不支持: {transport}（仅支持 http/sse/streamable_http/stdio）"
            )
        if transport in _HTTP_TRANSPORTS:
            if not url:
                raise ValidateErrorException(f"server '{server_name}' transport={transport} 时 url 必填")
        elif transport == "stdio":
            if not command:
                raise ValidateErrorException(f"server '{server_name}' transport=stdio 时 command 必填")

    # ------------------------------------------------------------------ #
    #  阶段 4.1：标准 mcp.json 批量导入                                     #
    # ------------------------------------------------------------------ #

    def import_from_mcp_json(self, json_str: str, account_id: UUID | None = None, *, overwrite: bool = False) -> dict:
        """解析标准 mcp.json 并批量导入。

        标准 mcp.json 格式（mcpServers 字典）：
            {
              "mcpServers": {
                "server-name": {"type": "stdio", "command": "npx", "args": [...], "env": {...}},
                "another": {"type": "http", "url": "https://...", "headers": {...}}
              }
            }

        返回：{"imported": [...], "skipped": [...], "failed": [...]}
        """
        config = self._parse_json(json_str, label="mcp.json")
        if not isinstance(config, dict):
            raise ValidateErrorException("mcp.json 必须是 JSON 对象")

        servers = config.get("mcpServers") if "mcpServers" in config else config.get("mcp_servers")
        if not isinstance(servers, dict):
            raise ValidateErrorException("mcp.json 缺少 mcpServers 字段或该字段不是对象")

        account = self._resolve_account(account_id)
        imported: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        for server_name, server_config in servers.items():
            try:
                result = self._create_provider_from_mcp_config(
                    name=str(server_name),
                    config=server_config,
                    account=account,
                    overwrite=overwrite,
                )
                if result["action"] == "imported":
                    imported.append({
                        "name": server_name,
                        "id": result["id"],
                        "action": "created" if result.get("is_new") else "updated",
                    })
                elif result["action"] == "skipped":
                    skipped.append({
                        "name": server_name,
                        "id": result.get("id", ""),
                        "reason": result.get("reason", "已存在"),
                    })
            except Exception as exc:
                logging.exception("导入 mcp.json server 失败: %s", server_name)
                failed.append({"name": server_name, "error": str(exc)})

        return {"imported": imported, "skipped": skipped, "failed": failed}

    def _create_provider_from_mcp_config(
        self,
        name: str,
        config: Any,
        account: Account | None,
        *,
        overwrite: bool,
    ) -> dict[str, Any]:
        """将单个 mcp.json server 配置转为 DB 记录。"""
        if not isinstance(config, dict):
            raise ValidateErrorException(f"server '{name}' 配置必须是 JSON 对象")

        # 标准 mcp.json 用 type 字段表示 transport，兼容 transport 字段
        transport = normalize_mcp_transport(config.get("type") or config.get("transport")) or "streamable_http"
        url = _normalize_text(config.get("url"))
        command = _normalize_text(config.get("command"))
        args = list(config.get("args") or [])
        env = dict(config.get("env") or {})
        headers = _convert_headers_to_list(config.get("headers"))

        if not _normalize_text(name):
            raise ValidateErrorException("server 名称不能为空")
        self._validate_transport(transport, url=url, command=command, server_name=name)

        existing = self._find_existing_provider(account, name)
        if existing and not overwrite:
            return {
                "action": "skipped",
                "reason": "已存在且 overwrite=False",
                "id": str(existing.id),
            }

        payload = _build_form_payload({
            "name": name,
            "label": name,
            "icon": _normalize_text(config.get("icon")),
            "description": _normalize_text(config.get("description")) or f"MCP server {name}",
            "category": _normalize_text(config.get("category")) or "other",
            "transport": transport,
            "url": url,
            "command": command,
            "headers": headers,
            "tool_names": list(config.get("tool_names") or []),
            "args": args,
            "env": env,
            "timeout_seconds": int(config.get("timeout_seconds") or 30),
        })

        if existing and overwrite:
            form = UpdateMcpProviderReq(data=payload)
            if not form.validate():
                raise ValidateErrorException(f"server '{name}' 校验失败: {form.errors}")
            provider = self.mcp_service.update_mcp_provider(existing.id, form, account)
            return {"action": "imported", "id": str(provider.id), "is_new": False}

        form = CreateMcpProviderReq(data=payload)
        if not form.validate():
            raise ValidateErrorException(f"server '{name}' 校验失败: {form.errors}")
        provider = self.mcp_service.create_mcp_provider(form, account)
        return {"action": "imported", "id": str(provider.id), "is_new": True}

    # ------------------------------------------------------------------ #
    #  阶段 4.2：URL 一键导入 + tools/list 预览                             #
    # ------------------------------------------------------------------ #

    def preview_tools_from_url(
        self,
        url: str,
        headers: list | None = None,
        transport: str = "http",
    ) -> dict:
        """调用 tools/list 预览远端工具列表，不写 DB。

        返回：{"tools": [...], "server_info": {...}}
        """
        normalized_url = _normalize_text(url)
        if not normalized_url:
            raise ValidateErrorException("url 不能为空")
        normalized_transport = normalize_mcp_transport(transport) or "streamable_http"
        if normalized_transport not in _HTTP_TRANSPORTS:
            raise ValidateErrorException(
                f"预览仅支持 http/sse/streamable_http transport，当前: {normalized_transport}"
            )

        headers_list = _convert_headers_to_list(headers) if headers else []
        # 构造临时 binding 用于调用 McpToolFactory
        binding = {
            "name": "_preview",
            "description": "",
            "transport": normalized_transport,
            "url": normalized_url,
            "headers": headers_list,
            "tool_names": [],
            "timeout_seconds": 30,
            "enabled": True,
        }

        # 直接调用 _list_remote_tools 以便清晰抛出 URL 不可达等错误
        # （公开方法 list_remote_tool_definitions 会吞掉异常返回 []，无法区分"无工具"和"请求失败"）
        try:
            tool_definitions = self._tool_factory._list_remote_tools(binding)
        except Exception as exc:
            logging.exception("预览 MCP URL 工具列表失败: %s", exc)
            raise ValidateErrorException(f"无法访问 MCP 服务: {exc}") from exc

        tools = [
            {
                "name": _normalize_text(td.get("name")),
                "label": _normalize_text(td.get("title")) or _normalize_text(td.get("name")),
                "description": _normalize_text(td.get("description")),
            }
            for td in tool_definitions
            if isinstance(td, dict)
        ]
        return {
            "tools": tools,
            "server_info": {
                "url": normalized_url,
                "transport": normalized_transport,
                "tool_count": len(tools),
            },
        }

    def import_from_url(
        self,
        url: str,
        name: str,
        description: str,
        headers: list,
        account_id: UUID | None = None,
        *,
        transport: str = "http",
        category: str = "",
        icon: str = "",
    ) -> McpProvider:
        """从 URL 导入：先 preview 校验可达，再创建 DB 记录。"""
        normalized_url = _normalize_text(url)
        if not normalized_url:
            raise ValidateErrorException("url 不能为空")
        if not _normalize_text(name):
            raise ValidateErrorException("name 不能为空")
        normalized_transport = normalize_mcp_transport(transport) or "streamable_http"
        if normalized_transport not in _HTTP_TRANSPORTS:
            raise ValidateErrorException(
                f"URL 导入仅支持 http/sse/streamable_http transport，当前: {normalized_transport}"
            )

        # 先 preview 校验 URL 可达（不可达会抛出 ValidateErrorException）
        self.preview_tools_from_url(normalized_url, headers=headers, transport=normalized_transport)

        account = self._resolve_account(account_id)
        payload = _build_form_payload({
            "name": name,
            "label": name,
            "icon": icon,
            "description": description or f"MCP server {name}",
            "category": category or "other",
            "transport": normalized_transport,
            "url": normalized_url,
            "command": "",
            "headers": headers or [],
            "tool_names": [],
            "args": [],
            "env": {},
            "timeout_seconds": 30,
        })
        form = CreateMcpProviderReq(data=payload)
        if not form.validate():
            raise ValidateErrorException(f"URL 导入校验失败: {form.errors}")
        return self.mcp_service.create_mcp_provider(form, account)

    # ------------------------------------------------------------------ #
    #  阶段 4.3：JSON 文本导入 + 格式校验                                   #
    # ------------------------------------------------------------------ #

    def import_from_json(self, json_str: str, account_id: UUID, *, overwrite: bool = False) -> dict:
        """单个 MCP server JSON 配置导入（非标准 mcp.json 格式）。

        支持的 JSON 格式：
            {
              "name": "my-mcp",
              "description": "...",
              "transport": "http",
              "url": "https://...",
              "headers": [{"key":"Authorization","value":"Bearer xxx"}],
              "category": "general",
              "icon": "..."
            }

        做格式校验：name 非空、transport 合法、url 或 command 必填（根据 transport）
        返回：{"imported": [...], "skipped": [...], "failed": [...]}
        """
        config = self._parse_json(json_str, label="JSON 配置")
        if not isinstance(config, dict):
            raise ValidateErrorException("JSON 配置必须是对象")

        name = _normalize_text(config.get("name"))
        if not name:
            raise ValidateErrorException("name 不能为空")

        transport = normalize_mcp_transport(config.get("transport")) or "streamable_http"
        url = _normalize_text(config.get("url"))
        command = _normalize_text(config.get("command"))
        self._validate_transport(transport, url=url, command=command, server_name=name)

        account = self._resolve_account(account_id)
        existing = self._find_existing_provider(account, name)
        if existing and not overwrite:
            return {
                "imported": [],
                "skipped": [{"name": name, "id": str(existing.id), "reason": "已存在且 overwrite=False"}],
                "failed": [],
            }

        payload = _build_form_payload({
            **config,
            "name": name,
            "transport": transport,
            "url": url,
            "command": command,
            "headers": _convert_headers_to_list(config.get("headers")),
        })

        try:
            if existing and overwrite:
                form = UpdateMcpProviderReq(data=payload)
                if not form.validate():
                    raise ValidateErrorException(f"校验失败: {form.errors}")
                provider = self.mcp_service.update_mcp_provider(existing.id, form, account)
                return {
                    "imported": [{"name": name, "id": str(provider.id), "action": "updated"}],
                    "skipped": [],
                    "failed": [],
                }
            form = CreateMcpProviderReq(data=payload)
            if not form.validate():
                raise ValidateErrorException(f"校验失败: {form.errors}")
            provider = self.mcp_service.create_mcp_provider(form, account)
            return {
                "imported": [{"name": name, "id": str(provider.id), "action": "created"}],
                "skipped": [],
                "failed": [],
            }
        except ValidateErrorException:
            raise
        except Exception as exc:
            logging.exception("JSON 配置导入失败: %s", name)
            return {
                "imported": [],
                "skipped": [],
                "failed": [{"name": name, "error": str(exc)}],
            }

    # ------------------------------------------------------------------ #
    #  通用工具                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_json(json_str: str, *, label: str = "JSON") -> Any:
        """解析 JSON 字符串，失败时抛出 ValidateErrorException。"""
        if not json_str or not str(json_str).strip():
            raise ValidateErrorException(f"{label} 内容不能为空")
        try:
            return json.loads(json_str) if isinstance(json_str, str) else json_str
        except json.JSONDecodeError as exc:
            raise ValidateErrorException(f"{label} 格式错误: {exc}") from exc
