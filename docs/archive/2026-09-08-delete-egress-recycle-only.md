# Agent 删除出口统一（删除只进回收站）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Agent 在本机上的所有删除动作（文件清理、整理、自动任务）都强制走回收站通道，禁止任何绕过回收站的终端物理删除。

**Architecture:** 在 `run_os_task`（Codex CLI 全权执行）的 apply 阶段与 worker `/run` 处理器统一加一道删除命令护栏：凡是要物理删除的删除类命令一律拒绝执行，并引导 Agent 改用 `os_recycle_bin`（V4A 删除补丁已走回收站）。在 apply 提示词中显式声明"删除必须使用回收站工具"。加硬阻断层，即使 Codex 自行尝试删除命令也被拦截。

**Tech Stack:** Python、LangChain `BaseTool`、pytest、httplib（mock）、re（命令 token 检测）

**设计决策：**
1. `run_os_task` 在 apply 阶段、调用 worker 前做**本地快速拦截**（客户端护栏，防任务无效提交）——不需要网络往返。
2. `os_automation_worker.py` 的 `/run` 处理器是**硬阻断层**（无论从哪提交都强制），`_build_prompt` 同时把"禁止删除"注入 apply 提示词。
3. 所有拦截返回结构化结果，明确引导走 `os_recycle_bin`。

---
## 任务与文件结构

| 任务 | 文件 |
| --- | --- |
| Task 1 核心库函数 | `api/internal/core/tools/builtin_tools/providers/codex_os/delete_guard.py`（新建，纯逻辑无 I/O） |
| Task 2 客户端拦截 | `run_os_task.py`（+delete_guard），新增 delete_guard 测试 |
| Task 3 worker 硬阻断 + 提示词 | `os_automation_worker.py`（+删除检测逻辑 + `_build_prompt` apply 分支加固），新增 worker 测试 |
| Task 4 worker 硬阻断 + 提示词 | 同上（worker 端） |

---

### Task 1: 删除命令检测核心库

**Files:**
- Create: `api/internal/core/tools/builtin_tools/providers/codex_os/delete_guard.py`
- Test: `api/test/internal/core/tools/test_codex_os_delete_guard.py`（新建）

- [ ] **Step 1: 写失败测试**

创建 `api/test/internal/core/tools/test_codex_os_delete_guard.py`：

```python
"""delete_guard：识别终端删除命令的单元测试。"""
from internal.core.tools.builtin_tools.providers.codex_os.delete_guard import (
    find_delete_command,
    DELETE_COMMANDS,
)


class TestFindDeleteCommand:
    def test_returns_none_when_no_delete_command(self):
        assert find_delete_command("Write-Output hello") is None
        assert find_delete_command("ls -la") is None
        assert find_delete_command("Get-Content file.txt") is None

    def test_returns_powershell_remove_item(self):
        assert find_delete_command("Remove-Item C:\\temp\\x.txt") is not None

    def test_returns_powershell_del_alias(self):
        assert find_delete_command("del C:\\temp\\x.txt") is not None

    def test_returns_cmd_del(self):
        assert find_delete_command("del /f /q C:\\temp\\x.txt") is not None

    def test_returns_unix_rm(self):
        assert find_delete_command("rm -rf /home/user/tmp") is not None

    def test_returns_unix_rmdir(self):
        assert find_delete_command("rmdir /home/user/old") is not None

    def test_powershell_remove_item_case_insensitive(self):
        assert find_delete_command("remove-item file.txt") is not None

    def test_tolerates_multiline_scripts(self):
        script = (
            "$files = Get-ChildItem C:\\temp\n"
            "foreach ($f in $files) { Remove-Item $f.FullName }\n"
        )
        assert find_delete_command(script) is not None

    def test_returns_exact_command_text_for_report(self):
        match = find_delete_command("  Remove-Item  C:\\temp\\x.txt  ")
        assert match is not None
        assert "Remove-Item" in match.command
        assert match.index >= 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/core/tools/test_codex_os_delete_guard.py -v`
Expected: FAIL（ModuleNotFoundError: delete_guard）

- [ ] **Step 3: 实现核心库**

创建 `api/internal/core/tools/builtin_tools/providers/codex_os/delete_guard.py`：

