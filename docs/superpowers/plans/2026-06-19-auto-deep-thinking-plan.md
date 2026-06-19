# 深度思考自动化（LLM 意图判断 + 二阶段确认）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把深度思考的触发从「显式开关 + 9 个中文关键词」升级为「cheap 档 LLM 意图判断 + 用户二阶段确认」，并补齐此前形同虚设的余额预检护栏。

**Architecture:** 编排层 L2 的 TaskClassifierService 用 cheap LLM 判断深度思考意图；chat() 改为二阶段——阶段1判定后发 deep_thinking_proposal SSE 事件，阶段2 用户确认后执行。余额从 CreditAccount 表查真实值传入 decide()，执行路径真正读取 cost_policy.allowed 做拦截。

**Tech Stack:** Python / Flask / SQLAlchemy / LangChain structured output / injector DI

---

## 文件结构总览

| 文件 | 操作 | 职责 |
|------|------|------|
| `internal/core/agent/entities/deep_thinking_entity.py` | 修改 | 新增 DeepThinkingIntent Pydantic 模型 |
| `internal/service/language_model_service.py` | 修改 | 新增 get_cheap_chat_model() 方法 |
| `internal/service/task_classifier_service.py` | 修改 | 移除 DEEP_THINKING_KEYWORDS 分支，新增 LLM 意图判断 |
| `internal/service/request_context_builder_service.py` | 修改 | 从 CreditAccount 查真实余额 |
| `internal/entity/orchestrator_entity.py` | 修改 | RequestContext 增加 budget_allowed 字段 |
| `internal/service/orchestrator_service.py` | 修改 | decide() 传递 budget_allowed 给 classifier |
| `internal/service/assistant_agent_service.py` | 修改 | chat() 改为二阶段 + 读取 cost_policy.allowed |
| `internal/core/agent/entities/queue_entity.py` | 修改 | 新增 DEEP_THINKING_PROPOSAL 事件 |
| `internal/schema/assistant_agent_schema.py` | 修改 | enable_deep_thinking → confirm_deep_thinking |
| `internal/schema/app_schema.py` | 修改 | 同上 |
| `internal/schema/web_app_schema.py` | 修改 | 同上 |
| `internal/entity/orchestration_feature_flag_entity.py` | 修改 | 新增 ENABLE_AUTO_DEEP_THINKING 开关 |
| `test/internal/service/test_task_classifier_service.py` | 新建 | LLM 判断单测 |
| `test/internal/service/test_request_context_builder_service.py` | 修改 | 余额查询单测 |
| `test/internal/service/test_assistant_agent_service.py` | 修改 | 二阶段流程单测 |
| `test/internal/entity/test_deep_thinking_entity.py` | 修改 | DeepThinkingIntent 单测 |

执行顺序：Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8，每完成一个任务跑测试。

---

### Task 1: 新增 DeepThinkingIntent Pydantic 模型

**Files:**
- Modify: `internal/core/agent/entities/deep_thinking_entity.py`
- Test: `test/internal/entity/test_deep_thinking_entity.py`

- [ ] **Step 1: 写失败测试**

在 `test/internal/entity/test_deep_thinking_entity.py` 末尾追加：

```python
from internal.core.agent.entities.deep_thinking_entity import DeepThinkingIntent


class TestDeepThinkingIntent:
    def test_default_should_not_need_deep_thinking(self):
        intent = DeepThinkingIntent()
        assert intent.needs_deep_thinking is False
        assert intent.reason == ""

    def test_explicit_need_with_reason(self):
        intent = DeepThinkingIntent(needs_deep_thinking=True, reason="需要多步推理")
        assert intent.needs_deep_thinking is True
        assert intent.reason == "需要多步推理"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest test/internal/entity/test_deep_thinking_entity.py::TestDeepThinkingIntent -v`
Expected: FAIL — `cannot import name 'DeepThinkingIntent'`

- [ ] **Step 3: 实现模型**

在 `internal/core/agent/entities/deep_thinking_entity.py` 末尾追加：

