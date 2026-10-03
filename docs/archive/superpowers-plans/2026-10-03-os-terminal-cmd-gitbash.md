# 本机终端工具（Windows：CMD + GitBash）实施计划

> 状态：**已实施**（落地记录见本文件末「实施结果」；按仓库规则，落地后归档到 `docs/archive/superpowers-plans/`）
> 日期：2026-10-03
> 关联模块：[docs/prd/modules/08-os-automation.md](../../prd/modules/08-os-automation.md)

## 背景与目标

让 Agent 能在用户本机（Windows）通过命令行工具执行命令：**CMD** 与 **GitBash** 双 shell。
硬约束：**禁止 Agent 用终端删除命令绕过删除治理**——本机删除只能走 `os_recycle_bin`
（移入回收站、可恢复）；终端删除命令一律硬阻断（fail-closed），并引导 Agent 改用删除工具。

### 历史教训（必须避免重蹈）

2026-09-08 曾上线 `run_os_task`（Codex CLI 全权执行）+ worker `/run` + `delete_guard`，
同日整体删除（`4aee37f0`、`faa862ab`）。失败原因：

1. `delete_guard` 只做「行首命令名匹配」，绕过面极大（管道、嵌套解释器、脚本文件、base64）；
2. 守卫挂在已被删除的全权执行通道上，通道本身能力过大（可写任意路径、跑任意程序）。

本次重建的两个前提：**执行面收窄**（工作目录限定安全根）+ **守卫显著增强**（多层解析 + 递归）。

## 现状（对齐证据）

- worker `api/scripts/os_automation_worker.py` 现有端点：`/file`、`/recycle`、`/snapshot`，**无 /exec**。
- 桌面桥 `desktop/bridge.js` 路由表：`/file /recycle /snapshot /browser /control /render /artifact`，**无 /exec**。
- 平台侧 Agent 无任何通用终端工具；`execute_code` 仅远端沙箱、默认关闭。
- 删除治理：`os_recycle_bin` → worker `_delete_into_recycle`（移入 `<safe_root>/.yujianwo_recycle`，可恢复，平台回收站同步 `deleted_by_type=agent`）。

## 设计

### 1. 分层防御（从外到内）

| 层 | 位置 | 作用 |
| --- | --- | --- |
| L1 提示词 | `api/internal/core/prompts/system_prompts.yaml` | 声明「删除只走 os_recycle_bin，终端删除命令会被拒绝」 |
| L2 工具描述 | `os_terminal` 工具 `description` | 同上，Agent 在工具选择阶段即知约束 |
| L3 **硬阻断（唯一权威入口）** | worker `find_blocked_delete()`，命令执行**前** | 命中即拒绝执行，返回结构化引导；**不在工具侧重复实现**（避免双实现漂移） |
| L4 执行面收敛 | worker `_exec_operation()` | cwd 必须在安全根内；子进程 env 剥离 worker 自身 token；超时杀进程树；输出限长 |

### 2. 删除守卫算法（`find_blocked_delete`）

对命令文本做**归一化 → 分段 → 段首命令名匹配 → 递归内联代码 → 危险模式**五步：

1. **归一化**：剥离成对引号/反引号与反斜杠转义（`r''m` → `rm`）、统一小写。
2. **分段**：按 `;` `&&` `||` `|` `&` 换行 `()` `{}` 切分，逐段取**段首 token** 归一化
   （去路径前缀、去 `.exe/.cmd/.bat/.com/.ps1` 后缀）。
3. **命令名命中**：`rm rmdir del erase rd unlink remove-item ri` 等 → 拒绝。
4. **递归内联代码**（深度 ≤ 3）：解释器 `cmd/bash/sh/powershell/pwsh/python/node/perl/ruby/forfiles/wsl`
   的内联参数（`-c /c -Command -e -EncodedCommand` 等）取出后递归扫描；
   `-EncodedCommand` 的 base64 解码（UTF-16LE）后扫描。
   **脚本文件**：`bash script.sh` / `python script.py` 的已存在文件参数，读内容递归扫描。
5. **危险模式**（仅在内联代码/脚本内容上，避免 `echo "rm -rf"` 误伤）：
   `shutil.rmtree` / `os.remove(` / `os.unlink(` / `.unlink()` / `fs.rm(` / `[IO.File]::Delete` /
   `find -delete` / `xargs rm` / `git rm` / `git clean` / `robocopy /mir` / `rsync --delete` /
   `b64decode('...')` 解码后再递归。
   另加：**管道右侧为解释器（`curl ... | bash`）→ 拒绝**（下载即执行无法审计）。

命中返回 `{blocked, reason, command}`；未命中才执行。

### 3. shell 集成（Windows）

