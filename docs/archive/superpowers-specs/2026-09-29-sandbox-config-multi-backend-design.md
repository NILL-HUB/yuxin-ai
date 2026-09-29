# 沙箱配置治理与多后端热切换设计（spec）

> **已归档（2026-09-29）**：该设计已全部落地。当前实现的权威说明见
> [docs/prd/modules/10-sandbox-runtime.md](../../prd/modules/10-sandbox-runtime.md)；
> 本文档仅保留设计过程与决策依据，**不代表当前实现**（实现细节以模块文档 + 代码为准）。

- 状态：**已落地（2026-09-29）**
- 触发：体检发现「沙箱全线不可用」（[capability-and-user-path-audit.md](../../research/2026-09-29-capability-and-user-path-audit.md) P0-2），且排查发现沙箱配置**完全走 env、无 admin 入口、无工厂、无热切换**，无法像存储（cos/oss）那样切换
- 目标一句话：**把沙箱从"14 处散读 env"收编为"admin 可配 + 多后端热切换"的单一权威入口，且迁移期行为零变化**

> 落地偏差说明（实现以后者为准）：
> - 后端名由 `scf_http` 定为 **`http_sandbox`**（区分能力域各自持 endpoint）。
> - 注入方式采用**运行时注册表**（`sandbox_runtime_registry` + TTL 缓存）而非 `AgentConfig.sandbox_runtime` 字段；core 经 `get_sandbox_runtime(capability)` 读取，service 启动时注册加载器。
> - §6 本地执行隔离**已实现**：默认关闭 `allow_local_exec`；开启后改为**受限子进程**（独立临时目录 + 独立进程组 + 子进程内 setrlimit + 最小化 env + 超时 `killpg`），不再在 API 进程内 `exec_module`，且不再污染父进程 `os.environ`。详见 [modules/10-sandbox-runtime.md](../../prd/modules/10-sandbox-runtime.md) §8。

---

## 1. 现状：沙箱是怎么配置的（实测）

### 1.1 配置面（14 个 env 读取点，跨 5 文件）

| 文件 | 读取变量 | 用途 |
|---|---|---|
| `internal/core/agent/backends/baidu_cfc_sandbox_backend.py` | `E2B_API_KEY`、`E2B_DOMAIN`、`SANDBOX_TEMPLATE_ALIAS`、`SANDBOX_FALLBACK_TEMPLATE_ALIAS` | 构造 E2B 后端；**并反写 `os.environ`** 以绕过 e2b SDK 的本地校验 |
| `internal/core/agent/agents/deep_thinking_agent.py:1889-1904` | 上述 4 个 + `SANDBOX_PROFILE`、`SANDBOX_TIMEOUT_SECONDS`、`SANDBOX_EXECUTE_TIMEOUT_SECONDS` | 判断是否启用沙箱 + 构造 |
| `internal/core/workflow/nodes/code/code_node.py:35-91` | `SANDBOX_URL` | 工作流代码节点（HTTP 协议） |
| `internal/core/skills/skill_executor.py:95-126,307` | `SKILL_SCF_URL`/`SANDBOX_URL`、`E2B_API_KEY`/`E2B_DOMAIN` | 技能 SCF 客户端 + 技能沙箱执行器 |
| `internal/core/tools/.../code_execution_tool/execute_code.py:27-31` | 经 `tool_credential_resolver`（**也只是读 env**）读 5 个 | 工具启用判断 + 构造 |
| `internal/core/agent/entities/sandbox_policy_entity.py` | —（硬编码默认值） | 第 3 处默认值来源（另两处：`.env.example`、`docker/entrypoint.sh`） |

### 1.2 三条互不复用的执行机制（各自判"是否配置"、各自降级）

1. **E2B / 百度 CFC 代码解释器**（`BaiduCfcSandboxBackend`）→ 深度思考、`execute_code`、技能沙箱执行器
2. **SCF HTTP 技能服务**（`SkillScfClient`）→ 技能同步 / 执行
3. **`SANDBOX_URL` HTTP 代码节点**（`code_node`）→ 工作流

**语义污染**：同一 `SANDBOX_URL` 同时表示"技能 SCF 端点"与"工作流代码节点"（两套不同 HTTP 协议）；同一 `E2B_*` 同时被深度思考与技能执行器使用。

### 1.3 安全问题（borrowed risk）

