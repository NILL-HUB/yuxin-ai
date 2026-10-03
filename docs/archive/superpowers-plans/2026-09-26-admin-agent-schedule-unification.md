# 管理员 Agent 定时任务统一与无人值守自治 Implementation Plan

> **已归档（2026-10-03）**：五阶段（L1~L5）已全部落地。当前契约见 [admin-agents-api.md](../../api/admin-agents-api.md)（`per_run_tokens` / `admin_agent_chat` 通道）与 [01-agent-tool-pool.md](../../prd/modules/01-agent-tool-pool.md)（`schedule_task` 板块）；本文档仅保留实施过程，**不代表当前实现**。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 admin Agent 的 token 预算记账断链，让定时唤醒走带记忆的多步骤对话链，加入单次唤醒 token 硬顶，最终让 Agent 能自建/删除定时任务并收敛到统一的平台入口。

**Architecture:** 后端已是单一实现（同一 `schedule_task` 表、同一 `ScheduleTaskService`、同一 `ScheduleExecutionService`、同一 Celery beat），不做重建。分五阶段：L1 修 `AdminAgentBudgetGate` 的 token 记账接线；L2 新增 `task_type=admin_agent_chat` 复用既有 `AdminAgentChatService.chat`（旧 `admin_agent_execution` 分支不动）；L3 在 `budget_config` 加 `per_run_tokens` 并在 `_run_tool_loop` 内累计中断；L4 在 `BOARD_ACTIONS` 登记 `schedule_task` 板块让 Agent 获得能力；L5 前端收敛到 `/admin/schedules`，B 通道路由降为薄转发。

**Tech Stack:** Python 3 / Quart / SQLAlchemy / Celery / Redis / injector / pytest；Vue 3 / TypeScript / Arco Design / vue-i18n / vitest；Docker 容器 `llmops-api`（后端 pytest）、`llmops-ui`（前端 vitest）。

**前置：** 本计划 5 个阶段必须按 L1 → L2 → L3 → L4 → L5 顺序执行（L1 不做则 L3/L4 的预算保护形同虚设）。

**Spec:** `docs/archive/superpowers-specs/2026-09-26-admin-agent-schedule-unification-design.md`

---

## 环境与命令速查

**后端测试**（在 `llmops-api` 容器内跑；容器内 pytest 需 `--no-cov`，`pytest.ini` 默认带覆盖率参数会拖慢）：

```bash
docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/<路径> -v --no-cov"
```

**前端测试**（`llmops-ui` 容器有 node，无 python3）：

```bash
docker exec llmops-ui sh -lc "cd /app && npx vitest run src/<路径>"
```

**前端 i18n 一致性（提交前必须通过）：**

```bash
docker exec llmops-ui sh -lc "cd /app && npx vitest run src/i18n/__tests__/parity.spec.ts"
```

**前端类型检查：**

```bash
docker exec llmops-ui sh -lc "cd /app && npx vue-tsc --build --force"
```

---

## 文件结构（改动映射）

| 文件 | 职责 | 阶段 |
|---|---|---|
| `api/internal/service/admin_agent_chat_service.py` | 对话编排：加 token 累计记账 + per-run 硬顶中断 | L1 / L3 |
| `api/internal/service/schedule_task_service.py` | 加 `TASK_TYPE_ADMIN_AGENT_CHAT` 常量 + `create_task` 分支选择 + `update_task` 支持 `admin_agent_id` | L2 / L5 |
| `api/internal/service/schedule_execution_service.py` | 加 `_run_admin_agent_chat` 分支 | L2 |
| `api/internal/service/admin_agent_service.py` | `_validate_budget_config` 加 `per_run_tokens` | L3 |
| `api/internal/core/admin_agent_boards.py` | `BOARD_ACTIONS` 登记 `schedule_task` 板块 | L4 |
| `api/internal/service/admin_agent_board_tools.py` | `BoardToolExecutor._do_schedule_task` 实现体 | L4 |
| `api/app/http/admin_routes_5.py` | 平台级 create/update 补 `admin_agent_id` 透传 | L5 |
| `api/app/http/admin_routes_7.py` | B 通道标注 `PATCH(schedule)` + 清理残留裸 `# ` 行 | L5 |
| `ui/src/views/admin/agents/ListView.vue` | 删手填弹窗 → 跳转；加 `per_run_tokens` 字段 | L3 / L5 |
| `ui/src/views/space/schedules/ListView.vue` | 读 `route.query.agent_id` 过滤 | L5 |
| `ui/src/views/space/schedules/CreateScheduleWizard.vue` | 加「绑定管理端 Agent」选项 | L5 |
| `ui/src/services/admin-agents.ts` | 删 schedule CRUD（改走 schedule-task.ts）；加 per_run_tokens 类型 | L3 / L5 |
| `ui/src/i18n/messages/{zh-CN,en-US}/admin/agents.ts` | 加 `perRunTokens`；调整文案 | L3 / L5 |
| `docs/api/admin-agents-api.md` | B 通道标注兼容别名 | L5 |

---

# L1 — 修复 token 记账断链

## Task 1: 在对话工具循环中累计并记账 token

**背景：** `_run_tool_loop`（`admin_agent_chat_service.py` L207-270）每轮 `bound.invoke(messages)` 的返回值带 `usage_metadata`，但被丢弃。`AdminAgentBudgetGate.record_usage` 的 token 项因此永不累加，`daily_tokens`/`monthly_tokens` 永不触发。

**Files:**
- Modify: `api/internal/service/admin_agent_chat_service.py`（`_run_tool_loop` L207-270、`chat` L113-116 与 L139-155）
- Test: `api/test/internal/service/test_admin_agent_chat_service.py`

- [ ] **Step 1: 写失败测试**

在 `api/test/internal/service/test_admin_agent_chat_service.py` 末尾追加：

```python
def test_tool_loop_records_accumulated_tokens_after_convergence():
    """L1：工具循环收敛后，本轮累计 token 必须写回预算闸门。

    断链背景：`record_usage` 的 token 项此前无调用方传 tokens，
    导致 daily_tokens/monthly_tokens 配置永不生效。
    """
    class _UsageLLM:
        def __init__(self):
            self._scripted = [
                SimpleNamespace(
                    content="",
                    tool_calls=[{"name": "admin_builtin_tool", "args": {"action": "list"}, "id": "c1"}],
                    usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                ),
                SimpleNamespace(
                    content="完成",
                    tool_calls=[],
                    usage_metadata={"input_tokens": 200, "output_tokens": 30, "total_tokens": 230},
                ),
            ]

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return self._scripted.pop(0)

    recorded = {}

    class _RecordingGate:
        def check_and_record(self, *args, **kwargs):
            return None

        def record_usage(self, agent_id, budget_config, *, tokens=0):
            recorded["agent_id"] = agent_id
            recorded["tokens"] = tokens

    llm = _UsageLLM()
    tool = _FakeTool("admin_builtin_tool")
    service = _service(_principal(), llm, [tool])
    service._budget_gate = lambda: _RecordingGate()
    service._load_agent = lambda agent_id, admin_user_id: SimpleNamespace(
        prompt_key=None, budget_config={"daily_tokens": 100000}
    )

    list(
        service.chat(
            agent_id=uuid4(),
            admin_user_id=uuid4(),
            admin_permissions=["builtin_tool:read"],
            query="盘点工具",
        )
    )

    assert recorded.get("tokens") == 350, f"应累计 120+230=350，实际 {recorded.get('tokens')}"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_admin_agent_chat_service.py::test_tool_loop_records_accumulated_tokens_after_convergence -v --no-cov"`

