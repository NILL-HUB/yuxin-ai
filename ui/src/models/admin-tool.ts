import type { BasePaginatorResponse, BasePaginatorRequest } from '@/models/base'

export type AdminToolRecord = {
  id: string
  tool_id: string
  tool_name: string
  source_type: string
  provider_id: string
  risk_level: string
  visibility: string
  allowed_pools: string[]
  enabled: boolean
  max_invocations_per_request: number
  cooldown_seconds: number
  require_confirmation: boolean
  description: string
  created_at?: number
  updated_at?: number
}

export type GetAdminToolsParams = BasePaginatorRequest & {
  keyword?: string
}

export type AdminToolsPageData = BasePaginatorResponse<AdminToolRecord>['data']
