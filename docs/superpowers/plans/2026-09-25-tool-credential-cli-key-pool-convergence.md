# 工具凭证收敛入口 / CLI 本地进程接入 / 模型 Key 池优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一次性收敛三块「工具/凭证/密钥」治理债务：① 把 builtin 工具 provider 里散落的裸 `os.getenv` 读取收敛到单一凭证解析入口（并补上 `browser_action` 的断链接线）；② 让本地 CLI 进程成为 MCP 工具工厂的一等传输形态（复用既有 stdio client，不新建平行实现）；③ 明确「模型 Key 池 / 工具凭证」的分区判据，并补上 Key 池熔断的硬编码与「永不恢复」缺口。

**Architecture:**
- **Part A（收敛入口）**：以既有的 `internal/service/desktop_bridge_resolver.py` 为范式，新建 `internal/service/tool_credential_resolver.py`，只提供「按候选名顺序取第一个非空值」这一个能力；**缺失凭证的三种业务语义（`return None` 降级 / 返回中文提示串 / `raise FailException`）留在各调用点**，解析器不替调用方做决策。同时删除 OS/bridge 家族里「`resolve_desktop_bridge` 返回 None 后再读一遍 `DESKTOP_BRIDGE_URL`」的可证死分支。
- **Part B（CLI 接入）**：不新建 `CliClient`。`mcp_stdio_client.py` 已经是「spawn 本地进程」这唯一的轮胎，CLI 只是它的**无协议模式**：同一 client 增加 `protocol="mcp" | "raw"`，`transport=cli` 是 `stdio + protocol=raw` 的别名。工具声明来自 `mcp_provider.tool_schema`（新增 JSONB 列，admin 可编辑 + 运行时读取，成对交付）。
- **Part C（Key 池优化）**：**不按「模型 vs 工具」分区，按「是否可跨 Key 路由」分区**——可路由池（轮换/配额/熔断/按 provider 或模型绑定）继续用 `model_key_config`；一对一静态凭证（一把部署一把 key，无轮换需求）走 env + Part A 的统一入口。并补两个真实缺口：熔断阈值/恢复冷却从硬编码迁入 `global_control_config`，熔断增加时间戳以支持冷却后自动恢复。

**Tech Stack:** Python 3.12 / SQLAlchemy + Alembic / FastAPI(wtforms+marshmallow) / LangChain `BaseTool` / Vue 3 + Arco + vue-i18n / pytest。

**依据调研：**
- 运行范式（Part A 的权威参照）：`api/internal/service/desktop_bridge_resolver.py`（全文 56 行，docstring 明写「工具层只依赖本函数，不直接读表或读环境变量」）
- 配置治理分级（Part A/C 的 env 口径依据）：`docs/research/config-inventory.md`（C 节「密钥类一律不入库，走 env 是正确位置」；D 节 6 section 收编模式）
- 治理规范（本方案自我约束）：`AGENTS.md`「拒绝意大利面补丁：轮胎 vs 补丁」「系统配置统一走 admin 管理」「任务完成前的接线审查」
- MCP stdio 既有能力：`api/internal/core/tools/mcp_tools/providers/mcp_stdio_client.py`（全文 227 行）、`mcp_tool_factory.py`（`SUPPORTED_STDIO_TRANSPORTS={"stdio"}`、`_stdio_client` dataclass 字段）
- CLI 作 stdio command 的先例：`docs/superpowers/plans/2026-09-24-qwen-mm-plugins-assistant-omni.md`（`ASSISTANT_MCP_BINDINGS` + `"transport":"stdio"` + `env` 必须 `{}`）
- 模型 Key 池：`api/internal/service/runtime_model_pool_service.py`（全文 180 行）、`api/internal/service/fallback_llm_wrapper.py`（双层 `[primary,*candidates] × keys`）、`api/internal/model/model_pool_entity.py`

---

## 范围说明

| 计划块 | 内容 | 交付形态 |
| --- | --- | --- |
| **A. 工具凭证收敛入口** | 新建 `tool_credential_resolver`；迁移 23 处凭证读取；修 `browser_action` 断链（动态 bridge + 运行时挂载点）；清理 20 处 bridge/OS 死分支 | 代码 + 文档 |
| **B. CLI 本地进程接入** | `mcp_provider.tool_schema` 列 + `protocol=raw` 模式 + `transport=cli` 别名 + admin 表单 + 前端 i18n | 代码 + 迁移 + 文档 |
| **C. 模型 Key 池优化** | 分区判据落文档；熔断阈值/冷却迁入 `global_control_config`；`circuit_opened_at` 列 + 冷却自动恢复 | 代码 + 迁移 + 文档 |

执行顺序：**A → C → B**。A 清债且是 C/B 的凭证口径基础；C 小而独立；B 面最大（触及迁移、admin、前端），放最后避免前面任务的测试被 schema 变更干扰。

**明确不做（YAGNI）：**
- **不新增任何工具凭证表。** `api/internal/model` 全表 98 张无凭证表；`config-inventory.md:36` 明确「密钥类一律不入库」。Part A 只收敛「读取方式」，不改变「存放位置」。
- **不改三种缺凭证语义。** `web_search` 的 `return None`（降级下一个 provider）、gaode 的中文提示串、atlascloud 的 `raise FailException` 都是各自链路（多 provider 降级 / 用户可读提示 / 硬失败）的正确行为，统一成一种会分别破坏三者。解析器只返回 `str`（空串=缺失），决策留在调用点。
- **不新建 `CliClient` 平行实现。** CLI 与 MCP stdio 共用「spawn 本地进程」能力，新增第二个 client 就是「平行机制」，违反 AGENTS.md。用 `protocol` 模式参数收纳进既有 `McpStdioClient`。
- **不把 CLI 做成 `transport=cli` 的独立 JSON-RPC 语义。** `protocol=raw` 只做「按模板拼 argv → 执行 → 收 stdout/stderr」，不实现工具发现协议；工具声明必须由 admin 显式声明（杜绝「猜」）。
- **不动 `ModelKeyConfig` 的可路由语义。** `model_id IS NULL` = provider 级共享 Key 是既定设计，本次不重构 `get_keys_for_model` 的过滤条件（属「能看出成型的轮胎」，见下方判定）。
- **不给工具凭证加熔断/配额。** 工具凭证无轮换需求，加熔断是过度设计。

---

## 补丁密度测量与处置判定（动手前必做，依据 AGENTS.md）

**测量（2026-09-25 实测）：**

| 测量项 | 命令 / 结果 |
| --- | --- |
| providers 目录 env 读取 | `Grep "os\.getenv\(|os\.environ" api/internal/core/tools/builtin_tools/providers` → **22 文件**（约 49~51 个读取点，视 `getenv`/`environ` 是否同函数计） |
| 归类拆分（按文件，可精确核对） | **含凭证读取 17 文件**、**bridge/OS 类 5 文件**（`computer_action` / `os_file_task` / `os_recycle_bin` / `os_snapshot` / `browser_action`）；17 + 5 = **22 文件**。设置类读取（超时/base_url/模板名等）不构成独立文件，落在上述文件内 |
| 统一凭证解析器是否存在 | `Grep "resolve_tool_credential\|class .*CredentialResolver\|def resolve_env\|tool_credential_resolver\|builtin_credential"` → **No matches found**（完全不存在） |
| 既有范式复用面 | `resolve_desktop_bridge` 被 providers 目录 **5 文件 / 12 行**引用（`computer_action` / `os_file_task` / `os_recycle_bin` / `os_snapshot` / `local_render_runner`），另有 `recycle_bin_handlers.py` 在 service 层引用 |
| 加密底座复用面 | `tool_credential_encryptor`（`encrypt_headers`/`decrypt_env`/`mask_env`…）已被 10 个模块 import（MCP / skill / admin / 外部数据源） |

**判定与处置：**

1. **这是「轮胎 + 补丁」，不是「补丁组成的轮胎」。** 依据：`desktop_bridge_resolver` 已是成型轮胎（单一入口 + 静态 env 兜底 + 5 文件复用 + 有测试 `test_desktop_device_service.py::test_resolver_*`）；`tool_credential_encryptor` 亦是（10 模块复用）。散落在 22 个 provider 文件里的裸 `os.getenv` 是**补丁**，其中 23 处凭证读取可被**同一个**解析入口收纳。
2. **本次是「补洞口」，不推倒重建。** 迁移方式：新增 1 个解析器（复用既有加密与 bridge 范式），把 23 处凭证读取逐个并入；**不新建第二套凭证机制**。
3. **是否引入平行机制：否。** Part A 复用 `desktop_bridge_resolver` 范式 + 既有 `tool_credential_encryptor`；Part B 复用 `McpStdioClient`；Part C 复用 `global_control_config` + `model_key_config`。三块均收敛到既有权威入口。

---

## 已核实的事实（写代码前先读，避免重复踩坑）

| 事实 | 位置 / 证据 |
| --- | --- |
| 工具层「只依赖解析函数」的范式已存在 | `desktop_bridge_resolver.py` docstring：`工具层只依赖本函数，不直接读表或读环境变量，便于单测与替换。` |
| 动态优先 → 静态 env 兜底 → None | `resolve_desktop_bridge()`：动态分支 `DesktopDeviceService(db=db).resolve_bridge(account_id)`；`except Exception` 只 `logger.warning`；静态读 `DESKTOP_BRIDGE_URL`/`DESKTOP_BRIDGE_TOKEN`，`return url.rstrip("/"), token`，否则 `None` |
| **`resolve_desktop_bridge` 已内含 DESKTOP_BRIDGE 兜底** | 同文件 `:52-55`。因此 OS 家族 `else` 分支里「再读一次 `DESKTOP_BRIDGE_URL`」是**可证死分支**（`resolve` 返回 None ⇒ 该 env 对不存在） |
| `browser_action` 是唯一未接动态 bridge 的 OS 家族文件 | `browser_action.py:63-76 _call_worker` 只读 env 两段，无 `resolve_desktop_bridge`；文件头 docstring 自述「平台侧默认关闭」 |
| **`browser_action` 还缺运行时挂载点（第二处断链）** | `assistant_agent_service.py` 有 `host_os`(970-984) / `computer_control`(991-1002) / `audio_tools` / `web_tools` / `code_execution_tool` / `vision_tools` / `todo_tool` / `knowledge_base_tools` 挂载块，**无 `browser_automation`**；全仓 `browser_action` 仅出现于 `tool_policy_entity.py:28`（高风险名单）、`providers.yaml:169`、provider 包内文件与 `test_` |
| 工具取用统一入口 | `BuiltinProviderManager.get_tool(provider_name, tool_name)`（`builtin_provider_manager.py:36-41`）；`get_provider` → `Provider.get_tool(tool_name)` → `tool_func_map.get(tool_name)`；工厂函数签名如 `browser_action(**kwargs)` 返回 `BaseTool` |
| 三种缺凭证语义（**必须原样保留**） | `web_tools/web_search.py:73-75`（`if not api_key: return None`）；`gaode/gaode_weather.py:50-52`（`return "高德开放平台API未配置"`）；`atlascloud_shared.py::_build_headers`（`raise FailException("未配置ATLASCLOUD_API_KEY环境变量")`） |
| 凭证读取全清单（23 处 / 13 文件） | `atlascloud_shared.py:22`；`baidu/baidu_translate.py:26,27`；`x_search/x_search.py:32`；`gaode/{gaode_poi_search:25,gaode_weather:51,gaode_geocode:24,gaode_regeo:23,gaode_route_planning:25}`；`code_execution_tool/execute_code.py:30,77,78`；`github/{github_repo_search:15,github_issue_search:15,github_user_info:15}`；`newsapi/{newsapi_search:15,newsapi_top_headlines:15,newsapi_sources:17}`；`stability/stability_text_to_image.py:15`；`web_tools/web_search.py:73,92,112,132` |
| 既有测试会 pin env（迁移必须保持行为等价） | `test_web_search_tool.py`（`monkeypatch.setenv("TAVILY_API_KEY", ...)`）、`test_x_search_tool.py`（`XAI_API_KEY`）、`test_builtin_apps_and_providers.py`（`GAODE_API_KEY`） |
| stdio 已是主白名单成员 | `internal/schema/mcp_schema.py:13`：`_SUPPORTED_TRANSPORTS = {"http","sse","streamable_http","streamable-http","stdio"}`；`normalize_mcp_transport()`（`internal/entity/mcp_entity.py:129`）只归一 `streamable-http` |
| 仅「预览 / URL 导入」排除 stdio | `mcp_schema.py:179-184`（预览）、`:231-236`（URL 导入）—— 二者语义上确实不需要 stdio，保持排除 |
| 工厂分派点 | `mcp_tool_factory.py:19` `SUPPORTED_STDIO_TRANSPORTS={"stdio"}`；`:123` `_stdio_client: McpStdioClient = field(default_factory=McpStdioClient)`；`:547-554 _is_binding_enabled`；`:556-560 _normalize_transport`；`:640-651 _list_remote_tools`；`:653-665 _call_remote_tool`；`:428-431` 与 `:333-346` 两处「不支持的 MCP transport」守卫 |
| stdio client 的能力面 | `mcp_stdio_client.py`：`DEFAULT_MCP_STDIO_TIMEOUT_SECONDS=30`；`_build_stdio_params`（command 空→`ValueError("stdio 绑定缺少 command")`；args 过滤空串）；`_build_subprocess_env`（先继承 `os.environ` 再 `decrypt_env(binding["env"])`）；`_run_async`（有 loop→ThreadPoolExecutor，无 loop→`asyncio.run`）；`_split_command`（`shlex.split`） |
| `env` 明文会被静默跳过 | `decrypt_env` 对非密文抛 `ValueError`；`_list_remote_tools` 的 try/except 吞掉只记日志 → binding 静默失效。**CLI 绑定的 `env` 必须留 `{}`，密钥走容器 env 由子进程继承** |
| `mcp_provider` 既有列 | `api/internal/model/mcp.py`：`transport:47` / `command:49` / `args:52` / `env:53` / `tool_names:51` / `headers:50` / `timeout_seconds:55`；无 `tool_schema`、无 `protocol` |
| 落库前已加密 | `mcp_service.py:787/790`（create）、`:822/825`（update）调用 `encrypt_headers` / `encrypt_env`（幂等） |
| 对外展示已脱敏 | `mcp_service.py:331-332` `mask_headers` / `mask_env`；`:333-334` 注释明确 binding 保留密文供运行时 `decrypt_*` |
| 前端 transport 选项已含 stdio | `ui/src/views/space/mcp/components/CreateOrUpdateMcpModal.vue:436-443`（`streamable_http/http/sse/stdio` 四个 `<a-option>`）；表单字段含 `transport/url/command/headers_text/tool_names_text/args_text/env_text/timeout_seconds` |
| 前端校验已含 stdio | 同文件 `:277`（`transport === 'stdio' && !command`）、`:281`（http/sse/streamable_http 需 url） |
| 迁移单 head | `api/internal/migration/versions/g1b2c3d4e5f8_add_global_control_config.py`：`revision="g1b2c3d4e5f8"`、`down_revision="f3e4d5c6b7a8"`。**新迁移 `down_revision` 必须为 `g1b2c3d4e5f8`** |
| 全局控制配置是「成对交付」的既有样板 | `global_control_config_service.py`：`DEFAULT_CONFIGS` + `_SECTION_FIELD_TYPES` + `SUPPORTED_SECTIONS` + `_POLICY_OPTIONS`；`get_config(section)` 字段白名单并集默认值；`update_config` 类型/枚举校验；admin `GET/PUT /admin/global-control-config`；前端 `GlobalControlConfigView.vue` 六个 section |
| Key 池熔断阈值硬编码 | `runtime_model_pool_service.py:138`：`if key.failure_count >= 3: key.status = "circuit_open"` |
| 熔断后**永不恢复** | 同文件无「冷却后复位」逻辑；`get_keys_for_model` 只取 `status == "active"` → `circuit_open` 是终态；`model_key_config` 无 `circuit_opened_at` 列 |
| Key 状态枚举 | `internal/schema/admin_model_pool_schema.py:9`：`["active","disabled","circuit_open"]`；`internal/entity/billing_runtime_entity.py:8`：`{"active","inactive","circuit_open"}` |
| Key 池既有消费面 | `fallback_llm_wrapper.py`：`for model in [primary, *candidates]: keys = get_keys_for_model(model.id)` → 逐 key `try/_build_llm/invoke`，失败 `record_key_failure`，成功 `record_key_success`；全失败降级 `_invoke_default` |
| `model_id` 可空 = provider 级共享 Key | `model_pool_entity.py:130`：`model_id = Column(String(36), nullable=True)`；`get_keys_for_model` 过滤 `(model_id IS NULL AND provider == model.provider) OR (model_id == model_id_text)` |
| 测试执行方式 | 兄弟计划统一用 `docker exec llmops-api pytest <path> -q` |

