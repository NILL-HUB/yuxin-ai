import { get, post } from '@/utils/request'
import {
  type AdminDistributionOverviewResponse,
  type AdminDistributionRelationListResponse,
  type CommissionListResponse,
} from '@/models/distribution'
import {
  type AdminOrderListResponse,
  type AdminOrderResponse,
  type RefundListResponse,
  type WithdrawalListResponse,
  type WithdrawalResponse,
} from '@/models/commerce'

export const getDistributionOverview = async () => {
  const response = await get<AdminDistributionOverviewResponse>('/admin/distribution/overview')
  return response.data
}

export const listDistributionRelations = async (params: {
  current_page: number
  page_size: number
  inviter_id?: string
}) => {
  const response = await get<AdminDistributionRelationListResponse>('/admin/distribution/relations', { params })
  return response.data
}

export const listDistributionCommissions = async (params: {
  user_id?: string
  current_page: number
  page_size: number
}) => {
  const cleanParams = Object.fromEntries(
    Object.entries(params).filter(([, value]) => value !== '' && value !== undefined && value !== null),
  )
  const response = await get<CommissionListResponse>('/admin/distribution/commissions', { params: cleanParams })
  return response.data
}

export const listAdminOrders = async (params: {
  status?: string
  order_source?: string
  account_id?: string
  current_page: number
  page_size: number
}) => {
  const response = await get<AdminOrderListResponse>('/admin/orders', { params })
  return response.data
}

export const getAdminOrderDetail = async (orderId: string) => {
  const response = await get<AdminOrderResponse>(`/admin/orders/${orderId}`)
  return response.data
}

export const closeAdminOrder = async (orderId: string) => {
  const response = await post<AdminOrderResponse>(`/admin/orders/${orderId}/close`)
  return response.data
}

export const listAdminWithdrawals = async (params: { status?: string; current_page: number; page_size: number }) => {
  const response = await get<WithdrawalListResponse>('/admin/withdrawals', { params })
  return response.data
}

export const reviewWithdrawal = async (withdrawId: string, action: 'approve' | 'reject', note: string) => {
  const response = await post<WithdrawalResponse>(`/admin/withdrawals/${withdrawId}/${action}`, { body: { note } })
  return response.data
}

export const listAdminRefunds = async (params: { status?: string; current_page: number; page_size: number }) => {
  const response = await get<RefundListResponse>('/admin/refunds', { params })
  return response.data
}

export const reviewRefund = async (refundId: string, action: 'approve' | 'reject', note: string) => {
  const response = await post<{ code: string; message: string; data: { id: string; status: string } }>(
    `/admin/refunds/${refundId}/${action}`,
    { body: { note } },
  )
  return response.data
}