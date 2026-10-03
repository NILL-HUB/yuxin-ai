# 手机端遥控 P0（设备列表与设备绑定）Implementation Plan

> **For agentic workers:** 本计划按任务逐个执行，每个任务独立提交、独立验收；完成后按 AGENTS「架构文档同步」更新文档。设计依据：[手机端遥控与多设备协作设计（spec）](../specs/2026-10-03-mobile-remote-control-multi-device-design.md)。

**Goal:** 打通 P0 最小闭环——手机/Web 登录后自动看到同账号设备列表，**显式选择设备**后进入会话，会话内的本机工具在**指定设备**上执行；配套设备管理（重命名/设默认/解绑）与设备定向的在线推送房间。

**Architecture:** 不新建通道、不碰设备网关（P1）。复用既有链路：`desktop_device` 注册表 + 心跳租约 → `resolve_desktop_bridge` 按账号解析 bridge → 本机 workers。P0 只做三件增量：① 设备管理接口补全；② **会话级设备绑定**（conversation 字段 + 请求参数 + 工具透传 + resolver 显式 device_id）；③ socket.io 设备房间。前端补设备列表页与会话入口，移动端把 Capacitor 壳跑通并做遥控面骨架。

**Tech Stack:** Python 3.12 / Quart / SQLAlchemy / Alembic / python-socketio；Vue 3 + Vitest；Capacitor 6。

**依据与前置（已核实，写代码前先读）：**
- `api/internal/service/desktop_bridge_resolver.py`：`resolve_desktop_bridge(account_id, *, purpose)`，当前只按「默认 + 最近在线」解析；`DESKTOP_UNAVAILABLE_MESSAGE` 是 4 处消费方共用的**统一文案单一事实源**（os_file_task / os_recycle_bin / os_snapshot / recycle_bin_handlers）。
- `api/app/http/desktop_routes.py`：现有端点仅 `register` / `list` / `revoke`（L76/L106/L121）。
- `api/internal/service/assistant_agent_service.py`：运行时工具注入区（`requester=str(account_id)`，含 fc / cc / browser 与 os 三件套），是 device_id 透传的**唯一注入点**。
- `api/internal/extension/websocket_handlers.py`：房间订阅范式 `handle_subscribe_* → sio.enter_room/leave_room`（L101-208）；发送入口 `api/internal/lib/websocket_manager.py:111 emit_to_account`。
- `api/internal/model/conversation.py`：会话表**没有**设备字段（L37-57）。
- UI：`ui/src/views/space/` 下无 devices 目录；路由先例见 `ui/src/router/index.ts`（schedules / recycle-bin）；i18n 已有 `zh-CN/desktopDevice.ts`（桌面面板用）。
- `mobile/`：Capacitor 6 壳（`webDir=../ui/dist`），无 android/ios 原生工程（CI 生成）。

**明确不做（YAGNI，留给 P1/P2）：**
- 设备网关（`/device` 命名空间、device_token、下行指令）——P1；
- 系统级推送（友盟/个推接入）——P1；
- 审批挂起-复活、消息准入三途径——P1（P0 里审批仍走现有 Web 确认卡）；
- 跨设备编排——P2；
- 扫码（已确认不做）。

---

## 已核实的事实（避免重复踩坑）

1. `resolve_desktop_bridge` 目前**没有** device_id 参数，工具层不读表、不读 env，只依赖本函数（注释明确要求保持这一点）。
2. 工具实参注入在 `assistant_agent_service.py` 的构建期（`requester=str(account_id)` 同一点），新增 `device_id` 必须**只在这一处**注入，禁止工具内部自行读会话/读 DB。
3. 设备"在线"是**读时计算**（`_effective_status`：`last_seen_at` 超 `DEVICE_ONLINE_TTL_SECONDS=180s` 即离线，不写库）。指定设备的可用性校验必须复用同一判据，不得另写一套。
4. 现有 socket.io 房间均按 **account_id**（`emit_to_account`）；设备房间需独立键并**校验设备归属**，防止越权订阅。
5. conversation 表无 JSON 扩展字段可直接用；设备绑定用**新增 nullable 列**（可索引、可查询），不加 FK 约束（设备可被 revoke，避免删除设备时的外键问题），读时校验归属。
6. P0 的"指定设备执行"端到端只在 **bridge 可达场景**成立（同机 Docker `host.docker.internal` / 内网）；公网形态依赖 P1 设备网关，本计划不以公网为验收条件。

