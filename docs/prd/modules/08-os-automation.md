# 宿主机 OS 自动化

> 更新日期：2026-10-03（新增 `/exec` 终端通道与删除命令守卫、`os_terminal` 工具挂载；上一版 2026-09-19 新增本机渲染路由）
>
> ✅ **实现状态（2026-09-11）**：本文描述的"用户端自然语言提出本机任务 → 平台 Agent 调用宿主机 worker"这条**服务端 → 宿主机方向**的链路**已打通**。桌面端登录后把本机 bridge 地址与随机 token 上报服务端（`desktop_device` 表，按账号存储），服务端经 `resolve_desktop_bridge(account_id, purpose=...)` 动态解析出该账号默认在线设备的 bridge，替代静态 `DESKTOP_BRIDGE_URL/TOKEN`；静态配置仍作回退。容器内 `host.docker.internal` 可达宿主机回环（已实测）。实现细节见 [product-vision.md §4.1](../product-vision.md)。
>
> **宿主壳关联**：本文描述的 `os_automation_worker.py`（及 browser/computer/render/wake worker）由桌面客户端托管与分发——Windows 桌面端以单一 `yujianwo-worker.exe`（PyInstaller + worker_super 子命令入口）随安装包携带，Electron 主进程 spawn 启动（开发模式回退 python 脚本）。桌面壳架构见 [09-desktop-client.md](./09-desktop-client.md)。

## 目标

让用户在钰见我 用户端自然语言提出本机文件操作任务（例如“读一下 C 盘的项目代码”“改一下配置并重启后回滚”），
由平台 Agent 调用宿主机自研 worker，在真实操作系统安全目录内执行读取、搜索、V4A 补丁修改、
回收站删除/恢复与写前快照回滚——纯 Python，不依赖外部 CLI。

## 架构

```text
用户端 / 首页助手 / 平台回收站
  → AssistantAgentService 挂载 os_file_task / os_recycle_bin / os_snapshot / os_terminal（内置工具）
     （构建期注入 requester=account_id；computer_action 同）
  → resolve_desktop_bridge(account_id, purpose="/file")
     ├─ 动态：desktop_device 表（该账号默认在线设备的 bridge_origin + 解密 token）
     └─ 回退：DESKTOP_BRIDGE_URL/TOKEN 或 OS_AUTOMATION_URL/TOKEN（静态）
  → 桌面端本地能力桥 desktop/bridge.js（127.0.0.1:9876）
  → 宿主机 os_automation_worker.py（api/scripts/os_automation_worker.py，HTTP 8765）
     ├─ /file      → read / list / search / V4A patch（preview 只读 dry-run；apply 写前快照）
     ├─ /recycle   → delete（移入回收站）/ list / restore / purge
     ├─ /snapshot  → rollback_file / rollback_turn / list_snapshots
     └─ /exec      → 终端命令（Windows: cmd / gitbash；执行前删除命令守卫 fail-closed）
```

> 所有对用户主机 worker 的 HTTP 调用由 `providers/worker_client.py` 单点承载
> （`call_host_worker(purpose=..., static_url_env=..., unavailable_error=...)`）：
> 动态 bridge 优先、静态凭证回退、统一鉴权与错误文案；消费方为 `host_os` 四工具
> （`/file` `/recycle` `/snapshot` `/exec`）、`browser_automation`（`/browser`）、
> `computer_control`（`/control`），各工具模块只保留同名薄包装 `_call_worker`
> （既有单测的注入点）。**2026-10-04 完成收编**：此前六份近似副本（差异仅在 purpose、
> 静态回退 env 名、不可用文案与超时推导）已全部收敛到该单入口，禁止再新增同构副本。

本地能力桥（`desktop/bridge.js`，`127.0.0.1:9876`）的路由表——服务端工具不直接连 worker，
统一经 bridge 转发到对应 worker：