`SkillSandboxExecutor._execute_skill_locally`（`skill_executor.py:384-450`）在**沙箱未配置**时，用 `importlib.util.spec_from_file_location(...).exec_module` **在 API 进程内直接执行第三方 `skill.py`**，并通过 `_apply_bundle_env` 把解密后的密钥**写进全局 `os.environ`**（用后恢复）。即"没有沙箱就直接裸跑"，且污染进程级环境变量。

---

## 2. 判定（轮胎 vs 补丁，按 AGENTS 规则量化）

| 测量项 | 实测 | 判读 |
|---|---|---|
| 是否已有核心能力层 | `BaseSandbox` 协议 + **单一实现** `BaiduCfcSandboxBackend`，被 **4 个模块**复用 | ✅ **能力层是轮胎** |
| 补丁密度 | **14 处 env 散读 / 5 文件**；**3 套并行机制**；默认值 **3 处**硬编码 | ⚠️ 配置层是补丁堆 |
| 入口是否统一 | 构造（写）4 处 + 配置（读）5 处，**双双散落且无统一入口** | ❌ **配置层缺失** |

**结论**：不是「补丁组成的轮胎」（**无需推倒重来**——执行后端只有一份实现，不存在需要合并的第二套机制），而是**「轮胎 + 一大片散补丁 + 缺失的统一配置层」**。

**处置**：**补齐缺失的配置层（新权威入口）并把 14 处散读与 3 套机制收编进去**；不新建平行机制 —— 新配置层自身就是那个权威入口。

---

## 3. 目标 / 非目标

**目标**
1. 沙箱配置入库，admin 可编辑、可切换、可观测（对齐 `/admin/storage`）
2. 支持**多后端**与**按能力域热切换**（切换只影响新会话）
3. 收编 14 处 env 散读与 3 套机制到单一入口
4. 迁移期**行为零变化**；未配置时**显式**表达"未开通"，不再静默降级

**非目标**
- 不做历史数据迁移（沙箱每次执行新建会话，无"存量数据"需搬迁）
- 不引入"用户本机沙箱后端"（`desktop_local`）—— 列为后续增量
- 不改变"密钥类不入库"的口径（`E2B_API_KEY`/`E2B_DOMAIN` 继续走 env）

---

## 4. 设计

### 4.1 数据模型：`sandbox_config`

```
sandbox_config
  id            uuid pk
  capability    varchar(32)  not null   -- code_interpreter | skill_exec | workflow_code
  backend       varchar(32)  not null   -- baidu_cfc | e2b_cloud | http_sandbox | disabled
  label         varchar(64)  not null default ''
  configs       jsonb        not null default '{}'   -- 白名单键，禁止明文密钥
  is_active     boolean      not null default false
  created_at / updated_at timestamp
  UNIQUE (capability, backend)
  INDEX (capability, is_active)
```

**为什么按能力域分组**（而非像 storage 那样全局单一 active）：代码解释器（E2B 协议）与技能 HTTP 服务（`http_sandbox`）是**两种不同协议**，不可能共用一个后端；工作流代码节点又是另一套 endpoint。故每个 `capability` 各自一个 active。

白名单键（`_ALLOWED_CONFIG_KEYS`，服务层定义）：

| backend | 允许入库的键 |
|---|---|
| `baidu_cfc` | `template_alias`、`fallback_template_alias`、`profile`、`execute_timeout_seconds`、`sandbox_timeout_seconds`、`allow_local_exec` |
| `e2b_cloud` | `template_alias`、`execute_timeout_seconds`、`sandbox_timeout_seconds` |
| `http_sandbox` | `endpoint`、`timeout_seconds`、`allow_local_exec` |
| `disabled` | （无） |

### 4.2 `SandboxConfigService`（新，`internal/service/sandbox/sandbox_config_service.py`）

对标 `StorageConfigService`，签名：

```python
SUPPORTED_CAPABILITIES = ("code_interpreter", "skill_exec", "workflow_code")
SUPPORTED_BACKENDS = ("baidu_cfc", "e2b_cloud", "http_sandbox", "disabled")

@inject
@dataclass
class SandboxConfigService:
    db: SQLAlchemy

    def get_active_backend(self, capability: str) -> str: ...      # DB is_active 优先 → env 兜底 → disabled
    def list_configs(self, capability: str | None = None) -> list[SandboxConfig]: ...
    def get_config(self, capability: str, backend: str) -> SandboxConfig | None: ...
    def upsert_config(self, capability: str, backend: str, configs: dict | None) -> SandboxConfig: ...
    def set_active_backend(self, capability: str, backend: str) -> SandboxConfig: ...  # 同 capability 内互斥置位
    def ensure_default_config(self) -> None: ...                    # 启动幂等补齐（挂在 app.py 现有 ensure_* 旁）
    def resolve_runtime(self, capability: str) -> SandboxRuntime: ...  # ★ 唯一权威入口
```

