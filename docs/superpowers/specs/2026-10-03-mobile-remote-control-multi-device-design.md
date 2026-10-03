# 手机端遥控与多设备协作设计（spec）

> 状态：**设计稿，未实现**（本文件全部内容为设计，不含已落地能力；落地状态见 §9）
> 定位：子项目 B「手机 → 电脑远程控制通道」+ 多设备派发与协作 + 审批挂起模型 + 系统级推送，四项一体。
> 相关：[modules/09-desktop-client.md](../modules/09-desktop-client.md)（设备宿主壳）、[modules/08-os-automation.md](../modules/08-os-automation.md)（本地 worker）、[proactive-agent-ecosystem.md](../proactive-agent-ecosystem.md)（三端分工与缺口 #2）
> 更新日期：2026-10-03

## 1. 现状（实测）

| 件 | 现状 | 证据 |
|---|---|---|
| 设备注册表 | `desktop_device`（device_id / account_id / bridge_origin / bridge_token_encrypted / is_default / status / last_seen_at），注册即 UPSERT，API：`POST /desktop/devices/register`、`GET /desktop/devices`、`revoke` | `api/internal/model/desktop_device.py`、`api/internal/service/desktop_device_service.py`、`api/app/http/desktop_routes.py` |
| 设备在线态 | 客户端 60s 心跳复用注册接口；服务端 `DEVICE_ONLINE_TTL_SECONDS=180` 租约，`_effective_status` 读时判离线（不写库） | `desktop/main.js`、`desktop_device_service.py` |
| 桥解析 | `resolve_desktop_bridge(account_id, purpose)` **只取「默认 + 最近在线」一台**，工具/任务**无法指定 device_id** | `api/internal/service/desktop_bridge_resolver.py` |
| 本地执行面 | 桌面端托管 workers：os(8765) / browser(8766) / computer(8767) / render(8768) / wake；统一桥 `127.0.0.1:9876` | `desktop/main.js`、`desktop/bridge.js`、`api/scripts/worker_super.py` |
| 执行位置先例 | 仅 `render_video` 有显式三级路由：本机 bridge 优先 → 云端 Celery（`cloud-render` profile **默认关闭**）→ 报错 | `docs/prd/execution-roadmap.md` KB-P3.8、`deployment-single-node.md` |
| 云端下发能力 | 服务端**主动 HTTP 打设备 bridge**（依赖 `host.docker.internal`，仅同机 Docker 可达）；**设备侧无到云端的常驻连接**（主进程只有 HTTP；renderer 的 socket.io 是 UI 通知，不可混用为指令通道） | `desktop/main.js`、`docs/prd/proactive-agent-ecosystem.md` §4.5 注 |
| 推送 | 账号级 Socket.IO（`emit_to_account`，房间按账号，**不能按设备定向**）+ SSE；桌面端有原生通知；**移动端无任何推送** | `api/internal/extension/socketio_extension.py`、`websocket_handlers.py`、`ui/src/hooks/use-notification-websocket.ts` |
| 定时任务 | `ScheduleTask` / `ScheduleTaskRun`（cron/once/next_run_at），beat 每分钟 `run_scheduled_tasks`，**全部云端 Celery 执行，无 device 字段** | `api/internal/model/schedule_task.py`、`api/internal/service/schedule_task_service.py`、`api/internal/task/schedule_tasks.py` |
| 审批确认 | 高风险工具在 turn 内**同步阻塞等待**（`_wait_for_confirmation`），等待窗口内可注入纠正（`midturn_redirect`，Redis TTL 1200s/600s），超时 → 工具标记 cancelled → Agent 继续 | `api/internal/core/agent/agents/function_call_agent.py`、`api/internal/core/agent/adapters/hermes/midturn_redirect.py`、`api/internal/model/tool_confirmation.py` |
| 消息准入 | **无通用用户消息排队机制**（`AgentQueueManager` 是 SSE 事件发布队列，不是用户消息队列；中途注入仅限确认等待窗口） | `api/internal/core/agent/agents/agent_queue_manager.py` |
| 手机壳 | Capacitor 6 壳就绪（`webDir=../ui/dist`），CI 可出 Android 包；无独立移动端 PRD | `mobile/`、`.github/workflows/mobile-build.yml` |

## 2. 目标 / 非目标

