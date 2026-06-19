# 深度思考自动化（LLM 意图判断 + 二阶段确认）设计文档

> **文档信息**
> | 项 | 值 |
> |---|---|
> | 版本 | v1.0 |
> | 日期 | 2026-06-19 |
> | 状态 | 待审阅 |
> | 关联 PRD | general-agent-orchestration-prd.md v3.1（5.2 八层架构图 第2层 ExecutionModeSelector） |
> | 方案 | A：编排层 LLM 判断 + 二阶段请求 |

## 一、背景与动机

### 1.1 现状

深度思考（`A2ADeepThinkingAgent`）的触发逻辑位于 [assistant_agent_service.py:324](file:///d:/DEMO/openagent-main/api/internal/service/assistant_agent_service.py#L324)：

```python
should_deep_think = bool(req.enable_deep_thinking.data) or execution_mode == "deep_thinking"
```

- `enable_deep_thinking`：前端显式开关，默认 `False`
- `execution_mode == "deep_thinking"`：由 `TaskClassifierService` 的 `DEEP_THINKING_KEYWORDS`（9 个中文词）子串匹配决定

### 1.2 问题

1. **关键词漏判严重**：9 个词（深度分析/深度思考/详细分析/全面分析/系统性分析/研究报告/调研/对比分析/可行性分析）全是中文、纯子串匹配，无同义词/无分词/无英文。下列语义等价的查询全部漏判为普通 QA：
   - "评估一下把微服务从 REST 迁移到 gRPC 的利弊"（等价"可行性分析"）
   - "比较 React 和 Vue 在大型项目里的优缺点"（等价"对比分析"）
   - "把这份 50 页论文精简成 300 字摘要，并指出核心创新点"（需深度提炼）

2. **余额预检形同虚设**：`CostPolicyService` 设计了 `allowed`/`deep_thinking` 降级字段，但 `chat()` 调用 `decide()` 时**未传** `balance_credits`/`budget_level`，回退到默认值 `1.0`/`normal`，降级分支永远不触发。执行路径中也无人读取 `cost_policy["allowed"]`。意味着用户问一句含"调研"的话，就在不知情下触发沙箱执行 + 4+ 次 LLM 调用 + COS 上传，无任何护栏。

### 1.3 改造目标

把深度思考的触发从「显式开关 + 关键词」升级为「LLM 意图判断 + 用户二阶段确认」，并同步补齐余额预检护栏。

## 二、决策记录

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 成本保护策略 | 先提示再执行 | 自动触发高成本/高延迟操作前让用户知情确认 |
| 判断方式 | 纯 LLM 判断（cheap 档） | 关键词无法覆盖同义表述和英文；LLM 可语义判断 |
| 与手动开关关系 | 取消手动开关 | 用户控制从"显式开关"变为"自然语言意图" |
| 判断调用计费 | 同步补齐余额预检 | 余额不足时跳过判断，避免无意义消耗 |
| 方案 | A：编排层判断 + 二阶段请求 | 判断留在 L2 符合分层；二阶段 REST 友好；复用现有 chat 入口 |

## 三、整体架构与数据流

### 3.1 二阶段请求模型

```
第一阶段（判定）：
  用户提问（无开关字段）
    → 余额预检（balance_credits/budget_level 真正接入）
       ├─ 余额不足 → 跳过 LLM 判断，直接普通回答（SSE 正常流）
       └─ 余额充足 → OrchestratorService.decide()
            → TaskClassifierService 用 cheap LLM 判断深度思考意图
               ├─ 不需要 → 正常走 FunctionCallAgent（SSE 正常流）
               └─ 需要 → 返回 deep_thinking_proposal 事件（含理由），流结束

第二阶段（确认执行）：
  用户点"确认" → 带 confirm_deep_thinking=true 重新请求
    → chat() 看到该标记，跳过判断，直接进入 A2ADeepThinkingAgent（SSE 正常流）
```

### 3.2 组件变更一览

| 组件 | 变更 | 文件 |
|------|------|------|
| `TaskClassifierService` | 移除 `DEEP_THINKING_KEYWORDS` 分支；新增 `_classify_deep_thinking_intent()` 用 cheap 档 LLM + structured output | `internal/service/task_classifier_service.py` |
| `RequestContextBuilder` | 真正从账户表查询并填入 `balance_credits`/`budget_level` | `internal/service/request_context_builder_service.py` |
| `assistant_agent_service.chat()` | 改为二阶段：阶段1判定+提案、阶段2确认执行；执行路径真正读取 `cost_policy.allowed` | `internal/service/assistant_agent_service.py` |
| 3 个 Schema | `enable_deep_thinking` → `confirm_deep_thinking` | `assistant_agent_schema.py` / `app_schema.py` / `web_app_schema.py` |
| 新增 SSE 事件类型 | `deep_thinking_proposal`（含 reason/estimated_steps） | 事件枚举 |
| 新增特性开关 | `ENABLE_AUTO_DEEP_THINKING`（默认 True，关停回退旧行为） | `orchestration_feature_flag_entity.py` |
| 新增 Pydantic 模型 | `DeepThinkingIntent`（`needs_deep_thinking: bool` + `reason: str`） | `internal/core/agent/entities/deep_thinking_entity.py` |

## 四、组件细节

### 4.1 TaskClassifierService — LLM 意图判断

只把"深度思考"这一项判断 LLM 化；`tool_task`/`vertical_agent`/`general_qa` 的关键词判断保留——这些判断相对准确且成本敏感度低，避免把所有判断都 LLM 化导致每次请求多调多次。

```python
class TaskClassifierService:
    @inject
    def __init__(self, language_model_service: LanguageModelService):
        self.language_model_service = language_model_service

    def classify(self, query: str, *, budget_allowed: bool = True) -> RoutingDecision:
        # 高风险关键词（保留，零成本硬规则，优先于一切）
        if self._contains_any(query, self.HIGH_RISK_KEYWORDS):
            return RoutingDecision(execution_mode=REJECT_OR_CONFIRM, ...)

        # 余额不足时跳过 LLM 判断，省一次 cheap 调用
        if not budget_allowed:
            return self._fallback_direct_answer(query)

        # LLM 意图判断（cheap 档 + structured output）
        intent = self._classify_deep_thinking_intent(query)
        if intent.needs_deep_thinking:
            return RoutingDecision(
                execution_mode=DEEP_THINKING,
                needs_deep_thinking=True,
                reason=intent.reason,
                ...
            )
        # 其余走原有 tool/vertical/general 分支（关键词保留）
        ...

    def _classify_deep_thinking_intent(self, query: str) -> DeepThinkingIntent:
        llm = self.language_model_service.get_cheap_model()
        structured = llm.with_structured_output(DeepThinkingIntent)
        return structured.invoke(self._build_intent_prompt(query))
```

### 4.2 RequestContextBuilder — 接通真实余额

```python
def build(self, **kwargs) -> RequestContext:
    account_id = kwargs.get("account_id")
    account = self.db.session.get(Account, account_id) if account_id else None
    balance_credits = float(account.balance_credits) if account else 0.0
    budget_level = self._resolve_budget_level(account)
    return RequestContext(
        ...,
        balance_credits=balance_credits,
        budget_level=budget_level,
    )
```

`chat()` 调 `decide()` 时补传 `balance_credits`/`budget_level`（当前漏传）。

### 4.3 assistant_agent_service.chat() — 二阶段逻辑

```python
def chat(self, req, ...):
    is_confirm_phase = bool(req.confirm_deep_thinking.data)

    if is_confirm_phase:
        return self._execute_deep_thinking(req, ...)

    routing_decision = self.orchestrator_service.decide(
        req.query.data,
        account_id=account.id,
        balance_credits=account.balance_credits,  # 新增
        budget_level=...,                         # 新增
        ...
    ).to_dict()

    if not routing_decision.get("cost_policy", {}).get("allowed", True):
        return self._stream_insufficient_balance(...)

    execution_mode = routing_decision.get("execution_mode")
    if execution_mode == "deep_thinking":
        return self._stream_deep_thinking_proposal(routing_decision)

    return self._stream_normal_response(...)
```

### 4.4 Schema 变更

3 个 schema：`enable_deep_thinking = BooleanField(default=False)` → `confirm_deep_thinking = BooleanField(default=False)`。前端语义从"我要开深度思考"变为"我确认要执行深度思考"。

### 4.5 新增 SSE 事件 + 特性开关

- SSE 事件 `deep_thinking_proposal`：`{event, reason, estimated_steps}`，前端据此弹确认框
- 特性开关 `ENABLE_AUTO_DEEP_THINKING`（默认 True）：关闭后回退旧行为（保留 `enable_deep_thinking` 开关 + 关键词），作为灰度/回滚手段

## 五、错误处理

原则：任何判断/预检失败都回退到普通回答，绝不阻断用户。

| 失败点 | 处理 | 用户感知 |
|--------|------|----------|
| 账户余额查询失败（DB 异常） | `balance_credits` 回退为 0，触发"余额不足"提示 | 提示账户异常，建议普通回答 |
| cheap LLM 判断调用失败/超时 | 降级为 `general_qa` → 普通回答；记录 warning 日志 | 无感知，正常拿到回答 |
| cheap LLM 返回无法解析的 structured output | 同上，降级普通回答 | 无感知 |
| `cost_policy.allowed=False`（余额不足） | 跳过深度思考，普通回答 + 余额不足提示 | 明确告知余额不足 |
| `cost_policy.deep_thinking=False`（低预算） | 即使 LLM 判定需要，也降级普通回答 | 正常回答，不提示（静默降级） |
| 第二阶段 `confirm_deep_thinking` 但余额已耗尽 | 二次预检失败，返回余额不足提示 | 明确告知 |
| 第二阶段请求携带 `confirm_deep_thinking` 但无对应会话上下文 | 视为非法状态，按普通回答处理 + warning | 正常回答 |
| `ENABLE_AUTO_DEEP_THINKING=False`（开关关闭） | 完全回退旧行为 | 无变化 |

关键决策：cheap LLM 判断失败时**不重试**——重试叠加延迟，而降级普通回答对用户可接受。只有真正的深度思考执行阶段（沙箱、多 LLM）才需既有重试逻辑。

## 六、测试策略

### 6.1 单元测试

| 组件 | 新增/改动测试 |
|------|---------------|
| `TaskClassifierService` | LLM 判断命中深度思考；LLM 判断不命中；LLM 调用失败降级普通回答；余额不足跳过 LLM；高风险关键词仍优先于 LLM 判断 |
| `RequestContextBuilder` | 真实账户余额正确填入；账户不存在时余额为 0；DB 异常时安全回退 |
| `ExecutionModeSelectorService` | `budget_allowed=False` 时返回 `DIRECT_ANSWER` |
| `CostPolicyService` | 已有测试补充：验证 `chat()` 执行路径真正读取 `allowed`/`deep_thinking` |

### 6.2 集成测试（二阶段流程）

| 场景 | 验证点 |
|------|--------|
| 阶段1 判定需要 → 收到 `deep_thinking_proposal` 事件 | 事件含 reason，流正常结束 |
| 阶段2 确认 → 进入 `A2ADeepThinkingAgent` | `confirm_deep_thinking=True` 时跳过判断 |
| 阶段1 余额不足 → 无 proposal，直接普通回答 | 不消耗 cheap LLM 调用 |
| 阶段1 LLM 判断失败 → 降级普通回答 | 无异常抛出 |
| `ENABLE_AUTO_DEEP_THINKING=False` → 旧行为 | `enable_deep_thinking` 字段仍生效 |

### 6.3 回归保护

- 既有 46 个 `assistant_agent_service` 测试 + 11 个 `orchestrator` 测试 + 12 个 `execution_mode_selector` 测试全部需通过
- schema 字段改名涉及 3 个 schema 测试文件，需同步更新

## 七、范围与非目标

### 本次范围
- 深度思考意图的 LLM 判断
- 二阶段请求流程
- 余额预检接通（修复既有隐患）
- schema 字段改名
- 灰度开关

### 非目标（本次不做）
- `ExecutionCoordinatorService` 接入生产流式执行（属架构重构计划的 P4-B 阶段 2/3，独立任务）
- `tool_task`/`vertical_agent` 判断的 LLM 化（保留关键词，成本敏感度低）
- 前端确认 UI 的实现（后端只负责发 `deep_thinking_proposal` 事件，前端如何展示由前端团队决定）
