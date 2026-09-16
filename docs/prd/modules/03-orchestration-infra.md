# 模型路由、编排执行、结果汇总与可观测性

> 本文档为主架构文档的子模块，包含模型路由/模型池与提供商体系/成本控制、编排执行（Conductor + ExecutionCoordinatorService）、ResultSynthesizer 设计和可观测性与审计的完整内容。
>
> **主文档**: [architecture-design.md](../architecture-design.md)
> **相关模块**: [01-agent-tool-pool.md](./01-agent-tool-pool.md) | [02-knowledge-base.md](./02-knowledge-base.md)
>
> **定位与现状**：本模块的编排主导权已由旧 Orchestrator 串行决策移交至 **Conductor（指挥官）+ ExecutionCoordinatorService（执行编排）** 主导的现状。OrchestratorService 仍保留为旧链路（规则决策），并在 `ENABLE_CONDUCTOR` 开启时委托 Conductor、失败回退旧链路（见 [architecture-design.md](../architecture-design.md) 与 [execution-roadmap.md](../execution-roadmap.md) 2026-08-26 记录）。早期叙事中的 DAGEngine（`dag_entity` / `dag_engine_service` / `agent_instance_pool` / `test_dag_engine`）已删除，统一为 `TaskPlan + ExecutionCoordinatorService`。模型 Key 管理已并入**模型池/提供商体系**（`RuntimeModelPoolService` 管理模型池与 Key 池），独立 `ModelPoolService`/`KeyPoolService` 空壳已物理删除。

---

## 12. 模型路由、模型池、提供商体系与成本控制

### 12.1 模型档位

档位码为 `model_tier_policy.tier_code`（内置 seed 与线上实例档位名可不同，见 07 文档 §24.2.1）。按语义分为五级：

| 档位码 | 适用任务 | 示例策略 |
| --- | --- | --- |
| `1`（经济型 / 低价） | 简单问答、改写、摘要、分类 | 默认优先使用 |
| `2`（标准型 / 均衡） | 中等复杂任务、普通工具调用 | 常规执行模型 |
| `3`（强力型 / 高价） | 复杂推理、规划、多 Agent 汇总、代码/研究 | 按需升级 |
| `4`（视觉型） | 图片理解 | 有图片输入或视觉任务时使用 |
| `5`（长上下文型） | 长文档任务 | 长上下文场景使用 |

### 12.1.1 模型池与提供商体系

后台需要统一模型池与提供商体系，否则多个 Agent 难以稳定流转。

> **现状说明**：模型 Key 管理已并入模型池/提供商体系。独立空壳 `ModelPoolService` / `KeyPoolService` 已删除；真实实体为 `ModelPoolConfig` / `ModelKeyConfig` / `ModelTierPolicy`（`internal/model/model_pool_entity.py`）+ `ModelProviderConfig`（`model_provider_entity.py`），运行服务为 `RuntimeModelPoolService`（`internal/service/runtime_model_pool_service.py`），提供按档位/类型选择模型、按模型轮询 Key、Key 失败熔断计数等能力。Admin 侧由 `admin_model_pool_service.py` / `admin_model_provider_service.py` 管理。

模型池管理：

- 供应商（provider）。
- 模型名称。
- 模型档位（tier）。
- 模型类型（model_type，含上下文无关/长上下文等分类）。
- 支持模态。
- 上下文长度。
- 输入 / 输出价格。
- 速率限制。
- 健康状态。
- 优先级与默认 fallback。

> **模型类型（`model_type`）白名单**：以 `ModelType` 枚举（`internal/core/language_model/entities/model_entity.py`）为唯一事实源，当前为 `chat` / `embedding` / `multimodal` / `image_generation` / `video_generation` / `ocr` / `tts` / `asr` / `rerank` / `visual_embedding`。该枚举在后端有两份白名单副本（`admin_model_pool_schema.MODEL_TYPES`、`admin_model_provider_schema.MODEL_TYPES`），必须与枚举保持一致；`test_model_type_parity.py` 断言三者相等以防新增类型时漏改。`visual_embedding`（视觉编码，用于知识库关键帧以图搜图）与 `embedding` 同属「嵌入类」：创建/更新时都会触发 `_auto_probe_dimension` 维度探测（`_EMBEDDING_MODEL_DIMENSIONS` 兜底）；它同时属于 `CONTEXT_LESS_MODEL_TYPES`（无上下文窗口，token 上限强制 0）。该类型刻意**不注册进** langchain `model_class_registry`，其 REST 入参与 `OpenAIEmbeddings` 不兼容。

Key 池管理（并入模型池体系，`ModelKeyConfig`）：

- 供应商 Key。
- Key 归属模型或供应商（`model_id` 为空时归属 provider）。
- 可用额度。
- 并发限制。
- 失败次数。
- 熔断状态。
- 轮询和权重（按优先级/权重轮询选取，`select_key`）。
- 到期时间。

运行时模型选择链路：`ModelGatewayService`（`internal/service/model_gateway_service.py`）依据编排决策（`RoutingDecision`）与上下文解析模型档位；`RuntimeModelPoolService.select_model_with_fallback` 在模型池内按 tier + 成本参考 + 优先级选取并支持 fallback；`RuntimeModelPoolService.select_key` 为选定模型选取可用 Key 并维护失败计数。管理员可为每个 Agent 配置底座模型，也可以选择"跟随系统策略"。系统策略负责在 Key 不可用、限流、余额不足或模型故障时自动切换。

#### 12.1.1.1 运行时模型故障转移（实例层，断点续传-模型层）

> **现状说明（同步于可靠性改造）**：实例层故障转移统一由 `RuntimeFallbackLanguageModelProxy`（`internal/service/language_model_service.py`）承载。所有入口的 LLM（单 Agent、多 Agent 子任务、direct_answer、编排决策/直答、工作流 LLM 节点、首页助手定时任务）均由 `resolve_runtime_language_model` / `load_language_model` 解析并套代理，因此下述能力对全部 LLM 调用生效，无需各调用方自行处理。

故障转移顺序（生产级语义）：

1. **当前模型/Key 重连**：单次调用失败（可重试错误：5xx / 429 / 超时 / 连接错误）时，在当前模型 + Key 上重连 `RUNTIME_FALLBACK_RETRY_ATTEMPTS` 次（默认 **5**），仍失败才进入下一步。
2. **同档位、同类型候选轮换**：通过候选加载器从模型池解析「同档位（tier）+ 同类型（chat）」的候选模型（复用 `RuntimeModelPoolService.select_model_with_fallback` 的 priority + 成本排序，最多 3 个，自动排除当前 provider+model），逐一实例化并尝试。每个候选自身也是 `RuntimeFallbackLanguageModelProxy`，具备同等的「重连 → 再换候选 → 默认兜底」能力。
3. **默认模型兜底**：候选耗尽或模型池不可用时，回退 `load_default_language_model` 的默认模型。

**同 provider 优先（缓存保持）**：候选 loader 内按「是否与当前模型同 provider」稳定分组排序（`chain.sort(key=同provider)`），组内保留原有 priority+成本相对序。故障转移先换同一提供商的其他型号（如 DeepSeek → DeepSeek 另一型号），尽量贴近原 provider 的上下文缓存命名空间——同 provider 的自动缓存（DeepSeek/OpenAI 兼容网关按前缀命中）可在续跑时继续命中；同 provider 全部失败后才轮到跨 provider 候选（跨 provider 换模型缓存命名空间必然变化，命中丢失无可避免）。

关键语义与保护：