| 桥路由 | 目标 worker | 端口 |
| --- | --- | --- |
| `POST /file` | os worker | 8765 |
| `POST /recycle` | os worker | 8765 |
| `POST /snapshot` | os worker | 8765 |
| `POST /exec` | os worker | 8765 |
| `POST /browser` | browser worker | 8766 |
| `POST /control` | computer worker | 8767 |
| `POST /render` | render worker | 8768 |
| `POST /artifact` | render worker | 8768 |

> ⚠️ **服务端工具必须经 `resolve_desktop_bridge(account_id, purpose=...)` 解析 bridge，勿只读静态 env**
> （如 `DESKTOP_BRIDGE_URL/TOKEN`、`OS_AUTOMATION_URL/TOKEN`）：桌面端 bridge token 由主进程每次启动
> 随机生成，只有注册到 `desktop_device` 才能解析到（见上文「历史缺陷」）。`purpose` 传入目标路由
> （如 `/render`、`/artifact`、`/file`），解析结果即该账号默认在线设备的 bridge 地址与 token。

**解析路径只有一条（工具与平台回收站同源）**：Agent 工具（`os_file_task` /
`os_recycle_bin` / `os_snapshot` / `os_terminal` / `computer_action`）与平台回收站的
`restore` / `purge` 本机文件，**都经 `resolve_desktop_bridge`** 解析 bridge，
不存在两套逻辑。`recycle_bin_handlers._worker_recycle_endpoint(account_id)` 与工具侧
同源；归属账号取自回收站条目的 `_owner_account_context()`（`deleted_by_type` 为
`user`/`agent` 时用 `deleted_by`，`admin` 条目不含账号语义故返回 `None` 退回静态配置）。

> **历史缺陷（已修复）**：`_worker_recycle_endpoint` 曾只读静态 env，不调
> `resolve_desktop_bridge`。桌面端 token 是每次启动随机生成的
> （`desktop/main.js` 的 `randomBytes(24)`），只有注册到 `desktop_device` 才能解析到；
> 因此在**未配静态 env 的纯动态注册场景**下，「agent 删了本机文件 → 用户在平台回收站
> 里恢复/销毁」必然失败（统一报 `desktop_bridge_resolver.DESKTOP_UNAVAILABLE_MESSAGE`：
> 「未找到可用的本机连接……请安装并登录桌面端」，见 `api/internal/service/desktop_bridge_resolver.py`），
> 而同一账号的 Agent 工具却能正常工作。回归测试见
> `api/test/internal/service/test_recycle_bin_handlers.py::TestWorkerRecycleEndpointResolution`。

平台容器运行在 Docker 内，默认不直接接触宿主机磁盘。宿主机侧常驻轻量 HTTP worker，
以 `Bearer <OS_AUTOMATION_TOKEN>` 鉴权，所有文件操作限制在安全根目录内
（`OS_AUTOMATION_SAFE_ROOT`，缺省当前用户主目录）。

## 安全模型

1. worker 仅接受 `Authorization: Bearer <OS_AUTOMATION_TOKEN>` 的请求，缺省监听回环地址。
2. `/file` 的 V4A 补丁：
   - `mode=preview`：只读 dry-run——在临时副本上模拟补丁，校验路径/格式/可应用性，
     不修改真实文件、不删除文件、不移入回收站。响应仍携带 `approval_token` 仅为兼容旧客户端结构。
   - `mode=apply`：直接执行（**无需逐次人工确认**）。每次真实写文件前自动捕获写前快照
     （fail-closed：快照失败拒绝本次写）；删除类操作移入本机回收站（可恢复）。
3. **回滚兜底取代人工确认**：
   - 改错 → `os_snapshot` `rollback_file`（单文件）或 `rollback_turn`（按用户消息轮批量恢复）。
   - 误删 → `os_recycle_bin` `list` + `restore`。
   - 快照全存宿主机本机隐藏目录（`<safe_root>/.yujianwo_snapshots`），默认留存 7 天后 GC 清理。
