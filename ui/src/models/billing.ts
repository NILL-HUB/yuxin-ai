import { type BasePaginatorResponse, type BaseResponse } from '@/models/base'

export type BillingStatus = 'active' | 'disabled'
export type RedeemCodeStatus = '' | 'unused' | 'used' | 'disabled' | 'expired'
export type EntitlementValueType = 'string' | 'number' | 'decimal' | 'boolean' | 'json'

export type PlanEntitlement = {
  id?: string
  feature_key: string
  feature_value: string
  value_type: EntitlementValueType
  parsed_value?: unknown
}

export type Plan = {
  id: string
  code: string
  name: string
  description: string
  duration_days: number
  grant_token_credits: number
  price: string
  status: BillingStatus
  sort_order: number
  created_at: number | null
  updated_at: number | null
  entitlements?: PlanEntitlement[]
}

export type PlanPayload = Partial<Omit<Plan, 'id' | 'created_at' | 'updated_at' | 'entitlements'>> & {
  entitlements?: PlanEntitlement[]
}

export type PlanListRequest = {
  keyword?: string
  status?: '' | BillingStatus
  current_page: number
  page_size: number
}

export type RedeemCodeBatch = {
  id: string
  name: string
  plan_id: string
  quantity: number
  status?: string
  expires_at: number | null
  disabled_at?: number | null
  created_by: string | null
  created_at: number | null
}

export type RedeemCodeListRequest = {
  batch_id?: string
  status?: RedeemCodeStatus
  code_keyword?: string
  current_page: number
  page_size: number
}

export type RedeemCodeRecord = {
  id: string
  batch_id: string | null
  plan_id: string
  code_mask: string
  status: RedeemCodeStatus
  redeemed_by: string | null
  redeemed_at: number | null
  expires_at: number | null
  disabled_at: number | null
  created_at: number | null
}

export type GenerateRedeemCodesRequest = {
  name: string
  plan_id: string
  quantity: number
  expires_at?: number
}

export type GeneratedRedeemCode = {
  plain_code: string
  code_mask: string
}

export type MembershipPlan = {
  id: string
  code: string
  name: string
  duration_days: number
  grant_token_credits: number
}

export type Membership = {
  id: string
  status: string
  started_at: number | null
  expires_at: number | null
  source: string
  source_id: string | null
  plan: MembershipPlan | null
}

export type CreditAccount = {
  account_id: string
  balance: number
  total_granted: number
  total_consumed: number
}

export type CreditTransaction = {
  id: string
  amount: number
  balance_after: number
  transaction_type: string
  source: string
  source_id: string | null
  description: string
  created_at: number | null
}

export type MembershipSummary = {
  membership: Membership | null
  credit_account: CreditAccount
  recent_transactions: CreditTransaction[]
}

export type RedeemRecord = {
  id: string
  code_mask: string
  redeemed_at: number | null
  plan: MembershipPlan | null
  grant_token_credits: number
  membership_expires_at: number | null
}

export type RedeemRecordList = {
  list: RedeemRecord[]
}

export type PlanListResponse = BasePaginatorResponse<Plan>
export type PlanResponse = BaseResponse<Plan>
export type RedeemCodeBatchListResponse = BasePaginatorResponse<RedeemCodeBatch>
export type RedeemCodeListResponse = BasePaginatorResponse<RedeemCodeRecord>
export type GenerateRedeemCodesResponse = BaseResponse<{ batch: RedeemCodeBatch; codes: GeneratedRedeemCode[] }>
export type MembershipSummaryResponse = BaseResponse<MembershipSummary>
export type RedeemRecordListResponse = BaseResponse<RedeemRecordList>