```python
class DeepThinkingIntent(BaseModel):
    """LLM 判断的深度思考意图结果。"""

    needs_deep_thinking: bool = False
    reason: str = ""
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest test/internal/entity/test_deep_thinking_entity.py::TestDeepThinkingIntent -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/core/agent/entities/deep_thinking_entity.py test/internal/entity/test_deep_thinking_entity.py
git commit -m "feat: add DeepThinkingIntent model for LLM-based intent detection"
```

---

### Task 2: LanguageModelService 新增 get_cheap_chat_model()

**Files:**
- Modify: `internal/service/language_model_service.py`
- Test: `test/internal/service/test_language_model_service.py`

- [ ] **Step 1: 写失败测试**

在 `test/internal/service/test_language_model_service.py` 中找到 TestLanguageModelService 类，追加：

```python
    def test_get_cheap_chat_model_should_return_llm_instance(self):
        service = LanguageModelService(
            language_model_manager=_build_manager_stub(),
            db=self.db,
        )
        model = service.get_cheap_chat_model()
        assert model is not None
        assert hasattr(model, "with_structured_output")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest test/internal/service/test_language_model_service.py -k "get_cheap_chat_model" -v`
Expected: FAIL — `AttributeError: 'LanguageModelService' object has no attribute 'get_cheap_chat_model'`

- [ ] **Step 3: 实现方法**

在 `internal/service/language_model_service.py` 的 `LanguageModelService` 类中（`get_assistant_agent_model_config` 方法之后）追加：

```python
    def get_cheap_chat_model(self) -> BaseLanguageModel:
        """返回用于意图判断等轻量任务的 cheap 档 LLM 实例。"""
        config = self.get_default_model_config()
        return self.from_model(
            model=self._instantiate_language_model(config),
            fallback_loader=self._get_fallback_model,
            requested_model_config=config,
            runtime_fallback_enabled=True,
        )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest test/internal/service/test_language_model_service.py -k "get_cheap_chat_model" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add internal/service/language_model_service.py test/internal/service/test_language_model_service.py
git commit -m "feat: add get_cheap_chat_model for lightweight LLM intent detection"
```

---

### Task 3: TaskClassifierService 改用 LLM 判断深度思考意图

**Files:**
- Modify: `internal/service/task_classifier_service.py`
- Test: `test/internal/service/test_task_classifier_service.py`

- [ ] **Step 1: 写失败测试**

新建 `test/internal/service/test_task_classifier_service.py`：

```python
from unittest.mock import MagicMock, patch

from internal.entity.orchestrator_entity import ExecutionMode, RiskLevel
from internal.service.task_classifier_service import TaskClassifierService


def _build_service(llm_response=None, llm_raises=False):
    service = TaskClassifierService.__new__(TaskClassifierService)
    service.language_model_service = MagicMock()
    mock_llm = MagicMock()
    if llm_raises:
        mock_llm.with_structured_output.return_value.invoke.side_effect = RuntimeError("timeout")
    elif llm_response is not None:
        mock_llm.with_structured_output.return_value.invoke.return_value = llm_response
    service.language_model_service.get_cheap_chat_model.return_value = mock_llm
    return service


class TestTaskClassifierDeepThinking:
    def test_llm_says_need_deep_thinking_should_return_deep_thinking_mode(self):
        from internal.core.agent.entities.deep_thinking_entity import DeepThinkingIntent
        service = _build_service(DeepThinkingIntent(needs_deep_thinking=True, reason="需要多步推理"))
        decision = service.classify("评估迁移到 gRPC 的利弊")
        assert decision.execution_mode == ExecutionMode.DEEP_THINKING.value
        assert decision.needs_deep_thinking is True

    def test_llm_says_no_deep_thinking_should_fall_to_general(self):
        from internal.core.agent.entities.deep_thinking_entity import DeepThinkingIntent
        service = _build_service(DeepThinkingIntent(needs_deep_thinking=False))
        decision = service.classify("今天天气怎么样")
        assert decision.execution_mode != ExecutionMode.DEEP_THINKING.value

    def test_llm_call_failure_should_degrade_to_general_qa(self):
        service = _build_service(llm_raises=True)
        decision = service.classify("随便问个问题")
        assert decision.execution_mode != ExecutionMode.DEEP_THINKING.value
        assert decision.execution_mode != ExecutionMode.REJECT_OR_CONFIRM.value

    def test_budget_not_allowed_should_skip_llm_and_return_direct_answer(self):
        service = _build_service()
        decision = service.classify("深度分析一下", budget_allowed=False)
        assert decision.execution_mode == ExecutionMode.DIRECT_ANSWER.value
        service.language_model_service.get_cheap_chat_model.assert_not_called()

    def test_high_risk_keyword_should_override_llm_judgment(self):
        from internal.core.agent.entities.deep_thinking_entity import DeepThinkingIntent
        service = _build_service(DeepThinkingIntent(needs_deep_thinking=True))
        decision = service.classify("请删除数据库里的所有用户表")
        assert decision.execution_mode == ExecutionMode.REJECT_OR_CONFIRM.value
        assert decision.risk_level == RiskLevel.HIGH.value
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest test/internal/service/test_task_classifier_service.py -v`
Expected: FAIL — 测试需要新的 `classify` 签名和 `_classify_deep_thinking_intent` 方法