4. `os_file_task` 已移出 `ToolPolicy._DEFAULT_HIGH_RISK_TOOL_NAMES`：Agent 修改本机文件不再弹
   高风险确认窗口（由快照+回收站自愈闭环兜底）。其余高风险工具（send_email/execute_code/
   browser_action/computer_action 等）仍走原确认链路。
5. **动作审计不放开**：os_file_task/os_recycle_bin/os_snapshot 的每次调用仍以
   AgentThought（AGENT_ACTION 事件，含谁/哪台设备/工具入参/结果）全程记录，
   与高风险名单解耦（名单只决定是否弹确认，不决定是否审计）。
6. 越界防护：任何路径先经 `_is_path_within`/`_resolve_safe_root` resolve 判定，dry-run 与
   apply 口径一致，含 `..` 段的越界路径一律拒绝。
7. **敏感读取黑名单**：写/删免确认放开后，读取面由 worker 读黑名单兜底——
   `/file` read/search 命中敏感路径（`~/.ssh` 私钥、`.env*` 密钥文件（`.env.example`
   除外）、`id_rsa`/`*.pem`/`*.pfx` 私钥类文件、浏览器凭据目录
   `User Data`/`Login Data`/`logins.json`/`key4.db`、`.aws`/`.kube`/`.gnupg`/`.npm`
   等凭据目录、`.yujianwo_recycle`/`.yujianwo_snapshots` 自管目录）直接拒绝且不读取内容；
   search 还会以 rg 排除 glob 跳过敏感目录与文件，敏感路径不进搜索结果。
8. **终端（`/exec`）删除守卫（fail-closed）**：终端是任意命令通道，若放行物理删除命令即可
   绕过「删除只进回收站」治理，因此 worker 在执行**前**扫描命令文本，命中删除语义即拒绝执行
   并引导改用 `os_recycle_bin`（统一文案含删除工具名）。覆盖形态：
   - 删除命令名：`rm`/`del`/`erase`/`rd`/`rmdir`/`unlink`/`Remove-Item`/`ri`/`shred`/`sdelete`/
     `trash`/`format`/`diskpart`（含去路径前缀、去 `.exe` 等后缀、大小写、引号拼接 `r''m`）；
   - 命令包装器：`sudo`/`doas`/`env`/`nohup`/`timeout`/`wsl` 等前缀后接删除命令同样命中；
   - 组合形态：`xargs rm`、`find -delete` / `find -exec rm`、`git rm` / `git clean`、
     `robocopy /MIR`、`rsync --delete`；
   - 嵌套解释器内联代码：`cmd /c`、`bash -c`、`sh -c`、`powershell -Command`、`python -c`、
     `node -e`、`perl -e`、`forfiles /c`（递归 ≤3 层，超限同样拒绝而非放行）；
   - 编码载荷：PowerShell `-EncodedCommand` 与内联代码中的 `b64decode(...)`/`atob(...)`
     解码后再扫描；
   - 脚本文本件：`bash script.sh` / `python script.py` 读取脚本内容递归扫描（二进制跳过）；
   - 管道到解释器：`curl ... | bash`（内容不可审计，直接拒绝）；
   - 删除 API 模式：`shutil.rmtree`、`os.remove/unlink/rmdir`、`.unlink()`、
     Node `fs.rm/rmSync/unlinkSync`、`.NET [IO.File]::Delete` 等。
   执行面同时收窄：工作目录必须落安全根内（越界回退安全根）、子进程环境剥离 worker 自身
   凭证 token（防 `echo %OS_AUTOMATION_TOKEN%` 反调 worker）、超时（默认 60s／上限 300s）
   杀进程树、stdin 关闭、输出上限 200K 字符。
   **已知绕过面（守卫是护栏而非形式化沙箱，不承诺穷尽）**：shell alias 内联定义后调用、
   把删除逻辑藏进被 import 的第三方模块、运行时动态拼出的删除命令——属「代码即数据」的
   不可判定问题，由提示词约束 + 平台侧调用审计兜底。命中与误伤取舍按 fail-closed：
   字符串中出现删除命令名（如 `node -e "x=['rm','-f']"`）会被拒绝，Agent 应改用
   `os_file_task` / `os_recycle_bin` 完成任务。