| shell | 解析 | 执行 |
| --- | --- | --- |
| `cmd`（默认） | `COMSPEC` 或 `%SystemRoot%\System32\cmd.exe` | `cmd.exe /d /s /c <command>` |
| `gitbash` | `GIT_BASH_PATH` → 常见安装路径（Program Files\Git\bin\bash.exe 等）→ `which bash`（排除 System32 的 WSL bash） | `bash.exe -c <command>` |

- 非 Windows：`cmd`/`gitbash` 均映射到 `sh -c`（保持接口一致，便于部署到 Linux 宿主机）。
- **输出解码**：先 UTF-8 严格解码，失败回退系统 ANSI 编码（Windows cp936），再兜底 `replace`。
- 超时（默认 60s，上限 300s）→ `taskkill /F /T`（Windows）/ `killpg`（POSIX）杀进程树。
- 输出上限 200KB 字符，超出截断并标注。
- `stdin=DEVNULL`（命令等待输入不会挂死 worker）。

### 4. 契约

```
POST /exec  {"command": str, "shell": "cmd"|"gitbash", "working_dir": str,
             "timeout_seconds": int, "requester": str}
→ 200 {"ok": true, "exit_code": int, "stdout": str, "stderr": str, "shell": str,
       "cwd": str, "duration_ms": int, "truncated": bool, "timed_out": bool}
→ 200 {"ok": false, "blocked": true, "reason": str, "error": str}   # 删除守卫拒绝
```

工具 `os_terminal` 经 `resolve_desktop_bridge(requester, purpose="/exec")` 转发，
与 `os_file_task` 同源（动态桌面设备优先，静态 env 回退）。

### 5. 文件与接线清单

| 动作 | 文件 |
| --- | --- |
| 改 | `api/scripts/os_automation_worker.py`（守卫 + `/exec` 端点 + handler 路由 + health 报告 shells） |
| 改 | `desktop/bridge.js`（targets 加 `/exec` → os worker 8765） |
| 改 | `desktop/main.js`（`createBridge` 加 `execPort/execToken`） |
| 新增 | `api/internal/core/tools/builtin_tools/providers/host_os/os_terminal.py` + `.yaml` |
| 改 | `.../host_os/positions.yaml`（加 `os_terminal`）、`.../host_os/__init__.py`（导出） |
| 改 | `api/internal/service/assistant_agent_service.py`（挂载 tuple 加 `os_terminal`） |
| 改 | `api/internal/core/prompts/system_prompts.yaml`（终端使用规范） |
| 新增测试 | `api/test/scripts/test_os_terminal_worker.py`、`api/test/internal/core/tools/test_os_terminal_tool.py` |
| 改文档 | `docs/prd/modules/08-os-automation.md`（路由表 + 安全模型 + 工具清单） |

### 6. 风险与取舍

- **风险等级**：`os_terminal` 走 `DEFAULT_TOOL_METADATA`（medium / 免确认），与 `os_file_task` 一致
  ——删除已硬阻断，终端用于构建/查询/测试；管理员可在 `/admin` 工具治理中上调等级或加确认。
- **不是沙箱**：终端可执行任意（非删除）程序，命令可越出安全根读取；本计划只承诺
  「删除类命令被阻断 + cwd 起点受安全根约束」，不承诺全命令沙箱。
- **已知绕过面**（诚实标注，不隐藏）：shell alias 内联定义后调用、将删除逻辑藏进被 import 的
  第三方模块、脚本运行时动态生成删除命令（如 `echo "$X" | bash` 其中 X 由运行时拼出）。
  这些属于"代码即数据"的不可判定问题；守卫定位为**护栏**而非形式化保证。

## 测试策略

- 守卫：纯文本表格化用例（正例：命中；反例：`echo "rm -rf"`、`grep -rn "del"`、`python -m pytest` 等不误伤）。
- exec：跨平台用 `sh` 分支验证回声/退出码/超时；Windows 专属用例验证 cmd 与 gitbash。
- 工具：monkeypatch `_call_worker` 验证 payload 组装与结果透传。
- 真机验证：Windows 本机启动 worker，实测 cmd/gitbash 执行 + 删除命令阻断。

## 实施结果（2026-10-03，已落地）

| 产物 | 文件 |
| --- | --- |
| 删除守卫 + `/exec` 端点 | `api/scripts/os_automation_worker.py`（`_find_blocked_delete` / `_exec_operation` / `_resolve_terminal_shell` / `_build_child_env` / `_truncate_output` / `_decode_console_output` / `_kill_process_tree`；handler 路由 + `/health` 新增 `terminal_shells`） |
| 桌面桥路由 | `desktop/bridge.js`（`/exec` → os worker 8765）、`desktop/main.js`（`execPort/execToken`）、`desktop/test/bridge.test.js`（+1 用例） |
| 平台工具 | `providers/host_os/os_terminal.py` + `os_terminal.yaml` + `positions.yaml` + `__init__.py` + `assistant_agent_service` 挂载四件套 |
| 调用收敛 | 新增 `providers/host_os/worker_client.py`（host_os 工具族 HTTP 单一入口），`os_file_task`/`os_recycle_bin`/`os_snapshot` 的 `_call_worker` 瘦身为薄包装 |
| 提示词 | `system_prompts.yaml` 新增规则 14（终端用法）/15（删除禁令），原 14-16 顺延为 16-18；原「临时目录可直接删」改为走 `os_recycle_bin`（消除与守卫的矛盾） |
| 测试 | `test/scripts/test_os_terminal_worker.py`（101 例）、`test/internal/core/tools/test_os_terminal_tool.py`（7 例）、desktop 桥测试 8 例 |
| 文档 | `docs/prd/modules/08-os-automation.md`（路由表 / 安全模型第 8 条 / 工具清单 / 验证）、`desktop/README.md`、`docs/prd/modules/09-desktop-client.md`、`docs/prd/product-vision.md` |