Expected: FAIL，`assert None == 350` 或 `recorded` 为空（因为当前无 `record_usage` 调用）。

- [ ] **Step 3: 实现累计与记账**

**关键（并发安全）：** `AdminAgentChatService` 经 `@inject` 注册为**单例**，多个对话可能并发。**不得**把累计值挂在 `self._last_run_tokens` 上（会互相覆盖）。改用**调用局部**的可变容器 `usage_state: dict`，由 `chat` 创建并传入 `_run_tool_loop`，`finally` 里读同一容器。

在 `admin_agent_chat_service.py` 中修改 `_run_tool_loop`。新增 `usage_state` 参数并累计：

```python
    def _run_tool_loop(
        self, *, llm, system_prompt: str, history, tools, on_tool, usage_state: dict
    ) -> Generator[tuple[str, Any], None, None]:
        """驱动「LLM ⇄ 板块工具」循环（**生成器**）。

        逐次产出 ``("tool", event)``（每完成一次工具调用即产出），使调用方
        得以在循环进行中即时推帧；收敛后产出 ``("answer", text)`` 收尾。

        每轮 LLM 响应的 token 用量累计到**调用局部**的 ``usage_state["tokens"]``
        （不挂 self：本服务是 injector 单例，并发对话会互相覆盖），
        供 ``chat`` 写回预算闸门；L3 的单次硬顶也读同一计数器。
        """
        from langchain_core.messages import SystemMessage, ToolMessage
        from pydantic import ValidationError

        from internal.core.agent.usage_utils import extract_token_usage

        usage_state["tokens"] = 0
        messages: list[Any] = [SystemMessage(content=system_prompt), *history]
        tools_by_name = {tool.name: tool for tool in tools}
        bound = llm.bind_tools(tools) if tools else llm

        for _ in range(MAX_TOOL_ITERATIONS):
            ai = bound.invoke(messages)
            usage = extract_token_usage(ai)
            if usage:
                usage_state["tokens"] += int(usage.get("total_tokens") or 0)
            messages.append(ai)
            calls = list(getattr(ai, "tool_calls", None) or [])
            if not calls:
                yield ("answer", str(getattr(ai, "content", "") or ""))
                return
        # ...（后续 for call in calls 循环原样保留，不重复贴出）
```

保留方法内其余代码不变（`for call in calls:` 段与末尾 `raise FailException(...)`）。

- [ ] **Step 4: 在 `chat` 中创建 `usage_state` 并用 `try/finally` 记账**

**关键：** ① 记账放 `try/finally` 的 `finally`，**不能「循环收敛后再记」**——L3 硬顶会抛 `FailException` 提前跳出循环，收敛后记账会漏掉已消耗的 token；② `usage_state` 是**调用局部** dict，由 `chat` 创建。

修改 `chat` 中 `for kind, payload in self._run_tool_loop(...)` 段（L139-155），并在其前加容器创建：

```python
            # L1：token 累计容器按调用创建（本服务是 injector 单例，不可挂 self）
            usage_state: dict = {"tokens": 0}
            # L1：把本轮累计 token 写回预算闸门——放 finally，保证 L3 硬顶
            # 中断（抛 FailException 提前退出循环）时已消耗的 token 仍被记账，
            # 否则成本统计会漏掉中断那一段。
            try:
                for kind, payload in self._run_tool_loop(
                    llm=llm,
                    system_prompt=system_prompt,
                    history=self._history_for(conversation.id),
                    tools=tools,
                    usage_state=usage_state,
                    on_tool=lambda event: self.append_message(
                        conversation_id=conversation.id,
                        role=AdminAgentMessageRole.TOOL.value,
                        content=json.dumps(event, ensure_ascii=False),
                        tool_calls=[event],
                    ),
                ):
                    if kind == "tool":
                        tool_events.append(payload)
                        yield self._frame(AdminAgentChatEvent.TOOL, payload)
                    else:
                        answer = str(payload or "")
            finally:
                self._budget_gate().record_usage(
                    str(principal.agent_id),
                    getattr(agent, "budget_config", None) or {},
                    tokens=int(usage_state.get("tokens") or 0),
                )
```

- [ ] **Step 6: 给 `_service()` 替身补 `_budget_gate`（保护既有全部用例）**

Task1 后 `chat` 的 `finally` 会调用 `self._budget_gate().record_usage(...)`。既有用例（如 `test_tool_loop_executes_tool_and_returns_answer`）的 `_service()` 未替换 `_budget_gate`，会落到**真实** `AdminAgentBudgetGate` 去访问 `current_app.extensions["redis"]`——测试环境不应依赖它。在 `_service()` 辅助函数（L91-105）中统一加替身：

```python
    service._budget_gate = lambda: SimpleNamespace(
        check_and_record=lambda *a, **k: None,
        record_usage=lambda *a, **k: None,
    )
```

`test_budget_exceeded_...`（L534）在用例内已覆盖 `service._budget_gate` 为 `_BoomGate`，其 `_BoomGate` 只需 `check_and_record`；因该用例在 `check_and_record` 即抛错、不会进循环，`record_usage` 不会被调用，故无需为 `_BoomGate` 添加方法。

- [ ] **Step 7: 运行确认通过**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_admin_agent_chat_service.py -v --no-cov"`

Expected: PASS（新用例 + 既有全部用例通过）。

- [ ] **Step 8: 提交**

```bash
git add api/internal/service/admin_agent_chat_service.py api/test/internal/service/test_admin_agent_chat_service.py
git commit -m "fix(admin-agent): 修复对话链路 token 记账断链"
```

## Task 2: 为无 token 消耗的调用点补注释（不改行为）

**背景：** `admin_routes_7.py` L476 与 `schedule_execution_service.py` L239 走的是单动作直调 service，无 LLM 消耗，`tokens=0` 语义正确。补注释防止后人误以为遗漏。

**Files:**
- Modify: `api/app/http/admin_routes_7.py:476-478`
- Modify: `api/internal/service/schedule_execution_service.py:239-241`

- [ ] **Step 1: 补注释（invoke 路由）**

`admin_routes_7.py` L476 处：

```python
            # tokens=0 是正确语义：invoke 执行单个板块动作、不调 LLM，
            # 无 token 消耗；token 记账在 AdminAgentChatService.chat 的
            # 工具循环收敛后完成（L1）。
            _build_budget_gate().check_and_record(
                str(agent.id), getattr(agent, "budget_config", None) or {}
            )
```

- [ ] **Step 2: 补注释（定时执行）**

`schedule_execution_service.py` L239 处：

```python
        # tokens=0 是正确语义：admin_agent_execution 为单动作执行、不调 LLM；
        # 带 LLM 的 admin_agent_chat 分支由 chat 链路自行记账（L1/L2）。
        _build_budget_gate().check_and_record(
            str(agent.id), getattr(agent, "budget_config", None) or {}
        )
```

