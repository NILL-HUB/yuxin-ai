"""CLI 工具来源服务：CRUD + tool_schema→cli_tool 展开 + 运行时 binding 构造。

CLI 是与 builtin / api_tool / mcp / skill 并列的**独立工具来源**（source_type=cli）：
- ``cli_provider.tool_schema`` 是管理员维护的"能力说明书"，
  注册/更新时展开写入 ``cli_tool``（候选收集的唯一事实源）。
- 运行时把 ``cli_provider`` 行构造成 MCP 形状 binding 交给既有
  ``McpToolFactory``（内部走 ``McpStdioClient`` 的 ``protocol=raw``），
  不重复实现本地进程执行器。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from injector import inject
from pkg.sqlalchemy import SQLAlchemy

from internal.core.tools.mcp_tools.providers.mcp_tool_factory import McpToolFactory
from internal.model.cli import CliProvider, CliTool
from internal.service.tool_credential_encryptor import ensure_encrypted_env

# create_provider / update_provider 允许更新的字段（tool_schema 变更需重建 cli_tool）
_UPDATABLE_FIELDS = (
    "label",
    "description",
    "category",
    "command",
    "args",
    "env",
    "tool_schema",
    "task_keywords",
    "timeout_seconds",
    "enabled",
)


@inject
@dataclass
class CliService:
    """CLI 工具来源服务。"""

    db: SQLAlchemy

    # ------------------------------------------------------------------ #
    # 能力说明书展开
    # ------------------------------------------------------------------ #

    @staticmethod
    def expand_tool_schema(tool_schema: dict[str, Any] | None) -> list[dict[str, Any]]:
        """把能力说明书展开为 cli_tool 行数据（cli_tool 的唯一写入入口）。

        非法条目（key 非字符串/空串、value 非 dict）一律跳过，保证
        单个坏条目不会让整个 provider 注册失败。
        """
        if not isinstance(tool_schema, dict):
            return []

        rows: list[dict[str, Any]] = []
        for name, spec in tool_schema.items():
            if not isinstance(name, str) or not name.strip():
                continue
            if not isinstance(spec, dict):
                continue
            normalized_name = name.strip()
            parameters = spec.get("parameters")
            rows.append({
                "name": normalized_name,
                "description": str(spec.get("description") or "").strip(),
                "input_schema": parameters if isinstance(parameters, dict) else {},
                "task_keywords": [normalized_name],
            })
        return rows

    # ------------------------------------------------------------------ #
    # 写路径
    # ------------------------------------------------------------------ #

    def create_provider(
        self,
        *,
        account_id: Any,
        name: str,
        label: str,
        description: str,
        category: str,
        command: str,
        args: list,
        env: dict,
        tool_schema: dict,
        task_keywords: list,
        timeout_seconds: int,
        enabled: bool = True,
    ) -> CliProvider:
        """注册 CLI provider，并把能力说明书展开为 cli_tool。"""
        provider = CliProvider(
            account_id=account_id,
            name=name,
            label=label or name,
            description=description,
            category=category,
            command=command,
            args=list(args or []),
            env=self._encrypt_env(env or {}),
            tool_schema=dict(tool_schema or {}),
            task_keywords=list(task_keywords or []),
            timeout_seconds=int(timeout_seconds or 30),
            enabled=bool(enabled),
            source_type="cli",
        )
        with self.db.auto_commit():
            self.db.session.add(provider)
            self.db.session.flush()
            self._sync_tools(provider)
        return provider

    def update_provider(self, provider_id: Any, **fields: Any) -> CliProvider | None:
        """更新 CLI provider；tool_schema 变更后按新说明书重建 cli_tool。"""
        provider = self.get_provider(provider_id)
        if provider is None:
            return None

        schema_changed = "tool_schema" in fields
        with self.db.auto_commit():
            for key, value in fields.items():
                if key not in _UPDATABLE_FIELDS:
                    continue
                if key == "env":
                    setattr(provider, key, self._encrypt_env(value or {}))
                elif key == "args":
                    setattr(provider, key, list(value or []))
                elif key == "task_keywords":
                    setattr(provider, key, list(value or []))
                elif key == "tool_schema":
                    setattr(provider, key, dict(value or {}))
                elif key == "timeout_seconds":
                    setattr(provider, key, int(value or 30))
                else:
                    setattr(provider, key, value)
            if schema_changed:
                self._sync_tools(provider)
        return provider

    def delete_provider(self, provider_id: Any) -> bool:
        """删除 CLI provider（cli_tool 经外键 CASCADE 一并删除）。"""
        provider = self.get_provider(provider_id)
        if provider is None:
            return False
        with self.db.auto_commit():
            self.db.session.delete(provider)
        return True

    def _sync_tools(self, provider: CliProvider) -> None:
        """以 tool_schema 为唯一权威重建 cli_tool（候选唯一事实源）。"""
        self.db.session.query(CliTool).filter(CliTool.provider_id == provider.id).delete()
        for row in self.expand_tool_schema(provider.tool_schema):
            self.db.session.add(CliTool(provider_id=provider.id, **row))

    # ------------------------------------------------------------------ #
    # 读路径
    # ------------------------------------------------------------------ #

    def get_provider(self, provider_id: Any) -> CliProvider | None:
        if provider_id is None:
            return None
        normalized_id = self._coerce_uuid(provider_id)
        if normalized_id is None:
            return None
        return self.db.session.query(CliProvider).filter(CliProvider.id == normalized_id).one_or_none()

    @staticmethod
    def _coerce_uuid(value: Any):
        """把候选/路由传来的 provider_id（可能是字符串）归一为 UUID。"""
        import uuid as _uuid

        if isinstance(value, _uuid.UUID):
            return value
        try:
            return _uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            return None

    def list_providers(self, account_id: Any) -> list[dict[str, Any]]:
        """列出可见的 CLI provider（账号私有 + 系统公共）。"""
        query = self.db.session.query(CliProvider)
        if account_id is None:
            # account_id 为 NULL 时 `==` 会生成 NULL = NULL（永假），只取公共 provider
            providers = query.filter(CliProvider.is_public == True).all()  # noqa: E712
        else:
            providers = query.filter(
                (CliProvider.account_id == account_id) | (CliProvider.is_public == True)  # noqa: E712
            ).all()
        return [self.to_dict(provider) for provider in providers]

    @staticmethod
    def to_dict(provider: CliProvider) -> dict[str, Any]:
        """把 provider 序列化为可返回给前端的 dict（含工具数量）。"""
        return {
            "id": str(provider.id),
            "name": provider.name,
            "label": provider.label,
            "description": provider.description,
            "category": provider.category,
            "command": provider.command,
            "args": list(provider.args or []),
            "tool_schema": dict(provider.tool_schema or {}),
            "task_keywords": list(provider.task_keywords or []),
            "timeout_seconds": provider.timeout_seconds,
            "enabled": bool(provider.enabled),
            "is_public": bool(provider.is_public),
            "tool_count": len(provider.tools or []),
        }

    # ------------------------------------------------------------------ #
    # 运行时装配（复用 McpToolFactory，不重复实现执行器）
    # ------------------------------------------------------------------ #

    @staticmethod
    def build_mcp_shaped_bindings(
        providers: list[CliProvider],
        tool_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """把 cli_provider 行构造成 MCP 形状 binding，供 McpToolFactory 复用执行。

        ``env`` 是加密存储值，原样透传——``McpStdioClient._build_subprocess_env``
        会调用 ``decrypt_env`` 还原后注入子进程。
        """
        return [
            {
                "name": provider.name,
                "label": provider.label,
                "description": provider.description,
                "transport": "cli",
                "command": provider.command,
                "args": list(provider.args or []),
                "env": dict(provider.env or {}),
                "timeout_seconds": provider.timeout_seconds,
                "tool_schema": dict(provider.tool_schema or {}),
                "tool_names": list(tool_names or []),
                "enabled": bool(provider.enabled),
            }
            for provider in providers
        ]

    @staticmethod
    def build_selected_tools(
        providers: list[CliProvider],
        tool_names: list[str] | None = None,
    ):
        """把 CLI provider 装配为 LangChain 工具（内部走 protocol=raw 执行）。"""
        bindings = CliService.build_mcp_shaped_bindings(providers, tool_names=tool_names)
        if not bindings:
            return []
        return McpToolFactory().get_tools(bindings, mcp_tool_snapshots=None)

    # ------------------------------------------------------------------ #
    # 凭证
    # ------------------------------------------------------------------ #

    @staticmethod
    def _encrypt_env(env: dict) -> dict:
        """加密 CLI 环境变量。

        加密失败必须**显式抛出**：静默返回空 env 会让管理员以为密钥已保存，
        而子进程实际拿不到凭证（表现为"配置了却不生效"的难查故障）。
        """
        return ensure_encrypted_env(env)
