import { get } from '@/utils/request'
import type { BaseResponse } from '@/models/base'
import type {
  AdminRoutingLogFilters,
  AdminRoutingLogListResponse,
  RoutingLogDistributionResponse,
  RoutingLogStatsOverview,
  RoutingLogTrendResponse,
} from '@/models/admin-routing-log'

export const listAdminRoutingLogs = async (
  params: AdminRoutingLogFilters,
): Promise<AdminRoutingLogListResponse> => {
  const response = await get<BaseResponse<AdminRoutingLogListResponse>>(
    '/admin/routing-logs',
    { params },
  )
  return response.data
}

export type RoutingLogStatsParams = {
  start_at?: string
  end_at?: string
  status?: string
  invoke_from?: string
}

export const getRoutingLogStats = async (
  params: RoutingLogStatsParams = {},
): Promise<RoutingLogStatsOverview> => {
  const response = await get<BaseResponse<RoutingLogStatsOverview>>(
    '/admin/routing-logs/stats',
    { params },
  )
  return response.data
}

export type RoutingLogTrendParams = {
  start_at?: string
  end_at?: string
  granularity?: 'day' | 'hour'
  status?: string
  invoke_from?: string
}

export const getRoutingLogTrend = async (
  params: RoutingLogTrendParams = {},
): Promise<RoutingLogTrendResponse> => {
  const response = await get<BaseResponse<RoutingLogTrendResponse>>(
    '/admin/routing-logs/trend',
    { params },
  )
  return response.data
}

export type RoutingLogDistributionParams = {
  start_at?: string
  end_at?: string
  dimension?: string
  limit?: number
}

export const getRoutingLogDistribution = async (
  params: RoutingLogDistributionParams = {},
): Promise<RoutingLogDistributionResponse> => {
  const response = await get<BaseResponse<RoutingLogDistributionResponse>>(
    '/admin/routing-logs/distribution',
    { params },
  )
  return response.data
}
