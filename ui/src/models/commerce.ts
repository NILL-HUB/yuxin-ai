import { type BasePaginatorResponse, type BaseResponse } from '@/models/base'

export type PlanType = 'balance' | 'membership' | 'credits'

export type BalanceProfile = {
  balance: number
  recharge_balance: number
  commission_balance: number
  total_withdrawn: number
  total_purchased: number
  high_rate_locked: boolean
  quota_credit: number
  permanent_credit: number
}

export type PurchaseOrder = {
  order_no: string
  plan_id: string
  plan_type: string
  amount: number
  pay_method: string
  order_source: string
  status: string
  transaction_id: string | null
  paid_at: number | null
  created_at: number | null
}

export type AdminPurchaseOrder = PurchaseOrder & {
  id: string
  account_id: string
  user_name?: string | null
  user_email?: string | null
}

export type OrderCreateResult = {
  order: PurchaseOrder
  payment_params: Record<string, unknown> | null
}

export type RefundRecord = {
  id: string
  account_id?: string | null
  user_name?: string | null
  user_email?: string | null
  order_no: string
  plan_type: string
  amount: number
  reason: string
  status: string
  review_note: string
  created_at: number | null
}

export type WithdrawalRecord = {
  id: string
  account_id: string
  user_name?: string | null
  user_email?: string | null
  amount: number
  status: string
  review_note: string
  created_at: number | null
}

export type AutoRenewal = {
  id: string
  plan_id: string
  plan_name: string
  plan_type: string
  pay_method: string
  status: string
  trigger: string
  threshold_percent: number | null
  threshold_days: number | null
  next_renew_at: number | null
  last_renewed_at: number | null
  renew_count: number
  fail_count: number
}

export type CommercePlan = {
  id: string
  code: string
  name: string
  description: string
  plan_type: PlanType
  duration_days: number
  grant_token_credits: number
  price: string
  status: string
  sort_order: number
  auto_renew_threshold_percent: number | null
  auto_renew_threshold_days: number | null
  purchase_limit: number
  purchase_limit_period: 'none' | 'all' | 'day' | 'week' | 'month'
  quota_refresh_period: 'none' | 'cycle'
  auto_renew_default?: boolean
}

export type OrderListResponse = BasePaginatorResponse<PurchaseOrder>
export type OrderCreateResponse = BaseResponse<OrderCreateResult>
export type OrderResponse = BaseResponse<PurchaseOrder>
export type AdminOrderListResponse = BasePaginatorResponse<AdminPurchaseOrder>
export type AdminOrderResponse = BaseResponse<AdminPurchaseOrder>
export type RefundListResponse = BasePaginatorResponse<RefundRecord>
export type RefundCreateResponse = BaseResponse<{ id: string; order_no: string; status: string }>
export type WithdrawalListResponse = BasePaginatorResponse<WithdrawalRecord>
export type WithdrawalResponse = BaseResponse<{
  id: string
  account_id: string
  amount: number
  status: string
  review_note: string
  created_at: number | null
}>
export type AutoRenewalListData = { list: AutoRenewal[] }
export type AutoRenewalListResponse = BaseResponse<AutoRenewalListData>
export type AutoRenewalActionResponse = BaseResponse<{ id: string; status: string }>
export type BalanceProfileResponse = BaseResponse<BalanceProfile>
export type PlanListResponse = BasePaginatorResponse<CommercePlan>