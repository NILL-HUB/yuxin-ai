# 能力可用性与用户链路体检（Web 环境）

> **性质**：内部审计快照（非权威）｜**日期**：2026-09-29｜**环境**：单机 Docker 部署（`llmops-*`）
> **目的**：回答三个问题——① 系统在 Web 环境**真能干什么、不能干什么**；② 哪些能力依赖**云端/本地客户端**而在 Web 里不可用；③ 哪些达到生产标准。并给出下一步修复方向。
> **方法**：不采信文档结论，直接采集**运行环境的真实事实**（容器/环境变量/数据库/端点可达性）并**发起真实用户请求**走完整链路。凡未实测者一律标注「未实测」。
> **与文档的关系**：[product-vision.md](../prd/product-vision.md) §三的「✅ 真可用」多为**系统性单测**结论；本次体检按**用户链路**标准复核，结论与其中若干项**不一致**（见 §5）。

---

## 1. 结论速览

| 判定 | 含义 | 本次归属 |
|---|---|---|
| ✅ **真实可用** | 有端到端实测证据 | 注册登录鉴权、基础对话、记忆子系统、Conductor 规划、计费、容器与模型池底座 |
| ⚠️ **配置齐备但未实测** | 依赖项已配置，链路未跑通验证 | 知识库解析/RAG、图片生成、语音、视频**生成**、生活服务、搜索类工具、定时任务、店铺/计费 |
| ⛔ **当前不可用（缺配置）** | 依赖未配置，运行时不可达 | **代码沙箱 / 深度思考沙箱产物 / SCF 技能 / 办公文件生成** |
| ⛔ **当前不可用（缺本地端）** | 依赖本地客户端或本机算力 | **控制用户电脑、视频渲染成片** |
| ⛔ **当前不可用（空表）** | 承载数据为 0 | **MCP 工具调用、API 工具** |
| ✅ **（曾）核心链路缺陷，已修复** | 曾经的用户链路断点，现已闭环 | **工具调用主干**（2026-09-29 修复并实测通过，见 §4 复核更新） |

**一句话**：当前 Web 环境能提供的是**「通用大模型文字性应答 + 已修复的工具调用主干」**（对话/问答/总结/翻译/检索/知识库问答/联网搜索等工具——工具主干已于 2026-09-29 修复，见 §4 复核更新）；而**文件产出、代码执行、视频成片、控制电脑**四类重活仍全部依赖未配置的云端沙箱或未接入的本地客户端。

---

## 2. 环境事实（实测）

### 2.1 容器拓扑

| 容器 | 状态 | 作用 |
|---|---|---|
| `llmops-api` | Up (healthy) | 业务 API（`APP_ENV=production`、`MODE=asgi`） |
| `llmops-ui` / `llmops-nginx` / `llmops-db` / `llmops-redis` / `llmops-neo4j` | Up | 前端 / 网关 / PG(pgvector) / Redis / 图数据库 |
| `llmops-celery` / `llmops-celery-beat` | Up | 异步任务 / 定时调度 |
| `llmops-browser-worker` | Up | **服务端** Playwright 浏览器自动化（`browser_automation_worker.py`） |
| `llmops-computer-worker` | Up | **容器内虚拟桌面**（`xvfb-run computer_control_worker.py`） |
| `llmops-kkfileview` | Up | 文件在线预览 |
| `llmops-render-worker` | **未启动** | 视频渲染；在 compose 中属 `profiles: ["cloud-render"]`，**默认不启动** |

### 2.2 外部依赖配置（关键）

