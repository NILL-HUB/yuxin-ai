# Windows 桌面客户端（设备 Agent 宿主壳）

> 更新日期：2026-09-19
> 定位：桌面客户端（子项目 A）已实现首版并完成 NSIS 打包验证；设备注册（登录即设备）已实现，"服务端 → 宿主机"链路已打通。
> 更新（2026-10-04）：手机端遥控 **P0 已落地**——设备管理（重命名/设默认/解绑）、会话级设备绑定（`conversation.desktop_device_id`）、设备定向推送房间、Web/手机设备列表页；设计见 [spec](../../superpowers/specs/2026-10-03-mobile-remote-control-multi-device-design.md)、计划见 [plan](../../superpowers/plans/2026-10-03-mobile-p0-device-list-and-binding.md)。
> 主文档：[architecture-design.md](../architecture-design.md)
> 相关模块：[08-os-automation.md](./08-os-automation.md)（宿主机 OS worker 服务端）｜ 设计规格：[2026-09-08-desktop-client-a-design.md](../../archive/superpowers-specs/2026-09-08-desktop-client-a-design.md)（已归档）｜ 执行计划：[2026-09-08-desktop-client-a-plan.md](../../archive/superpowers-plans/2026-09-08-desktop-client-a-plan.md)（已归档）

## 目标

面向普通用户的完整 Windows 桌面客户端：单 NSIS 安装包交付，Electron 主程序为唯一入口，内嵌完整 Web UI（免装 Python、免配环境），自动托管本机 Python worker（OS 文件/回收站/快照、浏览器自动化、计算机控制、本机渲染出片、唤醒词），带桌面原生体验（托盘/通知/开机自启/自动更新）与 safeStorage 凭证持久化。

不在本模块范围：手机→电脑下发任务的远程中枢长连接（WS 通道）仍为子项目 B（设备注册的**本地落地**已实现，见 §1c）。

## 架构

```text
Electron 主进程（desktop/main.js，唯一入口）
├─ server-config（server-config.js）
│     内置入口域名（可用 DESKTOP_ENTRY_ORIGIN 覆盖）→ GET <entry>/api/desktop-config
│     → { api_origin, api_prefix, app_name }（api_origin 优先取 admin 配置的桌面连接地址，未配置回退同源）
│     → 缓存 userData/server-config.json；失败用缓存/入口兜底
│     → preload 同步注入 window.__DESKTOP_CONFIG__（apiBase/socketUrl/...）
├─ worker-host（main.js 内）
│     spawn 单一 worker exe（PyInstaller: yujianwo-worker.exe，super 入口）
│     按子命令起 os(8765)/browser(8766)/computer(8767)/render(8768)；wake 按需启动
│     端口动态化：启动前探测可用端口，被占用（如与 Docker 容器映射冲突）自动顺延并互斥分配；
│     开发模式（无 exe）回退 python scripts/<worker>.py；退出通知 + 崩溃不自动拉起
├─ cua-driver-host（cua-driver-host.js）
│     解析 cua-driver 二进制 → spawn serve（后台计算机控制 daemon）→ 就绪探测；退出停 daemon
├─ device-registry（device-registry.js）
│     持久化稳定 device_id（userData/device-id）；登录后 POST /desktop/devices/register
│     上报 bridge_origin（默认 http://host.docker.internal:9876）+ 随机 bridge token
├─ 本地能力桥（bridge.js，127.0.0.1:9876）
│     /file /recycle /snapshot /exec → os worker；/browser → browser；/control → computer；
│     /render /artifact → render worker（本机出片与产物取回）
├─ 原生体验
│     托盘 tray.js（关闭驻留/显示/真退出停 worker）
│     系统通知（worker 异常/更新可用）
│     开机自启 IPC（app.setLoginItemSettings）
│     自动更新 updater.js（electron-updater，publish.provider=generic，
│       url=https://openllm.cloud/desktop-updates）
├─ 凭证 credential-store.js
│     safeStorage（Windows DPAPI）加密存取 access_token（userData/credential.bin）
│     与 Web UI localStorage 双向同步
└─ BrowserWindow（loadFile resources/ui-dist/index.html；dev 模式连 Vite）
      renderer = 完整 Web UI（extraResources 携带的桌面版产物 ui-dist）
      API base = window.__DESKTOP_CONFIG__.apiBase（非 file:// origin）
      CORS：file:// 页面（Origin: null）请求远程 API 由主进程
            session.webRequest.onHeadersReceived 对配置的 apiOrigin 放宽 CORS 头
            （回显请求 Origin；不可用 ACAO:'*'，renderer 固定 credentials:'include'，
             通配符+凭据组合会被 Chromium 拦截）
```