**目标（v1）**
1. 手机登录即自动发现**同账号在线设备**，设备列表为一等界面；选择设备后即可在该设备上发起任务、看进度、收结果、做审批。
2. 打通「手机 → 云端 → 设备」的常驻下行通道（子项目 B），云端 Agent 下发、设备本地执行。
3. 审批改为**挂起-复活模型**：弹窗后 Agent 断活（释放执行资源）、用户确认后从检查点复活，上下文与任务进度无损。
4. **系统级推送**（APNs / 国内厂商通道）为硬性要求，前台在线只是补充。
5. 消息准入三途径：**新会话 / 排队待发 / 中途纠偏**（+自动新会话），用户可选。

**非目标（明确不做）**
- ❌ 扫码配对（账号中心制下无必要：登录 + 自动发现已覆盖；扫码只在「免登录」口径下有价值，与我们的账号体系冲突）。
- ❌ 「用客厅那台」式自然语言指定设备（伪需求：手机端无 Agent 决策能力，设备必须由用户显式选择）。
- ❌ 离线模式 / B 端二次部署 / 用户侧配模型（模型只能经 admin 供应商接入，没网即不可用）。
- ❌ 设备离线任务队列（离线直接报错，不堆积过时任务）。
- ❌ 设备本地 cron（调度唯一在云端，避免第二份事实源）。
- ❌ 设备直连 P2P（数据一律经云端中转）。

## 3. 复用与新建判定（按 AGENTS「轮胎 vs 补丁」口径）

- **复用（既有轮胎）**：`desktop_device` 注册表与心跳/租约/吊销链路；Socket.IO + RedisManager 跨进程广播；Celery beat 扫描范式（`run_scheduled_tasks`）；`tool_confirmation` 表与确认事件；`midturn_redirect` 的纠正注入思路；渲染三级路由（执行层本机优先）作为推广模板；Capacitor 双壳。
- **新建（本 spec 范围）**：① 设备网关（设备侧常驻连接 + 云端下行/上行通道）；② 设备级凭证（`device_token`，账号签发、可吊销）；③ `execution_target` 执行位置路由；④ 审批挂起状态机（turn 可挂起/复活）；⑤ 系统级推送通道；⑥ 手机端精简遥控面；⑦ 用户消息排队/纠偏。

## 4. 设计

### 4.1 总体链路

```text
手机 App / Web ──(账号 API + 推送)──▶ 云端（账号中心：任务 / 会话 / 文件 / 授权 / 审计）
                                        │
                               设备网关（Socket.IO 房间 device:<id>，复用 RedisManager）
                                        │ 设备主动外连 + device_token
                               桌面客户端（执行宿主：workers / bridge / 心跳）
```

纪律：**手机不直连设备**，一律「手机→云→设备」；服务端现有 socket.io 是「服务端→浏览器推送」，设备通道用**新命名空间**（如 `/device`），两者不混用。

### 4.2 设备自动发现与设备列表（无扫码）

- 桌面端保持「登录即注册 + 60s 心跳」（已实现），并新增上报 `capabilities`（os / browser / computer / render / wake 的可用性 + 版本）。
- 手机端登录后调 `GET /desktop/devices` 拉取同账号设备列表（在线态由服务端按租约读时计算），呈现为手机端首页/入口列表。
- 设备选择是**显式用户动作**：点进设备 = 进入该设备的会话上下文（此后该会话产生的任务默认在该设备执行）；不做隐式设备决策，也不做自然语言指定。
- 设备重命名、解绑（`revoke`）、默认设备设置沿用现有接口，补 UI。

### 4.3 设备网关（子项目 B 核心）

- **连接**：桌面主进程（Node）建立到云端的常驻 Socket.IO 连接，命名空间 `/device`，鉴权用 `device_token`；上线后加入房间 `device:<device_id>`，与心跳租约相互独立（WS 在线 = 可下发；心跳 = 设备存活语义，两者都保留）。
- **下行指令**（云 → 设备）：
  | 消息 | 载荷要点 |
  |---|---|
  | `task.dispatch` | task_id、会话/turn 上下文、执行指令（工具名 + 入参，或任务声明）、幂等键 |
  | `task.cancel` | task_id（用户取消/超时取消） |
  | `approval.sync` | 仅同步状态展示（审批主体仍在用户端，不在设备端） |
  | `ping` | 保活（与心跳解耦） |
- **上行事件**（设备 → 云）：
  | 消息 | 载荷要点 |
  |---|---|
  | `task.progress` | task_id、seq、阶段/百分比/日志摘要 |
  | `task.result` | task_id、成功/失败、产物引用（不传大文件，产物走既有 `/artifact` 取回后入库） |
  | `device.capabilities` | 能力与版本（启动/变更时上报） |
  | `pong` / `device.status` | 存活与运行时状态 |