| 依赖 | 配置 | 实测结果 |
|---|---|---|
| 代码沙箱 / SCF | `SANDBOX_URL=https://your-scf-url.tencentscf.com`（占位符）；`E2B_API_KEY`/`E2B_DOMAIN`/`SKILL_SCF_URL` **均未设置**；`ENABLE_CODE_EXECUTION_TOOL` 未设置 | **DNS 不解析 → 不可达** |
| OS 自动化（宿主机） | `OS_AUTOMATION_URL=http://host.docker.internal:8765` | **Connection refused** |
| 电脑控制（容器） | `COMPUTER_CONTROL_URL=http://llmops-computer-worker:8767` | 服务在（HTTP 501，仅 POST 端点）——但控制的是**容器虚拟桌面**，非用户真机 |
| 浏览器自动化 | `BROWSER_AUTOMATION_URL=http://llmops-browser-worker:8766` | 服务在（HTTP 501）——**服务端可达，Web 可用** |
| 桌面端设备 | `desktop_device` 3 条，`last_seen_at` 均为 **2026-09-11** | **当前无在线桌面端** |
| 对象存储 | `STORAGE_BACKEND=local` | 本地磁盘 |
| 已配置的第三方 Key | `ATLASCLOUD_API_KEY`、`GAODE_API_KEY`、`SERPAPI/SERPER/TAVILY/NEWSAPI/OPENWEATHERMAP/STABILITY`、`GITHUB_*`、`GOOGLE_CLIENT_*`、`WOLFRAM_ALPHA_APPID`、`LANGCHAIN_*`、`NEO4J_*`、`MAIL_*`、`COS_*` | 存在 |

### 2.3 模型池（`model_pool_config`）

| 类型 | 档位 | 状态 | 模型 | 备注 |
|---|---|---|---|---|
| chat | 0 | active | `tencent/Hunyuan-MT-7B` | 仅翻译 |
| chat | **1** | **active** | **`commandcode/deepseek/deepseek-v4.1-flash`** | **`capabilities=[]`（无工具调用声明）** |
| chat | 2 | active | `deepseek/deepseek-flash` | `capabilities` 含 **「工具调用」** |
| chat | 2/3 | disabled | SiliconFlow / opencode 若干 | 已禁用 |
| multimodal | 2 | active | `VolcanoArk/glm-5-3-flash` | 多模态视觉 |
| embedding / ocr / asr / tts / rerank / visual_embedding / image_generation / video_generation | — | **均有 active** | — | 图像/语音/视频/检索类模型齐备 |

### 2.4 承载数据量（`llmops` 库）

| 表 | 行数 | 含义 |
|---|---|---|
| `builtin_tool` | **75（全部 enabled）** | 内置工具"全开" |
| `api_tool` | **0** | 自定义 API 工具：无 |
| `mcp_provider` / `mcp_tool` | **12 / 0** | 12 个 MCP provider **一个工具都没同步成功** |
| `tool_invocation_audit` | **0** | **从未记录到任何一次工具执行** |
| `skill_package` | 25 `scf` + 132 `prompt` | 25 个 scf 技能因远端未配置不可执行 |
| `workflow` | 1 | 工作流近乎未用 |
| `external_data_source` | 1 | — |
| `conversation` | 353 | 以测试数据为主 |

### 2.5 容器内工具链

- `ffmpeg` / `ffprobe` / `tesseract` / `libreoffice` / `pandoc`：**api 容器内均不存在**（ffmpeg 仅以 `imageio-ffmpeg` Python 包形式存在）。
- `python-docx` / `python-pptx` / `openpyxl`：**可导入，但全仓代码零引用** → 不存在"本地进程生成办公文件"的通路。
- `unstructured`：可导入（知识库解析可用）。

---

## 3. 能力 × 运行时依赖矩阵

> 「Web 可用？」= 用户只开浏览器、不装桌面端、后端不做任何新配置时能否跑通。

### 3.1 文字性工作（当前主战场）

| 能力 | 载体 | Web 可用？ | 依赖与证据 |
|---|---|---|---|
| 注册/登录/鉴权 | `account_auth_routes` + JWT | ✅ **实测** | 真实 HTTP 200 |
| 基础对话（小钰） | `/assistant-agent/chat` SSE | ✅ **实测** | 落库答案正确（见 §4.1） |
| 记忆子系统 | Neo4j + `memory_*` | ✅ **实测（日志）** | 抽取/情感/新颖度/目标相关性/结果影响分析真实执行 |
| Conductor 规划 | `conductor_service` | ✅ **实测（日志）** | `ConductorPlanModel` 真实产出 |
| 计费 | `billing_*` 事件 | ✅ **实测** | `billing_started/delta/summary/final` 完整 |
| 知识库上传→解析→RAG | `02-knowledge-base` | ⚠️ **未实测** | ocr/asr/embedding/rerank 模型 active；`unstructured` 可用；未见打通证据 |
| 文档/表格/PPT **文件生成** | — | ⛔ **不可用** | 无生成工具（75 个内置工具中无）；`docx`/`powerpoint` 等技能为 `prompt` 型且无执行后端；沙箱不可用 → **只能输出文字，产不出真实 .docx/.pptx/.xlsx** |
| 代码执行 / 数据分析脚本 | `execute_code` | ⛔ **不可用** | 需 `ENABLE_CODE_EXECUTION_TOOL=1` + `E2B_API_KEY`/`E2B_DOMAIN`，均未配置 |
| 深度思考（含文件产物） | `deep_thinking_agent` | ⚠️ **静默降级** | `sandbox_enabled = need_sandbox and e2b_key and e2b_domain` → key 缺失 → **无声退回无沙箱**，无代码执行/无产物 |
| 翻译 / 总结 / 文案 / 问答 | LLM | ✅ 可用 | 不依赖工具 |