## 关键实现

### 1. 单一 worker exe（worker_super）

- `api/scripts/worker_super.py`：argparse 子命令 `os|browser|computer|render|wake`（`parse_args` 的 `choices` 与 `_module_and_entry` 两处白名单），按白名单转发 `--host/--port` 到各 worker 模块 `main()`（替换 `sys.argv` 后调用，避免 worker 内 argparse 吃到自身不认识的参数）；`SystemExit` 包装保留退出码。
- PyInstaller spec `api/scripts/pyinstaller/worker.spec` 产出 `api/scripts/pyinstaller/dist/yujianwo-worker.exe`（hiddenimports 显式声明 5 个 worker 模块：os/browser/computer/render/wake）。
- computer worker 的 `pyautogui`/`Pillow` 依赖族经 spec 内 `collect_all` 显式打进 exe（worker 内为延迟 import，静态分析扫不到），使桌面端安装包开箱即可真正操作鼠标/键盘/截屏，无需用户额外装 Python 依赖。
- worker 间 token 由主进程 `crypto.randomBytes` 生成注入 env；全部仅回环监听。
- 打包依赖：浏览器/唤醒词运行时二进制（Chromium/模型）不在 PyInstaller 内——浏览器 worker 依赖 `playwright` + `playwright install chromium`，唤醒词 worker 依赖 `sounddevice`/`numpy`/`openwakeword`；缺失时对应 worker 启动即报明确依赖缺失错误（os/computer 不受影响）。render worker 的运行时（Chromium/ffmpeg/ffprobe/Node 依赖）不走 PyInstaller，改由 `extraResources` 随包分发，见 §1a。
>
> **历史注记**：早期版本此处提到 `PLAYWRIGHT_BROWSERS_PATH` / `WAKE_WORD_MODEL_DIR` 两个环境变量，但代码中并未读取它们；worker 各自解析的是 `BROWSER_AUTOMATION_*` 与 `WAKE_WORD_*`（keyword/endpoint/token/engine）系列变量。

### 1a. render worker（本机出片）

- **子命令**：`yujianwo-worker.exe render --port 8768`（默认端口 `render_worker.DEFAULT_PORT = 8768`；主进程如其余 worker 一样先探测可用端口，被占用自动顺延）。
- **职责**：在本机执行 HyperFrames 渲染（Node + Chromium + ffmpeg），把重负载算力从平台服务器转移到用户设备；平台服务器只处理轻量内容，成本可控。
- **桥路由**：`/render`（出片）、`/artifact`（取回产物字节）。
- **硬依赖**：`HYPERFRAMES_BROWSER_PATH` / `HYPERFRAMES_FFMPEG_PATH` / `HYPERFRAMES_FFPROBE_PATH`，缺一即返回可读错误（`RenderEnvironmentError`）。**浏览器必须是能响应 `--version` 的构建（chrome-headless-shell）**，Electron 自带 `chrome.exe` 不可替代。
- **Node 来源**：不要求用户安装 Node——`render-runtime.js` 的 `ensureCliShim` 在 `userData/render-runtime-bin/` 生成 `hyperframes.cmd`，用 `ELECTRON_RUN_AS_NODE=1` 把 Electron 内置 Node 包装为 CLI 入口（`HYPERFRAMES_CLI_BIN` 指向该 shim）。CLI 只接受单个可执行文件路径，故必须经 shim 两段式调用。
- **运行时分发**：Chromium / ffmpeg / ffprobe / `node_modules`（含裁剪到 win32 的 `onnxruntime-node`）由 `desktop/scripts/stage-render-runtime.js` 暂存到 `vendor/render-runtime/`，electron-builder `extraResources` 落到安装包 `resources/render-runtime/`；源目录缺失时跳过捆绑（打印提示、不阻断打包），此时本机渲染不可用而云端回退仍可用。
- **回传**：产物写在用户设备临时目录（`hf-local-render-` 前缀），服务端经 bridge `/artifact` 取回后复用 `KnowledgeBaseService.store_render_output` 入库；取回即清理该临时目录，不留残渣。
- **安全**：仅接受 `Bearer RENDER_WORKER_TOKEN`（常量时间比对），未配置 token 直接拒绝启动；`/artifact` 只允许读取系统临时目录内 `hf-local-render-` 前缀路径，避免被当作任意文件读取端点。