9. **终端写前快照（改坏可回滚，范围跟随写入面）**：终端命令会改哪些文件无法预知，不能像
   V4A 补丁那样按目标文件精确快照，因此 `/exec` 在启动进程前做增量快照（内容寻址，与补丁
   共用 `.yujianwo_snapshots` manifest 与 `os_snapshot` 回滚链路；条目标记
   `source=os_terminal`、`taken_before=terminal`，并按注入的 `conversation_turn` 分组）。
   **快照范围 = 工作目录 + 命令文本中引用的、安全根内真实存在的目录**（Windows 盘符路径与
   GitBash 的 `/d/...` 形式都会提取）——覆盖「一条命令顺手改了 cwd 之外文件」的场景，
   治理范围跟随 Agent 的实际写入面而不是只盯 cwd；manifest 统一落安全根（多根不分裂），
   各扫描根独立维护增量基线：
   - **增量**：以 (size, mtime_ns) 指纹判断，只有自上次快照后变化的文件才重新计算哈希/落盘；
     首次进入某工作目录为全量。Worker 重启后缓存清空、自动回到全量，语义不变；
   - **排除**：node_modules / .git / dist / build / venv / \_\_pycache\_\_ / target /
     .yujianwo_recycle / .yujianwo_snapshots 等可再生或自管目录不进快照（这些目录内的
     改动不提供回滚，重装/重建即可恢复）；
   - **上限降级**：单次扫描超过 20000 文件或 500MB 时降级为"不快照"，结果携带
     `snapshot.status="skipped_too_large"` 与引导文案（建议 `working_dir` 指向具体项目
     目录），命令仍执行——不因大目录阻断终端可用性；
   - **fail-closed**：快照写入失败（磁盘满/权限异常）时**拒绝执行**命令，保证
     「执行过的命令都可回滚」这一不变式；
   - **改动清单**：执行后重新对比指纹，结果附 `changes`（modified/created/removed，
     相对工作目录、cwd 外显示绝对路径，各截断 50 条）——Agent 与用户都能看到本次命令
     实际动了哪些文件；
   - **自愈信号**：命令失败/超时且已有文件被改动时，结果附 `recovery_hint`——引导 Agent
     按 changes 自查、确认改坏后**立即自行调用 os_snapshot 回滚**（回滚是 Agent 的
     自主义务，不等用户提出；成功命令的改动不触发提示，避免误报）；
   - **回滚入口（复用，不新增）**：`os_snapshot` 的 `rollback_file`（单文件）与
     `rollback_turn`（按轮批量，覆盖该轮终端与补丁的全部改动）。
   **cmd 引号处理**：Windows 侧用字符串命令行 `cmd.exe /d /s /c "<命令>"` 而非 list 传参
   ——Python 的 `list2cmdline` 转义（`\"`）与 cmd.exe 解析规则不兼容，会把命令里的引号
   路径（如 `> "C:\a b\x.txt"`）弄坏；`/s` 剥掉外层引号、命令原文逐字传递（回归测试
   `test_exec_cmd_handles_quoted_path_with_spaces`）。

### 治理模型矩阵（能力 × 治理手段 × 边界）

治理边界必须与 Agent 的真实能力边界对齐——Agent 经电脑控制天然可达整机，若治理只覆盖
工作区，快照/回收站就会被 GUI 路径整体绕过。当前模型按**可逆性**分档：可逆操作自动化
（快照/回收站兜底），不可逆操作人审（逐次确认）并以禁令把文件操作引导回治理通道：

