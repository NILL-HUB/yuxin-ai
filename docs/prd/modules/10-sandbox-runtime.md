# 沙箱运行时：admin 统一配置与多后端热切换

> 状态：**已落地（2026-09-29）**。本文档为沙箱配置与执行的权威说明。
> 设计来源：[沙箱配置治理与多后端热切换设计](../../archive/superpowers-specs/2026-09-29-sandbox-config-multi-backend-design.md)（已落地归档）。

## 1. 定位与目标

沙箱是**代码/命令隔离执行**的底座，服务三类能力域（capability）：

| capability | 典型消费方 | 说明 |
| --- | --- | --- |
| `code_interpreter` | 深度思考（DeepThinkingAgent）、builtin 工具 `execute_code` | E2B 协议沙箱（百度 CFC / 官方 E2B 云） |
| `skill_exec` | 技能包同步与执行（`SkillScfClient` / `SkillSandboxExecutor`） | HTTP 远端执行服务 或 E2B 协议沙箱 |
| `workflow_code` | 工作流 Python 代码节点（`CodeNode`） | HTTP 远端执行服务 |

设计目标（对齐 `/admin/storage` 的存储源热切换范式）：

1. 沙箱配置**入库**、admin 可编辑 / 可切换 / 可观测；
2. **多后端** + **按能力域热切换**（切换只影响新会话）；
3. 收编历史「14 处散读 env」到**单一权威入口**；
4. 未配置时**显式**表达"未开通"，不静默降级；
5. **接入新沙箱只需沿主干延伸分支**（见 §7）。

> 密钥口径（2026-09-29 更新）：`E2B_API_KEY` / `E2B_DOMAIN` 等沙箱凭据现由管理员在 `/admin/sandbox` 配置，
> **加密入库** `sandbox_config.credentials`（Fernet，键=env 名），运行时经 `resolve_credentials`「DB 解密优先 → env 兜底」读取，
> 接口只回掩码。DB 为空时行为与升级前逐字节一致。与工具凭证（`builtin_tool_provider.credentials`）同口径。

## 2. 数据模型

表 `sandbox_config`（模型 `api/internal/model/sandbox_config.py`，迁移 `k5a6b7c8d9e0` / `n8d9e0f1a2b3`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | uuid pk | |
| `capability` | varchar(32) | `code_interpreter` / `skill_exec` / `workflow_code` |
| `backend` | varchar(32) | `baidu_cfc` / `e2b_cloud` / `http_sandbox` / `disabled` |
| `label` | varchar(64) | 展示名 |
| `configs` | jsonb | **白名单键**（模板名/超时/endpoint），**不含密钥** |
| `credentials` | jsonb | 后端凭证（**加密**，键=env 名，如 `E2B_API_KEY`）；键清单由 `_ALLOWED_CREDENTIAL_KEYS` 代码声明 |
| `is_active` | boolean | 同 capability 内同一时间仅一行为 true |
| `created_at` / `updated_at` | timestamp | |

约束：`UNIQUE (capability, backend)`；`INDEX (capability, is_active)`。

**为什么按能力域分组**（而非像 storage 全局单一 active）：代码解释器（E2B 协议）与技能/工作流的 HTTP 执行服务是**不同协议**，不可能共用一个后端；每个 capability 各自一个 active。

### 能力域允许的后端（`CAPABILITY_BACKENDS`）

```python
code_interpreter: (baidu_cfc, e2b_cloud, disabled)
skill_exec:       (http_sandbox, baidu_cfc, disabled)
workflow_code:    (http_sandbox, disabled)
```

### 配置键白名单（`SandboxConfigService._ALLOWED_CONFIG_KEYS`）

| backend | 允许入库的键 |
| --- | --- |
| `baidu_cfc` | `template_alias`、`fallback_template_alias`、`profile`、`execute_timeout_seconds`、`sandbox_timeout_seconds`、`allow_local_exec` |
| `e2b_cloud` | `template_alias`、`execute_timeout_seconds`、`sandbox_timeout_seconds` |
| `http_sandbox` | `endpoint`、`timeout_seconds`、`allow_local_exec` |
| `disabled` | （无） |

## 3. 单一权威入口（核心链路）