### 1b. cua-driver 后台计算机控制托管

- `desktop/cua-driver-host.js`：`resolveCuaDriverExe` 依次探测 `CUA_DRIVER_EXE` → 安装包 `resources/cua-driver/` → `~/.cua-driver/packages/current` → `%LOCALAPPDATA%`；`startCuaDriver` 复用已运行 daemon 或 `spawn(exe, ['serve'])` 并轮询 `status` 至就绪；退出时 `stopCuaDriver`。未安装则静默跳过，worker 自动回退前台 pyautogui。
- 二进制随包分发：`desktop/scripts/stage-cua-driver.js` 把本机安装的 `cua-driver.exe` / `cua-driver-uia.exe` / `cua-cursor-theme.exe` 复制到 `desktop/vendor/cua-driver/`，electron-builder `extraResources` 落到 `resources/cua-driver/`；`npm run pack/dist` 前自动 stage（CI `desktop-build.yml` 先装 cua-driver 再打包）。
- worker 侧经 `COMPUTER_CONTROL_BACKEND=auto` 探测 daemon（`cua_driver_client.daemon_reachable()`）后选 cua 后端——后台定向控制，不抢焦点、不移动真实光标（回执 `delivery.mode=background`）。
- `cua_driver_client.py` 已加入 worker.spec `hiddenimports`，随单一 worker exe 分发。

### 1c. 登录即设备注册（打通服务端 → 宿主机链路）

- 背景：桌面端 worker/bridge token 由主进程随机生成，服务端静态 `DESKTOP_BRIDGE_*` 永远对不上；桌面端需主动上报。
- `desktop/device-registry.js`：
  - `loadOrCreateDeviceId({filePath})`：`userData/device-id` 持久化稳定设备标识（首启生成 UUID）。
  - `resolveBridgePublicOrigin`：桥的对外地址；默认 `http://host.docker.internal:9876`（Bridge 仅监听 `127.0.0.1`，容器经 `host.docker.internal` 可达宿主回环，已实测），可用 `DESKTOP_BRIDGE_PUBLIC_ORIGIN` 覆盖。
  - `registerDevice(...)`：`POST {apiBase}/desktop/devices/register`，Bearer = 登录 access_token，body `{device_id, bridge_origin, bridge_token, name, platform}`。
- `main.js`：`app.whenReady` 内记录 `bridgeAccessInfo` 并尝试注册；`desktop:set-credential`（登录同步）与新增 `desktop:register-device` IPC 均触发注册（凭证落盘后再注册，避免竞态）。
- **设备心跳（2026-09-30）**：注册成功后 `main.js` 启动 `setInterval`，每 60s（`DEVICE_HEARTBEAT_INTERVAL_MS`）复用 `registerDevice` 上报一次以刷新服务端 `last_seen_at`；登出（`desktop:clear-credential`）与退出（`before-quit`）时停止。心跳是「设备在线」的唯一凭据——没有心跳，服务端无法区分设备是在线还是已关机。
- UI：`desktop-credential-sync.ts` 在 `setCredential` 成功后调用 `registerDevice()`（可选桥方法）。
- 服务端：`desktop_device` 表 + `DesktopDeviceService`（幂等 UPSERT / 按账号解析默认在线设备 / list / revoke）+ `resolve_desktop_bridge(account_id, purpose)`；工具层（os_* / computer_action / 渲染 / 浏览器自动化）统一经该解析器取 bridge，静态配置回退。详见 [08-os-automation.md](./08-os-automation.md) 与 [product-vision.md §4.1](../product-vision.md)。
- **设备租约（2026-09-30）**：`resolve_bridge` 在 `status = online` 之外，还要求 `last_seen_at` 落在 `DEVICE_ONLINE_TTL_SECONDS`（180s）内；`list_devices` 返回的 `status` 为**读时计算**（`_effective_status`，心跳超期显示 `offline`，不写库）。修复「`status` 由注册直接置位、无心跳维持」导致设备关机后仍被判在线、任务被派给死设备的主链路缺陷。约束：TTL 必须显著大于客户端心跳间隔（当前取 3 倍），改动需两端同步核对。
- **兼容性**：旧版客户端（无心跳）在服务端升级后，注册满 TTL 即被判离线，本机操作将回退静态配置或返回明确错误；服务端与客户端需同批升级。
- `browser_action` 已接入 `resolve_desktop_bridge`（按账号动态解析在线设备）并已在
  `assistant_agent_service` 挂载（`requester=account_id`），不再依赖静态 env 才能可用；
  未注册设备时回退 `BROWSER_AUTOMATION_URL/TOKEN` 并返回明确错误（默认关闭）。
  （2026-09-25 修复：`local_render_runner.py` 曾把「`browser_action` 仅读静态 env」记为已知断链，现已消除。）