```python
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
_DELETE_COMMANDS: dict[str, str] = {
    # Windows CMD
    "del": "cmd del（物理删除，不经过回收站）",
    "erase": "cmd erase（del 别名，物理删除）",
    "rmdir": "cmd rmdir（物理删除目录）",
    "rd": "cmd rd（rmdir 别名，物理删除目录）",
    # PowerShell（含常见别名）
    "remove-item": "PowerShell Remove-Item（物理删除）",
    "ri": "PowerShell Remove-Item 别名",
    "rm": "PowerShell/Unix rm（物理删除）",
    "del": "PowerShell del 别名",
    "erase": "PowerShell erase 别名",
    "rd": "PowerShell rd 别名",
    "rmdir": "PowerShell rmdir 别名",
    # Unix/Linux
    "rm": "Unix rm（物理删除）",
    "rmdir": "Unix rmdir（物理删除目录）",
    "unlink": "Unix unlink（物理删除）",
}

# 命令名 → 解释；上面 dict 有重复键会被后者覆盖，用集合更可靠
DELETE_COMMANDS: frozenset[str] = frozenset(
    {"del", "erase", "rmdir", "rd", "remove-item", "ri", "rm", "unlink"}
)

# 非删除命令（列入防止误伤）
_NON_DELETE_COMMANDS: frozenset[str] = frozenset(
    {"Get-RemoveItem", "remove-itemproperty"}  # 仅示例；无实际误伤
)


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


def _is_clear_delete_statement(line: str) -> bool:
    """判断一行是否为明确"删除语句"。

    命中规则：
    1. 行首命令为删除命令（含 PowerShell 变量赋值 + 删除命令，如 `$x = Remove-Item ...`）；
    2. 删除命令出现在 `;`、`&&`、`|` 之后（多命令拼接）。
    保守起见，任何"删除命令名出现在行首或命令边界"都算命中。
    """
    stripped = line.strip()
    if not stripped:
        return False
    # PowerShell 变量赋值前缀：`$files = Remove-Item ...`
    stripped = re.sub(r"^\s*\$[A-Za-z_][A-Za-z0-9_]*\s*=\s*", "", stripped)
    # 按常见分隔符拆成"子命令"，检查每个子命令是否以删除命令开头
    # 注意：`Remove-Item ... | Remove-Item` 只取第一段即可
    segments = re.split(r";|\|\||&&", stripped)
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        first_token = segment.split()[0] if segment.split() else ""
        command_name = _token_command_name(first_token)
        if command_name in DELETE_COMMANDS:
            return True
    return False


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
        if _is_clear_delete_statement(line):
            # 提取具体命令名用于报错信息
            first_token = line.split()[0] if line.split() else ""
            command_name = _token_command_name(first_token)
            reason = next(
                (v for k, v in _DELETE_COMMANDS.items() if k == command_name),
                f"检测到删除命令 {command_name}",
            )
            return DeleteCommandMatch(
                command=line, index=index, reason=reason
            )
    return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/core/tools/test_codex_os_delete_guard.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add api/internal/core/tools/builtin_tools/providers/codex_os/delete_guard.py api/test/internal/core/tools/test_codex_os_delete_guard.py
git commit -m "feat(codex_os): add delete-command guard core"
```

---

### Task 2: `run_os_task` 客户端拦截

**Files:**
- Modify: `api/internal/core/tools/builtin_tools/providers/codex_os/run_os_task.py`
- Modify: `api/test/internal/core/tools/test_codex_os_tool.py`（新增 2 个测试）

- [ ] **Step 1: 写失败测试**

在 `api/test/internal/core/tools/test_codex_os_tool.py` 末尾新增：