---

## 文件结构

| 文件 | 职责 | 动作 |
| --- | --- | --- |
| `api/internal/service/tool_credential_resolver.py` | **Part A 单一凭证读取入口**：`get_tool_credential` / `get_tool_setting` | 新建 |
| `api/test/internal/service/test_tool_credential_resolver.py` | 解析器单测（候选顺序 / 空串语义 / 缺失） | 新建 |
| `api/internal/core/tools/builtin_tools/providers/**`（17 文件） | 23 处凭证读取改走解析器 | 修改 |
| `api/internal/core/tools/builtin_tools/providers/browser_automation/browser_action.py` | 接动态 bridge + `requester` 字段 | 修改 |
| `api/internal/core/tools/builtin_tools/providers/{computer_control,host_os,video_render_tools}/*.py`（5 文件） | 删可证死分支，改走解析器 | 修改 |
| `api/internal/service/assistant_agent_service.py` | 补 `browser_automation` 运行时挂载点 | 修改 |
| `api/test/internal/core/tools/test_browser_action_tool.py` | 补动态 bridge 用例 + 隔离 DESKTOP_BRIDGE env | 修改 |
| `api/internal/model/mcp.py` | 新增 `tool_schema` JSONB 列 | 修改 |
| `api/internal/migration/versions/h2c3d4e5f6a9_add_mcp_tool_schema.py` | 建 `tool_schema` 列 | 新建 |
| `api/internal/core/tools/mcp_tools/providers/mcp_stdio_client.py` | 新增 `protocol="raw"` 模式（argv 模板执行） | 修改 |
| `api/internal/core/tools/mcp_tools/providers/mcp_tool_factory.py` | `SUPPORTED_CLI_TRANSPORTS`、`cli` 别名分派、`tool_schema` 读取 | 修改 |
| `api/internal/schema/mcp_schema.py` | `_SUPPORTED_TRANSPORTS` 加 `cli`；`tool_schema` 字段 + 校验；`McpProviderResp` 加 `tool_schema`（防序列化丢字段） | 修改 |
| `api/internal/entity/mcp_entity.py` | `normalize_mcp_transport` 归一 `cli` | 修改 |
| `api/internal/service/mcp_service.py` | `_normalize_binding` / `_is_binding_enabled` / `_binding_reason` 支持 `cli`；payload 透传 `tool_schema` | 修改 |
| `api/test/internal/core/tools/test_mcp_stdio_client_raw.py` | `protocol=raw` 行为测试 | 新建 |
| `api/test/internal/core/tools/test_mcp_cli_transport.py` | `transport=cli` 端到端（假 command） | 新建 |
| `ui/src/views/space/mcp/components/CreateOrUpdateMcpModal.vue` | transport 加 `cli` 选项；新增 `tool_schema` 编辑区 | 修改 |
| `ui/src/i18n/messages/{zh-CN,en-US}/space.ts` | 新增 4 个键（两侧同步） | 修改 |
| `api/internal/model/model_pool_entity.py` | `ModelKeyConfig` 新增 `circuit_opened_at` | 修改 |
| `api/internal/migration/versions/i3d4e5f6a7b0_add_model_key_circuit_opened_at.py` | 建 `circuit_opened_at` 列 | 新建 |
| `api/internal/service/global_control_config_service.py` | 新增 `model_key_pool` section（阈值 + 冷却） | 修改 |
| `api/internal/service/runtime_model_pool_service.py` | 阈值/冷却读配置；熔断写时间戳；冷却自动恢复 | 修改 |
| `api/test/internal/service/test_runtime_model_pool_service.py` | 补熔断阈值可配 + 冷却恢复用例 | 修改 |
| `ui/src/views/admin/GlobalControlConfigView.vue` | 新增 `model_key_pool` 表单区 | 修改 |
| `ui/src/i18n/messages/{zh-CN,en-US}/admin/globalControlConfig.ts` | 新增键（两侧同步） | 修改 |
| `docs/research/config-inventory.md` | C 节补「已收编哪些补丁」 | 修改 |
| `docs/prd/modules/01-agent-tool-pool.md` | 补「工具凭证与 Key 池分区判据」一节 | 修改 |
| `docs/prd/modules/09-desktop-client.md` | 更新 `browser_action` 已接动态 bridge 的事实 | 修改 |
| `docs/README.md` | 登记本计划（`superpowers/` 已在导航内，只需确认） | 按需 |

---

## Part A：工具凭证收敛入口

### Task A1: 新建统一凭证解析器

**Files:**
- Create: `api/internal/service/tool_credential_resolver.py`
- Test: `api/test/internal/service/test_tool_credential_resolver.py`

- [ ] **Step 1: 写失败测试**

创建 `api/test/internal/service/test_tool_credential_resolver.py`：

```python
"""tool_credential_resolver 行为测试。

验证候选名顺序取值、空白归一、缺失返回空串（缺失语义由调用方决定）。
"""
import pytest

from internal.service import tool_credential_resolver as resolver


def test_returns_first_non_empty_candidate(monkeypatch):
    monkeypatch.setenv("RESOLVER_PRIMARY", "")
    monkeypatch.setenv("RESOLVER_SECONDARY", "secondary-value")

    assert resolver.get_tool_credential("RESOLVER_PRIMARY", "RESOLVER_SECONDARY") == "secondary-value"


def test_skips_whitespace_only_candidates(monkeypatch):
    monkeypatch.setenv("RESOLVER_PRIMARY", "   ")
    monkeypatch.setenv("RESOLVER_SECONDARY", "ok")

    assert resolver.get_tool_credential("RESOLVER_PRIMARY", "RESOLVER_SECONDARY") == "ok"


def test_strips_surrounding_whitespace(monkeypatch):
    monkeypatch.setenv("RESOLVER_ONLY", "  token-key  ")

    assert resolver.get_tool_credential("RESOLVER_ONLY") == "token-key"


def test_returns_empty_string_when_all_missing(monkeypatch):
    monkeypatch.delenv("RESOLVER_ABSENT", raising=False)

    assert resolver.get_tool_credential("RESOLVER_ABSENT") == ""


def test_setting_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("RESOLVER_SETTING", raising=False)

    assert resolver.get_tool_setting("RESOLVER_SETTING", default="180") == "180"


def test_setting_prefers_env_over_default(monkeypatch):
    monkeypatch.setenv("RESOLVER_SETTING", "300")

    assert resolver.get_tool_setting("RESOLVER_SETTING", default="180") == "300"


def test_accepts_multiple_candidate_names_for_aliases(monkeypatch):
    monkeypatch.delenv("RESOLVER_ALIAS_A", raising=False)
    monkeypatch.setenv("RESOLVER_ALIAS_B", "b")

    assert resolver.get_tool_credential("RESOLVER_ALIAS_A", "RESOLVER_ALIAS_B") == "b"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker exec llmops-api pytest api/test/internal/service/test_tool_credential_resolver.py -q`
Expected：FAIL —— `ModuleNotFoundError: No module named 'internal.service.tool_credential_resolver'`

- [ ] **Step 3: 实现解析器**

创建 `api/internal/service/tool_credential_resolver.py`：

```python
"""工具凭证与设置解析器。

统一收口 builtin 工具 provider 里散落的 `os.getenv` 读取：工具层只依赖本模块，
不直接读环境变量，便于单测与替换（与 desktop_bridge_resolver 同一范式）。

存放位置不变（重要）：密钥类凭证**不入库、走 env**，见
`docs/research/config-inventory.md` C 节「密钥类一律不入库，走 env 是正确位置」。
本模块只收敛「读取方式」，不改变「存放位置」。

缺失语义由调用方决定（本模块只回答「有没有值」）：
- `web_search` 缺 key → return None（降级下一个 provider）
- `gaode` 缺 key → 返回中文提示串
- `atlascloud` 缺 key → raise FailException
因此本模块**不**抛异常、不返回 None，统一返回空串表示缺失。
"""
from __future__ import annotations

import os

__all__ = ["get_tool_credential", "get_tool_setting"]


def _read_first_non_empty(env_names: tuple[str, ...]) -> str:
    for name in env_names:
        value = str(os.getenv(name, "") or "").strip()
        if value:
            return value
    return ""


def get_tool_credential(*env_names: str) -> str:
    """按候选名顺序返回第一个非空的环境变量值；全部缺失返回空串。

    支持同一凭证的历史别名（如 `ATLASCLOUD_API_KEY` / `ATLAS_CLOUD_API_KEY`）。
    """
    return _read_first_non_empty(env_names)


def get_tool_setting(*env_names: str, default: str = "") -> str:
    """读取非凭证类设置（超时、base_url、模板名等）；缺失时返回 default。"""
    return _read_first_non_empty(env_names) or default
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker exec llmops-api pytest api/test/internal/service/test_tool_credential_resolver.py -q`
Expected：PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/tool_credential_resolver.py api/test/internal/service/test_tool_credential_resolver.py
git commit -m "feat(tools): add unified tool credential resolver"
```

---

### Task A2: 迁移 17 个文件 / 23 处凭证读取

**Files:**
- Modify: `api/internal/core/tools/builtin_tools/providers/atlascloud_shared.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/baidu/baidu_translate.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/x_search/x_search.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/gaode/gaode_poi_search.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/gaode/gaode_weather.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/gaode/gaode_geocode.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/gaode/gaode_regeo.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/gaode/gaode_route_planning.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/code_execution_tool/execute_code.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/github/github_repo_search.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/github/github_issue_search.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/github/github_user_info.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/newsapi/newsapi_search.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/newsapi/newsapi_top_headlines.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/newsapi/newsapi_sources.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/stability/stability_text_to_image.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/web_tools/web_search.py`

- [ ] **Step 1: 建立迁移前的行为基线**

Run: `docker exec llmops-api pytest api/test/internal/core/tools/test_web_search_tool.py api/test/internal/core/tools/test_x_search_tool.py api/test/internal/core/tools/test_builtin_apps_and_providers.py -q`
Expected：PASS（记录通过数，迁移后必须仍为 PASS 且数量不变）

**为什么先跑基线**：这三个测试用 `monkeypatch.setenv` 直接 pin 凭证 env，是「迁移是否行为等价」的裁判。迁移只许改变「从哪里读」，不许改变「读到什么」与「缺失时的行为」。

- [ ] **Step 2: 迁移 `atlascloud_shared.py`（保留 raise 语义）**

把 `:19-44` 改为：

```python
from internal.service.tool_credential_resolver import get_tool_credential, get_tool_setting