- [ ] **Step 3: 跑相关测试**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_schedule_execution_service_admin_agent.py test/app/http/test_admin_agent_invoke_routes.py -v --no-cov"`

Expected: PASS（纯注释，行为不变）。

- [ ] **Step 4: 提交**

```bash
git add api/app/http/admin_routes_7.py api/internal/service/schedule_execution_service.py
git commit -m "docs(admin-agent): 说明单动作路径 tokens=0 语义"
```

---

# L2 — 唤醒链升级（新增 task_type，旧分支不动）

## Task 3: 新增 `TASK_TYPE_ADMIN_AGENT_CHAT` 常量与 `create_task` 分支

**Files:**
- Modify: `api/internal/service/schedule_task_service.py:41-44`（常量）、`L365-380`（`create_task` 分支）
- Test: `api/test/internal/service/test_schedule_task_admin_agent.py`

- [ ] **Step 1: 写失败测试**

在 `api/test/internal/service/test_schedule_task_admin_agent.py` 追加：

```python
def test_create_task_with_admin_agent_defaults_to_chat_type():
    """L2：绑定 admin agent 的新任务默认 admin_agent_chat（带记忆多步骤）。"""
    from internal.service.schedule_task_service import (
        TASK_TYPE_ADMIN_AGENT_CHAT,
        ScheduleTaskService,
    )

    svc = ScheduleTaskService.__new__(ScheduleTaskService)
    captured = {}

    def _create(model, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=uuid4(), **kwargs)

    svc.create = _create
    svc.validate_cron = lambda expr: None
    svc._guess_humanized = lambda expr: expr
    svc.compute_task_next_run = lambda *a, **k: None
    svc._validate_admin_agent_binding = lambda agent_id, admin_user_id: agent_id
    svc._get_platform_account = lambda: SimpleNamespace(id=uuid4())

    agent_id = uuid4()
    task = svc.create_task(
        account=None,
        name="巡检",
        prompt="每天盘点",
        cron_expression="0 9 * * *",
        owner_type="admin",
        admin_agent_id=agent_id,
        admin_user_id=uuid4(),
        admin_agent_chat=True,
    )

    assert captured["task_type"] == TASK_TYPE_ADMIN_AGENT_CHAT
    assert captured["admin_agent_id"] == agent_id
```

- [ ] **Step 2: 运行确认失败**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_schedule_task_admin_agent.py::test_create_task_with_admin_agent_defaults_to_chat_type -v --no-cov"`

Expected: FAIL（`TASK_TYPE_ADMIN_AGENT_CHAT` 不存在 → ImportError，或 `create_task` 不接受 `admin_agent_chat`）。

- [ ] **Step 3: 加常量**

`schedule_task_service.py` L41-44：

```python
TASK_TYPE_APP_EXECUTION = "app_execution"
TASK_TYPE_ASSISTANT_CHAT = "assistant_chat"
TASK_TYPE_ADMIN_AGENT_EXECUTION = "admin_agent_execution"
# L2：绑定 admin agent 时的带记忆多步骤对话类型（走 AdminAgentChatService.chat）
TASK_TYPE_ADMIN_AGENT_CHAT = "admin_agent_chat"
TASK_TYPES = (
    TASK_TYPE_APP_EXECUTION,
    TASK_TYPE_ASSISTANT_CHAT,
    TASK_TYPE_ADMIN_AGENT_EXECUTION,
    TASK_TYPE_ADMIN_AGENT_CHAT,
)
```

- [ ] **Step 4: 改 `create_task` 分支**

`create_task` 签名（L322-339）加参数 `admin_agent_chat: bool = True`。改 L365-373：

```python
        if admin_agent_id:
            if owner_type != "admin":
                raise FailException("仅平台级（owner_type=admin）任务可绑定管理端 Agent")
            if app_id:
                raise FailException("绑定管理端 Agent 的任务不能同时绑定应用")
            normalized_admin_agent_id = self._validate_admin_agent_binding(
                admin_agent_id, admin_user_id
            )
            # L2：默认走带记忆的 chat 链；显式 admin_agent_chat=False 时保留
            # 既有单动作语义（存量任务与需要精确指定 board/action 的场景）。
            normalized_task_type = (
                TASK_TYPE_ADMIN_AGENT_CHAT if admin_agent_chat
                else TASK_TYPE_ADMIN_AGENT_EXECUTION
            )
```

- [ ] **Step 5: 运行确认通过**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_schedule_task_admin_agent.py -v --no-cov"`

Expected: PASS（新用例通过）。**但既有用例 `TestCreateAdminAgentTask::test_sets_type_and_binding`（L30-62）会失败**——它用真实 `create_task` 但未传 `admin_agent_chat`，断言 `created["task_type"] == TASK_TYPE_ADMIN_AGENT_EXECUTION`，改默认后变成 chat。该用例验证的是「单动作语义下 type 与 binding 正确」，故按原意显式传 `admin_agent_chat=False`：

```python
        svc.create_task(
            None,
            "每日巡检",
            "对服务器做巡检",
            "0 0 7 * * *",
            owner_type="admin",
            admin_agent_id=agent_id,
            admin_user_id=admin_user_id,
            admin_agent_chat=False,
            input_params={"board": "builtin_tool", "action": "list", "payload": {}},
        )
```

**另需确认**（无需改动）：`test_admin_agent_schedule_routes.py` 的 `_StubScheduleService.create_task`（L51-58）是**替身**，自带「强制 admin_agent_execution」逻辑，不经过真实 service，故不受本任务影响。跑一遍该文件确认无回归：

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/app/http/test_admin_agent_schedule_routes.py -v --no-cov"`

Expected: PASS（替身逻辑独立，应全绿）。

- [ ] **Step 6: 提交**

```bash
git add api/internal/service/schedule_task_service.py api/test/internal/service/test_schedule_task_admin_agent.py
git commit -m "feat(schedule): 新增 admin_agent_chat 任务类型支持记忆多步骤"
```

## Task 4: 新增 `_run_admin_agent_chat` 执行分支

**Files:**
- Modify: `api/internal/service/schedule_execution_service.py:142-152`（`execute_task` 分支）、新增 `_run_admin_agent_chat`
- Test: `api/test/internal/service/test_schedule_execution_service_admin_agent.py`

- [ ] **Step 1: 写失败测试**

追加到 `test_schedule_execution_service_admin_agent.py`：

```python
class TestRunAdminAgentChat:
    def test_dispatches_admin_agent_chat_to_chat_chain(self, monkeypatch):
        """L2：task_type=admin_agent_chat 时调用 AdminAgentChatService.chat 并取答案。"""
        svc = _svc()
        agent = _agent()
        task = _task(agent.id)
        task.task_type = "admin_agent_chat"
        task.input_params = {}
        task.prompt = "每天盘点工具并汇报"

        def fake_query(model):
            return MagicMock(filter=MagicMock(
                return_value=MagicMock(one_or_none=MagicMock(return_value=agent))
            ))

        monkeypatch.setattr(svc.db.session, "query", fake_query)
        principal = SimpleNamespace(
            admin_user_id=uuid4(),
            agent_id=agent.id,
            effective_permissions=frozenset({"builtin_tool:read"}),
        )
        monkeypatch.setattr(
            module, "_build_admin_agent_principal", lambda a: principal
        )
        gate = MagicMock()
        monkeypatch.setattr(module, "_build_budget_gate", lambda: gate)

        captured = {}

        class _FakeChat:
            def chat(self, **kwargs):
                captured.update(kwargs)
                yield 'event: answer\ndata:{"answer": "巡检完成"}\n\n'
                yield "event: end\ndata:{}\n\n"

        monkeypatch.setattr(
            module, "_build_admin_agent_chat", lambda: _FakeChat()
        )

        summary = svc._run_admin_agent_chat(task)

        assert captured["query"] == "每天盘点工具并汇报"
        assert captured["agent_id"] == agent.id
        assert captured["admin_user_id"] == principal.admin_user_id
        assert "巡检完成" in summary
        gate.check_and_record.assert_called_once_with(
            str(agent.id), agent.budget_config
        )
```

