import { type BaseResponse } from '@/models/base'
import { get } from '@/utils/request'

export type ToolInventoryMetadata = {
  tool_pool: string
  tool_tags?: string[]
  capabilities?: string[]
  risk_level: string
  permission_scope: string
  cost_level: string
  health_status: string
  success_rate?: number
  avg_latency?: number
  owner?: string
  knowledge_scope?: string
  tenant_scope?: string
  user_scope?: string
  requires_confirmation?: boolean
  allowed_agent_pools?: string[]
  enabled?: boolean
}

export type ToolInventoryCandidate = {
  id: string
  name: string
  description?: string
  source_type: string
  provider_id?: string
  provider_name?: string
  inputs?: Array<Record<string, unknown>>
  visibility?: string
  enabled?: boolean
  metadata: ToolInventoryMetadata
}

export type FilteredTool = {
  id: string
  name: string
  reason: string
}

export type GetToolInventoryParams = {
  tool_pool?: string
  agent_pool?: string
  budget_level?: string
  risk_level?: string
  allow_confirmation?: boolean
}

export type GetToolInventoryResponse = BaseResponse<{
  candidates: ToolInventoryCandidate[]
  filtered_out_tools: FilteredTool[]
}>

export const getToolInventory = (params: GetToolInventoryParams = {}) => {
  return get<GetToolInventoryResponse['data']>('/tool-inventory', {
    params: {
      ...params,
      allow_confirmation: String(params.allow_confirmation ?? false),
    },
  })
}
