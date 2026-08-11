import { get, post } from '@/utils/request'
import type { BaseResponse } from '@/models/base'
import type {
  AdminRoutingOptimizationSuggestion,
  AdminRoutingQualityFeedback,
  AdminRoutingQualityMetrics,
  CreateAdminRoutingQualityFeedbackRequest,
} from '@/models/admin-routing-quality'

export const createAdminRoutingQualityFeedback = async (
  data: CreateAdminRoutingQualityFeedbackRequest,
): Promise<AdminRoutingQualityFeedback> => {
  const response = await post<BaseResponse<AdminRoutingQualityFeedback>>(
    '/admin/routing-quality/feedback',
    {
    body: data,
    },
  )
  return response.data
}

export const listAdminRoutingQualityFeedback = async (params?: {
  routing_log_id?: string
  source?: string
  page?: number
  page_size?: number
}): Promise<AdminRoutingQualityFeedback[]> => {
  const response = await get<BaseResponse<AdminRoutingQualityFeedback[]>>(
    '/admin/routing-quality/feedback',
    {
    params,
    },
  )
  return response.data
}

export const getAdminRoutingQualityMetrics = async (): Promise<AdminRoutingQualityMetrics> => {
  const response = await get<BaseResponse<AdminRoutingQualityMetrics>>(
    '/admin/routing-quality/metrics',
  )
  return response.data
}

export const listAdminRoutingQualitySuggestions = async (): Promise<
  AdminRoutingOptimizationSuggestion[]
> => {
  const response = await get<BaseResponse<AdminRoutingOptimizationSuggestion[]>>(
    '/admin/routing-quality/suggestions',
  )
  return response.data
}