| 能力 | 治理手段 | 边界 | 残余风险（诚实标注） |
| --- | --- | --- | --- |
| `os_file_task`（读/搜/补丁） | 逐文件精确快照 + 删除进回收站；敏感读黑名单 | 安全根（默认用户主目录） | 超过单文件上限（50MB）的内容不做快照 |
| `os_recycle_bin`（删除） | 移入本机回收站 + 平台回收站同步（按 deleted_by_type 区分留存期） | 安全根 | — |
| `os_terminal`（命令） | 删除命令硬阻断 + 写前快照（cwd + 命令引用目录）+ `changes` 清单 + `recovery_hint` 自愈信号 | 安全根内、跟随命令实际写入面 | 排除目录（node_modules 等）不回滚；目录超限降级并明示 |
| `os_workspace_scope`（范围扩展） | 用户逐次确认（`always_confirm_tool_names`，不受轮内放行/智能审批影响）+ TTL 12h + 上限 8 个/会话 + 可撤销 | 扩展至任意目录，但每次扩展都是**用户显式批准** | 授权目录应由用户判断是否可信（确认弹窗显示目录与原因） |
| `computer_action`（GUI） | **按入参分档确认**（`ToolPolicy.requires_confirmation`）：纯观察动作（screenshot/capture/list_apps/list_windows）免确认；会改 GUI 状态的动作轮内首次确认、批准后本轮回合内放行（`authorized_tools` 随 state 累积）；文件操作禁令（工具描述与系统提示词双层） | 整机（GUI 天然全机可达） | 模型违反禁令经 GUI 改文件时无快照兜底——由确认弹窗的人审把关，这是刻意的分档而非漏洞 |

**边界成立性论证**：
1. 文件三件套的一切写/删都在安全根内且可回滚——自动化区域的治理是完备的；
2. 安全根之外：文件工具**硬拒绝**（`_resolve_safe_root` 越界回退），能触达整机的是
   电脑控制，而它被锁在「逐次人工确认」档——**可逆的自动、不可逆的人审**，两种治理
   模式分别匹配两类操作的风险性质；
3. 终端删除命令被 worker 端硬阻断（与工具/提示词无关的最终闸门），GUI 路径被禁令
   引导回三件套，电脑控制的确认弹窗构成最后的人审闸门。

**会话级工作区授权（已落地 2026-10-04）**：三件套与 GUI 的覆盖缺口 = 安全根之外的目录，
已实现会话绑定授权根：工具越界返回 `needs_scope_grant` → Agent 调用 `os_workspace_scope`
（高风险、**每次必确认**）→ 用户批准 → 落 `session_workspace_scope` 表（TTL 12h、
上限 8 个/会话）→ 后续调用经 `worker_client` 单点注入 `session_scopes` → worker 按
「安全根 ∪ 会话授权根」校验，scope 内享受同构治理（写前快照/回收站/删除守卫）。
未授权越界**拒绝执行**（不再静默回退，避免在错误目录执行命令）；不存在的目录仍宽容回退。
GUI 体验侧：纯观察动作免确认、轮内一次放行、管理员智能审批策略可进一步放行。
设计与落地记录见 [archive/superpowers-specs/2026-10-04-session-workspace-scope-design.md](../archive/superpowers-specs/2026-10-04-session-workspace-scope-design.md)。

## 环境变量

在 `api/.env` 配置：

```dotenv
OS_AUTOMATION_URL=http://host.docker.internal:8765
OS_AUTOMATION_TOKEN=replace-with-strong-token
OS_AUTOMATION_SAFE_ROOT=C:\Users\Administrator
OS_AUTOMATION_SNAPSHOT_RETENTION_DAYS=7
OS_AUTOMATION_SNAPSHOT_MAX_BYTES=52428800
```

宿主机 worker 启动：

