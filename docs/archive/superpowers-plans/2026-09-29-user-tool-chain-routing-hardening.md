# 用户端工具链与路由硬化实施计划（plan）

配套 spec：`docs/superpowers/specs/2026-09-29-user-tool-chain-routing-hardening-design.md`
执行顺序：A（根因）→ B（链路一致性）→ C（防御）→ D（配置文档）→ 回归与文档同步。

## Task A1 — 能力标签归一化支持中文
- 文件：`api/internal/core/language_model/language_model_manager.py`
- 改动：扩展 `_CAPABILITY_LABEL_TO_FEATURE`，覆盖 `工具调用/函数调用/深度推理/推理/智能体推理/图片输入/多模态/视觉/JSON输出` 等中文标签（映射到既有 `ModelFeature`）。
- 验收：新增单测 `api/test/internal/core/language_model/test_capability_normalization.py`，断言中文标签归一化为对应 `ModelFeature`，未知标签返回 `None`。
- 接线：既有唯一入口 `_normalize_capability_to_feature`，无新增调用点。

## Task A2 — 修正模型能力数据 + 连通性验证
- 先用最小请求验证 `commandcode/deepseek/deepseek-v4.1-flash` 支持原生 function calling。
- 通过 admin 模型池（或 SQL 数据订正）把该模型 `capabilities` 补为含 `tool_call`（及必要能力）。
- 验收：`get_feature_model('assistant_agent')` 实例 `features` 含 `tool_call`；一次真实对话产生 `agent_thought`(tool_calls) 事件。

## Task A3 — 补绑 routing feature 模型
- 为 `task_classification` / `tool_selection` / `pool_intent_resolution` / `public_agent_router` 绑定可用 chat 模型（admin 数据）。
- 验收：`get_feature_model(<key>)` 非 None；`task_classifier` 可走 LLM 兜底。

## Task B4 — 统一路由入口
- 文件：`api/internal/service/assistant_agent_service.py`
- 改动：删除 `use_conductor` 直连分支（约 1710-1742 行），路由统一由 `orchestrator_service.decide()` 产出（其内部按 `ENABLE_CONDUCTOR` 调用完整 `conductor.decide()`）。保留 `os_automation` 前置分支与缺失兜底。
- 验收：既有 `test_assistant_agent_service.py` 相关用例通过；`ENABLE_CONDUCTOR=true` 时助手路径产生 `routing_log`，且 `routing_decision.tool_subset` 非 None。

## Task B5 — 拦截与门控
- `reject_or_confirm`：在 `assistant_agent_service` 分发处输出拒绝/澄清文案并终止（不再落到 `_stream_single_agent`）。
- `repair_plan`：`_build_plan_repairer` 增加 `ENABLE_CONDUCTOR` 判定，关闭时不注入修复器。
- 验收：单测覆盖两条分支。

## Task C7 — 伪工具调用剥离 + 去重
- 新增单一函数 `strip_pseudo_tool_call_markup(text)`（放 `api/internal/core/agent/entities/`），识别已知工具标签（`search_knowledge_base`、`dataset_retrieval`、`_XML_TOOL_CALL_TAG_NAMES`/`_XML_PARAMETER_TAG_NAMES` 等）构成的完整块并剥离。
- 在 `FunctionCallAgent._llm_node` 流式与 `_finalize_llm_output` 应用（同一函数）；流式用前缀回撤缓冲避免跨 chunk 泄漏。
- `AGENT_MESSAGE` 事件不再令 `thought==answer`（消除重复显示）。
- 验收：单测 `test_pseudo_tool_call_stripping.py`：整块、跨 chunk、非工具 `<` 内容不被误删。

## Task C8 — 无工具时不注入工具指令
- 新增 prompt 变体 `agent_system_prompt_template_no_tools`（`system_prompts.yaml`），`_call_model_node` 依据"模型是否可绑定工具"选择模板。
- 验收：模型 `features` 无 `tool_call` 时系统提示不含工具调用指令。

## Task D9/D10 — 配置与文档
- `.env.example` 补 `EXA_API_KEY` / `BRAVE_SEARCH_API_KEY` / `XAI_API_KEY`。
- 文档标注 scf 技能 `not_configured` 语义（已存在于 01-agent-tool-pool.md §13，复核即可）。

## 收尾
- 跑后端与前端测试；更新 `docs/prd/modules/01-agent-tool-pool.md`、`03-orchestration-infra.md`、`07-public-ai-config.md` 相关章节；`python -m graphify update .`。