- [ ] **Step 2: 运行确认失败**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_schedule_execution_service_admin_agent.py::TestRunAdminAgentChat -v --no-cov"`

Expected: FAIL（`_run_admin_agent_chat` 不存在）。

- [ ] **Step 3: 加构造接缝**

在 `schedule_execution_service.py` 的 `_build_admin_agent_execution`（L63-79）之后新增：

```python
def _build_admin_agent_chat():
    """构造管理端 Agent 对话链（L2，测试接缝）。"""
    from internal.service.admin_agent_chat_service import AdminAgentChatService

    return current_app.injector.get(AdminAgentChatService)
```

- [ ] **Step 4: 加 `execute_task` 分支**

`execute_task` L142-152：

```python
                if (
                    schedule_task.task_type == "admin_agent_chat"
                    and schedule_task.admin_agent_id
                ):
                    answer = self._run_admin_agent_chat(schedule_task)
                elif (
                    schedule_task.task_type == "admin_agent_execution"
                    and schedule_task.admin_agent_id
                ):
                    answer = self._run_admin_agent(schedule_task)
                elif schedule_task.task_type == "app_execution" and schedule_task.app_id:
                    answer = self._run_bound_app(schedule_task)
                else:
                    answer = self._run_assistant_chat(schedule_task)
```

- [ ] **Step 5: 实现 `_run_admin_agent_chat`**

在 `_run_admin_agent`（L249）之后新增：

```python
    def _run_admin_agent_chat(self, schedule_task: ScheduleTask) -> str:
        """以管理端 Agent 身份跑一次带记忆的多步骤对话（L2）。

        与 ``_run_admin_agent`` 的区别：走 ``AdminAgentChatService.chat``，
        具备记忆召回 / 记忆写入 / 工具循环，能推进多步骤任务；记忆主体键为
        ``MemoryOwnerKey.for_admin(admin_user_id, agent_id=...)``，与管理员
        自身记忆隔离（每 Agent 一份）。
        """
        import json

        from internal.model import AdminAgent

        agent = (
            self.db.session.query(AdminAgent)
            .filter(AdminAgent.id == schedule_task.admin_agent_id)
            .one_or_none()
        )
        if agent is None:
            raise NotFoundException("管理端 Agent 不存在")
        if not bool(getattr(agent, "enabled", True)):
            raise NotFoundException("管理端 Agent 已停用")

        # 预算闸门：executions 计数与周期额度预检（token 由 chat 内部记账）
        _build_budget_gate().check_and_record(
            str(agent.id), getattr(agent, "budget_config", None) or {}
        )

        principal = _build_admin_agent_principal(agent)
        if principal is None:
            raise NotFoundException("管理端 Agent 不可用")

        service = _build_admin_agent_chat()
        answer = ""
        # 传 admin_permissions 用 principal.effective_permissions：它是
        # `compute_effective_permissions(admin_permissions, granted_permissions)`
        # 已算好的三重交集，chat 内部对同一输入再算一次交集是**幂等**的
        # （交集运算满足幂等律 A∩B∩B = A∩B），不会二次收窄权限。
        for frame in service.chat(
            agent_id=agent.id,
            admin_user_id=principal.admin_user_id,
            admin_permissions=list(principal.effective_permissions or []),
            query=schedule_task.prompt or "",
            conversation_id=None,
        ):
            if "event: answer" in frame:
                data_part = frame.split("data:", 1)[1] if "data:" in frame else ""
                try:
                    answer = str(json.loads(data_part).get("answer") or "")
                except Exception:
                    continue
        return answer
```

- [ ] **Step 6: 运行确认通过**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_schedule_execution_service_admin_agent.py -v --no-cov"`

Expected: PASS（新用例 + 既有 `admin_agent_execution` 用例全部通过）。

- [ ] **Step 7: 提交**

```bash
git add api/internal/service/schedule_execution_service.py api/test/internal/service/test_schedule_execution_service_admin_agent.py
git commit -m "feat(schedule): admin_agent_chat 走带记忆对话链执行"
```

---

# L3 — 单次唤醒预算

## Task 5: `budget_config` 增加 `per_run_tokens` 校验

**Files:**
- Modify: `api/internal/service/admin_agent_service.py:292-297`（`_validate_budget_config` 的 key 元组）
- Test: `api/test/internal/service/test_admin_agent_crud_routes.py`（或 `admin_agent_service` 对应测试）

- [ ] **Step 1: 写失败测试**

在 `api/test/internal/service/test_admin_agent_crud_routes.py` 追加：

```python
def test_validate_budget_config_accepts_per_run_tokens():
    """L3：per_run_tokens 必须被写路径接受（单次唤醒 token 硬顶）。"""
    from internal.service.admin_agent_service import AdminAgentService

    result = AdminAgentService._validate_budget_config(
        {"daily_tokens": 1000, "per_run_tokens": 500}
    )
    assert result == {"daily_tokens": 1000, "per_run_tokens": 500}


def test_validate_budget_config_rejects_negative_per_run_tokens():
    from internal.service.admin_agent_service import AdminAgentService
    import pytest

    with pytest.raises(ValueError):
        AdminAgentService._validate_budget_config({"per_run_tokens": -1})
```

- [ ] **Step 2: 运行确认失败**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_admin_agent_crud_routes.py::test_validate_budget_config_accepts_per_run_tokens -v --no-cov"`

Expected: FAIL（`per_run_tokens` 被静默丢弃，`result` 不含该键）。

- [ ] **Step 3: 加入 key 元组**

`admin_agent_service.py` L292-297：

```python
        for key in (
            "daily_executions",
            "monthly_executions",
            "daily_tokens",
            "monthly_tokens",
            "per_run_tokens",
        ):
```

