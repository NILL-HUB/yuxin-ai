# Phase 12：用户侧实时计费、任务终止与已发生成本展示 执行计划

> **目标：** 让长任务、多 Agent、deep thinking 和工具调用过程中，用户可以实时看到已发生的积分/token 消耗，并可以主动停止后续执行，停止后返回已完成内容和已发生成本。

**架构：** 在 `AssistantAgentService.chat` 的 SSE 循环中接入 `BillingUsageAggregator`，按 token 消耗产出 `billing_delta` 事件并推送；停止时联动产出 `billing_cancelled`，正常结束产出 `billing_final`；前端 `chat-stream.ts` 新增 billing 事件分支，路由到 `BillingUsageIndicator` 组件实时展示。

**技术栈：** Python 3.11 / Flask / LangGraph / SSE / Vue 3 / Arco Design Vue / TypeScript

---

## 1. 现状基线

### 已有基础设施（复用，不重做）

| 模块 | 状态 | 文件 |
|------|------|------|
| BillingEventType 枚举（5 个事件） | 已实现 | `api/internal/entity/billing_metering_entity.py` |
| BillingUsageDelta 数据类（含 to_sse 方法） | 已实现 | `api/internal/entity/billing_metering_entity.py` |
| BillingUsageAggregator（started/delta/summary/cancelled/final） | 已实现 | `api/internal/service/billing_metering_service.py` |
| QueueEvent 后端枚举（含 5 个 billing 事件） | 已实现 | `api/internal/core/agent/entities/queue_entity.py` |
| AgentQueueManager（publish/listen/stop_flag） | 已实现 | `api/internal/core/agent/agents/agent_queue_manager.py` |
| stop_chat 后端接口 | 已实现 | `api/internal/service/assistant_agent_service.py:570` |
| 前端停止按钮（4 个场景） | 已实现 | `HomeView.vue` / `PreviewDebugChat.vue` 等 |
| 前端 stopAssistantAgentChat API | 已实现 | `ui/src/services/assistant-agent.ts:58` |
| BillingUsageIndicator 组件 + 测试 | 已实现 | `ui/src/components/BillingUsageIndicator.vue` |
| 前端 BillingUsageEvent 类型 | 已实现 | `ui/src/models/billing-metering.ts` |

### 关键未闭环点（Phase 12 核心任务）

1. **SSE 流不推送 billing 事件**：`chat` 方法的 SSE 循环只推送 agent_thought 事件，`billing_started/delta/summary/cancelled/final` 从未在 SSE 中推送。
2. **前端 QueueEvent 缺 5 个 billing 事件**：前端 `config/index.ts` 的 QueueEvent 缺失 billingStarted 等，导致 billing 事件落入 else 分支被当普通 thought 处理。
3. **BillingUsageIndicator 未挂载**：组件已实现但无任何视图导入使用。
4. **停止时不联动 billing_cancelled**：`stop_chat` 只设 Redis 标志，不产出 billing_cancelled，不返回已发生成本摘要。
5. **AgentQueueManager 终态白名单风险**：一旦 AGENT_END 推送，后续 billing_final 会被丢弃。

---

## 2. 文件结构

### 需要修改的文件

| 文件 | 职责 | 改动 |
|------|------|------|
| `api/internal/service/assistant_agent_service.py` | SSE 流式推送 | chat 方法接入 BillingUsageAggregator，推送 5 个 billing 事件 |
| `api/internal/core/agent/agents/agent_queue_manager.py` | 队列终态白名单 | 确保 billing_final 不被 AGENT_END 后丢弃 |
| `api/internal/core/agent/agents/function_call_agent.py` | Agent 工具节点 | _tools_node 按工具调用产出 billing_delta |
| `ui/src/config/index.ts` | 前端 QueueEvent | 补齐 5 个 billing 事件 |
| `ui/src/views/shared/chat-stream.ts` | 前端流式处理 | 新增 billing 事件分支，路由到 indicator |
| `ui/src/views/pages/HomeView.vue` | 首页助手 | 挂载 BillingUsageIndicator + 停止后摘要 |
| `ui/src/views/space/apps/components/PreviewDebugChat.vue` | 应用调试 | 挂载 BillingUsageIndicator |
| `ui/src/i18n/messages/zh-CN.ts` | 中文 i18n | 新增 billing.realtime 段落 |
| `ui/src/i18n/messages/en-US.ts` | 英文 i18n | 新增 billing.realtime 段落 |

### 需要新建的文件

| 文件 | 职责 |
|------|------|
| `api/test/internal/service/test_billing_sse_integration.py` | billing SSE 推送集成测试 |
| `api/test/internal/service/test_billing_cancel_summary.py` | 停止后成本摘要测试 |
| `ui/src/components/__tests__/BillingUsageIndicator.realtime.spec.ts` | 实时计费指示器增强测试 |

