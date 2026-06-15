# 通用 Agent 调度平台 Phase 4 执行计划

## 1. 阶段目标

Phase 4 目标是完成动态工具检索与运行时工具挂载闭环，让 Agent 不再只能依赖预绑定工具，而是可以在受控策略下从工具池召回、过滤、排序、挂载并调用少量授权工具。

本阶段以 MCP 作为首个动态运行时试点，同时保持 RuntimeToolAdapter 抽象对 API、Builtin、Knowledge、Workflow 等工具类型开放。

## 2. 执行原则

- 所有生产代码变更先写失败测试，再实现最小代码通过。
- 保持 AppConfig.mcp_bindings 兼容。
- 不把完整工具池暴露给 Agent。
- 普通用户不能通过伪造工具名绕过挂载和策略检查。
- sensitive / dangerous 工具默认拒绝自动调用。
- 每个任务完成后更新本文件完成记录。
- 阶段结束必须跑 Docker 后端全量和前端 type-check / lint / unit test。

## 3. 任务清单

### 3.1 任务 0：基线确认与执行文档创建

#### 目标

确认 Phase 3 已提交且工作区干净，创建本执行文档，跑基线门禁。

#### 验收标准

- [ ] 工作区从 Phase 3 commit 后干净开始。
- [ ] Phase 4 执行文档已创建。
- [ ] 后端 Docker 全量测试通过。
- [ ] 前端 Docker type-check / lint / unit test 通过。

#### 完成记录

- [x] Phase 3 commit 后工作区干净开始：`979fc5a feat(orchestration): complete phase 3 tool governance`。
- [x] Phase 4 执行文档已创建。
- [x] 后端 Docker 全量基线通过：2025 passed / 6 skipped。
- [x] 前端 Docker type-check / lint / unit test 基线通过：97 files / 349 tests passed。

### 3.2 任务 1：定义运行时工具抽象

#### 目标

新增运行时工具实体，用于描述被挂载的工具、调用请求和调用结果。

#### 验收标准

- [ ] RuntimeToolDescriptor 可以表达 tool_id、runtime_name、source_type、provider、schema、metadata、audit_context。
- [ ] RuntimeToolCallRequest 可以表达 runtime_name、arguments、account_id、agent_id、request_id。
- [ ] RuntimeToolCallResult 可以统一表达 success / output / error / latency / audit payload。
- [ ] 单元测试覆盖归一化和默认值。

#### 完成记录

- [x] 新增 RuntimeToolDescriptor，支持候选工具到运行时描述的归一化。
- [x] 新增 RuntimeToolCallRequest，支持 runtime_name、arguments、account_id、agent_id、request_id 归一化。
- [x] 新增 RuntimeToolCallResult，统一 success/failure 输出结构。
- [x] 聚焦测试通过：`test/internal/entity/test_runtime_tool_entity.py` 3 passed。

### 3.3 任务 2：实现 RuntimeToolMountService

#### 目标

将 selected tool subset 和预绑定工具合并成 Agent 本次可见的 runtime tools。

#### 验收标准

- [ ] 合并动态工具和预绑定工具。
- [ ] 按 runtime_name 去重，动态工具优先。
- [ ] 控制 max_tool_count。
- [ ] 生成 audit_context。
- [ ] Agent 只能看到 mount 返回的工具子集。

#### 完成记录

- [x] 新增 RuntimeToolMountService，支持动态工具和预绑定工具合并。
- [x] 按 runtime_name 去重，动态工具优先。
- [x] 支持 max_tool_count 和 hidden_tools reason。
- [x] 输出 account_id、agent_id、request_id、mounted_runtime_names 审计上下文。
- [x] 聚焦测试通过：`test/internal/service/test_runtime_tool_mount_service.py` 3 passed。

### 3.4 任务 3：实现 MCP Runtime Adapter

#### 目标

将 MCP 候选工具转换为 RuntimeToolDescriptor，作为动态工具挂载首个试点。

#### 验收标准

- [ ] MCP candidate 可转换为 runtime descriptor。
- [ ] runtime_name 稳定且避免和非 MCP 工具冲突。
- [ ] provider_id、tool_name、permission_scope、risk_level 进入 audit_context。
- [ ] 非 MCP candidate 不由 MCP adapter 处理。

#### 完成记录

- [x] 新增 McpRuntimeAdapter，支持 MCP candidate 转 RuntimeToolDescriptor。
- [x] runtime_name 使用 `mcp__provider__tool` 稳定命名并清理特殊字符。
- [x] provider_id、risk_level、permission_scope 进入 audit_context。
- [x] 非 MCP candidate 不处理。
- [x] 聚焦测试通过：`test/internal/service/test_mcp_runtime_adapter.py` 3 passed。

### 3.5 任务 4：实现 ToolInvoker

#### 目标

提供统一工具调用入口，确保只能调用已挂载工具，并统一处理 schema、风险、超时和错误。

#### 验收标准

- [ ] 未挂载工具返回 tool_not_mounted。
- [ ] 输入缺少 required 字段返回 invalid_arguments。
- [ ] sensitive / dangerous 未确认返回 confirmation_required 或 forbidden。
- [ ] 已挂载 safe 工具可调用 adapter executor。
- [ ] 调用失败返回标准错误结构。