- [ ] **Step 4: 运行确认通过**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_admin_agent_crud_routes.py -v --no-cov"`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add api/internal/service/admin_agent_service.py api/test/internal/service/test_admin_agent_crud_routes.py
git commit -m "feat(admin-agent): budget_config 支持 per_run_tokens"
```

## Task 6: 工具循环内实施 per-run 硬顶中断

**Files:**
- Modify: `api/internal/service/admin_agent_chat_service.py`（`chat` L109-116 取 budget_config、`_run_tool_loop` 累计比对）
- Test: `api/test/internal/service/test_admin_agent_chat_service.py`

- [ ] **Step 1: 写失败测试**

追加：

```python
def test_per_run_tokens_exceeded_interrupts_loop():
    """L3：单次唤醒累计 token 超 per_run_tokens 时中断循环并给可读结论。"""
    class _BigUsageLLM:
        def __init__(self):
            # 每轮都请求工具，token 巨大；若无限轮会持续产出
            self.rounds = 0

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            self.rounds += 1
            return SimpleNamespace(
                content="",
                tool_calls=[{"name": "admin_builtin_tool", "args": {"action": "list"}, "id": f"c{self.rounds}"}],
                usage_metadata={"input_tokens": 600, "output_tokens": 0, "total_tokens": 600},
            )

    llm = _BigUsageLLM()
    tool = _FakeTool("admin_builtin_tool")
    service = _service(_principal(), llm, [tool])
    service._budget_gate = lambda: SimpleNamespace(
        check_and_record=lambda *a, **k: None,
        record_usage=lambda *a, **k: None,
    )
    service._load_agent = lambda agent_id, admin_user_id: SimpleNamespace(
        prompt_key=None, budget_config={"per_run_tokens": 1000}
    )

    frames = list(
        service.chat(
            agent_id=uuid4(),
            admin_user_id=uuid4(),
            admin_permissions=["builtin_tool:read"],
            query="盘点",
        )
    )

    body = "".join(frames)
    # 600*2=1200 > 1000，应在第 2 轮后中断，不得跑满 6 轮
    assert llm.rounds <= 3, f"应在超顶后尽快中断，实际轮数 {llm.rounds}"
    assert "上限" in body
```

- [ ] **Step 2: 运行确认失败**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_admin_agent_chat_service.py::test_per_run_tokens_exceeded_interrupts_loop -v --no-cov"`

Expected: FAIL（跑满 6 轮、body 无"上限"）。

- [ ] **Step 3: 读入 per_run_tokens**

`chat` 在取得 `agent`（L109）后、装 tools（L117）前插入（与 Task1 Step4 的 `usage_state` 同一位置，`per_run_limit` 需先于 tools 装配取得，供 Step 4 与 Task7 使用）：

```python
            budget_config = getattr(agent, "budget_config", None) or {}
            try:
                per_run_limit = int(budget_config.get("per_run_tokens") or 0)
            except (TypeError, ValueError):
                per_run_limit = 0
```

- [ ] **Step 4: 循环内比对中断**

`_run_tool_loop` 每轮累计后比对（在 Task 1 改过的同一段，注意用 `usage_state`、不是 `self`）。方法签名加 `per_run_limit: int = 0`：

```python
    def _run_tool_loop(
        self, *, llm, system_prompt: str, history, tools, on_tool,
        usage_state: dict, per_run_limit: int = 0,
    ) -> Generator[tuple[str, Any], None, None]:
        # ...（前置不变）
        for _ in range(MAX_TOOL_ITERATIONS):
            ai = bound.invoke(messages)
            usage = extract_token_usage(ai)
            if usage:
                usage_state["tokens"] += int(usage.get("total_tokens") or 0)
            # L3：单次唤醒硬顶。超顶立即中断，不让空烧跑到自然收敛或轮次上限。
            if per_run_limit and usage_state["tokens"] >= per_run_limit:
                raise FailException(
                    f"本次唤醒已达单次 token 上限"
                    f"（{usage_state['tokens']}/{per_run_limit}），已中断"
                )
            messages.append(ai)
```

`chat` 调用处传 `per_run_limit=per_run_limit`（与 `usage_state=usage_state` 同行添加）。

- [ ] **Step 5: 运行确认通过**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_admin_agent_chat_service.py -v --no-cov"`

Expected: PASS。既有用例未设 `per_run_tokens`（默认 0=不限制），行为不变。

- [ ] **Step 6: 提交**

```bash
git add api/internal/service/admin_agent_chat_service.py api/test/internal/service/test_admin_agent_chat_service.py
git commit -m "feat(admin-agent): 单次唤醒 token 硬顶中断"
```

## Task 7: 在 system prompt 注入剩余额度

**Files:**
- Modify: `api/internal/service/admin_agent_chat_service.py`（`_build_system_prompt` L344-353、`chat` 调用处 L132-134）
- Test: `api/test/internal/service/test_admin_agent_chat_service.py`

- [ ] **Step 1: 写失败测试**

追加：

```python
def test_system_prompt_includes_remaining_per_run_budget():
    """L3：剩余额度注入 prompt，Agent 据此判断是否安排下次唤醒。"""
    service = AdminAgentChatService.__new__(AdminAgentChatService)
    prompt = service._build_system_prompt(
        _principal(), None, memory_text="", remaining_run_tokens=4000
    )
    assert "4000" in prompt
    assert "下次唤醒" in prompt
```

- [ ] **Step 2: 运行确认失败**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_admin_agent_chat_service.py::test_system_prompt_includes_remaining_per_run_budget -v --no-cov"`

Expected: FAIL（`_build_system_prompt` 不接受 `remaining_run_tokens`）。

- [ ] **Step 3: 改 `_build_system_prompt`**

L344-353：

```python
    def _build_system_prompt(
        self, principal, prompt_key, *, memory_text: str = "",
        remaining_run_tokens: int = 0,
    ) -> str:
        # ...（原 prompt 取用逻辑不变）
        if memory_text:
            prompt = f"{prompt}\n\n## 你记得的相关信息\n{memory_text}"
        if remaining_run_tokens > 0:
            prompt = (
                f"{prompt}\n\n## 本次唤醒剩余 token 额度\n"
                f"{remaining_run_tokens}。若判断即将耗尽，请主动调用定时任务工具"
                f"安排下次唤醒，并在本次答复中说明进度；若任务已无法推进，"
                f"请如实说明而非空转。"
            )
        return prompt
```

- [ ] **Step 4: `chat` 调用处传入**

**时序说明：** `system_prompt` 在 L132 构建，`usage_state` 在循环前（L139 附近）才创建——**此处不得读 `usage_state`**（会 NameError）。而 prompt 构建时本轮尚未消费任何 token，剩余额度就是全额 `per_run_limit`，语义正确。

L132-134 改为：

```python
            system_prompt = self._build_system_prompt(
                principal, getattr(agent, "prompt_key", None),
                memory_text=memory_text,
                remaining_run_tokens=per_run_limit,
            )
```

（`per_run_limit` 须在 Task 6 Step 3 已提前到 tools 装配之前取得，此处可直接引用。）

**同时必须更新测试替身**：`test_admin_agent_chat_service.py` 的 `_service()` 辅助函数（L96）里 `_build_system_prompt` 的 lambda 需接受新参数，否则既有全部用例会 TypeError：

```python
    service._build_system_prompt = (
        lambda p, prompt_key, *, memory_text="", remaining_run_tokens=0: "系统提示词"
    )
```