- **流式中断保护**：流式调用一旦已产出 chunk 后失败（用户已看到部分输出），**不再切换模型重发**（避免重复计费与重复推送），直接中断并抛出错误；仅在完全未产出任何 chunk 时切换模型。
- **图片输入保护**：含图片输入时 `_contains_image_input` 判定后不切换（避免把多模态请求打到不支持视觉的候选）。
- **非可重试错误直抛**：400 / 401 / 权限拒绝等 `_NON_RETRYABLE` 错误不重试、不切换，直接抛出。
- **可配置开关**：候选轮换默认开启，可用 `RUNTIME_FALLBACK_ENABLE_POOL_CANDIDATES=0` 关闭（退化为单跳默认模型的原行为）；重连次数可用 `RUNTIME_FALLBACK_RETRY_ATTEMPTS` 调整。

**缓存命中与计费（v2）**：同模型重试/续跑时，LLM 输入前缀不变（重试原样透传 args、不重放），provider 自动缓存可命中。Agent 主链路 token 统计已从「tiktoken 估算」升级为「优先读取 LLM 返回的真实 usage（含 `prompt_cache_hit_tokens` / `cached_tokens`）」：`_calculate_usage` 提取真实 cached 后，`AgentThought.cached_token_count` → `AgentTaskExecutor.metadata.token_usage.cached_input_tokens` → executor billing delta → `billing_aggregator.model_tokens` 透传，最终由 `PricingEngine.plan_usage` 在模型池行级 `cache_pricing_enabled=True` 时按 `input_cached_price_per_1k_tokens` 缓存价计费——缓存命中真实省钱。

> **说明**：这是「单次调用内自动恢复 + 上下文续跑」的模型层断点续传。上游 LLM API 端点故障时，用户侧无感知，Agent 编排不会因单次模型 5xx 中断。

#### 12.1.1.2 进程级 checkpoint（LangGraph Redis 断点续传）

> **现状说明（同步于可靠性改造）**：进程级 checkpoint 由 LangGraph `checkpointer` + Redis 承载，把 Agent 图的**节点边界状态**持久化到 Redis。worker/进程崩溃后，以同一 `thread_id` 重新执行即可从最后稳定 checkpoint 继续（pending 节点续跑），已执行完的工具轮/LLM 轮不重放。

关键组件：

- **LoopAwareAsyncRedisSaver（checkpointer 工厂）**：`internal/core/agent/checkpointer.py` 提供 `get_async_checkpointer()` / `get_sync_checkpointer()`（等价，统一走 AsyncRedisSaver）。`LoopAwareAsyncRedisSaver` **继承** `langgraph.checkpoint.redis.aio.AsyncRedisSaver`（天然是 BaseCheckpointSaver，可通过 `graph.compile` 类型校验），并在每次 checkpoint 读写前检测当前事件循环：若与上次绑定的 loop 不同（base_agent 同步链路每请求在子线程内 `asyncio.run` 新建事件循环），先断开旧连接池再 `asetup()` 重建——解决 AsyncRedisSaver 跨事件循环复用的 "Event loop is closed" 问题（已用真实 Redis 8 验证崩溃后续跑）。同步 `get_tuple`（供 `has_pending_checkpoint`）内部用独立 `asyncio.run` 查询。Redis 不可用 / 缺 RediSearch 模块时返回 None，编译退化为无 checkpoint（Agent 照常执行）。
- **编译挂载**：`FunctionCallAgent` / `DeepThinkingAgent` 的 `_build_agent` 在 `enable_checkpoint=True` 时 `graph.compile(checkpointer=get_async_checkpointer())`。
- **稳定 thread_id**：`AgentConfig` 新增 `checkpoint_thread_id` 字段。`base_agent._resolve_checkpoint_config` 优先级：调用方显式 config > `agent_config.checkpoint_thread_id` > 随机。稳定 thread_id（如会话维度 `conv:{conversation_id}`）是崩溃后定位 checkpoint 线程的关键。
- **续跑检测与入口**：`BaseAgent.has_pending_checkpoint()` 检查该 thread 的 checkpoint 是否存在 `pending_writes`（崩溃/异常中断的标记）；`BaseAgent.resume()` 以 `ainvoke(None)` 驱动 LangGraph 继续执行 pending 节点——不追加新输入，不重放已提交节点，事件流与 `stream` 一致。
- **会话链路透传**：`AssistantAgentService.chat(..., checkpoint_thread_id="")` 支持显式启用；环境变量 `AGENT_CHECKPOINT_BY_CONVERSATION=1` 开启时默认以会话维度（`conv:{conversation_id}`）启用。**Docker 生产已默认开启**（compose environment 固化）；本地/其他部署默认关闭（不产生额外 Redis checkpoint 写入）。

恢复语义与边界：

- checkpoint 在图节点**完成后**保存。进程在单步执行中途（如 LLM 流式中）崩溃，最后一步未写入，只能从上一个稳定 checkpoint 恢复——意味着崩溃点所在步骤会重放一次（该步若含不可幂等工具副作用，存在重复风险，需配合工具确认机制与编排层"无副作用才自动重放"策略）。
- 多智能体路径（每个子任务独立 agent）暂不启用（thread_id 冲突），checkpoint 能力限定 single_agent 主链路。

> **部署前提与启用状态**：进程级 checkpoint 依赖 Redis 的 **RediSearch（FT.\* 命令）与 RedisJSON（JSON.SET/GET，langgraph-checkpoint-redis 主写入路径）**。仓库 Docker 部署用 `redis:8-alpine`（容器内实测 Redis 8.8.0）。**注意**：Redis 8 的镜像自带 `rejson.so` / `redisearch.so` 等模块文件（`/usr/local/lib/redis/modules/`），但默认精简 `redis.conf` **不会加载**——必须在启动命令显式 `--loadmodule`，否则 langgraph checkpoint 初始化报 `unknown command 'JSON.SET'`（RediSearch/ReJSON 缺失）。`docker/docker-compose.yaml` 的 `llmops-redis` 已把 `rejson.so` + `redisearch.so` 两个 `--loadmodule` 固化进启动 command（2026-09 生产实测：加载后 `asetup` 建索引、checkpoint 写入/读取均通过）。启用方式：`docker/docker-compose.yaml` 的 `llmops-api` / `llmops-celery` 已在 `environment` 固化 `AGENT_CHECKPOINT_BY_CONVERSATION: '1'`（environment 优先于 env_file，即使 `api/.env` 丢失或未配置该键也能稳定生效）。未部署模块或显式关闭时功能自动降级，不影响既有执行。

#### 12.1.1.3 工具执行登记表（崩溃恢复不重复副作用）

> **现状说明（同步于可靠性改造）**：工具执行登记表（`internal/core/agent/tool_execution_registry.py`）解决 checkpoint 恢复时「tools_node 重放导致已执行工具被再次调用」的副作用重复问题。LangGraph checkpoint 在节点**完成后**保存，进程在 `tools_node` 内部执行工具时崩溃（副作用已发生但节点未完成），恢复后 tools_node 会被重放——若不做防护，已执行的工具会再次被调用。

登记语义（命名空间 = 稳定 thread_id，跨崩溃稳定）：

| 登记状态 | 含义 | 恢复时 tools_node 行为 |
| --- | --- | --- |
| `done`（含结果） | 工具崩溃前已执行完 | **不重放执行**，直接重放登记的结果（ToolMessage 用登记结果构造） |
| `running` | 工具已发起但结果未知（崩溃残留） | **不盲目执行**；把状态标记 `unknown`，构造「结果未知，请先核实再决策」的 ToolMessage，由 LLM 用只读/核实工具确认实际结果后决定：已生效则继续、未生效再重试 |
| 无记录 | 未执行过 | 正常执行：先登记 `running`，执行成功登记 `done + 结果` |

