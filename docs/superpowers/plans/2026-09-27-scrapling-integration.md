# Scrapling 集成实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Scrapling（自适应网页抓取框架）以「API 容器内 MCP stdio 子进程」形态接入平台，作为内置 MCP 目录条目，与既有 `browser_action`（交互式浏览器）互补。

**Architecture:** 不新建容器、不新建代码链路。在 `api` 镜像内安装 `scrapling[ai]` 与 Chromium 依赖；在既有 MCP 目录 `providers.yaml` 新增一条 `transport=stdio`、`command=scrapling-mcp` 的 catalog 条目；admin 在 `/admin/mcp` 一键导入并配置 `tool_names` 白名单控制工具开放范围。运行时由既有 `McpToolFactory → McpStdioClient` 在 API 容器内 spawn 短连接子进程。

**Tech Stack:** Python 3.12 / Quart / SQLAlchemy / pytest / Docker / MCP（`mcp>=2.0.0`）/ Scrapling 0.4.15 / Playwright / Vue3（仅 i18n 与提示，不改逻辑）

**Spec:** `docs/superpowers/specs/2026-09-27-scrapling-integration-design.md`

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `api/requirements.txt` | 修改 | 增 `scrapling[ai]`，将 `mcp>=1.0.0` 收敛为 `mcp>=2.0.0` |
| `api/Dockerfile` | 修改 | 装 Chromium 运行库 + `playwright install chromium` |
| `api/internal/core/tools/mcp_tools/providers/providers.yaml` | 修改 | 新增 `scrapling` catalog 条目 |
| `api/test/internal/core/tools/test_tooling_core.py` | 修改 | 断言 scrapling catalog 条目的字段 |
| `docs/prd/modules/01-agent-tool-pool.md` | 修改 | 登记 Scrapling 能力与默认工具白名单 |

> 说明：`providers.yaml` 是 seed 数据文件（非代码），修改后由现有同步机制生效。

---

## Task 1: 收敛 mcp 依赖到 2.x 并验证兼容性

**背景**：`scrapling[ai]` 要求 `mcp>=2.0.0`，项目当前为 `mcp>=1.0.0`（实装 1.30.0）。必须显式收敛，避免 pip 解析歧义。

**Files:**
- Modify: `api/requirements.txt:232`

- [ ] **Step 1: 修改依赖约束**

将 `api/requirements.txt` 第 232 行：

```
mcp>=1.0.0
```

改为：

```
mcp>=2.0.0
```

- [ ] **Step 2: 验证关键导出在 2.x 下仍存在**

Run:
```bash
docker exec llmops-api python -c "from mcp import ClientSession, StdioServerParameters; from mcp.client.stdio import stdio_client; print('mcp exports ok')"
```
Expected: `mcp exports ok`

- [ ] **Step 3: 跑现有 MCP 相关测试**

Run:
```bash
docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/core/tools/test_mcp_stdio_client_raw.py test/internal/service/test_mcp_service.py test/internal/service/test_mcp_import_service.py -q --no-cov"
```
Expected: 全部 PASS（升级未破坏既有集成）

- [ ] **Step 4: 提交**

```bash
git add api/requirements.txt
git commit -m "chore(deps): 收敛 mcp 依赖至 2.x 以支持 Scrapling"
```

---

## Task 2: 在 API 镜像安装 Scrapling 与浏览器依赖

**背景**：`api/Dockerfile` 基于 `python:3.12-slim-bookworm`，无 Chromium 系统库。Scrapling 的 `DynamicFetcher` 用 Playwright/Chromium，需装运行库。`stealthy_fetch` 依赖 Camoufox，本任务**不装**（见 spec §7 决策），运行时该工具会明确报错。

**Files:**
- Modify: `api/requirements.txt`（追加 scrapling）
- Modify: `api/Dockerfile:30-45`

- [ ] **Step 1: 追加 scrapling 依赖**

在 `api/requirements.txt` 末尾（第 234 行 `yt-dlp==2026.8.19` 之后）追加：

```
scrapling[ai]==0.4.15
```