### 1d. 设备管理与会话级设备绑定（P0，2026-10-04 落地）

- **设备管理接口**：`PATCH /desktop/devices/<device_id>`（重命名 / 设为默认；缺字段拒绝；设默认同账号互斥、已解绑设备禁止设默认）→ `DesktopDeviceService.update_device`。
- **会话级设备绑定**：`conversation.desktop_device_id`（迁移 `b7c8d9e0f1a2`）记录该会话的执行设备；`POST /assistant-agent/chat` 的 `device_id` 语义：**缺省/None=不改动、空串=解绑、非空=绑定**（绑定校验归属；离线可绑、已解绑拒绝）。绑定值在 `assistant_agent_service._build_assistant_runtime_tools` 的**唯一注入点**透传给走设备 bridge 的工具（os_file_task / os_snapshot / os_terminal / os_recycle_bin / computer_action / browser_action）。
- **按设备解析 bridge**：`resolve_desktop_bridge(account_id, device_id=...)` 指定设备时只解析该设备（归属 + 心跳租约，与 `resolve_bridge` 同口径），**不命中不回退静态配置**（避免静默换机执行），并以 `resolve_unavailable_message` 返回「指定的设备不可用」统一文案。
- **设备定向推送**：Socket.IO 房间 `device:<device_id>`（`subscribe_device_notification`，订阅前校验归属）；设备注册「非在线→在线」跃迁与吊销广播 `device_status_changed`（心跳不广播，避免 60s 噪音）。
- **前端**：`/devices` 设备列表页（在线态/重命名/设默认/解绑/使用此设备）；「使用此设备」→ `/home?device_id=…` → 发送时随 `/assistant-agent/chat` 透传。
- **手机壳构建链**：`mobile/` 补齐 `typescript` 依赖（`capacitor.config.ts` 需要），`cap sync` 可通过；APK/模拟器验证走 CI（`.github/workflows/mobile-build.yml`）。

### 1e. 设备网关：云端 → 设备常驻下行通道（P1，2026-10-04 落地）

解决 bridge 在 NAT 后面、公网不可达的问题（此前直连依赖 `host.docker.internal`，仅同机 Docker 可用）。

- **桌面端**（`desktop/device-gateway.js`）：注册成功后建立到云端 Socket.IO `/device` 命名空间的常驻连接，鉴权 `device_id + bridge_token`（复用注册凭证，吊销即失效）；自管指数退避重连（1s→60s）、30s `device_ping` 续期；收到 `device_dispatch` 后按白名单调本地 bridge（`127.0.0.1:<port><purpose>`），再经 HTTP `POST /desktop/gateway/result` 回传（上行无 NAT 问题）。
- **服务端**：`device_gateway_handlers.py`（connect/断开/ping，Redis 键 `device-link:<id>` 标记可下发性，TTL 180s）、`DeviceGatewayService`（`is_online` / `call_device` 经 RedisManager 广播下发 + 按 `request_id` 订阅等待，多 worker 下靠 Redis pub/sub 关联回发起进程 / `publish_result`）、`POST /desktop/gateway/result`（设备 Bearer 鉴权）。
- **路由模式**：`desktop_client_config.gateway_mode`（admin 配置，env `DESKTOP_GATEWAY_MODE` 兜底，**默认 off 零行为变化**）：`prefer`=网关优先（公网部署推荐；一旦下发即最终结果，绝不回退直连防重复执行）；`fallback`=直连仅网络类失败（OSError）且链路在线时经网关重试一次。
- **边界**：网关路由仅对**已绑定设备**的调用生效（网关按 device_id 路由）；未绑定设备的自动解析调用仍走直连，`execution_target`（P2）再统一。
- 测试：服务端 19 例（服务/处理器/路由/配置）+ 工具路由 7 例 + 桌面端 9 例；真机冒烟清单（启动桌面端 → Redis 出现 `device-link:*` → 服务端 `call_device` 收到回传）待执行。
- 仍未实现（P1 后续）：系统级推送（个推为主、友盟为辅的双通道 admin 热切换，需先办厂商资质/备案）——见 spec §4.11。

