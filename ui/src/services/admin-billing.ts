import { del, get, post, put } from '@/utils/request'
import {
  type BillingConfigPayload,
  type BillingConfigResponse,
  type BillingStatus,
  type GenerateRedeemCodesRequest,
  type GenerateRedeemCodesResponse,
  type PlanListRequest,
  type PlanListResponse,
  type PlanPayload,
  type PlanResponse,
  type PlainCodeResponse,
  type RedeemCodeBatchListResponse,
  type RedeemCodeListRequest,
  type RedeemCodeListResponse,
} from '@/models/billing'

export const listPlans = async (params: PlanListRequest) => {
  const response = await get<PlanListResponse>('/admin/plans', { params })
  return response.data
}

export const getBillingConfig = async (code?: string) => {
  const response = await get<BillingConfigResponse>('/admin/billing-config', { params: code ? { code } : {} })
  return response.data
}

export const updateBillingConfig = async (payload: BillingConfigPayload) => {
  const response = await put<BillingConfigResponse>('/admin/billing-config', { body: payload })
  return response.data
}

export const createPlan = async (payload: PlanPayload) => {
  const response = await post<PlanResponse>(`/admin/plans`, { body: payload })
  return response.data
}

export const updatePlan = async (id: string, payload: PlanPayload) => {
  const response = await post<PlanResponse>(`/admin/plans/${id}`, { body: payload })
  return response.data
}

export const setPlanStatus = async (id: string, status: BillingStatus) => {
  const response = await post<PlanResponse>(`/admin/plans/${id}/status`, { body: { status } })
  return response.data
}

export const deletePlan = async (id: string) => {
  const response = await del<PlanResponse>(`/admin/plans/${id}`)
  return response.data
}

export const generateRedeemCodes = async (payload: GenerateRedeemCodesRequest) => {
  const response = await post<GenerateRedeemCodesResponse>(`/admin/redeem-code-batches`, { body: payload })
  return response.data
}

export const listRedeemCodeBatches = async (params: { keyword?: string; current_page: number; page_size: number }) => {
  const response = await get<RedeemCodeBatchListResponse>('/admin/redeem-code-batches', { params })
  return response.data
}

export const listRedeemCodes = async (params: RedeemCodeListRequest) => {
  const response = await get<RedeemCodeListResponse>('/admin/redeem-codes', { params })
  return response.data
}

export const disableRedeemCode = async (codeId: string) => {
  await post(`/admin/redeem-codes/${codeId}/disable`)
}

export const getRedeemCodePlain = async (codeId: string) => {
  const response = await get<PlainCodeResponse>(`/admin/redeem-codes/${codeId}/plain`)
  return response.data
}

export const disableRedeemCodeBatch = async (batchId: string) => {
  await post(`/admin/redeem-code-batches/${batchId}/disable`)
}