- [ ] **Step 5: 运行确认通过**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_admin_agent_chat_service.py -v --no-cov"`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add api/internal/service/admin_agent_chat_service.py api/test/internal/service/test_admin_agent_chat_service.py
git commit -m "feat(admin-agent): 注入单次唤醒剩余额度到提示词"
```

## Task 8: 前端预算表单加「单次唤醒 Token」

**Files:**
- Modify: `ui/src/views/admin/agents/ListView.vue:90-95`
- Modify: `ui/src/i18n/messages/zh-CN/admin/agents.ts`、`ui/src/i18n/messages/en-US/admin/agents.ts`
- Test: `ui/src/i18n/__tests__/parity.spec.ts`（自动覆盖）

- [ ] **Step 1: 加 i18n 键（zh-CN）**

`zh-CN/admin/agents.ts` 在 `monthlyTokens` 行后加：

```typescript
  perRunTokens: '单次唤醒 Token 上限',
```

- [ ] **Step 2: 加 i18n 键（en-US）**

`en-US/admin/agents.ts` 对应位置加（值需与 zh 键集合一致）：

```typescript
  perRunTokens: 'Per-run token limit',
```

- [ ] **Step 3: 加表单字段**

`ListView.vue` L90-95：

```typescript
const budgetFields = [
  { key: 'daily_executions', label: t('admin.agents.dailyExecutions') },
  { key: 'monthly_executions', label: t('admin.agents.monthlyExecutions') },
  { key: 'daily_tokens', label: t('admin.agents.dailyTokens') },
  { key: 'monthly_tokens', label: t('admin.agents.monthlyTokens') },
  { key: 'per_run_tokens', label: t('admin.agents.perRunTokens') },
] as const
```

- [ ] **Step 4: 加类型**

`ui/src/services/admin-agents.ts`：`budget_config` 的类型（L17 / L29 / L50）与 `BudgetUsage.usage`（L54 附近）加入 `per_run_tokens?: number` / `per_run_tokens: number`。

- [ ] **Step 5: 跑 i18n parity 与类型检查**

Run: `docker exec llmops-ui sh -lc "cd /app && npx vitest run src/i18n/__tests__/parity.spec.ts"`

Expected: PASS（7/7）。

Run: `docker exec llmops-ui sh -lc "cd /app && npx vue-tsc --build --force"`

Expected: 无新增错误（基线有 19 个既存错误，改动文件不得引入新的）。

- [ ] **Step 6: 提交**

```bash
git add ui/src/views/admin/agents/ListView.vue ui/src/services/admin-agents.ts ui/src/i18n/messages/zh-CN/admin/agents.ts ui/src/i18n/messages/en-US/admin/agents.ts
git commit -m "feat(admin-ui): 预算表单支持单次唤醒 Token 上限"
```

---

# L4 — Agent 自建定时任务

## Task 9: `BOARD_ACTIONS` 登记 `schedule_task` 板块

**Files:**
- Modify: `api/internal/core/admin_agent_boards.py:65-82`
- Test: `api/test/internal/service/test_admin_agent_board_tools.py`（或新 test）

- [ ] **Step 1: 写失败测试**

在 `api/test/internal/service/test_admin_agent_board_tools.py` 追加：

```python
def test_schedule_task_board_actions_are_registered():
    """L4：schedule_task 板块登记 list/create/delete，且不开 update。"""
    from internal.core.admin_agent_boards import (
        board_ids_of,
        resolve_action,
    )

    assert set(board_ids_of("schedule_task")) == {"list", "create", "delete"}
    assert resolve_action("schedule_task", "list").permission_code == "schedule_task:read"
    assert resolve_action("schedule_task", "create").permission_code == "schedule_task:create"
    assert resolve_action("schedule_task", "delete").kind == "delete"
```

- [ ] **Step 2: 运行确认失败**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_admin_agent_board_tools.py::test_schedule_task_board_actions_are_registered -v --no-cov"`

Expected: FAIL（板块未登记 → ValueError）。

- [ ] **Step 3: 登记板块**

`admin_agent_boards.py` 的 `BOARD_ACTIONS` 元组末尾追加：

```python
    # -------- 定时任务（L4：Agent 自治调度，实现无人值守自拉起）--------
    _a("schedule_task", "list", "read", "schedule_task:read", "列出平台级定时任务"),
    _a("schedule_task", "create", "write", "schedule_task:create", "创建定时任务"),
    # delete 走回收站（可恢复），故按 kind=delete 由既有分流处理
    _a("schedule_task", "delete", "delete", "schedule_task:delete", "删除定时任务（进回收站可恢复）"),
```

- [ ] **Step 4: 运行确认通过**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_admin_agent_board_tools.py -v --no-cov"`

Expected: PASS。若既有「board 数量」断言基准写死，同步更新该断言并说明新增板块。

- [ ] **Step 5: 提交**

```bash
git add api/internal/core/admin_agent_boards.py api/test/internal/service/test_admin_agent_board_tools.py
git commit -m "feat(admin-agent): 登记 schedule_task 板块能力"
```

## Task 10: `BoardToolExecutor._do_schedule_task` 实现体

**Files:**
- Modify: `api/internal/service/admin_agent_board_tools.py`（`_do_builtin_tool` 之后新增 `_do_schedule_task`）
- Test: `api/test/internal/service/test_admin_agent_board_tools.py`

- [ ] **Step 1: 写失败测试**

追加：

```python
def test_do_schedule_task_create_uses_service(monkeypatch):
    """L4：create action 复用 ScheduleTaskService.create_task。"""
    from internal.service.admin_agent_board_tools import BoardToolExecutor
    import internal.service.admin_agent_board_tools as mod

    captured = {}

    class _FakeSvc:
        def create_task(self, account, name, prompt, cron_expression, **kwargs):
            captured.update({"name": name, "cron": cron_expression, **kwargs})
            return SimpleNamespace(id="task-1", name=name)

    monkeypatch.setattr(
        mod, "ScheduleTaskService", None, raising=False
    )
    executor = BoardToolExecutor()
    monkeypatch.setattr(
        executor, "_schedule_task_service", lambda: _FakeSvc(), raising=False
    )

    principal = SimpleNamespace(
        admin_user_id=uuid4(), agent_id=uuid4(),
        has_permission=lambda code: True,
        automation_level_for=lambda board: None,
    )
    import internal.core.admin_agent_boards as boards_mod
    from internal.entity.admin_agent_entity import AutomationLevel
    monkeypatch.setattr(
        boards_mod, "resolve_action",
        lambda b, a: SimpleNamespace(
            board=b, action=a, kind="write",
            permission_code="schedule_task:create", is_write=True,
        ),
    )

    result = executor._do_schedule_task(
        principal, action="create",
        payload={"name": "巡检", "prompt": "盘点", "cron_expression": "0 9 * * *"},
    )
    assert captured["name"] == "巡检"
    assert result["action"] == "create"
```

- [ ] **Step 2: 运行确认失败**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_admin_agent_board_tools.py::test_do_schedule_task_create_uses_service -v --no-cov"`

Expected: FAIL（`_do_schedule_task` 不存在 → `execute` 抛"板块尚未实现"）。

- [ ] **Step 3: 实现 `_do_schedule_task`**

在 `admin_agent_board_tools.py` 的 `_do_builtin_tool` 方法之后新增：

