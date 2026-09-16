"""管理端 Agent 板块动作注册表（设计 §7.1）。

为什么单独成文件：板块动作 → 所需权限点 的映射是**授权边界**，必须能被
独立测试与静态核对。若把它写进工具实现体，就会与"执行"耦合，无法单独
审计"哪个 action 需要哪个权限点"。

核心不变式：**未声明的 (board, action) 一律拒绝**（fail closed）。
工具内部按 action 分支，若校验漏了某个 action 就会越权；显式登记制使
"新增 action 忘记声明"表现为明确报错，而不是静默放行。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ActionKind = Literal["read", "write", "delete"]


@dataclass(frozen=True)
class BoardAction:
    """一个板块动作的声明。

    Attributes:
        board: 板块标识（同时作为 automation_policy 的键）。
        action: 动作标识。
        kind: 动作类别。``delete`` 类必须走回收站（设计 §5.1）。
        permission_code: 执行该动作所需的权限点（必须在 PERMISSION_CATALOG 中）。
        description: 人类可读说明，用于工具 schema 文档与审计。
    """

    board: str
    action: str
    kind: ActionKind
    permission_code: str
    description: str = ""

    @property
    def is_write(self) -> bool:
        """是否需要按 automation_policy 分流。

        只读动作不进草稿、不需要自动化级别判定——否则「只读也要人工批准」
        会让 supervised 档的 Agent 连列表都查不了。
        """
        return self.kind in ("write", "delete")


def _a(
    board: str,
    action: str,
    kind: ActionKind,
    permission_code: str,
    description: str = "",
) -> BoardAction:
    return BoardAction(
        board=board,
        action=action,
        kind=kind,
        permission_code=permission_code,
        description=description,
    )


# 板块动作登记表。
# 约定：每个板块至少登记一个只读 action（否则 Agent 无法了解现状再动手）。
BOARD_ACTIONS: tuple[BoardAction, ...] = (
    # -------- 内置工具（P1b 端到端样板板块）--------
    _a("builtin_tool", "list", "read", "builtin_tool:read", "列出内置工具及其启停状态"),
    _a(
        "builtin_tool",
        "update_enabled",
        "write",
        "builtin_tool:update",
        "启用/停用某个内置工具",
    ),
    _a(
        "builtin_tool",
        "update_metadata",
        "write",
        "builtin_tool:update",
        "更新内置工具的标签/描述/关键词",
    ),
)

BOARD_IDS: tuple[str, ...] = tuple(sorted({a.board for a in BOARD_ACTIONS}))

_INDEX: dict[tuple[str, str], BoardAction] = {
    (a.board, a.action): a for a in BOARD_ACTIONS
}


def resolve_action(board: str, action: str) -> BoardAction:
    """解析 (board, action) 声明；未声明则抛 ValueError（fail closed）。

    Raises:
        ValueError: 板块或动作未登记，或参数为空。
    """
    board = str(board or "").strip()
    action = str(action or "").strip()
    if not board or not action:
        raise ValueError("board 与 action 不能为空")
    declared = _INDEX.get((board, action))
    if declared is None:
        known = sorted(a for (b, a) in _INDEX if b == board)
        if not known:
            raise ValueError(
                f"未登记的板块: {board}（已登记板块: {', '.join(BOARD_IDS)}）"
            )
        raise ValueError(
            f"板块 {board} 未登记动作 {action}（已登记: {', '.join(known)}）"
        )
    return declared


def board_ids_of(board: str) -> list[str]:
    """列出某板块已登记的全部 action（用于工具 schema 与报错提示）。"""
    board = str(board or "").strip()
    return sorted(action for (b, action) in _INDEX if b == board)


def boards() -> tuple[str, ...]:
    """全部已登记板块。"""
    return BOARD_IDS
