"""删除命令检测核心：识别"物理删除"类终端命令。

目标：保证 Agent 在本机上的删除动作只走回收站通道（os_recycle_bin），
禁止绕过回收站的终端物理删除（del / rm / Remove-Item 等）。
检测不到并不代表 100% 安全——本模块是护栏的一部分，与提示词约束、
worker 端拦截共同生效。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DeleteCommandMatch:
    command: str
    index: int
    reason: str


# 物理删除命令清单（小写、去空白后的命令名 → 说明）
# 同一命令名在 cmd/PowerShell/Unix 下语义相同（物理删除），合并为唯一条目，
# 避免 dict 重复键导致后者覆盖前者的映射丢失问题。
DELETE_COMMANDS: dict[str, str] = {
    # Windows CMD / PowerShell 别名 / Unix 共用词（物理删除语义一致）
    "del": "del（cmd/PowerShell 物理删除，不经过回收站）",
    "erase": "erase（cmd/PowerShell 物理删除，del/Remove-Item 别名）",
    "rmdir": "rmdir（cmd/PowerShell/Unix 物理删除目录）",
    "rd": "rd（cmd/PowerShell rmdir 别名，物理删除目录）",
    "remove-item": "PowerShell Remove-Item（物理删除）",
    "ri": "PowerShell Remove-Item 别名（物理删除）",
    "rm": "rm（PowerShell/Unix 物理删除）",
    "unlink": "unlink（Unix 物理删除）",
}

# 非删除命令（列入防止误伤；当前无实际误伤，保留为空集合占位）
_NON_DELETE_COMMANDS: frozenset[str] = frozenset(
    {"Get-RemoveItem", "remove-itemproperty"}
)

# 删除命令名集合（DELETE_COMMANDS 的键）
_DELETE_COMMAND_NAMES: frozenset[str] = frozenset(DELETE_COMMANDS)


def _extract_command_tokens(line: str) -> list[str]:
    """从一行中提取首命令 token（处理管道、变量赋值等）。

    简单启发式：切分后跳过常见 PS 前缀，返回候选命令名。
    """
    tokens = line.strip().split()
    if not tokens:
        return []
    return tokens


def _token_command_name(token: str) -> str:
    """规范化单个 token 为小写命令名：去掉引号、路径、.exe 后缀。"""
    name = token.strip().strip("\"'`")
    # 去掉常见前缀（./ 或 .\ 或路径），保留最后一段
    name = re.sub(r"^.*[\\/]", "", name)
    # 去掉 .exe/.cmd/.bat 后缀
    name = re.sub(r"\.(exe|cmd|bat)$", "", name, flags=re.IGNORECASE)
    return name.lower()


def _is_clear_delete_statement(line: str) -> str | None:
    """判断一行是否为明确"删除语句"，返回命中的规范命令名（未命中返回 None）。

    命中规则：
    1. 行首命令为删除命令（含 PowerShell 变量赋值 + 删除命令，如 `$x = Remove-Item ...`）；
    2. 删除命令出现在 `;`、`&&`、`|` 之后（多命令拼接）。
    保守起见，任何"删除命令名出现在行首或命令边界"都算命中。
    """
    stripped = line.strip()
    if not stripped:
        return None
    # PowerShell 变量赋值前缀：`$files = Remove-Item ...`
    stripped = re.sub(r"^\s*\$[A-Za-z_][A-Za-z0-9_]*\s*=\s*", "", stripped)
    # 按常见分隔符拆成"子命令"，检查每个子命令是否以删除命令开头
    # 注意：`Remove-Item ... | Remove-Item` 只取第一段即可；
    # `{`/`}` 用于覆盖语句块体（如 `foreach (...) { Remove-Item ... }`）
    segments = re.split(r"[;{}]|\|\||&&", stripped)
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        first_token = segment.split()[0] if segment.split() else ""
        command_name = _token_command_name(first_token)
        if command_name in _DELETE_COMMAND_NAMES:
            return command_name
    return None


def find_delete_command(command_text: str) -> DeleteCommandMatch | None:
    """在命令文本中查找物理删除命令，返回首个命中。

    Args:
        command_text: 需要检测的命令文本（可为多行/整段脚本）。

    Returns:
        DeleteCommandMatch（含命令、行号、原因）或 None。
    """
    for index, raw_line in enumerate(command_text.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        command_name = _is_clear_delete_statement(line)
        if command_name is not None:
            return DeleteCommandMatch(
                command=line,
                index=index,
                reason=DELETE_COMMANDS[command_name],
            )
    return None
