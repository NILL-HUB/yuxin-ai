# 桌面客户端（子项目 A：本机桌面端）设计

> 更新日期：2026-09-08
> 定位：设计规格（已评审确认）。子项目 B（远程中枢）另文设计。
> 前置依赖：用户端登录已路由化（`/auth/login` 完整页，见 `2026-09-08-user-login-routing-design.md`）；本机文件操作自愈闭环（os_file_task V4A 写前快照 + os_recycle_bin + os_snapshot，见 `local-file-snapshot-rollback-plan.md`）。

## 0. 目标

把现有 `desktop/` Electron 壳（复用 Web UI + 托管本地 Python worker + 本地桥）完善为**面向普通用户的完整 Windows 桌面客户端**：单安装包交付、用户免装 Python、内嵌完整 Web UI（登录即用）、本机能力（文件操作/回收站/快照回滚/浏览器/计算机控制/唤醒词）开箱即用、带桌面原生体验（托盘/通知/开机自启/自动更新/UI 原生化/设备面板）。

本子项目**不含**远程中枢（设备注册、手机→电脑下发任务），留给子项目 B。

## 1. 已确认决策

| 项 | 决策 |
| --- | --- |
| 程序形态 | 单 NSIS 安装包：Electron 主程序（含 Web UI）为唯一用户入口 |
| Worker 运行时 | PyInstaller 打包为**单一 worker exe**（内含 os/computer/browser/wake 全部能力，super 入口按子命令启动对应服务），随安装包分发，用户免装 Python |
| 首版 worker 范围 | os / computer / browser / wake 全含 |
| 登录 | 内嵌 Web UI（复用完整登录页）；凭证存 Electron `safeStorage`（主进程加解密）+ localStorage 同步 Web UI |
| 原生能力 | 托盘 + 系统通知 + 开机自启 + 自动更新（electron-updater，服务器后续接入）+ UI 原生化（自绘标题栏）+ 设备面板完善 |
| 服务器地址 | 内置入口域名（编译常量）→ 首次请求后端 `/api/desktop-config` 获取/确认实际 API origin，缓存本机 |
| 设备注册 | 本子项目不做（子项目 B） |
| 目标平台 | Windows（NSIS）；架构预留 mac/linux |

## 2. 总体架构

```text
Electron 主进程（唯一安装/运行入口）
├─ server-config 模块
│    内置入口域名 → GET <入口>/api/desktop-config → 解析 { api_origin, app_name, ... }
│    → 缓存到 userData；preload 注入 renderer（window.__DESKTOP_CONFIG__）
├─ worker-host 模块
│    spawn 单一 worker exe（super 入口）→ 内部按需起 os(8765)/browser(8766)/computer(8767)/wake
│    监听退出/崩溃重启；状态暴露给 UI
├─ 本地桥 9876（已存在 bridge.js：/file /recycle /snapshot →8765，/browser→8766，/control→8767）
├─ 原生体验模块
│    托盘（关闭驻留/显示/退出）
│    系统通知（任务完成/worker 异常）
│    开机自启（app.setLoginItemSettings）
│    自动更新（electron-updater，手动/自动检查，服务器后接）
├─ 凭证模块
│    safeStorage 加密存取 access_token；与 Web UI localStorage 双向同步
└─ BrowserWindow（UI 原生化）
      └─ renderer = 完整 Web UI（dist）
           API base = window.__DESKTOP_CONFIG__.apiBase（而非 file:// origin）
```

## 3. 组件设计

### 3.1 server-config + 后端 desktop-config 接口

- 编译常量 `DESKTOP_ENTRY_ORIGIN`（如 `https://openllm.cloud`），打包注入。
- 首次启动：`GET {DESKTOP_ENTRY_ORIGIN}/api/desktop-config`（公开、无鉴权，返回轻量 JSON）：
  ```json
  { "ok": true, "data": { "app_name": "钰心AI", "api_origin": "https://openllm.cloud", "api_prefix": "/api" } }
  ```
  - 后端只需返回当前同源信息（api_origin 即请求 origin），供 UI 兜底与校验；不承载"切换服务器"。
  - 缓存在 `userData/server-config.json`；请求失败用缓存；无缓存则用编译入口 origin 兜底。
