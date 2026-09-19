# 钰见我 Windows 桌面端

Electron 壳复用现有 Vue3 Web UI，并托管本机能力 Worker：

- `os_automation_worker.py`：OS 自动化 + 本机回收站（`/recycle`）
- `browser_automation_worker.py`：浏览器自动化（Playwright）
- `computer_control_worker.py`：计算机控制（pyautogui）
- `render_worker.py`：本机视频渲染出片（HyperFrames CLI + Chromium + ffmpeg）
- `wake_word_worker.py`：本地唤醒词（openWakeWord）

## 开发

```bash
cd ui && npm install && npm run dev
cd ../desktop && npm install
set DESKTOP_PYTHON=python
npm run dev
```

## 构建

```bash
cd ui && npm run build
cd ../desktop && npm run dist
```

产物在 `desktop/dist/`。首次使用需在桌面前置环境安装 Python 依赖：

```bash
pip install sounddevice numpy openwakeword pyautogui pillow
playwright install chromium
```

> 上述依赖仅针对 Python worker（OS/浏览器/计算机控制/唤醒词）。**本机渲染不需要用户安装
> Node 或 Python 依赖**：`render-runtime.js` 会生成 `hyperframes.cmd` shim，用 Electron 内置的
> Node（`ELECTRON_RUN_AS_NODE=1`）驱动 HyperFrames CLI；Chromium/ffmpeg/ffprobe 随安装包分发到
> `resources/render-runtime/`，无需用户额外配置。

### 渲染运行时的打包前置（仅打包机需要，**不是**用户侧）

`npm run pack` / `npm run dist` 会用 `scripts/stage-render-runtime.js` 暂存渲染运行时。
缺失/不达标时脚本会**报错终止打包**，不会静默产出「渲染必崩」的安装包。

| 变量 | 必填 | 作用 |
| --- | --- | --- |
| `RENDER_RUNTIME_SOURCE_DIR` | ✅ | 运行时源目录（含 `node_modules`）。**从 `llmops-render-worker` 容器提取**，保证与云端 `hyperframes` 同源 |
| `RENDER_RUNTIME_WIN32_MODULES_DIR` | ✅ | Windows 侧 `hyperframes` 的 `node_modules`，用于补齐 win32 原生包 |
| `RENDER_RUNTIME_BROWSER_DIR` | ✅ | 含 `chrome-headless-shell.exe` 的**目录**（非单文件） |
| `RENDER_RUNTIME_FFMPEG_PATH` | ✅ | 自包含 ffmpeg 的 exe 路径 |
| `RENDER_RUNTIME_FFPROBE_PATH` | ✅ | 同构建的 ffprobe exe 路径 |
| `ORT_PLATFORMS` | ❌ | `onnxruntime-node` 保留的平台，默认 `win32` |
| `RENDER_RUNTIME_SKIP_BINARY_PROBE` | ❌ | 置 `1` 跳过 ffmpeg 能力探测（仅排障用，勿用于正式打包） |

```bash
# 1) 从容器导出 node_modules（与云端同源）
docker cp llmops-render-worker:/opt/hyperframes/node_modules <staging>/node_modules
export RENDER_RUNTIME_SOURCE_DIR=<staging>

# 2) Windows 侧装同版本 hyperframes，取 win32 原生包
mkdir -p <win32-staging> && cd <win32-staging>
npm init -y && npm install hyperframes@0.8.42 --no-audit --no-fund
export RENDER_RUNTIME_WIN32_MODULES_DIR=<win32-staging>/node_modules

# 3) Win32 Chromium / ffmpeg / ffprobe
export RENDER_RUNTIME_BROWSER_DIR=<.../chromium_headless_shell-1237/chrome-headless-shell-win64>
export RENDER_RUNTIME_FFMPEG_PATH=<.../ffmpeg.exe>
export RENDER_RUNTIME_FFPROBE_PATH=<.../ffprobe.exe>
```

**二进制获取（版本钉死，保证可复现）**：

```powershell
# Chromium：用 playwright 的 chrome-headless-shell（需能响应 --version）
npx playwright install chromium-headless-shell

# ffmpeg / ffprobe：gyan.dev essentials 自包含构建（**必须钉死版本号**）
#   ⚠️ 不要用 .../ffmpeg-release-essentials.zip —— 那是滚动最新版，下次打包会拿到不同版本
$ver = '9.0.1'
Invoke-WebRequest "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-$ver-essentials_build.zip" -OutFile ffmpeg.zip
Expand-Archive ffmpeg.zip -DestinationPath ffmpeg
# → ffmpeg-<ver>-essentials_build/bin/{ffmpeg.exe,ffprobe.exe}
```

> 实测可用组合与体积：Chromium `152.0.7977.x`（约 200 MB 主程序 + 68 MB 旁挂文件）、
> ffmpeg/ffprobe `9.0.1` 静态构建（**各约 98 MB**）。
> 打入的版本会写入 `resources/render-runtime/MANIFEST.json` 便于与容器比对。

**三个实测踩坑（对应脚本内的防护逻辑，勿绕过）**：

