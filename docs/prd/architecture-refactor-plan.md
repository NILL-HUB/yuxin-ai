# 架构重构与缺陷清理实施计划

> **文档信息**
> | 项 | 值 |
> |---|---|
> | 版本 | v1.0 |
> | 日期 | 2026-06-19 |
> | 状态 | 待执行 |
> | 关联 PRD | general-agent-orchestration-prd.md v3.1（5.2 八层架构图） |
> | 目标 | 消除 PRD 八层架构与实际代码的差距，清理技术债 |

## 一、背景与差距总览

PRD 5.2 定义了 8 层架构，实际代码逐层对比后识别出 5 大改进方向：

| # | 方向 | 严重度 | 风险 | 涉及层 |
|---|------|--------|------|--------|
| 1 | 执行链路断裂（决策与执行脱节） | 🔴 致命 | 高 | L2→L6 |
| 2 | 上帝类（3 个 >1000 行文件） | 🟠 高 | 中 | L6/L1 |
| 3 | 依赖注入不一致（编排子系统绕开 injector） | 🟠 高 | 低 | L2 |
| 4 | core→service 反向依赖（8 处） | 🟡 中 | 中 | L3/L4 |
| 5 | 残留技术债（ilike/to_dict/标识符） | 🟡 中 | 低 | 全层 |

## 二、优先级排序原则

采用"低风险高收益先行，架构级重构垫后"策略：

- **P1（技术债清理）**：风险最低、见效最快，先扫清基础卫生问题
- **P2（DI 一致性 + 反向依赖）**：为 P4 执行链路重构铺路（可测试性）
- **P3（上帝类拆分）**：独立重构，不阻塞其他任务
- **P4（执行链路接通）**：架构级重构，放最后，前置依赖 P2 完成的可注入性

## 三、任务分解

### P1-A：批量转义剩余 11 处未转义 ilike 拼接

**优先级**：P1（高收益/低风险）
**涉及文件**：11 个 service 文件
**依赖**：无（`escape_like_pattern` 工具函数已存在于 helper.py）

**待修改文件清单**：
1. `document_service.py:247`
2. `admin_app_service.py:20`
3. `admin_billing_plan_service.py:34`
4. `admin_user_service.py:269`
5. `admin_redeem_code_service.py:89,111`
6. `admin_workflow_service.py:19`
7. `admin_customer_user_service.py:64`
8. `api_tool_service.py:98`
9. `dataset_service.py:117`
10. `mcp_service.py:443-447`
11. `public_app_service.py:281-282`
12. `public_workflow_service.py:114-115`
13. `segment_service.py:232`
14. `skill_service.py:268-272`

**步骤**：
- [ ] 对每个文件添加 `escape_like_pattern` 导入（若缺失）
- [ ] 将 `Model.field.ilike(f"%{var}%")` 改为 `Model.field.ilike(f"%{escape_like_pattern(var)}%")`
- [ ] 运行 `pytest test/internal/service/test_admin* test/internal/service/test_document_service.py test/internal/service/test_dataset_service.py test/internal/service/test_segment_service.py test/internal/service/test_api_tool_service.py test/internal/service/test_skill_service.py test/internal/service/test_mcp_service.py test/internal/service/test_public* -q`

---

### P1-B：抽取统一 to_dict 基类，消除 16 处重复实现

**优先级**：P1（中收益/低风险）
**涉及文件**：16 个 entity 文件
**依赖**：无

**设计**：在 `internal/entity/base_entity.py` 新增 `SerializableMixin`，提供基于 `dataclasses.asdict` 的通用 `to_dict()`，各 entity 按需覆盖字段映射。

**步骤**：
- [ ] 创建 `internal/entity/base_entity.py`，定义 `SerializableMixin`（含 `to_dict()` 默认实现 + `_dict_field_overrides()` 钩子）
- [ ] 为 `SerializableMixin` 编写单元测试（验证基本序列化、字段覆盖、嵌套处理）
- [ ] 逐个迁移 16 个 entity（每迁移 1-2 个跑一次对应测试）
- [ ] 全量回归测试

