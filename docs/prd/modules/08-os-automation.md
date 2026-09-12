# 宿主机 OS 自动化

> 更新日期：2026-09-11（设备链路已打通）
>
> ✅ **实现状态（2026-09-11）**：本文描述的"用户端自然语言提出本机任务 → 平台 Agent 调用宿主机 worker"这条**服务端 → 宿主机方向**的链路**已打通**。桌面端登录后把本机 bridge 地址与随机 token 上报服务端（`desktop_device` 表，按账号存储），服务端经 `resolve_desktop_bridge(account_id, purpose=...)` 动态解析出该账号默认在线设备的 bridge，替代静态 `DESKTOP_BRIDGE_URL/TOKEN`；静态配置仍作回退。容器内 `host.docker.internal` 可达宿主机回环（已实测）。实现细节见 [product-vision.md §4.1](../product-vision.md)。
>
> **宿主壳关联**：本文描述的 `os_automation_worker.py`（及 browser/computer/wake worker）由桌面客户端托管与分发——Windows 桌面端以单一 `yujianwo-worker.exe`（PyInstaller + worker_super 子命令入口）随安装包携带，Electron 主进程 spawn 启动（开发模式回退 python 脚本）。桌面壳架构见 [09-desktop-client.md](./09-desktop-client.md)。

## 目标

让用户在钰见我 用户端自然语言提出本机文件操作任务（例如“读一下 C 盘的项目代码”“改一下配置并重启后回滚”），
由平台 Agent 调用宿主机自研 worker，在真实操作系统安全目录内执行读取、搜索、V4A 补丁修改、
回收站删除/恢复与写前快照回滚——纯 Python，不依赖外部 CLI。

## 架构

```text
用户端 / 首页助手
  → AssistantAgentService 挂载 os_file_task / os_recycle_bin / os_snapshot（内置工具）
     （构建期注入 requester=account_id；computer_action 同）
  → resolve_desktop_bridge(account_id, purpose="/file")
     ├─ 动态：desktop_device 表（该账号默认在线设备的 bridge_origin + 解密 token）
     └─ 回退：DESKTOP_BRIDGE_URL/TOKEN 或 OS_AUTOMATION_URL/TOKEN（静态）
  → 桌面端本地能力桥 desktop/bridge.js（127.0.0.1:9876）
  → 宿主机 os_automation_worker.py（api/scripts/os_automation_worker.py，HTTP 8765）
     ├─ /file      → read / search / V4A patch（preview 只读 dry-run；apply 写前快照）
     ├─ /recycle   → delete（移入回收站）/ list / restore / purge
     └─ /snapshot  → rollback_file / rollback_turn / list_snapshots
```

平台容器运行在 Docker 内，默认不直接接触宿主机磁盘。宿主机侧常驻轻量 HTTP worker，
以 `Bearer <OS_AUTOMATION_TOKEN>` 鉴权，所有文件操作限制在安全根目录内
（`OS_AUTOMATION_SAFE_ROOT`，缺省当前用户主目录）。

## 安全模型

1. worker 仅接受 `Authorization: Bearer <OS_AUTOMATION_TOKEN>` 的请求，缺省监听回环地址。
2. `/file` 的 V4A 补丁：
   - `mode=preview`：只读 dry-run——在临时副本上模拟补丁，校验路径/格式/可应用性，
     不修改真实文件、不删除文件、不移入回收站。响应仍携带 `approval_token` 仅为兼容旧客户端结构。
   - `mode=apply`：直接执行（**无需逐次人工确认**）。每次真实写文件前自动捕获写前快照
     （fail-closed：快照失败拒绝本次写）；删除类操作移入本机回收站（可恢复）。
3. **回滚兜底取代人工确认**：
   - 改错 → `os_snapshot` `rollback_file`（单文件）或 `rollback_turn`（按用户消息轮批量恢复）。
   - 误删 → `os_recycle_bin` `list` + `restore`。
   - 快照全存宿主机本机隐藏目录（`<safe_root>/.yujianwo_snapshots`），默认留存 7 天后 GC 清理。
