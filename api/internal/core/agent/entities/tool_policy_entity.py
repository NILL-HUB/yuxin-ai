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
    "recall_dataset": DATASET_RETRIEVAL_TOOL_NAME,
}
_DEFAULT_IMAGE_RESULT_TOOL_NAMES = _DEFAULT_HARD_FAIL_TOOL_NAMES
_DEFAULT_HIGH_RISK_TOOL_NAMES = (
    "send_email",
    "send_sms",
    "execute_sql",
    "deploy_application",
    "delete_resource",
    "modify_billing",
    "transfer_funds",
)
_DEFAULT_DANGEROUS_TOOL_NAMES = (
    "drop_table",
    "format_disk",
    "execute_shell",
)


class ToolPolicy(BaseModel):
    """工具运行时策略的统一定义。"""

    dataset_retrieval_tool_name: str = DATASET_RETRIEVAL_TOOL_NAME
    hard_fail_tool_names: tuple[str, ...] = _DEFAULT_HARD_FAIL_TOOL_NAMES
    tool_alias_synonyms: dict[str, str] = Field(default_factory=lambda: dict(_DEFAULT_TOOL_ALIAS_SYNONYMS))
    image_result_tool_names: tuple[str, ...] = _DEFAULT_IMAGE_RESULT_TOOL_NAMES
    high_risk_tool_names: tuple[str, ...] = _DEFAULT_HIGH_RISK_TOOL_NAMES
    dangerous_tool_names: tuple[str, ...] = _DEFAULT_DANGEROUS_TOOL_NAMES

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