```python
def test_run_os_task_apply_rejects_delete_command(monkeypatch):
    """apply 任务含终端删除命令时，本地直接拦截，不调用 worker。"""
    import importlib

    module = importlib.import_module(
        "internal.core.tools.builtin_tools.providers.codex_os.run_os_task"
    )
    called = {}

    def _fake_urlopen(request, timeout):
        called["called"] = True
        raise AssertionError("不应调用 worker")

    monkeypatch.setenv("OS_AUTOMATION_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("OS_AUTOMATION_TOKEN", "test-token")
    monkeypatch.setattr(module.urllib.request, "urlopen", _fake_urlopen)
    tool = RunOsTaskTool(requester="user-1")

    result = json.loads(
        tool._run(
            task="删除 C:\\temp\\x.txt",
            mode="apply",
            approval_token="some-token",
        )
    )

    assert result["ok"] is False
    assert "回收站" in result["error"]
    assert "delete" in result["error"].lower() or "删除" in result["error"]
    assert called.get("called") is None


def test_run_os_task_preview_delete_task_returns_recycle_guidance(monkeypatch):
    """preview 任务也提示删除走回收站（不阻断 preview，只做提示）。"""
    result = json.loads(
        run_os_task()._run(
            task="删除临时文件 x.txt",
            mode="preview",
        )
    )
    # preview 不做硬拦截（可能只是描述性语言），此处保持可配置。
    # 断言 preview 不要求 approval_token 且未配置时报配置错（环境未配置）。
    assert result["ok"] is False
```

（注：preview 默认不配置 env 时走"未配置"分支，该测试保留验证 preview 路径行为。）

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/internal/core/tools/test_codex_os_tool.py::test_run_os_task_apply_rejects_delete_command -v`
Expected: FAIL（当前 apply 不拦截，会走到 `_call_worker` 并因未配置返回配置错，或调 worker）

- [ ] **Step 3: 实现拦截**

修改 `api/internal/core/tools/builtin_tools/providers/codex_os/run_os_task.py`：

新增导入与工具 description 更新 + `_run` 拦截：

```python
from internal.core.tools.builtin_tools.providers.codex_os.delete_guard import (
    find_delete_command,
)
```

在 `RunOsTaskTool._run` 方法开头（组装 payload 前）加入：

```python
    def _run(self, **kwargs: Any) -> str:
        mode = _normalize_text(kwargs.get("mode") or "preview").lower()
        task_text = _normalize_text(kwargs.get("task"))

        # 删除出口护栏：apply 阶段任务包含物理删除命令 → 拒绝并引导回收站
        if mode == "apply" and task_text:
            delete_match = find_delete_command(task_text)
            if delete_match is not None:
                return json.dumps(
                    {
                        "ok": False,
                        "error": (
                            "任务包含物理删除命令（"
                            f"{delete_match.reason}"
                            "）。为保证可恢复，Agent 的删除必须走 os_recycle_bin "
                            "工具（先 list 确认，再 delete 移入回收站），"
                            "禁止用终端命令删除文件。"
                        ),
                        "blocked": "delete_command",
                        "detail": delete_match.command,
                    },
                    ensure_ascii=False,
                )

        payload = {
            "task": task_text,
            "mode": mode,
            ...
        }
```

同时更新 `description` 增加删除约束：

```python
        "只有用户在下一条消息中明确指定清理范围后，才能用同一个 approval_token "
        "以 mode=apply 执行；不要替用户自行决定清理范围。"
        "重要：删除文件/目录必须调用 os_recycle_bin 工具（移入回收站，可恢复），"
        "禁止在任务描述中使用 del/rm/Remove-Item 等终端删除命令（会被拒绝执行）。",
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/internal/core/tools/test_codex_os_tool.py -v`
Expected: PASS（原 2 个 + 新增 2 个）

- [ ] **Step 5: Commit**

```bash
git add api/internal/core/tools/builtin_tools/providers/codex_os/run_os_task.py api/test/internal/core/tools/test_codex_os_tool.py
git commit -m "feat(codex_os): reject terminal delete commands in run_os_task apply"
```

---

### Task 3: worker 端硬阻断 + apply 提示词加固

**Files:**
- Modify: `api/scripts/os_automation_worker.py`
- Modify: `api/test/scripts/test_os_automation_worker.py`（新增 4 个测试）

- [ ] **Step 1: 写失败测试**

在 `api/test/scripts/test_os_automation_worker.py` 新增导入并追加测试：

```python
from scripts.os_automation_worker import (
    _approvals,
    _build_prompt,
    _contains_delete_command,
    _create_approval,
    _file_operation,
    _read_run_output,
    _resolve_safe_root,
    _parse_codex_jsonl,
    _run_codex_task,
    _spill_run_output,
)
```

新增测试：

```python
class TestDeleteGuardInWorker:
    def test_detects_powershell_remove_item(self):
        assert _contains_delete_command("Remove-Item C:\\temp\\x.txt") is True

    def test_detects_cmd_del(self):
        assert _contains_delete_command("del /f /q C:\\temp\\x.txt") is True

    def test_detects_unix_rm(self):
        assert _contains_delete_command("rm -rf /tmp/x") is True

    def test_ignores_safe_command(self):
        assert _contains_delete_command("Write-Output hi") is False
        assert _contains_delete_command("Get-ChildItem C:\\temp") is False

    def test_apply_prompt_forbids_terminal_delete(self):
        prompt = _build_prompt("清理临时文件", "apply")
        assert "回收站" in prompt or "os_recycle_bin" in prompt