```
admin（/admin/sandbox，AdminSandboxView.vue）
   │  写：POST /admin/sandbox/configs/<capability>/<backend>、POST /admin/sandbox/activate
   ▼
sandbox_config 表
   │  读（唯一权威）：SandboxConfigService.resolve_runtime(capability) -> SandboxRuntime（纯数据）
   ▼
sandbox_runtime_registry（core，进程内 TTL 缓存，默认 10s）
   │  get_sandbox_runtime(capability)  <-- core 侧唯一读取点（core 不读 DB / 不读 env）
   ▼
backends/factory.build_sandbox_backend(runtime)  -> 后端句柄 / None
   ▼
消费方：DeepThinkingAgent / execute_code / CodeNode / SkillExecutor / SkillSandboxExecutor
   └─ HTTP 后端（http_sandbox）：唯一传输入口 = HttpSandboxHandle.execute(payload)
```

关键组件：

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| `SandboxRuntime` | `api/internal/core/agent/entities/sandbox_runtime_entity.py` | 跨层纯数据契约（`capability` / `backend` / `configs` / `enabled` / `reason`）+ 能力域与后端常量 |
| `SandboxConfigService` | `api/internal/service/sandbox/sandbox_config_service.py` | 唯一权威读取入口 `resolve_runtime`；`upsert_config` / `set_active_backend` / `ensure_default_config` / `overview` / `probe`；无 DB 记录时回退 env 判定（迁移期零变化） |
| 运行时注册表 | `api/internal/core/agent/sandbox_runtime_registry.py` | 弥合「core 无 DB」与「service 有 DB」：**每个会执行沙箱的进程**在入口注册 `register_sandbox_runtime_loader(service.resolve_runtime)`（API：`app.py` 启动初始化；Celery worker：`celery_app._ensure_runtime()`）；core 经 `get_sandbox_runtime(capability)` 读取（TTL 缓存）。未注册时按「未开通」返回并打一次 WARNING |
| 后端工厂 | `api/internal/core/agent/backends/factory.py` | `build_sandbox_backend(runtime)`；`register_sandbox_backend(name, builder)` 是**接入新后端的唯一扩展点** |
| HTTP 传输句柄 | `api/internal/core/agent/backends/factory.py` `HttpSandboxHandle` | HTTP 后端的**唯一传输入口**：`execute(payload)` = 向 endpoint 发一次请求并回传解析后的 JSON（含云函数网关 `body` 解包），统一收敛 endpoint 校验 / 超时 / 状态码 / 非 JSON / 网络异常。**不是 `BaseSandbox`**（HTTP 无 shell/文件系统语义），故消费方各自构造 payload、但不再各自 `requests.post` |
| 技能执行入口 | `api/internal/core/skills/skill_executor.py` `SkillExecutor` | 技能执行的**单一入口**：按 `skill_exec` 的 active 后端选协议（`http_sandbox` → `SkillScfClient`；`baidu_cfc`/`disabled` → `SkillSandboxExecutor`）。**决策只在此一处**——此前藏在 `SkillToolFactory` 的 try/except 里，导致 E2B 模式每次刷伪警告、双失败时吞掉原始错误 |
| 占位符判定 | `api/internal/core/agent/backends/endpoint_utils.py` | `is_placeholder_endpoint`（历史 `_is_placeholder_url` 的唯一副本） |

## 4. 管理端

- 后端路由：`api/app/http/admin_routes_7.py`，5 个端点
  - `GET  /admin/sandbox/overview`：各 capability 的 active 后端 / 可用性 / 原因 / 配置 / 候选项
  - `GET  /admin/sandbox/configs`：列出全部配置行
  - `POST /admin/sandbox/configs/<capability>/<backend>`：upsert（`configs` 白名单过滤；`credentials` 白名单键**加密入库**，空值表示清除，不传则保持既有凭证）
  - `POST /admin/sandbox/activate`：body `{capability, backend}`，同 capability 内互斥置位
  - `POST /admin/sandbox/probe`：body `{capability}`，返回配置层可用性判定与原因
- 权限：`sandbox:read` / `sandbox:update`（`api/internal/core/rbac.py` 的 `PERMISSION_CATALOG`；viewer 默认持有 `sandbox:read`）；映射在 `api/app/http/support.py` 的 `_admin_route_permission`
- 前端：`ui/src/views/admin/AdminSandboxView.vue`（卡片式后端选择 + 激活 + 探测 + 配置键值编辑）；**保存仅同步单个卡片**（不整页重建，保留其它卡片未保存草稿与当前选择），保存非激活后端时提示需「设为激活」才生效；`ui/src/services/admin-sandbox.ts`、`ui/src/models/admin-sandbox.ts`、`ui/src/i18n/messages/{zh-CN,en-US}/admin/sandbox.ts`；菜单在 `AdminLayout.vue` 系统配置组

