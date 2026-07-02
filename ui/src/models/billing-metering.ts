import type { BillingEventType } from '@/models/orchestration'

export type BillingUsageEvent = {
  event: BillingEventType
  source_type: string
  source_name: string
  delta_credits: number
  total_credits: number
  reason: string
  metadata?: Record<string, unknown>
}