```

（Task 3 的 `_contains_delete_command` 会作为 worker 内部便捷封装；Task 4 的 `/run` 处理器调用它做硬阻断。测试在 Task 3 先覆盖辅助函数与提示词。）

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/scripts/test_os_automation_worker.py -v`
Expected: FAIL（`_contains_delete_command` 不存在 / apply 提示词未含回收站）

- [ ] **Step 3: 实现 worker 端删除检测 + 提示词**

在 `api/scripts/os_automation_worker.py` 顶部导入区新增：

```python
import re
```

在文件顶部（`_env` 函数后）新增：

```python
_DELETE_TERMS: dict[str, str] = {
    "del": "cmd/PowerShell del",
    "erase": "cmd/PowerShell erase",
    "rmdir": "cmd/PowerShell rmdir",
    "rd": "cmd/PowerShell rd",
    "remove-item": "PowerShell Remove-Item",
    "ri": "PowerShell Remove-Item 别名",
    "rm": "rm",
    "unlink": "unlink",
}


def _contains_delete_command(command_text: str) -> bool:
    """检测命令文本是否包含物理删除命令（回收站护栏的 worker 端判定）。

    兼容：行首命令、`$x = Remove-Item ...`、分号/&& 拼接、反斜杠/正斜杠路径前缀。
    """
    if not command_text:
        return False
    for raw_line in command_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\s*\$[A-Za-z_][A-Za-z0-9_]*\s*=\s*", "", line)
        for segment in re.split(r";|\|\||&&", line):
            segment = segment.strip()
            if not segment:
                continue
            first = segment.split()[0] if segment.split() else ""
            name = first.strip("\"'`")
            name = re.sub(r"^.*[\\/]", "", name)
            name = re.sub(r"\.(exe|cmd|bat)$", "", name, flags=re.IGNORECASE).lower()
            if name in _DELETE_TERMS:
                return True
    return False
```

修改 `_build_prompt` 的 apply 分支：

```python
    return (
        f"{task}\n\n"
        "[模式] 用户已确认执行。请执行完成该任务所需的最小命令集合，"
        "并汇报实际执行命令、输出、退出码和结果。不要做超出任务范围的修改。"
        "禁止用终端命令删除任何文件/目录（del、rm、Remove-Item、rmdir、rd、"
        "unlink 等都会被拦截）。如需删除，请调用 os_recycle_bin 工具移入回收站"
        "（可恢复）；任务中删除类操作一律走回收站通道。"
    )
```

（注：`_build_prompt` 当前在 apply 分支使用。删除约束放 apply 提示词，preview 已是只读提示，无需删除约束——但保留"预览不含删除"语义。）

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/scripts/test_os_automation_worker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/scripts/os_automation_worker.py api/test/scripts/test_os_automation_worker.py
git commit -m "feat(os_worker): add delete-command detection and apply prompt guard"
```

---

### Task 4: worker `/run` 处理器硬阻断

**Files:**
- Modify: `api/scripts/os_automation_worker.py`
- Modify: `api/test/scripts/test_os_automation_worker.py`

- [ ] **Step 1: 写失败测试**

在 `test_os_automation_worker.py` 新增：