实现要点：

- `tools_node`（`function_call_agent.py`）在每个 tool_call 处理开头查询登记表（`_lookup_registered_tool_result` / `_is_crash_interrupted_tool`），命中后跳过授权/确认/执行全流程直接产出 ToolMessage 并 `continue`。
- 工具真正 `invoke` 前 `mark_running`，成功后 `mark_done`（best-effort，Redis 异常不阻断执行）。
- 仅在启用进程级 checkpoint（`enable_checkpoint` + `checkpoint_thread_id`）时生效；登记表 key 带 24h TTL 自动过期，崩溃场景保留供恢复、正常场景自动清理。

> **协作链路**：登记表让「崩溃点重放的 tools_node」变为**安全幂等**——已完成的工具不重跑、结果保留；结果未知的工具交还给 LLM 核实决策（而不是假设失败盲目重试，也不是静默跳过），在安全与交互体验间取得平衡。

### 12.2 复杂度判断

> **v5.2 变更（现状修正）**：`ENABLE_CONDUCTOR` 开启时，复杂度判断由指挥官 `ConductorService` 单次 LLM `structured_output` 输出的 `ConductorPlan.complexity` 字段承载；但 **`TaskClassifierService` 并未被删除**——它仍是旧规则回落链路与关键词快路径的活跃实现（`orchestrator_service.py` 调用，见 [task_classifier_service.py](../../api/internal/service/task_classifier_service.py)），其 LLM 分支使用 `get_feature_model("task_classification")`。下表规则同样作为指挥官 prompt 的参考规则。

`simple / medium / complex` 初始规则不是给用户看的产品概念，而是给指挥官使用的调度规则。它决定：

- 用哪个模型档位。
- 是否进入 Agent 子池。
- 是否需要工具子集。
- 是否允许多 Agent。
- 是否开启深度思考。
- 单次最多挂载多少工具。
- 最终如何计费和记录成本。

推荐初始规则（已融入指挥官 prompt）：

| 复杂度 | 判断信号 | 默认执行 |
| --- | --- | --- |
| simple | 单轮问答、常识解释、轻量改写、无需外部工具、无需多步骤推理 | 经济档模型 direct_answer |
| medium | 明确垂直任务、需要一个 Agent、需要少量工具、需要读取资料或生成结构化内容 | 标准档（`2`）模型 single_agent 或 single_agent_with_tools |
| complex | 多目标、多领域、多文件、长上下文、需要规划、需要多个 Agent、需要质量校验 | 强力档（`3`）模型 deep_thinking 或 multi_agent |

补充判断规则（已融入指挥官 prompt）：

| 信号 | 复杂度影响 |
| --- | --- |
| 用户上传图片 | 至少需要 vision 能力，不必然 complex |
| 用户上传长文档 | 可能升级到 long_context 或 medium/complex |
| 任务涉及两个以上领域 | 倾向 multi_agent，复杂度至少 medium |
| 需要写代码并解释方案 | 倾向 complex |
| 需要外部工具查询 | 至少 medium |
| 需要修改生产数据或外部发送 | 风险升级，不等同于复杂度升级 |
| 用户显式要求深度思考 | 可开启 deep_thinking，并按实际 token 计费 |

指挥官输出（取代原 TaskClassifier 输出）：

```json
{
  "execution_mode": "single_agent",
  "intent": "analysis",
  "complexity": "medium",
  "reason": "用户需要数据分析，单个 Agent 即可完成",
  "agents": [
    {
      "task_id": "t1",
      "title": "数据分析",
      "description": "...",
      "agent_pool": "data",
      "required_capabilities": ["data_analysis"],
      "model_tier": "2",
      "depends_on": [],
      "risk_level": "safe"
    }
  ]
}
```

### 12.3 成本策略

CostPolicyService 负责：

- 根据用户会员、token 余额或积分余额判断是否可执行。
- 控制强模型使用条件。
- 控制多 Agent 最大数量。
- 控制工具最大调用次数。
- 失败时决定是否升级模型。
- 预算不足时降级或提示用户。
- 将内部成本明细聚合成用户侧统一扣费。

现阶段允许普通用户开启 deep thinking，不设置系统侧固定预算上限，因为用户通过会员和 token / 积分承担成本。后续可以按套餐、会员等级、企业策略或后台权限再增加不同上限。

成本展示需要分两层：

| 层级 | 展示方式 |
| --- | --- |
| 管理员后台 | 按用户、Agent、工具、模型、Key、供应商、时间拆分统计 |
| 普通用户 | 聚合成一次请求消耗的积分 / token，不暴露内部 Agent 和工具成本细节 |

### 12.3.1 实时计费与手动终止

长任务、deep thinking、多 Agent 和多工具调用必须支持执行中实时计费。用户不应等任务完全结束后才知道成本，而应在执行过程中持续看到当前已经发生的消耗，并可以手动终止止损。第一阶段只展示已发生消耗，不展示预估最终成本，避免预估不准造成误导。

实时计费目标：

1. 用户能看到当前任务已消耗的积分 / token。
2. 用户能看到大致成本来源，例如模型推理、工具调用、deep thinking、多 Agent 执行。
3. 用户可以在前端点击“停止任务”终止后续执行。
4. 系统只扣除已实际发生的成本，不扣未执行部分。
5. 终止后仍返回已完成的部分结果、执行摘要和已扣费明细。

推荐执行链路：

```text
ExecutionCoordinator
  -> ModelGateway / ToolInvoker / A2AClient 持续上报 usage_delta
  -> BillingMetering 汇总增量成本
  -> SSE 推送 billing_delta / billing_summary
  -> 用户可触发 cancel_request
  -> ExecutionCoordinator 停止未开始子任务并尝试中断可中断任务
  -> ResultSynthesizer 汇总已完成结果
```

统一计费事件：

| 事件 | 触发时机 | 用途 |
| --- | --- | --- |
| billing_started | 任务开始执行时 | 初始化前端计费状态 |
| billing_delta | 每次模型、工具、Agent、A2A 产生增量消耗时 | 增量更新当前已发生消耗 |
| billing_summary | 阶段完成或关键节点完成时 | 展示当前阶段累计消耗 |
| billing_cancelled | 用户手动终止时 | 告知任务停止和最终已发生成本 |
| billing_final | 任务正常结束时 | 展示最终已发生成本 |

`billing_delta` 建议结构：

```json
{
  "event": "billing_delta",
  "request_id": "req_xxx",
  "conversation_id": "conv_xxx",
  "source_type": "model",
  "source_id": "agent-frontend",
  "stage": "frontend_implementation",
  "delta_tokens": 320,
  "delta_credits": 12,
  "total_tokens": 1840,
  "total_credits": 68,
  "display_text": "当前已消耗 68 积分",
  "created_at": 1710000000
}
```

用户侧统一计费 UI：

| UI 元素 | 说明 |
| --- | --- |
| 当前已消耗 | 固定展示当前已发生积分 / token |
| 当前执行阶段 | 正在思考、正在调用工具、正在等待 Agent、正在汇总 |
| 成本来源简述 | 模型推理、工具调用、Agent 协作、deep thinking |
| 停止按钮 | 用户可随时终止后续执行 |
| 终止后摘要 | 展示已完成内容、已发生成本和未执行阶段 |
| 不展示内容 | 第一阶段不展示预估最终成本 |

UI 展示原则：

1. 只展示当前已发生消耗，不预测最终成本。
2. 所有消耗增量必须来自统一 `billing_delta`，前端不自行估算。
3. 停止按钮在任务运行期间常驻可见。
4. 用户停止后，UI 切换为“已停止”，并展示最终已发生消耗。
5. 高风险工具确认 UI 中也应嵌入当前已消耗，保持成本认知一致。

