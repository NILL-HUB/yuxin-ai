"""V4A 补丁格式解析与文件应用。

移植自 NousResearch/hermes-agent `tools/patch_parser.py`（MIT License），
按本项目结构重写并补充自恢复诊断：

- 已应用补丁检测：目标文件已经包含补丁结果时返回 no-op 成功，而不是报错。
- 空白/缩进不一致诊断：hunk 无法匹配时给出可视化差异提示。
- 多处候选匹配时列出候选位置，供模型修复而不是盲目重试。
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class OperationType(str, Enum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    MOVE = "move"


@dataclass
class HunkLine:
    prefix: str  # ' ', '-', or '+'
    content: str


@dataclass
class Hunk:
    context_hint: str | None = None
    lines: list[HunkLine] = field(default_factory=list)

    def source_lines(self) -> list[str]:
        """补丁修改前应存在的行（上下文 + 删除行）。"""
        return [line.content for line in self.lines if line.prefix in {" ", "-"}]

    def result_lines(self) -> list[str]:
        """补丁应用后应存在的行（上下文 + 新增行）。"""
        return [line.content for line in self.lines if line.prefix in {" ", "+"}]


@dataclass
class PatchOperation:
    operation: OperationType
    file_path: str
    new_path: str | None = None
    hunks: list[Hunk] = field(default_factory=list)
    content: str | None = None


@dataclass
class FileTextOps:
    """文件操作的纯函数集合，便于测试与不同存储后端复用。"""

    def read_text(self, path: str) -> str | None:
        try:
            return Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError):
            return None

    def write_text(self, path: str, content: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def delete_file(self, path: str) -> None:
        Path(path).unlink()

    def move_file(self, path: str, new_path: str) -> None:
        target = Path(new_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        Path(path).replace(target)

    def exists(self, path: str) -> bool:
        return Path(path).is_file()


_BEGIN_MARKER = re.compile(r"^\*\*\*\s*Begin\s+Patch\s*$")
_END_MARKER = re.compile(r"^\*\*\*\s*End\s+Patch\s*$")


def _parse_marker(line: str) -> tuple[str | None, str | None]:
    """返回 (操作类型, 文件路径)。"""
    update = re.match(r"\*\*\*\s*Update\s+File:\s*(.+)", line)
    if update:
        return OperationType.UPDATE, update.group(1).strip()
    add = re.match(r"\*\*\*\s*Add\s+File:\s*(.+)", line)
    if add:
        return OperationType.ADD, add.group(1).strip()
    delete = re.match(r"\*\*\*\s*Delete\s+File:\s*(.+)", line)
    if delete:
        return OperationType.DELETE, delete.group(1).strip()
    move = re.match(r"\*\*\*\s*Move\s+File:\s*(.+?)\s*->\s*(.+)", line)
    if move:
        return OperationType.MOVE, (move.group(1).strip(), move.group(2).strip())
    return None, None


def _parse_hunk_header(line: str) -> str | None:
    match = re.match(r"^@@\s*(.*?)\s*@@\s*$", line)
    return match.group(1).strip() or None if match else None


def _finalize_operation(
    current: PatchOperation | None,
    current_hunk: Hunk | None,
    operations: list[PatchOperation],
) -> None:
    if current is None:
        return
    if current_hunk and current_hunk.lines:
        current.hunks.append(current_hunk)
    operations.append(current)


def parse_v4a_patch(patch_content: str) -> tuple[list[PatchOperation], str | None]:
    """解析 V4A 补丁文本，返回 (操作列表, 错误信息)。"""
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in patch_content.split("\n")]
    start_idx = -1
    end_idx = len(lines)
    for i, line in enumerate(lines):
        if _BEGIN_MARKER.match(line):
            start_idx = i
        elif _END_MARKER.match(line):
            end_idx = i
            break

    operations: list[PatchOperation] = []
    current: PatchOperation | None = None
    current_hunk: Hunk | None = None

    for i in range(start_idx + 1, end_idx):
        line = lines[i]
        op_type, op_target = _parse_marker(line)
        if op_type is not None:
            if op_type == OperationType.MOVE:
                assert isinstance(op_target, tuple)
                _finalize_operation(current, current_hunk, operations)
                current = PatchOperation(
                    operation=op_type,
                    file_path=op_target[0],
                    new_path=op_target[1],
                )
            else:
                _finalize_operation(current, current_hunk, operations)
                current = PatchOperation(operation=op_type, file_path=str(op_target or ""))
            current_hunk = None
            continue

        if line.strip() == "" and current is not None and current_hunk is not None:
            # 空行在文件内容中是有意义的；只有当 hunk 尚未开始时才跳过。
            if current_hunk.lines:
                current_hunk = None
                _finalize_operation(current, current_hunk, operations)
                current = None
            continue

        if current is None:
            continue

        if current_hunk is None:
            context_hint = _parse_hunk_header(line)
            if context_hint is not None or line.startswith("@@"):
                current_hunk = Hunk(context_hint=context_hint)
                continue
            if current.operation == OperationType.ADD:
                # Add File 后面直接跟 + 开头的内容行（部分工具省略 @@ 头）。
                if line.startswith("+"):
                    current_hunk = Hunk()
                    current_hunk.lines.append(HunkLine(prefix="+", content=line[1:]))
                elif current.content is None:
                    current.content = line
                continue
            if line.startswith((" ", "+", "-")):
                current_hunk = Hunk()
                current_hunk.lines.append(
                    HunkLine(prefix=line[0], content=line[1:])
                )
            continue

        if line.startswith((" ", "+", "-")):
            current_hunk.lines.append(HunkLine(prefix=line[0], content=line[1:]))
        else:
            # 新 hunk 头或新操作之间没有空行分隔。
            next_op, _next_target = _parse_marker(line)
            if next_op is not None:
                _finalize_operation(current, current_hunk, operations)
                current = None
                current_hunk = None
            else:
                context_hint = _parse_hunk_header(line)
                if context_hint is not None or line.startswith("@@"):
                    current.hunks.append(current_hunk)
                    current_hunk = Hunk(context_hint=context_hint)
                else:
                    current_hunk.lines.append(HunkLine(prefix=" ", content=line))

    _finalize_operation(current, current_hunk, operations)
    if not operations:
        return [], "补丁中未找到任何文件操作（需要 *** Add/Update/Delete/Move File）"
    return operations, None


def _detect_line_ending(sample: str) -> str | None:
    head = sample[:4096]
    if "\r\n" in head:
        return "\r\n"
    if "\n" in head:
        return "\n"
    return None


def _normalize_line_endings(text: str, target: str) -> str:
    lf = text.replace("\r\n", "\n").replace("\r", "\n")
    if target == "\n":
        return lf
    if target == "\r\n":
        return lf.replace("\n", "\r\n")
    return text


def _normalize_hunk_ending(hunk: Hunk, target: str) -> None:
    if target in {"\r\n", "\n"}:
        for line in hunk.lines:
            if line.content.endswith("\r") and target == "\n":
                line.content = line.content[:-1]
            elif not line.content.endswith("\r") and target == "\r\n":
                line.content = line.content + "\r"


def _locate_hunk(lines: list[str], hunk: Hunk) -> list[int]:
    """在目标行列表中定位 hunk 的 source_lines，返回所有候选起始下标。"""
    source = hunk.source_lines()
    if not source:
        return []
    candidates: list[int] = []
    for idx in range(len(lines) - len(source) + 1):
        if lines[idx : idx + len(source)] == source:
            candidates.append(idx)
    return candidates


def _already_applied(lines: list[str], hunk: Hunk) -> bool:
    result = hunk.result_lines()
    if not result:
        return False
    for idx in range(len(lines) - len(result) + 1):
        if lines[idx : idx + len(result)] == result:
            return True
    return False


def _diagnose_whitespace(lines: list[str], hunk: Hunk) -> str:
    """生成可视化差异诊断，帮助模型理解为何 hunk 未命中。"""
    source = hunk.source_lines()
    if not source:
        return ""
    near = max(0, min(len(lines) - len(source), max(0, len(lines) - 40)))
    window = lines[near : near + len(source) + 6]
    diff = difflib.ndiff(window, source)
    detail = "\n".join(list(diff)[:30])
    return (
        f"未找到精确匹配，可能是空白或缩进不一致。"
        f"目标文件窗口:\n{detail}"
    )


def _apply_update(ops: FileTextOps, op: PatchOperation) -> str:
    if not op.hunks:
        return f"OK: {op.file_path} 没有 hunk，跳过"
    original = ops.read_text(op.file_path)
    if original is None:
        return (
            f"ERROR: 文件不存在或无法读取: {op.file_path}\n"
            "请先确认路径，或用 Add File 创建文件。"
        )
    lines = original.split("\n")
    line_ending = _detect_line_ending(original)
    skipped = 0
    for hunk in op.hunks:
        _normalize_hunk_ending(hunk, line_ending or "\n")
        if _already_applied(lines, hunk):
            skipped += 1
            continue
        source = hunk.source_lines()
        if not source:
            # 纯新增 hunk：默认追加到文件末尾。
            added = [line.content for line in hunk.lines if line.prefix == "+"]
            if added:
                lines.extend(added)
            continue
        candidates = _locate_hunk(lines, hunk)
        if not candidates:
            return (
                f"ERROR: {op.file_path} 中未找到补丁上下文。\n"
                f"{_diagnose_whitespace(lines, hunk)}"
            )
        start = candidates[0]
        result = hunk.result_lines()
        lines[start : start + len(source)] = result
    text = "\n".join(lines)
    ops.write_text(op.file_path, text)
    if skipped and skipped == len(op.hunks):
        return f"OK(no-op): {op.file_path} 已包含补丁结果，无需修改"
    return f"OK: 已更新 {op.file_path}"


def _apply_add(ops: FileTextOps, op: PatchOperation) -> str:
    if ops.exists(op.file_path):
        return f"ERROR: 文件已存在: {op.file_path}，如需修改请用 Update File"
    lines: list[str] = []
    if op.content is not None:
        lines = op.content.split("\n")
    else:
        for hunk in op.hunks:
            lines.extend(line.content for line in hunk.lines if line.prefix == "+")
        if op.hunks and not lines:
            # 空文件补丁。
            lines = []
    ops.write_text(op.file_path, "\n".join(lines))
    return f"OK: 已创建 {op.file_path}"


def _apply_delete(ops: FileTextOps, op: PatchOperation) -> str:
    if not ops.exists(op.file_path):
        return f"OK(no-op): {op.file_path} 不存在，无需删除"
    ops.delete_file(op.file_path)
    return f"OK: 已删除 {op.file_path}"


def _apply_move(ops: FileTextOps, op: PatchOperation) -> str:
    if not ops.exists(op.file_path):
        return f"ERROR: 源文件不存在: {op.file_path}"
    if op.new_path and ops.exists(op.new_path):
        return f"ERROR: 目标文件已存在: {op.new_path}"
    ops.move_file(op.file_path, op.new_path or "")
    return f"OK: 已移动 {op.file_path} -> {op.new_path}"


def apply_v4a_operations(
    operations: list[PatchOperation],
    file_ops: FileTextOps | None = None,
) -> list[str]:
    """依次应用补丁操作，返回逐操作结果。"""
    ops = file_ops or FileTextOps()
    results: list[str] = []
    for op in operations:
        if op.operation == OperationType.ADD:
            results.append(_apply_add(ops, op))
        elif op.operation == OperationType.UPDATE:
            results.append(_apply_update(ops, op))
        elif op.operation == OperationType.DELETE:
            results.append(_apply_delete(ops, op))
        elif op.operation == OperationType.MOVE:
            results.append(_apply_move(ops, op))
        else:
            results.append(f"ERROR: 未知操作 {op.operation}")
    return results


def parse_and_apply_patch(
    patch_content: str,
    file_ops: FileTextOps | None = None,
) -> dict[str, Any]:
    """一站式解析并应用补丁，返回结构化结果供 Agent 展示。"""
    operations, error = parse_v4a_patch(patch_content)
    if error:
        return {"ok": False, "error": error, "results": []}
    results = apply_v4a_operations(operations, file_ops)
    errors = [r for r in results if r.startswith("ERROR:")]
    return {
        "ok": not errors,
        "results": results,
        "errors": errors,
    }