```python
    # ------------------------------------------------------------------
    # schedule_task（L4：Agent 自治调度）
    # ------------------------------------------------------------------

    @staticmethod
    def _schedule_task_service():
        from app.http import asgi_app as a
        from internal.service.schedule_task_service import ScheduleTaskService

        return a._get_service(ScheduleTaskService)

    def _do_schedule_task(
        self, principal, *, action: str, payload: dict
    ) -> dict:
        """定时任务板块：复用 ScheduleTaskService，不重写增删逻辑。

        仅开放 list/create/delete——不开 update：回收站只快照「删除那一刻」，
        改错无回滚路径，「改任务」以 删旧的 + 建新的 表达，两步都在回收站
        覆盖内，安全模型自洽（设计 §7）。
        """
        service = self._schedule_task_service()

        if action == "list":
            tasks, total = service.list_tasks(
                None, 1, 50, owner_type="admin"
            )
            return {
                "board": "schedule_task",
                "action": "list",
                "total": total,
                "items": [
                    {
                        "id": str(t.id),
                        "name": t.name,
                        "cron_expression": t.cron_expression,
                        "enabled": t.enabled,
                        "task_type": t.task_type,
                    }
                    for t in tasks
                ],
            }

        if action == "create":
            name = str(payload.get("name") or "").strip()
            prompt = str(payload.get("prompt") or "").strip()
            cron_expression = str(payload.get("cron_expression") or "").strip()
            if not name or not prompt or not cron_expression:
                raise FailException("create 需要 name / prompt / cron_expression")
            task = service.create_task(
                None,
                name,
                prompt,
                cron_expression,
                owner_type="admin",
                admin_agent_id=principal.agent_id,
                admin_user_id=principal.admin_user_id,
            )
            return {
                "board": "schedule_task",
                "action": "create",
                "id": str(task.id),
                "name": task.name,
            }

        if action == "delete":
            task_id = payload.get("task_id")
            if not task_id:
                raise FailException("delete 需要 task_id")
            service.delete_task(task_id, None, owner_type="admin")
            return {"board": "schedule_task", "action": "delete", "task_id": str(task_id)}

        raise FailException(f"schedule_task 未实现 action: {action}")
```

- [ ] **Step 4: 运行确认通过**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_admin_agent_board_tools.py -v --no-cov"`

Expected: PASS。

- [ ] **Step 5: 跑端到端接线测试**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/internal/service/test_admin_agent_chat_service.py test/internal/service/test_admin_agent_execution_service.py -v --no-cov"`

Expected: PASS（`build_board_tools` 现在会为 `schedule_task` 生成 `admin_schedule_task` 工具）。

- [ ] **Step 6: 提交**

```bash
git add api/internal/service/admin_agent_board_tools.py api/test/internal/service/test_admin_agent_board_tools.py
git commit -m "feat(admin-agent): Agent 可 list/create/delete 定时任务"
```

---

# L5 — 入口统一（收编 B 通道）

## Task 11: 平台级路由支持 `admin_agent_id` 透传

**Files:**
- Modify: `api/app/http/admin_routes_5.py:61-109`（create）、`L229-267`（update）
- Modify: `api/internal/service/schedule_task_service.py:407-425`（`update_task` 加 `admin_agent_id`）
- Test: `api/test/app/http/test_admin_routes_5.py`

- [ ] **Step 1: 写失败测试**

先把 `test_admin_routes_5.py` 的 `_FakeScheduleTaskService.create_task`（L63-65）改为记录 kwargs：

```python
    def create_task(self, account, name, prompt, cron_expression, **kwargs):
        self.calls.append(("create", name, kwargs))
        return self._task()
```

注意：该改动会让既有断言 `task_service.calls[0] == ("create", "任务A")`（L170）与 `calls[0][0] == "create"`（L220）形式变化——前者改为 `calls[0][:2] == ("create", "任务A")`，后者 `calls[0][0]` 不受影响。同步修正 L170。

然后在 `TestAdminScheduleTask` 内追加：

```python
    def test_create_task_passes_admin_agent_id(self, monkeypatch):
        """L5：平台级 create 透传 admin_agent_id（统一入口的关键）。"""
        task_service, _ = self._setup(monkeypatch)
        agent_id = str(uuid4())

        async def _run():
            async with asgi_app.quart_app.test_client() as client:
                resp = await client.post(
                    "/admin/schedule-tasks",
                    json={
                        "name": "Agent 巡检",
                        "prompt": "每天盘点",
                        "cron_expression": "0 9 * * *",
                        "admin_agent_id": agent_id,
                    },
                )
                return resp, await resp.json

        resp, payload = asyncio.run(_run())
        assert resp.status_code == 200
        _, _, kwargs = task_service.calls[0]
        assert str(kwargs["admin_agent_id"]) == agent_id
        assert kwargs["admin_user_id"] is not None
```

- [ ] **Step 2: 运行确认失败**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/app/http/test_admin_routes_5.py::test_admin_schedule_create_passes_admin_agent_id -v --no-cov"`

Expected: FAIL（当前 create 不透传该字段）。

- [ ] **Step 3: create 透传**

**注意（重要）：** `/admin/*` 的权限由全局 `before_request`（`asgi_app._enforce_admin_rbac` → `support._admin_route_permission`）强制，`admin/schedule-tasks` 已映射（`support.py` L614-630）。**路由内不得重复做权限校验**，只需在需要 `admin_user_id` 时解析身份。与既有的 delete 路由（`admin_routes_5.py` L273 `_resolve_admin_operator`）保持一致。

`admin_routes_5.py` 的 `admin_schedule_task_create`（L61-117）在取 body 后、调用 `create_task` 前加：

```python
        admin_agent_id = body.get("admin_agent_id") or None
        admin_user_id = None
        if admin_agent_id:
            admin, err = await a._resolve_admin_operator()
            if err is not None:
                return err
            admin_user_id = admin.id
```

`create_task` 调用（L94-109）加两个参数：

```python
                admin_agent_id=admin_agent_id,
                admin_user_id=admin_user_id,
```

- [ ] **Step 4: update 支持 admin_agent_id**

`schedule_task_service.py::update_task` 签名（L407-425）加 `admin_agent_id=None` 与 `admin_user_id=None`；在 `updates` 构造处（L437 附近）加：

```python
        if admin_agent_id is not None:
            updates["admin_agent_id"] = self._validate_admin_agent_binding(
                admin_agent_id, admin_user_id
            )
            updates["task_type"] = TASK_TYPE_ADMIN_AGENT_CHAT
```

`admin_routes_5.py` 的 update 路由（L229-267）同样按 Step 3 的方式解析 `admin_user_id`（仅当 body 含 `admin_agent_id`），并把 `admin_agent_id` / `admin_user_id` 透传给 `update_task`。

- [ ] **Step 5: list 支持 agent_id 过滤**

`admin_routes_5.py` 的 list 路由（L44-59）读取 `request.args.get("agent_id")` 并传给 `list_tasks`（该 service 方法已支持 `agent_id` 过滤，`schedule_task_service.py` L543-544）：

```python
        agent_id = request.args.get("agent_id") or None
        tasks, total = await a._to_thread(
            a._get_service(ScheduleTaskService).list_tasks,
            None,
            page,
            page_size,
            "admin",
            agent_id=agent_id,
        )
```