- [ ] **Step 3: 重构 TaskClassifierService**

修改 `internal/service/task_classifier_service.py`：

(a) 在 `@dataclass` 类定义中注入 `language_model_service`：

```python
from dataclasses import dataclass, field

from injector import inject

from internal.core.agent.entities.deep_thinking_entity import DeepThinkingIntent
from internal.entity.orchestrator_entity import ExecutionMode, RiskLevel, RoutingDecision
from internal.service.language_model_service import LanguageModelService


@inject
@dataclass
class TaskClassifierService:
    language_model_service: LanguageModelService = None
```

(b) 删除 `DEEP_THINKING_KEYWORDS` 常量（第 53-63 行那 9 个词的元组）。

(c) 修改 `classify` 方法签名增加 `budget_allowed` 参数，并在高风险判断之后、原深度思考关键词判断处替换为 LLM 调用：

```python
    def classify(self, query: str, *, budget_allowed: bool = True) -> RoutingDecision:
        normalized = query.strip()
        lowered = normalized.lower()

        if self._contains_any(normalized, self.HIGH_RISK_KEYWORDS) or self._contains_any(
            lowered, self.HIGH_RISK_KEYWORDS
        ):
            return RoutingDecision(
                intent="high_risk_operation",
                complexity="complex",
                execution_mode=ExecutionMode.REJECT_OR_CONFIRM.value,
                recommended_model_tier="strong",
                risk_level=RiskLevel.HIGH.value,
            )

        if not budget_allowed:
            return self._build_direct_answer(normalized)

        try:
            intent = self._classify_deep_thinking_intent(normalized)
            if intent.needs_deep_thinking:
                return RoutingDecision(
                    intent="deep_thinking",
                    complexity="complex",
                    execution_mode=ExecutionMode.DEEP_THINKING.value,
                    recommended_model_tier="strong",
                    risk_level=RiskLevel.SAFE.value,
                    needs_deep_thinking=True,
                )
        except Exception:
            pass

        return self._classify_remaining(normalized, lowered)
```

(d) 新增辅助方法：

```python
    def _classify_deep_thinking_intent(self, query: str) -> DeepThinkingIntent:
        llm = self.language_model_service.get_cheap_chat_model()
        structured = llm.with_structured_output(DeepThinkingIntent)
        return structured.invoke(self._build_intent_prompt(query))

    @staticmethod
    def _build_intent_prompt(query: str) -> str:
        return (
            "判断以下用户问题是否需要深度思考（多步推理、调研、对比分析、"
            "可行性评估、结构化报告生成等）。\n\n"
            f"用户问题：{query}\n\n"
            "请返回 needs_deep_thinking（布尔）和 reason（简短理由）。"
        )

    def _build_direct_answer(self, query: str) -> RoutingDecision:
        return RoutingDecision(
            intent="general_qa",
            complexity="simple",
            execution_mode=ExecutionMode.DIRECT_ANSWER.value,
            recommended_model_tier="cheap",
            risk_level=RiskLevel.SAFE.value,
        )

    def _classify_remaining(self, normalized: str, lowered: str) -> RoutingDecision:
        # 原 tool_task / vertical_agent / general_qa 关键词判断逻辑移到这里
        # （保留原 TOOL_KEYWORDS / AGENT_KEYWORDS / VERTICAL_HINTS 判断）
        ...
```

