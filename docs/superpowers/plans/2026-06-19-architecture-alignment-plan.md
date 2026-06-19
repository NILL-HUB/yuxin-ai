# PRD 八层架构对齐实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将后端实现从"41 模块中仅 4 个生产激活"对齐到 PRD 5.2/5.3/5.4 描述的八层架构目标状态，按"先激活孤儿→再填补缺失→最后治理"的顺序渐进推进。

**Architecture:** 六阶段渐进式改造。Phase 1-2 激活已实现但未接入的孤儿模块（ResultSynthesizer/ExecutionCoordinator），风险最低见效最快；Phase 3-4 填补缺失的关键执行器（DirectAnswer/MultiAgent）和模型池治理；Phase 5-6 激活池治理与可观测层、修复命名不一致。

**Tech Stack:** Python / Flask / SQLAlchemy / injector DI / LangGraph / LangChain / ThreadPoolExecutor

---

## 现状基线（审计结果）

| 层 | 模块总数 | ✅生产激活 | ⚠️孤儿 | ❌缺失 |
|----|----------|-----------|--------|--------|
| L2 主入口调度 | 7 | 3 | 4 | 0 |
| L3 Agent池 | 7 | 1 | 3 | 3 |
| L4 工具池 | 8 | 0 | 4 | 4 |
| L5 模型/Key池 | 5 | 1 | 3 | 1 |
| L6 执行编排 | 7 | 0 | 1 | 6 |
| L7 结果汇总 | 6 | 0 | 2 | 4 |
| L8 可观测 | 1 | 0 | 1 | 0 |
| **合计** | **41** | **5** | **18** | **18** |

注：L2 的 3 个激活模块（PoolIntentResolver/CostPolicyService/BillingMetering）经 HomeService 旁路激活；OrchestratorService 刚在本轮绑定 DI，主调度链已接通但下游执行/汇总仍断裂。

---

## Phase 1: 激活 ResultSynthesizer（结果汇总层接入生产）

**优先级：HIGH | 风险：LOW | 理由：已有完整实现，仅需在执行后调用 synthesize()**

`ResultSynthesizerService.synthesize()` 已实现答案合并、冲突检测、质量检查、置信度计算，但无人调用。本阶段在 `chat()` 执行完成后、返回最终回答前接入它。

### Task 1.1: ResultSynthesizerService 绑定 DI

**Files:**
- Modify: `api/app/http/module.py`
- Modify: `api/internal/service/result_synthesizer_service.py`（加 @inject）

- [ ] **Step 1: 给 ResultSynthesizerService 加 @inject 装饰器**

在 `result_synthesizer_service.py` 的类定义前加 `@inject`，`__init__` 不变（event_logger 默认 None）。

- [ ] **Step 2: 在 module.py 注册绑定**

```python
from internal.service.result_synthesizer_service import ResultSynthesizerService
# 在 configure() 中追加:
binder.bind(ResultSynthesizerService, to=ResultSynthesizerService)
```

- [ ] **Step 3: 验证 injector 可解析**

Run: `python -c "from app.http.module import injector; from internal.service.result_synthesizer_service import ResultSynthesizerService; print(type(injector.get(ResultSynthesizerService)).__name__)"`
Expected: `ResultSynthesizerService`

### Task 1.2: chat() 执行后调用 synthesize() 做质量检查

**Files:**
- Modify: `api/internal/service/assistant_agent_service.py`
- Test: `api/test/internal/service/test_assistant_agent_service.py`

- [ ] **Step 1: 写失败测试**

在 `test_assistant_agent_service.py` 追加测试，验证当 agent 执行完成后，`result_synthesizer_service.synthesize()` 被调用，且 synthesis 结果中的 `user_warnings` 被作为 SSE 事件输出。

```python
def test_chat_should_invoke_synthesizer_after_agent_execution(self, monkeypatch, app):
    # mock synthesizer 返回带 warning 的结果
    # 验证 chat() 输出流中包含 synthesis warning 事件
    # 验证 synthesizer.synthesize 被调用且传入了 agent 结果
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest test/internal/service/test_assistant_agent_service.py::TestAssistantAgentSynthesis -v`
Expected: FAIL

- [ ] **Step 3: 在 chat() 的 agent 执行完成后插入 synthesize 调用**

在 `assistant_agent_service.py` 的 `chat()` 方法中，agent 执行完成、yield 最终 `agent_message` 之前，调用：