```powershell
$env:OS_AUTOMATION_TOKEN="replace-with-strong-token"
python api/scripts/os_automation_worker.py --host 127.0.0.1 --port 8765
```

健康检查：

```powershell
curl.exe -H "Authorization: Bearer <token>" http://127.0.0.1:8765/health
```

## 平台工具

内置 `host_os` provider（展示名"本机文件操作"）下四个工具已预挂载到首页助手（`assistant_agent_service`）：

> **命名说明**：该 provider 原名 `codex_os`，现目录与 provider name 均已更正为 `host_os`（`api/internal/core/tools/builtin_tools/providers/host_os/`，DB 侧由迁移 `q3d4e5f6a7b8` 迁移）。原 Codex CLI 链路（`run_os_task` 工具 + worker `/run` 端点 + `delete_guard`）已于 2026-09-08 **整体移除**，原因是 Codex 强依赖 OpenAI（ChatGPT 登录/API key + 地区限制），ToC 不可行且 Windows 沙箱为 experimental；DB 残留由迁移 `0a1b2c3d4e6f` 清理。现存三件套为**纯 Python 自研**（`os_automation_worker.py` 中已无任何 Codex 依赖），`providers.yaml` 描述即"纯 Python 实现，不依赖外部 CLI"。**不要把 `host_os` 理解为依赖 Codex。**

- `os_file_task`：op=`read`（支持分页）/ `list`（枚举目录直接子项，目录在前，敏感项自动跳过）/ `search`（ripgrep）/ `patch`（V4A）。
  `patch` 默认 `mode=apply` 直接修改（写前自动快照）；`mode=preview` 只读 dry-run 预检查。
  `approval_token` 为历史兼容字段，apply 已不校验。`requester`/`session_id`/`conversation_turn`
  由平台注入，`conversation_turn` 随写前快照写入 manifest，供 `rollback_turn` 按消息轮回滚。
- `os_recycle_bin`：op=`delete`（移入回收站，不物理删除）/ `list` / `restore` / `purge`。
  删除天然免确认（可恢复）。
- `os_snapshot`：op=`rollback_file` / `rollback_turn` / `list_snapshots`，管理写前快照并回滚。
- `os_workspace_scope`（2026-10-04 新增）：申请把某个目录加入当前会话的工作区授权
  （用户确认弹窗显示目录与原因；高风险、每次必确认）。批准后该目录在会话内获得与
  安全根一致的治理能力；触发时机为本机工具返回 `needs_scope_grant`。授权记录落
  `session_workspace_scope` 表，worker 侧只接受真实存在的目录（自动过滤幽灵条目）。
- `os_terminal`（2026-10-03 新增，2026-10-04 重定位）：**本机任务的主力执行手段**
  （不是可选补充）——查看目录与文件、Git 操作、安装依赖、构建编译、运行测试与脚本、
  查看系统与进程信息、批量处理等，由 Agent 自主判断并主动用真实命令完成，而非逐个手工操作。
  `shell=gitbash`（默认，Unix 语法；需本机安装 Git for Windows，`GIT_BASH_PATH` 可显式指定）
  或 `shell=cmd`（Windows 原生命令）；`/health` 的 `terminal_shells` 报告两者可用性；
  非 Windows 平台两者统一映射到 `sh -c`。`working_dir` 限安全根内、`timeout_seconds`
  默认 60／上限 300。**执行前自动对工作目录做增量写前快照**（见安全模型第 9 条），
  返回结果含 `snapshot`（快照报告）与 `changes`（本次改动文件清单）；命令改坏文件时
  用 `os_snapshot` 的 `rollback_file` / `rollback_turn` 回滚。
  **工具分工（写进工具描述与系统提示词规则 10/11/12）**：执行命令 → `os_terminal`；
  改写文件内容 → `os_file_task`（写前快照、可回滚，避免终端改写丢失快照兜底）；
  删除 → `os_recycle_bin`。删除类命令被硬阻断（见安全模型第 8 条），返回结构化
  `{ok:false, blocked:true, reason}` 引导改用删除工具。
  **自主可用性链路**：主链路的工具经 `assistant_agent_service` 预挂载（模型直接可见可调用）；
  multi_agent 子任务自检索走 `ToolSelectorService` 关键词快通道——`os_terminal.yaml` 的
  `description`/`task_keywords` 已覆盖「本地开发 / 项目 / 构建 / 测试 / 依赖安装 / git /
  脚本 / 系统信息 / 批量处理」等高频作业词，确保快通道按任务描述命中该工具。
  与其余 host_os 工具一致：默认 medium 风险、免确认，管理员可在 `/admin` 工具治理中
  上调风险等级或开启确认。
  **部署提示**：终端能力在 worker 侧（`os_automation_worker.py`），桌面端需更新到
  包含该版本的安装包（`yujianwo-worker.exe` 重新打包）后才可用；未更新时工具调用
  返回 404 `not_found`，`/health` 不含 `terminal_shells`。