- **弱网与续传**：事件带 `seq`；断线重连后 `afterSeq` 补拉（设备侧保留短窗口重放缓冲，建议 8MB/45s，可调）；大消息只传引用不传内容。快照兜底走 REST（`GET /desktop/devices` + 任务状态查询）。
- **离线语义**：下发前校验租约（`last_seen_at` 在 TTL 内）与 WS 在线；离线**立即返回「设备离线」错误**（不排队、不延迟补发），调用方（对话/定时任务）按策略提示或改选设备。
- **与现有 HTTP bridge 的关系**：bridge 保留（本地 UI、本机调试、artifact 取回），网关是**新增的下行指令通道**；服务端工具调用方统一收敛到同一个「目标解析器」（§4.4），不出现两套派发逻辑。

### 4.4 执行位置路由（execution_target）

- 概念：任务/工具调用携带 `execution_target ∈ {device:<id>, cloud, auto}`。
  - 会话已绑定设备 → 默认 `device:<绑定设备>`；
  - 未绑定（如纯 Web 会话）→ `auto`：优先默认在线设备，无则按云端端口是否开启决定回退或报错。
- 云端执行端口**预留但默认关闭**（沿用 `cloud-render` profile 范式），仅作资源兜底，不作为主叙事。
- 存储：`ScheduleTask` 增 `execution_target`（枚举 + device_id 可空）；`ScheduleTaskRun` 记录实际执行设备与目标，供审计与排障。
- 调度：beat 仍为唯一时钟源，到点后按 `execution_target` 经设备网关下发；设备离线按 §4.3 直接失败并通知，不重试堆积（可选「顺延到下次」由用户显式配置，不做默认补发）。

### 4.5 消息准入三途径（用户可控）

当前会话正在执行时，用户新消息支持三种去向（用户可手动选择，默认「排队」）：

| 途径 | 语义 | 实现要点 |
|---|---|---|
| ① 新会话 | 另开会话窗口，互不影响 | 现有能力（新建 conversation） |
| ② 排队待发 | 当前 turn 完成后自动发送 | **新建**：会话级消息队列（DB 持久化 + turn 结束后消费），状态在 UI 可见、可撤回 |
| ③ 中途纠偏 | 立即注入当前轮，Agent 重新规划 | 现有 `midturn_redirect` 思路推广到全 turn（不只确认等待窗口）；需明确「撤销当前工具调用」的边界 |
| ④ 自动新会话 | 系统自动开新会话执行，不改动当前任务 | 发送入口给「自动新会话」选项 |

- 队列与纠偏的取舍在 UI 上明示（避免用户误以为阻塞）。
- 纠偏的安全性：仅允许注入**用户消息**（不直接改运行中工具入参）；破坏性动作仍走审批。

### 4.6 审批挂起-复活模型（替代阻塞等待）

```text
running ──触发高风险工具/需用户输入──▶ suspended（持久化检查点）
   ▲                                      │ 系统级推送（深链 → 确认卡）
   └────────── 用户确认/拒绝 ─────────────┘  （无确认则永久挂起，不自动继续）
```

- **挂起 = 释放执行资源**：turn 状态与检查点落库（对话消息、已完成的工具结果、待确认的工具调用、任务进度），不占用 worker / 流；SSE 连接可断可恢复。
- **复活 = 从检查点重建上下文继续**，任务进度不丢、上下文不断裂；拒绝则按「拒绝该工具调用」路径继续（与现有拒绝语义一致）。
- **无超时自动继续**（明确否决现行「超时=cancel 后继续」的行为）。
- **兜底**：新增 beat 定时扫描（沿用 `run_scheduled_tasks` 模式）清理**超过 N 天未处理**的挂起（默认 7 天，可配置）——动作是**取消**（状态标注「超时取消」并通知），不是继续；同时提供用户手动取消。
- **幂等**：同一确认多端重复提交只生效一次（`tool_confirmation` 状态机 + 唯一约束）。
- **推送**：确认请求必须带深链直达确认卡；推送载荷只含可公开摘要（不含敏感参数全文）。
- **与 `midturn_redirect` 收敛**：挂起期间用户发纠正消息 → 视为「拒绝当前工具 + 注入纠正」并复活继续（保留现有语义，去掉单纯靠 TTL 超时兜底的行为）。

### 4.7 系统级推送（双通道 + admin 热切换，已确认）