### 3.2 媒体与内容

| 能力 | Web 可用？ | 依据 |
|---|---|---|
| 图片生成 / 图片编辑（dalle3 / qwen / atlascloud / siliconflow / stability） | ⚠️ **未实测** | Key 齐 + `image_generation` 模型 active |
| 视频**生成**（hailuo / seedance / kling / vidu） | ⚠️ **未实测** | `ATLASCLOUD_API_KEY` + `video_generation` active |
| 语音识别 / 合成 | ⚠️ **未实测** | `asr` / `tts` 模型 active |
| 视频**剪辑**（trim/concat/subtitle） | ⛔ **很可能不可用** | 需 ffmpeg；api 容器无 ffmpeg（仅 `imageio-ffmpeg` 包），且未见媒体 worker |
| 视频**渲染成片**（`render_video` / HyperFrames） | ⛔ **不可用** | 设计为「本机优先」（`RENDER_LOCAL_ENABLED=true`）+ 云端 render worker **默认不启动** → **无执行者**（工具却 enabled=true） |

### 3.3 设备与自动化

| 能力 | Web 可用？ | 依据 |
|---|---|---|
| 浏览器自动化（服务端 Playwright） | ✅ **服务端可用** | `llmops-browser-worker` 在跑且内网可达；**不依赖用户本地** |
| 控制**用户真实电脑**（`computer_action` / `os_file_task` / `os_recycle_bin` / `os_snapshot`） | ⛔ **不可用** | 需桌面端在线；当前 **0 在线设备**；静态回退 `OS_AUTOMATION_URL` → **Connection refused** |
| 控制"容器虚拟桌面" | ⚠️ 技术在线但**对用户无价值** | `llmops-computer-worker` 是 `xvfb-run` 容器，控不到真机 |
| 桌面端面板（回收站/快照） | ⛔ 不可用 | 需安装桌面端 |

### 3.4 扩展能力

| 能力 | Web 可用？ | 依据 |
|---|---|---|
| 内置工具（75 个，全部 enabled） | ⚠️ **多数未验证** | 搜索/生活服务类 Key 齐；但**工具调用主干当前不通**（§4） |
| MCP 工具 | ⛔ **不可用** | 12 provider / **0 tool**；且 `ASSISTANT_MCP_BINDINGS=[]`（助手未绑任何 MCP）；同步失败还被静默吞掉 |
| 自定义 API 工具 | ⛔ **未配置** | `api_tool` 表 0 条 |
| 工作流 | ⚠️ 近乎未用 | `workflow` 仅 1 条 |
| 定时任务 | ✅ 可用 | `celery-beat` 在跑（`run-scheduled-tasks` 每分钟） |
| 店铺/分发/计费/订单 | ⚠️ 未实测 | 容器与表齐备 |

---

## 4. 🔴 用户链路端到端实测（本次体检的核心发现）

> **复核更新（2026-09-29 晚间）——本节 P0-1 已修复，P0-4 已重定性：**
> - **P0-1 工具调用主干：✅ 已修复并实测通过。** 修复（见 [execution-roadmap §3 AUDIT-P0](../prd/execution-roadmap.md)）：A1 能力归一化支持中文标签、A2 补齐默认模型 `tool_call` 能力数据、A3 四个 routing feature 补绑模型、B4 路由统一走 `OrchestratorService.decide`、C7 输出口新增伪工具调用剥离（流式状态机）、C8 无工具时不注入工具指令。**实测：修复前落库 `<search_knowledge_base>…`，修复后落库正常 Markdown 且出现原生 `agent_thought`(tool_calls)、`web_search` 被真实调用。**
> - **P0-4 流截断：重定性为 SSE 传输层收尾问题**——客户端已收全 `agent_end` / `billing_final` 后仍报 `incomplete chunked read`，**非业务异常**，优先级下调。
> - 因此下文 4.2/4.3 记录的是**修复前的现场证据**，保留作为该缺陷的历史快照与回归基线。