---

## 文件结构

```text
api/
├─ internal/service/desktop_device_service.py        # + update_device（重命名/设默认互斥）
├─ internal/service/desktop_bridge_resolver.py       # + device_id 显式解析与离线文案
├─ internal/service/assistant_agent_service.py       # 工具注入点透传 device_id（唯一注入点）
├─ internal/model/conversation.py                    # + desktop_device_id（nullable）
├─ internal/migration/versions/<rev>_add_conversation_desktop_device_id.py   # 新增
├─ app/http/desktop_routes.py                        # + PATCH /desktop/devices/<device_id>
├─ app/http/<chat 路由>.py                            # chat 请求可选 device_id（创建/续聊写入会话）
├─ internal/extension/websocket_handlers.py          # + device 订阅/退订
├─ internal/lib/websocket_manager.py                 # + emit_to_device
└─ test/internal/...（见各任务）

ui/
├─ services/desktop-device.ts                        # 新增（list/update/revoke）
├─ views/space/devices/ListView.vue                  # 新增设备列表页
├─ router/index.ts                                   # + devices 路由
├─ i18n/messages/{zh-CN,en-US}/devices.ts            # 新增（zh/en 同步 + parity）
└─ （会话页）携带 device_id 的会话创建/续聊入口

mobile/                                              # Capacitor 壳跑通 + 遥控面骨架
docs/prd/modules/09-desktop-client.md                # 收尾同步
```

---

## Task 1: 设备管理接口补全（重命名 / 设默认 / 解绑）

**目标**：`GET /desktop/devices` 之外，补齐管理动作，为设备列表页提供落点。

**文件**：`api/internal/service/desktop_device_service.py`、`api/app/http/desktop_routes.py`、`api/test/internal/service/test_desktop_device_service.py`。

**步骤**：
- [ ] `DesktopDeviceService.update_device(account_id, device_id, *, name=None, is_default=None)`：
  - 归属校验：设备必须属于该账号，否则返回"设备不存在"（不泄露他人设备存在性）；
  - `is_default=True` 时，同账号其他设备 `is_default` 置 false（互斥，单事务）；
  - `name` 长度/空值校验（schema 层）。
- [ ] 路由 `PATCH /desktop/devices/<device_id>`（鉴权同 list；请求体 schema：`name?`、`is_default?`），返回更新后的设备行（沿用 list 的序列化口径）。
- [ ] 测试（TDD：先写失败用例）：
  - 重命名成功且只改自己的设备；
  - 设默认互斥（旧默认被清）；
  - 非本人设备 → 404/业务错误；
  - 解绑沿用既有 `revoke`（本任务不改语义，补一条列表回归断言）。

**验收**：更新接口可用；`GET /desktop/devices` 返回反映更新结果；旧路径（register/heartbeat/revoke）零行为变化。

---

## Task 2: 会话级设备绑定 + resolver 支持显式 device_id（P0 闭环核心）

**目标**：用户选设备 → 会话记住它 → 该会话的本机工具在指定设备执行；不指定时行为与现在**完全一致**。

**文件**：`api/internal/model/conversation.py`、新增迁移、chat 路由（创建/续聊入口）、`api/internal/service/assistant_agent_service.py`、`api/internal/service/desktop_bridge_resolver.py`、`api/internal/core/tools/builtin_tools/providers/host_os/*`（工具工厂签名）、`api/test/...`。

**步骤**：
- [ ] 模型 + 迁移：`Conversation.desktop_device_id`（UUID, nullable）。迁移 `down_revision` 指向**已被 git 跟踪**的当前单 head（写计划时以 `alembic heads` 实测为准），并确认不产生多 head。
- [ ] chat 请求可选 `device_id`：
  - 创建会话：写入 `desktop_device_id`（先校验归属+业务存在性，不在线不阻断创建——在线性只影响执行时）；
  - 续聊：请求带 `device_id` 则更新会话绑定；不带则沿用会话现值；显式传空（`null`）表示解绑回"自动解析"。