验证证据：
- `pytest test/scripts/test_os_terminal_worker.py` → **101 passed**（含 Windows 真机 cmd/gitbash 执行、删除阻断、超时杀进程树、env 剥离）。
- `node --test desktop/test/bridge.test.js` → **8 passed**。
- 真机端到端（worker 直连 18999）：`/health.terminal_shells={"cmd":true,"gitbash":true}`；
  `echo hello-from-cmd` → ok；`echo $((6*7))`(gitbash) → `42`；`git --version` → 2.49.0.windows.1；
  `del` / `rm` / `bash -c "rm -rf"` / `python -c os.remove` / `curl|bash` / `git clean -fdx`
  六种形态全部 `blocked=true` 且目标文件存活；`echo "rm -rf is dangerous"` 正常放行。

实施期对本计划初稿的设计修正（均已加回归用例）：
1. **分段器必须引号感知**：初版把 `python -c "a; b()"` 的引号内容按 `;` `(` 切碎，内联代码提取失真导致漏检——修复。
2. **命令名归一化只按逗号切分**：`print('rm -rf')` 引号串内的空格是参数语义，不得拆出命令名 `rm`——修复。
3. **嵌套超深 fail-closed**：超过扫描深度上限时拒绝执行（而非静默放行无法核验的命令）。
4. **提示词一致性**：原第 14 条允许直接删除临时目录，与守卫（无路径语义、一律阻断）矛盾——统一改为走 `os_recycle_bin`。
5. **补丁密度收敛**：新增第 4 个工具前先测量——`_call_worker` 已有 3 份近似副本，属「同一逻辑各写一套」，故收敛到 `worker_client.py` 单一入口，而非新增第 4 份。
6. **禁用于全局**：守卫在 worker 端对 cmd/gitbash 统一生效（不分 shell），GitBash 里的 `cmd //c del` 等跨 shell 调用同样被拦。

## 后续演进（2026-10-04，已落地）

1. **终端定位修正（主力执行手段）**：初版把 `os_terminal` 写成"用户要求时使用"的可选工具，
   与"命令行是 AI 干活的主路径"相悖。已重写工具描述（"本机任务的主力执行手段，不是可选补充"）、
   系统提示词（规则 10 主动式 / 11 三件套分工 / 12 删除禁令）、`task_keywords`（覆盖作业语义），
   并新增 7 个 ToolSelector 真实性回归用例（读 `os_terminal.yaml`，锁住"作业语义 query →
   关键词快通道命中"）；默认 shell 由 cmd 改为 gitbash（Unix 语法对模型更友好）。
2. **写前快照（改坏可回滚）**：终端命令改动面不可预知，补丁式"按目标文件精确快照"不适用。
   已实现**工作目录级增量写前快照**（内容寻址、复用补丁的快照 manifest 与 `os_snapshot`
   回滚链路，`source=os_terminal` / `taken_before=terminal`、按 `conversation_turn` 分组）：
   (size, mtime_ns) 指纹增量；排除 node_modules/.git/dist 等可再生目录；扫描超 20000 文件
   或 500MB 降级并提示（命令仍执行）；快照写入失败则拒绝执行（fail-closed）；执行后对比
   指纹产出 `changes`（modified/created/removed）。回滚复用 `rollback_file` / `rollback_turn`，
   并新增 `session_id`/`conversation_turn` 透传使终端快照可按轮批量回滚。
3. **provider 调用单入口收编**：`worker_client.py` 提升到 `providers/` 包根并参数化
   （静态回退 env 名 / 不可用文案 / 超时），`browser_action`、`computer_action` 与 host_os
   四工具共六份 `_call_worker` 全部收敛；文档标注"禁止再新增同构副本"。
4. **cmd 引号缺陷修复**：Python `list2cmdline` 的 `\"` 转义与 cmd.exe 解析规则不兼容，
   会把 `> "C:\a b\x.txt"` 这类引号路径弄坏；改用字符串命令行 `cmd /d /s /c "<命令>"`
   逐字传递，并加 cmd/gitbash 双回归用例。