### 2. 服务器地址注入（server-config + /api/desktop-config）

- 后端 `GET /desktop-config`（公开、无鉴权）：返回 `{ app_name, api_origin, api_prefix }`。
  `api_origin` 优先取 admin 配置的"桌面客户端连接地址"（`desktop_client_config` 表单行 JSONB，
  见 `api/internal/service/desktop_client_config_service.py`），未配置时回退请求同源
  `{scheme}://{host}`；DB 异常时同样回退同源（引导入口不得 500）。
- admin 端维护该配置：`GET/PUT /admin/desktop-client-config`（`system_config:manage` 权限，
  UI 入口并入「全局控制配置」页面（`/admin/global-control-config`，`GlobalControlConfigView.vue` 的「桌面客户端连接」分组，
  数据/接口仍走 `admin-desktop-client-config` service）。开发环境配本地地址、生产环境换域名，桌面端启动自动跟随。
- `desktop/server-config.js` `loadServerConfig`：fetch 入口 → 校验 data.api_origin → 写 userData 缓存；失败读缓存；无缓存用入口兜底。
  入口域名默认 `https://openllm.cloud`，可用环境变量 `DESKTOP_ENTRY_ORIGIN` 覆盖（开发/自测指向本地后端）。
- 注入链路：preload `ipcRenderer.sendSync('desktop:get-config-sync')` → `window.__DESKTOP_CONFIG__`；运行中刷新经 `desktop:config-changed` 事件 + `onDesktopConfigChanged` 订阅。
- UI 侧 `resolveEndpointResolution`：desktop override（`window.__DESKTOP_CONFIG__`）优先级最高 > `VITE_API_PREFIX` > `location.origin`。
- 桌面环境（有 `window.__DESKTOP_CONFIG__`）路由用 hash history（`createWebHashHistory`），file 协议刷新/深链不依赖服务器 rewrite。

### 3. 凭证持久化（safeStorage）

- `desktop/credential-store.js` `createCredentialStore`：`encryptString` 写 `userData/credential.bin`；`save/load/clear` 返回布尔/null。
- IPC：`desktop:get/set/clear-credential`。UI `credential` store（`ui/src/stores/credential.ts`）在 update/clear 时经 `desktop-credential-sync.ts` 双向同步；应用启动、首次路由守卫 `restoreCredentialFromDesktop()` 在 localStorage 无凭证但主进程有 token 时回填（回填视为长有效期）。
- 安全：safeStorage 不可用（Windows 罕见）时降级为不持久化。

### 4. UI 侧（Vue 复用）

- `window.__DESKTOP_CONFIG__` 仅在 preload 存在时注入，Web 部署完全无感。
- 桌面版产物用相对路径（`base: './'` + `dist-desktop/`，`vite build --mode desktop`）——`loadFile` 的 `file://` 协议下 `/assets/*` 绝对路径会解析到磁盘根而白屏；Web 构建（`vite build`，`dist/`）保持绝对路径不变。
- `DesktopDevicePanel.vue`：worker 状态/版本/pid、回收站可恢复列表+恢复、唤醒词开关、开机自启开关、检查更新按钮；`desktopApi` 桥经 contextBridge 暴露。

