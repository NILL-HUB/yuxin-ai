/**
 * 编排相关共享类型定义
 * 与后端 internal/entity/orchestrator_entity.py 对齐
 */

/** 模型档位 */
export type ModelTier = 'cheap' | 'standard' | 'strong'

/** 风险等级 */
export type RiskLevel = 'safe' | 'medium' | 'high' | 'unknown'

/** 执行模式 */
export type ExecutionMode =
  | 'direct_answer'
  | 'single_agent'
  | 'single_agent_with_tools'
  | 'multi_agent'
  | 'multi_agent_parallel'
  | 'multi_agent_sequential'
  | 'deep_thinking'
  | 'reject_or_confirm'

/** 计费事件类型 */
export type BillingEventType =
  | 'billing_started'
  | 'billing_delta'
  | 'billing_summary'
  | 'billing_cancelled'
  | 'billing_final'

/** 成本策略 */
export type CostPolicy = {
  allowed: boolean
  model_tier: ModelTier
  max_agent_count: number
  max_tool_count: number
  deep_thinking: boolean
  reason: string
}

/** 路由决策 */
export interface RoutingDecision {
  intent: string
  complexity: string
  execution_mode: ExecutionMode
  needs_tools: boolean
  needs_agent: boolean
  needs_multi_agent: boolean
  needs_deep_thinking: boolean
  recommended_model_tier: ModelTier
  risk_level: RiskLevel
  reason: string
  agent_subset?: Record<string, unknown> | null
  tool_subset?: Record<string, unknown> | null
  cost_policy?: CostPolicy | null
  billing_events?: Record<string, unknown>[]
  task_plan_summary?: Record<string, unknown> | null
  synthesis_summary?: Record<string, unknown> | null
}

/** 升级策略配置 */
export interface EscalationPolicy {
  token_escalation_threshold: number
  balance_downgrade_threshold: number
  complexity_escalation: Record<string, ModelTier>
  budget_downgrade_map: Record<string, ModelTier>
}

/** SSE 事件载荷 - agent_thought */
export interface AgentThoughtPayload {
  id: string
  thought: string
  observation: string
  answer: string
  conversation_id: string
  message_id: string
  latency: number
  total_token_count: number
}

/** SSE 事件载荷 - agent_message */
export interface AgentMessagePayload {
  answer: string
  id: string
  conversation_id: string
  message_id: string
}

/** SSE 事件载荷 - orchestrator_routing */
export interface OrchestratorRoutingPayload {
  intent: string
  execution_mode: ExecutionMode
  complexity: string
  recommended_model_tier: ModelTier
  risk_level: RiskLevel
  reason: string
}

/** SSE 事件载荷 - orchestrator_reject */
export interface OrchestratorRejectPayload {
  reason: string
  message: string
  conversation_id?: string
  message_id?: string
}