`resolve_runtime(capability)` 返回跨层契约（不泄漏 SQLAlchemy 模型）：

```python
@dataclass(frozen=True)
class SandboxRuntime:
    capability: str
    backend: str            # 含 "disabled"
    configs: dict           # 白名单后的配置
    enabled: bool           # backend != disabled 且凭证齐备
    reason: str = ""        # enabled=False 时的人类可读原因（供前端/日志）
```

### 4.3 后端工厂（`internal/core/agent/backends/factory.py`）

```python
_REGISTRY: dict[str, SandboxBuilder] = {
    "baidu_cfc": _build_e2b_protocol,
    "e2b_cloud": _build_e2b_protocol,
    "http_sandbox": _build_http_sandbox,     # 返回 HttpSandboxHandle（承载 endpoint/timeout）
    "disabled": _build_disabled,             # 返回 None
}

def build_sandbox_backend(runtime: SandboxRuntime) -> Any | None: ...
```

**约束（关键）**：`internal/core/**` 是框架无关层（无 injector / 无 DB）。因此工厂**只接收 `SandboxRuntime`**，**不得**在此读 DB 或 env（凭证由工厂内的 `_e2b_credentials()` 单点读 env，属既定约定）。

### 4.4 注入路径（实现采用运行时注册表）

core 拿不到配置是"14 处裸读 env"的根因。实现采用**运行时注册表**弥合分层：

```
service 层（有 DB）在启动时（app.py，MODE != celery）：
  register_sandbox_runtime_loader(injector.get(SandboxConfigService).resolve_runtime)
core 层消费方：get_sandbox_runtime(capability)  →  注册表（TTL 10s 缓存）
admin 写入后：SandboxConfigService.upsert_config / set_active_backend 调 invalidate_sandbox_runtime_cache()
```

### 4.5 Admin API（镜像 `/admin/storage`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/sandbox/overview` | 各 capability 的 active 后端 + 配置 + 凭证齐备情况 + 最近探测结果 |
| GET | `/admin/sandbox/configs` | 列出全部配置 |
| POST | `/admin/sandbox/configs/<capability>/<backend>` | upsert（白名单过滤） |
| POST | `/admin/sandbox/activate` | body `{capability, backend}`，互斥置位 |
| POST | `/admin/sandbox/probe` | body `{capability, backend?}`，返回配置层可用性判定与原因 |

前端：`ui/src/views/admin/AdminSandboxView.vue`（卡片式切换 + 探测按钮，仿 `AdminStorageView.vue`），i18n 走 `admin/sandbox.ts`（zh/en 同步）。

### 4.6 热切换语义

- **会话粒度**：切换后**新会话**立即走新后端；**运行中会话**绑定自身后端直到结束（E2B session id 留痕，便于审计与排障）
- **无需迁移**：与 storage 不同，沙箱无存量数据 → 比 storage 更简单（不需要 `migration` 端点）
- **切换安全**：`set_active_backend` 与 `upsert_config` 均走 `auto_commit` 事务；切换前可先 `probe` 校验目标后端可用

---

## 5. 收编清单（14 处逐点，逐项验证）

| # | 位置 | 改法 |
|---|---|---|
| 1-4 | `baidu_cfc_sandbox_backend.py` | 构造参数全部改为**必填传入**（不再从 env 兜底读取）；删除反写 `os.environ` 的副作用，改为 `_scoped_e2b_env()` 作用域内注入所需环境并在退出时还原 |
| 5-11 | `deep_thinking_agent.py` | 改读 `get_sandbox_runtime("code_interpreter")`；`need_sandbox` 与 `runtime.enabled` 共同决定是否启用 |
| 12 | `code_node.py` | 改走 `get_sandbox_runtime("workflow_code")` 取 `http_sandbox` endpoint |
| 13 | `skill_executor.py`（`SkillScfClient`） | endpoint/timeout 改为经注册表解析；未配置时返回/抛出**显式未开通**（复用已落地的 `not_configured` 语义） |
| 14 | `skill_executor.py`（`SkillSandboxExecutor`） | 改为接收 runtime；默认关闭本地兜底，开启后走**受限子进程**（见 §6） |
| 15 | `execute_code.py` | 启用判断与构造改为读运行时快照（`ENABLE_CODE_EXECUTION_TOOL` 保留为工具级开关，与 `capability=code_interpreter` 的启用位共同生效） |
| 16 | `sandbox_policy_entity.py` | 硬编码默认值迁入服务层 `_DEFAULT_CONFIGS`，保留纯函数工具方法 |

