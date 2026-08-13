# Hermes 对齐能力部署与验证手册

本文档记录钰心AI 中 Hermes v0.20 对齐能力的部署方式：环境变量、webhook/worker
端点、真实平台凭证配置步骤与本地验证命令。所有能力都已通过单元/集成测试，
本节解决“接真实平台”的最后一步。

## 1. 环境变量

将 `api/.env.example` 中“IM 语音笔记（Hermes 对齐）”区块复制到 `api/.env`，
按平台填写。需要真实凭证的平台与用途：

| 变量 | 平台 | 用途 |
| --- | --- | --- |
| `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_CHANNEL_SECRET` | LINE | 下载语音、回复消息、webhook 签名校验 |
| `WHATSAPP_ACCESS_TOKEN` / `WHATSAPP_APP_SECRET` / `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | WhatsApp Cloud API | 媒体下载、回复、webhook 校验与订阅验证 |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_ENCRYPT_KEY` / `FEISHU_VERIFICATION_TOKEN` | 飞书/Lark | tenant token、语音下载、回复、事件校验 |
| `DINGTALK_APP_KEY` / `DINGTALK_APP_SECRET` / `DINGTALK_WEBHOOK_SECRET` | 钉钉 | 语音下载 token、加签校验、sessionWebhook 回复 |
| `GPT_TRANSCRIBE_ENABLED` / `GPT_TRANSCRIBE_MODEL` | 全局 ASR | 开启 gpt-transcribe 增强转写模型 |

## 2. Webhook 地址

以下端点在 Quart 应用启动后即可使用，平台回调地址需填公网可达 URL：

| 平台 | 端点 | 说明 |
| --- | --- | --- |
| LINE | `POST /im/line/webhook` | `X-Line-Signature` 校验（配置 `LINE_CHANNEL_SECRET` 后强制） |
| WhatsApp | `GET/POST /im/whatsapp/webhook` | GET 用于 `hub.verify_token` 订阅验证；POST 做 `X-Hub-Signature-256` 校验 |
| 飞书/Lark | `POST /im/feishu/webhook` | 支持 `url_verification` challenge；`X-Lark-Signature` 校验（配置 `FEISHU_ENCRYPT_KEY` 后强制） |
| 钉钉 | `POST /im/dingtalk/webhook?timestamp=...&sign=...` | 配置 `DINGTALK_WEBHOOK_SECRET` 后校验加签 |

## 3. 验证步骤

### 3.1 本地单测

```bash
cd api
python -m pytest --no-cov \
  test/internal/service/test_im_voice_service.py \
  test/app/http/test_im_voice_routes.py
```

### 3.2 飞书快速验证

```bash
curl -X POST http://127.0.0.1:5001/im/feishu/webhook \
  -H "Content-Type: application/json" \
  -d '{"type":"url_verification","challenge":"challenge-1"}'
```

应返回 `{"challenge":"challenge-1"}`。正式事件用平台控制台发送一条语音消息，
观察日志与机器人回复。

### 3.3 WhatsApp 订阅验证

```bash
curl "http://127.0.0.1:5001/im/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=<WHATSAPP_WEBHOOK_VERIFY_TOKEN>&hub.challenge=challenge-1"
```

应原样返回 `challenge-1`。

### 3.4 钉钉

- 钉钉：在钉钉开放平台配置机器人回调地址为公网 `POST /im/dingtalk/webhook`，
  按安全设置生成 `DINGTALK_WEBHOOK_SECRET`；发送语音后观察回复。

### 3.5 本机回收站安全删除

OS worker 已内置 `/recycle` 端点，平台侧使用 `os_recycle_bin` 工具：

```bash
curl -X POST http://127.0.0.1:8765/recycle \
  -H "Authorization: Bearer $OS_AUTOMATION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"op":"delete","paths":["C:/Users/you/Desktop/tmp.txt"],"reason":"清理临时文件"}'
```

删除会移入 `OS_AUTOMATION_SAFE_ROOT/.yuxin_ai_recycle` 并记录清单；`op=list`
按关键词检索，`op=restore` 恢复原处（冲突自动加后缀）。一次误删多文件时，
删除阶段统一传入同一个 `task_id`，恢复时按 `task_id` 批量找回：

```json
{"op":"restore","task_id":"task-batch"}
```