- [ ] **Step 2: 在 Dockerfile 装 Chromium 运行库**

修改 `api/Dockerfile` 第 30-34 行的 apt 段，在 `libmagic1 curl tzdata` 之后加入 Chromium 运行库（Playwright 官方 slim 依赖）：

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
        libmagic1 curl tzdata \
        fontconfig fonts-dejavu-core \
        libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 \
        libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
        libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
        libcairo2 libasound2 libatspi2.0-0 \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 3: 在 pip 段之后安装 Chromium 浏览器**

在 `api/Dockerfile` 的 pip install 段（第 43-45 行）之后追加：

```dockerfile
# Scrapling 的 DynamicFetcher 需要 Chromium；stealthy_fetch 的 Camoufox 刻意不装（见 spec §7）
RUN python -m playwright install chromium && rm -rf /root/.cache
```

- [ ] **Step 4: 重建 api 镜像**

Run:
```bash
docker compose -f docker/docker-compose.yaml build llmops-api
```
Expected: 构建成功，无依赖解析冲突

- [ ] **Step 5: 验证 scrapling-mcp 可执行**

Run:
```bash
docker compose -f docker/docker-compose.yaml up -d llmops-api
docker exec llmops-api scrapling-mcp --help
```
Expected: 输出包含 `--http`、`--auth-token` 等选项的 usage

- [ ] **Step 6: 验证 Chromium 可用**

Run:
```bash
docker exec llmops-api python -c "from scrapling.fetchers import Fetcher; r = Fetcher.get('https://example.com'); print('STATUS', r.status, 'LEN', len(r.body))"
```
Expected: `STATUS 200 LEN <非零>`

- [ ] **Step 7: 提交**

```bash
git add api/requirements.txt api/Dockerfile
git commit -m "feat(scrapling): API 镜像集成 Scrapling 与 Chromium 依赖"
```

---

## Task 3: 新增 Scrapling 内置 MCP 目录条目

**背景**：`providers.yaml` 是内置 MCP 目录（同 `playwright-mcp` 已是 stdio 条目）。新增条目后 admin 在 `/admin/mcp` 可见并导入，无需手敲 command。

**Files:**
- Modify: `api/internal/core/tools/mcp_tools/providers/providers.yaml`（末尾追加）
- Test: `api/test/internal/core/tools/test_tooling_core.py:473`

- [ ] **Step 1: 写失败测试**

在 `api/test/internal/core/tools/test_tooling_core.py` 的 `test_mcp_provider_manager_should_load_repo_catalog_urls` 函数末尾（第 498 行 `assert ... filesystem-mcp ... args[-1] ...` 之后）追加断言：

```python
    scrapling = manager.get_provider("scrapling").provider_entity
    assert scrapling.transport == "stdio"
    assert scrapling.command == "scrapling-mcp"
    assert scrapling.timeout_seconds == 120
    assert scrapling.tool_names == ["make_request", "bulk_get", "fetch"]
    assert scrapling.source_type == "catalog"
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
docker exec llmops-api sh -lc "cd /app/api && python -m pytest 'test/internal/core/tools/test_tooling_core.py::test_mcp_provider_manager_should_load_repo_catalog_urls' -q --no-cov"
```
Expected: FAIL — `AttributeError: 'NoneType' object has no attribute 'provider_entity'`（scrapling 条目不存在）

- [ ] **Step 3: 在 providers.yaml 追加条目**

在 `api/internal/core/tools/mcp_tools/providers/providers.yaml` 末尾追加：

```yaml
- name: scrapling
  label: Scrapling 网页抓取 MCP
  description: 自适应网页抓取框架，具备反爬绕过、浏览器指纹伪装、自适应选择器与批量并发抓取能力，适合数据采集与反爬场景；交互式操作仍用 browser_action。
  icon: ""
  background: "#DCFCE7"
  category: browser
  transport: stdio
  command: scrapling-mcp
  url: ""
  headers: []
  tool_names:
    - make_request
    - bulk_get
    - fetch
  args: []
  env: {}
  timeout_seconds: 120
  source_type: catalog
  source_key: "D4Vinci/Scrapling"
  source_url: https://github.com/D4Vinci/Scrapling
  created_at: 1790400000
  is_public: true
```

