import { get, post } from '@/utils/request'
import {
  type BalanceProfileResponse,
  type WithdrawalListResponse,
  type WithdrawalResponse,
} from '@/models/commerce'

export const getBalanceProfile = async () => {
  const response = await get<BalanceProfileResponse>('/account/balance')
  return response.data
}

export const createWithdrawal = async (amount: number) => {
  const response = await post<WithdrawalResponse>('/balance/withdraw', { body: { amount: String(amount) } })
  return response.data
}

export const listWithdrawals = async (params: { current_page: number; page_size: number }) => {
  const response = await get<WithdrawalListResponse>('/balance/withdrawals', { params })
  return response.data
}

export const cancelWithdrawal = async (withdrawId: string) => {
  const response = await post<WithdrawalResponse>(`/balance/withdrawals/${withdrawId}/cancel`)
  return response.data
}