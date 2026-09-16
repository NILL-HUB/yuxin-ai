import { type BasePaginatorResponse, type BaseResponse } from '@/models/base'

export type DistributionSuperior = {
  id: string
  name: string
}

export type MyDistribution = {
  referral_code: string
  share_url: string
  superior: DistributionSuperior | null
  subordinate_count: number
  high_rate_locked: boolean
  commission_rate: string
}

export type DistributionSubordinate = {
  id: string
  name: string
  email?: string | null
  bound_at: number | null
  source: string
}

export type DistributionCommission = {
  id: string
  account_id?: string
  account_name?: string | null
  buyer_name?: string | null
  amount: number
  rate: number | null
  source: string
  source_id: string | null
  description: string
  created_at: number | null
}

export type RegisterInviteInfo = {
  valid: boolean
  required: boolean
  inviter_name: string
}

export type MyDistributionResponse = BaseResponse<MyDistribution>
export type SubordinateListResponse = BasePaginatorResponse<DistributionSubordinate>
export type CommissionListResponse = BasePaginatorResponse<DistributionCommission>
export type RegisterInviteInfoResponse = BaseResponse<RegisterInviteInfo>