### 4.1 实测方法

以真实账号（`testexec`，active）签发合法 JWT，向**前端真实调用的入口** `POST /assistant-agent/chat`（SSE）发起 3 条真实用户请求，观察事件流、服务端日志与落库结果。

### 4.2 实测结果

| 用例 | HTTP | 事件流 | 落库答案 | 判定 |
|---|---|---|---|---|
| 纯对话：「你好，请用一句话介绍你自己」 | 200 | 正常（~51s） | `你好！我是小钰，一个可以陪你聊天、查资料、处理文件和帮你完成各种任务的智能助手。` | ✅ **通** |
| 工具：「北京今天天气怎么样？请给出温度和天气状况」 | 200 | ~60s 后**服务端截断**（`ASGI callable returned without completing response`） | **原始标记文本**（非答案） | ❌ **断** |
| 工具：「帮我搜索一下最近有什么重要的人工智能新闻，给两条」 | 200 | 同上 | **原始标记文本**（非答案） | ❌ **断** |

两条失败用例落库的"答案"实际是模型输出的**未解析工具调用标记**：

```text
<|DSML|tool_calls>
<|DSML|invoke name="route_public_agents">
<|DSML|parameter name="task">查询北京今天的天气情况，需要给出当前温度和天气状况</|DSML|parameter>
...
```

即：**用户问天气，小钰回了一堆诡异符号，什么也没查到。**

### 4.3 根因（已定位到代码）

1. 助手对话恒用 `FunctionCallAgent`（`assistant_agent_service.py:564`），其 `_llm_node` **本身有能力闸门**：仅当 `ModelFeature.TOOL_CALL in llm.features` 且 `bind_tools` 可用且 `tools` 非空时才绑定工具（`function_call_agent.py:219-226`）。
2. 默认（tier-1）chat 模型 `commandcode/deepseek/deepseek-v4.1-flash` 的 `model_pool_config.capabilities` **是字面空数组 `[]`** → 归一化后 `features` 不含 `TOOL_CALL` → **闸门按设计跳过工具绑定**。（注意：`language_model_manager._normalize_capability_to_feature` 的中文标签映射**已修复**，此处并非映射问题，而是该字段真的为空。）
3. 但系统提示词仍**承诺**模型可调用工具（如 `route_public_agents` / `search_knowledge_base`，见 `system_prompts.yaml:151-155`）→ 模型在"无真工具"时**自造工具调用标记**（本次实测为 `<|DSML|tool_calls>` 形态）并流式输出；
4. 输出口**无伪工具调用剥离**（全仓无 DSML 解析，grep 零命中）→ 标记作为正文落库并展示给用户；
5. 流在约 60s 处异常中断（`ASGI callable returned without completing response`，无 traceback），待进一步定位。

**旁证**：`tool_invocation_audit` **0 行**——该环境从未记录到任何一次工具执行（写入点 `tool_invoker_service.py:170`）。

> **后续**：本项由 [用户端工具链与路由硬化设计](../archive/superpowers-specs/2026-09-29-user-tool-chain-routing-hardening-design.md) 修复，**已于 2026-09-29 落地并实测通过**（见本节顶部复核更新）。

---

## 5. 与现有文档结论的差异（需修正）

| 文档结论（product-vision §三） | 本次复核 |
|---|---|
| #6「内容生成：PPT/文档/表格/改图/短视频 ✅ 真可用 — 技能与 builtin tool 均已实现」 | **不成立**：无任何办公文件生成工具；`docx`/`powerpoint` 技能为 `prompt` 型且无执行后端；沙箱不可用。**改图/短视频生成**另有模型支撑（未实测） |
| #1「注册→登录→首页助手流式对话 ✅ 真可用」 | **部分成立**：纯文本对话通；**一旦需要工具即失败** |
| #9/#10「对话里让小钰操作电脑 ✅ 真可用」 | **当前环境不成立**：无在线桌面端、宿主机端点 refused；9 月的"端到端实测通过"是**当时有本地桌面端在线**的条件下 |
| #11「知识库视频素材 … 视频轻量剪辑三件套 ✅」 | **待核**：视频剪辑依赖 ffmpeg，api 容器内无 ffmpeg |
| §三-24「AI 助手计费 ✅」 | **成立**（本次实测 billing 事件完整） |

