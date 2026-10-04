# 设备网关 P1（手机远控下行通道 / 子项目 B）Implementation Plan

> **For agentic workers:** 本计划按任务逐个执行、独立提交；完成后按 AGENTS「架构文档同步」更新文档。设计依据：[手机端遥控与多设备协作设计（spec）](../specs/2026-10-03-mobile-remote-control-multi-device-design.md) §4.3。

**Goal:** 打通「云端 → 设备」的**常驻下行通道**：让手机/Web 在非同机网络（公网部署）下也能把任务下发到指定设备并拿回结果，为后续系统推送、审批挂起、`execution_target` 调度提供统一设备通信底座。

**Architecture:** 桌面端主进程建立到云端的 Socket.IO 常驻连接（复用现有 AsyncServer + RedisManager 广播能力）；下行指令按房间转发给设备；设备执行后经 **HTTP 回传**（上行方向无 NAT 问题）到服务端，用 `request_id` 经 **Redis pub/sub** 关联回发起进程完成同步等待。工具调用层保持**直连优先**为默认行为，网关按 `gateway_mode`（`off`/`prefer`/`fallback`，默认 `off`）显式启用——发布/私有化时置 `prefer`。

**Tech Stack（双侧）:** python-socketio（AsyncServer + RedisManager）、Quart、Redis（同步 pubsub）、Electron main（Node）+ `socket.io-client`、pytest、`node --test`。

**依据与前置（已核实，写代码前先读）：**
- `api/internal/extension/socketio_extension.py`：`AsyncServer(async_mode="asgi", message_queue=REDIS_URL)` + `RedisManager` 跨进程广播；`register_socketio_handlers` 在 `websocket_handlers.py` 以 `socketio.on(...)` 注册（当前仅默认命名空间）。
- 鉴权素材：`desktop_device.bridge_token_encrypted`（桌面端**每次启动随机生成**并注册；`_decrypt_value` 可解密）——网关**复用 `device_id + bridge_token`**，不新增 token 类型；`revoke` 即失效。
- 咽喉收敛点：`api/internal/core/tools/builtin_tools/providers/worker_client.py` 的 `call_host_worker` 是 os/browser/computer 的唯一出口（payload 已含 `requester` / `device_id`）。
- 桌面端现状：主进程**无长连接**（renderer 的 socket.io 是 UI 通知，不可复用）；`desktop/main.js` 已把 `socketUrl`（= api origin）注入 `window.__DESKTOP_CONFIG__`；本地 bridge `127.0.0.1:9876` 已有 Bearer。
- 多进程事实：compose `ASGI_WORKER_AMOUNT=2` → 等待关联**必须**跨进程（Redis pub/sub），不能用进程内 Event。
- 同步工具经 `_to_thread` 执行 → 工具内同步阻塞等待是允许的（在工作线程内）。

**明确不做（本批边界）：**
- 不做系统推送接入（个推为主/友盟为辅，独立批次）；不做审批挂起-复活；不做 `execution_target` 调度；不做跨设备协作；不把 60s HTTP 心跳替换为纯 WS 心跳（双轨保留）；不做「请求走 WS 回 WS」的双向 RPC（回传统一走 HTTP + Redis 关联，回避跨进程双向等待）。

---

## 已核实的事实（避免重复踩坑）

1. 设备**已注册且未吊销**即可鉴权：网关连接时用 `device_id + bridge_token` 与 `desktop_device` 比对（解密后 `hmac.compare_digest`）。
2. 现有 `call_host_worker` 在「无 bridge 可解析」时的静态回退与文案（`resolve_unavailable_message`）**必须保持不变**；网关是新增的第三段，不改变前两段语义。
3. 设备房间命名与订阅侧约定：网关链路房间 `device-link:<device_id>`（服务端内部使用，**不对外暴露订阅**，与 P0 的 `device:<device_id>` 通知房间区分开）。
4. 结果回传必须**幂等**：同一 `request_id` 重复回传只唤醒一次（等待侧拿到即回收；重复发布无人订阅即丢弃）。
5. 网关在线判定 ≠ 心跳租约：两者独立（心跳=设备存活语义；网关链路=可下发语义）；`is_online` 只作为「经网关下发」的前提，不并入 `_effective_status`。

---

## 文件结构

