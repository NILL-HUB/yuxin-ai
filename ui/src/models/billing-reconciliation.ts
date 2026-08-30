import { type BaseResponse } from '@/models/base'

export interface BillingReconciliation {
  id: string
  task_id: string
  account_id: string
  estimated_credits: number
  actual_credits: number
  cost_credits: number
  diff_credits: number
  status: string
  alert_flags: string[]
  created_at: number
}

export interface MarginSummaryItem {
  model_name: string
  calls: number
  actual: number
  cost: number
  margin: number
}

export interface MarginTierItem {
  tier: string
  calls: number
  actual_credits: number
  cost_credits: number
  margin_credits: number
}

export interface MarginSummary {
  list: MarginSummaryItem[]
  total_margin: number
  total_actual: number
  overall: {
    actual_credits: number
    cost_credits: number
    margin_credits: number
  }
  by_tier: MarginTierItem[]
  cached_input_tokens_total: number
}

export type AdminReconciliationListResponse = BaseResponse<{
  list: BillingReconciliation[]
  paginator: {
    total_record: number
    total_page: number
    current_page: number
    page_size: number
  }
}>

export type MarginSummaryResponse = BaseResponse<MarginSummary>