- **通道方案**：友盟 U-Push 与个推**双接入**，服务端做 provider 抽象（`umeng | getui`），在 admin 统一配置中**热切换**：额度互补 + 故障转移（主通道下发失败/频次触顶自动切备，策略可配 auto/manual）。见 §6.1 评估。
- **配置与治理**：推送配置走 admin 统一配置（沿用 sandbox/storage 的多后端热切换范式），凭证（AppKey/AppSecret/MasterSecret）加密存储、掩码展示；运行时经统一读取接口取激活通道，禁止业务代码硬编码。
- **客户端**：App 同时集成两家 SDK 并各自注册别名/设备标识、上报双 token（保证切换后立即可达，避免切换延迟）；厂商通道资质与聚合由两家 SDK 各自承担。
- 覆盖：iOS（APNs）+ Android 国内厂商通道（华为/荣耀/小米/OPPO/vivo/魅族，由聚合 SDK 提供）+ 海外（FCM，后续）。
- 触发场景：任务完成/失败、需要审批（深链）、设备离线导致的派发失败、挂起超时取消。
- 前台/后台一致：前台走 WS 实时更新，后台由系统推送唤起；同一事件不重复打扰（幂等 + 合并）。
- 打扰分级（静默 → 回执 → 推送 → 呼叫）为后续演进，v1 只做后两类。

### 4.8 手机端 v1 遥控面（精简面）

- 页面：**设备列表**（在线态/能力）→ 设备内**会话**（对话 + 任务卡 + 产物查看）→ **审批中心** → **通知中心**。
- 不做完整 Web 管理面移植；不做仪表盘；默认一句话下达意图。
- 复用现有 UI 组件与 `mobile/` Capacitor 壳；Web 壳同套界面（浏览器可直接用）。
- 交互锚点：审批卡一键允许/拒绝；任务卡显示「在 <设备名> 上执行 · 进度」；离线设备在列表中明确置灰并给出原因。

### 4.9 多设备与跨设备协作（v1 范围）

- v1 支持：**同账号多设备**各自独立使用（每台设备 = 一个执行上下文），不做跨设备编排。
- 键鼠/屏幕占用语义（已按代码核实，2026-10-03）：**cua-driver 后端（默认优先）为后台定向控制**（按 `pid/window_id + element_index` 走 UIA Invoke/PostMessage），**不抢焦点、不移动真实鼠标、不占用用户屏幕**（`api/scripts/computer_control_worker.py` 模块说明与 `_run_actions_cua`）；仅 pyautogui 回退路径（daemon 不可用 / 动作显式指定 `backend=pyautogui` / cua 结构化拒绝后升前台）会抢焦点、动真实光标。据此**不做设备级全局键鼠互斥**，只保留两条窄约束：
  1. **前台路径串行**：pyautogui 前台动作执行期间，同一设备仅允许一个会话处于前台路径（避免与用户本人或其他会话争抢真实光标/焦点），并在设备端 UI 明示「前台操作中」；
  2. **同目标串行**：cua 后台路径按**目标窗口（pid/window_id）粒度**串行，不同目标可并发；避免两个会话操作同一窗口时元素句柄/状态竞争。
- v2（本 spec 预留）：跨设备协作 = 编排节点级 `execution_target`，产物经云端文件中心中转（设备 A 产出 → 云端入库 → 设备 B 取用），**串行优先、云端中转、状态机可见**（pending → dispatched → running → done/failed，租约超时回收）。

### 4.10 安全与审计

- `device_token`：注册时由账号签发、独立于用户 JWT、可单独吊销（与 `revoke` 同路）；设备侧加密存储（safeStorage，与 credential.bin 同规格）。
- 授权模型：v1 仅「账号 → 自己的设备」；跨账号共享/托管不开放。
- 审计：AGENT_ACTION 事件已含「谁 / 哪台设备 / 工具入参 / 结果」，网关下发与结果回传沿用同一审计口径（补 task_id / device_id 关联）。
- 危险动作仍走审批（§4.6），审批主体是**用户端**（手机/Web/桌面），设备端不做授权决策。

### 4.11 分期

| 期 | 范围 | 依赖 |
|---|---|---|
| **P0** | 设备列表 UI（含在线态/重命名/解绑/默认设备）；`resolve_bridge` 支持显式 device_id；账号推送加 `device:<id>` 房间与任务事件；手机壳跑通（移动适配 + 精简遥控面的设备列表/会话骨架） | 无新增后端大件 |
| **P1** | 设备网关（`/device` 命名空间 + `device_token` + 下发/回传协议 + 弱网续传）；离线即报错；审批挂起状态机 + 深链 + 兜底扫描；系统级推送接入；消息准入三途径 | P0；审批改造建议独立排期 |
| **P2** | `execution_target` 落到 ScheduleTask 与调度；重型任务本机优先推广；跨设备协作 v1（串行 + 云端中转） | P1 |

