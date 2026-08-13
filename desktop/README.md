# 钰心AI Windows 桌面端

Electron 壳复用现有 Vue3 Web UI，并托管本机能力 Worker：

- `os_automation_worker.py`：OS 自动化 + 本机回收站（`/recycle`）
- `browser_automation_worker.py`：浏览器自动化（Playwright）
- `computer_control_worker.py`：计算机控制（pyautogui）
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

## 安全模型

- 主进程为每个 Worker 生成随机 Bearer token，仅本机回环地址监听。
- 回收站删除（`os_recycle_bin`）可回滚，不要求确认弹窗；其余高风险动作仍按审批门处理。
- Renderer 不直接接触 Node/文件系统，只通过 `preload.js` 暴露的 IPC 调用。

## 与平台 API 对接

- 本地 Docker 部署：容器内通过 `http://host.docker.internal:<port>` 访问桌面 worker，
  端口固定为 OS=8765、Browser=8766、Computer=8767。
- 平台侧工具默认关闭：需在 `api/.env` 配置 `OS_AUTOMATION_URL`、
  `BROWSER_AUTOMATION_URL`、`COMPUTER_CONTROL_URL` 及对应 token，token 与桌面壳
  生成值保持一致（可由桌面壳写入 `desktop/local-workers.json` 后由部署脚本读取）。
- 纯本地运行（API 也在本机）：直接使用 `127.0.0.1` 端口。

桌面壳还启动一个统一本地能力桥（`bridge.js`，默认 `127.0.0.1:9876`）：

```text
POST /recycle  -> OS worker 8765/recycle
POST /browser  -> Browser worker 8766/browser
POST /control  -> Computer worker 8767/control
```

桥使用 `DESKTOP_BRIDGE_TOKEN` 鉴权，平台 API 只需配置一个 `DESKTOP_BRIDGE_URL`
即可访问全部本地能力。运行测试：`node --test desktop/test/bridge.test.js`。
