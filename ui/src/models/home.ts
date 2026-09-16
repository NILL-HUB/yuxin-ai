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

export type HomeIntentRecommendedAgent = {
  agent_id: string
  name: string
  description: string
  icon: string
  source_scope: string
  source_type: string
  app_id: string
  pool: string
  match_reason: string
  score: number
}

export type HomeIntentRecommendedTool = {
  source_type: string
  provider_id: string
  tool_name: string
  name: string
  description: string
  tool_pool: string
  reason: string
  match_type: string
}

export type HomeIntentData = {
  intent: string
  confidence: number
  should_ask_continue: boolean
  resume_question: string
  suggested_actions: HomeIntentSuggestedAction[]
  is_default: boolean
  task_plan_summary: HomeTaskPlanSummary
  synthesis_summary: HomeSynthesisSummary
  matched_agent_pools: string[]
  matched_tool_pools: string[]
  recommended_agents: HomeIntentRecommendedAgent[]
  recommended_tools: HomeIntentRecommendedTool[]
}

export type GetHomeIntentResponse = BaseResponse<HomeIntentData>