_DEFAULT_MODEL_API_BASE = "https://api.atlascloud.ai/api/v1/model"


def resolve_atlascloud_api_key() -> str:
    """解析 Atlas Cloud 的 API Key。"""
    return get_tool_credential("ATLASCLOUD_API_KEY", "ATLAS_CLOUD_API_KEY")


def resolve_atlascloud_model_api_base() -> str:
    base = get_tool_setting(
        "ATLASCLOUD_MODEL_API_BASE",
        "ATLAS_CLOUD_MODEL_API_BASE",
        default=_DEFAULT_MODEL_API_BASE,
    )
    return base.rstrip("/")


def _build_headers() -> dict[str, str]:
    api_key = resolve_atlascloud_api_key()
    if not api_key:
        raise FailException("未配置ATLASCLOUD_API_KEY环境变量")
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
```

`raise FailException(...)` 的文案与条件**逐字不动**（既有测试与用户提示依赖它）。

- [ ] **Step 3: 迁移 `web_tools/web_search.py`（保留 `return None` 降级语义）**

四处只替换取值行，`if not api_key: return None` 保持原位：

```python
from internal.service.tool_credential_resolver import get_tool_credential

def _tavily_search(query: str, max_results: int) -> list[dict] | None:
    api_key = get_tool_credential("TAVILY_API_KEY")
    if not api_key:
        return None
    ...

def _exa_search(query: str, max_results: int) -> list[dict] | None:
    api_key = get_tool_credential("EXA_API_KEY")
    if not api_key:
        return None
    ...

def _serpapi_search(query: str, max_results: int) -> list[dict] | None:
    api_key = get_tool_credential("SERPAPI_API_KEY")
    if not api_key:
        return None
    ...

def _brave_search(query: str, max_results: int) -> list[dict] | None:
    api_key = get_tool_credential("BRAVE_SEARCH_API_KEY")
    if not api_key:
        return None
    ...
```

- [ ] **Step 4: 迁移 gaode 五文件（保留中文提示串语义）**

`gaode_poi_search.py:25` / `gaode_geocode.py:24` / `gaode_regeo.py:23` / `gaode_route_planning.py:25`，四处形如：

```python
gaode_api_key = get_tool_credential("GAODE_API_KEY")
```

并在文件顶部 import：

```python
from internal.service.tool_credential_resolver import get_tool_credential, get_tool_setting
```

`gaode_weather.py` 两处：

```python
# :27-35，_get_timeout 内
raw = get_tool_setting("GAODE_API_TIMEOUT_SECONDS")
if not raw:
    return _DEFAULT_GAODE_TIMEOUT_SECONDS
try:
    value = int(raw)
except ValueError:
    return _DEFAULT_GAODE_TIMEOUT_SECONDS
return value if value > 0 else _DEFAULT_GAODE_TIMEOUT_SECONDS

# :50-52，_run 内
gaode_api_key = get_tool_credential("GAODE_API_KEY")
if not gaode_api_key:
    return "高德开放平台API未配置"
```

四文件原有「缺 key 返回中文串」的分支**逐字保留**。

- [ ] **Step 5: 迁移 github 三文件**

`github_repo_search.py:15` / `github_issue_search.py:15` / `github_user_info.py:15`：

```python
from internal.service.tool_credential_resolver import get_tool_credential

token = get_tool_credential("GITHUB_ACCESS_TOKEN")
```

三文件原有 `if token: headers["Authorization"] = ...` 语义保留（未配置时仍走匿名请求）。

- [ ] **Step 6: 迁移 newsapi 三文件与 stability**

`newsapi_search.py:15` / `newsapi_top_headlines.py:15` / `newsapi_sources.py:17`：

```python
from internal.service.tool_credential_resolver import get_tool_credential

api_key = get_tool_credential("NEWSAPI_API_KEY")
```

`stability/stability_text_to_image.py:15`：

```python
from internal.service.tool_credential_resolver import get_tool_credential

api_key = get_tool_credential("STABILITY_API_KEY")
```

两处原有「缺 key 返回中文错误串」分支逐字保留。

- [ ] **Step 7: 迁移 baidu 与 x_search**

`baidu/baidu_translate.py:26-27`：

```python
from internal.service.tool_credential_resolver import get_tool_credential

app_id = get_tool_credential("BAIDU_TRANSLATE_APP_ID")
secret_key = get_tool_credential("BAIDU_TRANSLATE_SECRET_KEY")
```

`x_search/x_search.py:30-31`（既有 helper 名为 `_xai_api_key`，保持名字不变）：

```python
from internal.service.tool_credential_resolver import get_tool_credential

def _xai_api_key() -> str:
    return get_tool_credential("XAI_API_KEY")
```

错误文案 `"未配置 XAI_API_KEY，无法使用 x_search"` **硬编码在 `XSearchTool._run`（`:90`）**，与本 helper 的返回值无关，因此迁移 `_xai_api_key()` 不影响 `test_x_search_tool.py:14-18` 的 `"XAI_API_KEY" in result["error"]` 断言。

- [ ] **Step 8: 迁移 `code_execution_tool/execute_code.py`**

```python
from internal.service.tool_credential_resolver import get_tool_credential, get_tool_setting

def _enabled() -> bool:
    flag = get_tool_setting("ENABLE_CODE_EXECUTION_TOOL").lower()
    if flag not in {"1", "true", "yes", "on"}:
        return False
    return bool(get_tool_credential("E2B_API_KEY") and get_tool_credential("E2B_DOMAIN"))
```

`_run` 内的后端构造改为：

```python
backend = backend_cls(
    api_key=get_tool_credential("E2B_API_KEY"),
    domain=get_tool_credential("E2B_DOMAIN"),
    template_alias=get_tool_setting("SANDBOX_TEMPLATE_ALIAS") or None,
    fallback_template_alias=get_tool_setting("SANDBOX_FALLBACK_TEMPLATE_ALIAS") or None,
)
```

- [ ] **Step 9: 全量对账（确认无遗留凭证读取）**

Run: `docker exec llmops-api pytest api/test/internal/core/tools -q`
Expected：PASS（与 Step 1 基线通过数一致）

再手工核对（应只剩 bridge/OS 类与设置类，无凭证类）：

```bash
grep -rn "os\.getenv(\"[A-Z_]*\(API_KEY\|TOKEN\|SECRET\|APP_ID\|ACCESS_TOKEN\)" \
  api/internal/core/tools/builtin_tools/providers/ || echo "OK: 无凭证裸读残留"
```

- [ ] **Step 10: 提交**

```bash
git add api/internal/core/tools/builtin_tools/providers/
git commit -m "refactor(tools): route builtin provider credentials through unified resolver"
```

---

### Task A3: 修复 `browser_action` 断链（动态 bridge + 运行时挂载点）

**Files:**
- Modify: `api/internal/core/tools/builtin_tools/providers/browser_automation/browser_action.py`
- Modify: `api/internal/service/assistant_agent_service.py`
- Test: `api/test/internal/core/tools/test_browser_action_tool.py`

**为什么两处一起改**：只接动态 bridge 而不补挂载点，工具在对话内根本到不了（历史断链类型「任务无派发点」）；只补挂载点而不接动态 bridge，桌面端每次启动随机生成的 token 永远对不上静态配置（`local_render_runner.py:8` 已把这个记为「`browser_action` 的已知断链，勿重蹈」）。二者必须同 PR。

- [ ] **Step 1: 补测试 —— 动态 bridge 优先 + 未配置时环境隔离**

修改 `api/test/internal/core/tools/test_browser_action_tool.py`：在 `test_browser_action_returns_disabled_error_when_not_configured` 内补删除 DESKTOP_BRIDGE env（否则 CI 上若设了该 env，用例会走动态/静态 bridge 分支而失败）：

```python
def test_browser_action_returns_disabled_error_when_not_configured(monkeypatch):
    monkeypatch.delenv("BROWSER_AUTOMATION_URL", raising=False)
    monkeypatch.delenv("BROWSER_AUTOMATION_TOKEN", raising=False)
    monkeypatch.delenv("DESKTOP_BRIDGE_URL", raising=False)
    monkeypatch.delenv("DESKTOP_BRIDGE_TOKEN", raising=False)

    result = json.loads(BrowserActionTool()._run(action="navigate", url="https://example.com"))

    assert result["ok"] is False
    assert "默认关闭" in result["error"]
```

在同文件末尾新增用例：

```python
def test_browser_action_prefers_dynamic_desktop_bridge(monkeypatch):
    monkeypatch.setattr(
        "internal.service.desktop_bridge_resolver.resolve_desktop_bridge",
        lambda *args, **kwargs: ("http://dynamic-host:9876", "dynamic-token"),
    )
    monkeypatch.setenv("BROWSER_AUTOMATION_URL", "http://fallback:1")
    monkeypatch.setenv("BROWSER_AUTOMATION_TOKEN", "fallback-token")
    captured = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok":true}'

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["auth"] = request.headers.get("Authorization")
        return _FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    tool = BrowserActionTool(requester="acct-1")
    result = json.loads(tool._run(action="snapshot", url="https://example.com"))

    assert result["ok"] is True
    assert captured["url"] == "http://dynamic-host:9876/browser"
    assert captured["auth"] == "Bearer dynamic-token"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker exec llmops-api pytest api/test/internal/core/tools/test_browser_action_tool.py -q`
Expected：FAIL —— `test_browser_action_prefers_dynamic_desktop_bridge` 断言 `captured["url"]` 为 `http://fallback:1/browser`（当前实现只读 env，不认动态 bridge）

- [ ] **Step 3: 改造 `browser_action.py` 的 `_call_worker`**

把 `:63-77` 替换为：

```python
def _call_worker(payload: dict[str, Any]) -> dict[str, Any]:
    # 1.优先按账号动态解析已注册的桌面设备 bridge（解决随机 token 无法静态配置的断链）
    from internal.service.desktop_bridge_resolver import resolve_desktop_bridge
    from internal.service.tool_credential_resolver import get_tool_credential

    resolved = resolve_desktop_bridge(payload.get("requester"), purpose="/browser")
    if resolved:
        endpoint, token = resolved
    else:
        # 2.回退静态配置（独立 browser worker）
        endpoint = get_tool_credential("BROWSER_AUTOMATION_URL")
        token = get_tool_credential("BROWSER_AUTOMATION_TOKEN")
    if not endpoint or not token:
        return {
            "ok": False,
            "error": "未找到可用的浏览器自动化连接（当前账号未注册在线设备），"
                     "且 BROWSER_AUTOMATION_URL/TOKEN 未配置，浏览器自动化默认关闭",
        }
    url = endpoint.rstrip("/") + "/browser"
```

要点：
- `DESKTOP_BRIDGE_URL/TOKEN` 的静态回退由 `resolve_desktop_bridge` 内部完成，**此处不再重复读**（消除与 OS 家族同款的冗余）。
- 错误文案同时保留「未注册在线设备」与「默认关闭」，兼容既有断言（`assert "默认关闭" in result["error"]`）。
- `/browser` 端点拼接语义不变。

- [ ] **Step 4: 给工具类加 `requester` 并可注入 payload**

`BrowserActionTool`（`:103-123`）改为：

```python
class BrowserActionTool(BaseTool):
    """在受控浏览器环境中执行网页操作。"""

    name: str = "browser_action"
    description: str = (
        "在受控浏览器中打开网页、读取页面内容、点击元素、填写表单、滚动、返回、"
        "按键、列出图片或读取控制台日志。用于需要动态渲染、登录后页面、表单操作的网页任务。"
        "该工具默认关闭，需要桌面端注册在线设备或平台配置 BROWSER_AUTOMATION_URL / "
        "BROWSER_AUTOMATION_TOKEN 且按高风险审批。"
    )
    args_schema: type[BaseModel] = BrowserActionInput
    requester: str = ""

    def _run(self, **kwargs: Any) -> str:
        payload = {
            "action": _normalize_text(kwargs.get("action") or "navigate").lower(),
            "url": _normalize_text(kwargs.get("url")),
            "selector": _normalize_text(kwargs.get("selector")),
            "text": str(kwargs.get("text") or ""),
            "wait_ms": int(kwargs.get("wait_ms") or 0),
            "timeout": int(kwargs.get("timeout") or 30000),
            "requester": _normalize_text(kwargs.get("requester") or self.requester),
        }
        result = _call_worker(payload)
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _arun(self, **kwargs: Any) -> str:
        return self._run(**kwargs)
```

- [ ] **Step 5: 补运行时挂载点**

在 `api/internal/service/assistant_agent_service.py` 的 `computer_control` 块（`:988-1002`）之后插入：

```python
        # 浏览器自动化：与 computer_control 同一注入点（requester=账号），
        # 让 browser_action 经 resolve_desktop_bridge 解析本账号已注册设备；
        # 未注册时回退 BROWSER_AUTOMATION_URL/TOKEN 并给出明确错误。高风险，需逐次确认。
        if self.app_config_service is not None:
            try:
                browser_tool_factory = (
                    self.app_config_service.builtin_provider_manager.get_tool(
                        "browser_automation",
                        "browser_action",
                    )
                )
                if browser_tool_factory is not None:
                    tools.append(browser_tool_factory(requester=str(account_id)))
            except Exception:
                logger.warning("构建浏览器自动化工具失败，不影响其他工具", exc_info=True)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `docker exec llmops-api pytest api/test/internal/core/tools/test_browser_action_tool.py -q`
Expected：PASS（4 passed）

- [ ] **Step 7: 验证挂载点确实可达（接线自检）**

Run: `docker exec llmops-api pytest api/test/internal/service/test_assistant_agent_service.py -q`
Expected：PASS

再确认挂载符号有调用方：

```bash
grep -rn "browser_automation" api/internal/service/assistant_agent_service.py
```

Expected：命中新插入的 `"browser_automation",` 一行（此前该文件零命中）。

- [ ] **Step 8: 提交**

```bash
git add api/internal/core/tools/builtin_tools/providers/browser_automation/browser_action.py \
        api/internal/service/assistant_agent_service.py \
        api/test/internal/core/tools/test_browser_action_tool.py
