import { get, post } from '@/utils/request'
import {
  type AutoRenewalActionResponse,
  type AutoRenewalListResponse,
  type OrderCreateResponse,
  type OrderListResponse,
  type OrderResponse,
  type PlanListResponse,
  type RefundCreateResponse,
  type RefundListResponse,
} from '@/models/commerce'

export const listPlans = async (params: { current_page: number; page_size: number; status?: string }) => {
  const response = await get<PlanListResponse>('/plans', { params })
  return response.data
}

export const createOrder = async (planId: string, payMethod: string) => {
  const response = await post<OrderCreateResponse>('/orders', { body: { plan_id: planId, pay_method: payMethod } })
  return response.data
}

export const listOrders = async (params: { current_page: number; page_size: number }) => {
  const response = await get<OrderListResponse>('/orders', { params })
  return response.data
}

export const getOrderDetail = async (orderNo: string) => {
  const response = await get<OrderResponse>(`/orders/${orderNo}`)
  return response.data
}

export const cancelOrder = async (orderNo: string) => {
  const response = await post<OrderResponse>(`/orders/${orderNo}/cancel`)
  return response.data
}

export const mockPaidOrder = async (orderNo: string) => {
  const response = await post<OrderResponse>(`/orders/${orderNo}/mock-paid`)
  return response.data
}

export const createRefund = async (orderNo: string, reason: string) => {
  const response = await post<RefundCreateResponse>('/refunds', { body: { order_no: orderNo, reason } })
  return response.data
}

export const listRefunds = async (params: { current_page: number; page_size: number }) => {
  const response = await get<RefundListResponse>('/refunds', { params })
  return response.data
}

export const listAutoRenewals = async () => {
  const response = await get<AutoRenewalListResponse>('/auto-renewals')
  return response.data
}

export const createAutoRenewal = async (planId: string, payMethod: string) => {
  const response = await post<AutoRenewalActionResponse>('/auto-renewals', { body: { plan_id: planId, pay_method: payMethod } })
  return response.data
}

export const setAutoRenewalStatus = async (renewalId: string, action: 'pause' | 'resume' | 'cancel') => {
  const response = await post<AutoRenewalActionResponse>(`/auto-renewals/${renewalId}/${action}`)
  return response.data
}