```text
api/
├─ internal/service/device_gateway_service.py            # 在线判定 + call_device（Redis 关联等待）
├─ internal/service/desktop_device_service.py            # + verify_bridge_token（设备鉴权）
├─ internal/extension/device_gateway_handlers.py         # /device 命名空间 connect/disconnect
├─ internal/extension/socketio_extension.py              # 挂载 /device 命名空间
├─ app/http/desktop_routes.py                            # + POST /desktop/gateway/result（设备回传）
├─ internal/core/tools/builtin_tools/providers/worker_client.py  # gateway_mode 路由（off/prefer/fallback）
├─ internal/service/desktop_client_config_service.py     # + gateway_mode 读取（admin 配置，env 兜底）
└─ test/...（见各任务）
desktop/
├─ device-gateway.js                                     # 常驻连接 + 指数退避重连 + 指令执行（调本地 bridge）
├─ main.js                                               # 注册成功后启动/退出停止
├─ package.json                                          # + socket.io-client
└─ test/device-gateway.test.js                           # node --test
```

---

## Task 1: 设备通道（服务端连接与在线判定）

**文件**：`device_gateway_service.py`（新）、`device_gateway_handlers.py`（新）、`socketio_extension.py`、`desktop_device_service.py`（+`verify_bridge_token`）、测试。

**步骤**：
- [ ] `DesktopDeviceService.verify_bridge_token(account_id=None, device_id, token) -> bool`：按 device_id 取设备（可选账约束）→ 解密比对（`hmac.compare_digest`）→ 未吊销才有效。
- [ ] `/device` 命名空间 `connect`：从 `auth` 取 `{device_id, bridge_token}` → 校验 → `enter_room(sid, "device-link:<device_id>")` → 记录 sid↔device 映射（进程内 map，供 disconnect 清理与日志）。失败 `return False`（拒绝连接）。
- [ ] `disconnect`：清理映射；房间由 socket.io 自动退。
- [ ] `DeviceGatewayService.is_online(device_id) -> bool`：进程内链路映射非空即在线（多进程下本进程视角；调用方为「发起下发的进程」，与设备所在进程可能不同——**下行经 RedisManager 广播，无需本进程持有连接**，故 `is_online` 的权威判据应改为 Redis 键：连接/断开时 `SET/DEL device-link:<id>`（带 TTL，由心跳续）→ 本任务同时实现该键的写入/清理）。
- [ ] 测试：鉴权通过/失败（错 token、已吊销）、房间与 Redis 键写入、disconnect 清理、`is_online` 读键。

**验收**：桌面端（或测试客户端）以 `device_id+bridge_token` 可连入 `/device` 并出现在 `device-link:*` 键中；错误凭证被拒。

---

## Task 2: 下行调用（call_device）

**文件**：`device_gateway_service.py`、测试 `test_device_gateway_service.py`。

**步骤**：
- [ ] `call_device(device_id, *, purpose, payload, timeout=60) -> dict | None`：
  1. `is_online` 不通过 → 返回 `None`（调用方按"设备离线"文案处理）；
  2. 生成 `request_id`（uuid4 hex）→ 订阅 Redis 频道 `device-gw-resp:<request_id>`（同步 `pubsub.get_message(timeout=...)` 循环到 deadline）；
  3. `RedisManager.emit("device_dispatch", {request_id, purpose, payload, timeout_ms}, room="device-link:<id>")`；
  4. 收到回传 → 解析 `{ok, result}` 返回；超时 → 返回 `{"ok": False, "error": "设备响应超时"}`；异常 → 与 worker_client 一致的错误 dict；
  5. `finally` 退订并清理。
- [ ] 常量与语义：`purpose` 用现有端点语义（`/file`、`/control`… 与 bridge 路由一致），payload 即 worker payload（含 device_id/requester），设备侧原样转发给本地 bridge。
- [ ] 测试（假 Redis pubsub + 假 manager.emit）：命中回传、超时、离线直接 None、emit 异常降级、request_id 唯一。

**验收**：单测覆盖全部分支；超时不泄漏订阅。

---

## Task 3: 结果回传端点

**文件**：`api/app/http/desktop_routes.py`、测试 `test_desktop_gateway_result.py`。

**步骤**：
- [ ] `POST /desktop/gateway/result`：body `{device_id, request_id, ok, result?, error?}`；Bearer = `bridge_token` → `verify_bridge_token` 失败 401；成功 → `redis.publish("device-gw-resp:<request_id>", json)` → `_ok({"accepted": True})`。
- [ ] 幂等与安全：不校验 request_id 是否在途（无人等待即丢弃）；不落库；日志含 device_id/request_id。
- [ ] 测试：鉴权失败 401、成功 publish（假 redis）、body 校验（缺字段 400）。