4. `os_file_task` 已移出 `ToolPolicy._DEFAULT_HIGH_RISK_TOOL_NAMES`：Agent 修改本机文件不再弹
   高风险确认窗口（由快照+回收站自愈闭环兜底）。其余高风险工具（send_email/execute_code/
   browser_action/computer_action 等）仍走原确认链路。
5. **动作审计不放开**：os_file_task/os_recycle_bin/os_snapshot 的每次调用仍以
   AgentThought（AGENT_ACTION 事件，含谁/哪台设备/工具入参/结果）全程记录，
   与高风险名单解耦（名单只决定是否弹确认，不决定是否审计）。
6. 越界防护：任何路径先经 `_is_path_within`/`_resolve_safe_root` resolve 判定，dry-run 与
   apply 口径一致，含 `..` 段的越界路径一律拒绝。
7. **敏感读取黑名单**：写/删免确认放开后，读取面由 worker 读黑名单兜底——
   `/file` read/search 命中敏感路径（`~/.ssh` 私钥、`.env*` 密钥文件（`.env.example`
   除外）、`id_rsa`/`*.pem`/`*.pfx` 私钥类文件、浏览器凭据目录
   `User Data`/`Login Data`/`logins.json`/`key4.db`、`.aws`/`.kube`/`.gnupg`/`.npm`
   等凭据目录、`.yujianwo_recycle`/`.yujianwo_snapshots` 自管目录）直接拒绝且不读取内容；
   search 还会以 rg 排除 glob 跳过敏感目录与文件，敏感路径不进搜索结果。

## 环境变量

在 `api/.env` 配置：

```dotenv
OS_AUTOMATION_URL=http://host.docker.internal:8765
OS_AUTOMATION_TOKEN=replace-with-strong-token
OS_AUTOMATION_SAFE_ROOT=C:\Users\Administrator
OS_AUTOMATION_SNAPSHOT_RETENTION_DAYS=7
OS_AUTOMATION_SNAPSHOT_MAX_BYTES=52428800
```

宿主机 worker 启动：

```powershell
$env:OS_AUTOMATION_TOKEN="replace-with-strong-token"
python api/scripts/os_automation_worker.py --host 127.0.0.1 --port 8765
```

健康检查：

```powershell
curl.exe -H "Authorization: Bearer <token>" http://127.0.0.1:8765/health
```

## 平台工具

内置 `codex_os` provider 下三个工具已预挂载到首页助手（`assistant_agent_service`）：

- `os_file_task`：op=`read`（支持分页）/ `search`（ripgrep）/ `patch`（V4A）。
  `patch` 默认 `mode=apply` 直接修改（写前自动快照）；`mode=preview` 只读 dry-run 预检查。
  `approval_token` 为历史兼容字段，apply 已不校验。`requester`/`session_id`/`conversation_turn`
  由平台注入，`conversation_turn` 随写前快照写入 manifest，供 `rollback_turn` 按消息轮回滚。
- `os_recycle_bin`：op=`delete`（移入回收站，不物理删除）/ `list` / `restore` / `purge`。
  删除天然免确认（可恢复）。
- `os_snapshot`：op=`rollback_file` / `rollback_turn` / `list_snapshots`，管理写前快照并回滚。

## 验证

单元测试：

```bash
python -m pytest test/scripts/test_os_automation_worker.py \
  test/internal/core/tools/test_os_file_task_tool.py \
  test/internal/core/tools/test_os_snapshot_tool.py \
  test/internal/core/tools/test_os_recycle_bin_tool.py \
  test/internal/core/agent/test_tool_confirmation_integration.py \
  test/internal/core/agent/test_function_call_and_react_agent.py -q --no-cov
```

覆盖：preview 只读不落盘、apply 直接执行且写前自动快照、路径越界拒绝、回收站删除可恢复、
单文件/按轮批量回滚、GC 清理、os_file_task 免确认（不再弹确认卡）。