- [ ] **Step 4: 跑测试确认通过**

Run:
```bash
docker exec llmops-api sh -lc "cd /app/api && python -m pytest 'test/internal/core/tools/test_tooling_core.py::test_mcp_provider_manager_should_load_repo_catalog_urls' -q --no-cov"
```
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add api/internal/core/tools/mcp_tools/providers/providers.yaml api/test/internal/core/tools/test_tooling_core.py
git commit -m "feat(scrapling): 新增 Scrapling 内置 MCP 目录条目"
```

---

## Task 4: 端到端验证 MCP 工具发现与调用

**背景**：验证 `McpToolFactory` 能 spawn `scrapling-mcp` 并拿到 13 个工具、`tool_names` 白名单只放行默认 3 个。这是"接线审查"要求的实测。

**Files:**
- 无代码改动（纯验证；若失败则回到 Task 2/3 修复）

- [ ] **Step 1: 直接验证 MCP 握手与工具列表**

Run:
```bash
docker exec llmops-api python -c "
from internal.core.tools.mcp_tools.providers.mcp_tool_factory import McpToolFactory
f = McpToolFactory()
binding = {'name': 'scrapling', 'transport': 'stdio', 'command': 'scrapling-mcp', 'args': [], 'env': {}, 'tool_names': ['make_request','bulk_get','fetch'], 'timeout_seconds': 120}
defs = f.list_remote_tool_definitions(binding)
print('TOTAL_DISCOVERED', len(defs))
print('NAMES', sorted(d['name'] for d in defs))
" 2>&1 | tail -n 5
```
Expected: `TOTAL_DISCOVERED 13`，NAMES 含 `make_request`/`bulk_get`/`fetch`/`stealthy_fetch` 等 13 个

- [ ] **Step 2: 验证白名单过滤生效**

Run:
```bash
docker exec llmops-api python -c "
from internal.core.tools.mcp_tools.providers.mcp_tool_factory import McpToolFactory
f = McpToolFactory()
binding = {'name': 'scrapling', 'label': 'Scrapling', 'description': 'x', 'transport': 'stdio', 'command': 'scrapling-mcp', 'args': [], 'env': {}, 'tool_names': ['make_request','bulk_get','fetch'], 'timeout_seconds': 120}
tools = f.get_tools([binding])
print('TOOL_COUNT', len(tools))
print('TOOL_NAMES', sorted(t.name for t in tools))
" 2>&1 | tail -n 5
```
Expected: `TOOL_COUNT 3`，TOOL_NAMES 为 `mcp__scrapling__bulk_get` / `mcp__scrapling__fetch` / `mcp__scrapling__make_request`

- [ ] **Step 3: 验证真实抓取**

Run:
```bash
docker exec llmops-api python -c "
from internal.core.tools.mcp_tools.providers.mcp_tool_factory import McpToolFactory
f = McpToolFactory()
binding = {'name': 'scrapling', 'label': 'Scrapling', 'description': 'x', 'transport': 'stdio', 'command': 'scrapling-mcp', 'args': [], 'env': {}, 'tool_names': ['make_request'], 'timeout_seconds': 120}
tool = f.get_tools([binding])[0]
out = tool.invoke({'url': 'https://example.com'})
print('RESULT_HEAD', str(out)[:200])
" 2>&1 | tail -n 5
```
Expected: 输出含 `example.com` 页面内容（非空）

- [ ] **Step 4: 记录验证结论**

无需提交（纯验证）。若 Step 1-3 全绿，在 Task 6 的文档中记录已验证。

---

## Task 5: 全量回归（确认升级无副作用）

**Files:**
- 无代码改动

- [ ] **Step 1: 后端全量测试**

Run:
```bash
docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/ -q --no-cov 2>&1 | tail -n 5"
```
Expected: 通过数 ≥ 现有基线（5424+），失败数不高于基线（7 个既存失败）

- [ ] **Step 2: 若有新增失败，定位并修复**

Run:
```bash
docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/ -q --no-cov 2>&1 | grep -E 'FAILED|ERROR' | head -n 20"
```
Expected: 无本次引入的新失败（lxml/orjson 升级相关）

- [ ] **Step 3: 前端 i18n parity（确保未误动文案）**

Run:
```bash
docker exec llmops-ui sh -lc "cd /app/web && npx vitest run src/i18n/__tests__/parity.spec.ts 2>&1 | tail -n 5"
```
Expected: 7/7 PASS

---

## Task 6: 同步架构文档

**背景**：AGENTS.md 强制要求——涉及能力新增须同步文档。

**Files:**
- Modify: `docs/prd/modules/01-agent-tool-pool.md`

- [ ] **Step 1: 在工具池文档补充 Scrapling 小节**

在 `docs/prd/modules/01-agent-tool-pool.md` 的 MCP/抓取能力相关章节，新增如下小节（放在 `browser_action` 描述之后）：

```markdown
### Scrapling 网页抓取（MCP stdio）