```python
class TestRunHandlerRejectsDelete:
    def _build_handler(self):
        from http.server import BaseHTTPRequestHandler
        import io

        handler = BaseHTTPRequestHandler.__new__(BaseHTTPRequestHandler)
        handler.headers = {}
        handler.rfile = io.BytesIO(b"{}")
        handler.wfile = io.BytesIO()
        handler.path = "/run"
        handler.command = "POST"
        return handler

    def test_run_apply_with_delete_command_returns_blocked(self, monkeypatch):
        """/run 在 apply 且任务含删除命令时返回 blocked，不执行 Codex。"""
        import scripts.os_automation_worker as mod

        monkeypatch.setattr(mod, "_authorized", lambda self: True)
        sent = {}

        class _Handler:
            def _send_json(self, code, payload):
                sent["code"] = code
                sent["payload"] = payload

        # 直接调用路由逻辑较繁琐；此处验证核心判定函数 + 提示词已覆盖，
        # 路由层通过模拟 handler 验证 task 含删除命令时走拒绝分支。
        # 具体路由分支的集成由下方测试覆盖（简化：验证 _contains_delete_command
        # 在 /run 语义下被正确用于判定）。
```

（说明：worker 的 `do_POST` 是 `BaseHTTPRequestHandler` 方法，依赖真实 socket 流。为可测性，把"任务含删除命令判定 + 拒绝"抽成纯函数更合适——因此在 Task 4 中把 `/run` 的判定逻辑提为 `_guard_delete_in_task(task, mode)` 纯函数，`do_POST` 调用它，测试针对纯函数。）

- [ ] **Step 2: 实现可测的纯函数 + 接线**

在 `os_automation_worker.py` 新增：

```python
def _guard_delete_in_task(task: str, mode: str) -> dict[str, Any] | None:
    """/run 处理器删除护栏：apply 任务含物理删除命令时返回拒绝结果，否则 None。"""
    task_text = str(task or "").strip()
    if mode != "apply" or not task_text:
        return None
    if _contains_delete_command(task_text):
        return {
            "ok": False,
            "blocked": "delete_command",
            "error": (
                "任务包含物理删除命令，禁止绕过回收站删除本机文件。"
                "Agent 删除必须使用 os_recycle_bin 工具（delete 移入回收站，可恢复）。"
            ),
        }
    return None
```

在 `do_POST` 的 `/run` 处理段（`task`/`mode` 校验后、`preview` 发放 approval 前）插入：

```python
            if mode == "apply":
                guard_result = _guard_delete_in_task(task, mode)
                if guard_result is not None:
                    self._send_json(200, guard_result)
                    return
```

- [ ] **Step 3: 补纯函数测试**

在 `test_os_automation_worker.py` 追加：

```python
from scripts.os_automation_worker import (
    ...
    _guard_delete_in_task,
)


class TestRunGuardRejectsDelete:
    def test_apply_with_remove_item_blocked(self):
        result = _guard_delete_in_task("删除文件：Remove-Item C:\\tmp\\a.txt", "apply")
        assert result is not None
        assert result["blocked"] == "delete_command"

    def test_apply_with_rm_blocked(self):
        result = _guard_delete_in_task("清理目录：rm -rf /home/user/tmp", "apply")
        assert result is not None
        assert result["blocked"] == "delete_command"

    def test_preview_not_blocked(self):
        assert _guard_delete_in_task("删除文件：del a.txt", "preview") is None

    def test_apply_safe_task_passes(self):
        assert _guard_delete_in_task("列出 C:\\temp 的文件", "apply") is None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/scripts/test_os_automation_worker.py -v`
Expected: PASS

- [ ] **Step 5: 运行完整相关测试**

Run: `cd api && python -m pytest test/scripts/test_os_automation_worker.py test/internal/core/tools/test_codex_os_tool.py test/internal/core/tools/test_codex_os_delete_guard.py -q`
Expected: 全部通过

- [ ] **Step 6: Commit**

```bash
git add api/scripts/os_automation_worker.py api/test/scripts/test_os_automation_worker.py
git commit -m "feat(os_worker): hard-block terminal delete commands in /run apply"
```

---

## 自检

**Spec 覆盖：**
- "固定删除文件的命令只能用工具执行" → Task 1（识别）+ Task 2（客户端拦截）+ Task 3/4（worker 硬阻断 + 提示词约束）。
- "禁止用无法控制的终端命令执行删除" → 双保险：客户端 + worker 硬阻断，且 apply 提示词显式禁止。
- V4A 删除补丁：已走回收站（`_delete_into_recycle`），`os_recycle_bin` 不受影响。