> 结论：产品总纲的「✅」多来自**系统性单测/当时的本地联调**，**不能代表当前 Web-only 环境**。这正是本次体检要补的缺口。

---

## 6. 生产就绪度缺陷清单（按优先级）

### P0（核心链路/虚假可用，必须尽快处理）

| # | 缺陷 | 证据 | 影响 |
|---|---|---|---|
| ~~P0-1~~ | ~~**工具调用主干失效**~~ → ✅ **已修复（2026-09-29）** | 修复前见 §4 实测 + `tool_invocation_audit=0` | 已闭环并实测（`web_search` 被真实调用、`agent_thought`(tool_calls) 出现）；保留为回归基线 |
| P0-2 | **沙箱全线未配置**（代码执行、深度思考产物、SCF 技能） | `E2B_*`/`SKILL_SCF_URL` 未设置、占位符 DNS 失败 | 文件产出/代码执行/25 个 scf 技能不可用；且深度思考**静默降级**，用户与管理员均无感知 |
| P0-3 | **视频渲染无执行者** | `cloud-render` profile 默认关闭 + 无在线桌面端 | `render_video` 工具 `enabled=true` 却必然失败 → 虚假可用 |
| P0-4 | **SSE 流收尾（传输层）** | `ASGI callable returned without completing response`（约 60s）；2026-09-29 复核：客户端已收全 `agent_end`/`billing_final` 后仍报 `incomplete chunked read` | **非业务异常**，重定性为传输层收尾问题，优先级下调 |
| P0-5 | **MCP 全量不可用且失败被静默吞掉** | 12 provider / 0 tool；同步失败仅日志 | MCP 生态能力为 0；管理员以为配置成功 |

### P1（可用性/一致性）

| # | 缺陷 | 说明 |
|---|---|---|
| P1-1 | **75 个内置工具"全开"制造虚假可用性** | 未做"依赖缺失即不可用"的联动（对比：本次已修的技能同步状态是正确范式） |
| P1-2 | **缺用户链路自动化测试** | 现有测试均为单点/组合 API（系统性）；本次 P0-1 正是**用户链路测试缺失**才长期潜伏 |
| P1-3 | **控制用户电脑的 5 个工具在前端未见"需桌面端"提示** | 用户点了必然失败 |
| P1-4 | **`/studio` 占位页仍挂侧边栏入口** | product-vision 已记录，未处理 |

---

## 7. 下一步修复方向

### 7.1 立即（P0-1）：让"工具调用"这条主干活起来 —— ✅ **已完成（2026-09-29）**

> 实际落地以 [用户端工具链与路由硬化设计](../archive/superpowers-specs/2026-09-29-user-tool-chain-routing-hardening-design.md) 的 A/B/C/D 方案为准（A1 中文能力归一化 / A2 补模型能力数据 / A3 routing feature 补绑模型 / B4 路由统一 / C7 伪工具调用剥离 / C8 无工具不注入工具指令），已实测通过。以下原始建议保留作为问题记录。

1. **换默认模型**：把 chat tier-1 换成**声明「工具调用」能力**的 active 模型（现成的 `deepseek/deepseek-flash` 即含该能力），并在模型池配置上**强制要求**：作为助手主模型的条目必须声明 `工具调用`。
2. **补能力闸门**：助手链路（`assistant_agent_service.py:564`）对齐 `app_runtime_service.py:749` 的能力判断；
3. **让失败可见**：`FunctionCallAgent` 绑定工具后，若模型未按协议返回 `tool_calls` 而疑似输出原生标记（含 `<|DSML|`、`tool_calls` 等），**必须识别并降级**（要么解析、要么剥离并告知用户"工具调用失败"），**禁止把标记当正文**；
4. **验证方式**：新增用户链路冒烟用例——断言一次"天气/搜索"提问后 `tool_invocation_audit` **新增一条**且答案中不含标记。

