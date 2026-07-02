import type { BaseResponse } from '@/models/base'
import type { ExecutionMode } from '@/models/orchestration'

export type HomeTaskPlanSummaryItem = {
  task_id: string
  title: string
  agent_pool: string
  execution_order: number
  risk_level: string
}

export type HomeTaskPlanSummary = {
  execution_mode: ExecutionMode
  reason: string
  task_count: number
  items: HomeTaskPlanSummaryItem[]
}

export type HomeSynthesisSummary = {
  final_answer: string
  summary: string
  confidence: number
  visible_sources: string[]
  user_warnings: string[]
}

export type HomeIntentSuggestedAction = {
  label: string
  action: string
  icon: string
}

export type HomeIntentData = {
  intent: string
  confidence: number
  suggested_actions: HomeIntentSuggestedAction[]
  is_default: boolean
  task_plan_summary: HomeTaskPlanSummary
  synthesis_summary: HomeSynthesisSummary
}

export type GetHomeIntentResponse = BaseResponse<HomeIntentData>
