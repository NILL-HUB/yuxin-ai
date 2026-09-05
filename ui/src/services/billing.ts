import { get, post } from '@/utils/request'
import { type MembershipSummaryResponse, type RedeemRecordListResponse } from '@/models/billing'

export const redeemCode = (code: string) => {
  return post('/redeem-codes/redeem', { body: { code } })
}

export const getMembershipSummary = async () => {
  const response = await get<MembershipSummaryResponse>('/membership/summary')
  return response.data
}

export const getRedeemRecords = async () => {
  const response = await get<RedeemRecordListResponse>('/membership/redeem-records')
  return response.data
}
