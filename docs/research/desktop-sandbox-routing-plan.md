# 多租户 Web 场景下的"真实桌面 / 云沙箱"双层执行路由方案

> 更新日期：2026-09-08（批次 5：§4.1.3 权限放开边界同步——写/删已放开靠快照回收站兜底，敏感读取由 worker 读黑名单拒绝）
> 定位：研究方案（设计稿），主体未实现（多通道路由、桌面桥远程化、cua-driver 后端均为愿景设计）；其中 §4.1.3 删除出口统一已随自研链路落地。背景调研见 `docs/research/hermes-v0.20-capability-deep-dive.md`、
> `docs/research/hermes-v0.20-saas-evaluation.md`、`docs/prd/modules/08-os-automation.md`。

## 0. 结论速览

- 目标：多租户 Web 平台上，让 Agent 既能在**用户自己的真实电脑**上干活（桌面控制），也能在**云端隔离沙箱**里干活（代码/文件/浏览器），按任务风险与用户选择自动路由。
- 核心机制：在 Agent 高风险工具确认链路前新增**环境路由决策**，按「任务类型 + 用户意图 + 设备状态」把动作送到三条通道之一：
  - **通道 A 用户真实桌面**：桌面桥（Electron 壳 + 本地 workers，升级 cua-driver 后端）
  - **通道 B 云沙箱**：E2B/CFC 容器沙箱（已有 `execute_code` 底座），未来可扩展 GUI 容器
  - **通道 C 云端浏览器**：现有 Playwright browser worker / 云浏览器
- 复用现状：风险分级（`ToolPolicyEntity`）、审批链路（`tool_confirmation`）、E2B 沙箱（`BaiduCfcSandboxBackend`）、`DESKTOP_BRIDGE` 统一通道均已存在，本方案不推倒重来，只补"路由决策 + 远程通道 + cua-driver 后端"三块。

---

## 1. 背景与问题

### 1.1 现状

| 能力 | 现状 | 落点 |
| --- | --- | --- |
| 宿主机系统自动化 | `os_file_task` / `os_recycle_bin` / `os_snapshot`，走宿主机 OS worker(8765)，纯 Python（无外部 CLI） | `api/internal/core/tools/builtin_tools/providers/codex_os/*` |
| 浏览器自动化 | `browser_action`，Playwright worker(8766) | `providers/browser_automation/browser_action.py` |
| 计算机控制 | `computer_action`，pyautogui worker(8767)，默认关 | `providers/computer_control/computer_action.py` |
| 代码执行沙箱 | `execute_code`，E2B/百度 CFC 隔离后端，默认关 | `providers/code_execution_tool/execute_code.py`、`backends/baidu_cfc_sandbox_backend.py` |
| 桌面壳（本地能力宿主） | Electron 壳托管 4 个本地 worker + 统一桥(9876) | `desktop/` |
| 风险分级 + 审批 | `ToolPolicyEntity` 分级，`function_call_agent` 拦截，`tool_confirmation` 确认 | `api/internal/core/agent/*` |

### 1.2 缺口

1. **没有"执行环境"概念**：高风险工具只能"确认执行"，不能选择"在哪执行"（用户真实桌面 vs 云端沙箱）。
2. **桌面壳是本机/单机模式**：bridge 只监听 `127.0.0.1`，靠 `host.docker.internal` 访问，无云端远程通道，多租户 Web 用户无法让自己的电脑被 Agent 控制。
3. **computer worker 是 pyautogui**：前台全局模拟，抢鼠标键盘焦点；无 SOM 视觉、无结构化验证。
4. **沙箱无 GUI**：`execute_code` 只能跑命令行，不能跑带界面的任务。

### 1.3 设计目标

- 用户可显式选择："在云端沙箱里跑"（安全优先）或"操作我自己的电脑"（真实优先）。
- 风险兜底：高危险动作默认倾向云沙箱；真实桌面路径必须有设备绑定 + 审批 + 审计三重保障。
- 增量演进：先补云沙箱 + 路由决策，再桌面桥远程化，最后 cua-driver 后端。

---

## 2. 总体架构