## 5. 热切换语义

- **会话粒度**：切换后**新会话**走新后端；**运行中会话**绑定自身后端直到结束。
- **生效路径**：`upsert_config` / `set_active_backend` 调用 `invalidate_sandbox_runtime_cache()` → **本进程立即生效**；其他 worker 依赖注册表 **TTL（默认 10s）** 自动跟进，无需重启。
- **进程注册（TTL 跟进的前提）**：各执行进程必须先注册加载器——API 进程在 `app.py` 启动初始化注册，Celery worker 在 `celery_app._ensure_runtime()` 注册（每个 pool worker 子进程各注册一次）。**新增执行进程必须补注册**；未注册进程恒返回「未开通」并打一次 WARNING。历史断链（2026-10-04 修复）：注册曾与 `ensure_default_config` 一起被限定在 `MODE != "celery"` 分支，Celery worker 从未注册，导致定时任务/后台 Agent 的沙箱恒不可用、admin 保存与切换全部不生效。
- **保存与激活分离**：`POST /configs/<capability>/<backend>`（保存配置）只写配置/凭证，**不会**切换激活后端；切换必须调 `POST /activate`。前端保存非激活后端时会提示「尚未激活，点击设为激活后生效」，避免"保存成功即已切换"的误解。
- **无需迁移**：沙箱每次执行新建会话，无存量数据（比 storage 简单，无 `migration` 端点）。
- **切换安全**：写入走 `auto_commit`；可先 `probe` 校验目标后端再切换；切换仅影响新会话，可随时切回。

## 6. 消费方接线（每个新调用都必须经此入口）

| 消费方 | 位置 | 接线方式 |
| --- | --- | --- |
| 深度思考 | `api/internal/core/agent/agents/deep_thinking_agent.py` `_build_deep_agent` | `get_sandbox_runtime("code_interpreter")` → `build_sandbox_backend(runtime)` |
| 代码执行工具 | `api/internal/core/tools/builtin_tools/providers/code_execution_tool/execute_code.py` | 同上；启用位 = 工具开关 `ENABLE_CODE_EXECUTION_TOOL` **且** `runtime.enabled` |
| 工作流代码节点 | `api/internal/core/workflow/nodes/code/code_node.py` | `get_sandbox_runtime("workflow_code")` → `build_sandbox_backend(runtime)` → `HttpSandboxHandle.execute(payload)` |
| 技能执行（单一入口） | `api/internal/core/skills/skill_executor.py` `SkillExecutor` | 按 `skill_exec` active 后端分发：`http_sandbox` → `SkillScfClient`；`baidu_cfc`/`disabled` → `SkillSandboxExecutor`。`SkillToolFactory`（工具展开）只委托它执行，不再自带 try/fallback |
| 技能 SCF 客户端 | `api/internal/core/skills/skill_executor.py` `SkillScfClient` | `build_sandbox_backend(get_sandbox_runtime("skill_exec"))` → `HttpSandboxHandle.execute(payload)`（显式 `endpoint` 可覆盖，供测试）；另承担 `sync_package`（技能包同步，纯 HTTP，与执行协议无关） |
| 技能沙箱执行器 | `api/internal/core/skills/skill_executor.py` `SkillSandboxExecutor` | `build_sandbox_backend(runtime)`；仅 `backend == baidu_cfc` 时走远端（HTTP 后端由 `SkillScfClient` 承担）；`disabled` 时走「未开通 / `allow_local_exec`」分支 |

> **不再散读 env**：收编后 `grep -rn "E2B_\|SANDBOX_" api/internal --include=*.py` 仅剩工厂 / 服务层 / 后端 SDK 作用域注入。

### 时间下限保护

`code_interpreter` 的超时保留历史下限（`_TIMEOUT_FLOORS`：`execute_timeout_seconds >= 3600`、`sandbox_timeout_seconds >= 86400`），在 `resolve_runtime` 中钳制——对齐迁移前 `read_positive_int_env(..., minimum=default)` 的行为。

## 7. 接入新沙箱：沿主干延伸（三步）

新增一个沙箱后端**无需改动任何消费方**，只需：

