# 用户端工具链与路由硬化设计（spec）

- 状态：在途（2026-09-29）
- 触发问题：用户提问「帮我查一下 jev 模型是什么东西」，小钰（用户端助手）回复泄漏 XML 伪工具调用
  `<search_knowledge_base><query>jev模型</query></search_knowledge_base>`
- 结论：**不是模型不支持工具调用，而是后端"能力闸门"把工具层与调用链切断**，叠加"提示词承诺工具、运行时没有工具"的错配，以及"输出口无伪工具调用剥离"。

## 1. 根因（代码 + 数据库实证）

1. 路由：`orchestration_feature_flag.ENABLE_CONDUCTOR` 实测为 `true`（代码默认 false，DB 被开启）。助手入口走 `AssistantAgentService` 直连 `conductor_service.plan()`。
2. 执行器：`message_agent_thought` 记录显示本次只有 `long_term_memory_recall` + 一串 `agent_message` 文本分片，**无 `agent_thought`（tool_calls）/ `agent_action`（工具执行）** → 执行器为 `FunctionCallAgent`，且 `bind_tools` 未生效。
3. 闸门：`FunctionCallAgent._llm_node` 仅在 `ModelFeature.TOOL_CALL in llm.features` 时 `bind_tools`。`assistant_agent` 绑定的 `commandcode/deepseek/deepseek-v4.1-flash` DB `capabilities=[]` → `features=[]` → 跳过绑定。
4. 提示词：`agent_system_prompt_template` 第 4/6 条写死"必须调用 `search_knowledge_base`"，模型无真工具只能自造 XML。
5. 无剥离：流式原样透传（仅敏感词），`_finalize_llm_output` 仅洗沙箱路径；全仓唯一 XML 解析是 `write_file` 特例。

## 2. 系统性缺陷（比单模型严重）

- `_normalize_capability_to_feature` 的 `_CAPABILITY_LABEL_TO_FEATURE` **只认英文别名**，中文能力标签（`工具调用`/`深度推理`/`JSON输出`…）全部静默丢弃；全仓无第二处中文映射。
- `public_ai_feature_config` 实测：几乎所有 feature 被指到同一个 `capabilities=[]` 的模型；`task_classification` / `tool_selection` / `pool_intent_resolution` / `public_agent_router` **完全未绑模型**。

## 3. 指挥官路由缺陷（实测）

- `ENABLE_CONDUCTOR=true`，指挥官确在调度，但助手入口的 `to_routing_decision_dict()` 自断三处：`tool_subset=None`（动态 skills/api/mcp 不挂载）、`needs_deep_thinking=False`（恒关深度思考）、`reject_or_confirm` 不拦截。
- 存在两条平行实现：助手入口 `plan()`（残缺）与其余渠道 `orchestrator.decide()`（完整，补齐 tool_subset/cost_policy/深度思考增强/路由日志）。
- `routing_log` 实证：assistant 最后记录停在 2026-09-07，本次 jev 对话无日志 → 启用指挥官后路由不可观测。
- 旁路：执行失败重规划 `repair_plan` 不受 `ENABLE_CONDUCTOR` 门控。

## 4. 工具 / Skills 可用性（实测）

| 组件 | 实测 | 说明 |
|---|---|---|
| builtin 工具 | 36 provider / 75 tool | 已装配，未绑给模型（闸门） |
| 联网搜索 `web_search` | 已挂首页助手 | 多 provider 降级；密钥多为占位符 → 只剩 ddgs |
| MCP | 12 provider | 依赖 `tool_subset` → 指挥官模式下不挂 |
| Skills | 157（prompt 132 / scf 25） | scf 需 `SKILL_SCF_URL`（当前占位符）；仅经 `tool_subset` 挂载 |

## 5. 方案（A+B+C+D）

### A. 根因修复
- **A1**：`_normalize_capability_to_feature` 增加中文标签映射（收敛到既有唯一权威入口，不新建机制）。
- **A2**：修正模型能力数据：`commandcode/deepseek/deepseek-v4.1-flash` 补齐真实能力（含 `tool_call`）；先做最小连通性验证。
- **A3**：为 `task_classification` / `tool_selection` / `pool_intent_resolution` / `public_agent_router` 绑定可用模型。

### B. 链路一致性（消除平行实现）
- **B4**：删除助手入口直连 `conductor.plan()` 分支，统一走 `orchestrator_service.decide()`（其内部在 `ENABLE_CONDUCTOR` 开启时调用完整的 `conductor.decide()`）。附带修复 tool_subset 丢失、深度思考恒关、路由日志缺失。
- **B5**：`reject_or_confirm` 真正拦截（输出拒绝/澄清并终止）；`repair_plan` 纳入 `ENABLE_CONDUCTOR` 门控语义。

### C. 防御
- **C7**：单一权威"伪工具调用标签剥离"逻辑，应用于 `FunctionCallAgent` 的流式输出与最终输出；流式采用"前缀回撤缓冲"避免跨 chunk 标签泄漏；同时修 `thought`/`answer` 重复赋值。
- **C8**：模型无法绑定工具时，不把工具指令写进 system prompt（使用无工具指令的模板变体）。

### D. 配置与文档
- **D9**：`.env.example` 补 `EXA_API_KEY` / `BRAVE_SEARCH_API_KEY` / `XAI_API_KEY` 等被代码读取却未登记的键。
- **D10**：scf 技能同步状态（`not_configured`）标注与文档说明。

## 6. 接线自检要求（完成后逐条回答）

- A1：`_normalize_capability_to_feature` 的调用方（`_build_model_entity`）→ `get_feature_model` → `FunctionCallAgent`。
- B4：唯一路由入口 = `OrchestratorService.decide`。
- C7：剥离函数被流式与最终输出两处调用（同一函数，逻辑单一）。
- A2/A3：DB 数据变更，同时确认 admin 端可继续编辑。

## 7. 判定（轮胎 vs 补丁）

核心能力层（`bind_tools` 闸门、`_normalize_capability_to_feature`、`get_feature_model`、`_build_tool_subset`、输出口）均为单一权威入口 → 属「轮胎 + 系统性洞口」，处置为**补洞口 + 修数据 + 消平行**，不推倒重建，且不引入第二套机制。