## 环境变量与配置

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DESKTOP_ENTRY_ORIGIN` | `https://openllm.cloud` | 入口域名，用于首次拉取 desktop-config；开发/自测用环境变量覆盖（如 `http://127.0.0.1`） |
| `DESKTOP_PYTHON` | `python` | 开发模式 worker 解释器 |
| `OS_AUTOMATION_PORT` / `BROWSER_AUTOMATION_PORT` / `COMPUTER_CONTROL_PORT` / `RENDER_WORKER_PORT` | 8765 / 8766 / 8767 / 8768 | worker 监听端口（dev 覆盖用）；被占用时自动顺延到空闲端口，bridge 同步使用实际端口 |
| `DESKTOP_BRIDGE_PORT` | 9876 | 本地能力桥端口 |
| `DESKTOP_BRIDGE_PUBLIC_ORIGIN` | `http://host.docker.internal:<bridgePort>` | 上报服务端的桥对外地址；裸机（非容器）服务端可设为 `http://127.0.0.1:<bridgePort>` |
| `DESKTOP_DEVICE_NAME` | 主机名 | 设备展示名（注册时上报） |
| `CUA_DRIVER_EXE` | 自动探测 | cua-driver 可执行文件路径（未设则探测安装包/用户目录/PATH） |
| `COMPUTER_CONTROL_BACKEND` | `auto` | computer worker 后端：auto（daemon 可达则 cua，否则 pyautogui）/ cua / pyautogui |
| `VITE_DEV_SERVER_URL` | — | dev 模式连 Vite dev server（标准端口 3000，对应 `docker/ui-dev`；`desktop/package.json` 的 `dev` script 已对齐） |

## 构建与分发

- UI 桌面版构建：`cd ui && npm run build:desktop`（`vite build --mode desktop`，`base:'./'`，产物 `ui/dist-desktop/`）；Web 部署仍用 `npm run build`（绝对路径 `dist/`），两者互不覆盖。
- Worker exe（已装 PyInstaller 时）：`cd api/scripts/pyinstaller && pyinstaller --clean --noconfirm worker.spec`。
- NSIS 安装包：`cd desktop && npm run dist`（自动先跑 `build:ui`、`stage:cua` 把 cua-driver 二进制 stage 到 `desktop/vendor/cua-driver/`、`stage:render` 把渲染运行时（`scripts/stage-render-runtime.js`，需 `RENDER_RUNTIME_SOURCE_DIR` 指向含 `node_modules`/Chromium/ffmpeg 的源目录）stage 到 `desktop/vendor/render-runtime/`；electron-builder 输出固定 `desktop/dist-nsis/`；`extraResources` 携带 `ui-dist`、`yujianwo-worker.exe`、`cua-driver/` 与 `render-runtime/`）。
- 打包环境变量（NSIS 资源下载失败时）：`ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/`。
- 签名：`signAndEditExecutable: false`，正式发布需代码签名证书；`publish` 已指向 `https://openllm.cloud/desktop-updates`（generic provider），更新服务器目录需自行托管安装包与 `latest.yml`。

### 自动更新与发布

**检查时机（2026-09-30 补全）**：启动后延迟 30s 检查一次 + 每 24h 巡检（`desktop/updater.js` 的 `schedulePeriodicChecks`，由 `main.js` 在 `setupUpdater` 之后调用）。另有两条手动入口：托盘「检查更新」菜单项（`tray.js` → `onCheckUpdates`）与 IPC `desktop:check-for-updates`。手动触发传 `manual: true`，**仅此时**才提示「已是最新版本」——自动巡检每天都会 `not-available`，无差别提示会变成噪音。补全前 `checkForUpdates()` 只有 IPC 一个调用点、且托盘无入口，用户不主动点就永远不会检查更新（新版本无法到达用户）。

**下载与安装**：`autoDownload = true`、`autoInstallOnAppQuit = true`（`updater.js`）。发现新版本即后台下载，完成后托盘通知，退出应用时安装——**全程无需用户操作**。

**更新弹窗与更新历程（2026-09-30 补全）**：发现新版本时渲染进程弹出 `ui/src/components/DesktopUpdateModal.vue`（挂载于 `App.vue`，仅桌面环境），展示目标版本号与更新内容；下载完成后弹窗内状态切为「更新已就绪」，并提供可选的「立即重启并安装」（加速入口，不做也不影响下次启动自动安装）。数据链路为**单向透传**：

1. 发布端 `build.releaseInfo.releaseNotesFile = release-notes.md`（`desktop/package.json`）→ `electron-builder` 把 `desktop/release-notes.md` 内容写入 `latest.yml` 的 `releaseNotes` 字段；
2. 客户端 `updater.js` 的 `pickUpdateInfo` / `normalizeReleaseNotes` 把 `UpdateInfo` 归一为 `{ version, releaseNotes }`（`releaseNotes` 兼容 string / `Array<{version,note}>` / null）；
3. `main.js` 的 `setupUpdater.onStatus` 向全部窗口 `webContents.send('desktop:update-status', { status, version, releaseNotes, manual })`；
4. `preload.js` 暴露 `onUpdateStatus(callback)` 订阅与 `quitAndInstall()`；**两个消费方订阅同一事件**——更新弹窗（`DesktopUpdateModal.vue`：仅 `available` 时弹出，`downloaded` 只更新弹窗内状态）与设备面板的「检查更新」按钮（`DesktopDevicePanel.vue`：把 `checking` / `available` / `not-available` / `downloaded` / `error` 映射为即时文案，修复此前成功后永久停在「正在检查」的缺陷；`not-available` 仅在 `manual:true` 时提示「已是最新」，自动巡检不打扰）。主进程在检查失败（`error` 事件）时同样广播 `status='error'`，否则按钮无从知晓失败。

