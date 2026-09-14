# 已交付模块隐患巡检 · 轮转台账

> **定位**：非权威区（`docs/research/`）的巡检进度台账。每晚只深挖一个模块，按 `module_slug` 顺序轮转。
> **稳定标识说明**：本表用 `module_slug`（不变的文件名主干/稳定短名）而非中文标题记录模块，避免模块重命名导致轮转错位。
> **候选来源**：`docs/prd/product-vision.md`（经代码验证的落地状态）+ `docs/prd/execution-roadmap.md`（状态标记为 ✅ 完成的能力），主线为 `docs/prd/modules/01~09`，并纳入已标完成的其他主线能力（记忆系统、计费/分销、权限与账号体系）。
> **轮转规则**：取「上次扫描记录之后的下一个模块」；一轮轮完后从第一个模块重来并把该行 `round` 加 1，注明「新一轮开始」。台账无法读写时退而依据 git log 或 `audit:<module_slug>` 标签推断，并在会话中说明依据。

## 模块清单与进度

| module_slug | module_name | round | last_scanned | findings_p0_p1_p2_p3 | issue_numbers |
|---|---|---|---|---|---|
| 01-agent-tool-pool | Agent 池与工具池 | 1 | 2026-09-14 | 0/3/2/1 | #1, #2, #3, #4, #5, #6 |
| 02-knowledge-base | 知识库双层设计 | 0 | — | — | — |
| 03-orchestration-infra | Conductor 编排、执行协调与可观测性 | 0 | — | — | — |
| 04-social-creator | 合伙人分身与内容板块（生态赋能） | 0 | — | — | — |
| 05-security-risk-decisions | 安全要求与风险决策 | 0 | — | — | — |
| 06-file-storage | 文件存储与对象存储 | 0 | — | — | — |
| 07-public-ai-config | 公共 AI 资源配置 | 0 | — | — | — |
| 08-os-automation | OS 自动化与设备 Agent | 0 | — | — | — |
| 09-desktop-client | Windows 桌面客户端（设备 Agent 宿主壳） | 0 | — | — | — |
| memory-system | 记忆系统 | 0 | — | — | — |
| commerce-distribution | 计费 / 定价 / 分销 | 0 | — | — | — |
| auth-rbac | 权限与账号体系 | 0 | — | — | — |

> `findings_p0_p1_p2_p3` 为「P0/P1/P2/P3」四级问题数量。`round` 为已完成的扫描轮次；`0` 表示尚未扫描。

## 扫描记录

### round 1 · 2026-09-14 · 01-agent-tool-pool（Agent 池与工具池）

- **权威状态出处**：`docs/prd/execution-roadmap.md` §1（Phase 2/3/4 ✅ 完成）、§3.1（P0-1~P1-5 全部 ✅ 已完成）；`docs/prd/modules/01-agent-tool-pool.md` §8~§10；`docs/prd/product-vision.md` §三（第 2/3/23 项 ✅ 真可用）。
- **覆盖维度**：业务性（治理模式三阶段、组合工具部分阻断、候选收集/过滤/排序）、安全性（风险枚举一致性、确认流程、权限点、越权）、交互性（加载/空/错误/禁用态、i18n）、前后端一致性（枚举、字段、接口路径、权限点）。
- **前后端代码入口**：
  - 后端：`api/internal/service/agent_pool_service.py`、`tool_inventory_service.py`、`composite_tool_resolver.py`、`runtime_tool_governance_gate.py`、`governance_mode_resolver.py`、`governance_audit_logger.py`、`app_runtime_service.py`（`build_runtime_tools_for_config`）、`admin_agent_pool_service.py`、`admin_tool_governance_service.py`、`orchestration_release_check_service.py`。
  - 前端：`ui/src/views/admin/AgentPoolView.vue`、`ToolGovernanceView.vue`、`OrchestrationFlagsView.vue`、`RoutingLogsView.vue`、`ui/src/components/GovernanceModeBanner.vue`、`ui/src/utils/semantic-labels.ts`。
- **结论**：发现 6 项隐患（P0×0 / P1×3 / P2×2 / P3×1），均已建 issue 并打 `audit:01-agent-tool-pool` + `needs-triage` + 优先级标签。
  - #1 [P1] 工具治理风险等级枚举三方不一致（admin `low/medium/high/critical` vs 运行时 `safe/low/medium/high/sensitive/dangerous`），高风险工具在阶段 2 静默放行。
  - #2 [P1] `orchestration_release_check_service` 引用不存在的 `ToolGovernancePolicy.status` 列且 import 未导出，敏感工具治理校验恒为 False（异常被吞）。
  - #3 [P1] `AgentPolicyFilter` 风险过滤仅拦 `high`，`sensitive/dangerous` 经归一化静默降级为 `safe`。
  - #4 [P2] `AgentPoolView` 统计卡用当前页数组长度替代全量 stats 接口，翻页即变。
  - #5 [P2] 池治理页面 read 角色可见写操作、删除无二次确认、`Promise.all` 权限耦合致整页失败。
  - #6 [P3] 池治理/观测页面 i18n 缺口（硬编码文案、`source_type` 语义映射用错表、`riskLevel` 缺 `low/critical`、`fallback` 缺 `orchestrator`）。
- **备注**：`ToolInvokerService`（`tool_invoker_service.py`，含 `dangerous` 强拦截与注入检测）**未接线到任何生产调用点**（仅测试引用），属设计已就绪但运行期未启用的组件，本次未计为隐患，仅记录待确认。
- **下一晚扫描**：`02-knowledge-base`（知识库双层设计）。
