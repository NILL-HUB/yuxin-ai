# Windows 桌面客户端（设备 Agent 宿主壳）

> 更新日期：2026-09-08
> 定位：桌面客户端（子项目 A）已实现首版并完成 NSIS 打包验证。本文档描述真实代码结构（`desktop/`），作为该模块的权威架构入口。
> 主文档：[architecture-design.md](../architecture-design.md)
> 相关模块：[08-os-automation.md](./08-os-automation.md)（宿主机 OS worker 服务端）｜ 设计规格：[2026-09-08-desktop-client-a-design.md](../../superpowers/specs/2026-09-08-desktop-client-a-design.md)｜ 执行计划：[2026-09-08-desktop-client-a-plan.md](../../superpowers/plans/2026-09-08-desktop-client-a-plan.md)

## 目标

面向普通用户的完整 Windows 桌面客户端：单 NSIS 安装包交付，Electron 主程序为唯一入口，内嵌完整 Web UI（免装 Python、免配环境），自动托管本机 Python worker（OS 文件/回收站/快照、浏览器自动化、计算机控制、唤醒词），带桌面原生体验（托盘/通知/开机自启/自动更新）与 safeStorage 凭证持久化。

不在本模块范围：远程中枢（设备注册、手机→电脑下发任务）为子项目 B（设计规格另文）。

## 架构

```text
Electron 主进程（desktop/main.js，唯一入口）
├─ server-config（server-config.js）
│     内置入口域名 → GET <entry>/api/desktop-config → { api_origin, api_prefix, app_name }
│     → 缓存 userData/server-config.json；失败用缓存/入口兜底
│     → preload 同步注入 window.__DESKTOP_CONFIG__（apiBase/socketUrl/...）
├─ worker-host（main.js 内）
│     spawn 单一 worker exe（PyInstaller: yuxin-worker.exe，super 入口）
│     按子命令起 os(8765)/browser(8766)/computer(8767)；wake 按需启动
│     开发模式（无 exe）回退 python scripts/<worker>.py；退出通知 + 崩溃不自动拉起
├─ 本地能力桥（bridge.js，127.0.0.1:9876）
│     /file /recycle /snapshot → os worker；/browser → browser；/control → computer
├─ 原生体验
│     托盘 tray.js（关闭驻留/显示/真退出停 worker）
│     系统通知（worker 异常/更新可用）
│     开机自启 IPC（app.setLoginItemSettings）
│     自动更新 updater.js（electron-updater，publish 指向更新服务器占位）
├─ 凭证 credential-store.js
│     safeStorage（Windows DPAPI）加密存取 access_token（userData/credential.bin）
│     与 Web UI localStorage 双向同步
└─ BrowserWindow（loadFile resources/ui-dist/index.html；dev 模式连 Vite）
      renderer = 完整 Web UI（extraResources 携带的桌面版产物 ui-dist）
      API base = window.__DESKTOP_CONFIG__.apiBase（非 file:// origin）
      CORS：file:// 页面（Origin: null）请求远程 API 由主进程
            session.webRequest.onHeadersReceived 对配置的 apiOrigin 放宽 CORS 头
```

## 关键实现

### 1. 单一 worker exe（worker_super）

- `api/scripts/worker_super.py`：argparse 子命令 `os|browser|computer|wake`，按白名单转发 `--host/--port` 到各 worker 模块 `main()`（替换 `sys.argv` 后调用，避免 worker 内 argparse 吃到自身不认识的参数）；`SystemExit` 包装保留退出码。
- PyInstaller spec `api/scripts/pyinstaller/worker.spec` 产出 `api/scripts/pyinstaller/dist/yuxin-worker.exe`（hiddenimports 显式声明 4 个 worker 模块）。
- worker 间 token 由主进程 `crypto.randomBytes` 生成注入 env；全部仅回环监听。
- 打包依赖：浏览器/唤醒词运行时二进制（Chromium/模型）不在 PyInstaller 内——浏览器 worker 需 `PLAYWRIGHT_BROWSERS_PATH`、唤醒词需 `WAKE_WORD_MODEL_DIR`；缺失时主进程侧仍可托管 os/computer，browser/wake 能力报清晰错误。