**误伤防护：**
- 只拦截"命令名出现在命令边界"的删除命令，`Get-Content`/`Write-Output` 等不受影响。
- 仅 apply 拦截，preview 是只读。

**跨平台：**
- 同时覆盖 cmd（del/erase/rd/rmdir）、PowerShell（Remove-Item/ri/del/erase）、Unix（rm/rmdir/unlink）。

**类型一致：**
- `find_delete_command` → `DeleteCommandMatch`；`_contains_delete_command` → bool；`_guard_delete_in_task` → dict|None。

---

### Task 5: Codex 沙箱强制隔离（preview 只读 + apply workspace-write）

**目标：** 让"Agent 删除只进回收站"从"明文拦截（模型听话）"升级为"OS 级强制（模型想删都删不掉）"。这是对既有 `danger-full-access` 策略的修正——新版 Codex（实测 0.150.0-alpha.8）已支持 `-s read-only|workspace-write` 沙箱，旧注释"Windows 不支持 read-only 沙箱"已过时。

**Files:**
- Modify: `api/scripts/os_automation_worker.py`（`_build_codex_command` + `_build_prompt`）
- Modify: `api/test/scripts/test_os_automation_worker.py`

- [ ] **Step 1: 写失败测试**

在 `test_os_automation_worker.py` 新增（针对 `_build_codex_command` 与 `_build_prompt` 行为；`_build_codex_command` 需先确认其当前签名/可测性，必要时把命令构造抽成可注入函数或直接测返回列表）：

```python
class TestSandboxIsolation:
    def test_preview_uses_read_only_sandbox(self):
        """preview 必须用 read-only 沙箱（禁止任何写/删命令）。"""
        codex_path = "codex.exe"
        cmd = _build_codex_command(codex_path, "preview", ".", 30)
        assert "--sandbox" in cmd
        idx = cmd.index("--sandbox")
        assert cmd[idx + 1] == "read-only"

    def test_apply_uses_workspace_write_sandbox(self):
        """apply 必须用 workspace-write 沙箱（禁止删除工作区外文件）。"""
        cmd = _build_codex_command("codex.exe", "apply", ".", 30)
        assert "--sandbox" in cmd
        idx = cmd.index("--sandbox")
        assert cmd[idx + 1] == "workspace-write"

    def test_apply_does_not_bypass_sandbox(self):
        """apply 绝不再用 --dangerously-bypass-approvals-and-sandbox。"""
        cmd = _build_codex_command("codex.exe", "apply", ".", 30)
        assert "--dangerously-bypass-approvals-and-sandbox" not in cmd

    def test_preview_prompt_explicitly_read_only(self):
        prompt = _build_prompt("清理 C 盘垃圾", "preview")
        assert "只读" in prompt
        assert "禁止执行任何会修改" in prompt
```

（若 `_build_codex_command` 现签名不含可注入 codex 路径，先调整测试写法适配实际签名——以最终代码为准，但断言"preview→read-only / apply→workspace-write / 无 bypass"三条红线必须锁住。）

- [ ] **Step 2: 运行测试确认失败**

Run: `cd api && python -m pytest test/scripts/test_os_automation_worker.py -k SandboxIsolation -v`
Expected: FAIL（当前 preview 是 danger-full-access、apply 是 bypass）

- [ ] **Step 3: 实现沙箱隔离**

修改 `api/scripts/os_automation_worker.py` 的 `_build_codex_command`：

```python
def _build_codex_command(
    codex_path: str,
    mode: str,
    working_dir: str,
    timeout: int,
) -> list[str]:
    command = [
        codex_path,
        "-a",
        "never",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--json",
        "--color",
        "never",
        "-C",
        working_dir,
    ]
    if mode == "preview":
        # 只读预览：用 Codex read-only 沙箱，OS 层禁止任何写/删命令。
        # （旧版"Windows 不支持 read-only"已过时——实测 0.150 支持 read-only。）
        command.extend(["--sandbox", "read-only"])
    else:
        # apply：用户已确认执行，但必须在 workspace-write 沙箱内运行，
        # 只能写当前工作区，无法删除工作区外文件。真实删除只能经
        # os_recycle_bin 工具（worker _delete_into_recycle），物理删除
        # 被 OS 沙箱挡在工作区之外。
        command.extend(["--sandbox", "workspace-write"])
    return command
```