**验收**：端点可被设备侧调用完成一次闭环（与 Task 2 的等待侧对接）。

---

## Task 4: 工具层接入（gateway_mode）

**文件**：`worker_client.py`、`desktop_client_config_service.py`、测试。

**步骤**：
- [ ] `DesktopClientConfigService.resolve_gateway_mode() -> "off" | "prefer" | "fallback"`：读 `desktop_client_config` JSONB 的 `gateway_mode`（admin 配置），空/异常回退 env `DESKTOP_GATEWAY_MODE`，默认 `off`。
- [ ] `call_host_worker` 三段式：
  - `off`（默认）：行为**完全不变**；
  - `prefer`：若 `device_id` 已解析且 `is_online` → `call_device`；否则走现有直连；
  - `fallback`：先直连；直连返回的是**连接类失败**（URLError/timeout，非业务错误）且 `is_online` → 再用 `call_device` 重试一次。
- [ ] 文案：网关离线 → 复用 `resolve_unavailable_message(device_id)`；网关超时 → 明确"设备响应超时"（可重试提示）。
- [ ] 测试：三种模式的路径选择（monkeypatch `is_online`/`call_device`/`urlopen`）；`off` 模式回归（现有测试全绿即证）；`prefer` 离线时直连兜底。

**验收**：默认零行为变化；置 `prefer` 后工具调用经网关；两条路径的测试均覆盖。

---

## Task 5: 桌面端网关客户端

**文件**：`desktop/device-gateway.js`（新）、`desktop/main.js`、`desktop/package.json`（+`socket.io-client`）、`desktop/test/device-gateway.test.js`。

**步骤**：
- [ ] 连接：注册成功（`device-registry` 回调/`bridgeAccessInfo` 就绪）后启动；URL = `socketUrl`（`__DESKTOP_CONFIG__`/server-config），namespace `/device`，auth `{device_id, bridge_token}`；断开指数退避重连（1s→60s 封顶），凭证刷新（每次重注册后 token 可能变化）时重连。
- [ ] 指令：监听 `device_dispatch` → 校验 `purpose` 属于白名单（`/file /recycle /snapshot /exec /browser /control /render /artifact`）→ 以 Bearer worker token POST `http://127.0.0.1:<bridgePort><purpose>`（复用 bridge 端口解析） → 由主进程 POST `{device_id, request_id, ok, result|error}` 到 `<apiBase>/desktop/gateway/result`。
- [ ] 生命周期：`before-quit` 断开；托盘菜单显示网关连接状态（可选，放最小实现）。
- [ ] 测试（`node --test`，mock socket.io-client 与 http）：dispatch 白名单、payload 透传、回传体格式、重连退避计算。
- [ ] **验证限制说明**：本环境无法运行 Electron 真机端到端；以单测 + 手工冒烟清单交付（启动桌面端 → 服务端 Redis 出现 `device-link:*` → 从服务端调用 `call_device` 收到设备回传）。

**验收**：单测通过；冒烟清单可人工执行；`npm run dist` 不受影响（新增依赖为纯 JS）。

---

## Task 6: 收尾

- [ ] 文档同步：`09-desktop-client.md` §1d 或新增 §1e（网关链路与 `gateway_mode`）；spec §9 标注网关批次状态；`docs/README.md` 本计划状态。
- [ ] 接线审查：`is_online` / `call_device` / `verify_bridge_token` / `/device` connect / 回传端点 逐个点名生产调用方（worker_client 与 socketio 注册）。
- [ ] `python -m graphify update .`；提交序列（`feat(gateway): ...` ×5 + `docs(prd): ...`）。

## 风险与依赖

- 多进程语义：`device-link:*` 键的 TTL 需 > 重连退避上限；设备崩溃/断网时键自然过期。
- 网关不经 WSS 独立鉴权层，复用 API 网关的 TLS；企业私有化如需独立入口，后续再评估（对应 ZCode 的 endpoint 覆盖思路）。
- 桌面端新增 `socket.io-client` 依赖需同步 NSIS 打包验证（CI 出包时覆盖）。
- 本批次完成后，「手机远控」才真正脱离同机部署限制；系统推送与审批挂起仍待后续批次。