## 5. 落地步骤与验收（要点）

- P0 验收：登录手机后 3 秒内看到同账号设备列表且在线态正确；对指定设备派单成功（`host.docker.internal` 之外的部署形态需 P1 网关，P0 仅限同机/内网可达场景）。
- P1 验收：断网重连后事件不丢（`afterSeq` 补齐）；设备离线派发返回明确错误且无残留任务；审批挂起后 worker 释放（CPU/内存回落可测）、确认后从检查点继续且上下文完整；杀后台手机能收到系统推送并深链直达确认卡。
- P2 验收：定时任务按 `execution_target` 落在指定设备；离线设备到点任务直接失败并通知；跨设备串行链路产物经云端中转可取回。

## 6. 风险与未决

### 6.1 推送通道（已确认：双接入 + admin 热切换）

| 方案 | 费用（公开信息，2026-10-03 查证） | 备注 |
|---|---|---|
| 友盟 U-Push | 免费标准版 **¥0 永久**（含 8 条通道聚合：华为/荣耀/小米/OPPO/vivo/魅族/鸿蒙/APNs）；专业版按 DAU 年付，1 万 DAU 内 **¥18,000/年**起 | 我们的通知为**单推为主、量小**，免费版足矣 |
| 个推 | 免费版**推送条数不限**（共享频次：全量 20 次/天、单推 250 万次/天）；VIP/SVIP 需商务咨询 | 免费版够用；全量广播频次限制不影响本场景 |
| 极光 JPush | 免费版共享配额（离线消息 5 条/天、广播 10 次/天）；高级版需商务咨询 | 离线消息配额对「任务完成通知」偏紧 |
| 厂商直连 + APNs/FCM | 通道本身免费；成本 = 6 家 SDK 集成维护 + 各厂商开发者审核 | 资质前置：企业开发者账号、App 备案、部分厂商要软著 |

**已确认（2026-10-03）**：友盟与个推**双接入**、admin 热切换与故障转移（两家免费额度互补，零新增通道费用）；iOS 走聚合 SDK 的 APNs。厂商直连 / FCM 直连留作后续评估。

### 6.2 其他风险
- 审批挂起改造是**最大改造量**（现行 turn 内同步阻塞 → 可挂起状态机），建议单独批次、单独回归测试（含 `midturn_redirect` 语义收敛）。
- 厂商推送资质周期不可控（备案/软著/企业认证），可能成为 P1 关键路径。
- 消息排队（②）与会话级并发控制（每用户并发上限、Redis 锁）需要对齐现有执行器语义。

## 7. 已确认决策（2026-10-03）

1. 不扫码：账号中心制下做**设备自动发现**，手机登录后自动列出同账号在线设备。
2. 设备选择是显式用户动作（进入设备后再操作）；不向 Agent 委派设备决策，不做自然语言指定设备。
3. 执行层本地化、云端下发任务；云端执行端口预留、默认关闭省资源。
4. 不做离线模式 / B 端二次部署 / 用户侧配模型（没网=不可用）。
5. 推送必须系统级（前台推送无意义）。
6. 离线派发直接报「设备离线」，不排队。
7. 云端为单一事实源。
8. 审批采用挂起-复活：确认期间 Agent 断活，确认后复活，不超时自动继续；兜底用定时扫描自动取消。
9. 消息准入三途径（新会话 / 排队 / 中途纠偏）+ 自动新会话，用户可选。
10. 手机端 v1 做精简遥控面。
11. 推送通道：友盟与个推**双接入**，admin 热切换 + 故障转移（额度互补，零新增费用）。
12. 键鼠互斥：cua 后台路径不占用用户键鼠/屏幕（已核实），**不做设备级全局互斥**；仅保留「前台 pyautogui 路径串行」与「cua 同目标窗口串行」两条窄约束（§4.9）。

## 8. 未实现范围声明

本 spec 描述的全部能力（设备网关、device_token、execution_target、审批挂起模型、系统推送、手机遥控面、消息准入三途径）**均为愿景设计，未实现**。实现按 §4.11 分期推进，每期完成时按 AGENTS「架构文档同步」更新本文档与相关模块文档，并回归 `docs/README.md` 导航。

## 9. 落地状态（2026-10-03）

- 设计稿完成；P0 尚未开始。
- 2026-10-03 更新：键鼠互斥按代码核实收敛为两条窄约束（§4.9）；推送确定为双通道 + admin 热切换（§4.7 / §6.1）；两项决策已记入 §7（#11 / #12）。