**待迁移 entity 清单**：
`orchestrator_entity.py`、`routing_observability_entity.py`、`billing_metering_entity.py`、`routing_quality_entity.py`、`policy_change_entity.py`、`billing_runtime_entity.py`、`runtime_tool_entity.py`、`orchestration_feature_flag_entity.py`

---

### P2-A：OrchestratorService 依赖注入改造

**优先级**：P2（为 P4 铺路）
**涉及文件**：`orchestrator_service.py`、`module.py`
**依赖**：无

**现状**：`__init__` 用 `or` 兜底手工 new `PoolIntentResolver`/`TaskPlannerService`/`RequestContextBuilder`/`ModelAssignmentPolicy`；方法体内直接 `CostPolicyService()`。

**步骤**：
- [ ] 将 `OrchestratorService.__init__` 改为 `@inject` + 显式类型注解依赖，保留 `None` 兜底以兼容测试
- [ ] 将方法体内的 `CostPolicyService()` 提升为构造函数注入字段
- [ ] 在 `module.py` 注册新依赖绑定
- [ ] 运行 `pytest test/internal/service/test_orchestrator_service.py -q`

**风险**：`OrchestratorService` 当前构造函数签名被测试直接调用（非走 injector），需保留默认值兼容。

---

### P2-B：反转 core→service 反向依赖

**优先级**：P2（架构卫生）
**涉及文件**：core 层 8 处 + 新增 Protocol 定义
**依赖**：无

**现状**：core 层直接 import service 层的 `CosService`/`JiebaService`/`RetrievalService`/`LanguageModelService`。

**步骤**：
- [ ] 在 `internal/core/ports/` 新建 Protocol 接口：`ObjectStoragePort`、`TokenizerPort`、`RetrievalPort`、`LanguageModelPort`
- [ ] core 层改为依赖 Protocol（类型注解），通过构造函数接收实现
- [ ] service 层实现这些 Protocol（duck typing，无需显式继承）
- [ ] 在调用 core 的 handler/service 处注入具体实现
- [ ] 全量回归测试

**风险**：4 处顶层导入改为注入会改变 core 类的构造签名，需同步修改实例化点。优先处理懒加载的 4 处（改动面小）。

---

### P3-A：拆分 deep_thinking_agent.py（2426 行）

**优先级**：P3（独立重构）
**涉及文件**：`deep_thinking_agent.py` + 4 个新文件
**依赖**：无

**拆分方案**：
| 新文件 | 职责 | 预估行数 |
|--------|------|---------|
| `deep_thinking_router.py` | 路由决策（need_sandbox/need_file_io/need_artifact） | ~300 |
| `sandbox_executor.py` | E2B/BaiduCFC 沙箱执行封装 | ~400 |
| `artifact_pipeline.py` | 产物持久化与恢复 | ~350 |
| `structured_document_generator.py` | 多段文档生成 | ~300 |
| `deep_thinking_agent.py`（保留） | LangGraph 编排 + 上述组件组合 | ~500 |

**步骤**：
- [ ] 先补齐 deep_thinking_agent 现有测试覆盖（确保拆分有安全网）
- [ ] 按职责提取方法到独立文件，保持 `DeepThinkingAgent` 公共 API 不变
- [ ] 每提取一个组件跑一次 `pytest test/internal/core/agent/ -q`
- [ ] 全量回归

**风险**：该文件被 `assistant_agent_service.py` 直接引用为 `A2ADeepThinkingAgent`，需保持类名和 `stream()` 接口不变。

---

### P3-B：拆分 app_service.py（~1730 行）

**优先级**：P3（低优先，可后续迭代）
**涉及文件**：`app_service.py` + 新文件
**依赖**：无

**拆分方案**：
- `app_crud_service.py`：基础 CRUD
- `app_debug_service.py`：调试会话
- `app_agent_build_service.py`：Agent 创建与配置
- `app_stream_service.py`：流式事件处理
- `app_service.py`（保留）：门面，组合上述服务

