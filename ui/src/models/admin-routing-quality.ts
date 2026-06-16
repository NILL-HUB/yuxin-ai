export type AdminRoutingQualityFeedback = {
  id?: string | null
  routing_log_id: string
  source: string
  rating: number
  dimension_scores: Record<string, number>
  comment: string
  metadata: Record<string, unknown>
  created_by?: string | null
  created_at?: string | null
}

export type CreateAdminRoutingQualityFeedbackRequest = {
  routing_log_id: string
  rating: number
  dimension_scores: Record<string, number>
  comment: string
  metadata?: Record<string, unknown>
}

export type AdminRoutingQualityMetrics = {
  total_count: number
  feedback_count: number
  avg_rating: number
  fallback_rate: number
  avg_latency_ms: number
  avg_cost_credits: number
  quality_by_task_type: Record<string, AdminRoutingQualityGroup>
  quality_by_agent_pool: Record<string, AdminRoutingQualityGroup>
  quality_by_tool_pool: Record<string, AdminRoutingQualityGroup>
  quality_by_model: Record<string, AdminRoutingQualityGroup>
}

export type AdminRoutingQualityGroup = {
  count: number
  avg_rating: number
  avg_cost_credits?: number
}

export type AdminRoutingOptimizationSuggestion = {
  target_type: string
  target_id: string
  suggestion_type: string
  severity: string
  reason: string
  evidence: Record<string, unknown>
  status: string
}