- [ ] 工具注入点透传（**唯一注入点**，`assistant_agent_service.py` 的构建区）：把会话解析出的 `device_id` 传给 fc / cc / browser / os 工具工厂（各工厂新增可选参数 `device_id: str | None = None`，贯穿到 `resolve_desktop_bridge(account_id, purpose=..., device_id=...)`）；**工具内部不得自行读会话**。
- [ ] resolver 扩展：`resolve_desktop_bridge(account_id, *, purpose="", device_id=None)`：
  - `device_id` 为空：保持现行为（默认 + 最近在线 → 静态回退）；
  - `device_id` 非空：校验归属 + 租约在线（复用 `_effective_status` 判据）→ 命中返回；归属不符 → 同"设备不存在"；离线 → 返回 None，并由调用方使用**新增统一文案** `DESKTOP_DEVICE_OFFLINE_MESSAGE`（"指定的设备当前离线……"），与 `DESKTOP_UNAVAILABLE_MESSAGE` 并列、同源维护；
  - 工具层消费方（4 处）统一改用"按返回 None 的文案选择"helper，不各写一份判断。
- [ ] 测试（TDD）：
  - resolver：指定设备命中 / 离线 / 非本人设备；不传 device_id 时与旧行为逐条等价（含静态回退分支）；
  - 工具透传：façade 单测断言 `resolve_desktop_bridge` 收到的 `device_id` 与会话绑定一致；
  - 会话绑定：创建带 device_id、续聊更新、显式 null 解绑、越权 device_id 被拒。

**验收**：指定设备的会话内触发 `os_file_task` 等工具时命中该设备 bridge（同机场景端到端）；离线设备返回明确错误；未绑定设备的旧路径行为零变化（回归全绿）。

---

## Task 3: `device:<id>` 在线推送房间与设备定向事件

**目标**：为手机端在线实时更新提供按设备定向的推送房间（系统级推送是 P1，本任务只做 WS）。

**文件**：`api/internal/extension/websocket_handlers.py`、`api/internal/lib/websocket_manager.py`、`api/test/internal/...`（socket handler 测试）。

**步骤**：
- [ ] 订阅/退订 handler：`handle_subscribe_device_notification` / `handle_unsubscribe_device_notification`，房间键 `device:<device_id>`；订阅时**校验设备归属**（非本人设备拒绝并返回错误码），沿用现有 `enter_room/leave_room` 范式与鉴权辅助（`_require_authenticated_connection`）。
- [ ] `emit_to_device(account_id, device_id, event, data)`：先校验归属（或由调用方保证）→ 只发对应房间；与 `emit_to_account` 并列。
- [ ] 接入一个真实事件源（避免"新符号无调用者"）：会话绑定设备时，现有 agent/任务通知在发送处按会话绑定设备**同时**发设备房间（无绑定时仅账号房间，行为不变）。
- [ ] 测试：越权订阅被拒；事件只到对应房间；无绑定会话的旧行为回归。

**验收**：Web/移动端订阅设备房间后可收到该设备的定向事件；未订阅/越权无泄漏。

---

## Task 4: 设备列表页与会话入口（前端）

**目标**：Web 与移动共用同一套设备列表页；点设备进入会话并携带 device_id。

**文件**：`ui/src/services/desktop-device.ts`、`ui/src/views/space/devices/ListView.vue`、`ui/src/router/index.ts`、`ui/src/i18n/messages/{zh-CN,en-US}/devices.ts`、（会话页/服务）`ui/src/services/conversation.ts`、`ui/src/views/space/...`（入口按钮）。

**步骤**：
- [ ] service：`listDevices()` / `updateDevice(deviceId, {name?, is_default?})` / `revokeDevice(deviceId)`（类型定义 + 错误归一）。
- [ ] 页面：设备卡片列表（名称、平台、在线态**读时态**、最后在线时间、默认标记）；操作：重命名、设为默认、解绑（二次确认）；离线置灰并给原因文案；空状态引导"安装并登录桌面端"。
- [ ] 路由与导航：`/space/devices`（登录态），侧边导航登记（对齐 schedules/recycle-bin 先例）。
- [ ] 会话入口：设备卡片"使用此设备"→ 进入对话（创建会话时带 `device_id`）；会话内显示当前设备标识（可切换/解绑）。
- [ ] i18n：新增 `devices.ts`（zh/en 结构镜像），跑 `npx vitest run src/i18n/__tests__/parity.spec.ts`。
- [ ] 测试：service（mock）、ListView（渲染/在线态/交互）、会话携带 device_id 的请求断言。