- [ ] **Step 6: 运行确认通过**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/app/http/test_admin_routes_5.py -v --no-cov"`

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add api/app/http/admin_routes_5.py api/internal/service/schedule_task_service.py api/test/app/http/test_admin_routes_5.py
git commit -m "feat(schedule): 平台级路由支持绑定 admin agent"
```

## Task 12: B 通道路由标注兼容别名 + 清理残留

**Files:**
- Modify: `api/app/http/admin_routes_7.py:580-708`（3 个路由加注释）、`L596`、`L682`（删裸 `# ` 行）

- [ ] **Step 1: 删残留裸行**

删除 `admin_routes_7.py` L596 与 L682 两处仅含 `# ` 的行（`from uuid import UUID` 之前的孤立注释行）。

- [ ] **Step 2: 加兼容别名注释**

`admin_agent_schedule_create`（L580）、`admin_agent_schedule_list`（L645）、`admin_agent_schedule_delete`（L669）三处 docstring 末尾统一加：

```
        PATCH(schedule): 兼容别名——能力已统一到平台级 /admin/schedule-tasks
        （前端已跳转该页）。本路由保留供旧客户端过渡，内部仍调同一
        ScheduleTaskService；收编计划：待旧客户端下线后移除。
```

- [ ] **Step 3: 跑回归**

Run: `docker exec llmops-api sh -lc "cd /app/api && python -m pytest test/app/http/test_admin_agent_schedule_routes.py -v --no-cov"`

Expected: PASS（纯注释与空行删除）。

- [ ] **Step 4: 提交**

```bash
git add api/app/http/admin_routes_7.py
git commit -m "chore(schedule): B 通道标注兼容别名并清理残留"
```

## Task 13: 前端 Agent 页改跳转 + 向导加 Agent 绑定

**Files:**
- Modify: `ui/src/views/admin/agents/ListView.vue`（删弹窗相关 L269-353 及其模板/状态）
- Modify: `ui/src/views/space/schedules/ListView.vue`（读 `route.query.agent_id`）
- Modify: `ui/src/views/space/schedules/CreateScheduleWizard.vue`（加绑定选项）
- Modify: `ui/src/services/admin-agents.ts`（删 `listSchedules`/`createSchedule`/`deleteSchedule`）
- Test: `ui/src/views/admin/agents/__tests__/ListView.spec.ts`、`CreateScheduleWizard.spec.ts`

- [ ] **Step 1: ListView.vue 改为跳转**

移除 `scheduleModalVisible`/`schedules`/`scheduleForm`/`openSchedules`/`loadSchedules`/`submitSchedule`/`handleDeleteSchedule` 及对应模板弹窗；`openSchedules` 替换为：

```typescript
const openSchedules = (agent: AdminAgent) => {
  router.push({ name: 'admin-schedules', query: { agent_id: agent.id } })
}
```

（需 `import { useRouter } from 'vue-router'` 并 `const router = useRouter()`。）

- [ ] **Step 2: schedules/ListView.vue 读取过滤**

在 `loadTasks` 里带上 `agent_id`：

```typescript
const agentFilter = computed(() => String(route.query.agent_id || ''))
// loadTasks 内：
const res = await listScheduleTasks(page.value, pageSize.value, isAdminContext.value, agentFilter.value)
```

`ui/src/services/schedule-task.ts` 的 `listScheduleTasks` 增加第 4 个可选参数 `agentId?: string`，非空时 query 追加 `agent_id`；后端 `list_tasks` 已支持 `agent_id` 过滤（`schedule_task_service.py` L543-544），需在 `admin_routes_5.py` 的 list 路由读取 `request.args.get("agent_id")` 并传入。

- [ ] **Step 3: 向导加绑定选项**

`CreateScheduleWizard.vue` 在 `isAdminContext` 为真时展示「绑定管理端 Agent」下拉（选项来自 `listAgents()`），选中则提交 `admin_agent_id`；`boundAppId` 与 `admin_agent_id` 互斥（二选一，参考后端 L368-369 的校验）。

- [ ] **Step 4: 更新测试**

`ListView.spec.ts`：把 `listSchedules`/`createSchedule`/`deleteSchedule` 的 mock 替换为「跳转被调用」的断言。
`CreateScheduleWizard.spec.ts`：加 agent 绑定提交用例。

- [ ] **Step 5: 跑前端测试**

Run: `docker exec llmops-ui sh -lc "cd /app && npx vitest run src/views/admin/agents src/views/space/schedules"`

Expected: PASS。

- [ ] **Step 6: i18n parity + 类型检查**

Run: `docker exec llmops-ui sh -lc "cd /app && npx vitest run src/i18n/__tests__/parity.spec.ts"`

Expected: PASS。

Run: `docker exec llmops-ui sh -lc "cd /app && npx vue-tsc --build --force"`

Expected: 无新增错误。

- [ ] **Step 7: 提交**

```bash
git add ui/src/views/admin/agents ui/src/views/space/schedules ui/src/services/admin-agents.ts ui/src/services/schedule-task.ts
git commit -m "feat(admin-ui): 定时任务入口统一到平台页"
```

## Task 14: 同步 API 与架构文档

**Files:**
- Modify: `docs/api/admin-agents-api.md:308-333`
- Modify: `docs/prd/modules/*.md`（涉及 admin Agent 定时任务的板块）

- [ ] **Step 1: API 文档标注**

`admin-agents-api.md` 三个 schedules 端点章节各加一行：

```
> 兼容别名：能力已统一到 `POST/GET /admin/schedule-tasks`（支持 `admin_agent_id`）。本端点保留供旧客户端过渡。
```

- [ ] **Step 2: 架构文档同步**

在 admin Agent 对应模块文档补：L2 新增 `task_type=admin_agent_chat`、L3 `per_run_tokens`、L4 `schedule_task` 板块。按 AGENTS.md 规则核对代码后再写，不照抄旧表述。

- [ ] **Step 3: 提交**

```bash
git add docs/api/admin-agents-api.md docs/prd
git commit -m "docs: 同步定时任务统一与 Agent 自治能力"
```

---

## Self-Review（计划自审结论）

**1. Spec 覆盖：** §4→Task1-2；§5→Task3-4；§6→Task5-8；§7→Task9-10；§8→Task11-13；§9 接线面→各 Task 均含入口；§11 契约→Task14。无遗漏。

**2. 占位符：** 无。所有代码步骤均含完整代码（含 Task11 的完整测试体与 `_FakeScheduleTaskService` 改造、Task1 的 `try/finally` 完整替换块）。

**3. 类型一致性：** `TASK_TYPE_ADMIN_AGENT_CHAT`（Task3 定义 → Task4/11 使用）；`usage_state`（Task1 定义 → Task6/7 使用）；`per_run_limit`（Task6 Step3 定义 → Task6 Step4 用 `usage_state`、Task7 用全额）；`_do_schedule_task`（Task9 登记 → Task10 实现）——命名跨任务一致。

**注意（执行时务必遵守）：** ① Task3 Step5 会改变 `admin_agent_id` 任务的默认 `task_type`，既有 `test_sets_type_and_binding` 需显式传 `admin_agent_chat=False`；② Task6 Step3 取 `per_run_limit` 与 Task1 Step4 创建 `usage_state` 必须在**同一位置**（tools 装配之前），Task7 的 prompt 构建引用 `per_run_limit`（不读 `usage_state`）；③ token 计数一律走调用局部 `usage_state`，**禁止**挂 `self`（单例并发会互相覆盖）。