```python
if self.result_synthesizer_service is not None:
    try:
        synthesis = self.result_synthesizer_service.synthesize(
            results=[OrchestratedAgentResult(answer=full_answer, ...)],
            original_query=req.query.data,
        )
        for warning in synthesis.get("user_warnings", []):
            yield from self._stream_synthesis_warning(warning)
    except Exception:
        logging.warning("结果合成失败，跳过", exc_info=True)
```

新增 `_stream_synthesis_warning` 私有方法，yield 一个 `agent_thought` 类型的 SSE 事件。

- [ ] **Step 4: 运行测试验证通过**

- [ ] **Step 5: 全量回归 + 提交**

```bash
git add api/app/http/module.py api/internal/service/result_synthesizer_service.py api/internal/service/assistant_agent_service.py api/test/internal/service/test_assistant_agent_service.py
git commit -m "feat(synthesis): 接入 ResultSynthesizerService 做执行后质量检查与冲突检测"
```

---

## Phase 2: 激活 ExecutionCoordinator（执行编排层接入生产）

**优先级：HIGH | 风险：MEDIUM | 理由：已有 parallel/sequential/fallback 实现，但需适配流式**

`ExecutionCoordinatorService.execute()` 是同步的（返回 list），而 `chat()` 是生成器（yield SSE）。本阶段采用"适配器"策略：ExecutionCoordinator 负责多 Agent 的并行/串行调度，chat() 负责流式输出。

### Task 2.1: 定义 AgentTaskExecutor 适配器

**Files:**
- Create: `api/internal/service/agent_task_executor.py`
- Test: `api/test/internal/service/test_agent_task_executor.py`

- [ ] **Step 1: 写失败测试**

测试 `AgentTaskExecutor` 实现 `TaskExecutor` Protocol，其 `execute(item)` 方法实例化指定 Agent 类并执行，返回 dict 结果。

- [ ] **Step 2: 实现适配器**

```python
class AgentTaskExecutor:
    """将 Agent 类适配为 ExecutionCoordinator 的 TaskExecutor。"""
    def __init__(self, agent_class, agent_config, ...):
        self.agent_class = agent_class
        ...

    def execute(self, item: TaskPlanItem) -> dict:
        agent = self.agent_class(...)
        result = agent.invoke(...)
        return {"agent_id": ..., "task_id": item.task_id, "answer": result, ...}
```

- [ ] **Step 3: 验证 + 提交**

### Task 2.2: chat() 多 Agent 路径接入 ExecutionCoordinator

**Files:**
- Modify: `api/internal/service/assistant_agent_service.py`
- Test: `api/test/internal/service/test_assistant_agent_service.py`

- [ ] **Step 1: 写失败测试**

测试当 `execution_mode == "multi_agent_parallel"` 时，chat() 使用 `ExecutionCoordinatorService` 调度多个 Agent，而非直接实例化单个 FunctionCallAgent。

- [ ] **Step 2: 在 chat() 中增加 multi_agent 分支**

在 `should_deep_think` 判断之后、`agent_class` 选择之前，增加：

```python
if execution_mode in ("multi_agent_parallel", "multi_agent_sequential") and self.execution_coordinator_service is not None:
    yield from self._execute_via_coordinator(routing_decision, req, ...)
    return
```

新增 `_execute_via_coordinator` 方法：构建 TaskPlan → 用 AgentTaskExecutor 包装 → 调 coordinator.execute() → 将结果流式输出。

- [ ] **Step 3: 全量回归 + 提交**

### Task 2.3: ExecutionCoordinatorService 绑定 DI

**Files:**
- Modify: `api/app/http/module.py`

- [ ] **Step 1: 注册绑定**

```python
from internal.service.execution_coordinator_service import ExecutionCoordinatorService
binder.bind(ExecutionCoordinatorService, to=ExecutionCoordinatorService)
```

注意：ExecutionCoordinatorService 的 `__init__` 需要 `executor` 参数，但 executor 是运行时动态的（不同请求用不同 Agent）。DI 绑定用于让 injector 知道这个类型存在，实际 executor 在 chat() 中通过 AgentTaskExecutor 传入。需改为工厂模式或延迟注入。

- [ ] **Step 2: 验证 + 提交**

---

## Phase 3: 填补缺失执行器（DirectAnswerExecutor）

**优先级：MEDIUM | 风险：LOW | 理由：direct_answer 目前走 FunctionCallAgent 是杀鸡用牛刀**

### Task 3.1: 创建 DirectAnswerExecutor

**Files:**
- Create: `api/internal/service/executors/direct_answer_executor.py`