---

## 3. 任务分解

### 任务 0：基线确认

- [ ] 跑后端全量测试 `docker compose exec llmops-api pytest -q --no-cov`，确认 2176 passed
- [ ] 跑前端全量测试 `npm run test:unit`，确认 368 passed
- [ ] 确认 migration head 为 `d1e2f3a4b5d4`

### 任务 1：AgentQueueManager 终态白名单修复

**Files:**
- Modify: `api/internal/core/agent/agents/agent_queue_manager.py`
- Test: `api/test/internal/core/agent/test_agent_queue_manager_billing.py`

- [ ] **Step 1: 写失败测试** - 验证 AGENT_END 后仍能推送 billing_final

```python
def test_billing_final_should_not_be_dropped_after_agent_end():
    from internal.core.agent.agents.agent_queue_manager import AgentQueueManager
    from internal.core.agent.entities.queue_entity import QueueEvent
    from internal.core.agent.entities.agent_entity import AgentThought
    from uuid import uuid4

    task_id = uuid4()
    manager = AgentQueueManager.__new__(AgentQueueManager)
    manager._terminal_events = {}

    manager.publish(task_id, AgentThought(
        id=uuid4(), task_id=task_id,
        event=QueueEvent.AGENT_END.value,
    ))
    result = manager.publish(task_id, AgentThought(
        id=uuid4(), task_id=task_id,
        event=QueueEvent.BILLING_FINAL.value,
    ))
    assert result is not False, "billing_final 不应在 AGENT_END 后被丢弃"
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 修改 publish 方法** - 将 BILLING_FINAL 和 BILLING_CANCELLED 加入终态事件白名单的允许通过集合

- [ ] **Step 4: 跑测试确认通过**

### 任务 2：AssistantAgentService.chat 接入 billing SSE 推送

**Files:**
- Modify: `api/internal/service/assistant_agent_service.py` (chat 方法)
- Test: `api/test/internal/service/test_billing_sse_integration.py`

- [ ] **Step 1: 写失败测试** - 验证 chat SSE 流包含 billing_started、billing_delta、billing_final 事件

```python
def test_chat_sse_should_push_billing_events(monkeypatch):
    """验证 SSE 流包含 billing_started / billing_delta / billing_final"""
    events = list(collect_sse_events(mock_chat_request))
    event_types = [e["event"] for e in events]
    assert "billing_started" in event_types
    assert "billing_delta" in event_types
    assert "billing_final" in event_types
```

- [ ] **Step 2: 实现 billing 接入** - 在 chat 方法中：
  - 循环开始前：`aggregator.started()` → 推送 `billing_started`
  - 循环中：检测 agent_thought 的 token 消耗 → `aggregator.model_tokens()` → 推送 `billing_delta`
  - 循环正常结束：`aggregator.final()` → 推送 `billing_final`
  - 循环异常/停止：`aggregator.cancelled()` → 推送 `billing_cancelled`

- [ ] **Step 3: 推送格式** - 使用 `BillingUsageDelta.to_sse()` 方法序列化

```python
billing_event = aggregator.started()
yield f"event: {billing_event.event_type}\ndata:{json.dumps(billing_event.to_dict())}\n\n"
```

- [ ] **Step 4: 跑测试确认通过**

### 任务 3：停止联动 billing_cancelled + 已发生成本摘要

**Files:**
- Modify: `api/internal/service/assistant_agent_service.py` (stop_chat 方法)
- Test: `api/test/internal/service/test_billing_cancel_summary.py`

- [ ] **Step 1: 写失败测试** - 验证停止后返回已发生成本摘要

```python
def test_stop_chat_should_return_billing_summary():
    result = AssistantAgentService.stop_chat_with_summary(task_id, account)
    assert "total_credits" in result
    assert "completed_steps" in result
    assert "cancelled" in result