- 2026-09-24 契约扩展（observe-act 回路）：`computer_action` 动作集声明扩至 15
  （前台 7 + cua 8：`capture/list_apps/list_windows/launch_app/double_click/right_click/drag/set_value`），
  支持 `pid/window_id/element_index/element_token` 元素寻址与 `capture` 元素树观察；
  `assistant_agent_markdown_preset` 新增规则 15/16（capture 先行 → 元素寻址 → 读
  `verified/effect/escalation` 回执 → 仅结构化拒绝才升级前台；视觉分析 `vision_analyze`
  仅作辅助）。截图仅 `screenshot` 动作 + `return_base64=true` 时经 FileCenterService 落存储
  并以 `![screenshot](url)` 内联（`image_result_tool_names` 已含 `computer_action`，
  base64 不进工具结果）。

## 验证

单元测试：

```bash
python -m pytest test/scripts/test_os_automation_worker.py \
  test/scripts/test_os_terminal_worker.py \
  test/internal/core/tools/test_os_file_task_tool.py \
  test/internal/core/tools/test_os_snapshot_tool.py \
  test/internal/core/tools/test_os_recycle_bin_tool.py \
  test/internal/core/tools/test_os_terminal_tool.py \
  test/internal/core/agent/test_tool_confirmation_integration.py \
  test/internal/core/agent/test_function_call_and_react_agent.py -q --no-cov
```

覆盖：preview 只读不落盘、apply 直接执行且写前自动快照、路径越界拒绝、回收站删除可恢复、
单文件/按轮批量回滚、GC 清理、os_file_task 免确认（不再弹确认卡）；终端侧覆盖
cmd/gitbash 真实执行、删除命令正例（cmd/PowerShell/GitBash/嵌套内联/脚本/管道/base64）
命中与反例（`echo "rm -rf"`、`grep -r 'rm -rf'`、`python -c "print('rm -rf')"`）不误伤、
工作目录越界回退、超时杀进程树、子进程 env 剥离、输出截断；写前快照侧覆盖
改坏→`rollback_file`/`rollback_turn` 恢复、增量去重、排除可再生目录、超限降级、
快照失败 fail-closed 拒绝执行、被阻断命令不产生快照、cmd/gitbash 含空格引号路径。

真机验证（Windows，worker 直连）：

```powershell
$env:OS_AUTOMATION_TOKEN="<token>"; $env:OS_AUTOMATION_SAFE_ROOT="D:\scratch"
python api/scripts/os_automation_worker.py --port 18999
# /health → terminal_shells={"cmd":true,"gitbash":true}
# POST /exec {"command":"echo hi","shell":"cmd"}            → ok, stdout="hi"
# POST /exec {"command":"rm -f x","shell":"gitbash"}        → blocked=true，x 未被删除
```
