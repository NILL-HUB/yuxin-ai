export type AdminRoutingLogFilters = {
  current_page: number
  page_size: number
  account_id?: string
  status?: string
  agent_id?: string
  agent_pool?: string
  tool_name?: string
  tool_pool?: string
  model_id?: string
  key_id?: string
  start_at?: string
  end_at?: string
}

type RoutingLogJsonValue = string | number | boolean | null | undefined

type RoutingLogJsonObject = Record<string, RoutingLogJsonValue>

export interface RoutingDecisionJson {
  execution_mode?: string
  intent?: string
  complexity?: string
  risk_level?: string
  recommended_model_tier?: string
  cost_policy?: {
    allowed?: boolean
    reason?: string
  }
  [key: string]: RoutingLogJsonValue
}

export type AdminRoutingLogRecord = {
  id: string
  account_id: string
  user_query?: string
  task_classification: RoutingLogJsonObject
  routing_decision: RoutingDecisionJson
  agent_candidates: RoutingLogJsonObject[]
  filtered_out_agents: RoutingLogJsonObject[]
  tool_candidates: RoutingLogJsonObject[]
  filtered_out_tools: RoutingLogJsonObject[]
  billing_events: RoutingLogJsonObject[]
  model_selection: RoutingLogJsonObject
  agent_pool_hits: RoutingLogJsonObject[]
  tool_pool_hits: RoutingLogJsonObject[]
  knowledge_hits: RoutingLogJsonObject[]
  key_usage: RoutingLogJsonObject
  cost_summary: RoutingLogJsonObject
  latency_ms: number
  fallback_reason: string
  redaction_enabled: boolean
  retention_expires_at?: number | null
  status: string
  created_at: number
}

export type AdminRoutingLogSummary = {
  total_count: number
  success_count: number
  fallback_count: number
  total_credits: number
  avg_latency_ms: number
  agent_pool_hit_rate: number
  tool_pool_hit_rate: number
}

export type AdminRoutingLogListResponse = {
  list: AdminRoutingLogRecord[]
  paginator: Record<string, unknown>
  summary: AdminRoutingLogSummary
}