git commit -m "fix(browser): wire browser_action to dynamic desktop bridge and mount in assistant tools"
```

---

### Task A4: 清理 OS/bridge 家族的可证死分支

**Files:**
- Modify: `api/internal/core/tools/builtin_tools/providers/computer_control/computer_action.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/host_os/os_file_task.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/host_os/os_recycle_bin.py`
- Modify: `api/internal/core/tools/builtin_tools/providers/host_os/os_snapshot.py`

- [ ] **Step 1: 建立基线**

Run: `docker exec llmops-api pytest api/test/internal/core/tools/test_computer_action_tool.py api/test/internal/core/tools/test_os_file_task_tool.py api/test/internal/core/tools/test_os_recycle_bin_tool.py api/test/internal/core/tools/test_os_snapshot_tool.py -q`
Expected：PASS（记录通过数）

**为什么可以删**：`resolve_desktop_bridge` 内部已含 `DESKTOP_BRIDGE_URL`/`DESKTOP_BRIDGE_TOKEN` 回退（`desktop_bridge_resolver.py:52-55`）。因此这些文件 `else` 分支里「返回 None 后再读一遍 `DESKTOP_BRIDGE_URL/TOKEN`」的分支**恒为假**——是死代码，不是行为。

- [ ] **Step 2: 简化 `computer_action.py`**

把 `:40-58` 替换为：

```python
def _call_worker(payload: dict[str, Any]) -> dict[str, Any]:
    # 1.优先按账号动态解析已注册的桌面设备 bridge（解决随机 token 无法静态配置的断链）
    from internal.service.desktop_bridge_resolver import resolve_desktop_bridge
    from internal.service.tool_credential_resolver import get_tool_credential

    resolved = resolve_desktop_bridge(payload.get("requester"), purpose="/control")
    if resolved:
        endpoint, token = resolved
    else:
        # 2.回退独立 computer worker（DESKTOP_BRIDGE 的静态回退已在 resolve 内部完成）
        endpoint = get_tool_credential("COMPUTER_CONTROL_URL")
        token = get_tool_credential("COMPUTER_CONTROL_TOKEN")
    if not endpoint or not token:
        return {
            "ok": False,
            "error": "未找到可用的桌面设备连接（当前账号未注册在线设备），"
                     "且 DESKTOP_BRIDGE_URL/TOKEN、COMPUTER_CONTROL_URL/TOKEN 均未配置",
        }
    # 桌面桥自带 /control 路由；直连 worker 时才补路径
    url = endpoint if endpoint.rstrip("/").endswith("/control") else endpoint.rstrip("/") + "/control"
```

（错误文案保留对 `DESKTOP_BRIDGE_URL/TOKEN` 的提示，因为 `resolve` 的静态回退确实会读它——文案属实。）

- [ ] **Step 3: 简化 `os_file_task.py`**

把 `:85-103` 替换为：

```python
    from internal.service.desktop_bridge_resolver import resolve_desktop_bridge
    from internal.service.tool_credential_resolver import get_tool_credential

    resolved = resolve_desktop_bridge(payload.get("requester"), purpose="/file")
    if resolved:
        bridge_url, bridge_token = resolved
        endpoint = bridge_url.rstrip("/") + "/file"
        token = bridge_token
    else:
        # 回退独立 OS worker 根地址（DESKTOP_BRIDGE 静态回退已在 resolve 内部完成）
        endpoint = get_tool_credential("OS_AUTOMATION_URL")
        token = get_tool_credential("OS_AUTOMATION_TOKEN")
```

- [ ] **Step 4: 简化 `os_recycle_bin.py` 与 `os_snapshot.py`**

两个文件的同一模式（`import` 移到函数内，删除 DESKTOP_BRIDGE 重读）：

```python
    from internal.service.desktop_bridge_resolver import resolve_desktop_bridge
    from internal.service.tool_credential_resolver import get_tool_credential

    resolved = resolve_desktop_bridge(payload.get("requester"), purpose="/recycle")  # os_snapshot 用 "/snapshot"
    if resolved:
        bridge_url, bridge_token = resolved
        endpoint = bridge_url.rstrip("/") + "/recycle"   # os_snapshot: + "/snapshot"
        token = bridge_token
    else:
        endpoint = get_tool_credential("OS_AUTOMATION_URL")
        token = get_tool_credential("OS_AUTOMATION_TOKEN")
```

- [ ] **Step 5: 运行测试确认行为不变**

Run: `docker exec llmops-api pytest api/test/internal/core/tools/test_computer_action_tool.py api/test/internal/core/tools/test_os_file_task_tool.py api/test/internal/core/tools/test_os_recycle_bin_tool.py api/test/internal/core/tools/test_os_snapshot_tool.py -q`
Expected：PASS（与 Step 1 通过数一致）

- [ ] **Step 6: 提交**

```bash
git add api/internal/core/tools/builtin_tools/providers/computer_control api/internal/core/tools/builtin_tools/providers/host_os
git commit -m "refactor(tools): drop provably-dead DESKTOP_BRIDGE fallback in os/computer workers"
```

---

### Task A5: 登记 Part A 的收编结果

**Files:**
- Modify: `docs/research/config-inventory.md`
- Modify: `docs/prd/modules/09-desktop-client.md`

- [ ] **Step 1: 在 `config-inventory.md` C 节补「已收编」说明**

在 C 节「第三方凭据与密钥」条目后追加：

```markdown
- **第三方凭据与密钥**：……密钥类一律不入库，走 env 是正确位置。
  - **2026-09-25 收编**：builtin 工具 provider 内 23 处凭证裸读（17 文件）已统一收敛到
    `internal/service/tool_credential_resolver.py` 的 `get_tool_credential()`；工具层不再直接
    调用 `os.getenv`。**存放位置不变（仍在 env），仅收敛读取方式**；三种缺凭证语义
    （`return None` / 中文提示串 / `raise FailException`）保留在各自调用点。
  - bridge/OS 家族 4 文件内「`resolve_desktop_bridge` 返回 None 后再读 `DESKTOP_BRIDGE_URL`」
    的可证死分支已删除（该静态回退由 `desktop_bridge_resolver` 内部完成）。
```

- [ ] **Step 2: 更新 `09-desktop-client.md` 中 `browser_action` 的状态**

把 `local_render_runner.py` docstring 里「`browser_action` 的已知断链，勿重蹈」所对应的文档描述更正为**已修复**：在 `09-desktop-client.md` 提到浏览器自动化/本机 worker 的段落补一行：

```markdown
- `browser_action` 已接入 `resolve_desktop_bridge`（按账号动态解析在线设备）并已在
  `assistant_agent_service` 挂载（`requester=account_id`），不再依赖静态 env 才能可用；
  未注册设备时回退 `BROWSER_AUTOMATION_URL/TOKEN` 并返回明确错误（默认关闭）。
```

- [ ] **Step 3: 运行 graphify 保持图谱最新**

Run: `python -m graphify update .`
Expected：命令成功，`graphify-out/` 有变动

- [ ] **Step 4: 提交**

```bash
git add docs/research/config-inventory.md docs/prd/modules/09-desktop-client.md graphify-out
git commit -m "docs: record tool credential convergence and browser_action fix"
```

---

## Part C：模型 Key 池优化

### Task C1: 熔断阈值与冷却迁入 `global_control_config`

**Files:**
- Modify: `api/internal/service/global_control_config_service.py`
- Test: `api/test/internal/service/test_global_control_config_service.py`（若不存在则新建）

- [ ] **Step 1: 写失败测试**

`api/test/internal/service/test_global_control_config_service.py` **已存在**（顶部有 `_Row` / `_Query` / `_Session` / `_service(row=None)` 轻量替身，不依赖真库）。在文件末尾追加：

```python
def test_get_config_returns_model_key_pool_defaults():
    svc = _service()
    assert svc.get_config("model_key_pool") == {"failure_threshold": 3, "cooldown_seconds": 300}


def test_model_key_pool_is_registered_as_supported_section():
    assert "model_key_pool" in SUPPORTED_SECTIONS
    assert "model_key_pool" in DEFAULT_CONFIGS


def test_update_model_key_pool_rejects_non_positive_threshold():
    import pytest

    # 必须限定 match：否则「未知 section」也会抛 ValueError，这条断言会因错误原因通过
    with pytest.raises(ValueError, match="必须大于 0"):
        _service().update_config("model_key_pool", {"failure_threshold": 0})


def test_update_model_key_pool_ignores_unknown_key():
    cfg = _service().update_config("model_key_pool", {"unknown_key": 1})

    assert "unknown_key" not in cfg
    assert cfg["failure_threshold"] == 3
```

**两点硬约束（写测试前先读）：**

1. **`match="必须大于 0"` 不可省。** `update_config` 有两条 `ValueError` 路径——未知 section（`不支持的配置分组`）与 int ≤ 0（`必须大于 0`）。只写 `pytest.raises(ValueError)` 会让断言在「section 根本没注册」时也通过，判别力为零。
2. **`cooldown_seconds` 也必须 > 0**，因为 `_SECTION_FIELD_TYPES` 的 int 分支统一执行 `if value <= 0: raise ValueError`。**本次刻意不为此开例外**（避免在既有校验机制里加第二条规则）。因此：C2 的冷却恢复测试改**回拨 `circuit_opened_at`** 来模拟冷却已过（不再用 `cooldown_seconds: 0`），C3 前端冷却控件 `:min` 用 **1**。

（`update_config` 的 `expected is int` 分支已含 `if value <= 0: raise ValueError(f"{key} 必须大于 0")`，因此「拒绝 0」无需额外实现即成立；白名单由 `DEFAULT_CONFIGS` 派生，未知 key 被 `continue` 跳过。）

- [ ] **Step 2: 运行测试确认失败**

Run: `docker exec llmops-api pytest api/test/internal/service/test_global_control_config_service.py -q`
Expected：FAIL —— `get_config("model_key_pool")` 返回 `{}`，第一条断言 `{} == {"failure_threshold": 3, ...}` 失败

- [ ] **Step 3: 新增 section**

在 `global_control_config_service.py` 中：

`DEFAULT_CONFIGS` 追加：

```python
    "model_key_pool": {"failure_threshold": 3, "cooldown_seconds": 300},
```

`_SECTION_FIELD_TYPES` 追加：

```python
    "model_key_pool": {"failure_threshold": int, "cooldown_seconds": int},
```

模块 docstring 的 section 列表追加一行：

```
- ``model_key_pool``：模型 Key 池熔断阈值（failure_threshold）与冷却恢复秒数（cooldown_seconds）
```

（`SUPPORTED_SECTIONS` 由 `frozenset(DEFAULT_CONFIGS)` 派生，自动生效；`get_config` 的白名单并集逻辑无需改动。）

- [ ] **Step 4: 运行测试确认通过**

Run: `docker exec llmops-api pytest api/test/internal/service/test_global_control_config_service.py -q`
Expected：PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/global_control_config_service.py api/test/internal/service/test_global_control_config_service.py
git commit -m "feat(config): add model_key_pool section for key pool circuit breaker"
```

---

### Task C2: Key 池读配置 + 熔断写时间戳 + 冷却自动恢复

**Files:**
- Modify: `api/internal/model/model_pool_entity.py`
- Create: `api/internal/migration/versions/i3d4e5f6a7b0_add_model_key_circuit_opened_at.py`
- Modify: `api/internal/service/runtime_model_pool_service.py`
- Test: `api/test/internal/service/test_runtime_model_pool_service.py`

**为什么需要新列**：现在 `circuit_open` 是**终态**——`get_keys_for_model` 只取 `status == "active"`，一旦某 key 连续失败 3 次就永久出局，配置的阈值再对也无人能恢复它。加 `circuit_opened_at` 后，冷却期读配置、到期自动复位为 `active`。

- [ ] **Step 1: 写失败测试**

在 `api/test/internal/service/test_runtime_model_pool_service.py` 的 `TestRuntimeModelPoolService` 类内追加两个方法（复用本文件既有 fixture 与 helper：`model_pool_db` fixture、`_make_model(db, ...)`、`_make_key(db, ...)`、`_service(db)`；注意 service 构造参数是 `db=` 而非 `session=`）：

