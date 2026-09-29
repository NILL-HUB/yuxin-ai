import type { BasePaginatorRequest, BasePaginatorResponse, BaseResponse } from '@/models/base'

export type McpCategory = {
  id: string
  name: string
  priority: number
  background: string
}

export type McpToolInput = {
  name: string
  type: string
  required: boolean
  description: string
}

export type McpTool = {
  name: string
  label: string
  description: string
  inputs: McpToolInput[]
}

export type McpBinding = {
  name: string
  description: string
  transport: string
  url: string
  command: string
  enabled: boolean
  headers: { key: string; value: string }[]
  tool_names: string[]
  timeout_seconds: number
  args: string[]
  env: Record<string, string>
  protocol?: string
  tool_schema?: Record<string, unknown>
  provider_key?: string
  source_type?: string
  source_key?: string
  source_url?: string
  label?: string
  icon?: string
  category?: string
}

export type McpProvider = {
  id: string
  provider_key: string
  name: string
  label: string
  icon: string
  background: string
  description: string
  category: string
  transport: string
  url: string
  command: string
  headers: { key: string; value: string }[]
  tool_names: string[]
  args: string[]
  env: Record<string, string>
  tool_schema: Record<string, unknown>
  timeout_seconds: number
  source_type: string
  source_key: string
  source_url: string
  creator_name: string
  creator_avatar: string
  is_public: boolean
  is_bindable: boolean
  bind_reason: string
  published_at: number
  created_at: number
  updated_at: number
  tool_count: number
  tools: McpTool[]
  binding: McpBinding
  task_keywords: string[]
  /** 工具同步状态：ready/empty/failed/not_configured/''（未同步） */
  sync_status: string
  /** 工具同步失败原因（sync_status=failed/not_configured 时有值） */
  sync_error: string
  /** 最近一次同步时间戳（秒） */
  last_synced_at: number | null
  /** 详情页实时探测工具时的错误（区分"无工具"与"探测失败"） */
  tool_sync_error: string
}

export type GetMcpProvidersWithPageRequest = BasePaginatorRequest & {
  search_word?: string
  category?: string
}

export type CreateMcpProviderRequest = {
  name: string
  label?: string
  icon?: string
  description: string
  category?: string
  transport?: string
  url?: string
  command?: string
  headers?: { key: string; value: string }[]
  tool_names?: string[]
  args?: string[]
  env?: Record<string, string>
  tool_schema?: Record<string, unknown>
  timeout_seconds?: number
  task_keywords?: string[]
}

export type UpdateMcpProviderRequest = CreateMcpProviderRequest

export type GetMcpCategoriesResponse = BaseResponse<{
  categories: McpCategory[]
}>

export type GetMcpProvidersWithPageResponse = BasePaginatorResponse<McpProvider>

export type GetMcpProviderResponse = BaseResponse<McpProvider>

