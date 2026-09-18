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

`npm run pack` / `npm run dist` 会用 `scripts/stage-render-runtime.js` 暂存渲染运行时，
需要两个环境变量：

| 变量 | 作用 |
| --- | --- |
| `RENDER_RUNTIME_SOURCE_DIR` | 运行时源目录（含 `node_modules`）。**从 `llmops-render-worker` 容器提取**，保证与云端版本同源 |
| `RENDER_RUNTIME_WIN32_MODULES_DIR` | Windows 侧 `hyperframes` 的 `node_modules`，用于补齐 win32 原生包 |
| `ORT_PLATFORMS` | 可选，`onnxruntime-node` 保留的平台，默认 `win32` |

```bash
# 1) 从容器导出运行时（node_modules 同源；Chromium/ffmpeg/ffprobe 另用 Windows 构建）
docker cp llmops-render-worker:/opt/hyperframes/node_modules <staging>/node_modules
export RENDER_RUNTIME_SOURCE_DIR=<staging>

# 2) Windows 侧装同版本 hyperframes，取其原生包
mkdir -p <win32-staging> && cd <win32-staging>
npm init -y && npm install hyperframes@0.8.42 --no-audit --no-fund
export RENDER_RUNTIME_WIN32_MODULES_DIR=<win32-staging>/node_modules
```

> ⚠️ **`RENDER_RUNTIME_WIN32_MODULES_DIR` 不可省略**：容器内 `node_modules` 只有 linux 原生包
> （`@esbuild/linux-x64`、`@img/sharp-linux-x64`、`@img/sharp-libvips-linux-x64`），
> 而 HyperFrames 的 `dist/cli.js` **在启动阶段就 eager import `sharp`**，缺 win32 构建时
> 安装版连 `hyperframes --version` 都会崩（实测报 `Could not load the "sharp" module using
> the win32-x64 runtime`）。暂存脚本会裁掉 linux 包并 overlay win32 包，
> **并在缺失时报错终止打包**，不会静默产出「渲染必崩」的安装包。
> 注意 `onnxruntime-node` 不受影响——它走 N-API v3 多平台布局，一份即可跨平台。

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