```python
    def test_record_key_failure_should_open_circuit_at_configurable_threshold(self, model_pool_db, monkeypatch):
        service = _service(model_pool_db)
        monkeypatch.setattr(
            service,
            "_key_pool_config",
            lambda: {"failure_threshold": 2, "cooldown_seconds": 300},
        )
        key = _make_key(model_pool_db, provider="openai", model_id=None)

        assert service.record_key_failure(key.id) is False
        assert service.record_key_failure(key.id) is True
        model_pool_db.session.expire_all()
        reloaded = model_pool_db.session.query(ModelKeyConfig).filter(ModelKeyConfig.id == key.id).one()
        assert reloaded.status == "circuit_open"
        assert reloaded.circuit_opened_at is not None

    def test_get_keys_for_model_should_recover_key_after_cooldown(self, model_pool_db, monkeypatch):
        service = _service(model_pool_db)
        # cooldown_seconds 必须 > 0（C1 的 int 校验统一拒绝 <= 0），
        # 因此用「回拨 circuit_opened_at」来模拟冷却已过，而不是把冷却设为 0。
        monkeypatch.setattr(
            service,
            "_key_pool_config",
            lambda: {"failure_threshold": 1, "cooldown_seconds": 300},
        )
        model = _make_model(model_pool_db, provider="openai")
        key = _make_key(model_pool_db, provider="openai", model_id=None)
        service.record_key_failure(key.id)
        model_pool_db.session.expire_all()
        assert model_pool_db.session.query(ModelKeyConfig).filter(
            ModelKeyConfig.id == key.id
        ).one().status == "circuit_open"

        # 把熔断时间回拨到冷却期之前（600s 前 > 300s 冷却），模拟冷却已到
        stale = model_pool_db.session.query(ModelKeyConfig).filter(ModelKeyConfig.id == key.id).one()
        stale.circuit_opened_at = service._now() - timedelta(seconds=600)
        model_pool_db.session.commit()

        keys = service.get_keys_for_model(model.id)

        assert [k.id for k in keys] == [key.id]
        model_pool_db.session.expire_all()
        recovered = model_pool_db.session.query(ModelKeyConfig).filter(ModelKeyConfig.id == key.id).one()
        assert recovered.status == "active"
        assert recovered.failure_count == 0
        assert recovered.circuit_opened_at is None

    def test_get_keys_for_model_should_not_recover_before_cooldown(self, model_pool_db, monkeypatch):
        service = _service(model_pool_db)
        monkeypatch.setattr(
            service,
            "_key_pool_config",
            lambda: {"failure_threshold": 1, "cooldown_seconds": 3600},
        )
        model = _make_model(model_pool_db, provider="openai")
        key = _make_key(model_pool_db, provider="openai", model_id=None)
        service.record_key_failure(key.id)

        assert service.get_keys_for_model(model.id) == []

    def test_get_keys_for_model_should_not_recover_manual_circuit_without_timestamp(self, model_pool_db):
        """手动熔断（无 timestamp）不得被自动恢复——否则 admin 拉闸会被静默撤销。"""
        service = _service(model_pool_db)
        model = _make_model(model_pool_db, provider="openai")
        # 模拟 admin set_key_status 的效果：只置 circuit_open，不写 circuit_opened_at
        _make_key(
            model_pool_db,
            provider="openai",
            model_id=None,
            status="circuit_open",
            circuit_opened_at=None,
        )

        assert service.get_keys_for_model(model.id) == []

    def test_get_keys_for_model_should_not_recover_key_of_other_provider(self, model_pool_db, monkeypatch):
        """冷却恢复只作用于本 provider，不得跨界复活其它供应商的 Key。

        判别力关键：other 的熔断时间必须**回拨到冷却期之外**（7200s > 3600s），
        这样「未收窄 provider」的旧实现会复活它（测试失败），收窄后才会通过。
        若写成 `circuit_opened_at=_now()`，旧实现也会因「冷却未到」而跳过，测试恒真。
        """
        service = _service(model_pool_db)
        monkeypatch.setattr(
            service,
            "_key_pool_config",
            lambda: {"failure_threshold": 1, "cooldown_seconds": 3600},
        )
        model = _make_model(model_pool_db, provider="openai")
        other = _make_key(
            model_pool_db,
            provider="deepseek",
            model_id=None,
            status="circuit_open",
            circuit_opened_at=_now() - timedelta(seconds=7200),
        )

        service.get_keys_for_model(model.id)

        model_pool_db.session.expire_all()
        still_open = model_pool_db.session.query(ModelKeyConfig).filter(ModelKeyConfig.id == other.id).one()
        assert still_open.status == "circuit_open"
```

（文件顶部已有 `from datetime import UTC, datetime, timedelta`，`timedelta` 可直接用。）

- [ ] **Step 2: 运行测试确认失败**

Run: `docker exec llmops-api pytest api/test/internal/service/test_runtime_model_pool_service.py -q`
Expected：FAIL —— 阈值 `2` 时第一次失败即被判定 `True`（当前硬编码 `>= 3`）；且 `_key_pool_config` 与 `_reload(...).status` 恢复断言均失败

- [ ] **Step 3: 加 `circuit_opened_at` 列**

在 `api/internal/model/model_pool_entity.py` 的 `ModelKeyConfig` 内、`last_used_at` 附近追加：

```python
    # 自动熔断开启时间（record_key_failure 写入）；仅冷却恢复读取。
    # 为 NULL 表示「非自动熔断」（含 admin 手动拉闸）：不参与冷却恢复，保持其状态。
    circuit_opened_at = Column(DateTime, nullable=True)
```

- [ ] **Step 4: 写迁移**

创建 `api/internal/migration/versions/i3d4e5f6a7b0_add_model_key_circuit_opened_at.py`：

```python
"""add model_key_config.circuit_opened_at

Revision ID: i3d4e5f6a7b0
Revises: g1b2c3d4e5f8
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = "i3d4e5f6a7b0"
down_revision = "g1b2c3d4e5f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_key_config",
        sa.Column("circuit_opened_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_key_config", "circuit_opened_at")
```

- [ ] **Step 5: 验证迁移链是单 head**

Run: `docker exec llmops-api alembic heads`
Expected：只输出一个 head：`i3d4e5f6a7b0`

```bash
docker exec llmops-api alembic upgrade head
```

Expected：成功（`down_revision` 指向已被 git 跟踪的 `g1b2c3d4e5f8`）

- [ ] **Step 5.5: 给测试 fixture 的建表 DDL 补同一列**

`api/test/conftest.py` 的 `model_pool_db` fixture 用的是**手写 SQLite DDL**（`_MODEL_KEY_CONFIG_DDL`，`:131-148`），不是 Alembic 迁移。因此新列必须在 DDL 里同步，否则测试里的 `ModelKeyConfig.circuit_opened_at` 查询会 `OperationalError: no such column`。

把 `:140` 的 `last_used_at DATETIME,` 之后插入一行：

```sql
    circuit_opened_at DATETIME,
```

**为什么容易漏**：本地 `alembic upgrade head` 会过、生产也会过，唯独单测库是独立 DDL——这是「迁移加了列但测试建表不同步」的典型坑。

- [ ] **Step 6: 改造 `runtime_model_pool_service.py`**

新增私有方法（放在 `_now()` 附近）：

```python
    def _key_pool_config(self) -> dict[str, Any]:
        """读取 Key 池熔断配置（表优先、缺省兜底），失败时返回内置默认值。"""
        defaults = {"failure_threshold": 3, "cooldown_seconds": 300}
        try:
            from internal.service.global_control_config_service import (
                GlobalControlConfigService,
            )

            cfg = GlobalControlConfigService(session=self._session()).get_config("model_key_pool")
            if isinstance(cfg, dict) and cfg:
                return {
                    "failure_threshold": int(cfg.get("failure_threshold") or defaults["failure_threshold"]),
                    "cooldown_seconds": int(cfg.get("cooldown_seconds") or defaults["cooldown_seconds"]),
                }
        except Exception:
            logger.warning("读取 model_key_pool 配置失败，使用内置默认值", exc_info=True)
        return defaults
```

把 `record_key_failure` 的判定改为读配置并写时间戳：

```python
    def record_key_failure(self, key_id: Any) -> bool:
        session = self._session()
        key = session.query(ModelKeyConfig).filter(ModelKeyConfig.id == key_id).one_or_none()
        if key is None:
            return False
        key.failure_count = int(key.failure_count or 0) + 1
        circuit_opened = False
        threshold = self._key_pool_config()["failure_threshold"]
        if key.failure_count >= threshold:
            key.status = "circuit_open"
            key.circuit_opened_at = self._now()
            circuit_opened = True
        key.updated_at = self._now()
        session.commit()
        return circuit_opened
```

在 `get_keys_for_model` 进入过滤前插入冷却恢复：

```python
    def get_keys_for_model(self, model_id: Any) -> list[ModelKeyConfig]:
        session = self._session()
        model = session.query(ModelPoolConfig).filter(ModelPoolConfig.id == model_id).one_or_none()
        if model is None:
            return []
        self._recover_cooled_down_keys(session)
        now = self._now()
        ...  # 以下过滤条件保持不变
```

`_recover_cooled_down_keys`：

```python
    def _recover_cooled_down_keys(self, session: Any, *, provider: str) -> None:
        """把冷却期已到的 circuit_open Key 复位为 active（失败计数清零）。

        - 只扫描**本 provider** 的熔断 Key：与 get_keys_for_model 的选键范围一致，
          避免「查 A 模型却复活 B 供应商的 Key」。
        - `circuit_opened_at is None` 视为**不可恢复**：只有带时间戳、且冷却已过的
          Key 才复活。这样既不会在部署时把历史 `circuit_open` 行（无时间戳）静默
          全量复活，也不会让 admin 手动拉闸（set_key_status 不写时间戳）被自动撤销。
        """
        candidates = (
            session.query(ModelKeyConfig)
            .filter(
                ModelKeyConfig.status == "circuit_open",
                ModelKeyConfig.provider == provider,
            )
            .all()
        )
        if not candidates:
            return
        cooldown = self._key_pool_config()["cooldown_seconds"]
        if cooldown < 0:
            return
        deadline = self._now() - timedelta(seconds=cooldown)
        recovered: list[ModelKeyConfig] = []
        for key in candidates:
            opened_at = key.circuit_opened_at
            if opened_at is None or opened_at > deadline:
                continue
            key.status = "active"
            key.failure_count = 0
            key.circuit_opened_at = None
            key.updated_at = self._now()
            recovered.append(key)
        if not recovered:
            return
        session.commit()
        logger.info(
            "Key 池冷却恢复 %d 个 Key provider=%s", len(recovered), provider
        )
```

调用点（`get_keys_for_model` 内，传 provider）：

```python
        self._recover_cooled_down_keys(session, provider=model.provider)
```

要点：
- **先查 `circuit_open` 再读配置**——绝大多数调用（无熔断 Key）直接 return，既省一次配置查询，也避免在缺表的测试库上反复打告警。
- **`opened_at is None` 必须跳过**（不是「立即复活」）。熔断的两个写入口语义不同：`record_key_failure`（自动熔断）会写 `circuit_opened_at`，可被冷却恢复；`admin_model_pool_service.set_key_status` / `update_key`（手动熔断）**不写**时间戳，NULL 分支跳过才能保证「管理员手动拉闸不被自动撤销」。这也是部署安全前提：存量 `circuit_open` 行迁移后时间为 NULL，跳过即维持其原有终态，不会静默复活。

文件顶部补 `from datetime import UTC, datetime, timedelta` 与 `import logging` / `logger = logging.getLogger(__name__)`（当前文件既无 `logging` 也无 `logger`，必须新增）。

- [ ] **Step 7: 运行测试确认通过**

Run: `docker exec llmops-api pytest api/test/internal/service/test_runtime_model_pool_service.py -q`
Expected：PASS

- [ ] **Step 8: 提交**

```bash
git add api/internal/model/model_pool_entity.py \
        api/internal/migration/versions/i3d4e5f6a7b0_add_model_key_circuit_opened_at.py \
        api/internal/service/runtime_model_pool_service.py \
        api/test/internal/service/test_runtime_model_pool_service.py
git commit -m "feat(model-pool): configurable circuit threshold and cooldown-based key recovery"
```

---

### Task C3: admin 可编辑入口（成对交付的另一半）

**Files:**
- Modify: `ui/src/views/admin/GlobalControlConfigView.vue`
- Modify: `ui/src/i18n/messages/zh-CN/admin/globalControlConfig.ts`
- Modify: `ui/src/i18n/messages/en-US/admin/globalControlConfig.ts`

**为什么必须有这个 Task**：AGENTS.md 强制「新配置项必须成对交付：admin 可编辑入口 + 运行时读取点」。C1/C2 已给出运行时读取点，此处补入口；缺任一半即断链。

- [ ] **Step 0: 补前端类型定义**

`ui/src/services/admin-global-control-config.ts` 定义了一个显式接口 `GlobalControlConfigs`（`:38-45`）——不加字段会直接 TS 报错。在 `VisionFallbackConfig` 之后追加接口：

```ts
/** 模型 Key 池熔断配置 */
export interface ModelKeyPoolConfig {
  failure_threshold: number
  cooldown_seconds: number
}
```

并在 `GlobalControlConfigs` 内追加一行（与 `vision_fallback` 同级）：

```ts
  model_key_pool: ModelKeyPoolConfig
```

`saveGlobalControlSection` 是泛型函数（`<T extends Record<string, unknown>>`），无需改动。

- [ ] **Step 1: 加表单状态**

在 `GlobalControlConfigView.vue` 的 `form` reactive（`:17-40`）中追加：

```ts
  model_key_pool: {
    failure_threshold: 3,
    cooldown_seconds: 300,
  },
```

- [ ] **Step 2: 加载与保存**

`loadConfig`（`:47-71`）内追加（与既有写法一致）：

```ts
    form.model_key_pool.failure_threshold = configs.model_key_pool?.failure_threshold ?? 3
    form.model_key_pool.cooldown_seconds = configs.model_key_pool?.cooldown_seconds ?? 300
```

`handleSave`（`:73-117`）内，紧随既有 `retry_attempts` 校验之后追加：

