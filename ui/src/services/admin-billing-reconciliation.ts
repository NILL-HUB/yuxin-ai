import { get } from '@/utils/request'
import type { AdminReconciliationListResponse, MarginSummaryResponse } from '@/models/billing-reconciliation'

export const listReconciliations = async (params: { alert?: string; current_page: number; page_size: number }) => {
  const response = await get<AdminReconciliationListResponse>('/admin/billing-reconciliations', { params })
  return response.data
}

export const getMarginSummary = async () => {
  const response = await get<MarginSummaryResponse>('/admin/billing-reconciliations/margin')
  return response.data
}