终止策略：

| 状态 | 处理方式 |
| --- | --- |
| 未开始的 Agent 子任务 | 直接取消，不计费 |
| 正在流式推理的模型 | 尽量中断，按已生成 token 或供应商账单计费 |
| 正在执行的工具 | 如果工具支持取消则取消；不支持则等待返回并标记为用户终止期间完成 |
| 已完成的工具 / Agent | 保留结果并计费 |
| 已进入外部系统写操作 | 不强制中断，必须记录审计并提示用户可能已生效 |

### 12.4 模型升级策略

推荐顺序：

```text
1 -> 2 -> 3
```

升级条件：

- 分类不确定。
- 用户明确要求高质量。
- 任务高复杂度。
- 低档位（`1`/`2`）执行失败。
- 结果校验未通过。



## 13. 编排执行：Conductor + ExecutionCoordinatorService

> **现状说明（取代原 v5.2 注记）**：原 Orchestrator 多模块串行（TaskClassifier → TaskPlanner → PoolIntentResolver → ExecutionModeSelector）已被 ConductorService 替代。现状链路为：
> - 编排决策：`ENABLE_CONDUCTOR` 开启时，`assistant_agent_service.py` / `orchestrator_service.py` 委托 **ConductorService.plan()** 单次 LLM `structured_output` 输出 `ConductorPlan`；OrchestratorService 在 Conductor 决策异常时回退旧规则链路（`orchestrator_service.py` 日志"Conductor 决策失败，回退旧 Orchestrator"）。
> - 执行编排：`ConductorPlan` 经 `to_task_plan()` 转为 `TaskPlan`，由 **ExecutionCoordinatorService** 按并行/波次/串行分派执行；执行失败经 `repair_plan()` 修复（`_build_plan_repairer`，见 `assistant_agent_service.py`）。
> - 执行器真实现分部：`internal/service/executors/` 下为 `single_agent_executor.py` / `multi_agent_executor.py` / `direct_answer_executor.py`；`AgentTaskExecutor`（`agent_task_executor.py`）位于 `internal/service/` 根目录（不在 `executors/`），负责具体子任务执行，并在 `_resolve_query` 中把上游子任务结果（`upstream_results`）拼进 query。
> - DAGEngine 时代遗留（`dag_entity` / `dag_engine_service` / `agent_instance_pool` / `test_dag_engine`）已于 2026-08-26 删除，统一为 `TaskPlan + ExecutionCoordinatorService`。

### 13.1 执行模式

编排决策层输出 `execution_mode`（Conductor 侧为 `ConductorPlan.execution_mode`；旧链路为 `RoutingDecision.execution_mode`）：

| 模式 | 说明 | 适用场景 | 计费方式 |
| --- | --- | --- | --- |
| direct_answer | 直接回答 | 简单问答 | 系统承担，不扣用户额度 |
| single_agent | 单 Agent 执行 | 明确垂直任务 | 用户承担 |
| single_agent_with_tools | 单 Agent + 工具 | 需要查询/操作 | 用户承担 |
| multi_agent_parallel | 多 Agent 并行 | 多角度分析 | 用户承担 |
| multi_agent_sequential | 多 Agent 串行 | 前后依赖任务 | 用户承担 |
| deep_thinking | 深度思考执行 | 复杂产物、长任务 | 用户承担 |
| reject_or_confirm | 拒绝或请求确认 | 高风险任务 | 不计费 |

> **深度思考的触发权（2026-09 同步）**：深度思考**只由入口指挥官决策**，用户不再有手动开关。
> - `assistant_agent_service.chat()` 调用 `orchestrator.decide()` 时固定传 `enable_deep_thinking=False`——用户请求体里的 `confirm_deep_thinking`（旧前端/旧开关遗留）不再作为输入，也不能强制/绕过指挥官决策。
> - 执行判定 `should_deep_think = (execution_mode == "deep_thinking")`：仅当指挥官（传统规则路径的 `TaskClassifier` 命中深度思考关键词/意图，受 `ENABLE_AUTO_DEEP_THINKING` 开关约束；或 Conductor 决策后由 orchestrator 的关键词增强升级）判定为 `deep_thinking` 才执行。
> - 原「deep_thinking_proposal 二阶段确认」不再下发（`_stream_deep_thinking_proposal` 不再被 chat 调用）——指挥官判定后直接自动执行，避免用户在开/关之间误操作（开了不关会让简单问题也走深度思考烧钱）。
> - 前端已彻底删除深度思考手动开关（2026-09）：`ChatComposer` 的 `showDeepThinkingToggle`/`deepThinkingEnabled` props 与灯泡按钮 UI 已移除，HomeView/WebApp 预览/应用调试等所有聊天入口不再暴露 toggle，也不向请求体传 `confirm_deep_thinking`（web-app/assistant-agent/app 调试的 model、service、hook 均已清理该字段）；前端仅保留对指挥官决策后的 `deep_thinking` 过程事件做展示。
> - Conductor（LLM 指挥官）本身不输出 `deep_thinking` 模式，orchestrator 在 conductor 决策后对其 single/multi agent 类结果做**关键词层深度思考增强**（复用 `TaskClassifier._classify_with_keywords`，零 LLM 成本），命中且 `ENABLE_AUTO_DEEP_THINKING` 开启时升级为 `deep_thinking`。

> **SSE 长任务活性保障（2026-09 修复）**：`support.py` 的 `_sse_response` 心跳帧（`: keep-alive`）现在同步刷新 `last_activity`——历史缺陷：Agent 图单节点（如 deep_agent 内部长 LLM 调用）单帧耗时超过原 `SSE_ACTIVITY_TIMEOUT`（60s）会被误判"生成器失活"掐断整条 SSE 流，导致深度思考最终长文丢失。现改为单帧上限 `SSE_MAX_FRAME_SECONDS`（默认 1800s，仅兜底线程死锁）。同时 `conversation_service.save_agent_thoughts` 修复两个落库缺陷：(a) message 已被删除/查询为 None 时安全早退（不再 AttributeError 拖垮整条持久化链）；(b) 分块流式/空 answer 的 token 统计 AGENT_MESSAGE 事件不再逐条覆盖 `message.answer`——仅当 answer 尚未写入时用事件内容兜底，保证外层聚合的完整长文正确落库。

### 13.2 快速路径（direct_answer）

指挥官判定为简单问题时，直接在 `ConductorPlan.direct_answer` 字段中给出完整回复，不经 Agent 执行：

```text
用户请求 -> 指挥官 LLM（direct_answer）-> BillingUsageAggregator -> SSE 直接返回
```

不进入 Agent 池和工具池。指挥官 LLM 成本由系统承担，不扣用户额度，避免双重计费。

### 13.3 复杂路径

指挥官判定需要 Agent 时，输出 `agents[]` 子任务列表，`to_task_plan()` 转为 `TaskPlan` 后进入：

```text
ConductorService.plan
  -> ConductorPlanValidator.validate（失败回退 single_agent）
  -> ExecutionCoordinatorService.execute(plan)
      -> 按 TaskPlan 执行模式分派
          -> AgentCandidateCollector（Agent 池候选收集，见 01 模块 8.2）
          -> ToolCandidateCollector / RuntimeToolMountService（工具候选与挂载，见 01 模块 8.4/10.5）
          -> AgentTaskExecutor（子任务执行，上游结果拼接进 query）
          -> 失败子任务 -> ConductorService.repair_plan 修复（可选，经 plan_repairer 注入）
  -> ResultSynthesizer 汇总
```