```ts
  if (
    !Number.isFinite(form.model_key_pool.failure_threshold) ||
    form.model_key_pool.failure_threshold <= 0
  ) {
    Message.error(t('admin.globalControlConfig.fields.failureThresholdInvalid'))
    return
  }
```

并在 `Promise.all([...])`（`:87-110`）内追加一项：

```ts
      saveGlobalControlSection('model_key_pool', {
        failure_threshold: Math.round(form.model_key_pool.failure_threshold),
        cooldown_seconds: Math.round(form.model_key_pool.cooldown_seconds),
      }),
```

- [ ] **Step 3: 加模板卡片**

在模板中与既有 section 卡片同层级追加（**沿用既有 `section.config-card` + `card-header` 结构**，不是 `<a-card>`）：

```html
        <!-- 模型 Key 池 -->
        <section class="config-card">
          <div class="card-header">
            <h3>{{ t('admin.globalControlConfig.sections.modelKeyPool.title') }}</h3>
            <p>{{ t('admin.globalControlConfig.sections.modelKeyPool.description') }}</p>
          </div>
          <a-form :model="form.model_key_pool" layout="vertical">
            <a-form-item :label="t('admin.globalControlConfig.fields.failureThreshold')" field="failure_threshold">
              <a-input-number v-model="form.model_key_pool.failure_threshold" :min="1" :step="1" :precision="0" />
            </a-form-item>
            <a-form-item :label="t('admin.globalControlConfig.fields.cooldownSeconds')" field="cooldown_seconds">
              <a-input-number v-model="form.model_key_pool.cooldown_seconds" :min="1" :step="1" :precision="0" />
            </a-form-item>
          </a-form>
          <p class="hint-text">{{ t('admin.globalControlConfig.fields.cooldownSecondsHint') }}</p>
        </section>
```

- [ ] **Step 4: 补 i18n（zh-CN 与 en-US 同步）**

**注意真实嵌套层级**：section 文案在 `admin.globalControlConfig.sections.<camelCase>.{title,description}`，字段文案在 `admin.globalControlConfig.fields.<camelCase>`（见 `zh-CN/admin/globalControlConfig.ts:9-57`）。

`zh-CN/admin/globalControlConfig.ts` 的 `sections` 内追加（与既有 `visionFallback` 同级）：

```ts
    modelKeyPool: {
      title: '模型 Key 池',
      description: '控制模型 Key 的熔断阈值与冷却恢复时间。',
    },
```

`fields` 内追加：

```ts
    failureThreshold: '熔断失败阈值 (次)',
    failureThresholdHint: '同一 Key 连续失败达到该次数后熔断，默认 3 次，需大于 0。',
    failureThresholdInvalid: '熔断失败阈值必须大于 0',
    cooldownSeconds: '冷却恢复 (秒)',
    cooldownSecondsHint: '熔断后经过该时长自动恢复为可用，默认 300 秒。',
```

`en-US/admin/globalControlConfig.ts` 对应位置同步：

```ts
    modelKeyPool: {
      title: 'Model key pool',
      description: 'Controls the circuit-breaker threshold and cooldown recovery for model keys.',
    },
```

```ts
    failureThreshold: 'Failure threshold (times)',
    failureThresholdHint: 'A key is tripped after this many consecutive failures. Default 3, must be greater than 0.',
    failureThresholdInvalid: 'Failure threshold must be greater than 0',
    cooldownSeconds: 'Cooldown recovery (seconds)',
    cooldownSecondsHint: 'A tripped key recovers automatically after this duration. Default 300 seconds.',
```

- [ ] **Step 5: 运行 i18n 一致性测试**

Run: `cd ui && npx vitest run src/i18n/__tests__/parity.spec.ts`
Expected：PASS（zh/en 叶子键集合一致，且所有 `t('...')` 引用都能解析）

- [ ] **Step 6: 提交**

```bash
git add ui/src/views/admin/GlobalControlConfigView.vue ui/src/i18n/messages
git commit -m "feat(admin): editable model key pool circuit breaker settings"
```

---

### Task C4: 落定「工具凭证 / 模型 Key 池」分区判据

**Files:**
- Modify: `docs/prd/modules/01-agent-tool-pool.md`

- [ ] **Step 1: 新增一节**

在 `01-agent-tool-pool.md` 的「工具池设计」章节下追加：

```markdown
### 10.x 凭证与 Key 池的分区判据

判据**不是**「模型 vs 工具」，而是**「该凭证是否需要在多个候选之间路由」**：

| 维度 | 可路由池（`model_key_config`） | 具名凭证（env + 统一入口） |
| --- | --- | --- |
| 归属 | 多个 Key 为一个 provider/模型提供服务 | 一把部署一把 Key，一一对应 |
| 是否需要轮换 | 是（按 `used_credits`/`created_at` 排序轮换） | 否 |
| 是否需要配额 | 是（`tenant_quota`，用尽转 `disabled`） | 否 |
| 是否需要熔断 | 是（`failure_count` → `circuit_open`，冷却恢复） | 否 |
| 存储 | DB（`model_key_config.key_value_encrypted`，Fernet 加密） | env（**不入库**） |
| 读取入口 | `RuntimeModelPoolService.get_keys_for_model()` → `FallbackLLMWrapper` | `internal/service/tool_credential_resolver.get_tool_credential()` |

- `model_key_config.model_id IS NULL` 表示 **provider 级共享 Key**（该 provider 下所有模型可用）；
  非空表示绑定到具体模型。此语义由 `get_keys_for_model` 的过滤条件实现，勿改成「模型专属才可用」。
- 工具凭证（gaode/newsapi/github/stability/github/xai/baidu/tavily 等 builtin provider）
  一律走 env + `get_tool_credential()`；**不给工具凭证加熔断/配额**——无轮换需求，加了是过度设计。
- 新增「可路由」需求时，扩展 `model_key_config` 与 `RuntimeModelPoolService`，
  **不要**新建第二套 Key 表或第二个解析器（AGENTS.md「禁止新建平行机制」）。
```

- [ ] **Step 2: 提交**

```bash
git add docs/prd/modules/01-agent-tool-pool.md
git commit -m "docs: document credential vs model key pool partitioning rule"
```

---

## Part B：CLI 本地进程接入

### Task B1: `mcp_provider.tool_schema` 列 + 迁移

**Files:**
- Modify: `api/internal/model/mcp.py`
- Create: `api/internal/migration/versions/j4e5f6a7b8c1_add_mcp_tool_schema.py`

**背景**：MCP 协议能用 `tools/list` 自描述工具；**纯 CLI 不能**。因此 `protocol=raw` 模式必须由 admin 显式声明工具，存 `tool_schema`（`{tool_name: {description, parameters}}`）。这是「不猜」的硬约束。

- [ ] **Step 1: 加列**

在 `api/internal/model/mcp.py` 的 `McpProvider` 内，紧跟 `env`（`:53`）之后追加：

```python
    # CLI（protocol=raw）工具声明：{tool_name: {"description": str, "parameters": {JSON Schema}}}
    # MCP 协议走 tools/list 自描述，不需要本列；纯 CLI 无自描述能力，必须显式声明
    tool_schema = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
```

- [ ] **Step 2: 写迁移**

创建 `api/internal/migration/versions/j4e5f6a7b8c1_add_mcp_tool_schema.py`：

```python
"""add mcp_provider.tool_schema

Revision ID: j4e5f6a7b8c1
Revises: i3d4e5f6a7b0
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "j4e5f6a7b8c1"
down_revision = "i3d4e5f6a7b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_provider",
        sa.Column(
            "tool_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_provider", "tool_schema")
```

（`down_revision` 指向 C2 的迁移，保持单 head 链：`… → g1b2c3d4e5f8 → i3d4e5f6a7b0 → j4e5f6a7b8c1`。）

- [ ] **Step 3: 验证迁移**

Run: `docker exec llmops-api alembic heads` → 单一 head `j4e5f6a7b8c1`
Run: `docker exec llmops-api alembic upgrade head` → 成功

- [ ] **Step 4: 提交**

```bash
git add api/internal/model/mcp.py api/internal/migration/versions/j4e5f6a7b8c1_add_mcp_tool_schema.py
git commit -m "feat(mcp): add tool_schema column for raw CLI tool declarations"
```

---

### Task B2: `McpStdioClient` 增加 `protocol="raw"` 模式

**Files:**
- Modify: `api/internal/core/tools/mcp_tools/providers/mcp_stdio_client.py`
- Test: `api/test/internal/core/tools/test_mcp_stdio_client_raw.py`

**为什么改同一个 client 而不是新建 `McpCliClient`**：二者共用「spawn 本地进程 + 构造 env + 超时 + 进程回收」这一整套能力（`_build_stdio_params` / `_build_subprocess_env` / `_run_async` / `_split_command`）。新建平行 client 就是把同一套逻辑写第二遍（AGENTS.md 的「平行机制」禁忌）。`protocol` 是模式参数，是可被主体吸纳的补丁。

- [ ] **Step 1: 写失败测试**

创建 `api/test/internal/core/tools/test_mcp_stdio_client_raw.py`：

```python
import sys

from internal.core.tools.mcp_tools.providers.mcp_stdio_client import McpStdioClient


def _python_command(script: str) -> str:
    return f'{sys.executable} -c "{script}"'


def test_raw_protocol_lists_declared_tools():
    client = McpStdioClient()
    binding = {
        "protocol": "raw",
        "command": sys.executable,
        "args": [],
        "env": {},
        "tool_schema": {
            "echo_text": {
                "description": "回声文本",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            }
        },
    }

    tools = client.list_tools_sync(binding)

    assert [tool["name"] for tool in tools] == ["echo_text"]
    assert tools[0]["description"] == "回声文本"
    assert tools[0]["inputSchema"]["properties"]["text"]["type"] == "string"


def test_raw_protocol_substitutes_argv_placeholders():
    client = McpStdioClient()
    binding = {
        "protocol": "raw",
        "command": sys.executable,
        "args": ["-c", "print('hello', '{text}')"],
        "env": {},
        "timeout_seconds": 30,
        "tool_schema": {
            "echo_text": {
                "description": "回声文本",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            }
        },
    }

    result = client.call_tool_sync(binding, "echo_text", {"text": "world"})

    assert result["isError"] is False
    assert "hello world" in result["content"][0]["text"]


def test_raw_protocol_reports_nonzero_exit_as_error():
    client = McpStdioClient()
    binding = {
        "protocol": "raw",
        "command": sys.executable,
        "args": ["-c", "import sys; sys.stderr.write('boom'); sys.exit(2)"],
        "env": {},
        "timeout_seconds": 30,
        "tool_schema": {
            "fail_cmd": {
                "description": "必然失败",
                "parameters": {"type": "object", "properties": {}},
            }
        },
    }

    result = client.call_tool_sync(binding, "fail_cmd", {})

    assert result["isError"] is True
    assert "boom" in result["content"][0]["text"]


def test_raw_protocol_rejects_undeclared_tool():
    client = McpStdioClient()
    binding = {
        "protocol": "raw",
        "command": sys.executable,
        "args": [],
        "env": {},
        "tool_schema": {},
    }

    result = client.call_tool_sync(binding, "not_declared", {})

    assert result["isError"] is True
    assert "未声明" in result["content"][0]["text"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker exec llmops-api pytest api/test/internal/core/tools/test_mcp_stdio_client_raw.py -q`
Expected：FAIL —— `list_tools_sync` 走 MCP JSON-RPC 分支，对非 MCP 的 python 子进程拿不到 `tools/list` 响应

- [ ] **Step 3: 实现 `protocol=raw`**

在 `mcp_stdio_client.py` 中加模块常量与分派：

```python
SUPPORTED_STDIO_PROTOCOLS = {"mcp", "raw"}
DEFAULT_STDIO_PROTOCOL = "mcp"
```

`list_tools_sync` / `call_tool_sync` 入口处按协议分派（保持原方法签名不变）：

```python
    def list_tools_sync(self, binding: dict[str, Any]) -> list[dict[str, Any]]:
        if self._resolve_protocol(binding) == "raw":
            return self._list_declared_tools(binding)
        return self._run_async(self._list_tools_async(binding))
```

```python
    def call_tool_sync(self, binding: dict[str, Any], tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._resolve_protocol(binding) == "raw":
            return self._call_raw_command(binding, tool_name, arguments)
        return self._run_async(self._call_tool_async(binding, tool_name, arguments))
```

（若既有实现把同步逻辑直接写在 `list_tools_sync` 内而非转 `_list_tools_async`，则**保留其原有写法**，只在最前面插入 raw 分派，避免改动既有 MCP 分支。）

新增方法：

