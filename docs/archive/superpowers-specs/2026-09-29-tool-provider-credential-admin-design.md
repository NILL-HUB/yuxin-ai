# 第三方工具凭证（搜索密钥等）收编 admin 设计（spec）

> **已归档（2026-10-03）**：该设计核心范围已落地（DB 解密优先 → env 兜底的单一解析入口、admin 凭证页签、P1-1 依赖联动；`probe` 按 §8 收窄为齐备性检查）。当前说明见 [01-agent-tool-pool.md](../../prd/modules/01-agent-tool-pool.md) 工具凭证章节与 [config-inventory.md](../../research/config-inventory.md)；本文档仅保留设计过程与决策依据，**不代表当前实现**。

- 状态：已落地（2026-09-29 设计并实施；设计期标注「在途/待评审」为当时状态；2026-10-03 归档）
- 触发：`web_search` 等工具的密钥（`SERPER_API_KEY`/`TAVILY_API_KEY`/`EXA_API_KEY`/`BRAVE_SEARCH_API_KEY`/`XAI_API_KEY`…）
  目前**只走 env**，后台无处可配、也无处可看；`.env.example` 里还是占位符，线上实际只剩免费 `ddgs` 兜底。
- 目标一句话：**把散落在 env 的工具密钥收编为"admin 可配 + 加密入库 + 单一解析入口 + env 兜底"，迁移期行为零变化。**

---

## 1. 现状（实测）

| 面 | 现状 |
|---|---|
| 读取 | `internal/service/tool_credential_resolver.py` 的 `get_tool_credential(*env_names)` / `get_tool_setting(...)`，**只读 env**（文件头注明"密钥类不入库、走 env"） |
| 加密能力 | `internal/service/tool_credential_encryptor.py` 已具备 `encrypt/decrypt/mask`，被 MCP headers/env、model key、skill bundle、external data source、redeem 等 **10 个模块**复用 |
| 工具有关的表 | `builtin_tool_provider`（36 行，仅元数据：name/label/description/icon/category/source）**无凭证字段**；`api_tool_provider`（自定义 API 工具，自带凭证）；`mcp_provider`（headers/env 加密）；`model_key_config`（模型 Key 池，加密） |
| admin 入口 | `/admin/tools` 当前指向 `AdminToolGovernanceService.list_policies(source_type="api_tool")`（api_tool 治理），**builtin provider 无"凭证编辑"入口** |
| 现状缺口 | 搜索类密钥在 `.env.example` 只登记了部分（`EXA/BRAVE/XAI` 曾缺失，2026-09-29 已补登记），且**无 admin 可视化/可配** |

---

## 2. 目标 / 非目标

**目标**
1. 工具密钥（至少搜索类）入库、加密、admin 可编辑可观测
2. **单一权威解析入口**：所有工具仍经 `tool_credential_resolver` 取值（业务代码零改动）
3. 解析顺序：**DB（admin 配置，解密）> env（兜底）**；DB 无值时行为与现状**逐字节一致**
4. 凭证缺失时工具可"如实表达未配置"（对齐技能 `not_configured`、MCP `sync_status` 的既有范式）

**非目标**
- 不新建"全局第三方密钥"平行表（违反"优先扩展既有板块，禁止新建平行机制"）
- 不改变模型类密钥的既有归宿（模型 Key 仍走 `model_key_config`）
- 不在本次实现"密钥轮换/多 key 池路由"（搜索类一般单 key；如需再扩展）

---

## 3. 判定（轮胎 vs 补丁，按 AGENTS 规则量化）

| 测量项 | 实测 | 判读 |
|---|---|---|
| 是否已有核心能力层 | `tool_credential_resolver` 是工具侧取值的**唯一入口**；`tool_credential_encryptor` 被 10 模块复用 | ✅ 能力层是轮胎 |
| 补丁密度 | 历史上 36 处裸 `os.getenv("..._API_KEY")` 跨 21 文件（多数已收编到 resolver） | ⚠️ 残留补丁可继续并入 resolver |
| 入口是否统一 | 读取 1 个（resolver）；但**写入/配置入口缺失**（无 admin 可配） | ❌ **配置层缺失** |

**结论**：`轮胎 + 缺失的统一配置层`。处置：**补齐配置层（在既有 `builtin_tool_provider` 上加加密凭证字段）并把读取收敛到既有 resolver**；不新建平行机制。

---

## 4. 设计

### 4.1 数据模型：扩展 `builtin_tool_provider`（不新建表）