- **UI API base 注入**：现有 `ui/src/config/index.ts` 用 `VITE_API_PREFIX` 或 `location.origin+/api`。桌面端 `file://` 下 origin 为空 → 需支持运行时覆盖：
  - 新增读取 `window.__DESKTOP_CONFIG__?.apiBase ?? window.__DESKTOP_CONFIG__?.apiOrigin+prefix`，优先级最高（> VITE_API_PREFIX > location.origin）。
  - preload 通过 contextBridge 暴露 `desktopConfig`（主进程注入）。

### 3.2 单一 worker exe（PyInstaller）

- 新增 `api/scripts/worker_super.py`：argparse 子命令 `os|browser|computer|wake`，转发调用各 worker 的 `main()`（导入各自模块后调其 main/相应入口），统一日志前缀。
- PyInstaller spec：把 4 个 worker 模块 + super 打成一个 `yuxin-worker.exe`。
  - 隐藏导入（playwright、pyautogui、openwakeword 等动态导入依赖）在 spec 中显式声明。
  - browser worker 的 Chromium：PyInstaller 不打包浏览器二进制；`playwright install chromium` 的浏览器放 `userData/ms-playwright/` 或安装包 extraResources，worker 启动时 `PLAYWRIGHT_BROWSERS_PATH` 指向该处；若缺失，UI 引导首次下载（子项目 A 可先要求构建时预置，运行时缺失报清晰错误）。
  - wake worker（openWakeWord 模型文件）同理：模型放 extraResources 或 userData，`WAKE_WORD_MODEL_DIR` 指向。
- Electron 侧 `worker-host` 不再 `spawn python script.py`，改 `spawn(process.resourcesPath/yuxin-worker.exe, ["os", "--port", ...])`；开发模式（无 exe）回退 `python scripts/os_automation_worker.py`（保留现有 DESKTOP_PYTHON 逻辑）。
- 安全：worker 间随机 token 由主进程生成并注入 env（沿用现有 tokens 机制）；仅回环监听。

### 3.3 原生体验

- **托盘**：`Tray` + 菜单（显示主窗口/本机状态/退出）。关闭窗口默认隐藏到托盘（`close` 拦截），托盘"退出"才真退出并停 worker。
- **通知**：`new Notification()`——任务完成/worker 异常/自动更新可用时。
- **开机自启**：设置页开关 → `app.setLoginItemSettings({ openAtLogin })`（Windows）。启动后可 `--hidden` 最小化到托盘。
- **自动更新**：接入 `electron-updater`（`autoUpdater`），配置 `publish` 指向更新服务器（占位配置，服务器后接）；手动"检查更新"按钮 + 后台自动检查。
- **UI 原生化**：BrowserWindow `titleBarStyle: 'hidden'` + 自绘标题栏组件（window controls 经 preload IPC）；深色模式跟随 Web UI 主题。注意 Electron 33 的 `titleBarOverlay`。
- **设备面板完善**：现有 `DesktopDevicePanel.vue` 扩展——显示本机 worker 状态（os/browser/computer/wake 各自 running/版本）、回收站入口、快照/回滚入口、开机自启开关、检查更新按钮；经 preload 暴露新 IPC（`desktop:getWorkerStatus` 等）由主进程查询。

### 3.4 凭证存储

- 登录流程在 Web UI（内嵌）完成 → `credential` 写 localStorage（现有机制）。
- 主进程监听登录态变化（或 renderer 经 IPC 上报）→ 用 `safeStorage.encryptString(token)` 存 `userData/credential.bin`。
- 重启：主进程解密注入（renderer 启动时若 localStorage 无凭证则从主进程恢复）→ 保持登录态。
- 登出：两端清空。
- 说明：safeStorage 在 Windows 用 DPAPI（当前用户），可防其他用户读。

### 3.5 登录页与 Web UI 复用