#### 完成记录

- [x] 新增 ToolInvokerService 统一调用入口。
- [x] 未挂载工具返回 tool_not_mounted。
- [x] 输入缺少 required 字段返回 invalid_arguments。
- [x] high risk 未确认返回 confirmation_required。
- [x] 已挂载 safe 工具可调用 executor，执行失败返回 tool_execution_failed。
- [x] 聚焦测试通过：`test/internal/service/test_tool_invoker_service.py` 5 passed。

### 3.6 任务 5：工具调用审计日志

#### 目标

记录每次工具调用摘要，支撑后续治理和问题排查。

#### 验收标准

- [ ] 成功和失败调用均产生审计 payload。
- [ ] 审计 payload 包含 tool_id、runtime_name、source_type、account_id、agent_id、request_id、latency、status、failure_reason。
- [ ] 不记录完整敏感输入，只记录 input_summary。

#### 完成记录

- [x] 新增 ToolInvocationAuditService，统一构建工具调用审计 payload。
- [x] 成功和失败调用均包含 tool_id、runtime_name、source_type、account_id、agent_id、request_id、latency、status、failure_reason。
- [x] input_summary 只记录参数 key，并标记 api_key/token/password/secret/credential 等敏感 key。
- [x] ToolInvokerService 已复用审计服务输出 audit_payload。
- [x] 聚焦测试通过：`test_tool_invocation_audit_service.py` 与 `test_tool_invoker_service.py` 共 7 passed。

### 3.7 任务 6：安全拒绝路径

#### 目标

强化动态工具调用安全边界。

#### 验收标准

- [ ] 普通用户伪造工具名不能绕过 ToolPolicy。
- [ ] prompt injection 要求调用未挂载或敏感工具时被拒绝。
- [ ] permission_scope 不匹配时拒绝调用。
- [ ] forbidden / confirmation_required / tool_not_mounted reason 稳定。

#### 完成记录

- [x] 未挂载工具稳定返回 tool_not_mounted。
- [x] sensitive/high 工具未确认返回 confirmation_required。
- [x] dangerous 工具即使确认也返回 forbidden。
- [x] owner 私有工具 owner 不匹配返回 permission_scope_denied。
- [x] 聚焦测试通过：`test/internal/service/test_tool_invoker_service.py` 8 passed。

### 3.8 任务 7：动态 public MCP 集成验收

#### 目标

验证 Agent 未显式绑定 public MCP 时，也能通过动态工具池召回、挂载并调用 public MCP。

#### 验收标准

- [ ] public MCP 可被动态召回和挂载。
- [ ] sensitive MCP 不自动挂载或不可自动调用。
- [ ] 动态 MCP 与预绑定 MCP 合并去重。
- [ ] 工具调用失败时返回 fallback 标准结构。

#### 完成记录

- [x] 新增 DynamicMcpRuntimeService，串联 collector、policy_filter、ToolRanker、McpRuntimeAdapter、RuntimeToolMountService。
- [x] public MCP 可动态召回、转换、挂载。
- [x] dangerous MCP 被过滤并进入 filtered_out_tools。
- [x] 动态 MCP 与预绑定 MCP 按 runtime_name 去重，动态工具优先。
- [x] runtime 构建异常返回 fallback 标准结构。
- [x] 聚焦测试通过：`test/internal/service/test_dynamic_mcp_runtime_service.py` 2 passed。

### 3.9 任务 8：Admin 可观测增强

#### 目标

增强 Admin Tools 页面展示 runtime/mount 状态和过滤原因。

#### 验收标准

- [ ] 前端 service 类型包含 runtime_name、mounted、mount_reason、filtered reason。
- [ ] Admin Tools 页面展示 runtime_name 和 filtered_out_tools。
- [ ] 前端单测覆盖治理字段展示。

#### 完成记录

- [x] ToolInventory API 候选项新增 runtime_name、mounted、mount_reason。
- [x] 前端 ToolInventory service 类型新增 runtime/mount 字段。
- [x] Admin ToolsView 展示 runtime_name、mount_reason 和 filtered_out_tools reason。
- [x] 聚焦测试通过：后端 ToolInventory handler 2 passed，前端 ToolsView 1 passed。

### 3.10 任务 9：端到端门禁与文档同步

#### 目标

完成最终全量验证，更新 PRD 和本执行文档。

#### 验收标准

- [ ] 后端 Docker 全量测试通过。
- [ ] 前端 Docker type-check 通过。
- [ ] 前端 Docker lint 通过。
- [ ] 前端 Docker unit test 通过。
- [ ] PRD 状态更新为 Phase 4 已完成。
- [ ] 本执行文档所有任务完成记录已更新。

#### 完成记录

- [x] 后端 Docker 全量测试通过：2046 passed / 6 skipped。
- [x] 前端 Docker type-check 通过。
- [x] 前端 Docker lint 通过。
- [x] 前端 Docker unit test 通过：97 files / 349 tests passed。
- [x] PRD 状态更新为 Phase 4 已完成，版本更新为 v2.5。
- [x] 本执行文档所有任务完成记录已更新。
