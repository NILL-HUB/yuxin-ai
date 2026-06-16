export type BillingUsageEvent = {
  event: 'billing_started' | 'billing_delta' | 'billing_summary' | 'billing_cancelled' | 'billing_final'
  source_type: string
  source_name: string
  delta_credits: number
  total_credits: number
  reason: string
  metadata?: Record<string, unknown>
}
