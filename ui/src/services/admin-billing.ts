import { get, post } from '@/utils/request'
import {
  type BillingStatus,
  type GenerateRedeemCodesRequest,
  type GenerateRedeemCodesResponse,
  type PlanListRequest,
  type PlanListResponse,
  type PlanPayload,
  type PlanResponse,
  type RedeemCodeBatchListResponse,
  type RedeemCodeListRequest,
  type RedeemCodeListResponse,
} from '@/models/billing'

export const listPlans = (params: PlanListRequest) => {
  return get<PlanListResponse['data']>('/admin/plans', { params })
}

export const createPlan = (payload: PlanPayload) => {
  return post<PlanResponse['data']>('/admin/plans', { body: payload })
}

export const updatePlan = (id: string, payload: PlanPayload) => {
  return post<PlanResponse['data']>(`/admin/plans/${id}`, { body: payload })
}

export const setPlanStatus = (id: string, status: BillingStatus) => {
  return post<PlanResponse['data']>(`/admin/plans/${id}/status`, { body: { status } })
}

export const generateRedeemCodes = (payload: GenerateRedeemCodesRequest) => {
  return post<GenerateRedeemCodesResponse['data']>('/admin/redeem-code-batches', { body: payload })
}

export const listRedeemCodeBatches = (params: { keyword?: string; current_page: number; page_size: number }) => {
  return get<RedeemCodeBatchListResponse['data']>('/admin/redeem-code-batches', { params })
}

export const listRedeemCodes = (params: RedeemCodeListRequest) => {
  return get<RedeemCodeListResponse['data']>('/admin/redeem-codes', { params })
}

export const disableRedeemCode = (codeId: string) => {
  return post(`/admin/redeem-codes/${codeId}/disable`)
}

export const disableRedeemCodeBatch = (batchId: string) => {
  return post(`/admin/redeem-code-batches/${batchId}/disable`)
}