1. **容器 `node_modules` 不是全平台**。容器内只有 `@esbuild/linux-x64`、`@img/sharp-linux-x64`、
   `@img/sharp-libvips-linux-x64`，而 `hyperframes/dist/cli.js` **在启动阶段就 eager import `sharp`**，
   直接打包会让 Windows 上连 `hyperframes --version` 都崩
   （`Could not load the "sharp" module using the win32-x64 runtime`）。脚本会裁掉 linux 包、
   overlay win32 包并断言其存在。`onnxruntime-node` 不受影响（N-API v3 多平台布局）。
2. **Chromium 不是单文件**。`chrome-headless-shell.exe` 依赖同目录的 `icudtl.dat` / `*.pak` / `*.dll`，
   只拷 exe 会在启动时直接崩（实测退出码 `0x80000003`）。脚本整目录复制并校验必需文件。
3. **ffmpeg 需要三项能力**：`image2pipe` 解复用 + `mjpeg` 解码 + `libx264` 编码。
   实测缺 `image2pipe` 报 `Unknown input format: 'image2pipe'`；缺 `libx264` 无法编码。
   脚本暂存后做能力探测，不达标即终止打包。

> **版本说明**：Chromium / ffmpeg 必须用 **Windows 构建**，与容器内的 Debian 构建版本号
> 不可能完全相同（容器基准：Chromium 152.0.7977.82、ffmpeg 5.1.9-0+deb12u1）。
> 实测可用的组合：`chromium_headless_shell`（Google Chrome for Testing 152.x）+
> gyan.dev essentials 自包含 ffmpeg/ffprobe。实际打入的版本会记入
> `resources/render-runtime/MANIFEST.json` 便于比对。

> **⚠️ `extraResources` 的 `node_modules` 必须拆成独立条目**（已配置，勿合并回去）：
> electron-builder 会**无条件剔除**匹配器**根部**的 `node_modules`
> （见 app-builder-lib `util/filter.js`：`if (relative === "node_modules") return false`）。
> 若把 `vendor/render-runtime` 作为单一条目传入，`node_modules` 会整棵丢失，
> 结果就是「`npm start` 正常、安装版渲染必崩」。故 `desktop/package.json` 中
> `render-runtime`（含 `filter: ["**/*","!node_modules/**"]`）与
> `render-runtime/node_modules` 是**两条独立** `extraResources`。
> 打包后可用 `desktop/dist-nsis/win-unpacked/resources/render-runtime/node_modules/hyperframes/dist/cli.js`
> 是否存在来快速自检。

**体积与可选瘦身**：暂存产物实测约 **687 MB**（node_modules 222 MB + Chromium 268 MB + ffmpeg/ffprobe 196 MB）。
其中 `locales/`（42 MB）与 `hyphen-data/` 实测**非必需**（渲染链路不读它们），
如需瘦身可在 `stage-render-runtime.js` 的 `stageBrowser` 里按需跳过；当前为降低风险默认保留。

> **`onnxruntime-node` 属「已提供能力但未接入」**：它已随包分发（含 win32 裁剪，供后续
> 图片处理 / 抠像使用），但**当前全仓无任何生产调用点**。请勿据此认为「图片处理已实现」。

## 安全模型

- 主进程为每个 Worker 生成随机 Bearer token，仅本机回环地址监听。
- 回收站删除（`os_recycle_bin`）可回滚，不要求确认弹窗；其余高风险动作仍按审批门处理。
- Renderer 不直接接触 Node/文件系统，只通过 `preload.js` 暴露的 IPC 调用。

## 与平台 API 对接

- 本地 Docker 部署：容器内通过 `http://host.docker.internal:<port>` 访问桌面 worker，
  端口固定为 OS=8765、Browser=8766、Computer=8767、Render=8768。
- 平台侧工具默认关闭：需在 `api/.env` 配置 `OS_AUTOMATION_URL`、
  `BROWSER_AUTOMATION_URL`、`COMPUTER_CONTROL_URL` 及对应 token，token 与桌面壳
  生成值保持一致（可由桌面壳写入 `desktop/local-workers.json` 后由部署脚本读取）。
- 纯本地运行（API 也在本机）：直接使用 `127.0.0.1` 端口。

桌面壳还启动一个统一本地能力桥（`bridge.js`，默认 `127.0.0.1:9876`）：

```text
POST /file      -> OS worker 8765/file
POST /recycle   -> OS worker 8765/recycle
POST /snapshot  -> OS worker 8765/snapshot
POST /browser   -> Browser worker 8766/browser
POST /control   -> Computer worker 8767/control
POST /render    -> Render worker 8768/render
POST /artifact  -> Render worker 8768/artifact
```

桥使用 `DESKTOP_BRIDGE_TOKEN` 鉴权，平台 API 只需配置一个 `DESKTOP_BRIDGE_URL`
即可访问全部本地能力。运行测试：`node --test desktop/test/bridge.test.js`。

> 服务端侧（`api/internal/service/desktop_bridge_resolver.py`）按账号动态解析桥地址与随机 token，
> 渲染工具（`local_render_runner`）经 `resolve_desktop_bridge(account_id, purpose="/render")`
> 取桥，再打 `/render` 出片、`/artifact` 取回产物。桌面端 token 每次启动随机生成，
> 静态 `DESKTOP_BRIDGE_*` 仅作回退，**不要只依赖静态 env**。
