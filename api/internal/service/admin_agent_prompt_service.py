"""管理端 Agent 的系统提示词构造（AGENTS.md 强制规则）。

提示词内容**只**从 `prompt_template` 表（由 YAML seed 同步）读取，
本模块只负责：
1. 解析 Agent 的 `prompt_key`（为空 → 内置默认）；
2. 用 `AdminAgentPrincipal` 填充变量（agent_name / granted_permissions / automation_policy）。

运行时读取顺序遵循 AGENTS.md：DB（admin 编辑过的 `source=custom`）> YAML seed。
该优先级与变量填充**已由** `PromptSyncService.get_prompt`（`@staticmethod`，
读全局 `db.session`）实现，故此处直接复用，不再自行解析。
"""
from __future__ import annotations

from internal.entity.admin_agent_entity import AdminAgentPrincipal

__all__ = ["DEFAULT_ADMIN_AGENT_PROMPT_KEY", "AdminAgentPromptService"]

# 兜底提示词 key（YAML: api/internal/core/prompts/admin_agent/board_agent.yaml）
DEFAULT_ADMIN_AGENT_PROMPT_KEY = "admin_agent_board_agent"


class AdminAgentPromptService:
    """无状态服务：提示词读取走 `PromptSyncService.get_prompt`（用全局 db）。

    不持有 db，因此可无参构造；`_render_template` 是测试替换点。
    """

    def build_system_prompt(self, principal: AdminAgentPrincipal, *, prompt_key: str | None) -> str:
        key = str(prompt_key or "").strip() or DEFAULT_ADMIN_AGENT_PROMPT_KEY
        variables = {
            "agent_name": principal.agent_name,
            "granted_permissions": self._format_permissions(principal),
            "automation_policy": self._format_policy(principal),
        }
        return self._render_template(key, variables)

    # ------------------------------------------------------------------
    # 可替换点（测试替换，避免依赖 DB）
    # ------------------------------------------------------------------

    def _render_template(self, key: str, variables: dict) -> str:
        """按 key 取提示词并填充变量；取不到内容时抛错，**不**返回空串。

        静默空串会让 Agent 失去全部行为约束（等于没有系统提示词），
        属于"看起来能跑、实际无边界"的隐患，必须显式失败。

        `PromptSyncService.get_prompt` 已实现「custom > catalog」优先级与
        `content.format(**variables)` 变量填充，故此处不再自行 replace。
        """
        from internal.service.prompt_sync_service import PromptSyncService

        content = PromptSyncService.get_prompt(key, **variables)
        if not content:
            raise RuntimeError(
                f"管理端 Agent 提示词缺失：{key}（检查 prompts/index.yaml 登记与启动同步）"
            )
        return content

    @staticmethod
    def _format_permissions(principal: AdminAgentPrincipal) -> str:
        codes = sorted(principal.effective_permissions)
        return "、".join(codes) if codes else "（无：管理员尚未下放任何权限）"

    @staticmethod
    def _format_policy(principal: AdminAgentPrincipal) -> str:
        if not principal.automation_policy:
            return "（未配置：全部板块按 supervised 处理）"
        return "、".join(
            f"{board}={level.value}" for board, level in sorted(principal.automation_policy.items())
        )