实现一个轻量执行器：直接调 LLM（不经 Agent 循环、不带工具），返回回答。用于 `execution_mode == "direct_answer"` 的简单 QA。

### Task 3.2: chat() direct_answer 路径分派

在 chat() 中，当 `execution_mode == "direct_answer"` 时使用 DirectAnswerExecutor 而非 FunctionCallAgent。

---

## Phase 4: 模型池治理层激活

**优先级：MEDIUM | 风险：MEDIUM | 理由：ModelPool/KeyPool 已实现但孤儿，ModelGateway 缺失**

### Task 4.1: 创建 ModelGateway 门面

**Files:**
- Create: `api/internal/service/model_gateway_service.py`

封装 LanguageModelManager + ModelPool + KeyPool，提供统一的 `get_model(task_complexity, budget_level)` 接口。

### Task 4.2: 激活 ModelPool/KeyPool

在 module.py 绑定 ModelPoolService/KeyPoolService，让 ModelGateway 通过它们选择模型和密钥。

### Task 4.3: chat() 模型选择接入 ModelGateway

将 chat() 中硬编码的 `DeepSeekChat` 改为通过 ModelGateway 选择。

---

## Phase 5: 池治理层激活（Agent/Tool 子集构建器）

**优先级：LOW | 风险：MEDIUM | 理由：需要 Agent/Tool 池数据有实际内容才有意义**

### Task 5.1: 激活 CrossPoolAgentSubsetBuilder

在 OrchestratorService.decide() 中调用 CrossPoolAgentSubsetBuilder，将选出的 Agent 子集填入 routing_decision.agent_subset。

### Task 5.2: 激活 CrossPoolToolSubsetBuilder（重命名自 ToolSubsetBuilder）

修正命名不一致，在 decide() 中调用，填入 routing_decision.tool_subset。

### Task 5.3: 激活 RuntimeToolMountService

让选出的工具子集在执行时真正挂载到 Agent。

---

## Phase 6: 可观测层激活 + 命名治理

**优先级：LOW | 风险：LOW | 理由：完善全链路可观测性，修复命名不一致**

### Task 6.1: 激活 RoutingObservabilityService

在 OrchestratorService 的各阶段调用 RoutingObservabilityService 记录决策事件。

### Task 6.2: 命名对齐

- `ToolSubsetBuilder` → `CrossPoolToolSubsetBuilder`（对齐 PRD 命名）
- `DeepThinkingAgent` 保留（Agent 命名是 LangGraph 惯例，不强求 Executor 后缀）
- `ModelPoolService`/`KeyPoolService` 保留 Service 后缀（项目惯例）

### Task 6.3: 补齐 ENABLE_MODEL_ASSIGNMENT_POLICY 开关注册

在 `ORCHESTRATION_FEATURE_FLAG_CODES` 列表中补注册此开关（当前被 orchestrator_service 使用但未注册）。

---

## Self-Review

**1. Spec coverage:**
- L2 主入口调度：OrchestratorService DI 绑定 ✅（已完成），ExecutionModeSelector 分派 → Phase 2
- L3 Agent池：CrossPoolAgentSubsetBuilder 激活 → Phase 5
- L4 工具池：CrossPoolToolSubsetBuilder 激活 → Phase 5
- L5 模型池：ModelGateway 创建 + ModelPool/KeyPool 激活 → Phase 4
- L6 执行编排：ExecutionCoordinator 激活 → Phase 2，DirectAnswerExecutor → Phase 3
- L7 结果汇总：ResultSynthesizer 激活 → Phase 1
- L8 可观测：RoutingObservabilityService 激活 → Phase 6

**2. 风险控制策略：**
- 每个 Phase 都有"DI 绑定 + try/except 兜底"模式，确保新接入的模块异常不阻断原有流程
- Phase 1（ResultSynthesizer）是纯后处理，不改变执行流，风险最低
- Phase 2（ExecutionCoordinator）仅对 multi_agent 路径生效，direct/single/deep 路径不变
- 建议每个 Phase 完成后做全量回归 + 特性开关灰度

**3. 未覆盖项（YAGNI）：**
- AgentResultNormalizer/EvidenceMerger/ConflictResolver/FinalAnswerComposer 不单独创建——它们的职责已被 ResultSynthesizerService 的私有方法覆盖，拆分无实际收益
- A2AClient 不单独创建——A2A 能力已由 A2ADeepThinkingAgent 承担
- FallbackManager 不单独创建——ExecutionCoordinatorService._apply_global_fallback 已覆盖