**执行失败与修复**：`ExecutionCoordinatorService.execute()` 支持：
- `resume=True` 时读取子任务快照（`subtask_registry.snapshot(request_id)`，由 `SubtaskRegistryService` 注册计划），跳过已完成子任务、标记 `resumed:completed` / `resumed:failed`。
- 注入的 `plan_repairer`（`Callable[[str, list[dict]], TaskPlan | None]`）在存在失败子任务时基于失败信息调用 `ConductorService.repair_plan`（把失败反馈拼入 query 重新 `plan()`），再以 `_run_plan` 重跑修复后的计划；修复器返回空则保留原结果。
- 升级/降级策略由 `cost_policy_service.EscalationPolicyService` 承担（读取 `billing_config` 的 `escalation_enabled`，经 `resolve_escalation_policy_service()` 注入）。

**子任务上下文**：`ExecutionCoordinatorService._build_upstream_context` 为每个子任务构建上游结果上下文；`AgentTaskExecutor._resolve_query` 在存在 `upstream_results` 时，将上游子任务输出拼接到 `item.description`（或原始 query）之后，实现串行链路的信息传递。

#### 13.3.1 定时任务执行可靠性（长任务治理）

> **现状说明（同步于可靠性改造）**：首页助手/应用的定时任务（ScheduleTask）由 Celery 驱动：`internal.task.schedule_tasks.run_scheduled_tasks`（celery-beat 每分钟扫描）与 `schedule_task_execute`（真正执行，独立任务）解耦；`ScheduleExecutionService.execute_task`（`internal/service/schedule_execution_service.py`）以任务归属用户身份走完整编排链。

可靠性机制（全部已落地）：

| 机制 | 实现 | 说明 |
| --- | --- | --- |
| 扫描/执行解耦 | `run_scheduled_tasks` 只扫描+`advance_next_run`+`.delay()` 投递，立即返回 | 长任务（数小时/跨天）不阻塞每分钟扫描 tick |
| 无硬超时 | `_run_assistant_chat` 直接同步迭代 chat 生成器直至自然完成 | 移除旧 90s daemon 线程超时（该机制会误杀长任务且线程空转） |
| 每用户并发上限 | `_account_under_concurrency_limit` 统计该账号 running 且 6h 窗口内的 run 数，上限 `_MAX_CONCURRENT_RUNS_PER_ACCOUNT=10` | 非 Celery 全局计数（后者会误伤其他用户长任务）；僵尸 running 不计额度 |
| Redis 执行锁（token 化） | `SET NX EX` 带随机 token，TTL 8h | 防同一任务重入；释放用 Lua 脚本按 token 比对（防误删他人锁） |
| 锁续租 watchdog | `execute_task` 内 daemon 线程每 60s `expire` 重置 TTL | 真实长任务超 8h 锁不过期，不会被下个 tick 重入 |
| 僵尸清理周期任务 | `cleanup_stale_runs`（celery-beat 每 15 分钟）把超过 8h（`SCHEDULE_STALE_RUN_HOURS` 可配）仍 running 的 run 标记 failed | 回收 worker 崩溃/重启留下的僵尸记录，避免永久占用并发额度 |
| acks_late + reject_on_worker_lost | `schedule_task_execute` 装饰器开启 | worker 执行中途崩溃时 broker 重新投递；`execute_task` 幂等（Redis 锁），不会并行。配套 `broker_transport_options.visibility_timeout=86400`（`CELERY_BROKER_VISIBILITY_TIMEOUT`），防止正常长任务超 1h 被 broker 误重投 |
| 连续失败自动停用 | `_maybe_disable_after_consecutive_failures`：最近连续 5 次 run 全 failed → `enabled=False, status=paused` | 避免任务永久失败烧资源 |
| 进程级 checkpoint（可选） | LangGraph 同步 RedisSaver + `checkpoint_thread_id`（`AGENT_CHECKPOINT_BY_CONVERSATION=1` / 显式传入开启） | 进程崩溃后同会话重发从节点边界续跑；需 Redis 带 RediSearch 模块，默认关闭 |

#### 13.3.2 单次任务（trigger_type=once）

> **现状说明**：定时任务支持三种触发类型 `trigger_type`：`cron`（6 段秒级表达式）、`interval`（间隔对齐）、`once`（单次执行）。`once` 面向「用户在对话中提出的临时诉求」——例如「下午三点帮我把 XX 文档整理一遍」——Agent 在意图解析阶段识别为一次性诉求后自动创建，到点执行一次即完成交付。

**语义与实现**：

| 环节 | 实现 | 说明 |
| --- | --- | --- |
| 字段 | `schedule_task.run_at`（`DateTime`，UTC naive），迁移 `o9d0e1f2a3b4` | 单次任务的绝对执行时刻；`cron`/`interval` 任务该列为 NULL |
| 意图识别 | `ScheduleIntentParser` 输出 `trigger_type` + `run_at`（ISO8601 或秒级时间戳） | 提示词 `schedule_intent_parser_prompt`（`system_prompts.yaml`）判定一次性 vs 重复诉求；裸时间按业务时区（Asia/Shanghai）解释后转 UTC |
| 创建校验 | `ScheduleTaskService.validate_once_run_at` / `describe_once` | 未提供或非法时刻报「单次任务需要指定合法的执行时间」；早于当前时间（60s 容差）报「执行时间不能早于当前时间」；`cron_expression` 置空，`next_run_at = run_at` |
| 扫描后不重跑 | `advance_next_run`：单次任务清空 `next_run_at`（保持 `enabled=True`） | `scan_due_tasks` 要求 `next_run_at` 非空，清空即阻止下个 tick 重复扫描；保持 enabled 是为了让 `schedule_task_execute` 不命中「已停用」分支而跳过本次执行 |
| 执行后自动归档 | `ScheduleExecutionService._archive_once_task`（`_finish_run` 末尾调用） | 无论成功或失败，执行结束即经 `RecycleBinService.delete_resource` 入回收站；快照含任务与全部运行记录；留存期跟随系统默认（30 天），期间用户/admin 可在回收站恢复 |
| 归档失败降级 | `_archive_once_task` 捕获全部异常仅记日志 | 归档失败不影响主流程，任务保留在主列表供用户手动删除 |
| 恢复后不重复执行 | 归档时 `next_run_at` 已清空并写入快照，恢复后该列为 NULL | 恢复的语义是「找回记录/结果」而非「重跑」；如需重跑，用户可显式点「立即执行」 |

**触发类型对照**：

| trigger_type | 时间字段 | 执行次数 | 执行后 |
| --- | --- | --- | --- |
| `cron` | `cron_expression` | 按表达式周期 | 保留，`next_run_at` 推进 |
| `interval` | `interval_config` | 按间隔周期 | 保留，`next_run_at` 推进 |
| `once` | `run_at` | 仅 1 次 | 自动进入回收站 |

**接口**：用户端 `POST /schedule-tasks`、`POST /schedule-tasks/confirm`、`PUT /schedule-tasks/<id>` 与 admin 端 `/admin/schedule-tasks*` 均已支持 `trigger_type=once` + `run_at`；`GET /schedule-tasks*` 响应新增 `run_at` 字段。前端用户端与 admin 端共用同一套向导组件（`CreateScheduleWizard.vue`）与建议卡片（`ScheduleSuggestionCard.vue`），均提供「单次任务」触发类型与日期时间选择器。

**中断场景行为**：