1. 在 `sandbox_runtime_entity.py` 的 `BACKENDS` 加一个后端名常量；
2. 在 `CAPABILITY_BACKENDS` 里把它挂到对应能力域；
3. 在 `factory.py` 写一个 `builder(runtime) -> 句柄 | None` 并 `register_sandbox_backend(名字, builder)`；
   （如新后端有自己的配置键，再在 `SandboxConfigService._ALLOWED_CONFIG_KEYS` 与 `_BACKEND_LABELS` 登记。）

Admin 端与全部消费方自动识别新后端（前端按 `overview.backends` 渲染候选项，配置键按白名单回显）。

## 8. 安全：本地兜底执行默认关闭 + 受限子进程隔离（S5）

`SkillSandboxExecutor._execute_skill_locally` 会在服务端就地执行第三方 `skill.py`，历史上在"沙箱未配置"时被**静默当作兜底**执行——既绕过隔离，又通过 `_apply_bundle_env` 污染进程级 `os.environ`。

现状处置（**已实现**）：

- 本地兜底执行**默认关闭**；仅当 `skill_exec` 能力域配置显式开启 `allow_local_exec = true` 时才可用。
- 未启用且未显式开启 → 抛 `FailException("技能沙箱不可用：…")`，**明确告知未开通**，不再静默裸跑。
- 开启后也**不再在 API 进程内 `exec_module`**，改为**受限子进程执行**（`subprocess.Popen`）：
  - **独立临时工作目录**：`tempfile.TemporaryDirectory(prefix="skill_local_")`，退出即清理；`HOME`/`TMPDIR` 指向该目录。
  - **独立进程组**：`start_new_session=True`；超时用 `os.killpg(SIGKILL)` **整组强杀**（含其 fork 出的后代），不会留下僵尸树。
  - **子进程内 setrlimit（best-effort）**：CPU(`RLIMIT_CPU` 60s) / 地址空间(`RLIMIT_AS` 1 GiB) / 单文件(`RLIMIT_FSIZE` 64 MiB) / 进程数(`RLIMIT_NPROC` 512) / 句柄(`RLIMIT_NOFILE` 256) / 关闭 core dump。常量在 `skill_executor.py` 顶部（`_LOCAL_EXEC_*`），可调。由 runner 在子进程内应用，平台不支持或越权时**忽略而非失败**。
  - **最小化子进程 env**：不继承父进程完整环境，只传白名单（`PATH`/`LANG`/`LC_*`/`SSL_CERT_*`）+ 技能包 env（经 `Popen(env=...)` 注入，**不落盘**）。API 的密钥/连接串不会泄漏给第三方技能代码。
  - **不再污染父进程 `os.environ`**：移除旧的 `_apply_bundle_env` / `_restore_env`。
- `BaiduCfcSandboxBackend` 不再往 `os.environ` 写凭证：改为 `_scoped_e2b_env()` 上下文管理器，在构造 e2b SDK 的作用域内临时注入并在退出时**严格还原**（原值不存在则删除），不泄漏到父进程。

> **边界（务必明确）**：以上是**故障与资源围栏**，不是安全沙箱——它管资源/崩溃/超时，**管不了**读容器内可读文件、发起网络请求。真正的安全边界仍是远端沙箱（E2B/CFC 或 HTTP 执行服务）。`allow_local_exec` 应仅在无可信远端沙箱、且接受该风险时才开启。

## 9. 迁移与零变化

- 迁移**只建表**；`ensure_default_config()` 在启动时（`app.py` 的 `ensure_*` 序列，`MODE != celery`）幂等补齐各 (capability, backend) 行，并依**当前 env** 推断 active（`E2B_*` 齐 → `baidu_cfc`；`SKILL_SCF_URL`/`SANDBOX_URL` 非占位 → `http_sandbox`；否则 `disabled`），使库内状态与升级前运行时一致。注意：**运行时加载器注册不是 seed**——它是进程级注册，Celery 侧在 `celery_app._ensure_runtime()` 单独执行，勿随 seed 一起限定进程。
- `resolve_runtime` 在**无 DB 记录**时回退 env 判定 → 升级瞬间行为不变。
- 注册表未注册加载器时（脚本 / 单测）`get_sandbox_runtime` 返回 `disabled`，调用方走「未开通」分支（不崩溃、不静默）；**执行进程漏注册会打一次 WARNING**（见 §5「进程注册」），便于第一时间定位断链。