- `desktop/main.js createWindow` 加载 `ui/dist/index.html`。**SPA 加载方式决策**：Web UI 路由当前用 `createWebHistory`（依赖服务器 rewrite），`file://` 下直接加载会导致刷新/深链 404。桌面端二选一，实施时以验证结果定：
  1. **推荐：自定义协议**（`protocol.handle('app', ...)` 服务 dist 静态文件），URL 形如 `app://bundle/index.html`，history 路由在协议内可用，且 `location.origin` 为 `app://bundle`（不干扰注入的 apiBase）；
  2. 备选：`loadFile` + 前端在桌面环境（检测 `window.__DESKTOP_CONFIG__`）改用 `createWebHashHistory`。
  两者都不依赖 `location.origin` 推断 API（桌面端一律用注入的 apiBase）。生产构建 `VITE_API_PREFIX` 不设。
- dev 模式：`VITE_DEV_SERVER_URL`（现有）连 Vite dev server。

## 4. 安全模型

| 面 | 措施 |
| --- | --- |
| worker | 主进程随机 Bearer token、仅 127.0.0.1 监听、renderer 不直连 worker（经 IPC/bridge） |
| 凭证 | safeStorage(DPAPI) 加密；登录/登出双向同步 |
| 服务器 | 入口域名编译常量；desktop-config 响应仅同源信息，UI 只信注入 apiBase |
| 文件能力 | 沿用自愈闭环（V4A 写前快照 / 回收站 / snapshot 回滚）+ 敏感读黑名单（worker 已实现） |
| 更新 | electron-updater 校验签名（正式版需代码签名证书；未签前本地/内测分发并提示） |

## 5. 分阶段实施（子项目 A 内部）

| 阶段 | 内容 | 交付 |
| --- | --- | --- |
| A1 worker exe | `worker_super.py` + PyInstaller spec + Electron 侧 worker-host 改 spawn exe（开发回退 python） | 单 worker exe 可跑 4 服务；Electron 托管它 |
| A2 服务器注入 | 后端 `/api/desktop-config` + UI config 运行时覆盖 + preload 注入 | 桌面端连真实 API 登录可用 |
| A3 原生体验 | 托盘/通知/开机自启/自动更新接入/窗口原生化 | 桌面软件基础体验 |
| A4 UI 原生化 + 设备面板 | 自绘标题栏 + DesktopDevicePanel 完善 + 设置集成 | UI 桌面化 + 本机状态可视化 |
| A5 构建分发 | NSIS 打包（worker exe 入 extraResources）、登录/登出/重启流程验证 | 可分发安装包 |

> A1 与 A2 可并行（互不依赖代码）；A3/A4 依赖 A2（需登录态）。A5 收尾。

## 6. 风险与对策

| 风险 | 对策 |
| --- | --- |
| Playwright/openWakeWord 打包体积与浏览器/模型分发 | Chromium/模型放 extraResources 或 userData 按需下载（不在 PyInstaller 内），运行时缺失给清晰引导 |
| PyInstaller 隐藏导入遗漏 | spec 显式声明 + 打包后冒烟（4 服务各起一次） |
| file:// 下 SPA 路由/API | 运行时 apiBase 注入 + `createWebHistory` 在 file:// 下退 `createWebHashHistory`（或 desktop 用自定义协议加载）——**实施时验证 hash history 兼容** |
| safeStorage 不可用（罕见） | 降级提示（Windows 一般可用） |
| NSIS 未签名触发 SmartScreen | 记录为已知限制；正式发布需代码签名证书 |
| 多 worker 端口冲突 | 主进程随机端口 + bridge 动态配置（保留现有 env 覆盖） |

## 7. 验证

- 单测：worker_super 子命令分发；server-config 解析/缓存；凭证加解密；托盘菜单逻辑。
- UI 单测：config 运行时覆盖（window.__DESKTOP_CONFIG__ 优先级）；DesktopDevicePanel 状态渲染。
- 手工：开发模式起 Vite → Electron dev 登录/登出/重启保持登录；PyInstaller 打包后 worker exe 跑 4 服务冒烟；NSIS 安装→启动→托盘→文件操作闭环。

## 8. 相关文档
- 登录路由化：`docs/superpowers/specs/2026-09-08-user-login-routing-design.md`
- 本机文件自愈闭环：`docs/research/local-file-snapshot-rollback-plan.md`
- 多通道路由愿景（含子项目 B 远程中枢方向）：`docs/research/desktop-sandbox-routing-plan.md`
