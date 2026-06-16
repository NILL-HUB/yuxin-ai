export type AdminOrchestrationFlag = {
  code: string
  name: string
  description: string
  enabled: boolean
  risk_level: string
  fallback_behavior: string
  updated_by?: string | null
}

export type UpdateAdminOrchestrationFlagRequest = {
  enabled: boolean
}

export type AdminOrchestrationReleaseCheck = {
  test_status: Record<string, unknown>
  migration_status: Record<string, unknown>
  feature_flags: AdminOrchestrationFlag[]
  security_checklist: Record<string, unknown>
  cost_metrics: Record<string, unknown>
  routing_metrics: Record<string, unknown>
  rollback_plan: {
    primary_action?: string
    fallback_flow?: string
    steps?: string[]
  }
  warnings: string[]
}