```text
用户（多租户 Web，任何浏览器）
  │
  ▼
平台 API（llmops-api 容器）
  │  Agent 主循环（FunctionCallAgent）
  │    └─ 工具调用前：风险分级拦截（已有）
  │         └─ 新增：执行环境路由（ExecutionEnvironmentRouter）
  │              ├─ 通道 A：真实桌面 ── DESKTOP_BRIDGE 长连接 ──► 用户电脑桌面壳
  │              │                                             ├─ os worker(8765, os_file_task/os_recycle_bin/os_snapshot)
  │              │                                             ├─ computer worker(8767, cua-driver 后端)
  │              │                                             └─ browser worker(8766, Playwright)
  │              ├─ 通道 B：云沙箱 ── E2B/CFC 沙箱 ──► 隔离容器（代码/文件/未来 GUI）
  │              └─ 通道 C：云端浏览器 ── Playwright worker ──► 云浏览器（现有）
```

### 2.1 三条通道的定位

| 通道 | 能力 | 隔离程度 | 成本 | 适用 |
| --- | --- | --- | --- | --- |
| A 真实桌面 | 控制用户自己的电脑（文件/桌面应用/回收站） | 低（输入隔离，无环境隔离） | 低（用户自有机器） | 用户明确要"帮我操作我电脑上的 X" |
| B 云沙箱 | 云端隔离环境跑代码/文件/未来 GUI 应用 | 高（容器/VM 隔离） | 中（按用量） | 默认安全兜底；"跑个脚本/整理数据" |
| C 云端浏览器 | 云端浏览器自动化 | 高 | 低 | 网页操作类任务 |

---

## 3. 核心机制：执行环境路由

### 3.1 路由决策点

在 `function_call_agent.py` 的高风险拦截处（`_tools_node` 工具调用前）之前插入 `ExecutionEnvironmentRouter`。决策输入：

1. **工具分类**（静态）：`ToolPolicyEntity` 已有 `high_risk/dangerous` 分级 → 扩展出 `environment_hint`：
   - `os_file_task` / `os_recycle_bin` / `os_snapshot` / `computer_action` → `local_desktop`
   - `execute_code` → `cloud_sandbox`
   - `browser_action` → `cloud_browser`（可被用户改为 local_desktop）
2. **用户意图**（动态）：会话/请求级参数 `execution_target`：
   - 用户在发起任务时可选"在云端沙箱执行 / 在我的电脑上执行"（默认：有绑定设备则提供选择，无设备则只能沙箱）。
3. **设备状态**（动态）：该用户是否有已配对在线设备（见 §5）。

### 3.2 路由规则（决策表）

| 工具分类 | 用户意图 | 设备在线 | 路由结果 |
| --- | --- | --- | --- |
| local_desktop 类 | 未指定 | — | 引导用户选择；默认 B 云沙箱（如该工具支持） |
| local_desktop 类 | 我的电脑 | 是 | A 真实桌面（需审批 + 审计） |
| local_desktop 类 | 我的电脑 | 否 | 拒绝并提示"无在线设备，请启动桌面端或改用云沙箱" |
| local_desktop 类 | 云沙箱 | — | 若工具存在沙箱实现 → B；否则拒绝并提示 |
| cloud_sandbox 类 | 任意 | — | B 云沙箱（默认） |
| cloud_browser 类 | 任意 | — | C 云端浏览器（默认）；用户选我的电脑且有设备 → A |

> 默认倾向安全侧：无法确定时走云沙箱或拒绝，不让动作无声落到真实桌面。

### 3.3 环境描述注入

路由完成后，向 Agent 上下文注入"当前执行环境说明"（system prompt 片段或工具结果前缀），例如：
"本次任务将在【云端沙箱】执行，文件系统为隔离环境，任务完成产物可下载；如需操作你的真实电脑，请明确说明。"

---

## 4. 通道设计

### 4.1 通道 A：真实桌面（桌面桥 + cua-driver 后端）

#### 4.1.1 桌面壳远程化（阶段 2）

先区分两个场景：

- **本地场景**（用户在这台电脑上用客户端）：桌面客户端封装完整 WebUI，用户登录后直接用，本地 worker 走回环地址 + 随机 token，**不需要任何配对**。
- **远程场景**（手机浏览器 / 其他设备给这台电脑发任务）：需要"设备标识 + 长连接"。配对采用**登录即设备**，不用配对码。

远程模式补四件：

