export type CostStatsOverview = {
  total_credits: number
  total_requests: number
  avg_cost_per_request: number
  total_input_tokens: number
  total_output_tokens: number
}

export type CostStatsDimensionItem = {
  name: string
  total_credits: number
  request_count: number
  avg_credits: number
  percentage: number
}

export type CostStatsByDimension = {
  dimension: string
  items: CostStatsDimensionItem[]
  total_credits: number
}

export type CostStatsTimeseriesPoint = {
  timestamp: number
  total_credits: number
  request_count: number
}

export type CostStatsTimeseries = {
  granularity: string
  points: CostStatsTimeseriesPoint[]
}

export type CostStatsFilters = {
  start_at: string
  end_at: string
}

export type CostStatsDimensionFilters = {
  dimension: string
  start_at: string
  end_at: string
  limit: number
}

export type CostStatsTimeseriesFilters = {
  granularity: string
  start_at: string
  end_at: string
}