```
builtin_tool_provider（既有表）
  + credentials   jsonb   not null default '{}'   -- 值经 tool_credential_encryptor 加密；键=env 名（如 TAVILY_API_KEY）
```

- 键用 **env 名**（`TAVILY_API_KEY`）而非自定义名：`get_tool_credential("TAVILY_API_KEY")` 的调用点**无需修改**，resolver 内部按 env 名反查 DB。
- 值单独加密（复用 `encrypt_env` 幂等语义）；读接口只回 `mask` 后的值 + `source`（db/env/未配置）。
- **实现取舍（相对初稿）**：初稿拟另加 `credential_keys` 列，落地时改为**代码声明**
  （`BuiltinToolCredentialService.PROVIDER_CREDENTIAL_KEYS`）——"某 provider 需要哪些键"由工具实现决定（读哪个 env），属开发者定义而非管理员配置，入库会造成冗余与漂移。故只加 `credentials` 一列。

### 4.2 单一解析入口：`tool_credential_resolver`（升级，不改签名）

```python
def get_tool_credential(*env_names: str) -> str:
    """DB（admin 配置，解密，按 env 名匹配）优先 → env 兜底；缺失返回 ""（语义不变）。"""
```

- 内部：先从 `builtin_tool_provider.credentials` 里按 `env_names` 逐个查（解密），命中返回；否则回落 `os.getenv`。
- **保留"缺失语义由调用方决定"契约**（`web_search` 缺 key 降级下一 provider、`gaode` 返回中文提示等），不抛异常。
- core 层（工具实现）**不直接读 DB**：resolver 是唯一触点（与 `language_model_service=` 注入范式一致；resolver 本身在 service 层）。

### 4.3 Admin API（扩展既有工具治理板块）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/tools/providers` | 列出 builtin provider + 各凭证键的 `configured`（掩码，不回明文） |
| GET | `/admin/tools/providers/<name>` | 单个 provider 的凭证键 + 掩码值 |
| PUT | `/admin/tools/providers/<name>/credentials` | 设置/更新凭证（加密入库）；空值表示清除该键 |
| POST | `/admin/tools/providers/<name>/probe` | **实探**：用该 provider 的一个代表工具做一次轻量调用，返回 ok/latency/error |

前端：在既有工具管理页（`/admin/tools`，`toolsAdmin.ts`）新增「内置工具凭证」页签/区块，按 provider 渲染凭证键表单 + "测试"按钮；i18n 走 `admin/toolsAdmin.ts`（zh/en 同步）。

### 4.4 迁移与兼容（行为零变化）

1. 迁移**只加两列**（`credentials`、`credential_keys`），默认 `{}` / `[]`。
2. 无 DB 记录 → resolver 回落 env → 升级瞬间行为不变。
3. `credential_keys` 由启动同步服务从各 provider 的 YAML/声明补齐（幂等，仅补不覆盖 admin 的 `credentials`）。
4. 迁移需满足仓库守卫（`down_revision` 指向已跟踪文件、单 head）。

### 4.5 与既有范式对齐（"以一个工具或模型收入 admin"）

- **工具密钥 → 工具 provider 板块**（本 spec）：搜索类（Serper/Tavily/Exa/Brave/DDG 免费/XAI）、生活服务类（高德/OpenWeatherMap/Wolfram/NewsAPI）等。
- **模型密钥 → 模型 Key 池**（既有 `model_key_config`，已 admin 可配）：LLM/嵌入/图像/语音类。
- 判据：**凭证归属"工具"还是"模型"**，各归其位，不重复、不平行。

### 4.6 联动 P1-1（工具 enabled × 依赖联动）

有了 DB 凭证 + `credential_keys`，即可对每个内置工具计算"依赖是否齐备"：
- 任一必需凭证缺失（DB 与 env 均无）→ 工具/ provider 标记 `not_configured` 并给出缺哪个键；
- 列表/详情如实展示（对齐技能 `sync_status`、MCP `sync_status`），避免"工具 enabled=true 却根本跑不通"。

---

## 5. 收编清单（逐点验证）

| # | 位置 | 改法 |
|---|---|---|
| 1 | `tool_credential_resolver.py` | 增加 DB（解密）优先读取；保留 env 兜底与缺失语义 |
| 2 | `builtin_tool_provider` + 迁移 | 加 `credentials` / `credential_keys` 两列 |
| 3 | `builtin_tool_sync_service.py` | 同步时补齐 `credential_keys`（从 provider 声明） |
| 4 | `admin_routes_*` + service | 4 个凭证端点（列表/详情/更新/probe） |
| 5 | `AdminToolsView.vue`（或既有工具页） + i18n | 凭证表单 + 测试按钮 + 缺失告警 |
| 6 | 各工具 provider YAML/声明 | 标注所需 `credential_keys`（至少 `web_tools`/`google`/`tavily`/`exa`/`x_search` 等搜索类） |
| 7 | `docs/research/config-inventory.md` | 登记"已从 env 收编入 admin 的凭证键" |