```python
    def _resolve_protocol(self, binding: dict[str, Any]) -> str:
        protocol = str(binding.get("protocol") or DEFAULT_STDIO_PROTOCOL).strip().lower()
        return protocol if protocol in SUPPORTED_STDIO_PROTOCOLS else DEFAULT_STDIO_PROTOCOL

    def _declared_tool_schema(self, binding: dict[str, Any]) -> dict[str, Any]:
        schema = binding.get("tool_schema") or {}
        return schema if isinstance(schema, dict) else {}

    def _list_declared_tools(self, binding: dict[str, Any]) -> list[dict[str, Any]]:
        """raw 模式下工具由 admin 显式声明，不做任何进程探测。"""
        tools: list[dict[str, Any]] = []
        for tool_name, definition in self._declared_tool_schema(binding).items():
            if not isinstance(definition, dict):
                continue
            tools.append(
                {
                    "name": str(tool_name),
                    "description": str(definition.get("description") or ""),
                    "inputSchema": definition.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        return tools

    def _render_raw_args(self, binding: dict[str, Any], arguments: dict[str, Any]) -> list[str]:
        """把 args 模板里的 {占位符} 用调用参数替换。"""
        raw_args = binding.get("args") or []
        if not isinstance(raw_args, list):
            return []
        rendered: list[str] = []
        for token in raw_args:
            text = str(token)
            for key, value in (arguments or {}).items():
                text = text.replace("{" + str(key) + "}", str(value if value is not None else ""))
            rendered.append(text)
        return rendered

    def _call_raw_command(
        self,
        binding: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name not in self._declared_tool_schema(binding):
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"CLI 工具未声明: {tool_name}"}],
            }
        import subprocess

        command, args, env, timeout = self._build_stdio_params(
            {**binding, "args": self._render_raw_args(binding, arguments)}
        )
        executable, extra_args = self._split_command(command, args)
        try:
            completed = subprocess.run(
                [executable, *extra_args],
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"CLI 执行超时（{timeout}s）: {tool_name}"}],
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"CLI 执行失败: {exc}"}],
            }
        output = completed.stdout or ""
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip() or output.strip() or f"exit={completed.returncode}"
            return {"isError": True, "content": [{"type": "text", "text": detail}]}
        return {"isError": False, "content": [{"type": "text", "text": output}]}
```

要点：
- `command` 复用 `_build_stdio_params`（内含 `shlex.split(command)`、`args` 过滤空串、env 继承 + `decrypt_env`、timeout ≤0 兜底），**不重复实现**。
- `env` 必须留 `{}`（密钥由容器 env 继承）——与 stdio 既有约定一致，避免 `decrypt_env` 抛 `ValueError`。
- 未声明工具直接报错（不猜、不执行）。

- [ ] **Step 4: 运行测试确认通过**

Run: `docker exec llmops-api pytest api/test/internal/core/tools/test_mcp_stdio_client_raw.py -q`
Expected：PASS（4 passed）

- [ ] **Step 5: 回归既有 stdio 测试**

Run: `docker exec llmops-api pytest api/test/internal/core/tools/test_mcp_tool_factory.py api/test/internal/core/tools/test_mcp_tool_factory_identity.py -q`
Expected：PASS（MCP 分支未被改动）

- [ ] **Step 6: 提交**

```bash
git add api/internal/core/tools/mcp_tools/providers/mcp_stdio_client.py api/test/internal/core/tools/test_mcp_stdio_client_raw.py
git commit -m "feat(mcp): support raw CLI execution protocol in stdio client"
```

---

### Task B3: 工厂把 `cli` 分派到 raw 模式

**Files:**
- Modify: `api/internal/core/tools/mcp_tools/providers/mcp_tool_factory.py`
- Test: `api/test/internal/core/tools/test_mcp_cli_transport.py`

- [ ] **Step 1: 写失败测试**

创建 `api/test/internal/core/tools/test_mcp_cli_transport.py`：

```python
import sys

from internal.core.tools.mcp_tools.providers.mcp_tool_factory import McpToolFactory


def _cli_binding() -> dict:
    return {
        "name": "cli_echo",
        "transport": "cli",
        "command": sys.executable,
        "args": ["-c", "print('{text}')"],
        "env": {},
        "timeout_seconds": 30,
        "tool_schema": {
            "echo": {
                "description": "回声文本",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            }
        },
    }


def test_cli_transport_builds_langchain_tool(monkeypatch):
    factory = McpToolFactory()
    tools = factory.get_tools([_cli_binding()], mcp_tool_snapshots=None)

    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "mcp__cli_echo__echo"
    assert tool.invoke({"text": "hello-cli"}) == "hello-cli"


def test_cli_binding_disabled_without_command():
    factory = McpToolFactory()
    binding = _cli_binding()
    binding["command"] = ""

    assert factory.get_tools([binding], mcp_tool_snapshots=None) == []


def test_unknown_transport_is_still_skipped():
    factory = McpToolFactory()
    binding = _cli_binding()
    binding["transport"] = "carrier-pigeon"

    assert factory.get_tools([binding], mcp_tool_snapshots=None) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker exec llmops-api pytest api/test/internal/core/tools/test_mcp_cli_transport.py -q`
Expected：FAIL —— `不支持的 MCP transport，已跳过: cli`，返回 `[]`

- [ ] **Step 3: 加 CLI 传输常量与分派**

在 `mcp_tool_factory.py` 常量区（`:18-20`）追加：

```python
SUPPORTED_CLI_TRANSPORTS = {"cli"}
```

**共同判据**：把「支持全部传输」收敛为一个 helper，避免两处守卫各写一套（否则以后再加传输类型必然漏一处）：

```python
    def _is_supported_transport(self, transport: str) -> bool:
        return (
            transport in SUPPORTED_HTTP_TRANSPORTS
            or transport in SUPPORTED_STDIO_TRANSPORTS
            or transport in SUPPORTED_CLI_TRANSPORTS
        )
```

**两处守卫都要改**（这是同一判据的两个调用点，漏任一处即断链）：

① `get_tools` 路径（`:428-431`）：

```python
            transport = self._normalize_transport(binding.get("transport"))
            if not self._is_supported_transport(transport):
                logging.warning("不支持的 MCP transport，已跳过: %s", transport)
                continue
```

② **快照路径（`:333-346`）**：

```python
            transport = self._normalize_transport(binding.get("transport"))
            if not self._is_supported_transport(transport):
                snapshots.append(
                    self._build_snapshot_payload(
                        binding=binding,
                        status="unsupported",
                        tool_definitions=existing_snapshot.get("tool_definitions") if isinstance(existing_snapshot, dict) else [],
                        existing_snapshot=existing_snapshot,
                        last_error="不支持的 MCP transport",
                        retry_count=int(existing_snapshot.get("retry_count") or 0) if isinstance(existing_snapshot, dict) else 0,
                        retryable=False,
                    )
                )
                continue
```

**为什么两处都改**：`prepare_binding_snapshots`（`:249`）是 `get_tools` 用快照时的独立前置路径。只改 `get_tools` 会让绑定在快照侧被标记 `unsupported` 并返回空工具列表——工具在快照模式下静默消失。

`_is_binding_enabled`（`:547-554`）改为：

```python
    def _is_binding_enabled(self, binding: dict[str, Any]) -> bool:
        if "enabled" in binding and not bool(binding.get("enabled")):
            return False
        name = bool(_normalize_text(binding.get("name")))
        transport = self._normalize_transport(binding.get("transport"))
        if transport in SUPPORTED_STDIO_TRANSPORTS or transport in SUPPORTED_CLI_TRANSPORTS:
            return name and bool(_normalize_text(binding.get("command")))
        return name and bool(_normalize_text(binding.get("url")))
```

`_list_remote_tools`（`:640-651`）与 `_call_remote_tool`（`:653-665`）的 stdio 分支条件改为「stdio 或 cli」（两者都走 `_stdio_client`）：

```python
    def _list_remote_tools(self, binding: dict[str, Any]) -> list[dict[str, Any]]:
        transport = self._normalize_transport(binding.get("transport"))
        if transport in SUPPORTED_CLI_TRANSPORTS:
            binding = {**binding, "protocol": "raw"}
        if transport in SUPPORTED_STDIO_TRANSPORTS or transport in SUPPORTED_CLI_TRANSPORTS:
            return self._stdio_client.list_tools_sync(binding)
        payload = self._jsonrpc_request(binding, "tools/list", params={})
        ...
```

```python
    def _call_remote_tool(self, binding: dict[str, Any], tool_name: str, arguments: dict[str, Any]) -> str:
        transport = self._normalize_transport(binding.get("transport"))
        if transport in SUPPORTED_CLI_TRANSPORTS:
            binding = {**binding, "protocol": "raw"}
        if transport in SUPPORTED_STDIO_TRANSPORTS or transport in SUPPORTED_CLI_TRANSPORTS:
            payload = self._stdio_client.call_tool_sync(binding, tool_name, arguments)
        else:
            payload = self._jsonrpc_request(
                binding,
                "tools/call",
                params={"name": tool_name, "arguments": arguments},
            )
        ...
```

（`protocol=raw` 在进入 client 前注入，确保 raw 分支生效。）

同时 `_build_langchain_tool` 的 metadata dict 增加一行透传：

```python
            "transport": self._normalize_transport(binding.get("transport")),
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker exec llmops-api pytest api/test/internal/core/tools/test_mcp_cli_transport.py -q`
Expected：PASS（3 passed）

- [ ] **Step 5: 回归 MCP 全量**

Run: `docker exec llmops-api pytest api/test/internal/core/tools/test_mcp_tool_factory.py api/test/internal/core/tools/test_mcp_tool_factory_identity.py api/test/internal/core/tools/test_mcp_stdio_client_raw.py -q`
Expected：PASS

- [ ] **Step 6: 提交**

```bash
git add api/internal/core/tools/mcp_tools/providers/mcp_tool_factory.py api/test/internal/core/tools/test_mcp_cli_transport.py
git commit -m "feat(mcp): dispatch cli transport to raw stdio client"
```

---

### Task B4: schema / service 层支持 `cli` 与 `tool_schema`

**Files:**
- Modify: `api/internal/schema/mcp_schema.py`
- Modify: `api/internal/entity/mcp_entity.py`
- Modify: `api/internal/service/mcp_service.py`

- [ ] **Step 1: 扩展 transport 归一与白名单**

`api/internal/entity/mcp_entity.py:129`：

```python
def normalize_mcp_transport(transport: Any) -> str:
    """归一化 MCP transport。"""
    normalized = str(transport or "").strip().lower()
    if normalized in {"streamable-http", "streamable_http"}:
        return "streamable_http"
    return normalized
```

无需改动（`cli` 原样返回）。仅确认即可。

`api/internal/schema/mcp_schema.py:13`：

```python
_SUPPORTED_TRANSPORTS = {"http", "sse", "streamable_http", "streamable-http", "stdio", "cli"}
```

`:55` 的默认值保持不变（`streamable_http`）。

- [ ] **Step 2: 加 `tool_schema` 字段与校验**

在 `CreateMcpProviderReq`（`mcp_schema.py:23`）中，紧随 `env`（`:61`）之后追加：

```python
    tool_schema = DictField("tool_schema", default={})
```

在 `validate_command`（`:76-81`）之后追加：

```python
    def validate_tool_schema(self, field: DictField) -> None:
        """cli（protocol=raw）模式下必须声明工具 schema。"""
        transport = str(self.transport.data or "").strip().lower()
        schema = field.data or {}
        if not isinstance(schema, dict):
            raise ValidationError("tool_schema 必须是对象")
        if transport != "cli":
            return
        if not schema:
            raise ValidationError("cli 模式下必须声明 tool_schema（纯 CLI 无工具自描述能力）")
        for tool_name, definition in schema.items():
            if not isinstance(definition, dict):
                raise ValidationError(f"tool_schema[{tool_name}] 必须是对象")
            parameters = definition.get("parameters")
            if parameters is not None and not isinstance(parameters, dict):
                raise ValidationError(f"tool_schema[{tool_name}].parameters 必须是 JSON Schema 对象")
```

对 `UpdateMcpProviderReq` 做同样追加（该 Req 复用同一组校验方法；若其为独立类，则把 `tool_schema` 字段与上述 `validate_tool_schema` 一并复制过去）。

- [ ] **Step 3: service 层归一、判可用、理由、透传**

`mcp_service.py` 的 `_normalize_binding`（`:123-144`）字典内追加：

```python
            "protocol": "raw" if normalize_mcp_transport(binding.get("transport")) == "cli" else _normalize_text(binding.get("protocol")),
            "tool_schema": dict(binding.get("tool_schema") or {}),
```

`_is_binding_enabled`（`:146-157`）改为：

```python
    def _is_binding_enabled(self, binding: dict[str, Any]) -> bool:
        if "enabled" in binding and not bool(binding.get("enabled")):
            return False
        transport = normalize_mcp_transport(binding.get("transport"))
        if transport in {"stdio", "cli"}:
            return bool(_normalize_text(binding.get("name"))) and bool(_normalize_text(binding.get("command")))
        if transport in {"http", "sse", "streamable_http"}:
            return bool(_normalize_text(binding.get("name"))) and bool(_normalize_text(binding.get("url")))
        return False
```

`_binding_reason`（`:159-169`）改为：

```python
    def _binding_reason(self, binding: dict[str, Any]) -> str:
        transport = normalize_mcp_transport(binding.get("transport"))
        if transport in {"stdio", "cli"}:
            if not _normalize_text(binding.get("command")):
                return "stdio/cli 模式需要 command"
            return ""
        if transport in {"http", "sse", "streamable_http"}:
            if not _normalize_text(binding.get("url")):
                return "HTTP/SSE 模式需要 url"
            return ""
        return "当前仅支持 http、sse、streamable_http、stdio 和 cli"
```

`_build_binding_payload`（`:208-229`）**是死代码**（全仓仅此定义、无调用方：`grep -rn "_build_binding_payload" api/` 只命中定义行）。**本次不动它**，仅在其上方加一行注释标明，避免后人误以为它是活路径：

```python
    # NOTE(2026-09-25): 本方法无调用方（binding 已由 _build_provider_payload 直接构造）。
    # 保留仅为最小改动；如需删除请单独提交并跑 MCP 全量测试。
    def _build_binding_payload(self, provider_dict: dict[str, Any], provider_key: str) -> dict[str, Any]:
```

（按 AGENTS.md「删除模块时同步删除文档描述」，此处不做顺手删除以免扩大本次改动面。）

`_build_provider_payload`（`:231-260`）是**关键字参数函数**——不能只在返回字典里塞 `tool_schema`（那样 `_normalize_binding` 里的 binding 仍缺该字段，运行时拿不到）。必须三处齐改：