1. **登录即设备注册**：
   - 桌面壳登录账号即自动注册为该账号的一台设备（`device_id` = 客户端实例 + 设备指纹），云端设备列表自动出现。
   - 配对码/二维码降级为可选：仅在多设备命名区分时才需要。
   - 服务端建 `device_registry` 表：`device_id / user_id / tenant_id / name / platform / last_seen / status(online/offline/revoked)`。
2. **云端长连接**：
   - 桌面壳主动向云端 `wss://<api>/ws/device/<device_id>` 建立 WebSocket（解决 NAT/动态 IP），云端把 Agent 动作经连接下发。
   - 心跳 + 断线重连 + 幂等：动作带 `action_id`，桥执行后回执 `action_id + result`，云端去重。
3. **动作转发**：
   - 云端 → WS → 桌面壳主进程 → 本地桥(9876) → 对应 worker（os/browser/computer）。
   - 现有 `DESKTOP_BRIDGE_URL/TOKEN` 机制保留，新增 WS 通道与之并存（本地部署仍走旧通道）。
4. **产物回传**（远程闭环）：
   - 电脑端执行结果（截图、生成/修改的文件、回收站清单）经 WS 或存储服务回传云端，手机浏览器 / Web 可查看下载。
   - 远程任务**默认需电脑端确认**（防设备被盗后被远程操控）；用户可在客户端主动开启"远程免确认"开关（与合规确认）。

#### 4.1.2 cua-driver 后端（阶段 2 或 3）

computer worker 增加 `cua-driver` 后端（`cua-driver mcp` stdio 客户端），pyautogui 保留为 fallback：

| 能力 | pyautogui（现状） | cua-driver（新增） |
| --- | --- | --- |
| 输入方式 | 前台全局模拟（抢焦点） | 后台 pid 定向输入（不抢焦点） |
| 视觉 | 裸截图 | SOM 编号 overlay + AX 树，按 element 索引点击 |
| 验证 | 无 | structured verdict（verified/effect/escalation） |
| 跨平台 | Windows 为主 | macOS/Windows/Linux |

工具 schema（`computer_action`）扩展：
- `action=capture, mode=som|vision|ax`；`element=N` 索引点击；`delivery_mode=background|foreground`。
- 审批：`capture` 免费；其余动作沿用高风险确认链路。

安装：桌面壳安装包捆绑/首启拉取 cua-driver 二进制（MIT，`cua-driver.exe` 免 admin）。Agent 不负责安装。

#### 4.1.3 删除出口统一（已落地，现状描述）

核心需求：Agent 删的文件**必须**进回收站、**改**必须可回滚。终端删除（`del` / `Remove-Item` / `rm`）是物理删除、无法找回，因此**Agent 的本机删除一律走回收站通道**。该约束现由自研链路天然达成，无需额外删除护栏：

1. 通道 A 真实桌面的本地文件执行引擎为**纯 Python 自研链路**（不再有 `run_os_task`/Codex CLI 终端执行面，因此不存在"Agent 在终端里执行删除命令"的通道）：
   - `os_file_task`（read/search/V4A patch，默认 apply 直接执行、写前自动快照）；
   - `os_recycle_bin`（delete 移入回收站 / list / restore / purge）；
   - `os_snapshot`（rollback_file / rollback_turn / list_snapshots）。
   删除类命令检测（delete_guard 等）已随 run_os_task 链路一并删除，不再需要明文命令拦截。
2. 删除文件的唯一出口是 `os_recycle_bin`（worker `/recycle` → `.yujianwo_recycle`，可恢复）；修改的唯一出口是 `os_file_task`（V4A apply 写前快照，`.yujianwo_snapshots`，可回滚）。
3. 兜底闭环：误删 → `os_recycle_bin list` + `restore`；改错 → `os_snapshot rollback_file` / `rollback_turn`。快照与回收站均存宿主机本机，默认留存 7 天。

> 权限放开边界（现状，2026-09-08）：回收站只兜底"删错了"，兜不了"读走了"。写/删动作已放开
> （靠快照+回收站自愈闭环兜底），但**读取面由 worker 敏感路径黑名单兜底**：`os_file_task`
> read/search 命中敏感路径（`~/.ssh` 私钥、`.env` 密钥文件、浏览器凭据目录
> `User Data`/`Login Data`/`logins.json`、`.aws`/`.kube`/`.gnupg` 等凭据目录、`.yujianwo_recycle`
> `.yujianwo_snapshots` 自管目录）直接拒绝，不返回任何内容；search 用 rg 排除 glob 跳过敏感
> 目录/文件。系统级变更类动作（注册表/装软件/锁屏等，cua-driver/computer 通道）仍保留审批。