收编完成后：`grep -rn "os.getenv(\".*_API_KEY\")" api/internal` 应只剩 resolver（与仍属部署基础设施的项）。

---

## 6. 落地步骤与验收

| 步骤 | 产出 | 验收 |
|---|---|---|
| S1 | 迁移 + 模型两列 | 单测：缺省 `{}`/`[]`；加密幂等 |
| S2 | resolver 升级 | 单测：DB 有值优先、无值回落 env、缺失返回 "" |
| S3 | Admin 4 端点 + 前端表单 + probe + i18n | 契约测试 + parity 通过；probe 对无 key 返回明确原因 |
| S4 | 标注搜索类 `credential_keys` | `web_search` 在只配 DB key 时能真实搜到 |
| S5 | P1-1 依赖联动 | 列表如实展示 `not_configured` 及缺失键 |
| S6 | 文档同步 | `01-agent-tool-pool.md` 增「工具凭证」章节；`config-inventory.md` 登记收编项 |

**回归基线**：DB 为空时，`get_tool_credential` 行为与升级前**逐字节一致**。

---

## 7. 风险与未决

| 风险 | 处置 |
|---|---|
| "密钥不入库"旧口径冲突 | 该口径已被现实打破（MCP/model/skill/external 均已加密入库）；本 spec 明确"加密入库 + 掩码出参 + admin 可配"为新口径，并同步修订 `config-inventory.md` |
| 直接读 DB 让 core 层耦合 DB | resolver 保持在 service 层，core 只调 resolver（既有注入范式） |
| `credential_keys` 与 YAML 漂移 | 启动同步补齐 + `config-inventory.md` 登记，测试断言覆盖 |
| 多 key/轮换诉求 | 本次不支持；后续可在 `credentials` 内扩展为 key 列表而不改表结构 |

---

## 8. 落地状态（2026-09-29 已完成）

| 步骤 | 产出 | 现状 |
|---|---|---|
| S1 | 迁移 `m7c8d9e0f1a2`（`builtin_tool_provider.credentials`）+ 模型列 | ✅ |
| S2 | `tool_credential_resolver.get_tool_credential` 升级为 **DB 解密优先 → env 兜底**（签名/缺失语义不变） | ✅（DB 为空时行为逐字节一致） |
| S3 | `BuiltinToolCredentialService`（读取/列表/更新/探测）+ 3 个 admin 端点（`/admin/builtin-tools/credential-providers[...]`）+ `ToolsView.vue`「凭证配置」页签 + i18n | ✅ |
| S4 | `PROVIDER_CREDENTIAL_KEYS` 声明 16 个 provider 的键（搜索类/生活服务类/设备类） | ✅ |
| S5 | P1-1 工具 enabled × 依赖联动（用凭证齐备性标记 `not_configured`） | ✅ `BuiltinToolCredentialService.dependency_status` + `BuiltinToolService` 列表带 `credential_status/credential_missing` + 前端红标；占位符 env 视为未配置 |
| S6 | 文档同步（本节 + `01-agent-tool-pool.md` 工具凭证章节） | ✅ |

**S5 实测（容器内 36 个 provider）**：`time`→`ready`（无要求）；`web_tools`→`ready`（键"任一即可"+ddgs 兜底，missing 仅信息展示）；`tavily/google/gaode/newsapi/x_search/baidu…` 共 **13 个** →`not_configured`（其 env 仅 `.env.example` 占位符）——即"工具 `enabled=true` 但依赖缺失"如实可见。

**实测（容器内真实往返）**：`update_provider_credentials("tavily", ...)` → 落库密文（`gAAAAA…`）、返回掩码（`tvly****cdef`）；
`resolver.get_tool_credential("TAVILY_API_KEY")` 返回 DB 明文（优先级 > env）；`list_providers` 报 `source=db`；`probe` 返回齐备；
清空后解析器回退（返回空串，回落 env）。

**说明（相对初稿的收窄）**：`probe` 落地为**凭证齐备性检查**（逐键判断 DB/env 是否有值并返回缺失清单，不发起外网调用）；
真正的端到端连通性由管理员在对话中实际调用工具验证。初稿的"实探一次轻量调用"未做，列为后续增量。