### 7.2 明确"干不了的重活"的处置（二选一，不要悬空）

| 重活 | 选项 A（接通） | 选项 B（诚实下线） |
|---|---|---|
| 代码执行 / 文件生成 / 深度思考产物 | **已有设计**：[沙箱配置治理与多后端热切换设计](../archive/superpowers-specs/2026-09-29-sandbox-config-multi-backend-design.md)——沙箱入库 admin 可配 + 多后端热切换，`resolve_runtime` 唯一入口返回显式 `enabled/reason` | 沙箱不可用时**显式告知用户"该能力未开通"**，并把相关工具置 `enabled=false` |
| 视频渲染成片 | `docker compose --profile cloud-render up -d llmops-render-worker` | 标记为"需本机"，前端隐藏/提示需桌面端 |
| 控制用户电脑 | 引导安装桌面端并登录（`desktop_device` 在线） | 前端按"设备在线数=0"置灰入口 |
| MCP | 配好可用 provider 并修复同步失败可见性 | 暂时从能力清单移除，避免误导 |

### 7.3 机制建设（防复发）

1. **工具 enabled 与依赖配置联动**：为每个内置工具标注所需凭证/端点，缺失时自动置"未配置"（复用本次 `not_configured` 的诚实状态范式），而非一律 `enabled=true`。
2. **建立「用户链路冒烟测试」**（少量但覆盖主干）：
   - 对话主干：1 条纯文本（断言有答案）
   - 工具主干：1 条需工具（断言 `tool_invocation_audit` 增长）
   - 知识库主干：上传 1 个小文件 → 检索命中
   - 媒体主干：1 条图片生成（断言产物 URL 可下载）
   纳入 CI，失败即阻断——这是当前**系统性测试无法覆盖**的部分。
3. **环境自检端点**：把本次 §2 的探针（沙箱/OS/浏览器/渲染/MCP/模型工具能力）做成 `GET /healthz/dependencies`，管理员一眼看到"哪些能力真能用"。

### 7.4 开发路径建议（顺序）

```
第一步：P0-1 工具调用主干（换模型 + 能力闸门 + 标记降级 + 冒烟用例）   ← 收益最大
第二步：P0-2 决策沙箱路线（接通 or 诚实下线）           ← 决定"能不能产出文件"
第三步：P0-3/P0-5 渲染与 MCP 的接通 or 下线
第四步：P1-1 工具 enabled × 依赖联动 + 环境自检端点     ← 防复发
第五步：P1-2 用户链路冒烟测试纳入 CI                    ← 保证"车能一直跑"
```

---

## 8. 附：本次体检的原始证据

| 证据 | 内容 |
|---|---|
| 端点可达性 | 沙箱：`Name or service not known`；OS 自动化：`Connection refused`；电脑/浏览器 worker：`HTTP 501` |
| 关键环境变量 | `SANDBOX_URL=<占位符>`；`E2B_API_KEY`/`E2B_DOMAIN`/`SKILL_SCF_URL` 未设置；`OS_AUTOMATION_URL=http://host.docker.internal:8765`；`COMPUTER_CONTROL_URL=http://llmops-computer-worker:8767`；`BROWSER_AUTOMATION_URL=http://llmops-browser-worker:8766`；`RENDER_LOCAL_ENABLED=true` |
| 数据表 | `builtin_tool=75(全 enabled)`、`api_tool=0`、`mcp_provider=12`、`mcp_tool=0`、`tool_invocation_audit=0`、`workflow=1`、`desktop_device=3(2026-09-11)`、`skill_package` 25 scf + 132 prompt |
| 容器内工具链 | api 容器：`ffmpeg/ffprobe/tesseract/libreoffice/pandoc` 均无；`python-docx/pptx/openpyxl` 可导入但代码零引用 |
| 用户链路实测 | 纯对话 ✅ 落库正确；两条工具用例 ❌ 落库为 DSML 标记文本 + 服务端 `ASGI callable returned without completing response` |
| compose | `llmops-render-worker` 属 `profiles: ["cloud-render"]`（默认关闭） |

> 探针脚本为一次性验证用途，已删除；**未对业务数据做任何写入**（仅产生 1 条测试对话与 3 条消息）。