### 2. 服务器地址注入（server-config + /api/desktop-config）

- 后端 `GET /desktop-config`（公开、无鉴权）：返回 `{ app_name, api_origin, api_prefix }`（`api_origin` 即请求同源）。
- `desktop/server-config.js` `loadServerConfig`：fetch 入口 → 校验 data.api_origin → 写 userData 缓存；失败读缓存；无缓存用 `DEFAULT_ENTRY_ORIGIN` 兜底。
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
| `DESKTOP_ENTRY_ORIGIN`（`server-config.js` 内常量） | `https://openllm.cloud` | 内置入口域名，用于首次拉取 desktop-config |
| `DESKTOP_PYTHON` | `python` | 开发模式 worker 解释器 |
| `OS_AUTOMATION_PORT` / `BROWSER_AUTOMATION_PORT` / `COMPUTER_CONTROL_PORT` | 8765 / 8766 / 8767 | worker 监听端口（dev 覆盖用） |
| `DESKTOP_BRIDGE_PORT` | 9876 | 本地能力桥端口 |
| `VITE_DEV_SERVER_URL` | — | dev 模式连 Vite dev server |

## 构建与分发

- UI 桌面版构建：`cd ui && npm run build:desktop`（`vite build --mode desktop`，`base:'./'`，产物 `ui/dist-desktop/`）；Web 部署仍用 `npm run build`（绝对路径 `dist/`），两者互不覆盖。
- Worker exe（已装 PyInstaller 时）：`cd api/scripts/pyinstaller && pyinstaller --clean --noconfirm worker.spec`。
- NSIS 安装包：`cd desktop && npm run dist`（自动先跑 `build:ui`；electron-builder 输出固定 `desktop/dist-nsis/`；`extraResources` 携带 `ui-dist` 与 `yuxin-worker.exe`）。
- 打包环境变量（NSIS 资源下载失败时）：`ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/`。
- 签名：`signAndEditExecutable: false`，正式发布需代码签名证书；publish.url 为占位。

## 验证

- 桌面单元测试：`cd desktop && node --test test/*.test.js`（server-config 缓存回退、credential-store 加解密、bridge）。
- UI 测试：`cd ui && npx vitest run`（含 desktop-credential-sync、DesktopDevicePanel、config desktop override）。
- 冒烟：开发模式 `cd desktop && npm start`；桌面版产物（相对路径）需经 Electron 加载验证——`file://` 下资源/API 正常（CORS 头经主进程注入）；NSIS 安装后启动 → 托盘 → 登录/登出/重启保持登录态。

## 首版范围与后续

- 已交付（2026-09-08）：单 exe worker 托管、服务器地址注入、托盘/通知/自启/更新框架、safeStorage 凭证同步、设备面板完善、NSIS 打包验证（`钰心AI Setup 0.1.0.exe`）。
- 已交付（2026-09-09，窗口原生化，对标 Hermes）：移除默认应用菜单栏（`Menu.setApplicationMenu(null)`）；`titleBarStyle:'hidden'` + Windows `titleBarOverlay`（系统原生 min/max/close 叠加层，renderer 经 `navigator.windowControlsOverlay` 读取按钮区宽度避让）；自绘标题栏组件 `DesktopTitleBar.vue`（拖拽区 + 双击最大化 + 品牌名，fixed 毛玻璃悬浮，仅桌面环境渲染）；窗口位置/尺寸/最大化状态持久化（`window-state.js`）；布局以 CSS 变量 `--desktop-titlebar-h` 适配（Web 为 0，零影响）；worker 宿主存活看门狗修复（`GetExitCodeProcess` 探活替代 Windows 下不可用的 `os.kill(pid,0)`，宿主退出即自杀，含 PyInstaller onefile 双层进程）。
- 后续增强（不在首版）：更新服务器就绪后的正式自动更新验证、子项目 B 远程中枢（设备注册/手机下发任务）。
