import { get, post } from '@/utils/request'
import type {
  AdminRoutingOptimizationSuggestion,
  AdminRoutingQualityFeedback,
  AdminRoutingQualityMetrics,
  CreateAdminRoutingQualityFeedbackRequest,
} from '@/models/admin-routing-quality'

export const createAdminRoutingQualityFeedback = (
  data: CreateAdminRoutingQualityFeedbackRequest,
) => {
  return post<AdminRoutingQualityFeedback>('/admin/routing-quality/feedback', {
    body: data,
  })
}

export const listAdminRoutingQualityFeedback = (params?: {
  routing_log_id?: string
  source?: string
  page?: number
  page_size?: number
}) => {
  return get<AdminRoutingQualityFeedback[]>('/admin/routing-quality/feedback', {
    params,
  })
}

export const getAdminRoutingQualityMetrics = () => {
  return get<AdminRoutingQualityMetrics>('/admin/routing-quality/metrics')
}

export const listAdminRoutingQualitySuggestions = () => {
  return get<AdminRoutingOptimizationSuggestion[]>(
    '/admin/routing-quality/suggestions',
  )
}