将原 `classify` 方法中 `DEEP_THINKING_KEYWORDS` 之后的 tool/vertical/general 判断逻辑移到 `_classify_remaining`。

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest test/internal/service/test_task_classifier_service.py -v`
Expected: 5 个测试全部 PASS

- [ ] **Step 5: 跑 orchestrator 回归测试**

Run: `python -m pytest test/internal/service/test_orchestrator_service.py test/internal/service/test_execution_mode_selector_service.py -v`
Expected: PASS（如 orchestrator 测试因 classifier 签名变化失败，需同步更新 mock）

- [ ] **Step 6: 提交**

```bash
git add internal/service/task_classifier_service.py test/internal/service/test_task_classifier_service.py
git commit -m "feat: replace deep_thinking keyword matching with LLM intent detection"
```

---

### Task 4: RequestContextBuilder 接通 CreditAccount 真实余额

**Files:**
- Modify: `internal/service/request_context_builder_service.py`
- Modify: `internal/entity/orchestrator_entity.py`
- Test: `test/internal/service/test_request_context_builder_service.py`

- [ ] **Step 1: 写失败测试**

在 `test/internal/service/test_request_context_builder_service.py` 追加：

```python
from unittest.mock import MagicMock
from internal.model.billing import CreditAccount
from internal.service.request_context_builder_service import RequestContextBuilder


class TestRequestContextBuilderBalance:
    def test_should_query_credit_account_balance(self):
        db = MagicMock()
        credit_account = CreditAccount()
        credit_account.balance = 5000
        db.session.query.return_value.filter_by.return_value.first.return_value = credit_account
        builder = RequestContextBuilder(db=db)
        ctx = builder.build("query", account_id="acc-123")
        assert ctx.balance_credits == 5000.0

    def test_should_return_zero_when_no_credit_account(self):
        db = MagicMock()
        db.session.query.return_value.filter_by.return_value.first.return_value = None
        builder = RequestContextBuilder(db=db)
        ctx = builder.build("query", account_id="acc-123")
        assert ctx.balance_credits == 0.0

    def test_should_return_zero_on_db_exception(self):
        db = MagicMock()
        db.session.query.side_effect = RuntimeError("db down")
        builder = RequestContextBuilder(db=db)
        ctx = builder.build("query", account_id="acc-123")
        assert ctx.balance_credits == 0.0

    def test_budget_allowed_should_be_false_when_balance_below_threshold(self):
        db = MagicMock()
        credit_account = CreditAccount()
        credit_account.balance = 0
        db.session.query.return_value.filter_by.return_value.first.return_value = credit_account
        builder = RequestContextBuilder(db=db)
        ctx = builder.build("query", account_id="acc-123")
        assert ctx.budget_allowed is False
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest test/internal/service/test_request_context_builder_service.py::TestRequestContextBuilderBalance -v`
Expected: FAIL — `RequestContextBuilder` 不接受 `db` 参数

- [ ] **Step 3: RequestContext 增加 budget_allowed 字段**

在 `internal/entity/orchestrator_entity.py` 的 `RequestContext` dataclass 中，`balance_credits` 字段后追加：

```python
    budget_allowed: bool = True
```

并在 `to_dict` 方法中追加 `"budget_allowed": self.budget_allowed`。

- [ ] **Step 4: 重构 RequestContextBuilder**

修改 `internal/service/request_context_builder_service.py`：

```python
import logging

from injector import inject
from internal.entity.orchestrator_entity import RequestContext
from internal.model.billing import CreditAccount
from pkg.sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)

MINIMUM_BALANCE_FOR_DEEP_THINKING = 1