- Agent 执行抛业务异常（LLM/工具失败冒泡）→ run 落 `failed` + error_message，ws 通知用户；连续失败 5 次自动停用；失败重跑靠下个 cron tick（next_run 已推进）。
- worker 崩溃/被 kill → acks_late 让 broker 重投；Redis 锁 8h TTL 独立兜底防重入；僵尸 run 由 15 分钟周期任务标记 failed。
- LLM API 端点故障/5xx → 实例层 `RuntimeFallbackLanguageModelProxy` 重连 5 次 → 同档候选轮换 → 默认模型兜底（见 §12.1.1.1），对定时任务同样生效，任务不中断。
- **编排层安全续跑（AgentTaskExecutor）**：Agent 执行中出现 ERROR/TIMEOUT/STOP 终态失败事件（metadata.terminal_failure）且**未调用任何工具**（tool_calls 为空，无副作用）时，`AgentTaskExecutor.execute` 用同一份完整上下文（history + query + 记忆，`state["messages"]` 累积含全部历史）自动续跑一次——覆盖「LLM 调用在模型池全部故障后短暂恢复」等 proxy 耗尽候选的极端场景。一旦执行中已调用过工具（存在副作用）则不续跑，避免副作用重复执行。
- **进程崩溃（worker 被杀/滚动更新）**：若启用进程级 checkpoint（见 §12.1.1.2），Redis 中的节点边界状态保留；恢复进程以同一 thread_id（会话维度）执行时，`has_pending_checkpoint()` 判定存在 pending 节点，`resume()` 从断点续跑（不重放已提交工具/LLM 轮）。未启用时，同会话重发请求会作为全新执行处理（消息追加、从头规划）。

### 13.4 硬约束校验与回退

指挥官输出后经 `ConductorPlanValidator.validate()` 校验，失败时回退 `single_agent` 模式：

| 约束 | 校验内容 |
| --- | --- |
| execution_mode 合法 | 必须是枚举值之一 |
| direct_answer 一致性 | direct_answer 模式下 agents 必须为空 |
| agent 数量限制 | ≤ MAX_AGENTS_PER_PLAN |
| model_tier 合法 | 必须是 1/2/3 之一 |
| 并行依赖约束 | multi_agent_parallel 模式下 depends_on 必须为空 |

### 13.5 Feature Flag 与编排切换