**推送门控与 admin 检查（2026-09-30 新增）**：更新是否下发由 **admin 决定**，而非「上传即生效」。

- 配置落库 `desktop_client_config`（复用既有单行 JSONB，**未新建平行表**）：`update_feed_url`（更新包目录地址）、`update_enabled`（推送开关）；admin 入口为「全局控制配置 → 桌面客户端」卡片（`GlobalControlConfigView.vue`）。
- **客户端运行时读取点**：公开接口 `GET /desktop/update-manifest`（`desktop_routes.py`）返回 `{ enabled, feed_url }`；`updater.js` 的 `checkForUpdates` 在检查前先拉取该清单——`enabled=false` 时静默跳过，`feed_url` 非空时 `autoUpdater.setFeedURL({ provider: 'generic', url })` 覆盖打包内置 feed（便于随时切换托管位置）。接口不可达时按既有行为降级（用打包内置 feedUrl），不倒退。
- **admin 检查更新**：`POST /admin/desktop-update/check`（权限 `system_config:manage`）由服务端拉取 `${update_feed_url}/latest.yml` 并解析（版本号 / 更新内容 / 发布时间），供管理员在开启推送前核对上游是否已有版本——读的是客户端将要读的同一份 `latest.yml`。
- **兼容性**：门控只对**已升级到本版**的客户端生效；旧版客户端仍直连打包内置 feed（`package.json` 的 `publish.url`），不受开关约束，需覆盖升级后纳入管控。

**发布步骤**：

1. 递增 `desktop/package.json` 的 `version`（**必须递增**，`electron-updater` 依据 `latest.yml` 中的版本比对），并更新 `desktop/release-notes.md` 写明本次更新历程（该文件内容即客户端弹窗展示的文案）；
2. `cd desktop && npm run dist` → 产物在 `dist-nsis/`，含 `钰见我 Setup <版本>.exe`、`latest.yml`、`*.blockmap`；
3. 将 **`*.exe` + `latest.yml` + `*.blockmap` 三者同批**上传到更新包目录（默认 `https://openllm.cloud/desktop-updates/`）；
4. 在 admin「全局控制配置 → 桌面客户端」填入该更新包地址并**打开「向客户端推送更新」开关**——开关关闭时客户端静默跳过检查，新版本不会下发。

**三个易踩的坑**：① `latest.yml` 必须与新 exe 同批上传，只换 exe 会让客户端判定无更新；② 旧的 exe 不要删除——`.blockmap` 差分更新依赖它们，删除后客户端退化为全量下载；③ 版本号只能单调递增，回滚需发布更高版本号的新包，不能降号。

**未签名的影响**：`signAndEditExecutable: false` 时安装会触发 SmartScreen「未知发布者」警告。内部合伙人规模下手动分发可以接受，但要实现静默自动更新，代码签名基本是前提。

**部署前提（代码之外）**：更新包目录需由运维托管（nginx location 或对象存储）并可从公网读取，目录中须含 `latest.yml` 与安装包。目录地址不再写死在代码里——改用 admin 的 `update_feed_url` 指向任意可达位置即可；但**目录本身**仍需部署。截至 2026-09-30 实测 `https://openllm.cloud/desktop-updates/latest.yml` 返回错误页，说明该目录尚未部署或未配好路由——这是整条更新链路上唯一不在代码内的环节。

## 验证

- 桌面单元测试：`cd desktop && node --test test/*.test.js`（server-config 缓存回退、credential-store 加解密、bridge）。
- UI 测试：`cd ui && npx vitest run`（含 desktop-credential-sync、DesktopDevicePanel、DesktopUpdateModal、config desktop override）。
- 冒烟：开发模式 `cd desktop && npm start`；桌面版产物（相对路径）需经 Electron 加载验证——`file://` 下资源/API 正常（CORS 头经主进程注入）；NSIS 安装后启动 → 托盘 → 登录/登出/重启保持登录态。