@inject
class RequestContextBuilder:
    DEFAULT_BALANCE_CREDITS = 1.0
    DEFAULT_BUDGET_LEVEL = "normal"

    def __init__(self, db: SQLAlchemy = None):
        self.db = db

    def build(self, query: str, **context) -> RequestContext:
        enable_deep_thinking = bool(context.get("enable_deep_thinking"))
        account_id = self._text(context.get("account_id"))
        balance_credits = self._resolve_balance(account_id)
        budget_level = self._budget_level(context.get("budget_level"))
        return RequestContext(
            query=self._normalize_query(query),
            account_id=account_id,
            conversation_id=self._text(context.get("conversation_id")),
            message_id=self._text(context.get("message_id")),
            image_urls=self._image_urls(context.get("image_urls")),
            enable_deep_thinking=enable_deep_thinking,
            deep_thinking_requested=enable_deep_thinking,
            budget_level=budget_level,
            balance_credits=balance_credits,
            budget_allowed=balance_credits >= MINIMUM_BALANCE_FOR_DEEP_THINKING,
            routing_log_id=context.get("routing_log_id"),
        )

    def _resolve_balance(self, account_id: str) -> float:
        if not account_id or self.db is None:
            return 0.0
        try:
            credit_account = (
                self.db.session.query(CreditAccount)
                .filter_by(account_id=account_id)
                .first()
            )
            return float(credit_account.balance) if credit_account else 0.0
        except Exception:
            logger.warning("查询账户余额失败", exc_info=True)
            return 0.0

    @staticmethod
    def _normalize_query(query: str) -> str:
        return (query or "").strip()

    @staticmethod
    def _text(value) -> str:
        return str(value).strip() if value is not None else ""

    @staticmethod
    def _image_urls(value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]

    def _budget_level(self, value) -> str:
        text = self._text(value) or self.DEFAULT_BUDGET_LEVEL
        return text if text in {"low", "normal", "high"} else self.DEFAULT_BUDGET_LEVEL
```

- [ ] **Step 5: 运行测试验证通过**

Run: `python -m pytest test/internal/service/test_request_context_builder_service.py -v`
Expected: 全部 PASS（含原有测试 + 4 个新测试）

- [ ] **Step 6: 提交**

```bash
git add internal/service/request_context_builder_service.py internal/entity/orchestrator_entity.py test/internal/service/test_request_context_builder_service.py
git commit -m "feat: RequestContextBuilder queries real CreditAccount balance for budget guard"
```

---

### Task 5: OrchestratorService 传递 budget_allowed 给 classifier

**Files:**
- Modify: `internal/service/orchestrator_service.py`

- [ ] **Step 1: 写失败测试**

在 `test/internal/service/test_orchestrator_service.py` 追加：

```python
    def test_budget_not_allowed_should_skip_llm_classification(self):
        classifier = MagicMock()
        classifier.classify.return_value = RoutingDecision(
            intent="general_qa",
            complexity="simple",
            execution_mode="direct_answer",
            recommended_model_tier="cheap",
            risk_level="safe",
        )
        service = OrchestratorService(task_classifier_service=classifier)
        service.decide("深度分析", account_id="acc-1", budget_allowed=False)
        classifier.classify.assert_called_once()
        _, kwargs = classifier.classify.call_args
        assert kwargs.get("budget_allowed") is False
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest test/internal/service/test_orchestrator_service.py::TestOrchestratorService::test_budget_not_allowed_should_skip_llm_classification -v`
Expected: FAIL — `decide()` 不接受 `budget_allowed` 参数 / classifier.classify 未传 budget_allowed

- [ ] **Step 3: 修改 decide()**

在 `internal/service/orchestrator_service.py` 的 `decide` 方法签名中增加 `budget_allowed: bool = True`，并在调用 `self.task_classifier_service.classify(...)` 时传入：

```python
    def decide(
        self,
        query: str,
        *,
        account_id: str = "",
        conversation_id: str = "",
        message_id: str = "",
        image_urls: list[str] | None = None,
        enable_deep_thinking: bool = False,
        budget_allowed: bool = True,
    ) -> RoutingDecision:
        ...
        ctx = self.request_context_builder.build(
            query,
            account_id=account_id,
            ...
            balance_credits=...,
            budget_level=...,
        )
        ctx.budget_allowed = ctx.budget_allowed and budget_allowed
        ...
        decision = self.task_classifier_service.classify(query, budget_allowed=ctx.budget_allowed)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest test/internal/service/test_orchestrator_service.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add internal/service/orchestrator_service.py test/internal/service/test_orchestrator_service.py