**验收**：Web 端完整执行"看设备 → 重命名/设默认/解绑 → 选设备进入会话"；离线设备不可选（或可选但明确提示将失败）。

---

## Task 5: 手机壳跑通 + 遥控面骨架（移动端）

**目标**：Capacitor 壳可安装运行，登录后走到设备列表与会话（P0 遥控面的最小骨架）。

**文件**：`mobile/`（`cap add android` 产物按 CI 流程生成，不入库原生工程前先与 CI 对齐）、`ui/` 移动适配（仅范围：设备列表与会话页在窄屏可用、导航可达）。

**步骤**：
- [ ] 本地跑通：`cd ui && npm run build && cd ../mobile && npm install && npm run sync`，Android debug 运行（或直接走 `.github/workflows/mobile-build.yml` 出包）。
- [ ] 移动适配（最小范围）：登录 → **设备列表** → 进入会话 → 发送消息（对话输入区在窄屏可用）；桌面专属能力（设备面板/回收站面板）在移动端隐藏或降级。
- [ ] 会话内复用现有确认卡（P0 不做挂起模型）：高风险确认在移动端可见即可用。
- [ ] 验证：真机/模拟器 + 同机设备在线（bridge 可达）完成一次"手机下指令 → 本机 worker 执行 → 结果回显"。

**验收**：手机 App 完成上述闭环；桌面端与 Web 端不受影响（构建产物互不覆盖：`dist` / `dist-desktop` 口径不变）。

---

## Task 6: 收尾（文档 / 接线自检 / graphify）

- [ ] 文档同步：`docs/prd/modules/09-desktop-client.md`（设备管理、会话绑定、设备房间）；spec §9 落地状态更新（P0 完成后标注各任务状态）；`docs/README.md` 本计划状态更新。
- [ ] 接线审查（AGENTS 强制）：逐一点名生产调用方——`update_device`、`resolve_desktop_bridge(device_id=)`、`emit_to_device`、订阅 handler、前端 service/view；排除 test 后无孤儿符号。
- [ ] 影响面自检：`resolve_desktop_bridge` 4 处消费方；conversation 增列对既有查询/序列化的影响；socket 新房间对现有连接鉴权无回归。
- [ ] `python -m graphify update .`。
- [ ] 提交序列（每任务一次，中文）：`feat(desktop): 设备重命名与默认设备接口` → `feat(desktop): 会话级设备绑定与按设备解析 bridge` → `feat(ws): 设备定向推送房间` → `feat(ui): 设备列表页与会话设备绑定` → `feat(mobile): 手机壳与遥控面骨架` → `docs(prd): 同步设备遥控 P0 落地状态`。

---

## P0 总验收（对 spec §5 的 P0 项）

1. 手机/Web 登录后 **3 秒内**看到同账号设备列表且在线态正确（含离线置灰与原因）。
2. 显式选择设备进入会话后下发指令，本机工具在**指定设备**执行并回显结果（同机/内网可达场景）。
3. 指定设备离线/越权时返回**明确错误**（区分"无设备可用"与"指定设备离线"两种文案）。
4. 未绑定设备的旧路径行为零变化（全量回归通过）。
5. 设备管理动作（重命名/设默认/解绑）在 Web 与手机端均可用。

## 风险与依赖

- 迁移单 head：新增迁移前实测 `alembic heads`，避免多 head 与悬空引用（AGENTS 硬约束）。
- 工具工厂签名变更涉及 4 类工具 + façade 测试，注意**唯一注入点**纪律，避免各工具各写一套解析。
- P0 端到端不覆盖公网形态；P1 设备网关上线后补"跨网络"验收。
- 移动端原生工程与 CI 产物口径需与 `.github/workflows/mobile-build.yml` 对齐，避免本地生成物污染仓库。
