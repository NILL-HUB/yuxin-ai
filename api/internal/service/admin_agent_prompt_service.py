"""管理端 Agent 的系统提示词构造（AGENTS.md 强制规则）。

提示词内容**只**从 `prompt_template` 表（由 YAML seed 同步）读取，
本模块只负责：
1. 解析 Agent 的 `prompt_key`（为空 → 内置默认）；
2. 用 `AdminAgentPrincipal` 填充变量（agent_name / granted_permissions / automation_policy）。

运行时读取走 `PromptSyncService.get_prompt`（`@staticmethod`，读全局 `db.session`）：
按 `prompt_key` 取唯一记录，再做 `content.format(**variables)` 变量填充。
该方法是**先写后读的覆盖语义，读取时没有任何 source 排序**——admin 自定义之所以
优先，是因为写入侧 `update_prompt` 就地把该记录 `source` 改成 `custom`，
而 `_upsert_prompt` 只覆盖 `source="catalog"` 的记录（prompt_key 是主键，
同一 key 只有一条记录，改了它就是覆盖了它），并非读取时比较优先级。

填充失败的真实风险：`get_prompt` 在 `format` 抛 `KeyError/IndexError/ValueError`
时只记 warning 并**返回未渲染原文**。此时 Agent 会看到字面 `{granted_permissions}`
之类的占位符，行为约束静默失效——这种"看似有约束、实则无边界"的状态比没有
提示词更危险，故本模块在渲染后做残留占位符检测，命中即显式失败。
"""
from __future__ import annotations

import re

from internal.entity.admin_agent_entity import AdminAgentPrincipal
from internal.exception import FailException
from internal.service.prompt_sync_service import PromptSyncService

__all__ = ["DEFAULT_ADMIN_AGENT_PROMPT_KEY", "AdminAgentPromptService"]

# 兜底提示词 key（YAML: api/internal/core/prompts/admin_agent/board_agent.yaml）
DEFAULT_ADMIN_AGENT_PROMPT_KEY = "admin_agent_board_agent"


def _find_unfilled_placeholders(content: str, variables: dict[str, str]) -> list[str]:
    """返回 `content` 中仍残留的、**本服务注入变量**的占位符名（有序去重）。

    检测口径：只匹配本次注入的变量名（`agent_name` 等），因为填充失败时
    原样留下的只会是这些占位符；提示词正文里其它用途的花括号（JSON 示例
    `{"a": 1}`、转义 `{{x}}` 渲染出的字面 `{x}`）不在检测范围，不会被误伤。
    """
    if not content or not variables:
        return []
    pattern = re.compile(r"\{(" + "|".join(re.escape(name) for name in variables) + r")\}")
    return sorted({match.group(1) for match in pattern.finditer(content)})


class AdminAgentPromptService:
    """无状态服务：提示词读取走 `PromptSyncService.get_prompt`（用全局 db）。

    不持有 db，因此可无参构造；`_render_template` 是测试替换点。
    """

    def build_system_prompt(self, principal: AdminAgentPrincipal, *, prompt_key: str | None) -> str:
        """构造该管理员 Agent 的系统提示词。

        Raises:
            FailException: 提示词缺失（key 未在 `prompts/index.yaml` 登记或未同步），
                或渲染后仍残留本服务注入的变量占位符
                （`PromptSyncService.get_prompt` 填充失败会静默返回未渲染原文）。
        """
        key = str(prompt_key or "").strip() or DEFAULT_ADMIN_AGENT_PROMPT_KEY
        variables: dict[str, str] = {
            "agent_name": principal.agent_name,
            "granted_permissions": self._format_permissions(principal),
            "automation_policy": self._format_policy(principal),
        }
        return self._render_template(key, variables)

    # ------------------------------------------------------------------
    # 可替换点（测试替换，避免依赖 DB）
    # ------------------------------------------------------------------

    def _render_template(self, key: str, variables: dict[str, str]) -> str:
        """按 key 取提示词并填充变量；取不到内容或渲染不完整时抛错，**不**返回残缺内容。

        两种必须显式失败的场景：
        1. 内容缺失（None / 空串）：Agent 失去全部行为约束，等于没有系统提示词；
        2. 渲染后残留占位符：`get_prompt` 在 `format` 失败时返回**未渲染原文**，
           Agent 会照着字面 `{granted_permissions}` 行事，约束静默失效。

        变量填充由 `get_prompt` 完成，此处不自行 replace；检测口径见
        `_find_unfilled_placeholders`。
        """
        content = PromptSyncService.get_prompt(key, **variables)
        if not content:
            raise FailException(
                f"管理端 Agent 提示词缺失：{key}（检查 prompts/index.yaml 登记与启动同步）"
            )

        unfilled = _find_unfilled_placeholders(content, variables)
        if unfilled:
            raise FailException(
                f"管理端 Agent 提示词渲染不完整：{key} 仍残留占位符 "
                f"{'、'.join(unfilled)}（PromptSyncService.get_prompt 填充失败时"
                "会返回未渲染原文，请检查该 prompt 的 variables 与调用侧入参）"
            )
        return content

    @staticmethod
    def _format_permissions(principal: AdminAgentPrincipal) -> str:
        codes = sorted(principal.effective_permissions)
        return "、".join(codes) if codes else "（无：管理员尚未下放任何权限）"

    @staticmethod
    def _format_policy(principal: AdminAgentPrincipal) -> str:
        """按板块列出自动化级别。

        级别一律经 `principal.automation_level_for(board)` 归一化取得（该方法
        已内建 `isinstance` 判断与非法值 fail-closed 到 SUPERVISED），
        不在此处自行 `.value` 硬取，避免把"policy 里存的一定是 AutomationLevel"
        这一隐式不变量扩散到本模块。
        """
        if not principal.automation_policy:
            return "（未配置：全部板块按 supervised 处理）"
        return "、".join(
            f"{board}={principal.automation_level_for(board).value}"
            for board in sorted(principal.automation_policy)
        )