> 每收编一处，跑该模块的相关测试；全部收编后 `grep -rn "E2B_\|SANDBOX_" api/internal --include=*.py` 应只剩工厂/服务层/后端 SDK 作用域注入。

---

## 6. 安全修复（借机一并做）

`SkillSandboxExecutor._execute_skill_locally` 的处置（**已按：默认关闭 + 受限子进程**）：

- 新增 `SandboxRuntime.configs["allow_local_exec"]`（默认 `false`）；仅当显式开启才允许本机执行
- 未配置且未显式开启 → 抛**显式"技能沙箱不可用"**（禁止静默裸跑）
- 远端沙箱失败时不再静默回退本地（仅 `allow_local_exec=true` 时回退）
- 本机执行**已改为子进程 + 资源限制 + 独立工作目录**（不再 `exec_module` 进 API 进程）：`subprocess.Popen(start_new_session=True)` + `cwd=临时目录` + 超时 `killpg`；资源上限由 runner 在子进程内 `setrlimit`（CPU/AS/FSIZE/NPROC/NOFILE，best-effort）
- `_apply_bundle_env` 的"写全局 os.environ"**已删除**：技能包 env 改经 `Popen(env=...)` 只注入子进程，父进程 `os.environ` 不被修改
- `BaiduCfcSandboxBackend` 的反写 `os.environ` 已改为作用域注入（`_scoped_e2b_env`）

---

## 7. 迁移与兼容（行为零变化）

1. 迁移**只建表**；`ensure_default_config()` 依**当前 env** 推断 active（`E2B_*` 齐 → `baidu_cfc`；`SKILL_SCF_URL` 非占位 → `http_sandbox`；否则 `disabled`），使库内状态与当前运行时一致
2. `resolve_runtime` 在**无 DB 记录**时回退 env 判定 → 保证升级瞬间行为不变
3. 注册表未注册加载器时返回 `disabled`（而非崩溃）
4. 迁移需满足仓库迁移守卫（`test_migration_graph_integrity.py`：`down_revision` 指向已跟踪文件、单 head）

---

## 8. 落地步骤与验收

| 步骤 | 产出 | 验收 |
|---|---|---|
| S1 | 迁移 + `sandbox_config` 模型 + `SandboxConfigService` | 单测：`ensure_default_config` 幂等、`get/set_active` 互斥、白名单过滤、`resolve_runtime` 的 enabled/reason |
| S2 | `SandboxRuntime` + 工厂 + 注册表 | 单测：`disabled` → `None`；未知 backend 抛错；`baidu_cfc` 在凭证缺失时 `enabled=False` |
| S3 | Admin API 5 个端点 + `AdminSandboxView.vue` + i18n（parity 通过） | 契约测试 + 前端映射测试；`probe` 对占位符返回明确失败原因 |
| S4 | 收编 14 处（逐点） | 每点跑相关模块测试；收编完成后 env 裸读归零（grep 验证） |
| S5 | 安全修复（§6） | 单测：未开启 `allow_local_exec` 时本机执行被拒；开启后父进程 `os.environ` 不被写入、子进程不继承父进程密钥、子进程内资源上限实际生效、超时被强杀 |
| S6 | 文档同步 | `modules/10-sandbox-runtime.md` 新增；`research/config-inventory.md` 登记已收编的 env 读取点 |

**回归基线**：`resolve_runtime` 在 env 与当前一致时，深度思考/`execute_code`/技能执行的行为与升级前**逐字节一致**（可对比 `need_sandbox` 判定结果）。

---

## 9. 风险与未决

| 风险 | 处置 |
|---|---|
| 注入面较广（agent 构造点 10+ 处） | 采用运行时注册表，只在 service 层注册一次；消费方统一 `get_sandbox_runtime` |
| `http_sandbox` 与 E2B 的语义混淆 | 借本次**彻底拆开**：`skill_exec` 域承载 SCF/沙箱，`workflow_code` 域承载代码节点 |
| 管理员误切到不可用后端 | `probe` 前置校验 + overview 显示凭证齐备状态；切换仅影响新会话，可立即切回 |
| `desktop_local`（用户本机沙箱）诉求 | 本 spec 不覆盖，作为后续增量在 `capability` 维度加后端即可（表结构无需变更） |