条目默认留存 30 天（`retention_days` 可配），到期后可用 `op=purge` 物理清理：

```json
{"op":"purge"}
```

## 5. 已知边界

- Photon 是 Hermes 私有端到端语音协议，钰心AI 无对应平台，不提供适配器。
- 设备端唤醒词依赖本地麦克风常驻监听，Web 形态不适配，使用“按住说话”替代。
- webhook 签名变量未配置时默认跳过校验（便于本地联调），生产环境务必配置。

## 6. 浏览器自动化（默认关闭）

平台工具 `browser_action` 默认关闭，未配置 URL/token 时返回明确错误。启用步骤：

```bash
pip install playwright
playwright install chromium
cd api
set BROWSER_AUTOMATION_TOKEN=strong-token
python scripts/browser_automation_worker.py
```

在 `api/.env` 配置：

```dotenv
BROWSER_AUTOMATION_URL=http://127.0.0.1:8766
BROWSER_AUTOMATION_TOKEN=strong-token
```

worker 仅接受 Bearer token，拒绝 localhost/私网 URL（SSRF 防护），每次请求使用独立
browser context。`browser_action` 已列入高风险工具，调用前需要授权确认。

Docker 部署：`llmops-browser-worker` 使用 `Dockerfile.worker` 镜像，随
`--profile local-workers` 启动后，API 内通过 `http://llmops-browser-worker:8766` 访问。

## 7. 计算机控制（默认关闭）

平台工具 `computer_action` 默认关闭，启用步骤：

```bash
pip install pyautogui pillow
cd api
set COMPUTER_CONTROL_TOKEN=strong-token
python scripts/computer_control_worker.py
```

在 `api/.env` 配置：

```dotenv
COMPUTER_CONTROL_URL=http://127.0.0.1:8767
COMPUTER_CONTROL_TOKEN=strong-token
```

worker 仅接受 Bearer token，动作经过白名单与参数范围校验，不提供任意 shell；
截图默认不返回内容（可显式请求）。`computer_action` 已列入高风险工具。

Docker 部署：`llmops-computer-worker` 使用 `Dockerfile.worker` 镜像（xvfb-run），随
`--profile local-workers` 启动后，API 内通过 `http://llmops-computer-worker:8767` 访问。

## 8. 桌面本地能力桥

Windows 桌面壳会启动统一本地桥（`desktop/bridge.js`，`127.0.0.1:9876`）：

- `POST /recycle` -> OS worker `/recycle`
- `POST /browser` -> Browser worker `/browser`
- `POST /control` -> Computer worker `/control`

平台 API 配置 `DESKTOP_BRIDGE_URL=http://127.0.0.1:9876` 与 `DESKTOP_BRIDGE_TOKEN`
即可统一接入回收站/浏览器/计算机控制；`os_recycle_bin` / `browser_action` /
`computer_action` 已优先读取桥地址与 token。桥测试：

```bash
node --test desktop/test/bridge.test.js
```

## 9. Docker Worker 重构与构建

新增文件：

- `api/requirements-workers.txt`：browser/computer worker 可选依赖（playwright、
  pillow、pyautogui；唤醒词依赖按真机需要追加）。
- `api/Dockerfile.worker`：worker 专用镜像，安装 Chromium 与 GUI 依赖。
- compose 新增 `llmops-browser-worker` / `llmops-computer-worker`
  （`profiles: ["local-workers"]`）。
- worker 镜像只装 `requirements-workers.txt`（playwright/pillow/pyautogui）与
  Chromium，不再重复安装完整 API 依赖；浏览器 worker 使用 `--with-deps` 自动补齐运行库。
- browser/computer worker 默认使用开发 token（`dev-browser-worker-token` /
  `dev-computer-worker-token`），生产环境请在 `api/.env` 覆盖。

让修改生效：

```bash
cd docker
docker compose --profile local-workers up -d --build \
  llmops-browser-worker llmops-computer-worker
```

重建后 API 容器通过 env 读取 `BROWSER_AUTOMATION_URL` / `COMPUTER_CONTROL_URL`，
容器内推荐使用服务名（`http://llmops-browser-worker:8766` 等）。

验证：API `healthz` 返回 200；浏览器/计算机 worker 对带默认 token 的请求返回
参数校验结果（如 `navigate 操作需要 url` / `actions 不能为空`），说明已可达。