```

- [ ] **Step 2: 实现 stop_chat_with_summary** - 在停止时查询已发生的 billing 事件，返回摘要

- [ ] **Step 3: 更新 stop 路由** - 返回摘要而非空响应

- [ ] **Step 4: 跑测试确认通过**

### 任务 4：FunctionCallAgent _tools_node 产出 billing_delta

**Files:**
- Modify: `api/internal/core/agent/agents/function_call_agent.py` (_tools_node)

- [ ] **Step 1: 在 _tools_node 工具调用成功后** - 通过 AgentThought 的 metadata 携带 token 消耗信息

- [ ] **Step 2: chat 方法检测工具调用事件** - 提取 metadata 中的 token 消耗，调用 `aggregator.model_tokens()` 产出 billing_delta

- [ ] **Step 3: 跑全量测试确认无回归**

### 任务 5：前端 QueueEvent 补齐 billing 事件

**Files:**
- Modify: `ui/src/config/index.ts`

- [ ] **Step 1: 补齐 5 个 billing 事件**

```typescript
export const QueueEvent = {
  // ... 现有事件
  billingStarted: 'billing_started',
  billingDelta: 'billing_delta',
  billingSummary: 'billing_summary',
  billingCancelled: 'billing_cancelled',
  billingFinal: 'billing_final',
}
```

- [ ] **Step 2: 跑 type-check 确认无错误**

### 任务 6：前端 chat-stream.ts 处理 billing 事件

**Files:**
- Modify: `ui/src/views/shared/chat-stream.ts`

- [ ] **Step 1: 新增 billing 事件分支** - 在 agent_action 和 deep_thinking 分支之间插入

```typescript
else if (event === QueueEvent.billingStarted ||
         event === QueueEvent.billingDelta ||
         event === QueueEvent.billingSummary ||
         event === QueueEvent.billingCancelled ||
         event === QueueEvent.billingFinal) {
    nextState.billingEvents = [
        ...(state.billingEvents || []),
        data as BillingUsageEvent,
    ]
    return { state: nextState, didUpdate: true }
}
```

- [ ] **Step 2: StreamState 新增 billingEvents 字段**

- [ ] **Step 3: 跑前端测试确认无回归**

### 任务 7：前端挂载 BillingUsageIndicator

**Files:**
- Modify: `ui/src/views/pages/HomeView.vue`
- Modify: `ui/src/views/space/apps/components/PreviewDebugChat.vue`
- Test: `ui/src/components/__tests__/BillingUsageIndicator.realtime.spec.ts`

- [ ] **Step 1: HomeView 挂载 indicator** - 在对话区域底部展示实时消耗

```vue
<BillingUsageIndicator
  v-if="billingEvents.length > 0"
  :events="billingEvents"
/>
```

- [ ] **Step 2: PreviewDebugChat 同步挂载**

- [ ] **Step 3: 停止后摘要展示** - billing_cancelled 事件触发后展示已完成内容和已发生成本

- [ ] **Step 4: 新增 i18n** - billing.realtime 段落（已发生消耗、停止后摘要、未执行阶段等）

- [ ] **Step 5: 跑前端测试确认通过**

### 任务 8：最终全量测试与文档同步

- [ ] 跑后端全量测试
- [ ] 跑前端全量测试 + type-check + lint
- [ ] 跑 migration 验证
- [ ] 更新 PRD 当前状态为"Phase 1-12 已提交"
- [ ] 更新 Phase 12 执行计划完成状态
- [ ] git commit

---

## 4. 验收标准（对齐 PRD 16.13）

1. 用户侧只展示当前已发生消耗，不展示预估最终成本 ✅ BillingUsageIndicator 只展示 total_credits
2. 所有增量消耗必须来自后端 billing event，前端不自行估算 ✅ 前端只渲染后端推送的 billing_delta
3. 用户停止后，未开始子任务不计费，已完成部分正常计费 ✅ stop 时产出 billing_cancelled，已完成的 billing_delta 已推送
4. 停止后仍返回已完成内容、已发生成本和未执行阶段说明 ✅ stop_chat_with_summary 返回摘要
5. 高风险工具确认 UI 中展示的当前消耗与主任务计费 UI 一致 ✅ 共用同一 BillingUsageAggregator

---

## 5. 推荐执行顺序

1. 任务 0：基线确认
2. 任务 1：AgentQueueManager 终态白名单修复（前置，防止 billing_final 被丢弃）
3. 任务 2：chat 接入 billing SSE 推送（核心）
4. 任务 3：停止联动 billing_cancelled + 摘要
5. 任务 4：_tools_node 产出 billing_delta
6. 任务 5：前端 QueueEvent 补齐
7. 任务 6：前端 chat-stream 处理 billing 事件
8. 任务 7：前端挂载 BillingUsageIndicator + 停止摘要
9. 任务 8：最终全量测试与文档同步

---

## 6. 风险与约束

| 风险 | 应对 |
|------|------|
| billing_final 被 AGENT_END 后丢弃 | 任务 1 先修复终态白名单 |
| 停止延迟最长 1 秒 | 复用现有 Redis 轮询，不引入 asyncio.CancelledError |
| billing_delta 推送过于频繁影响 SSE 性能 | 按 LLM 调用批次推送（不是按 token），每次 llm 调用结束才推送一次 |
| 前端 billing 事件污染 agent_thoughts | 任务 6 新增独立分支，不落入 else |