### 4.2 通道 B：云沙箱（阶段 1）

基于已有 `BaiduCfcSandboxBackend`（E2B 协议）：

1. **补 GUI 沙箱**（可选）：E2B/CFC 容器加 `xvfb + 桌面 + 截图`，支持"跑 GUI 应用 → 截图 → 返回"；对应新增 `sandbox_desktop_action` 工具（容器内版 computer_action）。
2. **产物回传**：沙箱运行产物（文件/截图）经存储服务回传，用户可下载。
3. **多租户隔离**：沙箱按 `tenant_id` 命名空间隔离，资源配额与计费沿用现有成本体系。

### 4.3 通道 C：云端浏览器（现状保留）

`browser_action` + Playwright 维持现状，仅纳入路由（默认 cloud_browser）。

---

## 5. 多租户与设备管理

- 设备维度：`device_registry` 表（见 §4.1.1），用户可见自己的设备列表；管理员可跨租户查看/吊销。
- 授权粒度：设备绑定账号；跨设备动作一律经过审批；高风险动作（删除/写入系统目录）额外要求设备在线 + 最近活跃。
- 审计：动作记录带 `device_id / action_id / result`，进现有审计体系。
- 吊销：吊销后长连接立即失效，bridge 拒绝新动作。

---

## 6. 安全模型

| 层 | 措施 |
| --- | --- |
| 传输 | WS/TLS + device_token 鉴权 + 动作幂等 ID |
| 设备 | 登录即注册（本地场景免配对）、在线心跳、可吊销、远程任务默认电脑端确认 |
| 动作 | 现有 `ToolPolicyEntity` 分级 + `tool_confirmation` 审批；删除/修改类动作由删除出口统一（§4.1.3，自研链路天然回收站 + 快照回滚）兜底，审批已放开；敏感读取由 worker 读黑名单拒绝（`os_file_task` read/search 命中 `~/.ssh`/`.env`/浏览器凭据等直接拒），系统级变更（cua-driver 中除 `capture` 外的动作、注册表/装软件/锁屏类）保留审批；硬屏蔽危险组合键（如 `win+l` 锁屏） |
| 环境 | 默认倾向云沙箱；真实桌面需用户显式意图 |
| 审计 | 全动作审计（谁/哪台设备/什么操作/结果） |

---

## 7. 分阶段实施路线

| 阶段 | 内容 | 依赖 | 交付物 |
| --- | --- | --- | --- |
| **1 云沙箱 + 路由决策**（删除出口已落地，见 §4.1.3） | 路由决策器、沙箱产物回传、（可选）GUI 沙箱 | 现有 E2B/CFC | `ExecutionEnvironmentRouter`、`execution_target` 参数、沙箱 GUI 工具 |
| **2 桌面桥远程化** | 登录即设备注册、WS 长连接、产物回传、远程确认、设备管理页、审计扩展 | 阶段 1 的路由 | `device_registry`、`/ws/device/<id>`、桌面壳远程模式、Web 设备管理页 |
| **3 cua-driver 后端** | computer worker 换/增 cua-driver 后端、schema 扩展（SOM/element/delivery_mode） | 阶段 2 | cua-driver 后端、schema 升级、结构化验证 |

> 阶段 1 与 2 可并行；阶段 3 依赖 2（真实桌面通道就绪）。

---

## 8. 开放问题

1. **GUI 云沙箱的价值排序**：是否需要（成本 vs 收益）？先确认是否有"跑 GUI 应用"的真实场景。
2. **cua-driver Windows BETA 稳定性**：需在目标应用上 PoC（SOM 截图 + element 点击 + 后台输入）。
3. **设备长连接的规模化**：单用户多设备、并发任务、断线续跑策略。
4. **路由默认值的产品语义**：无设备用户默认体验 = 纯云沙箱，是否需要更明显的引导。

---

## 9. 相关文档

- 宿主机自动化：`docs/prd/modules/08-os-automation.md`
- Hermes 深度调研：`docs/research/hermes-v0.20-capability-deep-dive.md`
- Hermes SaaS 评估：`docs/research/hermes-v0.20-saas-evaluation.md`
- 桌面壳现状：`desktop/README.md`