**风险**：app_service 被 handler 层大量引用，拆分需保持 handler 调用不变（门面模式）。

---

### P4-A：新增 ExecutionModeSelector 服务

**优先级**：P4（执行链路重构前置）
**涉及文件**：新增 `execution_mode_selector_service.py`
**依赖**：P2-A（DI 改造）

**PRD 5.2 第 2 层要求**：`ExecutionModeSelector 选择 direct/single/multi/deep 路径`。当前只有 `ExecutionMode` 枚举，无 selector 类。

**步骤**：
- [ ] 创建 `ExecutionModeSelectorService`，封装"分类结果 → 执行模式"的决策逻辑（当前散落在 `TaskClassifier` 内联）
- [ ] 编写单元测试（覆盖 7+1 种执行模式的选择规则）
- [ ] 接入 `OrchestratorService.decide()`

---

### P4-B：接通执行链路（决策 → 执行）

**优先级**：P4（架构级，最高价值）
**涉及文件**：`assistant_agent_service.py`、`execution_coordinator_service.py`
**依赖**：P2-A（DI）、P4-A（Selector）

**现状**：`chat()` 中 `routing_decision` 仅打日志；`ExecutionCoordinatorService` 零生产调用。

**核心挑战**：现有执行是 SSE 流式（`agent.stream()` 产出事件），而 `ExecutionCoordinatorService.execute()` 是同步返回结果列表。直接替换会破坏 SSE 契约。

**分阶段方案**：
- [ ] **阶段 1（保守）**：`chat()` 中根据 `execution_mode` 选择 Agent 类（当前只看 `enable_deep_thinking` 布尔），让 `direct_answer`/`reject_or_confirm` 模式走快速路径，`multi_agent_*` 模式走协调器。保持 SSE 不变。
- [ ] **阶段 2（流式协调）**：为 `ExecutionCoordinatorService` 增加 `stream()` 方法，产出 SSE 事件，逐步替换 `agent.stream()` 直连。
- [ ] **阶段 3（完整接通）**：`TaskPlan` 真正传入协调器执行，`agent_subset`/`tool_subset` 真正约束 Agent/Tool 选择。

**风险**：这是用户可见行为变更，需逐步灰度，通过特性开关控制（`ENABLE_EXECUTION_COORDINATOR`），默认关闭，验证后开启。

---

## 四、执行顺序与里程碑

```
阶段一（P1 技术债，低风险）：
  P1-A ilike 转义  →  P1-B to_dict 统一
  里程碑：基础卫生问题清零

阶段二（P2 可测试性，中风险）：
  P2-A DI 改造  →  P2-B 反向依赖反转
  里程碑：编排子系统可注入、可 Mock

阶段三（P3 上帝类，中风险，可与阶段四并行）：
  P3-A deep_thinking 拆分  →  P3-B app_service 拆分
  里程碑：最大文件 < 800 行

阶段四（P4 执行链路，高风险）：
  P4-A ExecutionModeSelector  →  P4-B 执行链路接通（分 3 子阶段）
  里程碑：决策真正驱动执行，ExecutionCoordinator 接入生产
```

## 五、风险控制

1. **每步都跑测试**：每个任务完成后立即运行相关测试子集
2. **特性开关**：P4-B 通过 `ENABLE_EXECUTION_COORDINATOR` 开关灰度，默认关闭
3. **不破坏公共 API**：所有拆分保持类名、方法签名、SSE 事件契约不变
4. **小步提交**：每个子任务独立提交，便于回滚

## 六、验收标准

- [ ] 全量测试通过率不低于现状（当前基线：1616 passed，2 预存失败）
- [ ] 无新增 `except Exception: pass`
- [ ] 无新增 core→service 顶层导入
- [ ] `ExecutionCoordinatorService` 至少有 1 处生产调用（P4-B 阶段 1）
- [ ] 最大单文件行数 < 1000（P3 完成后）
- [ ] 所有 `ilike` 调用均使用 `escape_like_pattern`（P1-A 完成后）