## 首版范围与后续

- 已交付（2026-09-08）：单 exe worker 托管、服务器地址注入、托盘/通知/自启/更新框架、safeStorage 凭证同步、设备面板完善、NSIS 打包验证（`desktop/package.json` 当时未设 `productName`，安装包名取自 `name=yujianwo-desktop`；仓库内 `desktop/dist-nsis/` 现存产物为更名前构建的 `钰心AI Setup 0.1.0.exe`。**现状（2026-09-30 核对）**：`build.productName` 已设为 `钰见我`，产物名为 `钰见我 Setup <版本>.exe`）。
- 已交付（2026-09-09，窗口原生化，对标 Hermes）：移除默认应用菜单栏（`Menu.setApplicationMenu(null)`）；`titleBarStyle:'hidden'` + Windows `titleBarOverlay`（系统原生 min/max/close 叠加层，renderer 经 `navigator.windowControlsOverlay` 读取按钮区宽度避让）；自绘标题栏组件 `DesktopTitleBar.vue`（拖拽区 + 双击最大化 + 品牌名，fixed 毛玻璃悬浮，仅桌面环境渲染）；窗口位置/尺寸/最大化状态持久化（`window-state.js`）；布局以 CSS 变量 `--desktop-titlebar-h` 适配（Web 为 0，零影响）；worker 宿主存活看门狗修复（`GetExitCodeProcess` 探活替代 Windows 下不可用的 `os.kill(pid,0)`，宿主退出即自杀，含 PyInstaller onefile 双层进程）。
- 已交付（2026-09-09，连接配置与 CORS 修复）：admin 端新增"桌面客户端连接地址"配置（`desktop_client_config` 表单行 JSONB + `GET/PUT /admin/desktop-client-config`），`/desktop-config` 优先返回配置地址、未配置/DB 异常回退同源；`DESKTOP_ENTRY_ORIGIN` 支持环境变量覆盖；修复 `onHeadersReceived` CORS 通配符 + 凭据非法组合（改为回显请求 Origin）。2026-09-23 起该配置的 UI 入口并入「全局控制配置」页面「桌面客户端连接」卡片（`GlobalControlConfigView.vue`），数据/接口不变。
- 已交付（2026-09-11，电脑控制开箱可用）：worker exe 打包 `pyautogui`/`Pillow` 依赖族，桌面端无需额外装 Python 依赖即可真实操作鼠标/键盘/截屏（实测移动鼠标与截图通过）；重新产出 NSIS 安装包。
- 已交付（2026-09-11，设备链路打通 + cua-driver 集成）：
  - 登录即设备注册（`device-registry.js` + `desktop_device` 表 + `DesktopDeviceService` + `resolve_desktop_bridge`），服务端按账号动态解析 bridge，替代静态 `DESKTOP_BRIDGE_*`；端到端实测通过。
  - cua-driver 后台控制闭环：`cua-driver-host.js` 托管 daemon、`stage-cua-driver.js` 随包分发二进制、worker.spec 打包客户端；实测背景点击 `delivery.mode=background`，不抢焦点、不移动真实光标。
- 已交付（2026-09-19，本机渲染出片）：桌面端托管第 4 个本机 worker `render`（`yujianwo-worker.exe render`，默认 8768），Electron 内置 Node 经 `render-runtime.js` 生成的 `hyperframes.cmd` shim 充当 HyperFrames CLI，Chromium/ffmpeg/ffprobe/node_modules 随安装包分发到 `resources/render-runtime/`；bridge 新增 `/render`（出片）与 `/artifact`（取回产物字节）两条路由。服务端渲染工具改为**三级路由**：本机 bridge 优先 → 云端 Celery `render` 队列回退（受 `RENDER_CLOUD_FALLBACK_ENABLED` 控制）→ 明确报错；本机产物经 `/artifact` 取回后复用 `store_render_output` 入库。云端渲染代码与限流参数完整保留（`docker compose --profile cloud-render up -d llmops-render-worker` 一键接通），默认不启动。详见 [deployment-single-node.md](../../deployment-single-node.md) 的「渲染执行位置」。
- 后续增强（不在首版）：更新服务器就绪后的正式自动更新验证、子项目 B 远程中枢长连接（WS 通道 / 手机下发任务 / 产物回传）。