平台内置 Scrapling 抓取能力，作为 MCP 目录条目（`providers.yaml` 的 `scrapling`）:
- 部署形态：API 容器内 spawn `scrapling-mcp` 短连接子进程（不新增容器）。
- 与 browser_action 的分工：Scrapling 负责**抓取**（反爬绕过、指纹伪装、自适应选择器、批量并发、代理轮换）；browser_action 负责**交互**（点击/输入/按键/本机浏览器 bridge）。
- 默认开放工具（`tool_names` 白名单）：`make_request`、`bulk_get`、`fetch`。
- 其余 10 个工具（`bulk_fetch`/`stealthy_fetch`/`bulk_stealthy_fetch`/`open_session`/`open_request_session`/`close_session`/`list_sessions`/`session_fetch`/`session_make_request`/`screenshot`）已接入但默认关闭，由 admin 在 `/admin/mcp` 按需开启。
- 已知限制：`stealthy_fetch`/`bulk_stealthy_fetch` 依赖 Camoufox，当前构建未安装，调用会明确报错；如需启用须在 `api/Dockerfile` 追加 Camoufox 安装。
```

- [ ] **Step 2: 提交**

```bash
git add docs/prd/modules/01-agent-tool-pool.md
git commit -m "docs: 登记 Scrapling 抓取能力与默认工具白名单"
```

---

## Self-Review 记录

**1. Spec 覆盖检查**：
- spec §3.1（mcp 2.x 兼容）→ Task 1
- spec §4.1（镜像改造）→ Task 2
- spec §4.2（admin 配置/内置目录）→ Task 3
- spec §4.3（运行时链路）→ Task 4
- spec §5（工具开放范围）→ Task 3（`tool_names` 默认值）+ Task 4（白名单验证）
- spec §6（接线面验证）→ Task 4 + Task 5
- spec §7（风险：Camoufox 不装）→ Task 2 Step 3 注释 + Task 6 文档披露

**2. 占位符扫描**：无 TBD/TODO；所有步骤含完整命令与代码。

**3. 类型一致性检查**：
- `list_remote_tool_definitions(binding)` 与 `get_tools([binding])` 的签名与现有 [mcp_tool_factory.py](file:///d:/DEMO/openagent-main/api/internal/core/tools/mcp_tools/providers/mcp_tool_factory.py) 一致。
- `tool_names` 为 `list[str]`（原始工具名），与 [McpProviderEntity:19](file:///d:/DEMO/openagent-main/api/internal/core/tools/mcp_tools/entities/mcp_provider_entity.py#L19) 一致。
- 工具名前缀 `mcp__{name}__{raw}` 与 [mcp_tool_factory.py:582](file:///d:/DEMO/openagent-main/api/internal/core/tools/mcp_tools/providers/mcp_tool_factory.py#L582) 一致。
- `scrapling-mcp` entry point 已实测存在（`scrapling.cli:mcp`）。