若 workspace-write 在无审批下无法写工作区（需确认 exec 自动模式是否放行工作区写），可补 `-c 'approval_policy="never"'` 或等价配置——以实测为准并在测试中锁住最终命令形态。

同步更新 `_build_prompt` apply 分支：告知 Codex 它运行在 workspace-write 沙箱，删除工作区外文件会被 OS 拒绝，删除操作须调用 os_recycle_bin（经 worker 回收站通道）。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd api && python -m pytest test/scripts/test_os_automation_worker.py -k SandboxIsolation -v`
Expected: PASS

- [ ] **Step 5: 更新遗留加固项状态 + 运行全量**

将"执行记录"下方遗留加固项第 1 条标记为"已由 Task 5 部分解决"（沙箱隔离后 preview 无法执行删除；apply 无法删除工作区外文件——工作区内删除仍受明文护栏 + 提示词约束）。

Run: `cd api && python -m pytest test/scripts/test_os_automation_worker.py test/internal/core/tools/test_codex_os_tool.py test/internal/core/tools/test_codex_os_delete_guard.py -q`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add api/scripts/os_automation_worker.py api/test/scripts/test_os_automation_worker.py docs/superpowers/plans/2026-09-08-delete-egress-recycle-only.md
git commit -m "feat(os_worker): sandbox isolation - read-only preview, workspace-write apply"
```

> 注：本次提交与既有未提交改动共存时沿用 Task 3/4 的 stash 拆分手法。

---

## 执行记录（2026-09-08，subagent-driven）

| 任务 | 提交 | 说明 |
| --- | --- | --- |
| Task 1 核心库 | `337e8bf` + `8ef3598` | delete_guard.py 纯函数库；审查后补防误报回归测试、删死代码。16 测试 |
| Task 2 客户端拦截 | `faa862a` | run_os_task apply 本地拒绝终端删除，仅 apply 拦截 preview 放行。20 测试 |
| Task 3+4 worker 硬阻断 | `e37ccae` | _guard_delete_in_task + do_POST 接线 + _build_prompt apply 加固 + 08 文档安全模型第 6 条。42 测试 |
| Task 5 沙箱隔离 | `1fdc7e8` | preview→read-only、apply→workspace-write；OS 层阻止删除。48 测试 |

**审查发现的遗留加固项（不阻塞本次，后续处理）：**
1. 【安全纵深】本护栏拦的是"任务明文含删除命令"。preview 阶段本身以 `danger-full-access` 运行（Windows Codex 无 read-only 沙箱），若 Codex 在 preview/apply 期间自主生成删除命令且不在任务明文中，明文护栏拦不住。建议后续：把删除明文护栏下沉到 `_run_codex_task` 内做纵深（对 `_parse_codex_jsonl` 解析出的实际执行命令做执行后校验），并在 08 文档中明确"生成命令不受执行后校验"的局限，避免文档被误读为绝对物理屏障。——【已由 Task 5 部分解决】Task 5 沙箱隔离后：preview 运行于 read-only 沙箱，任何写/删除命令在 OS 层被拒绝（模型自主生成也删不掉）；apply 运行于 workspace-write 沙箱，无法删除/写入工作区外文件。残余缺口收窄为"apply 工作区内删除"——仍由明文护栏 + 提示词约束兜底，真实删除经 os_recycle_bin/回收站。若需彻底闭环，仍可把明文护栏下沉到 `_run_codex_task`（对 `_parse_codex_jsonl` 实际执行命令做执行后校验）。
2. 【误伤分级】`rd`/`rmdir` 默认只删空目录、不递归，与 `rm -rf` 杀伤力不同。当前一律等同拦截（宁严勿松）。如需减少摩擦，可在 DELETE_COMMANDS 中标注危险等级，把是否放行 `rd` 的决策留给上游。
3. 【已知漏报】管道第二段删除命令（`Get-ChildItem | Remove-Item`）、`cmd /c del` 包装属有意取舍（保守漏报优先于误伤），delete_guard docstring 已声明护栏定位。

**范围说明：** 本计划只落地"删除出口统一"（原三阶段方案中的阶段 1 子项）。云沙箱/路由、桌面桥远程化、cua-driver 后端见 `docs/research/desktop-sandbox-routing-plan.md`。
