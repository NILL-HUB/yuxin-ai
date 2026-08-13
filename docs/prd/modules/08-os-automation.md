# 宿主机 Codex OS 自动化

## 目标

让用户在钰心AI 用户端自然语言提出系统自动化任务（例如“帮我清理 C 盘垃圾”），
由平台 Agent 调用宿主机 Codex，在真实操作系统上先预览、再经用户确认后执行。

## 架构

```text
用户端 / 首页助手
  → AssistantAgentService.run_os_task（内置工具）
  → API 容器（OS_AUTOMATION_URL / OS_AUTOMATION_TOKEN）
  → 宿主机 OS automation worker（api/scripts/os_automation_worker.py）
  → Codex CLI（宿主机真实系统）
```

平台容器运行在 Docker 内，默认不直接接触宿主机 C 盘。因此需要宿主机侧
常驻一个轻量 HTTP worker，只做“受保护地调用 Codex”这一件事。

## 安全模型

1. worker 仅接受 `Authorization: Bearer <OS_AUTOMATION_TOKEN>`。
2. 每次任务先 `preview`：Codex 生成影响计划和命令，worker 返回一次性
   `approval_token`。
3. `apply` 必须携带同一个 `approval_token`，且 token 5 分钟内有效、成功后作废。
4. `preview` 使用 Codex `danger-full-access` 但提示词强制只读；Windows 的
   Codex CLI 不支持 read-only 沙箱，因此真正的执行门禁由 approval_token 承担。
5. `apply` 使用 `--dangerously-bypass-approvals-and-sandbox`，因为平台侧
   已经完成“预览 + 用户确认”。

## 环境变量

在 `api/.env` 配置：

```dotenv
OS_AUTOMATION_URL=http://host.docker.internal:8765
OS_AUTOMATION_TOKEN=replace-with-strong-token
CODEX_CLI_PATH=C:\Users\Administrator\AppData\Local\OpenAI\Codex\bin\8e8bf206e63ac436\codex.exe
```

宿主机 worker 启动：

```powershell
$env:OS_AUTOMATION_TOKEN="replace-with-strong-token"
$env:CODEX_CLI_PATH="C:\...\codex.exe"
python api/scripts/os_automation_worker.py --host 0.0.0.0 --port 8765
```

健康检查：

```powershell
curl.exe -H "Authorization: Bearer <token>" http://127.0.0.1:8765/health
```

## 平台工具

内置工具 `codex_os.run_os_task` 已预挂载到首页助手：

- 参数 `task`：自然语言任务描述。
- 参数 `mode`：`preview` / `apply`。
- 参数 `approval_token`：`preview` 返回，`apply` 必须携带。
- 参数 `working_dir`：宿主机工作目录，默认用户主目录。
- 参数 `requester`：由平台自动注入账号 ID，用于审计。

工具名 `run_os_task` 被加入 `ToolPolicy.high_risk_tool_names`，Agent 调用时
会进入现有高风险工具确认链路，避免无提示执行。

## 验证

单元测试：

```bash
python -m pytest test/scripts/test_os_automation_worker.py \
  test/internal/core/tools/test_codex_os_tool.py -q
```

真实全链路 E2E（需要本机 Codex CLI）：

```powershell
$env:OS_AUTOMATION_TOKEN="dev-os-automation-token-2026"
$env:CODEX_CLI_PATH="$env:LOCALAPPDATA\OpenAI\Codex\bin\8e8bf206e63ac436\codex.exe"
python api/scripts/test_os_automation_e2e.py
```

E2E 会验证：worker 健康检查 → Codex preview 返回计划与 approval_token →
apply 在临时目录真实创建文件并校验内容。