编排链路受 `orchestration_feature_flag_service` 控制（开关定义见 [architecture-design.md §22](../architecture-design.md#22-feature-flag-与回滚策略)）。与本节直接相关的开关：

| 开关 | 作用 |
| --- | --- |
| ENABLE_ORCHESTRATOR | 是否启用编排路由（默认开，关闭时直接回退 `direct_answer`） |
| ENABLE_CONDUCTOR | 是否启用 Conductor（LLM 指挥官）替代规则编排（默认关，fallback=orchestrator 旧链路） |
| ENABLE_MULTI_AGENT_EXECUTION | 是否允许多 Agent 规划（执行层按 TaskPlan 跑并行/串行子 Agent） |
| ENABLE_AUTO_DEEP_THINKING | 是否由 LLM 意图检测自动触发 deep thinking |
| ENABLE_RESULT_SYNTHESIZER | 任务计划明细开关（结果合成执行未接线，见实体描述） |

> 注：Feature Flag 的真实实体见 [orchestration_feature_flag_entity.py](../../../api/internal/entity/orchestration_feature_flag_entity.py)，共 14 个编排开关 + `list_flags` 附加的 3 个 `AUTH_*` 认证开关（`auth_switch_service.AUTH_CODES`），详见 [architecture-design.md §22](../architecture-design.md#22-feature-flag-与回滚策略)。

### 13.6 Orchestrator 旧链路的保留形态

`OrchestratorService` 仍保留为旧规则链路（`ENABLE_CONDUCTOR` 关闭时的默认路径），其 `decide()` 内部：先做 `task_classifier_service.classify()`（规则分类）→ 意图识别/成本策略/执行模式选择等规则决策；`ENABLE_CONDUCTOR` 开启时在分类前委托 `conductor_service.decide()` 输出 `RoutingDecision`，异常时回退到分类链路。`PoolIntentResolver`（`pool_intent_resolver_service.py`）不再位于主入口调度主链路，仅被 `home_service.py`（`/home` 意图摘要路径，`PoolIntentResolver().resolve(...)`）等轻量场景引用。

#### 13.6.1 `/home` 意图摘要的推荐产出（2026-09-13 修复）

首页意图摘要（`GET /home/intent`）此前只做真实 LLM 意图识别，但 **推荐字段为写死占位**：
`recommended_agents=[]`、`matched_tool_pools=["general"]`、`recommended_tools=[]`，且 `GetIntentResp`
schema 未声明这四个字段，导致即便后端产出也会被 marshmallow `dump()` **静默丢弃**。

现由 `HomeService._build_intent_recommendations(user, query, matched_agent_pools)` 复用编排主链路
已在用的候选收集器真实产出：

| 产物 | 来源 | 上限 |
|---|---|---|
| `recommended_agents` | `AgentCandidateCollector(session).collect_by_pools(account_id, matched_agent_pools, query)` 按子池 + query 语义打分排序 | `RECOMMENDED_AGENTS_LIMIT = 3` |
| `recommended_tools` | `ToolCandidateCollector(session).collect(account_id)` → `ToolSelectorService(language_model_service).select_tools(query, candidates, max_tools)`（关键词快通道 + LLM 兜底） | `RECOMMENDED_TOOLS_LIMIT = 5` |
| `matched_tool_pools` | 由被选中工具的 `metadata.tool_pool` 去重汇总；无产出时兜底 `["general"]` | — |

- `HomeService` 因此新增注入 `language_model_service: LanguageModelService`（工具选择器的 LLM 兜底需要）。
- 全流程 **fail-open**：Agent/工具任一收集环节异常都 `logging.warning` 后降级为空列表，首页摘要不因推荐失败而报错。
- 契约层：`GetIntentResp` 补全 `matched_agent_pools` / `matched_tool_pools` / `recommended_agents` / `recommended_tools` 四个字段（新增 `RecommendedAgentSchema` / `RecommendedToolSchema`）。
- 前端：首页渲染「推荐 Agent」「推荐工具」两个区块，点击推荐 Agent 直接以该 Agent 名发起对话。



## 14. ResultSynthesizer 设计

### 14.1 输入

```json
{
  "original_query": "...",
  "task_plan": [],
  "agent_results": [
    {
      "agent_id": "...",
      "answer": "...",
      "confidence": 0.8,
      "tool_calls": [],
      "warnings": [],
      "cost": {}
    }
  ],
  "errors": [],
  "cost_summary": {}
}
```

### 14.2 输出

```json
{
  "final_answer": "...",
  "summary": "...",
  "confidence": 0.82,
  "visible_sources": [],
  "user_warnings": [],
  "internal_notes": []
}
```

### 14.3 职责

- 合并多个 Agent 结果。
- 去重。
- 消除冲突。
- 标注不确定性。
- 统一格式。
- 面向用户重写。
- 隐藏内部配置细节。

即使不同 Agent 职责不同，仍可能出现冲突或重复，因此需要 ResultSynthesizer。

典型例子：

| 场景 | 可能问题 | 汇总策略 |
| --- | --- | --- |
| UI Agent 和前端 Agent 同时处理页面方案 | UI 建议动画很复杂，前端判断实现成本过高 | 标注取舍，生成可落地版本 |
| 数据 Agent 和研究 Agent 同时分析市场 | 一个用内部数据，一个用外部资料，结论不一致 | 标注数据来源和置信度 |
| 后端 Agent 和安全 Agent 评审接口 | 后端建议开放接口，安全 Agent 判断权限不足 | 以安全约束为硬边界 |
| 文档 Agent 和代码 Agent 生成交付物 | 文档描述的功能与代码实现细节不一致 | 统一术语和最终交付说明 |
| 多个工具返回相似资料 | 内容重复或来源冲突 | 去重、引用更可信来源 |

因此用户侧默认只展示主入口汇总后的最终结果，管理员后台可查看各 Agent 原始输出和合并过程。

### 14.4 与记忆系统的集成

ResultSynthesizer 在合成最终回答时，需要融合两类记忆上下文：

1. **Memory Digest 注入（System 1 路径）**：当 Orchestrator 判定为简单查询时，ResultSynthesizer 直接从 [第 16 章](#16-脑启发记忆系统v50-新增) 定义的 Memory Digest 获取用户画像、活跃技能和近期事件摘要，作为上下文注入 LLM prompt，无需触发完整检索。

2. **记忆检索结果融合（System 2 路径）**：当 Orchestrator 判定为复杂查询时，System 2 的 MemoryRetriever 返回记忆片段（带 tier/scope 标签），与 layered_search 返回的知识库片段（带 knowledge_scope 标签）在 ResultSynthesizer 中统一处理：
   - 知识库片段按 knowledge_scope 分类（system → 系统规则区，user_content → 用户资料区）
   - 记忆片段按 tier 和 memory_type 分类（preference → 用户偏好区，secret/event/project → 用户事实区）
   - SystemRulePriorityResolver 确保系统规则优先级高于用户偏好

3. **巩固引擎反馈**：ResultSynthesizer 合成的最终回答可作为巩固引擎的输入信号——回答中引用了哪些记忆片段，这些片段的访问次数+1，影响 HebbianDecay 的权重计算（复述强化因子）。



## 15. 可观测性与审计

### 15.1 必须记录的事件

| 事件 | 内容 |
| --- | --- |
| routing_started | 用户、query、conversation_id |
| task_classified | intent、complexity、needs_tools、model_tier |
| model_selected | 模型档位、模型名称、选择原因 |
| agent_candidates_found | 候选 Agent、评分、过滤原因 |
| agent_selected | 选中 Agent、原因 |
| tool_candidates_found | 候选工具、评分、过滤原因 |
| tool_selected | 选中工具、权限、风险等级 |
| tool_invoked | 输入摘要、耗时、状态 |
| agent_completed | 输出摘要、耗时、token、成本 |
| synthesis_started | 汇总开始 |
| synthesis_completed | 最终答案、置信度 |
| fallback_triggered | fallback 原因 |
| routing_failed | 错误类型和原因 |

### 15.2 管理员可见信息

管理员可以查看：

- 路由链路。
- 模型选择原因。
- Agent 子池命中情况。
- Agent 候选和选中原因。
- 工具子池命中情况。
- 工具候选和过滤原因。
- 成本明细。
- 用户侧扣费记录。
- 失败原因。
- fallback 记录。

普通用户只能看到简化进度和聚合后的扣费结果。

### 15.3 日志保留与脱敏策略

路由日志只暴露给管理员。日志保留周期应支持后台配置；如果第一阶段实现配置较复杂，默认保留一个月。

当前阶段暂不强制脱敏，但日志结构需要预留脱敏字段和策略开关，方便后续按合规要求启用。

### 15.4 观测中心聚合接口（2026-09 新增）

管理后台「观测中心」板块（路由日志 / 路由质量 / 审计日志 / 回收站 + 首页仪表盘）已翻新为「KPI 概览 + 时间序列 + 维度分布 + 高密度明细」结构。为此在既有分页列表接口之外，新增了 SQL 级全量聚合接口（均支持 `start_at/end_at` 秒级时间戳窗口，naive UTC）：

| 接口 | Service 方法 | 返回要点 |
| --- | --- | --- |
| `GET /admin/routing-logs/stats` | `RoutingLogService.stats_overview` | 窗口内全量 `total_count/success_count/fallback_count/success_rate/fallback_rate/total_credits/avg_latency_ms/agent_pool_hit_rate/tool_pool_hit_rate` + `by_status` 分布；可选 `status/invoke_from` 过滤 |
| `GET /admin/routing-logs/trend` | `RoutingLogService.trend` | `date_trunc(day\|hour)` 时间序列：`request_count/success_count/fallback_count/total_credits/avg_latency_ms` |
| `GET /admin/routing-logs/distribution` | `RoutingLogService.distribution` | 维度分布（`execution_mode/intent/model_tier/complexity/model/status/invoke_from`），JSONB `#>>` 取值、空值归一 `unknown`，含 `count/credits/avg_latency_ms/percentage` |
| `GET /admin/routing-quality/metrics` | `RoutingQualityMetricsService.build_metrics` | HTTP 层已接线 `start_at/end_at`（此前仅 service 层支持），整表内存聚合不变 |
| `GET /admin/audit-logs/overview` | `AuditLogService.overview` | `total` + `by_action/by_resource_type/trend(按日)/top_admins` 聚合 |
| `GET /admin/recycle-bin/overview` | `RecycleBinService.overview` | `total/pending_total` + `by_status/by_resource_type/by_deleted_by_type` 聚合 |
| `GET /space/recycle-bin/overview` | `RecycleBinService.user_overview` | 用户端回收站概览：过滤条件与 `list_user_items` 一致（按账号归属 + user/agent 来源 + 用户可见资源类型），同样返回 `total/pending_total` + 三组分布 |

关键语义：

- 与 `routing-logs` 列表接口的 `summary`（仅基于当前页 Python 聚合，`total_count` 除外）不同，`stats_overview` 是**SQL 全量聚合**，修复了首页仪表盘此前「最近 6 条窗口统计冒充全量指标」的误导问题。
- 成本键兼容 `cost_summary->>'estimated_credits'` 与旧键 `total_credits`（与 cost-stats 一致）。
- 时间戳统一为秒级；`_normalize_window` 同时接受秒级时间戳/字符串/`datetime` 输入并归一为 naive UTC。
- 审计与回收站 overview 沿用各表既有索引（`created_at`/`status`/`resource_type`），分布均为 Top N 截断（15/8 等），保证大表下查询可控。

#### 15.4.1 调优建议持久化与可操作闭环（2026-09 修复）

此前 `GET /admin/routing-quality/suggestions` 不带 `status` 时每次**实时生成、不落库、无 `id`**，而 `accept/dismiss/preview/apply` 全部要求 `suggestion_id` 并查库，导致管理端无法对建议做任何操作（数据库 `routing_optimization_suggestion` 恒为空）。本轮修复：

- `RoutingOptimizationSuggestionService` 新增 `sync_open_suggestions(metrics)`：按当前指标实时生成建议后**落库**（open 状态按 `suggestion_type+target_type+target_id` 指纹去重：已存在则刷新 reason/evidence，不存在则插入），返回带 `id` 的可操作建议。
- 无 `status` 的 `GET /suggestions` 改走 `sync_open_suggestions`；带 `status` 仍走 `list_suggestions` 查库。至此管理端「路由质量」板块与独立「调优建议管理」页（`/admin/routing-quality/suggestions`，已入观测中心侧边菜单）均可完整执行 采纳→预览→驳回→应用 闭环。
- 语义约束：`collect_more_feedback` 类建议无对应策略配置，前端不提供采纳/应用，仅可驳回；`review_model_cost/review_tool_health/review_fallback_rate` 提供完整操作。

#### 15.4.2 路由日志成本回填修复：`cost_summary.estimated_credits` 全 0（2026-09 修复）

管理端「路由日志」KPI / 列表的算力值此前恒为 0，根因在**写侧回填键错位**：`AssistantAgentService._update_routing_log_execution` 原先把 `message.total_token_count`（该字段在多数执行路径恒为 0）直接当作 `cost_summary.estimated_credits` 写入。真实扣费（按 message 结算）落在 `billing_reconciliation`（`task_id=message.id`，售价口径，由 billing aggregator `final()` 结算，幂等）。

本轮修复：

- **写侧**：`_update_routing_log_execution` 回填前先按 `BillingReconciliation.task_id == message.id` 查询真实结算 `estimated_credits`；无对账行时退化为 `total_token_count / 1000` 估算；同时写入 `actual_credits` 同值，不再把 token 数当作算力值。
- **读侧**（保持）：`routing_log_service._credits_sql_expr` 已按 `estimated_credits` → 旧键 `total_credits` 顺序读取，`stats_overview / trend / distribution / page.summary` 统一走该表达式，无需改动。
- **前端**：RoutingLogsView 明细/列表展示新增 `displayCost()` 兼容 `estimated_credits / actual_credits / total_credits / credits` 多键读取。
- **存量数据**：一次性 SQL 回填（`UPDATE routing_log SET cost_summary = jsonb_set(...) FROM billing_reconciliation`）把已有行中 `estimated_credits` 为 0 但存在对账行的记录修正为真实结算值。
- 文案统一：管理端全部「积分 / 总 credits」中文展示改为「算力值 / 总算力值」（i18n 字典 `ui/src/i18n/messages/<locale>/*.ts`，按板块模块化）。

#### 15.4.3 计费重复进位修复：同任务同模型调用合并后再 ceil（2026-09 修复）

**问题**：底层计费以「单次模型调用」为最小单元独立向上取整——`pricing_engine.plan_usage` 对每次调用 `math.ceil(金额×credits_per_yuan)`，`billing_aggregator.final()` 又对每条 usage event **逐条** `consume_for_feature`。一次任务内含多次模型调用（Agent 多轮/工具循环）时，每笔不足 1 算力的小调用都进位收 1，多次重复进位造成系统性多收。

**实测量化（NILL 账号，1,765 笔消费流水）**：按 desc token 逐笔 `ceil(token/1000)` 合计 **2,094**，按任务合并 token 后 `ceil` 合计 **1,373**——逐笔进位虚增约 **721 算力（约 34%）**。典型案例：「查北京天气」441,028 token 合并应收 442 算力、实际逐笔收 692（多 250）；每日 AI 头条 324,921 token 合并应收 325、实收 515（多 190）。

**修复**：
- `BillingUsageAggregator.final()`（`billing_metering_service.py`）：同任务扣费前先按 `model_id` 合并 usage_event 的 input/output/cached token，每组一次 `consume_for_feature`（一次 ceil）；幂等键改为 `{task_id}:{model_id}:merged`。
- `BillingReconciliationService.settle()`：结算重算同样先按 `model_id` 合并 token 再 `plan_usage`（一次 ceil），`diff = 合并后实际 - 逐条预扣` 为负时经 `adjust_credits` 自动退还多收（历史已 settle 行不自动重算）。
- 不变量：单任务内**不同模型**仍分开计价（各自合并）；`save_agent_thoughts` 的 `consume_for_message`（按整条消息汇总 token 单次扣费）本已是任务级合并，不受影响。

**回归测试**：`test_final_should_pass_feature_key_and_token_count_to_consume`（同任务两笔 750+750 token 合并为一次 1500 扣费）、`test_settle_merges_same_model_events_before_ceil`（两笔 400 token 合并 800 → ceil 1，diff=-1 退还）。

### 15.5 Agent 本机文件回收站（os_recycle_bin）修复记录（2026-09）

「Agent 删除本机文件 → 用户回收站恢复」链路在端到端测试中发现并修复两个缺陷：

1. **URL 拼接缺陷（`os_recycle_bin` 工具）**：`OsRecycleBinTool._call_worker` 在 `OS_AUTOMATION_URL` 分支未拼接 `/recycle` 路径，请求落到 worker 根路径返回 404 `not_found`，导致 Agent 删除本机文件失败（DESKTOP_BRIDGE_URL 分支因显式拼接 `/recycle` 正常）。修复为两分支统一在末尾拼接 `/recycle`（桥接分支 URL 已含则不再重复）。回归测试：`test_os_recycle_bin_appends_recycle_path_for_os_automation_url` / `test_os_recycle_bin_tolerates_trailing_slash_in_os_automation_url`。
2. **resource_name 跨平台缺陷（`RecycleBinService.record_os_file_deletion`）**：取文件名用 `os.sep` 分割，宿主机为 Windows 路径（`\`）而服务运行在 Linux 容器（`/`）时返回完整路径。修复为同时按 `\` 与 `/` 分割取末段。回归测试：`test_record_os_file_deletion_uses_basename_across_path_separators`。

端到端验证（NILL 账号，agent 来源 os_file）：删除 3 个测试文件 → 平台回收站记录（agent 来源、7 天留存、归属 NILL）→ 用户端列表可见 → 全部恢复成功、文件回到原位置、状态变 `restored`、overview 聚合正确。

### 15.6 审计日志资源名称展示（2026-09 新增）

管理端「观测中心 → 审计日志」此前只展示 `resource_id`（UUID / 内部标识），管理员看到「删除了个用户」却无从得知删的是谁，等价于没有信息。为让审计明细可读，`AuditLogService` 与 `AuditLogResp` 新增 `resource_name` 字段：

- **schema**：`AuditLogResp.resource_name`（`admin_audit_log_schema.py`），`AuditLog` 前端类型同步新增 `resource_name?: string`。
- **优先取快照**：`AuditLogService._extract_resource_name(before_data, after_data)` 按固定优先级扫描名称字段——`resource_name → name → username → display_name → title → tool_name → code → order_no → user_name → email → key`；先 `after_data` 再回退 `before_data`（删除类操作的名称只存在于变更前快照）。覆盖 `create/update/delete` 等把名称写入快照的操作（如 `customer_user` 删除 → 用户名 `t67545`）。
- **回源表兜底**：`disable/enable/set_status/revoke_sessions` 等**状态变更类操作**快照里只有状态字段，没有名称。此时 `AuditLogService._build_resource_name_map(audit_logs)` 按 `resource_type` 分组（`_RESOURCE_NAME_LOOKUPS` 登记了 30 个资源类型 → 模型/匹配列/名称列的映射），对缺失名称的记录批量各发一次 `IN` 查询回源表补全，避免 N+1；快照有名称时优先用快照，不触发回源。
- **健壮性**：未登记的资源类型、非 UUID 的 `resource_id`、导入失败或查询异常均静默降级为空字符串，不影响列表返回。
- **前端**：`AuditLogsView.vue` 列表「资源」列主显名称（超长截断、`a-tooltip` 显示全名），有 `resource_id` 时其次显截断 ID；详情弹窗新增「资源名称」行。i18n 新增 `admin.auditLogs.resource` / `admin.auditLogs.resourceNameLabel`。
- **无迁移**：名称是读时解析（`before_data/after_data` 中历史数据已存在名称字段），因此对存量记录同样生效。

回归测试：后端 `test_list_audit_logs_should_fallback_to_source_table_name`（状态变更回源补全）、`test_list_audit_logs_should_prefer_snapshot_name_over_source_table`（快照优先）、`test_list_audit_logs_should_tolerate_unknown_resource_type`（未登记类型降级），以及 `_extract_resource_name` 的 4 个单测；前端 `AuditLogsView.spec.ts` 覆盖名称展示、名称缺失时回退截断 ID、详情弹窗名称行。

接口契约（路径 / 入参 / 返回字段 / 枚举取值）见 [审计日志 API](../../api/audit-log-api.md)。

