from __future__ import annotations

from pydantic import BaseModel, Field


DATASET_RETRIEVAL_TOOL_NAME = "dataset_retrieval"
KNOWLEDGE_RETRIEVAL_TOOL_NAME = "search_knowledge_base"

_DEFAULT_HARD_FAIL_TOOL_NAMES = (
    "qwen_image_text_to_image",
    "qwen_image_edit",
    "qwen_image_edit_2509",
)
_DEFAULT_TOOL_ALIAS_SYNONYMS = {
    "recall_dataset": KNOWLEDGE_RETRIEVAL_TOOL_NAME,
    "dataset_retrieval": KNOWLEDGE_RETRIEVAL_TOOL_NAME,
}
_DEFAULT_IMAGE_RESULT_TOOL_NAMES = (*_DEFAULT_HARD_FAIL_TOOL_NAMES, "computer_action")
_DEFAULT_HIGH_RISK_TOOL_NAMES = (
    "send_email",
    "send_sms",
    "execute_sql",
    "deploy_application",
    "delete_resource",
    "modify_billing",
    "transfer_funds",
    "execute_code",
    "browser_action",
    "computer_action",
    # 会话工作区授权申请：安全根之外的目录必须经用户显式批准
    "os_workspace_scope",
)

# 每次调用都必须用户确认的工具（不受「轮内已授权列表」与智能审批策略影响）：
# 授权申请是不可复用的安全决策，批准目录 A 不等于批准目录 B。
_DEFAULT_ALWAYS_CONFIRM_TOOL_NAMES = ("os_workspace_scope",)
_DEFAULT_DANGEROUS_TOOL_NAMES = (
    "drop_table",
    "format_disk",
    "execute_shell",
)

# computer_action 的纯观察动作：截图/元素树/窗口与应用列表——零写入、零焦点影响，
# 与文件读取同档（免确认）。其余 GUI 动作（click/type/press/launch_app 等）会改变
# GUI 状态，仍按高风险逐次（轮内首次）确认。
_COMPUTER_OBSERVATION_ACTIONS: frozenset[str] = frozenset(
    {"screenshot", "capture", "list_apps", "list_windows"}
)


class ToolPolicy(BaseModel):
    """工具运行时策略的统一定义。"""

    dataset_retrieval_tool_name: str = DATASET_RETRIEVAL_TOOL_NAME
    hard_fail_tool_names: tuple[str, ...] = _DEFAULT_HARD_FAIL_TOOL_NAMES
    tool_alias_synonyms: dict[str, str] = Field(default_factory=lambda: dict(_DEFAULT_TOOL_ALIAS_SYNONYMS))
    image_result_tool_names: tuple[str, ...] = _DEFAULT_IMAGE_RESULT_TOOL_NAMES
    high_risk_tool_names: tuple[str, ...] = _DEFAULT_HIGH_RISK_TOOL_NAMES
    dangerous_tool_names: tuple[str, ...] = _DEFAULT_DANGEROUS_TOOL_NAMES
    always_confirm_tool_names: tuple[str, ...] = _DEFAULT_ALWAYS_CONFIRM_TOOL_NAMES

    @staticmethod
    def _normalize_tool_name(tool_name: str | None) -> str:
        return str(tool_name or "").strip()

    def resolve_tool_name(self, tool_name: str | None) -> str:
        normalized = self._normalize_tool_name(tool_name)
        if not normalized:
            return ""
        return self.tool_alias_synonyms.get(normalized, normalized)

    def is_hard_fail_tool(self, tool_name: str | None) -> bool:
        normalized = self._normalize_tool_name(tool_name)
        return bool(normalized and normalized in self.hard_fail_tool_names)

    def is_image_result_tool(self, tool_name: str | None) -> bool:
        normalized = self._normalize_tool_name(tool_name)
        return bool(normalized and normalized in self.image_result_tool_names)

    def is_dangerous_tool(self, tool_name: str | None) -> bool:
        normalized = self._normalize_tool_name(tool_name)
        return bool(normalized and normalized in self.dangerous_tool_names)

    def is_high_risk_tool(self, tool_name: str | None) -> bool:
        normalized = self._normalize_tool_name(tool_name)
        return bool(normalized and normalized in self.high_risk_tool_names)

    def always_requires_confirmation(self, tool_name: str | None) -> bool:
        """每次调用都必须用户确认（不受轮内已授权列表/智能审批影响）。

        用于授权申请类工具：批准一次目录 A 不能顺带放行目录 B。
        """
        normalized = self._normalize_tool_name(tool_name)
        return bool(normalized and normalized in self.always_confirm_tool_names)

    def requires_confirmation(self, tool_name: str | None, tool_input: dict | None = None) -> bool:
        """本次工具调用是否需要用户确认（比 is_high_risk_tool 更细：按入参分档）。

        唯一分档：computer_action 的 actions 全部为纯观察动作（截图/元素树/列表）时
        免确认——零写入、零焦点影响，逐次弹窗只会拖垮 GUI 任务的体验；
        其余 GUI 动作与全部高风险工具维持确认语义。
        """
        if not self.is_high_risk_tool(tool_name):
            return False
        if self._normalize_tool_name(tool_name) == "computer_action":
            actions = (tool_input or {}).get("actions") or []
            if actions and all(
                isinstance(action, dict)
                and str(action.get("action") or "").strip().lower()
                in _COMPUTER_OBSERVATION_ACTIONS
                for action in actions
            ):
                return False
        return True
