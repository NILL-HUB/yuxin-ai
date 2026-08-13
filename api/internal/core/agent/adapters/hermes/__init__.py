"""Hermes agent 能力适配层。

从 NousResearch/hermes-agent (MIT) 选择性移植的通用能力，按我们的
LangChain/多租户架构重写为独立模块。只吸收算法与安全规则，不引入
Hermes 的 CLI/配置/网关运行时。
"""

from .v4a_patch import (  # noqa: F401
    parse_v4a_patch,
    apply_v4a_operations,
    parse_and_apply_patch,
)
from .approval_mining import (  # noqa: F401
    ConfirmationRecord,
    mine_approval_history,
    as_serializable,
)

__all__ = [
    "parse_v4a_patch",
    "apply_v4a_operations",
    "parse_and_apply_patch",
    "ConfirmationRecord",
    "mine_approval_history",
    "as_serializable",
]
