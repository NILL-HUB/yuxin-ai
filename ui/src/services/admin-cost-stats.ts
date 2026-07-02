import { get } from '@/utils/request'
import type {
  CostStatsByDimension,
  CostStatsByDimension as DimensionResponse,
  CostStatsDimensionFilters,
  CostStatsFilters,
  CostStatsOverview,
  CostStatsTimeseries,
  CostStatsTimeseriesFilters,
} from '@/models/admin-cost-stats'

type ApiResponse<T> = {
  code: string
  message: string
  data: T
}

export const getCostStatsOverview = async (params: CostStatsFilters) => {
  const resp = await get<ApiResponse<CostStatsOverview>>('/admin/cost-stats/overview', { params })
  return resp.data
}

export const getCostStatsByDimension = async (params: CostStatsDimensionFilters) => {
  const resp = await get<ApiResponse<DimensionResponse>>('/admin/cost-stats/by-dimension', { params })
  return resp.data
}

export const getCostStatsTimeseries = async (params: CostStatsTimeseriesFilters) => {
  const resp = await get<ApiResponse<CostStatsTimeseries>>('/admin/cost-stats/timeseries', { params })
  return resp.data
}
