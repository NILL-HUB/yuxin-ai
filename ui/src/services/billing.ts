import { get, post } from '@/utils/request'
import { type MembershipSummaryResponse, type RedeemRecordListResponse } from '@/models/billing'

export const redeemCode = (code: string) => {
  return post('/redeem-codes/redeem', { body: { code } })
}

export const getMembershipSummary = () => {
  return get<MembershipSummaryResponse['data']>('/membership/summary')
}

export const getRedeemRecords = () => {
  return get<RedeemRecordListResponse['data']>('/membership/redeem-records')
}