git commit -m "feat: OrchestratorService passes budget_allowed to TaskClassifier"
```

---

### Task 6: 新增 ENABLE_AUTO_DEEP_THINKING 特性开关 + QueueEvent 事件

**Files:**
- Modify: `internal/entity/orchestration_feature_flag_entity.py`
- Modify: `internal/core/agent/entities/queue_entity.py`

- [ ] **Step 1: 新增特性开关注册**

在 `internal/entity/orchestration_feature_flag_entity.py` 的 `ORCHESTRATION_FEATURE_FLAG_CODES` 列表中追加 `"ENABLE_AUTO_DEEP_THINKING"`，并在 `get_default_orchestration_feature_flags()` 中追加默认值条目：

```python
    {
        "code": "ENABLE_AUTO_DEEP_THINKING",
        "name": "自动深度思考判断",
        "description": "启用 LLM 意图判断自动触发深度思考（关闭则回退到关键词+手动开关）",
        "is_enabled": True,
        "category": "routing",
    },
```

- [ ] **Step 2: 新增 SSE 事件类型**

在 `internal/core/agent/entities/queue_entity.py` 的 `QueueEvent` 枚举中追加：

```python
    DEEP_THINKING_PROPOSAL = "deep_thinking_proposal"
```

- [ ] **Step 3: 运行特性开关实体测试**

Run: `python -m pytest test/internal/entity/ -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add internal/entity/orchestration_feature_flag_entity.py internal/core/agent/entities/queue_entity.py
git commit -m "feat: add ENABLE_AUTO_DEEP_THINKING flag and deep_thinking_proposal event"
```

---

### Task 7: Schema 字段改名 enable_deep_thinking → confirm_deep_thinking

**Files:**
- Modify: `internal/schema/assistant_agent_schema.py`
- Modify: `internal/schema/app_schema.py`
- Modify: `internal/schema/web_app_schema.py`
- Test: 相关 schema 测试

- [ ] **Step 1: 改 3 个 schema**

在三个文件中，将：
```python
enable_deep_thinking = BooleanField("enable_deep_thinking", default=False)
```
改为：
```python
confirm_deep_thinking = BooleanField("confirm_deep_thinking", default=False)
```

- [ ] **Step 2: 同步更新引用该字段的测试**

搜索 `enable_deep_thinking` 在 `test/` 下的引用，将其改为 `confirm_deep_thinking`。

Run: `grep -rn "enable_deep_thinking" test/` 找到所有引用，逐一更新。

- [ ] **Step 3: 运行 schema 测试**

Run: `python -m pytest test/internal/schema/ -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add internal/schema/ test/
git commit -m "refactor: rename enable_deep_thinking to confirm_deep_thinking (two-phase confirm semantics)"
```

---

### Task 8: chat() 改为二阶段 + 读取 cost_policy.allowed

**Files:**
- Modify: `internal/service/assistant_agent_service.py`
- Test: `test/internal/service/test_assistant_agent_service.py`

- [ ] **Step 1: 写失败测试**

在 `test/internal/service/test_assistant_agent_service.py` 追加：

```python
class TestAssistantAgentDeepThinkingTwoPhase:
    def test_confirm_phase_should_skip_judgment_and_execute_deep_thinking(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-bytes-1234567")
        service = self._build_service(monkeypatch)
        req = self._build_req(confirm_deep_thinking=True)
        monkeypatch.setattr(
            "internal.service.assistant_agent_service.A2ADeepThinkingAgent",
            MagicMock(side_effect=lambda **kw: self._mock_agent_streaming()),
        )
        events = list(service.chat(req, app_id=...))
        assert any("agent_message" in e for e in events)

    def test_phase1_cost_policy_not_allowed_should_return_insufficient_balance(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-bytes-1234567")
        service = self._build_service(monkeypatch)
        service.orchestrator_service.decide = MagicMock(return_value=MagicMock(
            to_dict=MagicMock(return_value={
                "execution_mode": "direct_answer",
                "cost_policy": {"allowed": False},
            })
        ))
        req = self._build_req(confirm_deep_thinking=False)
        events = list(service.chat(req, app_id=...))
        assert any("余额不足" in str(e) for e in events)

    def test_phase1_deep_thinking_should_yield_proposal_event(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-32-bytes-1234567")
        service = self._build_service(monkeypatch)
        service.orchestrator_service.decide = MagicMock(return_value=MagicMock(
            to_dict=MagicMock(return_value={
                "execution_mode": "deep_thinking",
                "cost_policy": {"allowed": True},
                "reason": "需要多步推理",
            })
        ))
        req = self._build_req(confirm_deep_thinking=False)
        events = list(service.chat(req, app_id=...))
        assert any("deep_thinking_proposal" in str(e) for e in events)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest test/internal/service/test_assistant_agent_service.py::TestAssistantAgentDeepThinkingTwoPhase -v`
Expected: FAIL

- [ ] **Step 3: 重构 chat()**

在 `internal/service/assistant_agent_service.py` 的 `chat` 方法中：

(a) 在方法开头读取 confirm 标记：

```python
        is_confirm_phase = bool(req.confirm_deep_thinking.data)
```

(b) 在原 `should_deep_think` 逻辑处替换为二阶段判断：

```python
        if is_confirm_phase:
            should_deep_think = True
        else:
            routing_decision = self.orchestrator_service.decide(
                req.query.data,
                account_id=account.id,
                conversation_id=conversation.id,
                message_id=message.id,
                image_urls=req.image_urls.data,
                enable_deep_thinking=False,
                budget_allowed=True,
            ).to_dict()

            if not routing_decision.get("cost_policy", {}).get("allowed", True):
                return self._stream_insufficient_balance(account, conversation, message)

            execution_mode = routing_decision.get("execution_mode")
            if execution_mode == "deep_thinking":
                return self._stream_deep_thinking_proposal(routing_decision)

            should_deep_think = False
            logging.info(
                "辅助 Agent 路由决策 intent=%s execution_mode=%s",
                routing_decision.get("intent"), execution_mode,
            )
```

(c) 新增两个私有方法：

```python
    def _stream_deep_thinking_proposal(self, routing_decision: dict):
        import json
        payload = {
            "event": "deep_thinking_proposal",
            "reason": routing_decision.get("reason", ""),
            "estimated_steps": 4,
        }
        yield f"event: deep_thinking_proposal\ndata:{json.dumps(payload, ensure_ascii=False)}\n\n"

    def _stream_insufficient_balance(self, account, conversation, message):
        import json
        yield f"event: error\ndata:{json.dumps({'message': '账户余额不足，无法执行此任务'}, ensure_ascii=False)}\n\n"
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest test/internal/service/test_assistant_agent_service.py -v`
Expected: 全部 PASS（含原有 46 个 + 3 个新测试）

- [ ] **Step 5: 跑全量回归**

Run: `python -m pytest test/internal/service test/internal/entity test/internal/integration -q`
Expected: 无新增失败（已有 2 个 langchain 预存失败除外）

- [ ] **Step 6: 提交**

```bash
git add internal/service/assistant_agent_service.py test/internal/service/test_assistant_agent_service.py
git commit -m "feat: two-phase deep thinking with LLM intent + cost policy guard"
```

---

## Self-Review

**1. Spec coverage:**
- LLM 意图判断 → Task 1（模型）+ Task 2（cheap LLM）+ Task 3（classifier）
- 二阶段请求 → Task 8（chat 二阶段）
- 余额预检接通 → Task 4（RequestContextBuilder）+ Task 5（orchestrator 传递）+ Task 8（读取 allowed）
- schema 改名 → Task 7
- 灰度开关 → Task 6
- SSE 事件 → Task 6 + Task 8

**2. Placeholder scan:** `_classify_remaining` 中的 `...` 表示"将原 classify 的 tool/vertical/general 逻辑搬过来"——这是迁移现有逻辑，不是占位。已在 Step 3 说明。无 TBD/TODO。

**3. Type consistency:** `budget_allowed` 在 RequestContext（Task 4）→ decide()（Task 5）→ classify()（Task 3）链路一致。`confirm_deep_thinking` 在 schema（Task 7）→ chat()（Task 8）一致。`DeepThinkingIntent` 在 entity（Task 1）→ classifier（Task 3）一致。

---

## 执行选择

**计划已保存至 `docs/superpowers/plans/2026-06-19-auto-deep-thinking-plan.md`。两种执行方式：**

**1. Subagent-Driven（推荐）** - 每个 Task 派一个子代理实现，任务间审查，迭代快

**2. Inline Execution** - 在当前会话内逐任务执行，带检查点

选哪种？