① 签名（`:259` 的 `task_keywords` 之后）加参数：

```python
        task_keywords: list[str] | None = None,
        tool_schema: dict[str, Any] | None = None,
```

② `_normalize_binding({...})`（`:263-282`）的入参字典内追加（与 `"env": env` 同级）：

```python
            "tool_schema": tool_schema or {},
```

同时 `_normalize_binding`（`:123-144`）的返回字典内追加：

```python
            "protocol": "raw" if transport == "cli" else _normalize_text(binding.get("protocol")),
            "tool_schema": dict(binding.get("tool_schema") or {}),
```

③ `provider_dict = {...}`（`:286-318`）的返回字典内追加（与 `"env": env or {}` 同级）：

```python
            "tool_schema": tool_schema or {},
```

再让两个调用方透传：

- `_build_private_provider_payload`（`:345-372`）的调用实参中追加 `tool_schema=dict(provider.tool_schema or {}),`
- `_build_catalog_provider_payload`（`:377`）的调用实参中追加 `tool_schema=dict(getattr(provider_entity, "tool_schema", None) or {}),`（catalog 实体若无该字段则兜底 `{}`）

`_build_private_provider_payload` 的 `provider` 是 `McpProvider` ORM 实例，迁移加了列后 `provider.tool_schema` 直接可用。

- [ ] **Step 3.5: 给响应 schema 补字段（否则中间层丢字段）**

在 `api/internal/schema/mcp_schema.py` 的 `McpProviderResp`（`:296`）内、`env`（`:311`）之后追加：

```python
    tool_schema = fields.Dict(dump_default={})
```

**为什么必须加**：`McpProviderResp` 是 marshmallow **白名单**（`Schema` 默认丢弃未声明字段），且被 6 处路由用于响应序列化（`admin_routes_8.py:944/1479/1502`、`knowledge_mcp_routes.py:1044/1120`、`admin_routes_4.py:581`）。若不加，`_build_provider_payload` 里放进去的 `tool_schema` **会在序列化时被静默丢弃**，前端编辑已有 MCP 时读不到已存工具声明 → 用户一保存就把 `tool_schema` 清空。这正是 AGENTS.md「中间层丢字段」的典型失效模式。

`create_mcp_provider` / `update_mcp_provider` / `update_mcp_provider_for_admin` **三条写入路径**都要追加同一参数（`tool_schema=req.tool_schema.data or {}`）：

- `:790` 附近（`create_mcp_provider` 的 `McpProvider(...)`）
- `:825` 附近（`update_mcp_provider` 的 `self.update(...)`）
- `:908` 附近（`update_mcp_provider_for_admin` 的 `self.update(...)`）

**为什么三条都要**：admin 走的正是 `update_mcp_provider_for_admin`（`admin_routes_4.py:525 POST /admin/mcp`）。只改前两条会让「admin 保存的 `tool_schema` 不落库」——即本轮反复强调的断链（配置入口写了、运行时读不到）。

`UpdateMcpProviderReq` 继承自 `CreateMcpProviderReq`（`mcp_schema.py:122`），因此 `tool_schema` 字段与 `validate_tool_schema` **自动继承**，无需重复定义。

（`tool_schema` **不加密**——它只含工具名/描述/参数 schema，无凭证；凭证仍在 `env` 且留空。）

- [ ] **Step 4: 跑 service 测试**

Run: `docker exec llmops-api pytest api/test/internal/service -q -k "mcp"`
Expected：PASS

- [ ] **Step 5: 验证 API 契约可用（接线自检）**

Run: `docker exec llmops-api pytest api/test/internal/schema -q -k "mcp"`
Expected：PASS

确认新字段有读取点：

```bash
grep -rn "tool_schema" api/internal/ | grep -v migration
```

Expected：命中 `model/mcp.py`、`schema/mcp_schema.py`、`service/mcp_service.py`、两个 mcp_tools client/factory —— 即「写入（service create/update）+ 读取（factory → client）」齐全。

- [ ] **Step 6: 提交**

```bash
git add api/internal/schema/mcp_schema.py api/internal/entity/mcp_entity.py api/internal/service/mcp_service.py
git commit -m "feat(mcp): accept cli transport and tool_schema in schema and service"
```

---

### Task B5: 前端加 `cli` 选项与 `tool_schema` 编辑区

**Files:**
- Modify: `ui/src/views/space/mcp/components/CreateOrUpdateMcpModal.vue`
- Modify: `ui/src/i18n/messages/zh-CN/space.ts`
- Modify: `ui/src/i18n/messages/en-US/space.ts`

- [ ] **Step 1: 表单类型与默认值**

`McpForm` 追加字段：

```ts
  tool_schema_text: string
```

`defaultForm()` 追加：

```ts
  tool_schema_text: '{}',
```

`applyMcpPayload` 内追加（与 `args`/`env` 的解析写法一致）：

```ts
  const toolSchema =
    payload.tool_schema && typeof payload.tool_schema === 'object' && !Array.isArray(payload.tool_schema)
      ? payload.tool_schema
      : {}
  form.value.tool_schema_text = JSON.stringify(toolSchema, null, 2)
```

- [ ] **Step 2: 提交载荷与校验**

`handleSubmit`（`:230` 起；其内 `:261` 组装 `payload`）内追加：

```ts
    tool_schema: toolSchema,
```

其中 `toolSchema` 在 `:242` 的 `env = parseJsonObject(form.value.env_text)` 之后解析（复用同一 try/catch，JSON 错误同样友好提示）：

```ts
  let toolSchema: Record<string, unknown> = {}
  try {
    headers = parseJsonArray(form.value.headers_text)
      .map((item) => ({
        key: String(item?.key || '').trim(),
        value: String(item?.value || '').trim(),
      }))
      .filter((item) => item.key)
    env = parseJsonObject(form.value.env_text)
    toolSchema = parseJsonObject(form.value.tool_schema_text)
  } catch (error: unknown) {
    Message.warning(t('space.mcp.jsonError', { message: (error as Error).message }))
    return
  }
```

校验（在 `:277` 的 stdio 校验之后）追加：

```ts
  if (payload.transport === 'cli') {
    if (!payload.command) {
      Message.warning(t('space.mcp.stdioCommandRequired'))
      return
    }
    if (!Object.keys(payload.tool_schema || {}).length) {
      Message.warning(t('space.mcp.toolSchemaRequired'))
      return
    }
  }
```

注意：`command` 校验**复用既有 `space.mcp.stdioCommandRequired`**（`:132` 已存在，文案「stdio 模式需要填写命令」对 cli 同样成立），不新增重复键；提示级别用 `Message.warning`，与既有 `:278/:282` 保持一致。

- [ ] **Step 3: transport 下拉加 `cli`**

`:436-443` 追加一个选项：

```html
                  <a-option value="cli">cli</a-option>
```

- [ ] **Step 4: 加 `tool_schema` 编辑区**

在 `env_text` 表单项（`:482` 起）之后追加：

```html
              <a-form-item field="tool_schema_text" :label="t('space.mcp.toolSchemaLabel')" class="lg:col-span-2">
                <a-textarea
                  v-model:model-value="form.tool_schema_text"
                  :auto-size="{ minRows: 4, maxRows: 10 }"
                  :placeholder="t('space.mcp.toolSchemaPlaceholder')"
                />
              </a-form-item>
```

- [ ] **Step 5: 补 i18n（两侧同步）**

`zh-CN/space.ts` 的 `mcp` 命名空间内追加（`commandRequired` 不复用不新增，直接沿用既有 `stdioCommandRequired`）：

```ts
    toolSchemaLabel: 'CLI 工具声明（tool_schema）',
    toolSchemaPlaceholder: '{"echo": {"description": "回声文本", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}',
    toolSchemaRequired: 'cli 模式下必须声明至少一个工具',
```

`en-US/space.ts` 对应位置：

```ts
    toolSchemaLabel: 'CLI tool declarations (tool_schema)',
    toolSchemaPlaceholder: '{"echo": {"description": "Echo text", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}',
    toolSchemaRequired: 'At least one tool must be declared in cli mode',
```

- [ ] **Step 6: 运行 i18n 与前端测试**

Run: `cd ui && npx vitest run src/i18n/__tests__/parity.spec.ts`
Expected：PASS

Run: `cd ui && npx vitest run`
Expected：PASS

- [ ] **Step 7: 提交**

```bash
git add ui/src/views/space/mcp/components/CreateOrUpdateMcpModal.vue ui/src/i18n/messages
git commit -m "feat(ui): support cli transport and tool_schema in MCP modal"
```

---

### Task B6: 登记 CLI 接入方式到扩展性文档

**Files:**
- Modify: `docs/prd/extensibility-design.md`

- [ ] **Step 1: 补一节**

在 `extensibility-design.md` 的「第三方能力接入」章节下追加：

```markdown
### CLI 本地进程接入（2026-09-25 落地）

本地 CLI 作为工具接入**只有一条通道**：`McpStdioClient` 的本地进程能力，按协议分两种模式：

| transport | protocol | 工具来源 | 适用 |
| --- | --- | --- | --- |
| `stdio` | `mcp`（默认） | CLI 自身实现 MCP `tools/list` 自描述 | 已支持 MCP 的 CLI（如 `qwen-mm-plugins-api`） |
| `cli` | `raw`（自动） | admin 在 `mcp_provider.tool_schema` 显式声明 | 纯 CLI（无 MCP 协议），按 `args` 模板执行、取 stdout |

- **无平行实现**：两种模式共用 `_build_stdio_params` / `_build_subprocess_env` / 超时与进程回收；
  `cli` 只是 `stdio` 的模式别名，**禁止**新建第二个 CLI client。
- **`env` 必须留 `{}`**：`decrypt_env` 对非密文抛 `ValueError`，异常会被上层吞掉导致绑定静默失效。
  CLI 需要密钥时写进容器 env，由子进程 `os.environ` 继承。
- **`cli` 必须声明 `tool_schema`**：纯 CLI 无自描述能力，不声明即不可用（服务端与前端均校验）。
- **admin 入口**：MCP 编辑弹窗的 transport 下拉选 `cli`，下方 `tool_schema` 文本框填 JSON；
  运行时读取点为 `McpToolFactory.get_tools → McpStdioClient(protocol=raw)`。
```

- [ ] **Step 2: 运行 graphify**

Run: `python -m graphify update .`
Expected：成功

- [ ] **Step 3: 提交**

```bash
git add docs/prd/extensibility-design.md graphify-out
git commit -m "docs: document cli local process integration"
```

---

## 收尾：文档登记与全量回归

### Task D1: 登记计划并跑全量回归

**Files:**
- Modify: `docs/README.md`（如 `superpowers/` 已登记则仅确认）

- [ ] **Step 1: 确认 `docs/README.md` 导航**

`docs/README.md:50` 已有 `- [superpowers plans & specs](superpowers/)：近期功能的实现计划与规格（distribution / billing / pricing / auth）`——`superpowers/` 目录本身已登记，本计划作为目录内文件**无需**单独新增导航行。仅当该行缺失时才补：

```markdown
- [superpowers plans & specs](superpowers/)：近期功能的实现计划与规格（distribution / billing / pricing / auth）
```

- [ ] **Step 2: 后端全量回归**

Run: `docker exec llmops-api pytest api/test -q`
Expected：PASS（与改造前基线相比无新增失败）

- [ ] **Step 3: 迁移链完整性**

Run: `docker exec llmops-api alembic heads`
Expected：单一 head `j4e5f6a7b8c1`（`g1b2c3d4e5f8 → i3d4e5f6a7b0 → j4e5f6a7b8c1`）

- [ ] **Step 4: 前端回归与 i18n 一致性**

Run: `cd ui && npx vitest run`
Expected：PASS（含 `parity.spec.ts`）

- [ ] **Step 5: 接线审查自检（逐项点名入口）**

```bash
grep -rn "get_tool_credential" api/internal/core/tools/builtin_tools/providers/ | wc -l
grep -rn "browser_automation" api/internal/service/assistant_agent_service.py
grep -rn "SUPPORTED_CLI_TRANSPORTS\|tool_schema" api/internal/ | grep -v migration
grep -rn "_key_pool_config\|circuit_opened_at" api/internal/ | grep -v migration
```

Expected：四条均有命中 —— 即每个新符号都有调用方，无「只定义不接线」。

- [ ] **Step 6: 更新 graphify 并提交**

Run: `python -m graphify update .`

```bash
git add docs/README.md graphify-out
git commit -m "docs: register tool credential / cli transport / key pool plan"
```

---

## 交付后的接线入口速查（供审查者直接复核）

| 新增能力 | 入口 |
| --- | --- |
| 统一工具凭证读取 | `internal/service/tool_credential_resolver.get_tool_credential()`（23 处调用点） |
| 浏览器自动化动态通道 | `browser_action` → `resolve_desktop_bridge(requester, purpose="/browser")`；挂载点 `assistant_agent_service` 的 `browser_automation` 块 |
| CLI 工具接入 | admin MCP 弹窗 `transport=cli` + `tool_schema` → `POST /admin/mcp` → `McpToolFactory.get_tools` → `McpStdioClient(protocol=raw)` |
| Key 池熔断配置 | `GET/PUT /admin/global-control-config`（section `model_key_pool`）→ `RuntimeModelPoolService._key_pool_config()` → `record_key_failure` / `_recover_cooled_down_keys` |
| 熔断冷却恢复 | `RuntimeModelPoolService.get_keys_for_model()` 首行 `_recover_cooled_down_keys()` |
